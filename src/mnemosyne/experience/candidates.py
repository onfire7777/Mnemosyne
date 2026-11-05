"""Source-grounded data candidates and their mandatory promotion pipeline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from copy import deepcopy

from mnemosyne.gate import Candidate, PromotionGate, RegressionCase
from mnemosyne.learning import LocalCritic
from mnemosyne.security import sanitize_retrieved_text
from mnemosyne.skills import effects_of
from .receipts import digest

EXCLUDED_SOURCES = {"assistant", "self_generated", "provider_self_grade"}


def applies_to(artifact: dict, task: str, query: str) -> bool:
    if artifact.get("task_class") != task and task not in artifact.get(
        "task_classes", []
    ):
        return False
    scope = artifact.get("scope_match")
    if scope and (
        scope.get("kind") != "exact_query"
        or not scope.get("query")
        or scope["query"].casefold() != query.casefold()
    ):
        return False
    return all(
        token.casefold() in query.casefold() for token in artifact.get("conditions", [])
    )


def correction_texts(episode: dict) -> list[str]:
    return [
        item["evidence"]
        for item in episode.get("signals", [])
        if item.get("kind") == "correction"
        and item.get("source") not in EXCLUDED_SOURCES
        and isinstance(item.get("evidence"), str)
        and item["evidence"].strip()
    ]


def _source_case(artifact: dict, quote: dict) -> RegressionCase:
    return RegressionCase(
        "source-" + digest(quote)[:20],
        artifact["task_class"],
        quote["quote"],
        quote["quote"],
        protected=True,
        origin="genuine",
    )


def persist_protected_cases(state: dict, artifact: dict) -> None:
    if not artifact.get("gate_passed"):
        return
    protected_ids = artifact.get("gate_evidence", {}).get("protected_case_ids", [])
    for quote in artifact.get("source_quotes", []):
        case = _source_case(artifact, quote)
        if case.id in protected_ids:
            state["policy"].setdefault("protected_cases", {}).setdefault(
                case.id,
                {
                    "case": case.to_dict(),
                    "source_cids": [quote["cid"]],
                    "source_episode_ids": [quote["episode_id"]],
                    "reason": "retain_verified_source_quote",
                    "user_id": artifact.get("user_id"),
                },
            )


def expected_steps(episode: dict) -> list[list[str]]:
    result = []
    for event in episode.get("tool_events", []):
        if event.get("source") in EXCLUDED_SOURCES:
            continue
        steps = event.get("expected_steps") or event.get("corrective_steps")
        verified = (
            event.get("success") is True
            or event.get("verdict") in ("pass", "passed", "success")
            or isinstance(event.get("passed"), int)
            and event["passed"] > 0
            and event.get("failed") == 0
        )
        if (
            not steps
            and verified
            and (event.get("hypothesis_id") or event.get("revalidation_request_id"))
        ):
            steps = event.get("tested_steps")
        if (
            isinstance(steps, list)
            and steps
            and all(isinstance(step, str) and step for step in steps)
        ):
            result.append(steps)
    return result


def observed_steps(episode: dict) -> list[str]:
    return [
        event["name"]
        for event in episode.get("tool_events", [])
        if isinstance(event.get("name"), str)
        and event["name"] != "benchmark_verifier"
        and event.get("source") not in EXCLUDED_SOURCES
    ]


def ordered_subset(steps: list[str], expected: list[str]) -> bool:
    iterator = iter(expected)
    return all(any(value == step for value in iterator) for step in steps)


def candidate_score(artifact: dict, episode: dict) -> float | None:
    """Score only against an external order oracle, never model self-judgment."""
    if artifact.get("content_kind", artifact.get("kind")) == "lesson":
        corrections = correction_texts(episode)
        return float(artifact["content"] in corrections) if corrections else None
    expected = expected_steps(episode)
    if expected:
        match = any(artifact["steps"] == sequence for sequence in expected)
        if artifact.get("kind") == "chunk":
            match = any(
                any(
                    sequence[index : index + len(artifact["steps"])]
                    == artifact["steps"]
                    for index in range(len(sequence) - len(artifact["steps"]) + 1)
                )
                for sequence in expected
            )
        return float(match)
    if (episode.get("reward") or 0) > 0 and any(
        s["kind"] in {"verifier", "tests"} for s in episode.get("signals", [])
    ):
        observed = observed_steps(episode)
        if observed:
            if artifact.get("kind") == "chunk":
                return float(
                    any(
                        observed[index : index + len(artifact["steps"])]
                        == artifact["steps"]
                        for index in range(len(observed) - len(artifact["steps"]) + 1)
                    )
                )
            return float(ordered_subset(artifact["steps"], observed))
    return None


def ground_quotes(
    runtime, tenant: str, artifact: dict, episodes: list[dict]
) -> list[dict]:
    quotes = []
    for step in artifact["steps"]:
        found = None
        for episode in episodes:
            for cid in episode["source_cids"]:
                source = runtime.engine.get_evidence(tenant, cid)
                if (
                    source
                    and not source.erased
                    and (
                        source.actor == "tool"
                        or (
                            artifact.get("origin") == "imported"
                            or artifact.get("content_kind", artifact.get("kind"))
                            == "lesson"
                        )
                        and source.actor == "user"
                    )
                    and step in source.content
                ):
                    found = {"episode_id": episode["id"], "cid": cid, "quote": step}
                    break
            if found:
                break
        if not found:
            return []
        quotes.append(found)
    return quotes


def evaluate_candidate(
    runtime,
    tenant: str,
    artifact: dict,
    episodes: list[dict],
    replay_episodes: list[dict] | None = None,
) -> bool:
    artifact["sanitized"] = sanitize_retrieved_text(artifact["content"], 5)
    artifact["source_quotes"] = ground_quotes(runtime, tenant, artifact, episodes)
    safe = (
        LocalCritic()
        .verify({"category": "safety", "statement": artifact["content"]})
        .verified
    )
    artifact["safety_passed"] = safe
    if not safe:
        artifact.update(state="rejected", pending_reason="unsafe_candidate")
        return False
    if not artifact["source_quotes"] or not runtime._sources_live(
        tenant, artifact["source_cids"], artifact.get("user_id")
    ):
        artifact["pending_reason"] = "missing_live_quote_grounding"
        return False
    source_cases = [
        _source_case(artifact, quote) for quote in artifact["source_quotes"]
    ]
    recorded = runtime.writer.read(tenant)["policy"].get("protected_cases", {})
    protected = [
        RegressionCase.from_dict(row["case"])
        for row in recorded.values()
        if row.get("user_id") == artifact.get("user_id")
    ]
    protected.extend(getattr(runtime, "protected_cases", []))
    cases = list({case.id: case for case in [*source_cases, *protected]}.values())
    protected = [
        case
        for case in cases
        if case.protected
        and case.mode == "active"
        and case.origin in {"genuine", "curated"}
    ]
    gate = PromotionGate(
        runtime.engine,
        cases,
        retrieval_context={
            "principal": artifact.get("user_id"),
            "user_id": artifact.get("user_id"),
            "role": "reader",
        },
    )
    proposal = Candidate(
        artifact["id"],
        "procedure",
        artifact["task_class"],
        artifact["content"],
        "learning-check-" + artifact["id"][:16],
        artifact["source_cids"],
    )
    candidate_cases = []

    def check(engine, branch):
        if artifact.get("origin") == "imported":
            origin = artifact.get("source_origin", {})
            if (
                not origin.get("source_sha")
                or origin.get("tenant_id") != tenant
                or origin.get("user_id") != artifact.get("user_id")
            ):
                return "import_source_identity_missing"
            candidate_cases.append("import-integrity-" + origin["source_sha"])
            return None
        for episode in episodes:
            score = candidate_score(artifact, episode)
            if score is None:
                continue
            candidate_cases.append("order-" + episode["id"])
            if score < 1:
                return "candidate_external_order_mismatch"
        if not candidate_cases:
            return "candidate_external_verifier_missing"
        return None

    result = gate.evaluate(
        tenant, proposal, lambda engine, branch: None, pre_merge_check=check
    )
    replay = sorted(
        replay_episodes or episodes, key=lambda e: (e["created_at"], e["id"])
    )[-50:]
    scores = [
        {"episode_id": episode["id"], "score": score}
        for episode in replay
        if (score := candidate_score(artifact, episode)) is not None
    ]
    artifact["replay_evidence"] = {"cases": scores, "supports_probation_only": True}
    protected_ids = [case.id for case in protected if case.protected]
    imported = artifact.get("origin") == "imported"
    passed = (
        result.promoted
        and bool(protected_ids)
        and bool(candidate_cases)
        and (imported or bool(scores))
        and all(row["score"] == 1 for row in scores)
    )
    artifact["gate_evidence"] = {
        "content_hash": digest(artifact["content"]),
        "passed": passed,
        "case_ids": result.passed_cases,
        "candidate_case_ids": candidate_cases,
        "protected_case_ids": protected_ids,
        "protected_passed": bool(protected_ids)
        and all(key in result.passed_cases for key in protected_ids),
        "failed_cases": result.failed_cases,
        "admission_only": imported,
        "replay_episode_ids": [row["episode_id"] for row in scores],
    }
    artifact["gate_passed"] = passed
    if not passed:
        artifact["pending_reason"] = "external_verification_pending_or_failed"
    return passed


def register_import(runtime, tenant: str, candidate: dict) -> dict:
    """Admit a source import to local probation without manufacturing an outcome."""
    origin = candidate.get("source_origin", {})
    user = origin.get("user_id")
    identity = digest(
        [
            "import",
            candidate["id"],
            candidate.get("revision", 1),
            candidate.get("task_class", ""),
        ]
    )
    snapshot = runtime.writer.read(tenant)
    if identity in snapshot["artifacts"]:
        return snapshot["artifacts"][identity]
    timestamp = datetime.now(UTC)
    episode_id = "import-" + identity
    episode = {
        "id": episode_id,
        "tenant_id": tenant,
        "user_id": user,
        "session_id": episode_id,
        "task_class": candidate.get("task_class", ""),
        "receipt_ids": [],
        "source_cids": candidate.get("source_cids", []),
        "source_origin": origin,
        "signals": [],
        "tool_events": [],
        "user_text": "",
        "status": "imported",
        "reward": None,
        "rpe": None,
        "prediction": 0.5,
        "created_at": timestamp.isoformat(),
    }
    artifact = {
        "id": identity,
        "kind": "skill",
        "origin": "imported",
        "source_skill_id": candidate["id"],
        "source_skill_revision": candidate.get("revision", 1),
        "revision": 1,
        "parent_revision": None,
        "state": "candidate",
        "task_class": candidate.get("task_class", ""),
        "scope": candidate.get("task_class", ""),
        "conditions": [],
        "goal": "",
        "content": candidate["content"],
        "steps": candidate.get("steps", []),
        "source_cids": candidate.get("source_cids", []),
        "source_episode_ids": [episode_id],
        "source_origin": origin,
        "framework": deepcopy(candidate.get("framework") or {}),
        "tenant_id": tenant,
        "user_id": user,
        "explanation": "Imported source content awaits locally observed outcomes.",
        "explanation_sources": [episode_id],
        "pinned": False,
        "locked": False,
        "needs_approval": bool(
            candidate.get("needs_approval")
            or effects_of([{"content": candidate["content"]}], [])
        ),
        "approved": bool(candidate.get("approved")),
        "gate_passed": False,
        "created_at": timestamp.isoformat(),
        "revalidation_step": 0,
        "next_revalidation_at": (timestamp + timedelta(days=1)).isoformat(),
    }
    valid_identity = (
        origin.get("tenant_id") == tenant
        and bool(user)
        and bool(origin.get("source_sha"))
    )
    valid_sources = valid_identity and runtime._sources_live(
        tenant, artifact["source_cids"], user
    )
    if valid_sources and evaluate_candidate(runtime, tenant, artifact, [episode]):
        artifact["state"] = "probation"

        def admit(state):
            if identity not in state["artifacts"]:
                state["episodes"][episode_id] = episode
                state["artifacts"][identity] = artifact
                persist_protected_cases(state, artifact)
                state["policy"].get("pending_imports", {}).pop(identity, None)
            return state["artifacts"][identity]

        return runtime.writer.apply(tenant, "register_import", admit)
    pending = {
        "id": identity,
        "source_skill_id": candidate["id"],
        "source_revision": candidate.get("revision", 1),
        "source_cids": artifact["source_cids"],
        "source_origin": origin,
        "state": "pending",
        "reason": artifact.get("pending_reason", "live_import_source_required"),
    }

    def store(state):
        state["policy"].setdefault("pending_imports", {})[identity] = pending
        return pending

    return runtime.writer.apply(tenant, "register_import", store)


def parametric_export(runtime, tenant: str) -> dict:
    """Build a shadow-only export after 200 distinct credited external successes."""
    from mnemosyne.learning import Procedure
    from mnemosyne.parametric import ParametricTier, protected_suite_report

    state = runtime.writer.read(tenant)
    procedures = []
    for artifact in state["artifacts"].values():
        if artifact["kind"] != "procedure" or artifact["state"] != "active":
            continue
        if not runtime._sources_live(
            tenant, artifact["source_cids"], artifact.get("user_id")
        ):
            continue
        verified = set()
        for credit in state["credit"].values():
            if (
                credit["target_id"] != artifact["id"]
                or credit["revision"] != artifact["revision"]
            ):
                continue
            episode = state["episodes"].get(credit["episode_id"], {})
            if episode.get("status") != "resolved" or episode.get("reward", 0) <= 0:
                continue
            if not any(
                signal["kind"] in {"tests", "verifier"} and signal["value"] > 0
                for signal in episode.get("signals", [])
            ):
                continue
            served = [
                item
                for rid in episode.get("receipt_ids", [])
                for item in state["receipts"].get(rid, {}).get("items", [])
            ]
            if any(
                item["item_id"] == artifact["id"]
                and item["revision"] == artifact["revision"]
                for item in served
            ):
                verified.add(episode["id"])
        if len(verified) >= 200:
            procedures.append(
                Procedure(
                    tenant_id=tenant,
                    kind="procedure",
                    name=artifact["id"],
                    body=artifact["content"],
                    signature={"task_class": artifact["task_class"]},
                    status="active",
                    n_trials=len(verified),
                    id=artifact["id"],
                    source_episode_ids=sorted(verified),
                    source_cids=artifact["source_cids"],
                    conditions=artifact.get("conditions", []),
                )
            )
    # This tier deliberately has no trainer. Its existing evaluate method still
    # requires an actual gate result and an active protected suite to promote.
    shadow = ParametricTier().propose_from_lessons(tenant, [], procedures)
    return {
        "schema": "mnemosyne.learning-parametric-export.v1",
        "artifact": shadow.to_dict(),
        "procedures": [item.to_dict() for item in procedures],
        "protected_suite": protected_suite_report(
            getattr(runtime, "protected_cases", [])
        ),
        "protected_suite_required": True,
        "training_started": False,
    }


def erase_derived_policy(state: dict, cid: str, episode_ids: set[str]) -> list[str]:
    """Retract source-dependent derived data within the caller's erasure write."""
    removed = []
    for collection in (
        "knowledge_pages",
        "hypotheses",
        "pending_imports",
        "pattern_splits",
        "protected_cases",
        "reflection_history",
        "reflection_requests",
        "skill_revision_outbox",
    ):
        rows = state["policy"].get(collection, {})
        for key, row in list(rows.items()):
            references = (
                set(row.get("source_episode_ids", []))
                | set(row.get("holdout_episode_ids", []))
                | set(row.get("test_episode_ids", []))
                | set(row.get("episode_ids", []))
            )
            references.update(
                source for group in row.get("groups", []) for source in group[1]
            )
            if cid in row.get("source_cids", []) or references & episode_ids:
                rows.pop(key)
                removed.append(key)
    pages = state["policy"].get("active_knowledge_pages", {})
    for task, key in list(pages.items()):
        if key in removed:
            pages.pop(task)
    for key in episode_ids:
        state["policy"].get("replayed", {}).pop(key, None)
    return removed


