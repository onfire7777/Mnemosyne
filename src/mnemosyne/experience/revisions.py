"""Immutable content revisions and externally scored revision trials."""

from __future__ import annotations

from .receipts import digest
from .stats import Posterior, prob_better


def ab_assignment(tenant: str, task: str, trial_key: str, incumbent_id: str) -> str:
    """Stable assignment before either arm's result is known."""
    return (
        "candidate"
        if int(digest([tenant, task, trial_key, incumbent_id])[:16], 16) % 2
        else "incumbent"
    )


def ab_decision(
    candidate_successes: float,
    candidate_n: int,
    incumbent_successes: float,
    incumbent_n: int,
) -> str:
    if min(candidate_n, incumbent_n) < 8:
        return "inconclusive" if candidate_n + incumbent_n >= 40 else "pending"
    chance = prob_better(
        Posterior(
            1 + candidate_successes, 1 + candidate_n - candidate_successes, candidate_n
        ),
        Posterior(
            1 + incumbent_successes, 1 + incumbent_n - incumbent_successes, incumbent_n
        ),
    )
    if chance >= 0.9:
        return "promote"
    if chance <= 0.1:
        return "revert"
    return "inconclusive" if candidate_n + incumbent_n >= 40 else "pending"


def inherit_library_lineage(candidate: dict, parent: dict) -> None:
    """A new native revision must not masquerade as its parent's library row."""
    skill_id = parent.get("source_skill_id") or parent.get("source_library_skill_id")
    if not skill_id:
        return
    candidate["source_library_skill_id"] = skill_id
    candidate["source_library_parent_revision"] = parent.get("source_skill_revision")
    candidate["source_library_parent_artifact"] = parent["id"]
    candidate.pop("source_skill_id", None)
    candidate.pop("source_skill_revision", None)


def install_revision(
    state: dict, candidate: dict, parent_id: str, expected_revision: int
) -> None:
    parent = state["artifacts"][parent_id]
    if parent.get("locked") or parent.get("pinned"):
        raise ValueError("protected artifact refuses learned revision")
    if parent["revision"] != expected_revision or parent.get("pending_revision"):
        raise ValueError("artifact revision conflict")
    existing = state["artifacts"].get(candidate["id"])
    if existing and (
        existing["state"] != "candidate"
        or existing.get("locked")
        or existing.get("pinned")
        or existing["content"] != candidate["content"]
        or existing["steps"] != candidate["steps"]
        or existing["revision"] != candidate["revision"]
    ):
        raise ValueError("artifact revision already exists")
    if parent["state"] in {"archived", "retired", "rejected"}:
        raise ValueError("terminal artifact requires an independent candidate")
    candidate.update(parent_revision=parent_id, revision=expected_revision + 1)
    inherit_library_lineage(candidate, parent)
    candidate["ab_trial"] = {
        "incumbent_id": parent_id,
        "status": "pending",
        "candidate_n": 0,
        "incumbent_n": 0,
        "candidate_successes": 0.0,
        "incumbent_successes": 0.0,
        "episode_ids": [],
    }
    parent["pending_revision"] = candidate["id"]
    state["artifacts"][candidate["id"]] = candidate


def _trial_evidence(state: dict, candidate: dict, parent: dict, trial: dict) -> dict:
    for episode in sorted(state["episodes"].values(), key=lambda e: (e["created_at"], e["id"])):
        if (
            episode["status"] != "resolved" or episode["id"] in trial["episode_ids"]
            or episode["task_class"] != candidate["task_class"]
            or episode["created_at"] <= candidate["created_at"]
        ):
            continue
        assignments = [state["receipts"][rid].get("revision_trial")
                       for rid in episode["receipt_ids"] if rid in state["receipts"]]
        assignment = next((value for value in assignments
                           if value and value.get("candidate_id") == candidate["id"]), None)
        if not assignment:
            continue
        arm = assignment.get("arm")
        expected = ab_assignment(episode["tenant_id"], candidate["task_class"],
                                 assignment["trial_key"], parent["id"])
        if arm != expected:
            continue
        target = candidate if arm == "candidate" else parent
        served = [item for rid in episode["receipt_ids"]
                  for item in state["receipts"][rid]["items"]]
        if not any(item["item_id"] == target["id"] and item["revision"] == target["revision"]
                   for item in served):
            continue
        result = episode.get("target_outcomes", {}).get(target["id"])
        if episode.get("outcome_version", 1) >= 2 and result is None:
            continue
        value = result["value"] if result is not None else episode["reward"]
        trial[arm + "_n"] += 1
        trial[arm + "_successes"] += (value + 1) / 2
        trial["episode_ids"].append(episode["id"])
        if ab_decision(trial["candidate_successes"], trial["candidate_n"],
                       trial["incumbent_successes"], trial["incumbent_n"]) != "pending":
            break
    trial["status"] = ab_decision(trial["candidate_successes"], trial["candidate_n"],
                                  trial["incumbent_successes"], trial["incumbent_n"])
    return trial


def recompute_trial(state: dict, candidate: dict) -> dict:
    """Rebuild a prior trial solely from its original assigned observations."""
    trial = {**candidate["ab_trial"], "status": "pending", "candidate_n": 0,
             "incumbent_n": 0, "candidate_successes": 0.0,
             "incumbent_successes": 0.0, "episode_ids": []}
    parent = state["artifacts"].get(trial["incumbent_id"])
    return _trial_evidence(state, candidate, parent, trial) if parent else trial


def score_trials(state: dict) -> None:
    for candidate in list(state["artifacts"].values()):
        trial = candidate.get("ab_trial")
        if (not trial or trial["status"] != "pending" or candidate["state"] != "probation"
                or candidate.get("pinned") or candidate.get("locked")):
            continue
        parent = state["artifacts"].get(trial["incumbent_id"])
        if not parent or parent.get("pinned") or parent.get("locked"):
            continue
        trial = _trial_evidence(state, candidate, parent, trial)
        decision = trial["status"]
        if decision == "pending":
            continue
        if decision == "promote":
            candidate["ab_passed"] = True
        else:
            candidate["state"] = "retired"
            parent.pop("pending_revision", None)
            state["policy"].setdefault("reflection_queue", {})[candidate["id"]] = {
                "reason": "revision_" + decision,
                "episode_ids": trial["episode_ids"][:], "incumbent_id": parent["id"],
            }


def propagate_children(state: dict) -> None:
    """Propagate blocked children through a dependency DAG without revival."""
    for _ in range(len(state["artifacts"])):
        changed = False
        for parent in state["artifacts"].values():
            if (
                parent.get("pinned")
                or parent.get("locked")
                or parent["state"] not in {"active", "labile", "probation"}
            ):
                continue
            children = [
                state["artifacts"].get(ref["id"]) for ref in parent.get("children", [])
            ]
            invalid = any(
                child is None
                or child["revision"] != ref["revision"]
                or child["state"]
                in {"candidate", "demoted", "retired", "archived", "rejected"}
                for ref, child in zip(parent.get("children", []), children, strict=True)
            )
            labile = any(child and child["state"] == "labile" for child in children)
            target = (
                "demoted" if invalid else "labile"
                if labile and parent["state"] == "active" else parent["state"]
            )
            if target != parent["state"]:
                parent["state"] = target
                changed = True
        if not changed:
            break
