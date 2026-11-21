"""Outcome-grounded selection over already eligible memories.

This uses the existing guarded three-factor credit ledger, not a second model.
Exposure alone and an assistant's confidence never create utility.
"""

from __future__ import annotations

import os
import shlex

from .receipts import digest

_EXCLUDED_CITATION_SOURCES = frozenset({"assistant", "self_generated", "provider_self_grade"})
_MEMORY_READ_TOOL_SUFFIXES = frozenset({
    "skill_get",
    "knowledge_page_get",
    "observation_get",
    "memory_retrieve",
    "memory_retrieve_deep",
    "prepare_context",
})


def _is_memory_read_tool(event: dict) -> bool:
    name = str(event.get("name", "")).strip().lower()
    if not name:
        return False
    leaf = name.rsplit(".", 1)[-1].rsplit("__", 1)[-1]
    return leaf in _MEMORY_READ_TOOL_SUFFIXES or name.startswith("mnemosyne.")


def _event_file_paths(event: dict, cwd: str | None) -> set[str]:
    """Extract normalized file paths demonstrably targeted by an executed tool event."""
    paths: set[str] = set()
    candidates: list[str] = []
    for key in ("path", "file_path"):
        val = event.get(key)
        if isinstance(val, str) and val.strip():
            candidates.append(val.strip())
    arguments = event.get("arguments")
    if isinstance(arguments, dict):
        for key in ("path", "file_path"):
            val = arguments.get(key)
            if isinstance(val, str) and val.strip():
                candidates.append(val.strip())
    argv = event.get("argv")
    if not isinstance(argv, list):
        cmd = event.get("command")
        if isinstance(cmd, list):
            argv = cmd
        elif isinstance(cmd, str) and cmd.strip():
            try:
                argv = shlex.split(cmd)
            except ValueError:
                argv = []
        else:
            argv = []
    for token in argv[1:] if isinstance(argv, list) and len(argv) > 1 else []:
        if not isinstance(token, str) or not token or token.startswith("-") or "\0" in token:
            continue
        if "/" in token or "." in token:
            candidates.append(token)
    for raw in candidates:
        if "\0" in raw or len(raw) > 1024:
            continue
        if os.path.isabs(raw):
            paths.add(os.path.normpath(raw))
        elif cwd:
            paths.add(os.path.normpath(os.path.join(cwd, raw)))
    return paths


def _event_matches_contract(event: dict, contract: dict) -> bool:
    """Return True only when an external tool execution matches a frozen contract."""
    if event.get("source") != "tool" or event.get("evidence_rejected"):
        return False
    if _is_memory_read_tool(event):
        return False
    status = event.get("status")
    if status not in {None, "ok", "completed", "complete", "success", "succeeded", "failed", "failure"}:
        return False
    from mnemosyne.hosts.memory_checks import _same_workspace, command_argv
    from mnemosyne.local_paths import normalize_workspace

    kind = contract.get("kind")
    if kind == "command_observation":
        expected_argv = contract.get("argv")
        if not expected_argv:
            return False
        actual_argv = command_argv(event.get("argv") if event.get("argv") is not None else event.get("command"))
        return bool(
            actual_argv == expected_argv
            and _same_workspace(event.get("cwd"), contract.get("cwd"))
        )
    if kind == "structured_observation":
        expected_file = contract.get("file")
        if not isinstance(expected_file, str) or not expected_file:
            return False
        workspace = contract.get("workspace")
        if workspace and event.get("cwd") and not _same_workspace(event.get("cwd"), workspace):
            return False
        cwd = normalize_workspace(event.get("cwd")) or normalize_workspace(workspace)
        target_paths = _event_file_paths(event, cwd)
        return os.path.normpath(expected_file) in target_paths
    return False


def cited_memory_ids(events, receipts, source_is_live):
    """Admit actual-use references only to this turn's live, served memory.

    Hosts may report application without grading it. External checks still
    determine target outcomes independently in ``verified_target_outcome``.
    Passive attribution admits served items only when executed tool calls
    demonstrably match frozen command/file verification contracts or carry
    structured item references (never assistant text or memory reads).
    A raw citation to another tenant, turn, or expired source proves nothing.
    """
    by_receipt = {receipt["id"]: {item["item_id"] for item in receipt.get("items", [])
                                 if item.get("kind") == "item"}
                  for receipt in receipts}
    served = set().union(*by_receipt.values()) if by_receipt else set()
    sources = {item: receipt.get("item_sources", {}).get(item, [item])
               for receipt in receipts for item in by_receipt[receipt["id"]]}
    contracts_by_receipt = {
        receipt["id"]: receipt.get("item_verification_contracts", {})
        for receipt in receipts
        if receipt.get("item_verification_contracts")
    }
    cited = set()
    for event in events:
        if not isinstance(event, dict) or event.get("source") in _EXCLUDED_CITATION_SOURCES:
            continue
        allowed = by_receipt.get(event["receipt_id"], set()) if "receipt_id" in event else served
        if not allowed:
            continue
        claims = event.get("claims")
        if isinstance(claims, list):
            for claim in claims:
                cids = claim.get("evidence_cids") if isinstance(claim, dict) else None
                if not isinstance(cids, list):
                    continue
                cited.update(cid for cid in cids if isinstance(cid, str) and cid in allowed)
        if event.get("source") == "tool" and not event.get("evidence_rejected") and not _is_memory_read_tool(event):
            for field in ("referenced_cids", "cited_cids"):
                refs = event.get(field)
                if isinstance(refs, list):
                    cited.update(cid for cid in refs if isinstance(cid, str) and cid in allowed)
            if contracts_by_receipt:
                candidate_receipts = (
                    [contracts_by_receipt[event["receipt_id"]]]
                    if "receipt_id" in event and event["receipt_id"] in contracts_by_receipt
                    else ([] if "receipt_id" in event else list(contracts_by_receipt.values()))
                )
                for contract_map in candidate_receipts:
                    for item_id, contracts in contract_map.items():
                        if item_id not in allowed or item_id in cited or not isinstance(contracts, list):
                            continue
                        if any(isinstance(contract, dict) and _event_matches_contract(event, contract)
                               for contract in contracts):
                            cited.add(item_id)
    return sorted(cid for cid in cited if sources[cid] and source_is_live(sources[cid]))


