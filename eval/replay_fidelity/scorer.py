"""OQ2 replay-fidelity scorer (FR-17 cold-loop gate).

Pure functions, no Mnemosyne imports. Operates on **paired** measurements

    (replay_predicted_lift, observed_real_lift)

where ``replay_predicted_lift`` is exactly the number the production
``counterfactual_replay_score`` arithmetic emits for a candidate
((after_successes - before_successes) / total_cases) and
``observed_real_lift`` is the real lift the candidate actually produced once
shadow-promoted (the ground truth a cold loop is *not allowed* to see at
decide-time).

The blueprint's OQ2 / FR-17 cold-loop gate asks one question: **is the cheap
counterfactual-replay proxy faithful enough to the real world that we may let it
gate a self-modification?** A proxy that ranks candidates in the wrong order, or
flips the sign of a lift, or systematically over-/under-states the magnitude, is
worse than no proxy — it launders a bad change past the rails. So the gate scores
fidelity along four axes and binds them with a confidence interval (the §33
methodology guardrail: "most deltas are within noise"):

  * **Spearman rho** (rank fidelity) + **bootstrap CI** (n=1000, deterministic).
    Does the proxy rank candidates the way reality does? Rank (not Pearson)
    because the loop only needs the *ordering* to pick winners, and rank is
    robust to the proxy's monotone miscalibration.
  * **sign-agreement** — fraction of pairs where proxy and reality agree on the
    sign of the lift (helped / hurt / neutral). A sign flip is the worst failure:
    the loop would promote a regression.
  * **proxy-true gap** — mean |proxy - true|. Magnitude bias; the term
    ``self_optimization.tripwire_check`` already guards with ``max_proxy_gap``.
  * **decision-coverage** — fraction of pairs on which the proxy yields a
    *confident, correct* promote/reject decision at the loop's own threshold.
    This is the operational question: on what share of real candidates would
    trusting the proxy have been the right call?

A golden corpus of degenerate cases (all-tie, sign-flipped, tiny-window) MUST be
rejected by the bar — those are the exact pathologies that make a replay proxy
unsafe to gate on. The runnable check (``replay_fidelity_check.py``) exits
non-zero when below bar; that non-zero is the FR-17 promotion gate.

Default bar (OQ2):
    rho            >= 0.60   and   rho 95% CI-lower > 0.30
    sign-agreement >= 0.80
    proxy-true gap <= 0.15            (mirrors tripwire_check max_proxy_gap)
    window (n)     >= 50              (cold-loop ignition floor)
    decision-cov   >= 0.80
"""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass, field
from typing import Sequence

# --------------------------------------------------------------------------- #
# Bar (OQ2 / FR-17 thresholds)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class FidelityBar:
    """The OQ2 acceptance bar. Defaults are the blueprint FR-17 cold-loop gate."""

    min_rho: float = 0.60
    min_rho_ci_lower: float = 0.30
    min_sign_agreement: float = 0.80
    max_proxy_true_gap: float = 0.15
    min_window: int = 50
    min_decision_coverage: float = 0.80
    # Operational decision threshold the loop would use on a single lift value to
    # decide "promote" (lift above) vs "reject" (lift at/below). Sign-of-lift by
    # default — a candidate is worth promoting iff it strictly helps.
    decision_threshold: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Confidence interval container (mirrors harness/metrics.Interval shape)
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


# --------------------------------------------------------------------------- #
# Rank-correlation core
# --------------------------------------------------------------------------- #


def _rankdata(values: Sequence[float]) -> list[float]:
    """Average-rank (fractional ranks for ties), matching scipy.stats.rankdata."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    n = len(values)
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # 1-based average rank over the tie block
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(x: Sequence[float], y: Sequence[float]) -> float:
    n = len(x)
    if n < 2:
        return float("nan")
    mx = sum(x) / n
    my = sum(y) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    denom = math.sqrt(sxx * syy)
    if denom == 0.0:
        # No variance in at least one series (e.g. all-tie). Undefined
        # correlation -> 0.0 (no rank information), never spuriously 1.0.
        return 0.0
    return sxy / denom


def spearman_rho(predicted: Sequence[float], observed: Sequence[float]) -> float:
    """Spearman rank correlation. 0.0 (not NaN) when a series has no variance."""
    if len(predicted) != len(observed):
        raise ValueError("predicted/observed length mismatch")
    if len(predicted) < 2:
        return float("nan")
    return _pearson(_rankdata(predicted), _rankdata(observed))


def spearman_bootstrap_ci(
    predicted: Sequence[float],
    observed: Sequence[float],
    *,
    iterations: int = 1000,
    alpha: float = 0.05,
    seed: int = 17,
) -> Interval:
    """Percentile-bootstrap CI for Spearman rho (n=1000, deterministic seed).

    Resamples *pairs* with replacement (the correct unit — the pairing of a
    predicted lift with its observed lift is the datum). Deterministic seeding
    keeps the FR-17 gate reproducible: the same corpus yields the same CI, so a
    real fidelity regression is distinguishable from bootstrap noise.
    """
    predicted = list(predicted)
    observed = list(observed)
    n = len(predicted)
    point = spearman_rho(predicted, observed)
    if n < 2 or math.isnan(point):
        return Interval(point, float("nan"), float("nan"), "bootstrap-spearman")
    rng = random.Random(seed)
    stats: list[float] = []
    for _ in range(iterations):
        idx = [rng.randrange(n) for _ in range(n)]
        rp = [predicted[i] for i in idx]
        ro = [observed[i] for i in idx]
        rho = spearman_rho(rp, ro)
        # A degenerate resample (e.g. all-identical predicted) yields rho via the
        # zero-variance branch as 0.0; keep it — that is real evidence of fragility.
        stats.append(0.0 if math.isnan(rho) else rho)
    stats.sort()
    lo = _percentile(stats, alpha / 2)
    hi = _percentile(stats, 1 - alpha / 2)
    return Interval(point=point, low=lo, high=hi, method="bootstrap-spearman")


# --------------------------------------------------------------------------- #
# Sign / gap / coverage
# --------------------------------------------------------------------------- #


def _sign(value: float, tol: float = 1e-9) -> int:
    if value > tol:
        return 1
    if value < -tol:
        return -1
    return 0


def sign_agreement(predicted: Sequence[float], observed: Sequence[float]) -> float:
    """Fraction of pairs where proxy and reality agree on sign(lift)."""
    if not predicted:
        return float("nan")
    agree = sum(1 for p, o in zip(predicted, observed) if _sign(p) == _sign(o))
    return agree / len(predicted)


def proxy_true_gap(predicted: Sequence[float], observed: Sequence[float]) -> float:
    """Mean |proxy - true| (magnitude bias). Mirrors tripwire_check's gap."""
    if not predicted:
        return float("nan")
    return sum(abs(p - o) for p, o in zip(predicted, observed)) / len(predicted)


