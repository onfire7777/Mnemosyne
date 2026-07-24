"""§7 #17 — gate fact-candidates by external corroboration (§23.3).

Fail-closed: missing or self-only corroboration never promotes.
Uses Standing independent external counts only (not raw self-echo).
"""

from __future__ import annotations

from mnemosyne.gate import (
    evaluate_fact_external_corroboration,
    FactCorroborationVerdict,
)
from mnemosyne.policy import OperatingPolicy
from mnemosyne.standing import standing


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
