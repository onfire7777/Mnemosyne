"""Evaluation guards for consolidation and self-improvement."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class NoDegradationResult:
    passed: bool
    memory_score: float
    no_memory_baseline: float
    margin: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def no_degradation_guard(memory_score: float, no_memory_baseline: float, minimum_margin: float = 0.0) -> NoDegradationResult:
    margin = memory_score - no_memory_baseline
    if margin >= minimum_margin:
        return NoDegradationResult(True, memory_score, no_memory_baseline, margin, "memory is non-inferior to baseline")
    return NoDegradationResult(False, memory_score, no_memory_baseline, margin, "memory degraded below no-memory baseline")

