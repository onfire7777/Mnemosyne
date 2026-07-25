from __future__ import annotations

from datetime import UTC, datetime

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.gate import CounterfactualVerdict, RegressionCase
from mnemosyne.models import Assertion, Evidence
from mnemosyne.policy import OperatingPolicy
from mnemosyne.self_optimization import (
    OQ2_MIN_REPLAY_WINDOW,
    OQ2_PROXY_TRUE_GAP,
    PolicyVariant,
    SelfModelRecord,
    SelfModelStore,
    ShadowPolicyOptimizer,
    apply_cold_loop_counterfactual_trust,
    evaluate_oq2_fidelity,
    sign_agreement,
    spearman_rho,
    tripwire_check,
)


TENANT = "tenant-f"
USER = "user-f"


def seeded_engine() -> LocalMemoryEngine:
    engine = LocalMemoryEngine()
    cid = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="seed",
            content="Self optimization must remain inside immutable rails.",
            trust_tier=0,
            access_policy={"tenant": TENANT},
        )
    )
    engine.upsert_assertion(
        Assertion(
            tenant_id=TENANT,
            subject="self optimization",
            predicate="stays inside",
            object="immutable rails",
            confidence=0.95,
            source_evidence_cids=[cid],
            status="active",
            trust_tier=0,
            access_policy={"tenant": TENANT},
        )
    )
    return engine


def test_self_model_store_returns_latest_metric_window() -> None:
    store = SelfModelStore()
    first = SelfModelRecord(
        tenant_id=TENANT,
        metric="retrieval_quality",
        policy_version="v1",
        value=0.6,
        window_start=datetime(2026, 1, 1, tzinfo=UTC),
        window_end=datetime(2026, 1, 2, tzinfo=UTC),
    )
    second = SelfModelRecord(
        tenant_id=TENANT,
        metric="retrieval_quality",
        policy_version="v2",
        value=0.8,
        window_start=datetime(2026, 1, 2, tzinfo=UTC),
        window_end=datetime(2026, 1, 3, tzinfo=UTC),
    )

    store.add(first)
    store.add(second)

    assert store.latest(TENANT, "retrieval_quality").policy_version == "v2"


def test_policy_variant_proposal_responds_to_low_self_model_score() -> None:
    engine = seeded_engine()
    store = SelfModelStore()
    store.add(
        SelfModelRecord(
            tenant_id=TENANT,
            metric="retrieval_quality",
            policy_version="v1",
            value=0.4,
            window_start=datetime(2026, 1, 1, tzinfo=UTC),
            window_end=datetime(2026, 1, 2, tzinfo=UTC),
        )
    )
    optimizer = ShadowPolicyOptimizer(engine, [], self_model=store)

    variant = optimizer.propose_variant(TENANT)

    assert variant.id == "variant-retrieval_quality-recall"
    assert variant.top_k > engine.policy.top_k
    assert variant.activation_weights["semantic"] > engine.policy.activation_weights["semantic"]


def test_tripwire_blocks_low_diversity_and_proxy_divergence() -> None:
    low_diversity = tripwire_check(diversity=0.1, proxy_score=0.9, true_score=0.88)
    proxy_gap = tripwire_check(diversity=0.5, proxy_score=0.95, true_score=0.7)
    passing = tripwire_check(diversity=0.5, proxy_score=0.86, true_score=0.8)

    assert low_diversity.passed is False
    assert proxy_gap.passed is False
    assert passing.passed is True


def test_policy_canary_promotion_fails_closed_until_replay_is_proven() -> None:
    engine = seeded_engine()
    optimizer = ShadowPolicyOptimizer(
        engine,
        [
            RegressionCase(
                id="case-self-optimization-rails",
                signature="policy retrieval activation confidence",
                query="self optimization rails",
                expected_substring="immutable rails",
                protected=True,
            )
        ],
        require_ignition=False,
    )
    variant = PolicyVariant(
        id="safe",
        activation_weights={"base_level": 0.35, "semantic": 0.35, "importance": 0.20, "recency": 0.10},
        abstention_threshold=0.45,
        top_k=8,
    )

    result = optimizer.evaluate_variant(TENANT, variant)

    assert result.promoted is False
    assert result.counterfactual is not None
    assert result.counterfactual["passed"] is False
    assert "cf proxy unproven" in result.counterfactual["reason"]
    assert result.protected_regressions == []


def test_policy_canary_promotion_can_use_explicit_authorized_counterfactual_hook() -> None:
    engine = seeded_engine()
    optimizer = ShadowPolicyOptimizer(
        engine,
        [
            RegressionCase(
                id="case-self-optimization-rails",
                signature="policy retrieval activation confidence",
                query="self optimization rails",
                expected_substring="immutable rails",
                protected=True,
            )
        ],
        require_ignition=False,
    )
    variant = PolicyVariant(
        id="safe",
        activation_weights={"base_level": 0.35, "semantic": 0.35, "importance": 0.20, "recency": 0.10},
        abstention_threshold=0.45,
        top_k=8,
    )

    def authorized_hook(*_args, **_kwargs) -> CounterfactualVerdict:
        return CounterfactualVerdict(passed=True, predicted_lift=0.1, reason="explicitly authorized")

    result = optimizer.evaluate_variant(TENANT, variant, counterfactual_hook=authorized_hook)

    assert result.promoted is True
    assert result.counterfactual is not None
    assert result.counterfactual["reason"] == "explicitly authorized"


