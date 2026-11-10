"""Resumable source-grounded review of data-only consolidation proposals.

A review establishes what retained evidence actually supports. It is not a
task success signal, a trust upgrade, or permission to execute a procedure.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json

from .receipts import digest

VERSION = 1
KINDS = {"factual", "contradiction", "procedural", "knowledge_maintenance"}
STATES = {"proposed", "queued", "running", "verified", "rejected", "inconclusive"}


def _projection_options(runtime):
    config = getattr(runtime.engine, "_learning_configuration", {})
    return {"semantic_proposer": config.get("semantic_proposer"),
            "timezone": config.get("source_timezone")}


def fingerprint_source(source):
    return digest([source.content, source.created_at.isoformat(), source.metadata,
                   source.access_policy, source.actor, source.source_type, source.trust_tier])


def source_versions(runtime, tenant, hypothesis):
    versions = {}
    for cid in hypothesis.get("source_cids", []):
        if not runtime._sources_live(tenant, [cid], hypothesis.get("user_id")):
            return None
        source = runtime.engine.get_evidence(tenant, cid)
        if source is None:
            return None
        versions[cid] = fingerprint_source(source)
    return versions or None


def typed_hypothesis(runtime, tenant, item, *, kind=None, claim=None):
    row = deepcopy(item)
    kind = kind or ("procedural" if row.get("steps") else "factual")
    contract = {"version": VERSION, "kind": kind, "claim": claim,
                "steps": row.get("steps", []), "task_class": row.get("task_class"),
                "scope": row.get("scope_match"), "parent_revision": row.get("parent_revision"),
                "sandbox_check": row.get("sandbox_check")}
    row.update(review_contract=contract, contract_hash=digest(contract),
               source_versions=source_versions(runtime, tenant, row), status="queued",
               review_attempts=0, review_history=[], reality_class="self_generated",
               shadow_only=True, reward_weight=0.0)
    return row


def _claim(row):
    return {key: deepcopy(row.get(key)) for key in ("subject", "predicate", "object", "scope")}


def factual_proposals(runtime, tenant, episodes, *, limit=8):
    """Queue concrete source repairs, including evidence missed by old extractors."""
    from mnemosyne.memory_formation import preview_direct_user_memory
    rows, seen = [], set()
    for episode in sorted(episodes, key=lambda row: (row["created_at"], row["id"]), reverse=True):
        for cid in episode.get("source_cids", []):
            if cid in seen or not runtime._sources_live(tenant, [cid], episode.get("user_id")):
                continue
            seen.add(cid)
            preview = preview_direct_user_memory(runtime.engine, tenant, cid, **_projection_options(runtime))
            for assertion in preview.get("assertions", []):
                claim = _claim(assertion)
                row = {"id": "review:" + digest([tenant, episode["user_id"], cid, claim]),
                       "content": assertion.get("calibration", {}).get("source_quote", ""),
                       "source_cids": [cid], "source_episode_ids": [episode["id"]],
                       "task_class": episode["task_class"], "user_id": episode["user_id"],
                       "conditions": [], "instruction_authority": "none",
                       "capability_tags": ["data-only", "no-write-authority"]}
                rows.append(typed_hypothesis(runtime, tenant, row, kind="factual", claim=claim))
                if len(rows) >= limit:
                    return rows
    return rows


def experiment_proposals(runtime, tenant, episodes, *, limit=4):
    """Plan observed-trace experiments and discover explicitly supplied fixtures.

    Trace checks predict real external outcomes without executing the commands.
    Explicit expression fixtures remain available for user-supplied algorithms.
    """
    from .experiment_planner import propose_observed_experiments
    proposals = propose_observed_experiments(runtime, tenant, episodes, limit=limit)
    if len(proposals) >= limit:
        return proposals
    seen = set()
    decoder = json.JSONDecoder()
    for episode in episodes:
        for cid in episode.get("source_cids", []):
            if cid in seen or not runtime._sources_live(tenant, [cid], episode.get("user_id")):
                continue
            seen.add(cid)
            source = runtime.engine.get_evidence(tenant, cid)
            if source is None or source.actor == "assistant":
                continue
            content = source.content[:65536]
            starts = [index for index, char in enumerate(content) if char == "{"][:64]
            for start in starts:
                try:
                    check, end = decoder.raw_decode(content[start:])
                except ValueError:
                    continue
                if (not isinstance(check, dict) or check.get("version") != 1
                        or check.get("kind") != "python_expression"
                        or not isinstance(check.get("expression"), str) or not isinstance(check.get("cases"), list)):
                    continue
                check = {"version": 1, "kind": "python_expression", "expression": check["expression"],
                         "cases": check["cases"], "source_cid": cid, "source_quote": content[start:start + end]}
                row = {"id": "experiment:" + digest([tenant, episode["user_id"], cid, check]),
                       "content": check["expression"], "steps": [check["expression"]], "sandbox_check": check,
                       "source_cids": [cid], "source_episode_ids": [episode["id"]],
                       "task_class": episode["task_class"], "user_id": episode["user_id"], "conditions": [],
                       "instruction_authority": "none", "capability_tags": ["data-only", "no-write-authority"]}
                proposals.append(typed_hypothesis(runtime, tenant, row, kind="procedural"))
                if len(proposals) >= limit:
                    return proposals
    return proposals


def _review(runtime, tenant, row, state):
    """Use the semantic writer's own extraction contract, never a self-grade."""
    from mnemosyne.memory_formation import preview_direct_user_memory
    contract = row["review_contract"]
    kind = contract["kind"]
    if kind == "procedural":
        check = contract.get("sandbox_check")
        if check:
            from .hypothesis_sandbox import run_experiment
            if check.get("kind") == "observed_trace_replay":
                from .experiment_planner import validate_observed_check
                if not validate_observed_check(runtime, tenant, row, state):
                    return {"status": "inconclusive", "reason": "observed_cases_no_longer_grounded",
                            "verifier": "observed-trace-review:v1", "support": []}
                outcome = run_experiment(check)
                partitions = {}
                for name in ("training", "heldout"):
                    results = [result for case, result in zip(check["cases"], outcome.get("results", []), strict=False)
                               if case["partition"] == name]
                    partitions[name] = {"passed": sum(result["passed"] for result in results),
                                        "total": len(results)}
                return {"status": "rejected" if outcome["status"] == "failed" else "inconclusive",
                        "reason": "heldout_replay_passed_awaiting_real_outcomes" if outcome["status"] == "passed"
                                  else outcome.get("reason", "heldout_prediction_failed"),
                        "verifier": "observed-trace-review:v1", "support": [], "partitions": partitions,
                        "review_complete": outcome["status"] in {"passed", "failed"},
                        "review_stage": "awaiting_live_outcomes" if outcome["status"] == "passed" else "replay_failed",
                        "sandbox_event": {"name": "hypothesis_sandbox", "source": "tool",
                                          "check_id": "sandbox:" + digest([row["id"], row["contract_hash"], row["source_versions"]]),
                                          "hypothesis_id": row["id"], "contract_hash": row["contract_hash"],
                                          "output": json.dumps(outcome, sort_keys=True), "scope": "observed_trace_prediction",
                                          "passed": outcome.get("passed", 0), "failed": outcome.get("failed", 0)}}
            cid, quote = check.get("source_cid"), check.get("source_quote")
            source = runtime.engine.get_evidence(tenant, cid) if cid in row["source_cids"] else None
            try:
                fixture = json.loads(quote) if isinstance(quote, str) else None
            except ValueError:
                fixture = None
            if (source and quote in source.content and isinstance(fixture, dict)
                    and fixture.get("expression") == check.get("expression")
                    and fixture.get("cases") == check.get("cases")):
                outcome = run_experiment(check)
                check_id = "sandbox:" + digest([row["id"], row["contract_hash"], row["source_versions"]])
                # This is real fixture evidence, not a fabricated live episode.
                # Passing still awaits the unchanged held-out promotion gates.
                return {"status": "rejected" if outcome["status"] == "failed" else "inconclusive",
                        "reason": "sandbox_passed_awaiting_real_outcomes" if outcome["status"] == "passed" else outcome.get("reason", "sandbox_check_failed"),
                        "verifier": "bounded-expression-sandbox:v1", "support": [],
                        "sandbox_event": {"name": "hypothesis_sandbox", "source": "tool", "check_id": check_id,
                                          "hypothesis_id": row["id"], "contract_hash": row["contract_hash"],
                                          "output": json.dumps(outcome, sort_keys=True), "scope": "retained_fixtures",
                                          "passed": outcome.get("passed", 0), "failed": outcome.get("failed", 0)}}
            return {"status": "inconclusive", "reason": "sandbox_fixture_not_source_grounded",
                    "verifier": "source-review:v1", "support": []}
        return {"status": "inconclusive", "reason": "awaiting_real_procedure_outcome",
                "verifier": "source-review:v1", "support": []}
    proposals = []
    for cid in row["source_cids"]:
        preview = preview_direct_user_memory(runtime.engine, tenant, cid, **_projection_options(runtime))
        proposals.extend((cid, assertion) for assertion in preview.get("assertions", []))
    expected = contract.get("claim")
    if expected is None:
        # Ordinary content-only factual requests use the same exact source
        # parser. A vague generated association never becomes a factual claim.
        content = row.get("content", "").strip().removeprefix("Sandbox replay hypothesis: ").rstrip(".!?")
        matched = [_claim(assertion) for _, assertion in proposals
                   if assertion.get("calibration", {}).get("source_quote", "").strip().rstrip(".!?") == content]
        if matched and all(claim == matched[0] for claim in matched):
            expected = matched[0]
    support = [{"source_cid": cid, "claim": _claim(assertion),
                "quote": assertion.get("calibration", {}).get("source_quote", "")}
               for cid, assertion in proposals if expected and _claim(assertion) == expected]
    if kind in {"factual", "knowledge_maintenance"} and support:
        return {"status": "verified", "reason": "exact_source_supported_claim",
                "verifier": "semantic-source-review:v1", "support": support}
    if kind == "contradiction":
        from mnemosyne.assertion_semantics import assertions_conflict
        conflicts = []
        for i, (left_cid, left) in enumerate(proposals):
            for right_cid, right in proposals[i + 1:]:
                if (left_cid != right_cid and left.get("subject") == right.get("subject")
                        and left.get("scope") == right.get("scope")
                        and assertions_conflict(left, right)):
                    conflicts.extend([
                        {"source_cid": cid, "claim": _claim(assertion),
                         "quote": assertion.get("calibration", {}).get("source_quote", "")}
                        for cid, assertion in ((left_cid, left), (right_cid, right))])
        if conflicts:
            return {"status": "verified", "reason": "source_conflict_confirmed",
                    "verifier": "semantic-source-review:v1", "support": conflicts}
    # An explicit negative review is accepted only with current source versions
    # and its own checkable quotation. An unsupported theory is inconclusive.
    for episode in state["episodes"].values():
        if episode.get("user_id") != row.get("user_id"):
            continue
        for event in episode.get("tool_events", []):
            review = event.get("hypothesis_review", {})
            if (event.get("source") == "tool" and event.get("hypothesis_id") == row["id"]
                    and review.get("contract_hash") == row["contract_hash"]
                    and review.get("source_versions") == row["source_versions"]
                    and review.get("verdict") == "rejected" and event.get("output")):
                for evidence in review.get("support", []):
                    cid, quote = evidence.get("source_cid"), evidence.get("quote")
                    if cid in row["source_cids"] and quote and quote in runtime.engine.get_evidence(tenant, cid).content:
                        return {"status": "rejected", "reason": "external_source_review_rejected",
                                "verifier": event.get("name", "external-review"),
                                "support": [evidence], "review_episode_id": episode["id"]}
    return {"status": "inconclusive", "reason": "no_checkable_source_support",
            "verifier": "semantic-source-review:v1", "support": []}


