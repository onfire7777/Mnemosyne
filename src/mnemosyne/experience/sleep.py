"""Bounded, evidence-driven consolidation, revisions and revalidation."""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from difflib import SequenceMatcher
import re
from math import ceil
from datetime import UTC, datetime, timedelta

from mnemosyne.skills import effects_of
from mnemosyne.learning import Lesson, Procedure
from .receipts import digest
from .runtime import stat_key
from .stats import Posterior, prob_better, contingency_lower_bound
from .candidates import (
    evaluate_candidate,
    ground_quotes,
    candidate_score,
    applies_to,
    correction_texts,
    persist_protected_cases,
    observed_steps,
)
from .revisions import install_revision, score_trials, propagate_children, inherit_library_lineage
from .schema import assimilate
from .separation import propose_splits
from .revalidate import revalidate


def common_sequence(sequences: list[list[str]]) -> list[str]:
    """Longest common subsequence, preserving demonstrated successful order."""
    if not sequences:
        return []
    common = sequences[0]
    for other in sequences[1:]:
        table = [[[] for _ in range(len(other) + 1)] for _ in range(len(common) + 1)]
        for i, left in enumerate(common, 1):
            for j, right in enumerate(other, 1):
                table[i][j] = (
                    table[i - 1][j - 1] + [left]
                    if left == right
                    else max(table[i - 1][j], table[i][j - 1], key=len)
                )
        common = table[-1][-1]
    return common


def replay_batch(
    episodes: list[dict],
    replayed: dict,
    limit: int = 50,
    *,
    posterior_by_class: dict | None = None,
    curiosity: bool = False,
    interleave_fraction: float = 0.3,
) -> list[dict]:
    eligible = [
        episode
        for episode in episodes
        if episode["status"] == "resolved"
        and replayed.get(episode["id"]) != digest(episode["signals"])
    ]
    counts = Counter(episode["task_class"] for episode in episodes)
    posteriors = posterior_by_class or {}

    def priority(episode):
        task = episode["task_class"]
        need = counts[task]
        uncertainty = (
            Posterior.from_dict(posteriors.get(task)).variance if curiosity else 0.0
        )
        return (-(abs(episode["rpe"]) + uncertainty) * need, episode["id"])

    eligible.sort(key=priority)
    if not eligible or limit <= 0:
        return []
    if limit == 1:
        return eligible[:1]
    dominant = eligible[0]["task_class"]
    other = [episode for episode in eligible if episode["task_class"] != dominant]
    selected = other[
        : min(len(other), max(1, ceil(limit * max(0.3, min(1.0, interleave_fraction)))))
    ]
    selected = (
        selected + [episode for episode in eligible if episode not in selected]
    )[:limit]
    return sorted(selected, key=priority)


def _gate(runtime, tenant: str, artifact: dict, episodes: list[dict]) -> bool:
    return evaluate_candidate(runtime, tenant, artifact, episodes)


def _scope_identity(scope: dict | None) -> dict | None:
    if scope and scope.get("kind") == "exact_query":
        return {**scope, "query": scope["query"].casefold()}
    return scope


def _candidate(
    task: str,
    steps: list[str],
    episodes: list[dict],
    kind: str = "procedure",
    parent: dict | None = None,
) -> dict:
    content = "\n".join(steps)
    episodes = sorted(episodes, key=lambda e: (e["created_at"], e["id"]))
    owners = {(row.get("tenant_id"), row.get("user_id")) for row in episodes}
    if len(owners) != 1:
        raise ValueError("candidate sources must have one tenant and user")
    tenant, user = next(iter(owners))
    source_ids = sorted(episode["id"] for episode in episodes)
    queries = {episode.get("user_text", "").casefold() for episode in episodes}
    scope_match = (
        {"kind": "exact_query", "query": episodes[0].get("user_text", "")}
        if len(queries) == 1
        else None
    )
    conditions = [scope_match["query"]] if scope_match and scope_match["query"] else []
    model = Lesson if kind == "lesson" else Procedure
    return model.native(**{
        "id": digest([kind, tenant, user, task, content, _scope_identity(scope_match)]),
        "kind": kind,
        "task_class": task,
        "revision": parent["revision"] + 1 if parent else 1,
        "parent_revision": parent["id"] if parent else None,
        "content": content,
        "steps": steps,
        "scope": task,
        "conditions": conditions,
        "scope_match": scope_match,
        "goal": episodes[-1].get("user_text", ""),
        "state": "candidate",
        "origin": "learned",
        "source_episode_ids": source_ids,
        "tenant_id": episodes[-1].get("tenant_id"),
        "user_id": episodes[-1].get("user_id"),
        "source_cids": sorted(
            {cid for episode in episodes for cid in episode["source_cids"]}
        ),
        "explanation": "This order is recorded by the linked external outcomes.",
        "explanation_sources": source_ids,
        "pinned": False,
        "locked": False,
        "created_at": datetime.now(UTC).isoformat(),
        "gate_passed": False,
        "needs_approval": bool(effects_of([{"content": content}], [])),
        "approved": False,
        "next_revalidation_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "revalidation_step": 0,
    }).to_record()


