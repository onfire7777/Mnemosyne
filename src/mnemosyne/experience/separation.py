"""Deterministic context separation accepted only on independent held-out cases."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

from .candidates import candidate_score, expected_steps
from .receipts import digest


def _cosine(left: str, right: str) -> float:
    a, b = (
        Counter(re.findall(r"\w+", left.lower())),
        Counter(re.findall(r"\w+", right.lower())),
    )
    denominator = math.sqrt(
        sum(v * v for v in a.values()) * sum(v * v for v in b.values())
    )
    return (
        sum(value * b[token] for token, value in a.items()) / denominator
        if denominator
        else 0.0
    )


def _targets(state: dict, episode: dict) -> set[str]:
    return {
        item["item_id"]
        for rid in episode["receipt_ids"]
        for item in state["receipts"].get(rid, {}).get("items", [])
    }


def propose_splits(state: dict) -> list[dict]:
    by_task = defaultdict(list)
    for episode in state["episodes"].values():
        if episode["status"] == "resolved":
            by_task[episode["task_class"]].append(episode)
    proposals = []
    for task, episodes in by_task.items():
        opposite = any(
            left["reward"] * right["reward"] < 0
            and _cosine(left["user_text"], right["user_text"]) >= 0.85
            and _targets(state, left) & _targets(state, right)
            for index, left in enumerate(episodes)
            for right in episodes[index + 1 :]
        )
        if not opposite:
            continue
        features = defaultdict(lambda: defaultdict(list))
        for episode in episodes:
            for event in episode.get("tool_events", []):
                if event.get("source") in {
                    "assistant",
                    "self_generated",
                    "provider_self_grade",
                }:
                    continue
                for key, value in event.get("context_features", {}).items():
                    if (
                        isinstance(value, str)
                        and value
                        and value.casefold() in episode["user_text"].casefold()
                    ):
                        if episode not in features[key][value]:
                            features[key][value].append(episode)
        for feature, groups in features.items():
            if len(groups) != 2 or any(len(rows) < 4 for rows in groups.values()):
                continue
            training, holdouts, sequences = [], [], []
            for value, rows in sorted(groups.items()):
                rows = sorted(rows, key=lambda e: (e["created_at"], e["id"]))
                train, heldout = rows[::2], rows[1::2]
                orders = [steps for row in train for steps in expected_steps(row)]
                if not orders or any(steps != orders[0] for steps in orders):
                    break
                training.append((value, train))
                holdouts.append(heldout)
                sequences.append(orders[0])
            if len(sequences) != 2 or sequences[0] == sequences[1]:
                continue
            # The incumbent is the actual overlapping learned procedure.
            shared = set.intersection(
                *[_targets(state, row) for rows in groups.values() for row in rows]
            )
            incumbents = [
                state["artifacts"][key]
                for key in sorted(shared)
                if key in state["artifacts"]
            ]
            for incumbent in incumbents:
                before, after = [], []
                for sequence, rows in zip(sequences, holdouts, strict=True):
                    baseline = [candidate_score(incumbent, row) for row in rows]
                    scores = [candidate_score({"steps": sequence}, row) for row in rows]
                    if None in baseline or None in scores:
                        break
                    before.append(sum(baseline) / len(baseline))
                    after.append(sum(scores) / len(scores))
                if len(before) == 2 and all(
                    a > b for a, b in zip(after, before, strict=True)
                ):
                    proposals.append(
                        {
                            "id": digest([task, feature, sequences]),
                            "task_class": task,
                            "feature": feature,
                            "groups": [
                                (value, [row["id"] for row in rows], steps)
                                for (value, rows), steps in zip(
                                    training, sequences, strict=True
                                )
                            ],
                            "before": before,
                            "after": after,
                            "holdout_episode_ids": [
                                row["id"] for rows in holdouts for row in rows
                            ],
                        }
                    )
                    break
    return proposals
