"""Shadow-first policy optimization inside immutable rails."""

from __future__ import annotations

import json
import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.gate import (
    Candidate,
    CounterfactualHook,
    CounterfactualVerdict,
    GateResult,
    PromotionGate,
    RegressionCase,
)
from mnemosyne.ids import new_id
from mnemosyne.learning import counterfactual_replay_score
from mnemosyne.policy import OperatingPolicy

# Single source of truth for the proxy-vs-true gap rail (blueprint §23.5/OQ2).
# The tripwire monitor, the policy-ops validator, and the default cold-loop
# counterfactual scorer all bind to this one threshold so they cannot drift apart.
OQ2_PROXY_TRUE_GAP = 0.15
# Minimum number of real (predicted, observed) replay pairs before the cold-loop
# counterfactual proxy is authorized to act on a promotion (OQ2 forcing function).
OQ2_MIN_REPLAY_WINDOW = 50
# OQ2 / §17 FR-17 fidelity bar (docs/decisions/SECTION-17-OPEN-QUESTIONS.md).
# Used by the fidelity recorder to decide when the cold-loop rail *may* be flipped;
# never auto-sets OperatingPolicy.cold_loop_counterfactual_trusted.
OQ2_MIN_SPEARMAN_RHO = 0.60
OQ2_MIN_RHO_CI_LOWER = 0.30
OQ2_MIN_SIGN_AGREEMENT = 0.80
OQ2_MIN_DECISION_COVERAGE = 0.80
OQ2_MIN_ACTIVE_PAIRS = 10
OQ2_BOOTSTRAP_ITERATIONS = 1000
OQ2_BOOTSTRAP_SEED = 17


@dataclass(slots=True)
class PolicyVariant:
    id: str
    activation_weights: dict[str, float]
    abstention_threshold: float
    top_k: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SelfModelRecord:
    tenant_id: str
    metric: str
    policy_version: str
    value: float
    window_start: datetime
    window_end: datetime
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["window_start"] = self.window_start.astimezone(UTC).isoformat()
        data["window_end"] = self.window_end.astimezone(UTC).isoformat()
        return data


@dataclass(slots=True)
class PolicyOutcome:
    tenant_id: str
    variant_id: str
    reward: float
    context: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["recorded_at"] = self.recorded_at.astimezone(UTC).isoformat()
        return data


@dataclass(slots=True)
class TripwireResult:
    passed: bool
    reason: str
    diversity: float
    proxy_true_gap: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ReplayPair:
    """A paired (replay-predicted lift, observed real lift) sample (I12/OQ2).

    The cold loop records one of these after a promoted self-modification: the
    lift the counterfactual replay *predicted* and the lift actually *observed*
    in production. The OQ2 fidelity gate scores these pairs to decide whether the
    replay proxy is trustworthy enough to gate self-modifications.
    """

    tenant_id: str
    variant_id: str
    predicted_lift: float
    observed_lift: float
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class OQ2FidelityBar:
    """Pre-registered OQ2 acceptance bar (FR-17 / §17)."""

    min_rho: float = OQ2_MIN_SPEARMAN_RHO
    min_rho_ci_lower: float = OQ2_MIN_RHO_CI_LOWER
    min_sign_agreement: float = OQ2_MIN_SIGN_AGREEMENT
    max_proxy_true_gap: float = OQ2_PROXY_TRUE_GAP
    min_window: int = OQ2_MIN_REPLAY_WINDOW
    min_active_pairs: int = OQ2_MIN_ACTIVE_PAIRS
    min_decision_coverage: float = OQ2_MIN_DECISION_COVERAGE
    decision_threshold: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class OQ2Interval:
    point: float
    low: float
    high: float
    method: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "point": _oq2_round(self.point),
            "ci_low": _oq2_round(self.low),
            "ci_high": _oq2_round(self.high),
            "ci_method": self.method,
        }


@dataclass(slots=True)
class OQ2FidelityReport:
    """Deterministic OQ2 fidelity report over paired (predicted, observed) lifts.

    ``authorized_to_trust`` is True only when every OQ2 bar check passes. It does
    **not** flip ``OperatingPolicy.cold_loop_counterfactual_trusted`` — that requires
    an explicit operator call to :func:`apply_cold_loop_counterfactual_trust`.
    """

    n: int
    active_pairs: int
    rho: float
    rho_ci: OQ2Interval
    sign_agreement: float
    proxy_true_gap: float
    decision_coverage: float
    bar: OQ2FidelityBar
    checks: list[dict[str, Any]] = field(default_factory=list)
    bar_passed: bool = False
    authorized_to_trust: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "active_pairs": self.active_pairs,
            "rho": _oq2_round(self.rho),
            "rho_ci": self.rho_ci.to_dict(),
            "sign_agreement": _oq2_round(self.sign_agreement),
            "proxy_true_gap": _oq2_round(self.proxy_true_gap),
            "decision_coverage": _oq2_round(self.decision_coverage),
            "bar": self.bar.to_dict(),
            "checks": list(self.checks),
            "bar_passed": self.bar_passed,
            "authorized_to_trust": self.authorized_to_trust,
            "reason": self.reason,
        }


