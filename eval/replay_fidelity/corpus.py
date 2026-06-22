"""Golden corpus of (replay-predicted lift, observed real lift) pairs for OQ2.

Every predicted lift in this module is produced by the **real production
arithmetic** — ``mnemosyne.learning.counterfactual_replay_score`` — over a
before/after/total triple, never a hand-typed float. The observed real lift is
carried on the **real shape** ``mnemosyne.self_optimization.PolicyOutcome``
(stored in a real ``SelfModelStore``) under the metric key
``OBSERVED_REAL_LIFT_KEY``. This keeps the harness bound to the live contract:
if either the cf arithmetic or the PolicyOutcome/SelfModelStore shape changes,
this module breaks — which is the point (it is the FR-17 forcing function).

The corpus has two halves:

  * A **faithful** corpus the bar MUST accept — a replay proxy whose predicted
    lift tracks reality well enough to gate on. Generated deterministically so
    the harness is reproducible.
  * A **degenerate** golden set the bar MUST reject, one entry per pathology the
    OQ2 gate exists to catch:
        - ``all_tie``      — every candidate is a wash (proxy has no rank signal;
                             rho is undefined-> 0.0, coverage collapses).
        - ``sign_flipped`` — proxy systematically inverts the sign of the lift
                             (it would promote regressions). Worst case.
        - ``tiny_window``  — too few candidates to trust any statistic (below the
                             cold-loop ignition floor; CI is meaningless).
        - ``noise``        — proxy is pure noise, uncorrelated with reality.
        - ``biased_gap``   — proxy ranks fine but is magnitude-inflated past the
                             tripwire gap (would mis-size promotions).
"""

from __future__ import annotations

import random
import sys
from dataclasses import dataclass
from pathlib import Path

# Bind to the real src modules (the live contract under test). The harness drives
# the *arithmetic core* and *data shapes* directly per FR-17, not the CLI.
_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mnemosyne.learning import counterfactual_replay_score  # noqa: E402
from mnemosyne.self_optimization import (  # noqa: E402
    PolicyOutcome,
    SelfModelStore,
)

# Metric key under which a candidate's real, post-promotion lift is recorded on a
# PolicyOutcome. A real cold loop logs this once the shadow promotion has run long
# enough to observe the true effect; the gate then pairs it with the proxy.
OBSERVED_REAL_LIFT_KEY = "observed_real_lift"
PREDICTED_LIFT_KEY = "replay_predicted_lift"


@dataclass(slots=True)
class CandidatePair:
    """One (predicted, observed) datum, traceable back to its before/after/total."""

    candidate_id: str
    before_successes: int
    after_successes: int
    total_cases: int
    predicted_lift: float
    observed_real_lift: float

    @property
    def proxy(self) -> float:
        return self.predicted_lift

    @property
    def truth(self) -> float:
        return self.observed_real_lift


def _pair_from_counts(
    candidate_id: str,
    before: int,
    after: int,
    total: int,
    observed_real_lift: float,
) -> CandidatePair:
    """Build a pair whose predicted lift IS the production cf arithmetic output."""
    predicted = counterfactual_replay_score(before, after, total)
    return CandidatePair(
        candidate_id=candidate_id,
        before_successes=before,
        after_successes=after,
        total_cases=total,
        predicted_lift=predicted,
        observed_real_lift=float(observed_real_lift),
    )


