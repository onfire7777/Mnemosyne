"""§7 #17 — gate fact-candidates by external corroboration (§23.3).

Fail-closed: missing or self-only corroboration never promotes.
Uses Standing independent external counts only (not raw self-echo).
Pins refuse/allow through PromotionGate.evaluate (not helper-only).
"""

from __future__ import annotations

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.gate import (
    Candidate,
    FactCorroborationVerdict,
    PromotionGate,
    RegressionCase,
    evaluate_fact_external_corroboration,
)
from mnemosyne.policy import OperatingPolicy
from mnemosyne.standing import standing

TENANT = "tenant-g17"


def test_missing_corroboration_fails_closed() -> None:
    verdict = evaluate_fact_external_corroboration(
        unit_signals={
            "reality_class": "grounded",
            "trust_tier": 0,
            "independent_corroboration_count": 0,
            "independent_corroboration_weight": 0.0,
        }
    )
    assert isinstance(verdict, FactCorroborationVerdict)
    assert verdict.allowed is False
    assert verdict.independent_external_count == 0
    assert verdict.required >= 2
    assert "insufficient" in verdict.reason or "missing" in verdict.reason


def test_self_only_corroboration_fails_closed() -> None:
    """Self-generated echoes must not count as external corroboration (§23.3)."""
    verdict = evaluate_fact_external_corroboration(
        unit_signals={
            "reality_class": "self_generated",
            "trust_tier": 0,
            "corroboration_count": 10,
            "independent_corroboration_count": 10,
            "independent_corroboration_weight": 1.0,
            "self_generated_corroboration_count": 10,
        }
    )
    assert verdict.allowed is False
    assert verdict.independent_external_count == 0
    assert verdict.standing is not None
    assert verdict.standing["authority"] is False


def test_independent_external_corroboration_meets_floor() -> None:
    policy = OperatingPolicy()
    verdict = evaluate_fact_external_corroboration(
        unit_signals={
            "reality_class": "grounded",
            "trust_tier": 0,
            "calibrated_confidence": 0.5,
            "independent_corroboration_count": 2,
            "independent_corroboration_weight": 0.4,
        },
        policy=policy,
    )
    assert verdict.allowed is True
    assert verdict.independent_external_count >= policy.min_external_corroboration_for_fact
    assert verdict.required == policy.min_external_corroboration_for_fact
    assert verdict.standing is not None
    assert verdict.standing["authority"] is True


def test_policy_floor_is_respected_and_immutable_default() -> None:
    policy = OperatingPolicy()
    assert policy.min_external_corroboration_for_fact == 2
    # One independent source is not enough under the default floor.
    one = evaluate_fact_external_corroboration(
        unit_signals={
            "reality_class": "grounded",
            "trust_tier": 0,
            "independent_corroboration_count": 1,
            "independent_corroboration_weight": 0.2,
        },
        policy=policy,
    )
    assert one.allowed is False
    # Explicit higher floor still fails closed below it.
    strict = evaluate_fact_external_corroboration(
        unit_signals={
            "reality_class": "grounded",
            "trust_tier": 0,
            "independent_corroboration_count": 2,
            "independent_corroboration_weight": 0.4,
        },
        policy=OperatingPolicy(min_external_corroboration_for_fact=3),
    )
    assert strict.allowed is False
    assert strict.required == 3


def test_unknown_reality_class_fails_closed_even_with_counts() -> None:
    verdict = evaluate_fact_external_corroboration(
        unit_signals={
            "reality_class": "unknown",
            "trust_tier": 0,
            "independent_corroboration_count": 5,
            "independent_corroboration_weight": 1.0,
        }
    )
    assert verdict.allowed is False
    assert verdict.independent_external_count == 0


def test_gate_consumes_standing_effective_independent_count() -> None:
    """Gate must use Standing's effective external count, not raw self-echo."""
    signals = {
        "reality_class": "self_generated",
        "trust_tier": 0,
        "independent_corroboration_count": 5,
        "self_generated_corroboration_count": 5,
    }
    score = standing(signals)
    effective = int(score.explain["inputs"]["effective_independent_corroboration_count"])
    verdict = evaluate_fact_external_corroboration(unit_signals=signals)
    assert effective == 0
    assert verdict.independent_external_count == effective
    assert verdict.allowed is False


def test_empty_signals_fail_closed() -> None:
    verdict = evaluate_fact_external_corroboration(unit_signals=None)
    assert verdict.allowed is False
    assert verdict.independent_external_count == 0