def decision_coverage(
    predicted: Sequence[float],
    observed: Sequence[float],
    *,
    threshold: float = 0.0,
) -> float:
    """Fraction of pairs on which trusting the proxy's promote/reject decision is correct.

    The loop's rule: promote iff predicted lift > threshold. The decision is
    *correct* iff the observed lift agrees (observed > threshold). This is the
    operational fidelity question — not "is the number close" but "would acting
    on it have been right." A proxy can have decent rho yet poor coverage if it
    misclassifies near the threshold, which is exactly where promotions happen.
    """
    if not predicted:
        return float("nan")
    correct = 0
    for p, o in zip(predicted, observed):
        proxy_promote = p > threshold
        truth_promote = o > threshold
        if proxy_promote == truth_promote:
            correct += 1
    return correct / len(predicted)


# --------------------------------------------------------------------------- #
# Full score + verdict
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class FidelityScore:
    n: int
    rho: float
    rho_ci: Interval
    sign_agreement: float
    proxy_true_gap: float
    decision_coverage: float
    bar: FidelityBar
    checks: list[dict] = field(default_factory=list)
    passed: bool = False

    def to_dict(self) -> dict:
        return {
            "n": self.n,
            "rho": _round(self.rho),
            "rho_ci": self.rho_ci.as_dict(),
            "sign_agreement": _round(self.sign_agreement),
            "proxy_true_gap": _round(self.proxy_true_gap),
            "decision_coverage": _round(self.decision_coverage),
            "bar": self.bar.to_dict(),
            "checks": self.checks,
            "passed": self.passed,
        }


def score_fidelity(
    predicted: Sequence[float],
    observed: Sequence[float],
    *,
    bar: FidelityBar | None = None,
    bootstrap_iterations: int = 1000,
    seed: int = 17,
) -> FidelityScore:
    """Score one corpus of (predicted, observed) lift pairs against the OQ2 bar.

    Returns a :class:`FidelityScore` whose ``passed`` is the FR-17 gate verdict
    and whose ``checks`` carry a per-criterion PASS/FAIL with the comparison, so
    the runnable check and reports can show exactly which axis vetoed.
    """
    bar = bar or FidelityBar()
    predicted = list(predicted)
    observed = list(observed)
    if len(predicted) != len(observed):
        raise ValueError("predicted/observed length mismatch")
    n = len(predicted)

    rho = spearman_rho(predicted, observed) if n >= 2 else float("nan")
    rho_ci = spearman_bootstrap_ci(
        predicted, observed, iterations=bootstrap_iterations, seed=seed
    )
    sgn = sign_agreement(predicted, observed)
    gap = proxy_true_gap(predicted, observed)
    cov = decision_coverage(predicted, observed, threshold=bar.decision_threshold)

    def _check(name: str, value: float, op: str, target: float) -> dict:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            ok = False
        elif op == ">=":
            ok = value >= target
        elif op == ">":
            ok = value > target
        elif op == "<=":
            ok = value <= target
        else:  # pragma: no cover - guarded by callers
            raise ValueError(op)
        return {
            "name": name,
            "value": _round(value) if isinstance(value, float) else value,
            "op": op,
            "target": target,
            "pass": bool(ok),
        }

    checks = [
        _check("window", n, ">=", bar.min_window),
        _check("spearman_rho", rho, ">=", bar.min_rho),
        _check("rho_ci_lower", rho_ci.low, ">", bar.min_rho_ci_lower),
        _check("sign_agreement", sgn, ">=", bar.min_sign_agreement),
        _check("proxy_true_gap", gap, "<=", bar.max_proxy_true_gap),
        _check("decision_coverage", cov, ">=", bar.min_decision_coverage),
    ]
    passed = all(c["pass"] for c in checks)

    return FidelityScore(
        n=n,
        rho=rho,
        rho_ci=rho_ci,
        sign_agreement=sgn,
        proxy_true_gap=gap,
        decision_coverage=cov,
        bar=bar,
        checks=checks,
        passed=passed,
    )


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _percentile(ordered: Sequence[float], q: float) -> float:
    """Linear-interpolation percentile on an already-sorted sequence."""
    if not ordered:
        return float("nan")
    if len(ordered) == 1:
        return ordered[0]
    pos = q * (len(ordered) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[int(pos)]
    frac = pos - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def _round(x: float, places: int = 4) -> float:
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return x
    return round(x, places)