def _faithful_pairs(n: int = OQ2_MIN_REPLAY_WINDOW) -> list[tuple[float, float]]:
    """Deterministic high-fidelity (predicted, observed) pairs that clear OQ2 bar."""
    # Monotone near-identity with small noise so Spearman ρ≈1 and gap stays low.
    pairs: list[tuple[float, float]] = []
    for i in range(n):
        # Span negative / zero / positive for sign coverage and active-pair count.
        predicted = (i - n / 2) / n
        observed = predicted + (0.01 if i % 2 == 0 else -0.01)
        pairs.append((predicted, observed))
    return pairs


def test_oq2_fidelity_fails_closed_below_window() -> None:
    report = evaluate_oq2_fidelity([(0.1, 0.1), (0.2, 0.19)])
    assert report.bar_passed is False
    assert report.authorized_to_trust is False
    assert report.n < OQ2_MIN_REPLAY_WINDOW
    failed = {item["name"] for item in report.checks if not item["pass"]}
    assert "window" in failed


def test_oq2_fidelity_fails_when_proxy_uncorrelated() -> None:
    # Same magnitudes, reversed order → poor rank correlation / sign agreement.
    n = OQ2_MIN_REPLAY_WINDOW
    predicted = [(i - n / 2) / n for i in range(n)]
    observed = list(reversed(predicted))
    report = evaluate_oq2_fidelity(list(zip(predicted, observed, strict=True)))
    assert report.n == n
    assert report.bar_passed is False
    assert report.authorized_to_trust is False
    assert report.rho < 0.6


def test_oq2_fidelity_report_deterministic_for_fixed_pairs() -> None:
    pairs = _faithful_pairs()
    first = evaluate_oq2_fidelity(pairs, seed=17)
    second = evaluate_oq2_fidelity(pairs, seed=17)
    assert first.to_dict() == second.to_dict()
    assert first.bar_passed is True
    assert first.authorized_to_trust is True
    assert first.proxy_true_gap <= OQ2_PROXY_TRUE_GAP
    assert first.sign_agreement >= 0.80
    assert first.rho >= 0.60
    assert first.rho_ci.low > 0.30


def test_oq2_fidelity_does_not_auto_flip_cold_loop_rail() -> None:
    policy = OperatingPolicy()
    assert policy.cold_loop_counterfactual_trusted is False
    report = evaluate_oq2_fidelity(_faithful_pairs())
    assert report.authorized_to_trust is True
    # Recorder alone must never mutate the rail.
    assert policy.cold_loop_counterfactual_trusted is False


def test_apply_cold_loop_trust_requires_authorization_and_enable() -> None:
    policy = OperatingPolicy()
    bad = evaluate_oq2_fidelity([(0.5, -0.5)] * 10)
    assert bad.authorized_to_trust is False
    assert apply_cold_loop_counterfactual_trust(policy, bad, enable=True) is False
    assert policy.cold_loop_counterfactual_trusted is False

    good = evaluate_oq2_fidelity(_faithful_pairs())
    assert good.authorized_to_trust is True
    # enable=False demotes even when authorized.
    assert apply_cold_loop_counterfactual_trust(policy, good, enable=False) is False
    assert policy.cold_loop_counterfactual_trusted is False
    # Explicit enable + authorized bar → rail may flip.
    assert apply_cold_loop_counterfactual_trust(policy, good, enable=True) is True
    assert policy.cold_loop_counterfactual_trusted is True


def test_self_model_store_records_pairs_and_scores_oq2() -> None:
    store = SelfModelStore()
    for predicted, observed in _faithful_pairs():
        store.record_replay_pair(TENANT, "variant-a", predicted, observed)
    report = store.evaluate_oq2_fidelity(TENANT)
    assert report.n == OQ2_MIN_REPLAY_WINDOW
    assert report.bar_passed is True
    assert report.authorized_to_trust is True
    # Other tenants empty → fail closed.
    empty = store.evaluate_oq2_fidelity("other-tenant")
    assert empty.n == 0
    assert empty.authorized_to_trust is False


def test_spearman_and_sign_agreement_helpers() -> None:
    assert spearman_rho([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 1.0
    assert spearman_rho([1.0, 2.0, 3.0], [3.0, 2.0, 1.0]) == -1.0
    assert sign_agreement([0.1, -0.2, 0.0], [0.05, -0.1, 0.0]) == 1.0
    assert sign_agreement([0.1, -0.2], [-0.1, 0.2]) == 0.0


def test_untrusted_proxy_still_fails_closed_with_recorded_pairs_below_bar() -> None:
    """default_counterfactual_hook remains fail-closed when pairs exist but OQ2 bar fails."""
    engine = seeded_engine()
    store = SelfModelStore()
    # Enough pairs for the *hook window* path but with huge gap → still unproven.
    for i in range(OQ2_MIN_REPLAY_WINDOW):
        store.record_replay_pair(TENANT, "v", predicted_lift=0.5, observed_lift=-0.5)
    oq2 = store.evaluate_oq2_fidelity(TENANT)
    assert oq2.authorized_to_trust is False
    optimizer = ShadowPolicyOptimizer(
        engine,
        [
            RegressionCase(
                id="case-self-optimization-rails",
                signature="policy retrieval activation confidence",
                query="self optimization rails",
                expected_substring="immutable rails",
                protected=True,
            )
        ],
        self_model=store,
        require_ignition=False,
    )
    variant = PolicyVariant(
        id="safe",
        activation_weights={"base_level": 0.35, "semantic": 0.35, "importance": 0.20, "recency": 0.10},
        abstention_threshold=0.45,
        top_k=8,
    )
    result = optimizer.evaluate_variant(TENANT, variant)
    assert result.promoted is False
    assert result.counterfactual is not None
    assert result.counterfactual["passed"] is False
    assert "cf proxy unproven" in result.counterfactual["reason"]