def pairs_to_store(pairs: list[CandidatePair], tenant_id: str = "tenant-replay") -> SelfModelStore:
    """Materialize pairs onto the real SelfModelStore/PolicyOutcome shapes.

    The predicted lift rides in ``metrics`` (it is the cf-arithmetic output) and
    the observed real lift rides in ``metrics`` under OBSERVED_REAL_LIFT_KEY. The
    ``reward`` field carries the bounded observed lift (the loop's reward signal),
    exactly as ``ContextualBanditLearner.record_outcome`` would clamp it.
    """
    store = SelfModelStore()
    for pair in pairs:
        store.add_policy_outcome(
            PolicyOutcome(
                tenant_id=tenant_id,
                variant_id=pair.candidate_id,
                reward=max(0.0, min(1.0, pair.observed_real_lift)),
                context={"metric": "retrieval_quality"},
                metrics={
                    PREDICTED_LIFT_KEY: pair.predicted_lift,
                    OBSERVED_REAL_LIFT_KEY: pair.observed_real_lift,
                    "before_successes": float(pair.before_successes),
                    "after_successes": float(pair.after_successes),
                    "total_cases": float(pair.total_cases),
                },
            )
        )
    return store


def pairs_from_store(store: SelfModelStore, tenant_id: str = "tenant-replay") -> list[CandidatePair]:
    """Round-trip: recover (predicted, observed) pairs from a SelfModelStore.

    Proves the harness reads back the real shape the cold loop would persist —
    the gate input is reconstructed purely from PolicyOutcome.metrics.
    """
    out: list[CandidatePair] = []
    for outcome in store.outcomes(tenant_id):
        m = outcome.metrics
        before = int(m.get("before_successes", 0))
        after = int(m.get("after_successes", 0))
        total = int(m.get("total_cases", 0))
        # Recompute the predicted lift from counts via the production arithmetic
        # rather than trusting the stored float — keeps the proxy honest.
        predicted = counterfactual_replay_score(before, after, total)
        out.append(
            CandidatePair(
                candidate_id=outcome.variant_id,
                before_successes=before,
                after_successes=after,
                total_cases=total,
                predicted_lift=predicted,
                observed_real_lift=float(m.get(OBSERVED_REAL_LIFT_KEY, 0.0)),
            )
        )
    return out


# --------------------------------------------------------------------------- #
# Faithful corpus (the bar MUST accept)
# --------------------------------------------------------------------------- #


def faithful_corpus(n: int = 60, seed: int = 7) -> list[CandidatePair]:
    """A replay proxy that is faithful enough to gate on.

    Each candidate gets a true effect; the proxy (cf arithmetic over before/after
    counts on a fixed total window) tracks it with small, mean-zero noise and no
    sign flips. rho is high, the CI lower bound clears 0.30, sign-agreement and
    decision-coverage are high, and the magnitude gap stays under the tripwire.
    The point is not a perfect oracle but a *trustworthy* one.
    """
    rng = random.Random(seed)
    total = 40  # fixed replay window per candidate (>= cold-loop floor concerns)
    pairs: list[CandidatePair] = []
    for i in range(n):
        # A spread of true effects from clearly-helpful to clearly-harmful so the
        # ranking task is non-trivial and sign cases are well represented.
        true_lift = (i / (n - 1)) * 0.5 - 0.18  # roughly [-0.18, 0.32]
        # Proxy reflects truth with a little integer-quantization noise from the
        # counts arithmetic + a small jitter, but never flips sign.
        jitter = rng.uniform(-0.03, 0.03)
        proxy_target = true_lift + jitter
        after = round(total * (0.5 + proxy_target / 2))  # map lift->success delta
        before = round(total * 0.5)
        after = max(0, min(total, after))
        # observed real lift = true effect plus independent observation noise
        observed = true_lift + rng.uniform(-0.02, 0.02)
        pairs.append(_pair_from_counts(f"cand-{i:03d}", before, after, total, observed))
    return pairs


# --------------------------------------------------------------------------- #
# Degenerate golden set (the bar MUST reject — one per pathology)
# --------------------------------------------------------------------------- #


def degenerate_all_tie(n: int = 60) -> list[CandidatePair]:
    """Every candidate is a wash: before==after, observed lift 0. No rank signal."""
    total = 40
    half = total // 2
    return [
        _pair_from_counts(f"tie-{i:03d}", half, half, total, 0.0) for i in range(n)
    ]


