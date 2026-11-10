"""Propose and test behavioral hypotheses from real successful/failed traces.

The planner never executes observed commands. It predicts independently checked
outcomes from their action sequences in the bounded expression interpreter.
Training and held-out outcomes remain distinct; neither earns live task credit.
"""

from __future__ import annotations

from collections import defaultdict
import json

from .candidates import EXCLUDED_SOURCES, observed_action
from .receipts import digest
from .signals import reward, tool_signals


def observed_case(runtime, tenant, episode):
    if (episode.get("status") != "resolved" or not episode.get("source_cids")
            or not runtime._sources_live(tenant, episode["source_cids"], episode.get("user_id"))):
        return None
    sources = [runtime.engine.get_evidence(tenant, cid) for cid in episode["source_cids"]]
    sources = [source for source in sources if source and source.actor == "tool"]
    actions, checks = [], []
    for event in episode.get("tool_events", []):
        if event.get("source") in EXCLUDED_SOURCES:
            continue
        # Observed normalized events have immutable copies in the tool ledger.
        # Require that retained JSON actually contains the event, not just its
        # freely repeatable success text or a model's summary of the command.
        grounded = False
        action = observed_action(event)
        retained = str(event.get("output") or event.get("evidence") or "")
        if action and action != event.get("name"):
            retained = action + ("\n" + retained if retained else "")
        for field in ("expected_steps", "corrective_steps", "tested_steps"):
            steps = event.get(field)
            if isinstance(steps, list) and all(isinstance(step, str) for step in steps):
                retained += "\n" + "\n".join(steps)
        for source in sources:
            if retained and source.content == retained:
                grounded = True
                break
            try:
                stored = json.loads(source.content)
            except (ValueError, TypeError):
                continue
            if event == stored or isinstance(stored, list) and event in stored:
                grounded = True
                break
            if isinstance(stored, dict) and event in stored.get("tool_events", []):
                grounded = True
                break
        if not grounded:
            continue
        event_checks = [signal for signal in tool_signals([event]) if signal["kind"] in {"tests", "verifier"}]
        if action and (event.get("command") is not None or event.get("arguments") is not None):
            actions.append(action)
        checks.extend(event_checks)
    value = reward(checks)
    if not actions or value is None or value == 0:
        return None
    return {"episode_id": episode["id"], "input": {"actions": actions}, "expected": value > 0}


def split_cases(cases):
    """Keep at least one independent example of each label out of planning."""
    groups = defaultdict(list)
    for case in cases:
        groups[case["expected"]].append(case)
    if any(len(groups[label]) < 2 for label in (True, False)):
        return None
    result = []
    for label in (False, True):
        rows = sorted(groups[label], key=lambda row: digest(row["episode_id"]))
        # Bound execution and retain balanced train/heldout partitions.
        for index, row in enumerate(rows[:16]):
            result.append({**row, "partition": "heldout" if index % 2 else "training"})
    return result


def validate_observed_check(runtime, tenant, hypothesis, state):
    check = hypothesis.get("review_contract", {}).get("sandbox_check", {})
    rows = [state["episodes"].get(key) for key in hypothesis.get("source_episode_ids", [])]
    if not rows or any(row is None or row.get("user_id") != hypothesis.get("user_id")
                       or row.get("tenant_id") != tenant for row in rows):
        return False
    cases = [observed_case(runtime, tenant, row) for row in rows]
    if any(case is None for case in cases):
        return False
    expected = split_cases(cases)
    return bool(expected and check.get("cases") == expected
                and check.get("episode_fingerprints") == {row["id"]: digest(row) for row in rows})


def propose_observed_experiments(runtime, tenant, episodes, *, limit=4):
    from .hypotheses import typed_hypothesis
    from .hypothesis_sandbox import run_experiment
    from .sleep import common_sequence
    groups = defaultdict(list)
    for episode in episodes:
        case = observed_case(runtime, tenant, episode)
        if case:
            groups[(episode.get("user_id"), episode.get("task_class"))].append((episode, case))
    proposals = []
    config = getattr(runtime.engine, "_learning_configuration", {})
    provider = config.get("experiment_proposer")
    reviewed_cohorts = {row.get("cohort_fingerprint") for row in
                        runtime.writer.read(tenant)["policy"].get("hypotheses", {}).values()}
    ordered_groups = sorted(groups.items(), key=lambda pair: max(
        (row.get("created_at", ""), row["id"]) for row, _ in pair[1]), reverse=True)
    for (user, task), observations in ordered_groups:
        # Deduplicate episode IDs; repeated consolidation is not new evidence.
        observations = list({row["id"]: (row, case) for row, case in observations}.values())
        cases = split_cases([case for _, case in observations])
        if not cases:
            continue
        chosen = {case["episode_id"] for case in cases}
        rows = [row for row, _ in observations if row["id"] in chosen]
        cohort = digest([tenant, user, task, {row["id"]: digest(row) for row in rows}])
        if cohort in reviewed_cohorts:
            continue
        training = [case for case in cases if case["partition"] == "training"]
        positives = [case["input"]["actions"] for case in training if case["expected"]]
        common = common_sequence(positives)
        training_ids = {case["episode_id"] for case in training}
        failed_actions = {observed_action(event) for row in rows if row["id"] in training_ids
                          for event in row.get("tool_events", [])
                          if any(signal["value"] < 0 for signal in tool_signals([event]))}
        common = [step for step in common if step not in failed_actions]
        expressions = []
        # Test an observed sequence, then individual operations. No invented
        # command, output label, environment permission or live execution.
        sequences = [common] + [[step] for step in common]
        for steps in sequences[:9]:
            if steps:
                expressions.append((f'contains_sequence(value["actions"], {steps!r})',
                                    "An observed action sequence predicts the independently checked task outcome.", steps))
        if callable(provider):
            try:
                proposed = provider(task_class=task, training_cases=training,
                                    constraints={"kind": "observed_trace_replay", "no_effects": True,
                                                 "allowed_calls": ["contains_sequence", "len", "all", "any"]})
            except Exception:
                proposed = None
            if isinstance(proposed, dict) and isinstance(proposed.get("expression"), str):
                expressions.append((proposed["expression"], str(proposed.get("rationale", ""))[:2000], common))
        for expression, rationale, steps in expressions:
            check = {"version": 1, "kind": "observed_trace_replay", "expression": expression,
                     "cases": cases, "episode_fingerprints": {row["id"]: digest(row) for row in rows}}
            result = run_experiment({**check, "cases": training})
            if result.get("status") != "passed":
                continue
            hypothesis = {"id": "experiment:" + digest([tenant, user, task, expression, check]),
                          "content": rationale, "steps": steps, "sandbox_check": check,
                          "source_cids": sorted({cid for row in rows for cid in row["source_cids"]}),
                          "source_episode_ids": sorted(row["id"] for row in rows), "task_class": task,
                          "user_id": user, "conditions": [], "instruction_authority": "none",
                          "cohort_fingerprint": cohort,
                          "capability_tags": ["data-only", "no-write-authority"],
                          "experiment_scope": "outcome_prediction_not_causal_proof"}
            proposals.append(typed_hypothesis(runtime, tenant, hypothesis, kind="procedural"))
            # One training-selected rule per cohort; don't optimize on heldout.
            break
        if len(proposals) >= limit:
            break
    return proposals
