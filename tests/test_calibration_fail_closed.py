"""Confidence must never manufacture evidence from missing calibration."""
import math
from types import SimpleNamespace

import pytest

from mnemosyne.calibration import (
    CalibrationExample,
    CalibrationSet,
    conformal_prediction_set,
    conformal_prediction_set_size_for_hits,
    conformal_should_abstain,
    should_abstain,
)


def test_empty_calibration_rejects_even_a_claim_of_perfect_confidence():
    calibration = CalibrationSet("tenant", "assertion", [])
    assert should_abstain(1.0, calibration)
    assert conformal_prediction_set([("unsupported", 1.0)], calibration) == []
    assert conformal_should_abstain([("unsupported", 1.0)], calibration)


@pytest.mark.parametrize("threshold", [math.ulp(0.0), 1e-20, 0.2, 0.5, 1.0])
def test_prediction_set_uses_the_same_exact_boundary_as_abstention(threshold):
    calibration = CalibrationSet("tenant", "assertion", [threshold])
    below = math.nextafter(threshold, 0.0)
    assert should_abstain(below, calibration)
    assert not should_abstain(threshold, calibration)
    assert conformal_prediction_set([("below", below), ("at", threshold)], calibration) == ["at"]
    assert conformal_should_abstain([("below", below)], calibration)


def test_zero_confidence_is_not_supported_by_a_tiny_positive_threshold():
    calibration = CalibrationSet("tenant", "assertion", [1e-20])
    assert should_abstain(0.0, calibration)
    assert conformal_prediction_set([("zero", 0.0)], calibration) == []
    assert conformal_should_abstain([("zero", 0.0)], calibration)


@pytest.mark.parametrize("threshold", [math.ulp(0.0), 1e-20, 0.2, 0.5, 1.0])
def test_per_example_set_size_preserves_the_exact_confidence_boundary(threshold):
    hits = [SimpleNamespace(score=1.0, metadata={"confidence": confidence}) for confidence in (
        0.0, math.nextafter(threshold, 0.0), threshold,
    )]
    assert conformal_prediction_set_size_for_hits(hits, threshold=threshold) == 1


@pytest.mark.parametrize("score,expected", [
    (-2.0, ["above", "one", "middle", "zero", "below"]),
    (0.5, ["above", "one", "middle"]),
    (2.0, ["above", "one"]),
])
def test_finite_prediction_set_clipping_and_stable_order_are_preserved(score, expected):
    calibration = CalibrationSet("tenant", "assertion", [score])
    labels = [("above", 2.0), ("one", 1.0), ("middle", 0.5), ("zero", 0.0), ("below", -2.0)]
    assert conformal_prediction_set(labels, calibration) == expected
    hits = [SimpleNamespace(score=1.0, metadata={"confidence": confidence}) for _, confidence in labels]
    assert conformal_prediction_set_size_for_hits(hits, threshold=score) == len(expected)


@pytest.mark.parametrize("invalid", [math.nan, math.inf, -math.inf, True, None, "bad"])
def test_invalid_confidence_cannot_enter_prediction_set(invalid):
    calibration = CalibrationSet("tenant", "assertion", [0.2, 0.8])
    assert should_abstain(invalid, calibration)
    assert conformal_prediction_set([("invalid", invalid), ("valid", 0.9)], calibration) == ["valid"]


@pytest.mark.parametrize("scores,coverage", [
    ([math.nan], .9), ([math.inf, .5], .9), (["bad"], .9),
    ([True], .9), ([.5], math.nan), ([.5], math.inf), ([.5], -0.1), ([.5], 1.1),
])
def test_corrupt_calibration_fails_closed(scores, coverage):
    calibration = CalibrationSet("tenant", "assertion", scores, target_coverage=coverage)
    assert should_abstain(1.0, calibration)
    assert conformal_prediction_set([("unverified", 1.0)], calibration) == []


@pytest.mark.parametrize("invalid", [math.nan, math.inf, -math.inf, True])
def test_nonfinite_training_examples_are_rejected_not_clipped(invalid):
    with pytest.raises(ValueError, match="finite"):
        CalibrationExample.from_mapping({"confidence": invalid, "correct": True})


def test_negative_prediction_set_is_not_evidence():
    calibration = CalibrationSet("tenant", "assertion", [.5])
    assert should_abstain(.9, calibration, prediction_set_size=-1)


@pytest.mark.parametrize("scores", [True, .5, 1, {0.9: "corrupt"}, "0.9", None])
def test_corrupt_calibration_container_fails_closed_without_raising(scores):
    calibration = CalibrationSet("tenant", "assertion", scores)
    assert should_abstain(1.0, calibration)
    assert conformal_prediction_set([("unsupported", 1.0)], calibration) == []


@pytest.mark.parametrize("maximum", [None, "3", True, math.nan, math.inf, -1, 0])
def test_invalid_maximum_prediction_set_size_fails_closed(maximum):
    calibration = CalibrationSet("tenant", "assertion", [.5])
    assert conformal_should_abstain([("candidate", .9)], calibration, max_set_size=maximum)
