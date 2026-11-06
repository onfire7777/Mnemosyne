"""Seeded policy over surfaced memory. No in-agent learning or gold lookup."""

from __future__ import annotations

import random
import json
from collections.abc import Mapping
from typing import Any

from .families import Task


def as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict"):
        return value.to_dict()
    raise TypeError("runtime results must be mappings or expose to_dict()")


class ScriptedAgent:
    def __init__(self, seed: int, epsilon: float = 0.1):
        if epsilon != 0.1:
            raise ValueError("the preregistered exploration rate is 0.1")
        self.rng = random.Random(seed)
        self.epsilon = epsilon

    def act(
        self,
        task: Task,
        context: Mapping[str, Any],
        *,
        explore: bool = True,
    ) -> tuple[str, list[str], list[str]]:
        epsilon = self.epsilon if explore else 0.0
        procedures = list(context.get("procedures", [])) + list(
            context.get("skills", [])
        )
        lessons = list(context.get("lessons", []))
        for kind, artifacts in [
            ("procedure", procedures),
            ("chunk", list(context.get("chunks", []))),
            ("lesson", lessons),
        ]:
            if not artifacts:
                continue
            top = artifacts[0]
            raw = (
                top
                if isinstance(top, str)
                else top.get("steps", top.get("text", top.get("content", "")))
            )
            text = " -> ".join(raw) if isinstance(raw, list) else str(raw)
            matches = [choice for choice in task.choices if choice in text]
            if not matches and kind == "chunk" and text:
                matches = [
                    choice
                    for choice in task.choices
                    if choice.startswith(text + " -> ")
                ]
            if not matches and kind == "lesson" and "json" in text.lower():
                # A fixed interpreter of an explicit format lesson, not a learned
                # cache or an oracle lookup. The same rule applies in every arm.
                for choice in task.choices:
                    try:
                        parsed = json.loads(choice)
                    except (ValueError, TypeError):
                        continue
                    if isinstance(parsed, dict) and "status" in parsed:
                        matches.append(choice)
            if matches and self.rng.random() >= epsilon:
                identifier = (
                    top.get("id", top.get("skill_id", ""))
                    if isinstance(top, Mapping)
                    else ""
                )
                return (
                    matches[0],
                    [identifier]
                    if kind in {"procedure", "chunk"} and identifier
                    else [],
                    [identifier] if kind == "lesson" and identifier else [],
                )
        hits = context.get("hits", context.get("retrieval", {}).get("hits", []))
        if hits and self.rng.random() >= epsilon:
            top = as_mapping(hits[0])
            matches = [
                choice for choice in task.choices if choice in top.get("text", "")
            ]
            if matches:
                return matches[0], [], []
        return self.rng.choice(task.choices), [], []