def _oq2_round(value: float, places: int = 4) -> float:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return value
    return round(float(value), places)


def _oq2_rankdata(values: Sequence[float]) -> list[float]:
    """Average ranks (fractional ties), matching scipy.stats.rankdata."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    n = len(values)
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _oq2_pearson(x: Sequence[float], y: Sequence[float]) -> float:
    n = len(x)
    if n < 2:
        return float("nan")
    mx = sum(x) / n
    my = sum(y) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    denom = math.sqrt(sxx * syy)
    if denom == 0.0:
        return 0.0
    return sxy / denom


def spearman_rho(predicted: Sequence[float], observed: Sequence[float]) -> float:
    """Spearman rank correlation; 0.0 when a series has no variance."""
    if len(predicted) != len(observed):
        raise ValueError("predicted/observed length mismatch")
    if len(predicted) < 2:
        return float("nan")
    return _oq2_pearson(_oq2_rankdata(predicted), _oq2_rankdata(observed))


def _oq2_percentile(ordered: Sequence[float], q: float) -> float:
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


def spearman_bootstrap_ci(
    predicted: Sequence[float],
    observed: Sequence[float],
    *,
    iterations: int = OQ2_BOOTSTRAP_ITERATIONS,
    alpha: float = 0.05,
    seed: int = OQ2_BOOTSTRAP_SEED,
) -> OQ2Interval:
    """Deterministic percentile-bootstrap CI for Spearman ρ (OQ2 n=1000)."""
    predicted_list = list(predicted)
    observed_list = list(observed)
    n = len(predicted_list)
    point = spearman_rho(predicted_list, observed_list)
    if n < 2 or math.isnan(point):
        return OQ2Interval(point, float("nan"), float("nan"), "bootstrap-spearman")
    rng = random.Random(seed)
    stats: list[float] = []
    for _ in range(iterations):
        idx = [rng.randrange(n) for _ in range(n)]
        rp = [predicted_list[i] for i in idx]
        ro = [observed_list[i] for i in idx]
        rho = spearman_rho(rp, ro)
        stats.append(0.0 if math.isnan(rho) else rho)
    stats.sort()
    return OQ2Interval(
        point=point,
        low=_oq2_percentile(stats, alpha / 2),
        high=_oq2_percentile(stats, 1 - alpha / 2),
        method="bootstrap-spearman",
    )


def _oq2_sign(value: float, tol: float = 1e-9) -> int:
    if value > tol:
        return 1
    if value < -tol:
        return -1
    return 0


def sign_agreement(predicted: Sequence[float], observed: Sequence[float]) -> float:
    """Fraction of pairs where proxy and reality agree on sign(lift)."""
    if not predicted:
        return float("nan")
    agree = sum(1 for p, o in zip(predicted, observed, strict=True) if _oq2_sign(p) == _oq2_sign(o))
    return agree / len(predicted)


def proxy_true_gap(predicted: Sequence[float], observed: Sequence[float]) -> float:
    """Mean |proxy - true| magnitude bias (mirrors tripwire_check gap)."""
    if not predicted:
        return float("nan")
    return sum(abs(p - o) for p, o in zip(predicted, observed, strict=True)) / len(predicted)


def decision_coverage(
    predicted: Sequence[float],
    observed: Sequence[float],
    *,
    threshold: float = 0.0,
) -> float:
    """Fraction of pairs where proxy promote/reject matches observed truth."""
    if not predicted:
        return float("nan")
    correct = 0
    for p, o in zip(predicted, observed, strict=True):
        if (p > threshold) == (o > threshold):
            correct += 1
    return correct / len(predicted)


def count_active_pairs(pairs: Sequence[tuple[float, float]], *, tol: float = 1e-9) -> int:
    """Pairs with non-neutral predicted or observed lift (OQ2 ≥10 active)."""
    return sum(1 for predicted, observed in pairs if abs(predicted) > tol or abs(observed) > tol)


def evaluate_oq2_fidelity(
    pairs: Sequence[tuple[float, float]],
    *,
    bar: OQ2FidelityBar | None = None,
    bootstrap_iterations: int = OQ2_BOOTSTRAP_ITERATIONS,
    seed: int = OQ2_BOOTSTRAP_SEED,
) -> OQ2FidelityReport:
    """Score paired (predicted, observed) lifts against the OQ2 fidelity bar.

    Shadow-only recorder: never mutates policy. ``authorized_to_trust`` is True
    only when every criterion passes; operators must still call
    :func:`apply_cold_loop_counterfactual_trust` to flip the rail.
    """
    bar = bar or OQ2FidelityBar()
    pair_list = [(float(p), float(o)) for p, o in pairs]
    predicted = [p for p, _ in pair_list]
    observed = [o for _, o in pair_list]
    n = len(pair_list)
    active = count_active_pairs(pair_list)
    rho = spearman_rho(predicted, observed) if n >= 2 else float("nan")
    rho_ci = spearman_bootstrap_ci(
        predicted, observed, iterations=bootstrap_iterations, seed=seed
    )
    sgn = sign_agreement(predicted, observed)
    gap = proxy_true_gap(predicted, observed)
    cov = decision_coverage(predicted, observed, threshold=bar.decision_threshold)

    def _check(name: str, value: float, op: str, target: float) -> dict[str, Any]:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            ok = False
        elif op == ">=":
            ok = value >= target
        elif op == ">":
            ok = value > target
        elif op == "<=":
            ok = value <= target
        else:
            raise ValueError(op)
        return {
            "name": name,
            "value": _oq2_round(value) if isinstance(value, float) else value,
            "op": op,
            "target": target,
            "pass": bool(ok),
        }

    checks = [
        _check("window", float(n), ">=", float(bar.min_window)),
        _check("active_pairs", float(active), ">=", float(bar.min_active_pairs)),
        _check("spearman_rho", rho, ">=", bar.min_rho),
        _check("rho_ci_lower", rho_ci.low, ">", bar.min_rho_ci_lower),
        _check("sign_agreement", sgn, ">=", bar.min_sign_agreement),
        _check("proxy_true_gap", gap, "<=", bar.max_proxy_true_gap),
        _check("decision_coverage", cov, ">=", bar.min_decision_coverage),
    ]
    bar_passed = all(bool(item["pass"]) for item in checks)
    if bar_passed:
        reason = "OQ2 fidelity bar cleared; cold_loop rail may be flipped explicitly"
    else:
        failed = [item["name"] for item in checks if not item["pass"]]
        reason = f"OQ2 fidelity bar not met: {', '.join(failed)}"
    return OQ2FidelityReport(
        n=n,
        active_pairs=active,
        rho=rho,
        rho_ci=rho_ci,
        sign_agreement=sgn,
        proxy_true_gap=gap,
        decision_coverage=cov,
        bar=bar,
        checks=checks,
        bar_passed=bar_passed,
        authorized_to_trust=bar_passed,
        reason=reason,
    )


def apply_cold_loop_counterfactual_trust(
    policy: OperatingPolicy,
    report: OQ2FidelityReport,
    *,
    enable: bool,
) -> bool:
    """Explicit operator path to flip ``cold_loop_counterfactual_trusted``.

    Fail-closed: never sets True unless ``enable`` and ``report.authorized_to_trust``.
    Setting ``enable=False`` always clears the rail (safe demotion). Returns the
    resulting rail value. Does not promote candidates or open gate.py seams.
    """
    if not enable:
        policy.cold_loop_counterfactual_trusted = False
        return False
    if not report.authorized_to_trust:
        # Refuse silent trust — leave rail off (or leave prior False).
        policy.cold_loop_counterfactual_trusted = False
        return False
    policy.cold_loop_counterfactual_trusted = True
    return True


class SelfModelStore:
    def __init__(self) -> None:
        self.records: dict[str, SelfModelRecord] = {}
        self.policy_outcomes: dict[str, PolicyOutcome] = {}
        # Paired (predicted, observed) lift samples for the OQ2 replay-fidelity
        # gate. Kept separate from bandit ``policy_outcomes`` so recording a pair
        # never perturbs contextual-bandit scoring.
        self._replay_pairs: list[ReplayPair] = []

    def add(self, record: SelfModelRecord) -> str:
        self.records[record.id] = record
        return record.id

    def add_policy_outcome(self, outcome: PolicyOutcome) -> str:
        self.policy_outcomes[outcome.id] = outcome
        return outcome.id

    def outcomes(self, tenant_id: str, context: dict[str, Any] | None = None) -> list[PolicyOutcome]:
        context_key = _context_key(context) if context is not None else None
        matches = [record for record in self.policy_outcomes.values() if record.tenant_id == tenant_id]
        if context_key is None:
            return matches
        return [record for record in matches if _context_key(record.context) == context_key]

    def latest(self, tenant_id: str, metric: str) -> SelfModelRecord | None:
        matches = [record for record in self.records.values() if record.tenant_id == tenant_id and record.metric == metric]
        if not matches:
            return None
        return max(matches, key=lambda item: item.window_end)

    def record_replay_pair(
        self,
        tenant_id: str,
        variant_id: str,
        predicted_lift: float,
        observed_lift: float,
    ) -> str:
        """Record a paired (predicted, observed) lift sample for OQ2 fidelity."""
        pair = ReplayPair(
            tenant_id=tenant_id,
            variant_id=variant_id,
            predicted_lift=float(predicted_lift),
            observed_lift=float(observed_lift),
        )
        self._replay_pairs.append(pair)
        return pair.id

    def replay_pairs(self, tenant_id: str) -> list[tuple[float, float]]:
        """Return the (predicted_lift, observed_lift) pairs for a tenant.

        This is the first-class source of paired data the OQ2 replay-fidelity
        gate scores (blueprint §30.6 / FR-17).
        """
        return [(pair.predicted_lift, pair.observed_lift) for pair in self._replay_pairs if pair.tenant_id == tenant_id]

    def evaluate_oq2_fidelity(
        self,
        tenant_id: str,
        *,
        bar: OQ2FidelityBar | None = None,
        bootstrap_iterations: int = OQ2_BOOTSTRAP_ITERATIONS,
        seed: int = OQ2_BOOTSTRAP_SEED,
    ) -> OQ2FidelityReport:
        """Score this tenant's recorded replay pairs against the OQ2 bar (shadow-only)."""
        return evaluate_oq2_fidelity(
            self.replay_pairs(tenant_id),
            bar=bar,
            bootstrap_iterations=bootstrap_iterations,
            seed=seed,
        )


