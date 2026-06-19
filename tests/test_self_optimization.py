from __future__ import annotations

from datetime import UTC, datetime

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.gate import RegressionCase
from mnemosyne.models import Assertion, Evidence
from mnemosyne.self_optimization import (
    PolicyVariant,
    SelfModelRecord,
    SelfModelStore,
    ShadowPolicyOptimizer,
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
            trust_tier=3,
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
            trust_tier=3,
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


def test_policy_canary_promotion_uses_gate_and_rails() -> None:
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
    )
    variant = PolicyVariant(
        id="safe",
        activation_weights={"base_level": 0.35, "semantic": 0.35, "importance": 0.20, "recency": 0.10},
        abstention_threshold=0.45,
        top_k=8,
    )

    result = optimizer.evaluate_variant(TENANT, variant)

    assert result.promoted is True
    assert result.protected_regressions == []

