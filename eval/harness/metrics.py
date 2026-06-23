"""Metric primitives for the §33 evaluation harness.

Pure functions, no Mnemosyne imports — everything here operates on the parsed
CLI output. Implements exactly the measurement set named in blueprint §33 / §16:

  * recall@k, nDCG@k                          (FR-3 retrieval quality)
  * P50/P95/P99 latency                       (§16 fast-path SLO)
  * Expected Calibration Error (ECE)          (§16 ECE ≤ 0.05, FR-6)
  * answer-quality lift vs full context       (§16 G2: +15% at ≤10% tokens)
  * block rate                                (§16 G7 poison resistance ≥95%)

Plus the methodology guardrail the blueprint explicitly mandates — **confidence
intervals** — because "most deltas are within noise" (§33). We provide:
  * Wilson score interval for proportions (recall, block-rate, accuracy)
  * Bootstrap percentile interval for means / nDCG / latency percentiles
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Iterable, Sequence


# --------------------------------------------------------------------------- #
# Retrieval metrics
# --------------------------------------------------------------------------- #
def recall_at_k(retrieved_ids: Sequence[str], relevant_ids: Iterable[str], k: int) -> float:
    """Fraction of relevant items present in the top-k retrieved list.

    Defined as |relevant ∩ top_k| / |relevant|. Returns 0.0 when there are no
    relevant items (an unanswerable / abstain case contributes 0 recall mass and
    is handled separately by abstention metrics).
    """
    relevant = set(relevant_ids)
    if not relevant:
        return 0.0
    top = list(retrieved_ids)[:k]
    hit = sum(1 for rid in relevant if rid in top)
    return hit / len(relevant)


def dcg_at_k(retrieved_ids: Sequence[str], relevant_ids: Iterable[str], k: int) -> float:
    relevant = set(relevant_ids)
    dcg = 0.0
    for rank, rid in enumerate(list(retrieved_ids)[:k], start=1):
        if rid in relevant:
            dcg += 1.0 / math.log2(rank + 1)
    return dcg


def ndcg_at_k(retrieved_ids: Sequence[str], relevant_ids: Iterable[str], k: int) -> float:
    """Normalized DCG@k with binary relevance."""
    relevant = set(relevant_ids)
    if not relevant:
        return 0.0
    ideal = dcg_at_k(list(relevant), relevant, k)
    if ideal == 0.0:
        return 0.0
    return dcg_at_k(retrieved_ids, relevant, k) / ideal


# --------------------------------------------------------------------------- #
# Latency
# --------------------------------------------------------------------------- #
def percentile(values: Sequence[float], q: float) -> float:
    """Linear-interpolation percentile (q in [0,1]). Matches numpy's default."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = q * (len(ordered) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[int(pos)]
    frac = pos - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


@dataclass(slots=True)
class LatencySummary:
    count: int
    p50: float
    p95: float
    p99: float
    mean: float
    maximum: float


def latency_summary(values: Sequence[float]) -> LatencySummary:
    if not values:
        return LatencySummary(0, float("nan"), float("nan"), float("nan"), float("nan"), float("nan"))
    return LatencySummary(
        count=len(values),
        p50=percentile(values, 0.50),
        p95=percentile(values, 0.95),
        p99=percentile(values, 0.99),
        mean=sum(values) / len(values),
        maximum=max(values),
    )


# --------------------------------------------------------------------------- #
# Calibration (ECE)
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class ECEResult:
    ece: float
    bins: list[dict]
    n: int