def within_invariant_rails(base: OperatingPolicy, variant: PolicyVariant) -> bool:
    if variant.top_k < 1 or variant.top_k > 64:
        return False
    if variant.abstention_threshold < 0.05 or variant.abstention_threshold > 0.95:
        return False
    total = sum(variant.activation_weights.values())
    if abs(total - 1.0) > 0.001:
        return False
    if set(variant.activation_weights) != set(base.activation_weights):
        return False
    return all(base.immutable_rails.values())


def _context_key(context: dict[str, Any] | None) -> str:
    return json.dumps(context or {}, sort_keys=True, separators=(",", ":"))


class ContextualBanditLearner:
    """Deterministic UCB learner over shadow policy variants."""

    def __init__(self, self_model: SelfModelStore, exploration_weight: float = 0.15):
        self.self_model = self_model
        self.exploration_weight = exploration_weight

    def record_outcome(
        self,
        tenant_id: str,
        variant_id: str,
        reward: float,
        *,
        context: dict[str, Any] | None = None,
        metrics: dict[str, float] | None = None,
    ) -> str:
        bounded_reward = max(0.0, min(1.0, float(reward)))
        return self.self_model.add_policy_outcome(
            PolicyOutcome(
                tenant_id=tenant_id,
                variant_id=variant_id,
                reward=bounded_reward,
                context=dict(context or {}),
                metrics=dict(metrics or {}),
            )
        )

    def score_variant(self, tenant_id: str, variant_id: str, context: dict[str, Any] | None = None) -> float:
        outcomes = self.self_model.outcomes(tenant_id, context)
        variant_outcomes = [outcome for outcome in outcomes if outcome.variant_id == variant_id]
        total = max(len(outcomes), 1)
        if not variant_outcomes:
            return self.exploration_weight * math.sqrt(math.log(total + 1.0))
        average = sum(outcome.reward for outcome in variant_outcomes) / len(variant_outcomes)
        bonus = self.exploration_weight * math.sqrt(math.log(total + 1.0) / len(variant_outcomes))
        return average + bonus

    def choose_variant(
        self,
        tenant_id: str,
        candidates: list[PolicyVariant],
        context: dict[str, Any] | None = None,
    ) -> PolicyVariant:
        if not candidates:
            raise ValueError("bandit learner requires at least one policy variant")
        return max(candidates, key=lambda variant: self.score_variant(tenant_id, variant.id, context))


