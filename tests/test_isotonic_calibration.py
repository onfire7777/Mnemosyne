"""Mathematical invariants for the optional isotonic calibrator."""
import json
import math
from dataclasses import FrozenInstanceError
from decimal import Decimal
from fractions import Fraction

import pytest

from mnemosyne.calibration import IsotonicCalibrator


def test_identical_scores_are_one_empirical_bin_not_ordered_by_outcome():
    model = IsotonicCalibrator.fit([.1, .5, .5, .9], [False, True, False, True])
    assert model.predict(.5) == pytest.approx(.5)
    assert len(model.knots_x) == len(set(model.knots_x))


def test_pooled_block_is_constant_at_all_training_scores():
    model = IsotonicCalibrator.fit([.1, .3, .7, .9], [False, True, False, True])
    assert model.predict(.3) == pytest.approx(.5)
    assert model.predict(.7) == pytest.approx(.5)


def test_pooled_tied_scores_keep_their_observation_weight():
    model = IsotonicCalibrator.fit(
        [0.1, 0.3, 0.3, 0.3, 0.7, 0.9],
        [False, True, True, True, False, True],
    )
    assert model.predict(0.3) == 0.75
    assert model.predict(0.7) == 0.75
    assert model.predict(0.1) == 0.0
    assert model.predict(0.9) == 1.0


@pytest.mark.parametrize("scores,outcomes", [
    ([], []), ([.5], []), ([float("nan")], [True]),
    ([float("inf")], [False]), ([.5], ["false"]), ([True], [False]),
])
def test_invalid_fit_input_does_not_become_an_identity_or_perfect_model(scores, outcomes):
    with pytest.raises(ValueError):
        IsotonicCalibrator.fit(scores, outcomes)


@pytest.mark.parametrize("payload", [
    {}, {"knots_x": [], "knots_y": []},
    {"knots_x": [0, .5], "knots_y": [0]},
    {"knots_x": [.5, .5], "knots_y": [0, 1]},
    {"knots_x": [.5, .2], "knots_y": [0, 1]},
    {"knots_x": [.2, .5], "knots_y": [1, 0]},
    {"knots_x": [.2], "knots_y": [float("nan")]},
    {"knots_x": [.2], "knots_y": [2]},
])
def test_corrupt_serialized_model_is_rejected(payload):
    with pytest.raises(ValueError):
        IsotonicCalibrator.from_dict(payload)


@pytest.mark.parametrize("number_type", ["fraction", "numpy_float32"])
def test_real_number_knots_round_trip_through_json(number_type):
    number = Fraction if number_type == "fraction" else pytest.importorskip("numpy").float32
    model = IsotonicCalibrator.from_dict({
        "knots_x": [number("0.1"), number("0.5"), number("0.9")],
        "knots_y": [number("0.0"), number("0.5"), number("1.0")],
    })
    encoded = json.dumps(model.to_dict(), allow_nan=False)
    restored = IsotonicCalibrator.from_dict(json.loads(encoded))
    assert all(type(value) is float for knots in model.to_dict().values() for value in knots)
    assert restored.to_dict() == model.to_dict()
    for score in [0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0]:
        assert restored.predict(score) == model.predict(score)


@pytest.mark.parametrize("field", ["knots_x", "knots_y"])
@pytest.mark.parametrize("invalid", [
    True, "0.5", None, float("nan"), float("inf"), -float("inf"),
    Fraction(-1, 10 ** 400), Fraction(10 ** 400 + 1, 10 ** 400),
])
def test_raw_knots_are_validated_before_float_normalization(field, invalid):
    payload = {"knots_x": [0.5], "knots_y": [0.5]}
    payload[field] = [invalid]
    with pytest.raises(ValueError, match="finite probabilities"):
        IsotonicCalibrator.from_dict(payload)


def test_distinct_score_knots_that_collapse_to_one_float_are_rejected():
    left = Fraction(1, 2)
    right = left + Fraction(1, 2 ** 55)
    assert left < right
    assert float(left) == float(right)
    with pytest.raises(ValueError, match="strictly increasing"):
        IsotonicCalibrator.from_dict({"knots_x": [left, right], "knots_y": [0, 1]})


