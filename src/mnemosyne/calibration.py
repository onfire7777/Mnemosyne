"""Conformal calibration for confidence and abstention."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class CalibrationSet:
    tenant_id: str
    memory_type: str
    scores: list[float]
    target_coverage: float = 0.9

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CalibrationExample:
    confidence: float
    correct: bool
    prediction_set_size: int = 1

    @classmethod
    def from_mapping(cls, row: dict[str, Any]) -> "CalibrationExample":
        if "confidence" not in row:
            raise ValueError("calibration example requires confidence")
        if "correct" not in row:
            raise ValueError("calibration example requires correct")
        confidence = max(0.0, min(1.0, float(row["confidence"])))
        prediction_set_size = int(row.get("prediction_set_size", 1))
        if prediction_set_size < 0:
            raise ValueError("calibration example prediction_set_size must be non-negative")
        return cls(
            confidence=confidence,
            correct=bool(row["correct"]),
            prediction_set_size=prediction_set_size,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CalibrationTuneResult:
    calibration: CalibrationSet
    threshold: float
    metrics: dict[str, Any]
    failures: list[str]

    @property
    def ok(self) -> bool:
        return not self.failures

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "calibration": self.calibration.to_dict(),
            "threshold": self.threshold,
            "metrics": dict(self.metrics),
            "failures": list(self.failures),
        }


def conformal_threshold(calibration: CalibrationSet) -> float:
    """Return the split-conformal accept threshold for a calibration set.

    Computes the lower ``alpha``-quantile (``alpha = 1 - target_coverage``) of
    the calibration scores so that at least ``target_coverage`` of correctly
    answered memories clear the bar. An empty calibration set returns ``1.0``,
    which makes the system abstain on everything (fail-closed metacognition).
    """
    if not calibration.scores:
        return 1.0
    bounded = sorted(max(0.0, min(1.0, score)) for score in calibration.scores)
    alpha = 1.0 - calibration.target_coverage
    index = min(len(bounded) - 1, max(0, int((len(bounded) + 1) * alpha) - 1))
    return bounded[index]


def should_abstain(confidence: float, calibration: CalibrationSet, prediction_set_size: int = 1, max_set_size: int = 3) -> bool:
    """Decide whether to abstain rather than answer from this memory.

    Abstains when the conformal prediction set is empty or larger than
    ``max_set_size`` (the evidence is too thin or too ambiguous), or when the
    calibrated ``confidence`` falls below :func:`conformal_threshold`.
    """
    if prediction_set_size == 0 or prediction_set_size > max_set_size:
        return True
    return confidence < conformal_threshold(calibration)


def nonconformity_score(confidence: float) -> float:
    """Conformal nonconformity score for a calibrated confidence.

    Uses ``1 - confidence`` so that a more confident memory is *less*
    nonconforming. This is the per-example score the conformal prediction set is
    thresholded against.
    """
    return 1.0 - max(0.0, min(1.0, confidence))


def conformal_prediction_set(
    scored_labels: list[tuple[str, float]],
    calibration: CalibrationSet,
) -> list[str]:
    """Build the conformal prediction set for one query's candidate labels.

    Keeps every candidate whose :func:`nonconformity_score` is within the
    calibrated quantile — equivalently, whose confidence clears
    :func:`conformal_threshold` — ordered by descending confidence. An empty set
    signals that no candidate is supported strongly enough, so the caller should
    abstain rather than guess.
    """
    cutoff = nonconformity_score(conformal_threshold(calibration))
    chosen = [
        (label, max(0.0, min(1.0, confidence)))
        for label, confidence in scored_labels
        if nonconformity_score(confidence) <= cutoff
    ]
    chosen.sort(key=lambda row: row[1], reverse=True)
    return [label for label, _ in chosen]


def conformal_should_abstain(
    scored_labels: list[tuple[str, float]],
    calibration: CalibrationSet,
    max_set_size: int = 3,
) -> bool:
    """Abstain when the computed conformal prediction set is empty or too large.

    Unlike :func:`should_abstain`, which takes a pre-computed prediction-set
    size, this derives the set from the candidate labels via
    :func:`conformal_prediction_set` and abstains when it is empty (evidence too
    thin) or larger than ``max_set_size`` (too ambiguous to answer).
    """
    prediction_set = conformal_prediction_set(scored_labels, calibration)
    return not prediction_set or len(prediction_set) > max_set_size


def calibration_examples_from_rows(rows: list[dict[str, Any]]) -> list[CalibrationExample]:
    return [CalibrationExample.from_mapping(row) for row in rows]


def tune_calibration_set(
    *,
    tenant_id: str,
    memory_type: str,
    examples: list[CalibrationExample],
    target_coverage: float = 0.9,
    min_examples: int = 20,
    min_correct: int = 1,
    min_incorrect: int = 1,
    min_empirical_coverage: float | None = None,
    max_false_accept_rate: float = 0.1,
    max_prediction_set_size: int = 3,
) -> CalibrationTuneResult:
    """Fit a calibration set from labelled examples and gate its quality.

    Builds the calibration scores from the correctly answered examples, derives
    the conformal threshold, and validates the resulting accept/abstain policy
    against minimum sample sizes, an empirical-coverage floor, and a
    false-accept ceiling. The returned :class:`CalibrationTuneResult` is
    ``ok`` only when every gate passes, so an under-powered or poorly separated
    calibration set fails closed instead of silently shipping.
    """
    target_coverage = max(0.0, min(1.0, target_coverage))
    min_empirical_coverage = (
        max(0.0, target_coverage - 0.05)
        if min_empirical_coverage is None
        else max(0.0, min(1.0, min_empirical_coverage))
    )
    correct_examples = [example for example in examples if example.correct]
    incorrect_examples = [example for example in examples if not example.correct]
    calibration = CalibrationSet(
        tenant_id=tenant_id,
        memory_type=memory_type,
        scores=[example.confidence for example in correct_examples],
        target_coverage=target_coverage,
    )
    threshold = conformal_threshold(calibration)
    accepted = [
        example
        for example in examples
        if not should_abstain(
            example.confidence,
            calibration,
            prediction_set_size=example.prediction_set_size,
            max_set_size=max_prediction_set_size,
        )
    ]
    accepted_correct = [example for example in accepted if example.correct]
    accepted_incorrect = [example for example in accepted if not example.correct]
    correct_coverage = len(accepted_correct) / len(correct_examples) if correct_examples else 0.0
    false_accept_rate = len(accepted_incorrect) / len(incorrect_examples) if incorrect_examples else 0.0
    abstention_rate = 1.0 - (len(accepted) / len(examples)) if examples else 1.0
    failures: list[str] = []
    if len(examples) < min_examples:
        failures.append(f"example count {len(examples)} is below required minimum {min_examples}")
    if len(correct_examples) < min_correct:
        failures.append(f"correct example count {len(correct_examples)} is below required minimum {min_correct}")
    if len(incorrect_examples) < min_incorrect:
        failures.append(f"incorrect example count {len(incorrect_examples)} is below required minimum {min_incorrect}")
    if correct_coverage < min_empirical_coverage:
        failures.append(
            f"empirical correct coverage {correct_coverage:.6f} is below required minimum {min_empirical_coverage:.6f}"
        )
    if false_accept_rate > max_false_accept_rate:
        failures.append(
            f"false accept rate {false_accept_rate:.6f} exceeds allowed maximum {max_false_accept_rate:.6f}"
        )
    return CalibrationTuneResult(
        calibration=calibration,
        threshold=threshold,
        metrics={
            "examples": len(examples),
            "correct_examples": len(correct_examples),
            "incorrect_examples": len(incorrect_examples),
            "accepted": len(accepted),
            "accepted_correct": len(accepted_correct),
            "accepted_incorrect": len(accepted_incorrect),
            "correct_coverage": correct_coverage,
            "false_accept_rate": false_accept_rate,
            "abstention_rate": abstention_rate,
            "target_coverage": target_coverage,
            "min_empirical_coverage": min_empirical_coverage,
            "max_false_accept_rate": max_false_accept_rate,
            "max_prediction_set_size": max_prediction_set_size,
        },
        failures=failures,
    )