def _reuse_existing_identity(candidate: dict, state: dict) -> None:
    """Keep pre-scope identities stable, including withdrawn revisions."""
    previous_id = digest([
        candidate.get("content_kind", candidate["kind"]), candidate["task_class"],
        candidate["content"], candidate.get("scope_match"),
    ])
    if candidate.get("separation_ref"):
        previous_id = digest([previous_id, candidate["conditions"][0]])
    elif candidate.get("replaces"):
        previous_id = digest(["abstraction", previous_id, candidate["conditions"]])
    if candidate.get("schema_ref"):
        previous_id = digest(["schema", candidate["schema_ref"]["id"], candidate["content"]])
    previous = state["artifacts"].get(candidate["id"]) or state["artifacts"].get(previous_id)
    scope = candidate.get("scope_match")
    if previous is None and scope and not any(
        candidate.get(key) for key in ("separation_ref", "replaces", "schema_ref")
    ):
        # Earlier IDs used original query casing, or a broad scope merely
        # because the same query occurred twice. Keep their validated lifecycle
        # and scope; changing the identity must not revive a retired procedure.
        # ponytail: compatibility lookup is O(n) per missing identity; an indexed
        # migration can replace it if historical artifact volume warrants it.
        query = scope["query"].casefold()
        for row in state["artifacts"].values():
            if (row.get("tenant_id"), row.get("user_id")) != (
                candidate.get("tenant_id"), candidate.get("user_id")
            ):
                continue
            old_scope = row.get("scope_match")
            old_ids = {
                digest([candidate["kind"], candidate.get("tenant_id"), candidate.get("user_id"),
                        candidate["task_class"], candidate["content"], old_scope]),
                digest([candidate["kind"], candidate["task_class"], candidate["content"], old_scope]),
            }
            if row["id"] not in old_ids:
                continue
            sources = [state["episodes"].get(key) for key in row.get("source_episode_ids", [])]
            same_query = (
                old_scope and old_scope.get("kind") == "exact_query"
                and old_scope.get("query", "").casefold() == query
            ) or (
                old_scope is None and len(sources) > 1 and not row.get("conditions")
                and all(source and source.get("user_text", "").casefold() == query for source in sources)
            )
            if same_query:
                previous = row
                break
    if previous is None or (
        previous.get("tenant_id"), previous.get("user_id")
    ) != (candidate.get("tenant_id"), candidate.get("user_id")):
        return
    # A formerly mixed-user candidate is not an identity for either user's work.
    if any(
        (source.get("tenant_id"), source.get("user_id"))
        != (candidate.get("tenant_id"), candidate.get("user_id"))
        for key in previous.get("source_episode_ids", [])
        if (source := state["episodes"].get(key)) is not None
    ):
        return
    candidate["id"] = previous["id"]
    candidate["scope_match"] = deepcopy(previous.get("scope_match"))
    candidate["conditions"] = list(previous.get("conditions", []))


def _combine_candidates(candidates: list[dict]) -> list[dict]:
    """Keep one scoped candidate with all supporting episodes and proposal receipts."""
    combined = {}
    for candidate in candidates:
        item = combined.setdefault(candidate["id"], dict(candidate))
        for field in ("source_episode_ids", "source_cids", "explanation_sources"):
            item[field] = sorted(set(item.get(field, [])) | set(candidate.get(field, [])))
        records = [*item.get("proposal_records", []), *candidate.get("proposal_records", [])]
        if candidate.get("proposal_record"):
            records.append(candidate["proposal_record"])
        if records:
            item["proposal_records"] = list({digest(record): record for record in records}.values())
            item["proposal_record"] = item["proposal_records"][0]
        hypotheses = [*item.get("hypothesis_ids", []), *candidate.get("hypothesis_ids", [])]
        if candidate.get("hypothesis_id"):
            hypotheses.append(candidate["hypothesis_id"])
        if hypotheses:
            item["hypothesis_ids"] = sorted(set(hypotheses))
            item["hypothesis_id"] = item["hypothesis_ids"][0]
    return list(combined.values())


def _patch_parent(candidate: dict, artifacts: list[dict]) -> dict | None:
    scope = _scope_identity(candidate.get("scope_match"))
    exact_query = scope and scope.get("kind") == "exact_query"
    conditions = [value.casefold() if exact_query else value for value in candidate.get("conditions", [])]
    matches = [
        item
        for item in artifacts
        if item["task_class"] == candidate["task_class"]
        and item["kind"] == candidate["kind"]
        and item.get("user_id") == candidate.get("user_id")
        and _scope_identity(item.get("scope_match")) == scope
        and [value.casefold() if exact_query else value for value in item.get("conditions", [])] == conditions
        and item["state"] in {"active", "labile"}
        and (
            item["state"] == "labile"
            or SequenceMatcher(None, item["content"], candidate["content"]).ratio()
            >= 0.85
        )
    ]
    return (
        sorted(matches, key=lambda row: (row["state"] != "labile", row["id"]))[0]
        if matches
        else None
    )


def _scoped_splits(state: dict, tenant: str) -> list[dict]:
    splits = []
    for user in sorted({row["user_id"] for row in state["episodes"].values()}):
        scoped = {
            **state,
            "episodes": {key: row for key, row in state["episodes"].items()
                         if row["user_id"] == user},
            "artifacts": {key: row for key, row in state["artifacts"].items()
                          if row.get("user_id") == user},
        }
        for split in propose_splits(scoped):
            prior = state["policy"].get("pattern_splits", {}).get(split["id"])
            prior_ids = [key for _, ids, _ in prior["groups"] for key in ids] if prior else []
            if not prior_ids or any(
                state["episodes"].get(key, {}).get("user_id") != user
                for key in prior_ids
            ):
                split["id"] = digest([tenant, user, split["id"]])
            split["user_id"] = user
            splits.append(split)
    return splits


