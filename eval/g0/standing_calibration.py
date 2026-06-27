"""G0 Standing calibration fixture.

This reports functional Standing properties for Phase 7 P2. It is a local,
deterministic probe: it does not claim production calibration evidence, but it
does make the Standing contract measurable and gateable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mnemosyne.calibration import CalibrationSet, conformal_threshold, should_abstain
from mnemosyne.standing import (
    EVIDENCE_DOMINANCE_GAP,
    GROUNDED_FLOOR,
    SELF_GENERATED_CEILING,
    STANDING_FN_VERSION,
    standing,
)


@dataclass(frozen=True, slots=True)
class StandingCalibrationCase:
    case_id: str
    signals: dict[str, Any]
    observed_corroboration_likelihood: float


CALIBRATION_CASES: tuple[StandingCalibrationCase, ...] = (
    StandingCalibrationCase(
        "external_operator_1",
        {
            "reality_class": "grounded",
            "trust_tier": 0,
            "calibrated_confidence": 1.0,
            "independent_corroboration_count": 5,
            "independent_corroboration_weight": 1.0,
        },
        1.0,
    ),
    StandingCalibrationCase(
        "external_operator_2",
        {
            "reality_class": "evidence_grounded",
            "trust_tier": 0,
            "calibrated_confidence": 1.0,
            "independent_corroboration_count": 6,
            "independent_corroboration_weight": 1.0,
        },
        1.0,
    ),
    StandingCalibrationCase(
        "unknown_fail_closed_1",
        {
            "reality_class": "unknown",
            "trust_tier": 5,
            "calibrated_confidence": 0.0,
            "contradiction_pressure": 1.0,
            "groundedness_decay": 1.0,
        },
        0.0,
    ),
    StandingCalibrationCase(
        "self_generated_rejected_1",
        {
            "reality_class": "self_generated",
            "trust_tier": 5,
            "calibrated_confidence": 0.0,
            "self_generated_corroboration_count": 3,
            "contradiction_pressure": 1.0,
            "groundedness_decay": 1.0,
            "activation": 1.0,
        },
        0.0,
    ),
)


def run_standing_calibration_eval(*, repo_root: Path | None = None) -> dict[str, Any]:
    """Return deterministic Standing calibration and contract metrics."""

    _ = repo_root
    rows = [_row(case) for case in CALIBRATION_CASES]
    reliability_bins = _reliability_bins(rows)
    calibration_error = round(
        sum(bin_row["weight"] * abs(bin_row["mean_groundedness"] - bin_row["observed_rate"]) for bin_row in reliability_bins),
        6,
    )
    positives = [row for row in rows if row["observed_corroboration_likelihood"] >= 1.0]
    negatives = [row for row in rows if row["observed_corroboration_likelihood"] <= 0.0]
    calibration = CalibrationSet(
        tenant_id="g0-standing",
        memory_type="standing",
        scores=[row["groundedness"] for row in positives],
        target_coverage=0.95,
    )
    threshold = conformal_threshold(calibration)
    accepted_positive = [
        row
        for row in positives
        if not should_abstain(row["groundedness"], calibration, prediction_set_size=1, max_set_size=1)
    ]
    accepted_negative = [
        row
        for row in negatives
        if not should_abstain(row["groundedness"], calibration, prediction_set_size=1, max_set_size=1)
    ]
    conformal_coverage = round(len(accepted_positive) / max(len(positives), 1), 6)
    false_accept_rate = round(len(accepted_negative) / max(len(negatives), 1), 6)
    salience_contract = _salience_invariance_contract()
    independent_contract = _independent_corroboration_contract()
    evidence_gap = _evidence_dominance_gap(rows)
    passed = (
        calibration_error <= 0.05
        and conformal_coverage >= 0.95
        and false_accept_rate == 0.0
        and salience_contract == 1.0
        and independent_contract == 1.0
        and evidence_gap >= EVIDENCE_DOMINANCE_GAP
    )
    return {
        "schema_version": "g0.standing_calibration.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "standing_fn_version": STANDING_FN_VERSION,
        "measurement_scope": "deterministic local Standing fixture, not production operator evidence",
        "standing_calibration_error": calibration_error,
        "standing_conformal_coverage": conformal_coverage,
        "standing_false_accept_rate": false_accept_rate,
        "standing_salience_invariance_contract": salience_contract,
        "standing_independent_corroboration_contract": independent_contract,
        "standing_evidence_dominance_gap": evidence_gap,
        "conformal_threshold": round(threshold, 6),
        "target_coverage": calibration.target_coverage,
        "reliability_bins": reliability_bins,
        "rows": rows,
        "passed": passed,
    }


def _row(case: StandingCalibrationCase) -> dict[str, Any]:
    score = standing(case.signals)
    return {
        "case_id": case.case_id,
        "signals": dict(case.signals),
        "groundedness": score.groundedness,
        "salience": score.salience,
        "authority": score.authority,
        "observed_corroboration_likelihood": case.observed_corroboration_likelihood,
        "explain": score.explain,
    }


def _reliability_bins(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {"low": [], "external": []}
    for row in rows:
        key = "external" if row["groundedness"] >= GROUNDED_FLOOR else "low"
        grouped[key].append(row)
    total = max(len(rows), 1)
    bins: list[dict[str, Any]] = []
    for key in ("low", "external"):
        items = grouped[key]
        if not items:
            continue
        mean_groundedness = sum(row["groundedness"] for row in items) / len(items)
        observed_rate = sum(row["observed_corroboration_likelihood"] for row in items) / len(items)
        bins.append(
            {
                "bin": key,
                "count": len(items),
                "weight": round(len(items) / total, 6),
                "mean_groundedness": round(mean_groundedness, 6),
                "observed_rate": round(observed_rate, 6),
                "abs_error": round(abs(mean_groundedness - observed_rate), 6),
            }
        )
    return bins


def _salience_invariance_contract() -> float:
    low = standing(
        {
            "reality_class": "self_generated",
            "trust_tier": 5,
            "calibrated_confidence": 1.0,
            "activation": 0.0,
        }
    )
    high = standing(
        {
            "reality_class": "self_generated",
            "trust_tier": 5,
            "calibrated_confidence": 1.0,
            "activation": 1.0,
        }
    )
    external_low = standing(
        {
            "reality_class": "grounded",
            "trust_tier": 0,
            "calibrated_confidence": 1.0,
            "independent_corroboration_count": 5,
            "independent_corroboration_weight": 1.0,
            "activation": 0.0,
        }
    )
    external_high = standing(
        {
            "reality_class": "grounded",
            "trust_tier": 0,
            "calibrated_confidence": 1.0,
            "independent_corroboration_count": 5,
            "independent_corroboration_weight": 1.0,
            "activation": 1.0,
        }
    )
    return 1.0 if low.authority is high.authority and external_low.authority is external_high.authority else 0.0


def _independent_corroboration_contract() -> float:
    self_echo = standing(
        {
            "reality_class": "self_generated",
            "trust_tier": 0,
            "calibrated_confidence": 1.0,
            "corroboration_count": 8,
            "independent_corroboration_count": 8,
            "independent_corroboration_weight": 1.0,
            "self_generated_corroboration_count": 8,
        }
    )
    grounded_weak = standing(
        {
            "reality_class": "grounded",
            "trust_tier": 0,
            "calibrated_confidence": 0.2,
            "independent_corroboration_count": 0,
            "independent_corroboration_weight": 0.0,
        }
    )
    grounded_strong = standing(
        {
            "reality_class": "grounded",
            "trust_tier": 0,
            "calibrated_confidence": 0.2,
            "independent_corroboration_count": 5,
            "independent_corroboration_weight": 1.0,
        }
    )
    if self_echo.groundedness > SELF_GENERATED_CEILING:
        return 0.0
    if grounded_strong.groundedness <= grounded_weak.groundedness:
        return 0.0
    if self_echo.explain["inputs"]["effective_independent_corroboration_count"] != 0:
        return 0.0
    return 1.0


def _evidence_dominance_gap(rows: list[dict[str, Any]]) -> float:
    external = [row["groundedness"] for row in rows if row["groundedness"] >= GROUNDED_FLOOR]
    self_band = [row["groundedness"] for row in rows if row["groundedness"] <= SELF_GENERATED_CEILING]
    if not external or not self_band:
        return 0.0
    return round(min(external) - max(self_band), 6)


def main() -> int:
    import json

    print(json.dumps(run_standing_calibration_eval(), indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
