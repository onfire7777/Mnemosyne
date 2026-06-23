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


@dataclass(slots=True)
class LongHorizonDegradationResult:
    """Horizon-level verdict of the anti-degradation metric (§25)."""

    passed: bool
    samples: int
    worst_margin: float
    mean_margin: float
    final_margin: float
    breaches: list[int]
    first_breach: int | None
    trend: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _linear_trend(values: list[float]) -> float:
    """Least-squares slope of ``values`` over their indices.

    A non-negative slope means the margin (memory minus no-memory baseline) is not
    eroding across the horizon. Returns ``0.0`` for fewer than two samples.
    """
    n = len(values)
    if n < 2:
        return 0.0
    mean_x = (n - 1) / 2
    mean_y = sum(values) / n
    numerator = sum((i - mean_x) * (value - mean_y) for i, value in enumerate(values))
    denominator = sum((i - mean_x) ** 2 for i in range(n))
    if denominator == 0:
        return 0.0
    return numerator / denominator


class LongHorizonNoDegradationTracker:
    """Tracks the §25 anti-"Useful-Memories-Become-Faulty" metric over a horizon.

    ``no_degradation_guard`` answers "is memory non-inferior *right now*?". The
    blueprint additionally requires a *tracked* long-horizon metric proving that
    consolidated memory never drops below the no-memory baseline across many
    evaluations — consolidated summaries can drift and confabulate over time, so a
    single point-check is insufficient. Each :meth:`record` accumulates one
    ``(memory_score, no_memory_baseline)`` evaluation; :meth:`evaluate` reports
    horizon-level health (worst/mean/final margin, breach indices, and the margin
    trend), so dashboards and the promotion gate can act on long-range degradation.
    """

    def __init__(self, minimum_margin: float = 0.0) -> None:
        self.minimum_margin = minimum_margin
        self._memory_scores: list[float] = []
        self._baselines: list[float] = []

    @property
    def samples(self) -> int:
        return len(self._memory_scores)

    def record(self, memory_score: float, no_memory_baseline: float) -> NoDegradationResult:
        """Append one evaluation and return its point-check verdict."""
        self._memory_scores.append(memory_score)
        self._baselines.append(no_memory_baseline)
        return no_degradation_guard(memory_score, no_memory_baseline, self.minimum_margin)

    def evaluate(self) -> LongHorizonDegradationResult:
        """Summarise the full horizon; ``passed`` is False if any sample breached."""
        if not self._memory_scores:
            return LongHorizonDegradationResult(
                passed=True,
                samples=0,
                worst_margin=0.0,
                mean_margin=0.0,
                final_margin=0.0,
                breaches=[],
                first_breach=None,
                trend=0.0,
                reason="no samples recorded",
            )
        margins = [memory - baseline for memory, baseline in zip(self._memory_scores, self._baselines)]
        breaches = [index for index, margin in enumerate(margins) if margin < self.minimum_margin]
        passed = not breaches
        reason = (
            "memory stayed non-inferior to the no-memory baseline across the horizon"
            if passed
            else f"memory dropped below the no-memory baseline at {len(breaches)} of {len(margins)} evaluations"
        )
        return LongHorizonDegradationResult(
            passed=passed,
            samples=len(margins),
            worst_margin=min(margins),
            mean_margin=sum(margins) / len(margins),
            final_margin=margins[-1],
            breaches=breaches,
            first_breach=breaches[0] if breaches else None,
            trend=_linear_trend(margins),
            reason=reason,
        )