def consolidate(runtime, tenant: str) -> dict:
    snapshot = runtime.writer.read(tenant)
    if not runtime._enabled(snapshot, "lessons"):
        return {
            "replayed": 0,
            "candidates": 0,
            "frozen": snapshot["policy"].get("frozen", False),
        }
    tasks = {row["task_class"] for row in snapshot["episodes"].values()}
    class_stats = {
        task: snapshot["stats"].get(stat_key("class", task, 1, task), {})
        for task in tasks
    }
    score_trials(snapshot)
    reflection_episodes, reflections = _reflection_batch(snapshot)
    batch = replay_batch(
        list(snapshot["episodes"].values()),
        snapshot["policy"].get("replayed", {}),
        posterior_by_class=class_stats,
        curiosity=runtime._enabled(snapshot, "curiosity"),
        interleave_fraction=getattr(
            getattr(getattr(runtime, "engine", None), "policy", None),
            "learning_interleave_fraction",
            0.3,
        ),
    )
    analysis_batch = list(
        {row["id"]: row for row in [*batch, *reflection_episodes]}.values()
    )
    eligible_episodes = {
        row["id"] for row in snapshot["episodes"].values()
        if runtime._sources_live(tenant, row.get("source_cids", []), row.get("user_id"))
    }
    skipped_episodes = {
        row["id"] for row in analysis_batch if row["id"] not in eligible_episodes
    }
    analysis_batch = [row for row in analysis_batch if row["id"] in eligible_episodes]
    by_class = defaultdict(list)
    for episode in analysis_batch:
        if abs(episode["rpe"]) >= 0.2 or any(
            signal["kind"] == "correction" for signal in episode["signals"]
        ):
            by_class[(episode["user_id"], episode["task_class"])].append(episode)
    candidates = []
    induction_snapshot = {**snapshot, "episodes": {
        key: row for key, row in snapshot["episodes"].items() if key in eligible_episodes
    }}
    splits = (_scoped_splits(induction_snapshot, tenant)
              if runtime._enabled(snapshot, "pattern_separation") else [])
    for split in splits:
        if split["id"] in snapshot["policy"].get("pattern_splits", {}):
            continue
        for value, ids, steps in split["groups"]:
            candidate = _candidate(
                split["task_class"], steps, [snapshot["episodes"][key] for key in ids]
            )
            candidate["conditions"] = [value]
            candidate["id"] = digest([candidate["id"], value])
            candidate["separation_ref"] = split["id"]
            candidates.append(candidate)
    separated_tasks = {(split["user_id"], split["task_class"]) for split in splits}
    for (user, task), episodes in by_class.items():
        if (user, task) in separated_tasks:
            continue
        successes = [
            episode
            for episode in snapshot["episodes"].values()
            if episode["task_class"] == task
            and episode["user_id"] == user
            and episode["status"] == "resolved"
            and episode["reward"] > 0
            and episode["id"] in eligible_episodes
        ]
        demonstrated = [steps for episode in successes if (steps := observed_steps(episode))]
        if len(demonstrated) >= 2 and (steps := common_sequence(demonstrated)):
            candidates.append(_candidate(task, steps, successes))
        for episode in episodes:
            for text in correction_texts(episode):
                lesson = _candidate(task, [text], [episode], kind="lesson")
                lesson["node_type"] = "constraint"
                lesson["explanation"] = (
                    "This correction is quoted from the linked user feedback."
                )
                candidates.append(lesson)
            if episode["reward"] >= 0:
                continue
            for event in episode["tool_events"]:
                if event.get("source") in {
                    "assistant",
                    "self_generated",
                    "provider_self_grade",
                }:
                    continue
                steps = event.get("expected_steps") or event.get("corrective_steps")
                if (
                    isinstance(steps, list)
                    and steps
                    and all(isinstance(step, str) and step for step in steps)
                ):
                    candidates.append(_candidate(task, steps, [episode]))
    if runtime._enabled(snapshot, "chunking"):
        for chunk in mine_chunks(list(snapshot["artifacts"].values())):
            parents = [snapshot["artifacts"][key] for key in chunk["parents"]]
            ids = {key for parent in parents for key in parent["source_episode_ids"]}
            parent_ids = {parent["id"] for parent in parents}
            for row in snapshot["episodes"].values():
                if row["status"] != "resolved" or row["reward"] <= 0:
                    continue
                if row["user_id"] != parents[0].get("user_id"):
                    continue
                served = {
                    item["item_id"]
                    for rid in row["receipt_ids"]
                    for item in snapshot["receipts"].get(rid, {}).get("items", [])
                }
                if (
                    served & parent_ids
                    and candidate_score({"kind": "chunk", "steps": chunk["steps"]}, row)
                    == 1
                ):
                    ids.add(row["id"])
            candidate = _candidate(
                parents[0]["task_class"],
                chunk["steps"],
                [snapshot["episodes"][key] for key in sorted(ids)],
                kind="chunk",
            )
            candidate["chunk_parent_ids"] = chunk["parents"]
            candidate["task_classes"] = sorted({row["task_class"] for row in parents})
            candidates.append(candidate)
    if runtime._enabled(snapshot, "insight"):
        candidates.extend(_abstract_rules(snapshot))
    distill_mode = getattr(
        getattr(getattr(runtime, "engine", None), "policy", None),
        "learning_distill_mode",
        "deterministic",
    )
    provider_status = {"mode": distill_mode, "status": "ready"}
    if distill_mode == "off":
        candidates, splits = [], []
    elif distill_mode == "provider":
        proposals, provider_status = _provider_candidates(
            runtime, tenant, analysis_batch
        )
        candidates.extend(proposals)
    hypothesis_candidates, hypothesis_updates = _tested_hypotheses(snapshot)
    if distill_mode != "off":
        candidates.extend(hypothesis_candidates)
    prepared = []
    skipped_candidates = 0
    for candidate in candidates:
        _reuse_existing_identity(candidate, snapshot)
    for candidate in _combine_candidates(candidates):
        # Historical episodes can reference writes deferred by an older host.
        # Keep their immutable history, but never reuse partially missing or
        # erased provenance for a new learned behavior.
        if not set(candidate["source_episode_ids"]) <= eligible_episodes:
            skipped_candidates += 1
            continue
        existing = snapshot["artifacts"].get(candidate["id"])
        if existing and existing["state"] != "candidate":
            continue
        if not any(
            snapshot["policy"].get("replayed", {}).get(key)
            != digest(snapshot["episodes"][key]["signals"])
            for key in candidate["source_episode_ids"]
        ):
            continue
        if existing and existing.get("gate_evidence") and not (
            set(candidate["source_episode_ids"]) - set(existing["source_episode_ids"])
        ):
            continue
        if any(row["id"] == candidate["id"] for row in prepared):
            continue
        if existing:
            candidate["created_at"] = existing["created_at"]
        parent = _patch_parent(candidate, list(snapshot["artifacts"].values()))
        if parent and (
            parent.get("locked")
            or parent.get("pinned")
            or parent.get("pending_revision")
        ):
            continue
        episodes = [
            snapshot["episodes"][key] for key in candidate["source_episode_ids"]
        ]
        candidate["source_quotes"] = ground_quotes(runtime, tenant, candidate, episodes)
        if (
            runtime._enabled(snapshot, "schema")
            and parent is None
            and not candidate.get("replaces")
        ):
            candidate = assimilate(candidate, list(snapshot["artifacts"].values()))
            if candidate.get("schema_ref"):
                parent = snapshot["artifacts"][candidate["schema_ref"]["id"]]
                candidate["content_kind"] = candidate["kind"]
                candidate["kind"] = "skill"
                candidate["framework"] = {
                    "base_revision": candidate["schema_ref"],
                    "nodes": [candidate["framework_node"]],
                }
                candidate["id"] = digest(["schema", parent["id"], candidate["content"]])
                _reuse_existing_identity(candidate, snapshot)
        if parent:
            candidate.update(
                parent_revision=parent["id"], revision=parent["revision"] + 1
            )
            if candidate["kind"] == "skill":
                inherit_library_lineage(candidate, parent)
        replay = [
            row
            for row in snapshot["episodes"].values()
            if row["status"] == "resolved"
            and row["user_id"] == candidate.get("user_id")
            and row["task_class"] == candidate["task_class"]
            and applies_to(candidate, row["task_class"], row["user_text"])
        ]
        if evaluate_candidate(runtime, tenant, candidate, episodes, replay):
            candidate["state"] = "probation"
        prepared.append(candidate)
    hypotheses = (
        _dream_hypotheses(
            runtime, tenant,
            [row for row in batch if row["id"] in eligible_episodes], snapshot,
        )
        if runtime._enabled(snapshot, "dreamer")
        else []
    )

    def apply(state):
        score_trials(state)
        state["policy"]["distillation"] = provider_status
        for key, update in hypothesis_updates.items():
            if key in state["policy"].get("hypotheses", {}):
                state["policy"]["hypotheses"][key].update(update)
        for key, reflection in reflections.items():
            state["policy"].get("reflection_queue", {}).pop(key, None)
            state["policy"].setdefault("reflection_history", {})[key] = reflection
            if not any(
                candidate.get("parent_revision") == reflection["incumbent_id"]
                for candidate in prepared
            ):
                state["policy"].setdefault("reflection_requests", {})[key] = reflection
        for episode in batch:
            state["policy"].setdefault("replayed", {})[episode["id"]] = digest(
                episode["signals"]
            )
        for split in splits:
            state["policy"].setdefault("pattern_splits", {})[split["id"]] = split
        created = 0
        for candidate in prepared:
            persist_protected_cases(state, candidate)
            if candidate.get("gate_passed"):
                for hypothesis_id in candidate.get("hypothesis_ids", []):
                    state["policy"]["hypotheses"][hypothesis_id].update(
                        status="verified", candidate_id=candidate["id"]
                    )
            for key in candidate["source_episode_ids"]:
                for event in state["episodes"][key].get("tool_events", []):
                    if candidate.get("gate_passed") and event.get("reflection_id"):
                        state["policy"].get("reflection_requests", {}).pop(
                            event["reflection_id"], None
                        )
            existing = state["artifacts"].get(candidate["id"])
            if existing:
                if (
                    existing["state"] == "candidate"
                    and not existing.get("locked")
                    and not existing.get("pinned")
                ):
                    parent_id = candidate.get("parent_revision")
                    if parent_id and candidate["state"] == "probation":
                        install_revision(
                            state, candidate, parent_id, candidate["revision"] - 1
                        )
                    else:
                        existing.update(candidate)
                continue
            parent_id = candidate.get("parent_revision")
            if parent_id and candidate["state"] == "probation":
                parent = state["artifacts"].get(parent_id)
                if (
                    not parent
                    or parent.get("pinned")
                    or parent.get("locked")
                    or parent.get("pending_revision")
                ):
                    continue
                install_revision(state, candidate, parent_id, candidate["revision"] - 1)
            else:
                state["artifacts"][candidate["id"]] = candidate
            created += 1
        _lifecycle(runtime, state, tenant)
        _compile_knowledge(state)
        for hypothesis in hypotheses:
            state["policy"].setdefault("hypotheses", {}).setdefault(
                hypothesis["id"], hypothesis
            )
        if runtime._enabled(state, "homeostasis"):
            budget = getattr(
                getattr(getattr(runtime, "engine", None), "policy", None),
                "learning_homeostasis_budget",
                0.08,
            )
            _homeostasis(state, budget=budget)
        return {
            "replayed": len(batch), "candidates": created,
            "skipped_unavailable_source_episodes": len(skipped_episodes),
            "skipped_unavailable_source_candidates": skipped_candidates,
        }

    return runtime.writer.apply(
        tenant,
        "consolidate",
        apply,
        expected_revision=snapshot["policy"].get("revision", 0),
    )