def expected_calibration_error(
    confidences: Sequence[float],
    correct: Sequence[bool],
    n_bins: int = 10,
) -> ECEResult:
    """Standard binned ECE (Naeini et al.).

    ECE = Σ_b (n_b / N) · |acc(b) − conf(b)|, over ``n_bins`` equal-width bins of
    the [0,1] confidence axis. Blueprint §16 target: ECE ≤ 0.05.
    """
    assert len(confidences) == len(correct), "confidence/correct length mismatch"
    n = len(confidences)
    if n == 0:
        return ECEResult(float("nan"), [], 0)
    bins: list[dict] = []
    ece = 0.0
    for b in range(n_bins):
        lo = b / n_bins
        hi = (b + 1) / n_bins
        # Last bin is closed on the right so confidence==1.0 lands somewhere.
        in_bin = [
            i
            for i, c in enumerate(confidences)
            if (c > lo or (b == 0 and c >= lo)) and (c <= hi if b == n_bins - 1 else c <= hi)
        ]
        if not in_bin:
            bins.append({"lo": lo, "hi": hi, "count": 0, "accuracy": None, "confidence": None, "gap": None})
            continue
        acc = sum(1 for i in in_bin if correct[i]) / len(in_bin)
        conf = sum(confidences[i] for i in in_bin) / len(in_bin)
        gap = abs(acc - conf)
        ece += (len(in_bin) / n) * gap
        bins.append(
            {"lo": lo, "hi": hi, "count": len(in_bin), "accuracy": acc, "confidence": conf, "gap": gap}
        )
    return ECEResult(ece=ece, bins=bins, n=n)


# --------------------------------------------------------------------------- #
# Confidence intervals
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class Interval:
    point: float
    low: float
    high: float
    method: str

    def as_dict(self) -> dict:
        return {
            "point": _round(self.point),
            "ci_low": _round(self.low),
            "ci_high": _round(self.high),
            "ci_method": self.method,
        }


def wilson_interval(successes: int, total: int, z: float = 1.96) -> Interval:
    """Wilson score interval for a binomial proportion (95% by default).

    Far better than the normal approximation at the extremes we care about
    (block-rate near 1.0, recall near 1.0 or 0.0) and never escapes [0,1].
    """
    if total == 0:
        return Interval(float("nan"), float("nan"), float("nan"), "wilson")
    p = successes / total
    z2 = z * z
    denom = 1 + z2 / total
    center = (p + z2 / (2 * total)) / denom
    margin = (z * math.sqrt((p * (1 - p) + z2 / (4 * total)) / total)) / denom
    return Interval(point=p, low=max(0.0, center - margin), high=min(1.0, center + margin), method="wilson")


def bootstrap_mean_interval(
    values: Sequence[float],
    *,
    iterations: int = 2000,
    alpha: float = 0.05,
    seed: int = 1234,
) -> Interval:
    """Percentile-bootstrap CI for the mean of ``values`` (deterministic seed).

    Deterministic seeding keeps the harness reproducible — a hard requirement
    for a regression suite (blueprint §33 "continuous regression on every
    change"): the same inputs must yield the same intervals.
    """
    values = list(values)
    if not values:
        return Interval(float("nan"), float("nan"), float("nan"), "bootstrap")
    if len(values) == 1:
        return Interval(values[0], values[0], values[0], "bootstrap")
    rng = random.Random(seed)
    n = len(values)
    means: list[float] = []
    for _ in range(iterations):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = percentile(means, alpha / 2)
    hi = percentile(means, 1 - alpha / 2)
    return Interval(point=sum(values) / n, low=lo, high=hi, method="bootstrap")


def bootstrap_percentile_interval(
    values: Sequence[float],
    q: float,
    *,
    iterations: int = 2000,
    alpha: float = 0.05,
    seed: int = 4321,
) -> Interval:
    """Percentile-bootstrap CI for a *percentile* statistic (e.g. P95 latency)."""
    values = list(values)
    if not values:
        return Interval(float("nan"), float("nan"), float("nan"), "bootstrap-pctl")
    if len(values) == 1:
        return Interval(values[0], values[0], values[0], "bootstrap-pctl")
    rng = random.Random(seed)
    n = len(values)
    stats: list[float] = []
    for _ in range(iterations):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        stats.append(percentile(sample, q))
    stats.sort()
    return Interval(
        point=percentile(values, q),
        low=percentile(stats, alpha / 2),
        high=percentile(stats, 1 - alpha / 2),
        method="bootstrap-pctl",
    )


def _round(x: float, places: int = 4) -> float:
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return x
    return round(x, places)