class ShadowPolicyOptimizer:
    def __init__(
        self,
        engine: LocalMemoryEngine,
        cases: list[RegressionCase],
        self_model: SelfModelStore | None = None,
        bandit: ContextualBanditLearner | None = None,
        require_ignition: bool = True,
    ):
        self.engine = engine
        self.cases = cases
        self.self_model = self_model or SelfModelStore()
        self.bandit = bandit or ContextualBanditLearner(self.self_model)
        self.require_ignition = require_ignition

    def evaluate_variant(
        self,
        tenant_id: str,
        variant: PolicyVariant,
        *,
        counterfactual_hook: CounterfactualHook | None = None,
    ) -> GateResult:
        candidate = Candidate(
            id=variant.id,
            kind="policy",
            signature="policy retrieval activation confidence",
            description=f"top_k={variant.top_k}; abstention={variant.abstention_threshold}",
            branch=f"canary-policy-{variant.id}",
            source_evidence_cids=[],
        )
        # The cold loop consumes the counterfactual replay proxy by default: when
        # no explicit hook is supplied, attach the default scorer over recorded
        # replay pairs (promotion fails closed until fidelity is proven —
        # blueprint I12/§30.6).
        gate = PromotionGate(
            self.engine,
            self.cases,
            counterfactual_hook=counterfactual_hook or default_counterfactual_hook(self.self_model),
            require_ignition=self.require_ignition,
        )

        def apply(engine: LocalMemoryEngine, branch: str) -> None:
            if not within_invariant_rails(engine.policy, variant):
                raise ValueError("policy variant violates invariant rails")
            engine.policy.activation_weights = dict(variant.activation_weights)
            engine.policy.abstention_threshold = variant.abstention_threshold
            engine.policy.top_k = variant.top_k

        original_policy = self.engine.policy
        original_snapshot = original_policy.to_dict()
        try:
            result = gate.evaluate(tenant_id, candidate, apply)
        finally:
            restored = OperatingPolicy.from_dict(original_snapshot)
            for key, value in restored.to_dict().items():
                setattr(original_policy, key, value)
            self.engine.policy = original_policy
        return result

    def propose_variant(self, tenant_id: str, metric: str = "retrieval_quality") -> PolicyVariant:
        latest = self.self_model.latest(tenant_id, metric)
        base = self.engine.policy
        stable = PolicyVariant(
            id=f"variant-{metric}-stable",
            activation_weights=dict(base.activation_weights),
            abstention_threshold=base.abstention_threshold,
            top_k=base.top_k,
        )
        recall = PolicyVariant(
            id=f"variant-{metric}-recall",
            activation_weights={"base_level": 0.25, "semantic": 0.45, "importance": 0.20, "recency": 0.10},
            abstention_threshold=min(base.abstention_threshold + 0.05, 0.9),
            top_k=min(base.top_k + 4, 64),
        )
        candidates = [stable, recall]
        if latest and latest.value < 0.7:
            candidates = [recall, stable]
        return self.bandit.choose_variant(tenant_id, candidates, {"metric": metric})

    def record_policy_outcome(
        self,
        tenant_id: str,
        variant_id: str,
        reward: float,
        *,
        metric: str = "retrieval_quality",
        metrics: dict[str, float] | None = None,
    ) -> str:
        return self.bandit.record_outcome(
            tenant_id,
            variant_id,
            reward,
            context={"metric": metric},
            metrics=metrics,
        )

    def counterfactual_evaluate(
        self,
        tenant_id: str,
        variant: PolicyVariant,
        sessions: Sequence[ReplaySession],
    ) -> dict[str, Any]:
        """Cold-loop promotion gated by the §23.3 suite AND I12 replay.

        Wires :func:`mnemosyne.learning.counterfactual_replay_score` into the
        promotion gate through the §30.6 ``counterfactual_hook`` seam (gate.py):
        the candidate is promoted only when the relevance-scoped regression suite
        clears *and* counterfactual replay of historical ``sessions`` is
        non-inferior (§23.3 step 3). The baseline success count is measured under
        the current policy before the candidate is applied. Replay never rescues
        a candidate the suite already failed — it can only veto.
        """
        baseline_successes = sum(
            1 for session in sessions if session.tenant_id == tenant_id and _session_succeeds(self.engine, session)
        )
        hook = make_counterfactual_hook(sessions, baseline_successes=baseline_successes)
        gate_result = self.evaluate_variant(tenant_id, variant, counterfactual_hook=hook)
        return {
            "promoted": gate_result.promoted,
            "gate": gate_result.to_dict(),
            "replay": gate_result.counterfactual,
        }


