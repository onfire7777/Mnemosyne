"""Outcome-grounded selection over already eligible memories.

This uses the existing guarded three-factor credit ledger, not a second model.
Exposure alone and an assistant's confidence never create utility.
"""

from __future__ import annotations

from .receipts import digest


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
