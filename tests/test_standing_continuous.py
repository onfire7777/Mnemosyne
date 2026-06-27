from __future__ import annotations

from eval.g0.standing_calibration import run_standing_calibration_eval
from mnemosyne.standing import (
    EVIDENCE_DOMINANCE_GAP,
    GROUNDED_FLOOR,
    SELF_GENERATED_CEILING,
    standing,
)


def test_salience_never_changes_standing_authority() -> None:
    low_salience = standing(
        {
            "reality_class": "self_generated",
            "trust_tier": 5,
            "calibrated_confidence": 1.0,
            "activation": 0.0,
        }
    )
    high_salience = standing(
        {
            "reality_class": "self_generated",
            "trust_tier": 5,
            "calibrated_confidence": 1.0,
            "activation": 1.0,
        }
    )
    assert high_salience.salience > low_salience.salience
    assert high_salience.groundedness == low_salience.groundedness
    assert high_salience.authority is low_salience.authority
    assert high_salience.explain["salience_excluded_from_authority"] is True


def test_independent_external_corroboration_raises_groundedness() -> None:
    weak = standing(
        {
            "reality_class": "grounded",
            "trust_tier": 0,
            "calibrated_confidence": 0.2,
            "independent_corroboration_count": 0,
            "independent_corroboration_weight": 0.0,
        }
    )
    strong = standing(
        {
            "reality_class": "grounded",
            "trust_tier": 0,
            "calibrated_confidence": 0.2,
            "independent_corroboration_count": 5,
            "independent_corroboration_weight": 1.0,
        }
    )

    assert weak.groundedness >= GROUNDED_FLOOR
    assert strong.groundedness > weak.groundedness
    assert strong.authority is True


def test_self_generated_corroboration_cannot_cross_evidence_band() -> None:
    self_echo = standing(
        {
            "reality_class": "self_generated",
            "trust_tier": 0,
            "calibrated_confidence": 1.0,
            "corroboration_count": 10,
            "independent_corroboration_count": 10,
            "independent_corroboration_weight": 1.0,
            "self_generated_corroboration_count": 10,
            "activation": 1.0,
        }
    )
    external_min = standing({"reality_class": "grounded", "trust_tier": 5, "calibrated_confidence": 0.0})

    assert self_echo.groundedness <= SELF_GENERATED_CEILING
    assert self_echo.authority is False
    assert self_echo.explain["inputs"]["effective_independent_corroboration_count"] == 0
    assert external_min.groundedness - self_echo.groundedness >= EVIDENCE_DOMINANCE_GAP


def test_contradiction_and_decay_lower_groundedness_within_external_band() -> None:
    fresh = standing(
        {
            "reality_class": "grounded",
            "trust_tier": 0,
            "calibrated_confidence": 1.0,
            "independent_corroboration_count": 5,
            "independent_corroboration_weight": 1.0,
        }
    )
    stale_contested = standing(
        {
            "reality_class": "grounded",
            "trust_tier": 0,
            "calibrated_confidence": 1.0,
            "independent_corroboration_count": 5,
            "independent_corroboration_weight": 1.0,
            "contradiction_pressure": 1.0,
            "groundedness_decay": 1.0,
        }
    )

    assert stale_contested.groundedness < fresh.groundedness
    assert stale_contested.groundedness >= GROUNDED_FLOOR


def test_g0_standing_calibration_fixture_reports_p2_contracts() -> None:
    report = run_standing_calibration_eval()

    assert report["schema_version"] == "g0.standing_calibration.v1"
    assert report["standing_calibration_error"] <= 0.05
    assert report["standing_conformal_coverage"] >= 0.95
    assert report["standing_false_accept_rate"] == 0.0
    assert report["standing_salience_invariance_contract"] == 1.0
    assert report["standing_independent_corroboration_contract"] == 1.0
    assert report["standing_evidence_dominance_gap"] >= EVIDENCE_DOMINANCE_GAP
    assert report["passed"] is True