def learning_knowledge_context(
    runtime,
    tenant: str,
    user: str,
    task: str,
    query: str,
    *,
    state: dict | None = None,
    selected_artifact_ids: set[str] | None = None,
) -> list[dict]:
    """Publish compiled page views only from applicable, live, active revisions."""
    state = state if state is not None else runtime.writer.read(tenant)
    pages = state["policy"].get("knowledge_pages", {})
    result = []
    for page_id in state["policy"].get("active_knowledge_pages", {}).values():
        page = pages.get(page_id, {})
        if page.get("task_class") != task:
            continue
        artifacts = []
        for reference in page.get("artifact_revisions", []):
            item = state["artifacts"].get(reference["id"])
            if (
                not item
                or item["state"] != "active"
                or item["revision"] != reference["revision"]
            ):
                continue
            if item.get("user_id") != user or not applies_to(item, task, query):
                continue
            if (
                selected_artifact_ids is not None
                and item["id"] not in selected_artifact_ids
            ):
                continue
            if not runtime._sources_live(tenant, item["source_cids"], user):
                continue
            artifacts.append(item)
        if not artifacts:
            continue
        references = [
            {"id": item["id"], "revision": item["revision"]} for item in artifacts
        ]
        result.append(
            {
                "id": digest([page_id, references]),
                "compiled_page_id": page_id,
                "task_class": task,
                "content": "\n\n".join(item["content"] for item in artifacts),
                "artifact_revisions": references,
                "source_cids": sorted(
                    {cid for item in artifacts for cid in item["source_cids"]}
                ),
                "source_episode_ids": sorted(
                    {key for item in artifacts for key in item["source_episode_ids"]}
                ),
                "explanations": [
                    {
                        "artifact_id": item["id"],
                        "text": item["explanation"],
                        "source_episode_ids": item["explanation_sources"],
                    }
                    for item in artifacts
                ],
                "instruction_authority": "none",
                "capability_tags": ["data-only", "no-write-authority"],
            }
        )
    return result