def degenerate_sign_flipped(n: int = 60, seed: int = 11) -> list[CandidatePair]:
    """Proxy systematically inverts reality's sign: it would promote regressions."""
    rng = random.Random(seed)
    total = 40
    pairs: list[CandidatePair] = []
    for i in range(n):
        true_lift = (i / (n - 1)) * 0.5 - 0.25  # ~[-0.25, 0.25]
        # Proxy is the NEGATION of the true effect (anti-correlated).
        proxy_lift = -true_lift + rng.uniform(-0.01, 0.01)
        after = round(total * (0.5 + proxy_lift / 2))
        before = round(total * 0.5)
        after = max(0, min(total, after))
        pairs.append(_pair_from_counts(f"flip-{i:03d}", before, after, total, true_lift))
    return pairs


def degenerate_tiny_window(seed: int = 3) -> list[CandidatePair]:
    """Below the cold-loop ignition floor: too few candidates to trust a statistic."""
    rng = random.Random(seed)
    total = 40
    pairs: list[CandidatePair] = []
    for i in range(8):  # << min_window (50)
        true_lift = rng.uniform(-0.2, 0.2)
        after = round(total * (0.5 + true_lift / 2))
        before = round(total * 0.5)
        pairs.append(_pair_from_counts(f"tiny-{i:03d}", before, after, total, true_lift))
    return pairs


def degenerate_noise(n: int = 60, seed: int = 23) -> list[CandidatePair]:
    """Proxy is pure noise, uncorrelated with reality: rho ~ 0, coverage ~ chance."""
    rng = random.Random(seed)
    total = 40
    pairs: list[CandidatePair] = []
    for i in range(n):
        true_lift = rng.uniform(-0.25, 0.25)
        proxy_lift = rng.uniform(-0.25, 0.25)  # independent of truth
        after = round(total * (0.5 + proxy_lift / 2))
        before = round(total * 0.5)
        after = max(0, min(total, after))
        pairs.append(_pair_from_counts(f"noise-{i:03d}", before, after, total, true_lift))
    return pairs


def degenerate_biased_gap(n: int = 60, seed: int = 29) -> list[CandidatePair]:
    """Ranks fine, but magnitude is inflated past the tripwire gap.

    rho and sign-agreement can look great while the proxy over-states every lift
    by a constant the loop would act on (mis-sized promotions). The gap axis must
    veto this even when rank fidelity is perfect.
    """
    rng = random.Random(seed)
    total = 100  # larger window so the integer-count quantization faithfully
    # represents the inflation rather than crushing it to the gap boundary.
    pairs: list[CandidatePair] = []
    for i in range(n):
        true_lift = (i / (n - 1)) * 0.3 - 0.18  # spans negative->positive, monotone
        # Proxy preserves rank order but adds a large positive bias (~0.45) so the
        # mean magnitude gap clears the tripwire (> 0.15) with margin.
        proxy_lift = true_lift + 0.45 + rng.uniform(-0.01, 0.01)
        after = round(total * (0.5 + proxy_lift / 2))
        before = round(total * 0.5)
        after = max(0, min(total, after))
        pairs.append(_pair_from_counts(f"bias-{i:03d}", before, after, total, true_lift))
    return pairs


# Registry: name -> (builder, must_pass). The check iterates this so the golden
# guarantees are explicit and testable: faithful MUST pass, every degenerate MUST
# be rejected by the OQ2 bar.
GOLDEN_CASES: dict[str, tuple] = {
    "faithful": (faithful_corpus, True),
    "all_tie": (degenerate_all_tie, False),
    "sign_flipped": (degenerate_sign_flipped, False),
    "tiny_window": (degenerate_tiny_window, False),
    "noise": (degenerate_noise, False),
    "biased_gap": (degenerate_biased_gap, False),
}


def build_case(name: str) -> list[CandidatePair]:
    if name not in GOLDEN_CASES:
        raise KeyError(f"unknown golden case {name!r}; have {sorted(GOLDEN_CASES)}")
    builder, _ = GOLDEN_CASES[name]
    return builder()