def tripwire_check(diversity: float, proxy_score: float, true_score: float, min_diversity: float = 0.2, max_proxy_gap: float = OQ2_PROXY_TRUE_GAP) -> TripwireResult:
    gap = abs(proxy_score - true_score)
    if diversity < min_diversity:
        return TripwireResult(False, "diversity below rail", diversity, gap)
    if gap > max_proxy_gap:
        return TripwireResult(False, "proxy score diverges from true score", diversity, gap)
    return TripwireResult(True, "tripwires clear", diversity, gap)


@dataclass(slots=True)
class ReplaySession:
    """A historical session replayed against a candidate memory state (I12)."""

    tenant_id: str
    query: str
    expected_substring: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CounterfactualReplayReport:
    """Result of counterfactual replay (blueprint I12 / §23.3 step 2)."""

    before_successes: int
    after_successes: int
    total: int
    lift: float
    non_inferior: bool
    sessions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _session_succeeds(engine: LocalMemoryEngine, session: ReplaySession, *, branch: str = "main") -> bool:
    # Mirror the promotion gate's success criterion exactly (gate.py): the
    # expected answer must surface in retrieved hit text and not be abstained.
    result = engine.retrieve(session.query, session.tenant_id, branch=branch)
    rendered = "\n".join(getattr(hit, "text", "") for hit in result.hits)
    return session.expected_substring.lower() in rendered.lower() and not getattr(result, "abstained", False)


def make_counterfactual_hook(
    sessions: Sequence[ReplaySession],
    *,
    baseline_successes: int,
) -> CounterfactualHook:
    """Build a gate counterfactual-replay hook (blueprint §30.6).

    The returned closure matches ``gate.CounterfactualHook``: it replays the
    historical ``sessions`` against the candidate memory state (on the gate's
    canary branch) and reports a verdict. ``baseline_successes`` is the success
    count under the pre-candidate policy. The candidate is vetoed when it would
    *regress* historical task success (predicted lift < 0); a non-inferior
    candidate passes. The gate only ever uses this to veto, never to rescue a
    candidate the regression suite already failed.
    """

    def hook(
        tenant_id: str,
        candidate: Candidate,
        engine: LocalMemoryEngine,
        passed: list[str],
        failed: list[str],
    ) -> CounterfactualVerdict:
        relevant = [session for session in sessions if session.tenant_id == tenant_id]
        after = sum(1 for session in relevant if _session_succeeds(engine, session, branch=candidate.branch))
        total = len(relevant)
        lift = counterfactual_replay_score(baseline_successes, after, total)
        non_inferior = after >= baseline_successes
        reason = (
            "counterfactual replay non-inferior"
            if non_inferior
            else f"counterfactual regression: {baseline_successes}->{after} over {total} sessions"
        )
        return CounterfactualVerdict(passed=non_inferior, predicted_lift=lift, reason=reason)

    return hook