def materialize_framework(
    runtime, tenant: str, user: str, artifact: dict, state: dict
) -> dict:
    """Resolve immutable framework ancestry without making retired revisions servable."""
    chain, visited = [], set()
    item = artifact
    while item:
        if item["id"] in visited or item.get("user_id") != user:
            return {"valid": False, "nodes": [], "reason": "invalid_framework_ancestry"}
        if not runtime._sources_live(tenant, item.get("source_cids", []), user):
            return {
                "valid": False,
                "nodes": [],
                "reason": "framework_source_unavailable",
            }
        visited.add(item["id"])
        chain.append(item)
        reference = item.get("framework", {}).get("base_revision")
        if not reference:
            break
        parent = state["artifacts"].get(reference["id"])
        if not parent or parent["revision"] != reference["revision"]:
            return {"valid": False, "nodes": [], "reason": "framework_revision_missing"}
        if parent["state"] in {"archived", "rejected"} or (
            parent["state"] == "retired" and parent.get("superseded_by") != item["id"]
        ):
            return {
                "valid": False,
                "nodes": [],
                "reason": "framework_revision_withdrawn",
            }
        item = parent
    nodes = []
    for item in reversed(chain):
        for node in item.get("framework", {}).get("nodes", []):
            nodes.append(
                {
                    **deepcopy(node),
                    "source_revision": {"id": item["id"], "revision": item["revision"]},
                }
            )
    return {
        "valid": True,
        "nodes": nodes,
        "artifact_revisions": [
            {"id": item["id"], "revision": item["revision"]} for item in reversed(chain)
        ],
        "source_cids": sorted({cid for item in chain for cid in item["source_cids"]}),
        "instruction_authority": "none",
        "capability_tags": ["data-only", "no-write-authority"],
    }