def _dream_hypotheses(
    runtime, tenant: str, episodes: list[dict], state: dict | None = None
) -> list[dict]:
    from mnemosyne.dreamer import SandboxedDreamer

    groups = defaultdict(list)
    for episode in episodes:
        groups[(episode["user_id"], episode["task_class"])].append(episode)
    hypotheses = []
    for (user, task), rows in groups.items():
        sources = {}
        for episode in rows:
            for cid in episode["source_cids"]:
                if runtime._sources_live(tenant, [cid], user):
                    source = runtime.engine.get_evidence(tenant, cid)
                    if source.actor != "assistant":
                        sources[cid] = source
        report = SandboxedDreamer().dream(list(sources.values()), tenant_id=tenant)
        for item in report.candidates:
            hypotheses.append(
                {
                    "id": item.id,
                    "content": item.content,
                    "source_cids": list(item.source_evidence_cids),
                    "task_class": task,
                    "user_id": user,
                    "source_episode_ids": [row["id"] for row in rows],
                    "conditions": [],
                    "reality_class": "self_generated",
                    "reward_weight": 0.0,
                    "shadow_only": True,
                    "status": "awaiting_external_verifier",
                    "instruction_authority": "none",
                    "capability_tags": ["data-only", "no-write-authority"],
                }
            )
    if state:
        for artifact in state["artifacts"].values():
            if (
                artifact["state"] not in {"active", "labile"}
                or len(artifact["steps"]) < 2
            ):
                continue
            if (artifact.get("user_id"), artifact["task_class"]) not in groups:
                continue
            steps = artifact["steps"][:]
            steps[0], steps[1] = steps[1], steps[0]
            hypotheses.append(
                {
                    "id": digest(
                        ["hypothesis", artifact["id"], artifact["revision"], steps]
                    ),
                    "content": "\n".join(steps),
                    "steps": steps,
                    "parent_revision": artifact["id"],
                    "task_class": artifact["task_class"],
                    "user_id": artifact.get("user_id"),
                    "scope_match": artifact.get("scope_match"),
                    "conditions": artifact.get("conditions", []),
                    "source_cids": artifact["source_cids"],
                    "source_episode_ids": artifact["source_episode_ids"],
                    "reality_class": "self_generated",
                    "reward_weight": 0.0,
                    "shadow_only": True,
                    "status": "awaiting_external_verifier",
                    "instruction_authority": "none",
                    "capability_tags": ["data-only", "no-write-authority"],
                }
            )
    return hypotheses