def default_counterfactual_hook(
    self_model: SelfModelStore,
    *,
    min_window: int = OQ2_MIN_REPLAY_WINDOW,
    max_gap: float = OQ2_PROXY_TRUE_GAP,
    bar: OQ2FidelityBar | None = None,
    bootstrap_iterations: int = OQ2_BOOTSTRAP_ITERATIONS,
    seed: int = OQ2_BOOTSTRAP_SEED,
) -> CounterfactualHook:
    """Default cold-loop counterfactual scorer over recorded replay pairs (I12/§30.6).

    This is attached to the promotion gate by default so the cold loop *consumes*
    the counterfactual replay term on every self-modification decision. It is
    deterministic and strictly **veto-only**, and it honours the full OQ2 bar via
    :func:`evaluate_oq2_fidelity` (Spearman ρ + CI, sign-agreement, gap, coverage,
    window/active floors) — not a weaker window+mean-gap dual standard.

    * When the OQ2 bar is not cleared, the proxy is unproven → fails closed
      (``passed=False``). Callers that want shadow-only exploration may pass an
      explicit hook with different semantics.
    * Once the bar clears (``authorized_to_trust``), it vetoes any candidate whose
      mean predicted lift is negative. It still does **not** flip
      ``cold_loop_counterfactual_trusted``; that remains the explicit operator path.
    """

    fidelity_bar = bar or OQ2FidelityBar(min_window=min_window, max_proxy_true_gap=max_gap)

    def hook(
        tenant_id: str,
        candidate: Candidate,
        engine: LocalMemoryEngine,
        passed: list[str],
        failed: list[str],
    ) -> CounterfactualVerdict:
        pairs = self_model.replay_pairs(tenant_id)
        report = evaluate_oq2_fidelity(
            pairs,
            bar=fidelity_bar,
            bootstrap_iterations=bootstrap_iterations,
            seed=seed,
        )
        mean_predicted = (
            sum(predicted for predicted, _ in pairs) / len(pairs) if pairs else 0.0
        )
        if not report.authorized_to_trust:
            return CounterfactualVerdict(
                passed=False,
                predicted_lift=mean_predicted,
                reason=f"cf proxy unproven: {report.reason}",
            )
        non_inferior = mean_predicted >= 0.0
        reason = (
            "cf proxy authorized: OQ2 bar cleared; mean predicted lift non-negative"
            if non_inferior
            else f"cf proxy vetoes: mean predicted lift {mean_predicted:.3f} < 0"
        )
        return CounterfactualVerdict(passed=non_inferior, predicted_lift=mean_predicted, reason=reason)

    return hook


def counterfactual_replay(
    engine: LocalMemoryEngine,
    variant: PolicyVariant,
    sessions: Sequence[ReplaySession],
) -> CounterfactualReplayReport:
    """Replay historical sessions against a candidate policy (blueprint I12 / §30.6).

    Measures *would-it-have-helped*: every session is scored against the current
    (baseline) policy and then against ``variant`` applied to the engine, then
    the engine policy is restored. This is a pure shadow evaluation — it never
    mutates production state. Cold-loop promotion (§23.3 step 3) requires the
    returned report to be ``non_inferior`` (no historical regression).
    """
    baseline = engine.policy
    if not within_invariant_rails(baseline, variant):
        raise ValueError("counterfactual replay variant violates invariant rails")
    before = 0
    after = 0
    details: list[dict[str, Any]] = []
    try:
        for session in sessions:
            engine.policy = baseline
            baseline_hit = _session_succeeds(engine, session)
            candidate_policy = OperatingPolicy.from_dict(baseline.to_dict())
            candidate_policy.activation_weights = dict(variant.activation_weights)
            candidate_policy.abstention_threshold = variant.abstention_threshold
            candidate_policy.top_k = variant.top_k
            engine.policy = candidate_policy
            candidate_hit = _session_succeeds(engine, session)
            before += int(baseline_hit)
            after += int(candidate_hit)
            details.append(
                {"query": session.query, "baseline": baseline_hit, "candidate": candidate_hit}
            )
    finally:
        engine.policy = baseline
    total = len(sessions)
    return CounterfactualReplayReport(
        before_successes=before,
        after_successes=after,
        total=total,
        lift=counterfactual_replay_score(before, after, total),
        non_inferior=after >= before,
        sessions=details,
    )


def policy_variant_from_dict(row: Mapping[str, Any]) -> PolicyVariant:
    weights = row.get("activation_weights")
    if not isinstance(weights, Mapping):
        raise ValueError("policy variant requires activation_weights object")
    return PolicyVariant(
        id=str(row["id"]),
        activation_weights={str(key): float(value) for key, value in weights.items()},
        abstention_threshold=float(row["abstention_threshold"]),
        top_k=int(row["top_k"]),
    )