def verification_request_id(artifact: dict) -> str:
    return digest(
        [
            "revalidate",
            artifact["id"],
            artifact["revision"],
            artifact["next_revalidation_at"],
        ]
    )


def verification_requests(
    runtime, tenant: str, user: str, task: str, query: str, *, state: dict | None = None
) -> list[dict]:
    """Expose data-only test requests to the host's real tool execution loop."""
    state = state if state is not None else runtime.writer.read(tenant)
    timestamp = datetime.now(UTC)
    requests = []
    for item in state["artifacts"].values():
        if (
            item["state"] not in {"active", "labile", "probation", "demoted"}
            or item.get("pinned")
            or item.get("locked")
        ):
            continue
        if item.get("user_id") != user or not applies_to(item, task, query):
            continue
        if timestamp < datetime.fromisoformat(item["next_revalidation_at"]):
            continue
        if not runtime._sources_live(tenant, item["source_cids"], user):
            continue
        requests.append(
            {
                "id": verification_request_id(item),
                "kind": "revalidation",
                "artifact_id": item["id"],
                "revision": item["revision"],
                "steps": item["steps"],
                "source_cids": item["source_cids"],
                "reply_field": "revalidation_request_id",
                "reward_weight": 0.0,
                "instruction_authority": "none",
                "capability_tags": ["data-only", "no-write-authority"],
            }
        )
    for item in state["policy"].get("hypotheses", {}).values():
        if (
            item.get("status") in {"verified", "rejected"}
            or item.get("user_id") != user
        ):
            continue
        if not applies_to(item, task, query) or not runtime._sources_live(
            tenant, item["source_cids"], user
        ):
            continue
        requests.append(
            {
                "id": item["id"],
                "kind": "hypothesis" if item.get("steps") else "hypothesis_review",
                "content": item["content"],
                "steps": item.get("steps", []),
                "source_cids": item["source_cids"],
                "reply_field": "hypothesis_id",
                "reward_weight": 0.0,
                "instruction_authority": "none",
                "capability_tags": ["data-only", "no-write-authority"],
            }
        )
    for key, item in state["policy"].get("reflection_requests", {}).items():
        parent = state["artifacts"].get(item.get("incumbent_id"))
        if (
            item.get("user_id") == user
            and item.get("task_class") == task
            and parent
            and applies_to(parent, task, query)
            and runtime._sources_live(tenant, item.get("source_cids", []), user)
        ):
            requests.append(
                {
                    **item,
                    "id": key,
                    "kind": "reflection",
                    "steps": parent["steps"],
                    "reply_field": "reflection_id",
                    "reward_weight": 0.0,
                    "instruction_authority": "none",
                    "capability_tags": ["data-only", "no-write-authority"],
                }
            )
    return requests