def _reflection_batch(state: dict) -> tuple[list[dict], dict]:
    episodes, consumed = {}, {}
    for key, row in state["policy"].get("reflection_queue", {}).items():
        parent = state["artifacts"].get(row["incumbent_id"])
        if not parent:
            continue
        sources = [
            state["episodes"][identifier]
            for identifier in row["episode_ids"]
            if identifier in state["episodes"]
            and state["episodes"][identifier]["status"] == "resolved"
        ]
        episodes.update({source["id"]: source for source in sources})
        consumed[key] = {
            **row,
            "task_class": parent["task_class"],
            "user_id": parent.get("user_id"),
            "source_cids": sorted(
                {cid for source in sources for cid in source["source_cids"]}
            ),
            "status": "reviewed_waiting_for_verified_alternative",
        }
    return list(episodes.values()), consumed


def _tested_hypotheses(state: dict) -> tuple[list[dict], dict]:
    candidates, updates = [], {}
    for key, hypothesis in state["policy"].get("hypotheses", {}).items():
        if hypothesis.get("status") in {"verified", "rejected"} or not hypothesis.get(
            "steps"
        ):
            continue
        tested = []
        for episode in state["episodes"].values():
            if episode["status"] != "resolved" or episode.get(
                "user_id"
            ) != hypothesis.get("user_id"):
                continue
            for event in episode.get("tool_events", []):
                if event.get("source") in {
                    "assistant",
                    "self_generated",
                    "provider_self_grade",
                }:
                    continue
                steps = event.get("tested_steps")
                if (
                    event.get("hypothesis_id") != key
                    or not isinstance(steps, list)
                    or not steps
                ):
                    continue
                if hypothesis.get("steps") and steps != hypothesis["steps"]:
                    continue
                if episode["reward"] <= 0:
                    updates[key] = {
                        "status": "rejected",
                        "test_episode_ids": [episode["id"]],
                    }
                    break
                if any(
                    signal["kind"] in {"tests", "verifier"}
                    for signal in episode["signals"]
                ):
                    tested.append((episode, steps))
        if tested and key not in updates:
            rows = [row for row, _ in tested]
            steps = tested[0][1]
            if any(sequence != steps for _, sequence in tested):
                continue
            if not any(
                state["policy"].get("replayed", {}).get(row["id"])
                != digest(row["signals"])
                for row in rows
            ):
                continue
            candidate = _candidate(rows[0]["task_class"], steps, rows)
            candidate["hypothesis_id"] = key
            candidates.append(candidate)
            updates[key] = {
                "status": "externally_tested",
                "test_episode_ids": [row["id"] for row in rows],
                "candidate_id": candidate["id"],
            }
    return candidates, updates