def policy_ops_fingerprint(bundle: Mapping[str, Any]) -> str:
    encoded = json.dumps(bundle, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode("utf-8")).hexdigest()


def validate_policy_ops_bundle(
    bundle: Mapping[str, Any],
    *,
    min_variants: int = 2,
    min_outcomes: int = 3,
    min_tripwires: int = 1,
    required_variant_ids: list[str] | None = None,
    min_outcomes_per_required_variant: int = 1,
    min_cadence_window_hours: float = 1.0,
    max_updates_per_day: int = 4,
    min_diversity: float = 0.2,
    max_proxy_gap: float = OQ2_PROXY_TRUE_GAP,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    required_ids = list(required_variant_ids or [])
    tenant_id = str(bundle.get("tenant_id") or "")
    metric = str(bundle.get("metric") or "retrieval_quality")
    if not tenant_id:
        findings.append({"code": "missing_tenant", "message": "policy ops bundle requires tenant_id"})

    base_policy_raw = bundle.get("base_policy")
    if base_policy_raw is not None and not isinstance(base_policy_raw, Mapping):
        findings.append({"code": "invalid_base_policy", "message": "base_policy must be an object"})
        base_policy = OperatingPolicy()
    else:
        base_policy = OperatingPolicy.from_dict(dict(base_policy_raw or {}))
    if not all(base_policy.immutable_rails.values()):
        findings.append({"code": "base_rail_disabled", "message": "base policy has disabled immutable rails"})

    variants_raw = bundle.get("variants")
    if not isinstance(variants_raw, list):
        findings.append({"code": "invalid_variants", "message": "variants must be an array"})
        variants_raw = []
    variants: list[PolicyVariant] = []
    variant_reports: list[dict[str, Any]] = []
    for index, raw in enumerate(variants_raw, start=1):
        if not isinstance(raw, Mapping):
            findings.append({"code": "invalid_variant", "message": f"variant {index} must be an object"})
            continue
        variant_id = str(raw.get("id") or f"variant-{index}")
        try:
            variant = policy_variant_from_dict(raw)
        except (KeyError, TypeError, ValueError) as exc:
            findings.append({"code": "invalid_variant", "message": f"{variant_id}: {exc}"})
            continue
        rails_ok = within_invariant_rails(base_policy, variant)
        shadow_mode = raw.get("shadow_mode") is True
        variants.append(variant)
        variant_reports.append(
            {
                "id": variant.id,
                "rails_ok": rails_ok,
                "shadow_mode": shadow_mode,
                "top_k": variant.top_k,
                "abstention_threshold": variant.abstention_threshold,
            }
        )
        if not rails_ok:
            findings.append({"code": "variant_rail_violation", "message": f"{variant.id} violates immutable rails"})
        if not shadow_mode:
            findings.append({"code": "variant_not_shadow", "message": f"{variant.id} is not explicitly shadow_mode=true"})

    if len(variants) < min_variants:
        findings.append(
            {
                "code": "insufficient_variants",
                "message": f"variant count {len(variants)} is below required minimum {min_variants}",
            }
        )
    variant_ids = {variant.id for variant in variants}
    for variant_id in required_ids:
        if variant_id not in variant_ids:
            findings.append({"code": "missing_required_variant", "message": f"required variant {variant_id} is missing"})

    store = SelfModelStore()
    bandit = ContextualBanditLearner(store)
    outcomes_raw = bundle.get("outcomes")
    if not isinstance(outcomes_raw, list):
        findings.append({"code": "invalid_outcomes", "message": "outcomes must be an array"})
        outcomes_raw = []
    outcome_counts = {variant.id: 0 for variant in variants}
    for index, raw in enumerate(outcomes_raw, start=1):
        if not isinstance(raw, Mapping):
            findings.append({"code": "invalid_outcome", "message": f"outcome {index} must be an object"})
            continue
        variant_id = str(raw.get("variant_id") or "")
        context = raw.get("context")
        metrics = raw.get("metrics")
        if variant_id not in variant_ids:
            findings.append({"code": "unknown_outcome_variant", "message": f"outcome {index} references {variant_id}"})
            continue
        if context is not None and not isinstance(context, Mapping):
            findings.append({"code": "invalid_outcome_context", "message": f"outcome {index} context must be an object"})
            continue
        if metrics is not None and not isinstance(metrics, Mapping):
            findings.append({"code": "invalid_outcome_metrics", "message": f"outcome {index} metrics must be an object"})
            continue
        context_dict = dict(context or {"metric": metric})
        if context_dict.get("metric") != metric:
            findings.append({"code": "metric_context_mismatch", "message": f"outcome {index} metric context mismatch"})
            continue
        reward_source = str(raw.get("reward_source") or bundle.get("reward_source") or "")
        if reward_source not in {"external_eval", "human_feedback", "protected_suite"}:
            findings.append({"code": "invalid_reward_source", "message": f"outcome {index} lacks an external reward source"})
            continue
        try:
            reward = float(raw["reward"])
            bandit.record_outcome(
                tenant_id,
                variant_id,
                reward,
                context=context_dict,
                metrics={str(key): float(value) for key, value in dict(metrics or {}).items()},
            )
        except (KeyError, TypeError, ValueError) as exc:
            findings.append({"code": "invalid_outcome", "message": f"outcome {index}: {exc}"})
            continue
        outcome_counts[variant_id] += 1

    if len(outcomes_raw) < min_outcomes:
        findings.append(
            {
                "code": "insufficient_outcomes",
                "message": f"outcome count {len(outcomes_raw)} is below required minimum {min_outcomes}",
            }
        )
    for variant_id in required_ids:
        if outcome_counts.get(variant_id, 0) < min_outcomes_per_required_variant:
            findings.append(
                {
                    "code": "insufficient_required_variant_outcomes",
                    "message": f"{variant_id} has fewer than {min_outcomes_per_required_variant} outcomes",
                }
            )

    tripwires_raw = bundle.get("tripwires")
    if not isinstance(tripwires_raw, list):
        findings.append({"code": "invalid_tripwires", "message": "tripwires must be an array"})
        tripwires_raw = []
    tripwire_reports: list[dict[str, Any]] = []
    for index, raw in enumerate(tripwires_raw, start=1):
        if not isinstance(raw, Mapping):
            findings.append({"code": "invalid_tripwire", "message": f"tripwire {index} must be an object"})
            continue
        tripwire_id = str(raw.get("id") or f"tripwire-{index}")
        try:
            result = tripwire_check(
                diversity=float(raw["diversity"]),
                proxy_score=float(raw["proxy_score"]),
                true_score=float(raw["true_score"]),
                min_diversity=min_diversity,
                max_proxy_gap=max_proxy_gap,
            )
        except (KeyError, TypeError, ValueError) as exc:
            findings.append({"code": "invalid_tripwire", "message": f"{tripwire_id}: {exc}"})
            continue
        report = {"id": tripwire_id, **result.to_dict()}
        tripwire_reports.append(report)
        if not result.passed:
            findings.append({"code": "tripwire_failed", "message": f"{tripwire_id}: {result.reason}"})
    if len(tripwire_reports) < min_tripwires:
        findings.append(
            {
                "code": "insufficient_tripwires",
                "message": f"tripwire count {len(tripwire_reports)} is below required minimum {min_tripwires}",
            }
        )

    cadence = bundle.get("cadence")
    if not isinstance(cadence, Mapping):
        findings.append({"code": "invalid_cadence", "message": "cadence must be an object"})
        cadence = {}
    window_hours = float(cadence.get("window_hours", 0.0) or 0.0)
    updates_per_day = int(cadence.get("max_updates_per_day", max_updates_per_day + 1) or 0)
    if window_hours < min_cadence_window_hours:
        findings.append(
            {
                "code": "cadence_window_too_short",
                "message": f"cadence window {window_hours}h is below {min_cadence_window_hours}h",
            }
        )
    if updates_per_day > max_updates_per_day:
        findings.append(
            {
                "code": "cadence_updates_too_frequent",
                "message": f"max_updates_per_day {updates_per_day} exceeds {max_updates_per_day}",
            }
        )

    recommended_variant_id: str | None = None
    if variants:
        recommended_variant_id = bandit.choose_variant(tenant_id, variants, {"metric": metric}).id
    promotion = bundle.get("promotion")
    if not isinstance(promotion, Mapping):
        findings.append({"code": "invalid_promotion", "message": "promotion must be an object"})
        promotion = {}
    if promotion.get("mode") != "shadow":
        findings.append({"code": "promotion_not_shadow", "message": "policy ops validation requires shadow promotion mode"})
    if promotion.get("production_mutation") is not False:
        findings.append({"code": "production_mutation_enabled", "message": "shadow policy ops must not mutate production"})
    expected_variant_id = promotion.get("expected_recommended_variant_id")
    if expected_variant_id and expected_variant_id != recommended_variant_id:
        findings.append(
            {
                "code": "recommended_variant_mismatch",
                "message": "expected recommended variant does not match contextual bandit result",
            }
        )

    return {
        "ok": not findings,
        "fingerprint": policy_ops_fingerprint(bundle),
        "summary": {
            "tenant_id": tenant_id,
            "metric": metric,
            "variants": len(variants),
            "outcomes": len(outcomes_raw),
            "tripwires": len(tripwire_reports),
            "required_variant_ids": required_ids,
            "recommended_variant_id": recommended_variant_id,
        },
        "variants": variant_reports,
        "outcomes": {"counts_by_variant": outcome_counts},
        "tripwires": tripwire_reports,
        "cadence": {
            "window_hours": window_hours,
            "max_updates_per_day": updates_per_day,
        },
        "promotion": {
            "mode": promotion.get("mode"),
            "production_mutation": promotion.get("production_mutation"),
            "expected_recommended_variant_id": expected_variant_id,
        },
        "findings": findings,
    }
