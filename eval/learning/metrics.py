"""Paired seed-level learning statistics using the shared bootstrap."""

from __future__ import annotations

from collections.abc import Sequence
import math
from eval.harness.metrics import bootstrap_mean_interval, percentile


def learning_metrics(
    successes: Sequence[bool], latencies_ms: Sequence[float], *, flip: int | None = None
) -> dict:
    values = [float(value) for value in successes]
    if not values:
        raise ValueError("at least one episode is required")
    window = min(10, len(values))
    curve = [
        sum(values[max(0, i - window + 1) : i + 1])
        / len(values[max(0, i - window + 1) : i + 1])
        for i in range(len(values))
    ]
    episodes_to_80 = next(
        (i + 1 for i in range(window - 1, len(values)) if curve[i] >= 0.8), None
    )
    recovery = (
        None
        if flip is None
        else next(
            (
                i - flip + 1
                for i in range(flip + window - 1, len(values))
                if curve[i] >= 0.8
            ),
            None,
        )
    )
    midpoint = (len(curve) - 1) / 2
    slope = sum((i - midpoint) * value for i, value in enumerate(curve)) / (
        sum((i - midpoint) ** 2 for i in range(len(curve))) or 1
    )
    return {
        "learning_curve": curve,
        "aulc": sum(curve) / len(curve),
        "final_window_success": sum(values[-window:]) / window,
        "episodes_to_80": episodes_to_80,
        "recovery_after_flip": recovery,
        "slope": slope,
        "p95_latency_ms": percentile(sorted(latencies_ms), 0.95)
        if latencies_ms
        else 0.0,
    }


def paired_interval(
    candidate: Sequence[float], baseline: Sequence[float], *, seed: int = 1234
) -> dict:
    if len(candidate) != len(baseline) or not candidate:
        raise ValueError("paired seed results must be nonempty and equally sized")
    if any(not math.isfinite(value) for value in (*candidate, *baseline)):
        raise ValueError("paired seed results must be finite")
    interval = bootstrap_mean_interval(
        [a - b for a, b in zip(candidate, baseline, strict=True)], seed=seed
    )
    return {"mean": interval.point, "low": interval.low, "high": interval.high}