def _provider_candidates(
    runtime, tenant: str, episodes: list[dict]
) -> tuple[list[dict], dict]:
    from mnemosyne.consolidation import ProviderProposalLedger, _provider_payload_view

    providers = [
        ("lesson", getattr(runtime, "lesson_distiller", None)),
        ("procedure", getattr(runtime, "procedure_inducer", None)),
    ]
    providers = [
        (kind, provider)
        for kind, provider in providers
        if provider is not None
        and getattr(provider, "provider_kind", None) in {"command", "http"}
    ]
    if not providers:
        return [], {"mode": "provider", "status": "awaiting_configured_provider"}
    groups = defaultdict(list)
    for episode in episodes:
        groups[(episode["task_class"], episode["user_id"])].append(episode)
    results = []
    for (task, user), rows in groups.items():
        for kind, provider in providers:
            provider.proposal_ledger = ProviderProposalLedger(runtime.engine)
            provider.proposal_branch = "main"
            inputs = []
            for row in rows:
                for cid in row["source_cids"]:
                    source = runtime.engine.get_evidence(tenant, cid)
                    if (
                        source is None
                        or source.actor == "assistant"
                        or not runtime._sources_live(tenant, [cid], user)
                    ):
                        continue
                    view = _provider_payload_view(
                        {
                            "id": cid,
                            "content": source.content,
                            "sensitivity": source.sensitivity,
                            "access_policy": source.access_policy,
                            "source_evidence_cids": [cid],
                        },
                        provider.disclosure_policy,
                    )
                    inputs.append({**view, "signature": task, "episode_id": row["id"]})
            if not inputs:
                continue
            response = (
                provider.distill(tenant, inputs)
                if kind == "lesson"
                else provider.induce(tenant, inputs)
            )
            for proposal in response["lessons" if kind == "lesson" else "procedures"]:
                if kind == "lesson":
                    steps = [proposal["content"]]
                else:
                    steps = proposal["signature"].get("steps")
                    if not isinstance(steps, list) or not all(
                        isinstance(step, str) for step in steps
                    ):
                        steps = [
                            re.sub(r"^\s*\d+[.)]\s*", "", line).strip()
                            for line in proposal["body"].splitlines()
                            if line.strip()
                        ]
                if not steps:
                    continue
                candidate = _candidate(task, steps, rows, kind=kind)
                candidate["proposal_record"] = response.get("details", {}).get(
                    "proposal_record", {}
                )
                results.append(candidate)
    return results, {
        "mode": "provider",
        "status": "proposals_evaluated",
        "proposals": len(results),
    }


def _shrink_routes(state: dict) -> None:
    timestamp = datetime.now(UTC)
    for task, weights in state["policy"].get("routes", {}).items():
        if len(weights) < 2:
            continue
        outcomes = [
            state["episodes"].get(row["episode_id"], {})
            for row in state.get("credit", {}).values()
            if row["task_class"] == task
        ]
        latest = max(
            (
                row.get("resolved_at", row.get("created_at", timestamp.isoformat()))
                for row in outcomes
            ),
            default=None,
        )
        if (
            latest is None
            or (timestamp - datetime.fromisoformat(latest)).total_seconds() <= 86400
        ):
            continue
        prior = 1 / len(weights)
        maximum = max(abs(value - prior) for value in weights.values())
        if maximum == 0:
            continue
        daily = (
            state["policy"]
            .setdefault("route_daily", {})
            .setdefault(
                task, {"day": timestamp.date().isoformat(), "weights": dict(weights)}
            )
        )
        if daily["day"] != timestamp.date().isoformat():
            daily.update(day=timestamp.date().isoformat(), weights=dict(weights))
        fraction = min(1.0, 0.02 / maximum)
        for route, value in weights.items():
            distance = abs(value - prior)
            if distance:
                remaining = max(
                    0.0, 0.1 - abs(value - daily["weights"].get(route, value))
                )
                fraction = min(fraction, remaining / distance)
        if fraction <= 0:
            continue
        previous = dict(weights)
        weights.update(
            {
                route: value + (prior - value) * fraction
                for route, value in weights.items()
            }
        )
        state["policy"].setdefault("route_normalization", {})[task] = {
            "previous": previous,
            "prior": prior,
            "last_credit_at": latest,
            "observed_at": timestamp.isoformat(),
            "day": daily["day"],
            "maximum_movement": max(
                abs(weights[key] - previous[key]) for key in weights
            ),
        }