def test_decreasing_fraction_probabilities_are_not_hidden_by_float_rounding():
    lower = Fraction(1, 2)
    higher = lower + Fraction(1, 2 ** 55)
    assert float(lower) == float(higher)
    with pytest.raises(ValueError, match="nondecreasing"):
        IsotonicCalibrator.from_dict({"knots_x": [0, 1], "knots_y": [higher, lower]})


def test_caller_owned_knot_lists_cannot_corrupt_predictions():
    xs, ys = [0.0, 0.5, 1.0], [0.0, 0.5, 1.0]
    model = IsotonicCalibrator(knots_x=xs, knots_y=ys)  # type: ignore[arg-type]
    xs[:] = [float("nan")]
    ys[:] = [float("nan")]
    assert model.predict(0.25) == 0.25
    assert model.knots_x == (0.0, 0.5, 1.0)
    assert model.knots_y == (0.0, 0.5, 1.0)


@pytest.mark.parametrize("field", ["knots_x", "knots_y"])
def test_validated_knot_attributes_cannot_be_replaced(field):
    model = IsotonicCalibrator(knots_x=(0.0, 1.0), knots_y=(0.0, 1.0))
    with pytest.raises(FrozenInstanceError):
        setattr(model, field, (float("nan"), float("nan")))
    assert model.predict(0.25) == 0.25


def test_fit_is_permutation_invariant_monotone_and_round_trips():
    from itertools import permutations
    pairs = [(0.1, True), (0.3, False), (0.3, True), (0.9, True)]
    model = IsotonicCalibrator.fit(*map(list, zip(*pairs)))
    for permuted in permutations(pairs):
        assert IsotonicCalibrator.fit(*map(list, zip(*permuted))).to_dict() == model.to_dict()
    restored = IsotonicCalibrator.from_dict(model.to_dict())
    predictions = [restored.predict(i / 100) for i in range(101)]
    assert predictions == sorted(predictions)
    assert all(0 <= p <= 1 for p in predictions)


def test_distinct_nearby_knots_preserve_exact_pooled_training_values():
    model = IsotonicCalibrator.fit(
        [.1, .3, .3000000000001, .7, .9],
        [False, False, True, False, True],
    )
    assert model.predict(.3) == 0.0
    assert model.predict(.3000000000001) == pytest.approx(.5)
    assert model.predict(.7) == pytest.approx(.5)


def test_exact_interior_knot_preserves_stored_probability():
    model = IsotonicCalibrator(knots_x=(0.0, 0.5, 1.0), knots_y=(3 / 7, 18 / 19, 1.0))
    assert model.predict(0.5) == model.knots_y[1]


def test_predictions_remain_monotone_at_immediate_knot_neighbors():
    model = IsotonicCalibrator(knots_x=(0.0, 0.5, 1.0), knots_y=(3 / 7, 18 / 19, 1.0))
    predictions = [model.predict(score) for score in (
        math.nextafter(0.5, 0.0), 0.5, math.nextafter(0.5, 1.0),
    )]
    assert predictions == sorted(predictions)


@pytest.mark.parametrize("score", [
    float("nan"), float("inf"), -float("inf"), True, None, "bad",
    Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("-Infinity"),
    complex(float("nan"), 0.0), complex(float("inf"), 0.0),
])
def test_invalid_prediction_input_cannot_be_mapped_to_a_high_confidence_knot(score):
    model = IsotonicCalibrator.fit([.1, .9], [True, True])
    with pytest.raises(ValueError, match="finite"):
        model.predict(score)


@pytest.mark.parametrize("number_type", ["float32", "float64", "longdouble"])
@pytest.mark.parametrize("nonfinite", ["nan", "inf", "-inf"])
def test_nonfinite_numpy_predictions_raise_value_error(number_type, nonfinite):
    number = getattr(pytest.importorskip("numpy"), number_type)
    model = IsotonicCalibrator.fit([0.1, 0.9], [True, True])
    with pytest.raises(ValueError, match="finite"):
        model.predict(number(nonfinite))