def _fact_candidate(
    *,
    branch: str,
    cids: list[str],
    unit_signals: dict | None = None,
) -> Candidate:
    return Candidate(
        id=f"cand-{branch}",
        kind="fact",
        signature="grounded fact",
        description="fact under external corroboration rail",
        branch=branch,
        source_evidence_cids=list(cids),
        unit_signals=unit_signals,
    )


def test_promotion_gate_refuses_fact_with_self_only_corroboration() -> None:
    """Refuse path must run through PromotionGate.evaluate, not helper alone."""
    engine = LocalMemoryEngine()
    # Suite-promotable baseline (empty cases, negative noise); fact rail must veto.
    gate = PromotionGate(engine, [], noise_margin=-1.0)
    candidate = _fact_candidate(
        branch="self-only",
        cids=["cid-self-a", "cid-self-b"],
        unit_signals={
            "reality_class": "self_generated",
            "trust_tier": 0,
            "independent_corroboration_count": 10,
            "self_generated_corroboration_count": 10,
        },
    )

    def apply(_engine: LocalMemoryEngine, _branch: str) -> None:
        return None

    result = gate.evaluate(TENANT, candidate, apply)
    assert result.promoted is False
    assert any("fact_external_corroboration" in item for item in result.failed_cases)
    assert any("fact_external_corroboration" in item for item in result.protected_regressions)


def test_promotion_gate_refuses_fact_below_policy_floor() -> None:
    engine = LocalMemoryEngine()
    gate = PromotionGate(engine, [], noise_margin=-1.0)
    # Explicit Standing signals: one independent source < policy floor 2.
    candidate = _fact_candidate(
        branch="one-cid",
        cids=["cid-only"],
        unit_signals={
            "reality_class": "grounded",
            "trust_tier": 0,
            "independent_corroboration_count": 1,
            "independent_corroboration_weight": 0.2,
        },
    )

    def apply(_engine: LocalMemoryEngine, _branch: str) -> None:
        return None

    result = gate.evaluate(TENANT, candidate, apply)
    assert result.promoted is False
    assert any("fact_external_corroboration" in item for item in result.failed_cases)


def test_promotion_gate_derived_cid_path_allows_single_source_transitional() -> None:
    """CID-derived path keeps dual-standard min_external=1 until consolidation migrates."""
    engine = LocalMemoryEngine()
    gate = PromotionGate(engine, [], noise_margin=-1.0)
    candidate = _fact_candidate(branch="one-cid-derived", cids=["cid-only"])

    def apply(_engine: LocalMemoryEngine, _branch: str) -> None:
        return None

    result = gate.evaluate(TENANT, candidate, apply)
    assert result.promoted is True
    assert result.failed_cases == []


def test_promotion_gate_allows_fact_with_independent_external_floor() -> None:
    """Empty suite + negative noise → suite would promote; fact rail allows ≥ floor."""
    engine = LocalMemoryEngine()
    # Empty relevant cases: total=1, margin = 0 - (-1) = 1 > 0 → suite-promotable.
    gate = PromotionGate(engine, [], noise_margin=-1.0)
    candidate = _fact_candidate(
        branch="ok-floor",
        cids=["cid-a", "cid-b"],
        unit_signals={
            "reality_class": "grounded",
            "trust_tier": 0,
            "independent_corroboration_count": 2,
            "independent_corroboration_weight": 0.4,
        },
    )

    def apply(_engine: LocalMemoryEngine, _branch: str) -> None:
        return None

    result = gate.evaluate(TENANT, candidate, apply)
    assert result.promoted is True
    assert result.failed_cases == []
    assert result.protected_regressions == []


def test_promotion_gate_fact_rail_never_rescues_failed_suite() -> None:
    engine = LocalMemoryEngine()
    case = RegressionCase(
        id="protected-miss",
        signature="grounded fact",
        query="never-present-query",
        expected_substring="missing-substring",
        protected=True,
    )
    gate = PromotionGate(engine, [case])
    candidate = _fact_candidate(
        branch="no-rescue",
        cids=["cid-a", "cid-b"],
        unit_signals={
            "reality_class": "grounded",
            "trust_tier": 0,
            "independent_corroboration_count": 5,
            "independent_corroboration_weight": 1.0,
        },
    )

    def apply(_engine: LocalMemoryEngine, _branch: str) -> None:
        return None

    result = gate.evaluate(TENANT, candidate, apply)
    assert result.promoted is False
    assert "protected-miss" in result.protected_regressions
    assert not any("fact_external_corroboration" in item for item in result.failed_cases)