def _compile_knowledge(state: dict) -> None:
    by_task = defaultdict(list)
    for artifact in state["artifacts"].values():
        if artifact["kind"] == "lesson" and artifact["state"] == "active":
            by_task[artifact["task_class"]].append(artifact)
    active_pages = {}
    for task, artifacts in by_task.items():
        artifacts.sort(key=lambda row: row["id"])
        sources = [{"id": row["id"], "revision": row["revision"]} for row in artifacts]
        page_id = digest([task, sources])
        state["policy"].setdefault("knowledge_pages", {}).setdefault(
            page_id,
            {
                "id": page_id,
                "task_class": task,
                "artifact_revisions": sources,
                "content": "\n\n".join(row["content"] for row in artifacts),
                "source_episode_ids": sorted(
                    {key for row in artifacts for key in row["source_episode_ids"]}
                ),
                "source_cids": sorted(
                    {cid for row in artifacts for cid in row["source_cids"]}
                ),
                "explanations": [
                    {
                        "artifact_id": row["id"],
                        "text": row["explanation"],
                        "source_episode_ids": row["explanation_sources"],
                    }
                    for row in artifacts
                ],
                "instruction_authority": "none",
                "capability_tags": ["data-only", "no-write-authority"],
            },
        )
        active_pages[task] = page_id
    if active_pages or "active_knowledge_pages" in state["policy"]:
        state["policy"]["active_knowledge_pages"] = active_pages


def _abstract_rules(state: dict) -> list[dict]:
    groups = defaultdict(list)
    for item in state["artifacts"].values():
        if (
            item["kind"] == "lesson"
            and item["state"] == "active"
            and not item.get("locked")
            and not item.get("pinned")
        ):
            groups[(item.get("user_id"), item["task_class"], item["content"])].append(item)
    proposals = []
    for (user, task, _), originals in groups.items():
        if len(originals) < 2:
            continue
        conditions = sorted(
            set.intersection(*(set(row.get("conditions", [])) for row in originals))
        )
        if not any(
            len(conditions) < len(row.get("conditions", [])) for row in originals
        ):
            continue
        source_ids = sorted(
            {key for row in originals for key in row["source_episode_ids"]}
        )
        candidate = _candidate(
            task,
            originals[0]["steps"],
            [state["episodes"][key] for key in source_ids],
            kind="lesson",
        )
        candidate.update(
            id=digest(["abstraction", candidate["id"], conditions]),
            conditions=conditions,
            replaces=sorted(row["id"] for row in originals),
        )
        heldout = [
            row
            for row in state["episodes"].values()
            if row["id"] not in source_ids
            and row["status"] == "resolved"
            and row["user_id"] == user
            and row["task_class"] == task
            and all(
                token.casefold() in row["user_text"].casefold() for token in conditions
            )
        ]
        scores, before = [], []
        for row in heldout:
            score = candidate_score(candidate, row)
            previous = [
                candidate_score(old, row)
                for old in originals
                if applies_to(old, row["task_class"], row["user_text"])
            ]
            if score is not None and previous and None not in previous:
                scores.append(score)
                before.append(max(previous))
        candidate["training_source_episode_ids"] = source_ids
        candidate["abstraction_evaluation"] = {
            "candidate_scores": scores,
            "original_scores": before,
            "heldout_episode_ids": [row["id"] for row in heldout],
        }
        if not accept_abstraction(scores, before):
            candidate["abstraction_pending"] = True
        else:
            evidence_ids = sorted(set(source_ids) | {row["id"] for row in heldout})
            candidate["source_episode_ids"] = evidence_ids
            candidate["explanation_sources"] = evidence_ids
            candidate["source_cids"] = sorted(
                {
                    cid
                    for key in evidence_ids
                    for cid in state["episodes"][key]["source_cids"]
                }
            )
        proposals.append(candidate)
    return proposals


def _activation_trial(runtime, state: dict, artifact: dict):
    row = state["stats"].get(
        stat_key(artifact["kind"], artifact["id"], artifact["revision"], artifact["task_class"]),
        {},
    )
    probation = getattr(
        getattr(getattr(runtime, "engine", None), "policy", None),
        "learning_probation_outcomes", {},
    )
    threshold = (
        probation.get("schema", 5) if artifact.get("schema_ref")
        else probation.get("standalone", 12)
    )
    tested = Posterior.from_dict(row)
    control = Posterior(
        1 + row.get("control_successes", 0),
        1 + row.get("control_n", 0) - row.get("control_successes", 0),
        row.get("control_n", 0),
    )
    return row, tested, control, threshold


def activation_supported(
    runtime, state: dict, artifact: dict, *, superiority: float | None = None,
) -> bool:
    """Shared native evidence for promotion, operator changes and erasure."""
    row, tested, control, threshold = _activation_trial(runtime, state, artifact)
    bound = contingency_lower_bound(
        row.get("served_successes", tested.alpha - 1), row.get("served_n", tested.n),
        row.get("control_successes", 0), control.n, minimum=min(8, threshold),
    )
    return bool(
        tested.n >= threshold and control.n >= 8
        and row.get("verified_n", 0) >= threshold
        and row.get("verified_successes", 0) > 0
        and bound is not None and bound > 0
        and (prob_better(tested, control) if superiority is None else superiority) >= 0.9
        and artifact.get("gate_passed")
        and artifact.get("source_cids") and artifact.get("source_episode_ids")
        and (not artifact.get("needs_approval") or artifact.get("approved"))
        and (not artifact.get("ab_trial") or artifact.get("ab_passed"))
        and not artifact.get("abstraction_pending")
    )


