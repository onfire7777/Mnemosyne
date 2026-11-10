"""Derive transferable-strategy evidence from complete randomized task pairs."""

from __future__ import annotations

from collections import defaultdict


def strategy_trial_stats(state, artifact):
    from .signals import reward, verified_target_outcome
    from .strategies import strategy_applies, validated_strategy
    from .receipts import digest
    empty = {"alpha": 1.0, "beta": 1.0, "n": 0, "served_n": 0, "served_successes": 0.0,
             "verified_n": 0, "verified_successes": 0.0, "control_n": 0,
             "control_successes": 0.0, "matched_pairs": []}
    if not validated_strategy(artifact, state["episodes"], state["receipts"]):
        return empty
    groups = defaultdict(dict)
    ambiguous = set()
    for episode in state["episodes"].values():
        if (episode.get("status") != "resolved" or episode.get("tenant_id") != artifact.get("tenant_id")
                or episode.get("user_id") != artifact.get("user_id")):
            continue
        for receipt_id in episode.get("receipt_ids", []):
            receipt = state["receipts"].get(receipt_id, {})
            trial = receipt.get("probation_trial") or {}
            index, arm = trial.get("index"), trial.get("arm")
            if (trial.get("candidate_id") != artifact["id"] or trial.get("revision") != artifact["revision"]
                    or type(index) is not int or index < 0 or arm not in {"served", "control"}
                    or receipt.get("tenant_id") != artifact.get("tenant_id")
                    or receipt.get("user_id") != artifact.get("user_id")
                    or receipt.get("session_id") != episode.get("session_id")
                    or receipt.get("task_class") != episode.get("task_class")
                    or not strategy_applies(artifact, receipt.get("query", ""),
                        tools=receipt.get("available_tools", []), risk=receipt.get("risk_level", "normal"),
                        workspace=receipt.get("workspace"), require_workspace=True)):
                continue
            present = any(item.get("item_id") == artifact["id"] and item.get("revision") == artifact["revision"]
                          for item in receipt.get("items", []))
            if present != (arm == "served"):
                continue
            assignment = digest([artifact["tenant_id"], artifact["user_id"], episode["task_class"],
                                 artifact["id"], artifact["revision"], index // 2])
            expected_served = (index % 2 == 0) == (int(assignment[:16], 16) % 2 == 0)
            if present != expected_served:
                continue
            value = verified_target_outcome(artifact, episode) if present else reward([
                signal for signal in episode.get("signals", []) if signal.get("kind") in {"tests", "verifier"}])
            if value is None:
                continue
            key = (episode["task_class"], index // 2)
            if arm in groups[key]:
                ambiguous.add(key)
            groups[key][arm] = {"episode_id": episode["id"], "receipt_id": receipt_id,
                                "probability": (value + 1) / 2}
    result = dict(empty)
    used = set()
    for key, pair in sorted(groups.items()):
        if key in ambiguous or set(pair) != {"served", "control"}:
            continue
        ids = {row["episode_id"] for row in pair.values()}
        if len(ids) != 2 or ids & used:
            continue
        used.update(ids)
        result["matched_pairs"].append({"task_class": key[0], "pair_index": key[1], **pair})
        result["served_successes"] += pair["served"]["probability"]
        result["control_successes"] += pair["control"]["probability"]
    count = len(result["matched_pairs"])
    result.update(n=count, served_n=count, verified_n=count, control_n=count,
                  verified_successes=result["served_successes"], alpha=1 + result["served_successes"],
                  beta=1 + count - result["served_successes"])
    return result