def process_reviews(runtime, tenant, *, limit=8, now=None):
    """Claim, review and finalize bounded jobs with leases and source versions.

    Crashes after semantic projection are safe: deterministic projection IDs
    make the retry idempotent. A source change invalidates even a completed
    review. No synthetic episode or task reward is produced by this worker.
    """
    from mnemosyne.memory_formation import project_direct_user_memory
    timestamp = now or datetime.now(UTC)
    state = runtime.writer.read(tenant)
    if not runtime._enabled(state, "dreamer"):
        return {"reviewed": 0}
    reviewed = 0
    for key, old in list(state["policy"].get("hypotheses", {}).items()):
        if reviewed >= max(0, limit):
            break
        row = deepcopy(old)
        if "review_contract" not in row:
            row = typed_hypothesis(runtime, tenant, row)
            row["legacy_contract_adopted_at"] = timestamp.isoformat()
        versions = source_versions(runtime, tenant, row)
        changed = versions != old.get("source_versions")
        if old.get("status") == "running" and not changed:
            lease = old.get("lease_until")
            if lease and datetime.fromisoformat(lease) > timestamp:
                continue
        if old.get("status") in {"verified", "rejected"} and not changed:
            continue
        if old.get("review_complete") and not changed:
            continue
        next_review = old.get("next_review_at")
        if next_review and not changed and datetime.fromisoformat(next_review) > timestamp:
            continue
        token = digest([key, versions, old.get("review_attempts", 0), timestamp.isoformat()])
        def claim(current):
            stored = current["policy"].get("hypotheses", {}).get(key)
            if stored != old:
                return False
            history = list(stored.get("review_history", []))[-15:]
            if changed:
                history.append({"status": "queued", "reason": "source_version_changed", "at": timestamp.isoformat()})
            stored.update(row, source_versions=versions, status="running", review_token=token,
                          review_attempts=old.get("review_attempts", 0) + 1,
                          lease_until=(timestamp + timedelta(minutes=5)).isoformat(), review_history=history)
            return True
        if not runtime.writer.apply(tenant, "hypothesis_review_claim", claim):
            continue
        row.update(source_versions=versions)
        try:
            result = (_review(runtime, tenant, row, state) if versions else
                      {"status": "inconclusive", "reason": "source_unavailable", "support": [], "verifier": "source-review:v1"})
            if source_versions(runtime, tenant, row) != versions:
                result.update(status="inconclusive", reason="source_changed_during_review", support=[])
            if result["status"] == "verified":
                # The semantic writer independently rechecks source authority,
                # expiry, negation, uncertainty and temporal correction rules.
                cids = sorted({support["source_cid"] for support in result["support"]},
                              key=lambda cid: runtime.engine.get_evidence(tenant, cid).created_at)
                result["projection_results"] = [project_direct_user_memory(runtime.engine, tenant, cid,
                    **_projection_options(runtime)) for cid in cids]
                if source_versions(runtime, tenant, row) != versions:
                    result.update(status="inconclusive", reason="source_changed_during_projection")
        except Exception as exc:
            result = {"status": "inconclusive", "reason": "review_error", "error_type": type(exc).__name__,
                      "support": [], "verifier": "source-review:v1"}
        def finish(current):
            stored = current["policy"].get("hypotheses", {}).get(key)
            if not stored or stored.get("review_token") != token:
                return False
            stored.update(result, reviewed_at=timestamp.isoformat(), lease_until=None,
                          next_review_at=(timestamp + timedelta(minutes=min(1440, 5 * 2 ** min(stored["review_attempts"], 8)))).isoformat())
            stored.setdefault("review_history", []).append({"status": result["status"], "reason": result["reason"],
                                                            "at": timestamp.isoformat(), "verifier": result["verifier"]})
            return True
        reviewed += bool(runtime.writer.apply(tenant, "hypothesis_review_finish", finish))
    return {"reviewed": reviewed}