def _lifecycle(runtime, state: dict, tenant: str = "") -> None:
    timestamp = datetime.now(UTC)
    score_trials(state)
    for artifact in state["artifacts"].values():
        if (
            artifact.get("pinned")
            or artifact.get("locked")
            or artifact["state"] in {"retired", "archived", "rejected"}
        ):
            continue
        if artifact["state"] == "candidate":
            age = (timestamp - datetime.fromisoformat(artifact["created_at"])).days
            if artifact.get("origin") == "learned" and age >= 14:
                artifact["stale"] = True
                if age >= 30:
                    artifact["state"] = "archived"
            continue
        row, tested, control, threshold = _activation_trial(runtime, state, artifact)
        if tested.n >= threshold and control.n >= 8:
            better = prob_better(tested, control)
            if better <= 0.1:
                artifact["state"] = "retired"
                continue
            if activation_supported(runtime, state, artifact, superiority=better):
                artifact["state"] = "active"
                if artifact.get("parent_revision"):
                    parent = state["artifacts"][artifact["parent_revision"]]
                    if not parent.get("pinned") and not parent.get("locked"):
                        parent["state"] = "retired"
                        parent["superseded_by"] = artifact["id"]
                        parent.pop("pending_revision", None)
                for key in artifact.get("replaces", []):
                    original = state["artifacts"][key]
                    if not original.get("pinned") and not original.get("locked"):
                        original["state"] = "archived"
        if (
            tested.n >= 15
            and tested.lower_bound < control.lower_bound
            and artifact["state"] == "active"
        ):
            artifact["state"] = "demoted"
        if (
            artifact["state"] == "labile"
            and artifact.get("labile_until")
            and timestamp >= datetime.fromisoformat(artifact["labile_until"])
        ):
            artifact["state"] = "active" if activation_supported(runtime, state, artifact) else "probation"
        uses = [
            receipt["created_at"]
            for receipt in state["receipts"].values()
            if any(
                item["item_id"] == artifact["id"]
                and item["revision"] == artifact["revision"]
                for item in receipt.get("items", [])
            )
        ]
        last_used = max(
            [
                artifact["created_at"],
                row.get("last_outcome_at", artifact["created_at"]),
                *uses,
            ]
        )
        idle_days = (timestamp - datetime.fromisoformat(last_used)).days
        if artifact.get("origin") == "learned":
            if idle_days >= 30:
                artifact["state"] = "archived"
                continue
            if idle_days >= 14:
                artifact["state"] = "demoted"
        if runtime._enabled(state, "revalidation"):
            revalidate(
                runtime,
                tenant or artifact.get("tenant_id", ""),
                state,
                artifact,
                timestamp,
            )
    for artifact in state["artifacts"].values():
        if (
            artifact["state"] == "active"
            and artifact.get("source_library_skill_id")
            and not artifact.get("source_skill_id")
            and not artifact.get("pinned")
            and not artifact.get("locked")
        ):
            parent = state["artifacts"].get(
                artifact.get("source_library_parent_artifact"), {}
            )
            parent_revision = parent.get(
                "source_skill_revision", artifact.get("source_library_parent_revision")
            )
            state["policy"].setdefault("skill_revision_outbox", {}).setdefault(
                artifact["id"],
                {
                    "artifact_id": artifact["id"],
                    "skill_id": artifact["source_library_skill_id"],
                    "parent_revision": parent_revision,
                    "parent_artifact_id": parent.get("id"),
                    "revision": artifact["revision"],
                    "source_episode_ids": artifact["source_episode_ids"],
                    "source_cids": artifact["source_cids"],
                },
            )
    # Chunk links are added only once the child has independently passed probation.
    for child in state["artifacts"].values():
        if child["state"] != "active":
            continue
        for key in child.get("chunk_parent_ids", []):
            parent = state["artifacts"].get(key)
            if parent and not parent.get("locked") and not parent.get("pinned"):
                ref = {"id": child["id"], "revision": child["revision"]}
                if ref not in parent.setdefault("children", []):
                    parent["children"].append(ref)
                if child["id"] not in parent.setdefault("chunk_ids", []):
                    parent["chunk_ids"].append(child["id"])
    propagate_children(state)


def _homeostasis(state: dict, budget: float = 0.08) -> None:
    groups = defaultdict(list)
    task_for_key = {
        stat_key(
            row["target_kind"], row["target_id"], row["revision"], row["task_class"]
        ): row["task_class"]
        for row in state.get("credit", {}).values()
    }
    for key, row in state["stats"].items():
        if "utility" in row and key in task_for_key:
            groups[task_for_key[key]].append(row)
    for rows in groups.values():
        mean = sum(abs(row["utility"] - 1) for row in rows) / len(rows)
        if mean > budget:
            for row in rows:
                row["utility"] = 1 + (row["utility"] - 1) * (budget / mean)
    _shrink_routes(state)


def guarded_split(
    before_scores: tuple[float, float], after_scores: tuple[float, float]
) -> bool:
    return all(
        after > before
        for before, after in zip(before_scores, after_scores, strict=True)
    )


def mine_chunks(artifacts: list[dict], support: int = 5) -> list[dict]:
    occurrences = defaultdict(list)
    for artifact in artifacts:
        if artifact.get("state") != "active":
            continue
        for index in range(max(0, len(artifact.get("steps", [])) - 1)):
            occurrences[(artifact.get("user_id"), tuple(artifact["steps"][index : index + 2]))].append(artifact)
    return [
        {"steps": list(steps), "parents": sorted({row["id"] for row in rows})}
        for (_, steps), rows in occurrences.items()
        if len({row["id"] for row in rows}) >= support
        and len({row["task_class"] for row in rows}) >= 2
    ]


def accept_abstraction(
    candidate_scores: list[float], original_scores: list[float]
) -> bool:
    return (
        bool(candidate_scores)
        and len(candidate_scores) == len(original_scores)
        and all(
            candidate >= original
            for candidate, original in zip(
                candidate_scores, original_scores, strict=True
            )
        )
    )