def applied_target(episode, kind, target):
    """Require both application evidence and that target's external outcome."""
    if target not in episode.get("target_outcomes", {}):
        return False
    if kind == "item":
        return target in episode.get("cited_cids", [])
    if kind == "lesson":
        return target in episode.get("used_lessons", [])
    if kind in {"procedure", "skill", "chunk"}:
        return target in episode.get("used_skills", []) or any(
            target in event.get("target_ids", [])
            for event in episode.get("tool_events", [])
            if event.get("source") == "tool"
        )
    return False


def selection_utility(state, kind, target, revision, task, *, user_id=None):
    """Ignore legacy ungrounded credit while retaining immutable history.

    The persisted utility still controls the magnitude and rollback behavior;
    only a ledger with actually applied, independently evaluated targets can
    influence selection. Old exposure-only weights therefore stop leaking in.
    """
    key = digest([kind, target, revision, task])
    valid = []
    for row in state.get("credit", {}).values():
        if (row.get("target_kind"), row.get("target_id"), row.get("revision"), row.get("task_class")) != (kind, target, revision, task):
            continue
        episode = state.get("episodes", {}).get(row.get("episode_id"), {})
        if user_id is not None and episode.get("user_id") != user_id:
            continue
        if row.get("evidence_version", 0) >= 3 and applied_target(episode, kind, target):
            valid.append(row)
    if not valid:
        return 1.0
    # Include only demonstrably grounded increments. The stats bound also
    # respects homeostasis and explicit rollback's reduction toward neutrality.
    supported = max(0.8, min(1.2, 1.0 + sum(row.get("step", 0) for row in valid)))
    stored = state.get("stats", {}).get(key, {}).get("utility", 1.0)
    if (supported - 1) * (stored - 1) <= 0:
        return 1.0
    return 1.0 + (1 if supported > 1 else -1) * min(abs(supported - 1), abs(stored - 1))


def exposure_record(eligible, served_ids, *, probabilities=None):
    """Freeze selection opportunities, with known randomized propensities.

    Missing propensity is explicit, and must not be interpreted as a randomized
    counterfactual. Deterministically retained protected items have p=1.
    """
    probabilities = probabilities or {}
    return [{"item_id": row["id"], "kind": "item", "revision": 1,
             "served": row["id"] in served_ids,
             "propensity": probabilities.get(row["id"]),
             "selection_score": float(row.get("score", 0)),
             "utility": row.get("learning_utility", 1.0)} for row in eligible]


def artifact_exposure_record(eligible, served_ids, *, probation_trial=None, revision_trial=None):
    """Known paired allocations only; Thompson selection has unknown propensity."""
    probation_trial, revision_trial = probation_trial or {}, revision_trial or {}
    candidate = next((row for row in eligible if row["id"] == revision_trial.get("candidate_id")), {})
    pair = {candidate.get("id"), candidate.get("parent_revision")}
    rows = []
    for artifact in eligible:
        identifier = artifact["id"]
        probability = None
        intended = identifier in served_ids
        if identifier == probation_trial.get("candidate_id") and artifact["revision"] == probation_trial.get("revision"):
            probability = 0.5
            intended = probation_trial.get("arm") == "served"
        elif identifier in pair and candidate:
            probability = 0.5
            intended = identifier == (candidate["id"] if revision_trial.get("arm") == "candidate" else candidate.get("parent_revision"))
        # A composition drop invalidates the allocated treatment, never turns
        # that treatment into a control sample.
        if intended and identifier not in served_ids:
            probability = None
        rows.append({"item_id": identifier, "kind": artifact["kind"], "revision": artifact["revision"],
                     "served": identifier in served_ids, "propensity": probability,
                     "selection_score": artifact.get("lower_bound", 0),
                     "utility": artifact.get("learning_utility", 1.0)})
    return rows


def randomized_opportunity(episode, receipts, kind, target, revision):
    """Return a frozen serve/control propensity only for comparable trials."""
    exposures = [row for receipt in receipts for row in receipt.get("selection_exposures", [])
                 if (row.get("kind"), row.get("item_id"), row.get("revision")) == (kind, target, revision)]
    if not exposures:
        return None
    # Multiple retrievals are one opportunity; if allocation changes within an
    # episode there is no unambiguous control group for that episode.
    identities = {(row.get("served"), row.get("propensity")) for row in exposures}
    if len(identities) != 1:
        return None
    served, probability = next(iter(identities))
    if type(probability) not in {float, int} or not 0 < probability < 1:
        return None
    return {"served": bool(served), "propensity": probability,
            "inverse_propensity": 1 / (probability if served else 1 - probability)}
