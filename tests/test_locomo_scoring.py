"""Run explicitly in the isolated pinned LoCoMo scorer environment."""
from importlib.metadata import PackageNotFoundError, version

import pytest

from eval.public.adapters.locomo import LoCoMoError
from eval.public.adapters.locomo_scoring import DEPENDENCIES, score_case

try:
    available = all(version(name) == expected for name, expected in DEPENDENCIES.items())
except PackageNotFoundError:
    available = False
pytestmark = pytest.mark.skipif(not available, reason="requires isolated pinned LoCoMo scorer environment")


def annotation(category=4, answer="cats running", evidence=None):
    return {"category": category, "answer": answer, "evidence": ["D1:1"] if evidence is None else evidence}


@pytest.mark.parametrize("category,answer,prediction,expected", [
    (4, "cats running", "the cat runs", 1), (4, "red blue", "red green", .5),
    (1, "red,blue", "red", .5), (3, "red; blue", "red", 1),
    (5, "distractor", "Not mentioned in the conversation", 1),
    (5, "distractor", "unknown", 0), (4, "", "", 0),
    (2, 2024, "2024", 1),
])
def test_category_scoring(category, answer, prediction, expected):
    result = score_case(annotation(category, answer), prediction)
    assert result["score"] == expected
    assert result["reported_score"] == round(expected, 3)
    assert result["upstream_recall"] == 1
    assert result["measured_recall"] is None
    assert not result["recall_applicable"]


@pytest.mark.parametrize("context,expected", [(["D1:1"], 1), (["D2:1"], 0), (["S1"], 1), (["S2"], 0)])
def test_recall_requires_observed_context(context, expected):
    result = score_case(annotation(), "cat", retrieved_context=context)
    assert result["measured_recall"] == expected
    assert result["recall_applicable"]


def test_empty_evidence_stays_unmeasured_even_when_upstream_returns_one():
    result = score_case(annotation(evidence=[]), "cat", retrieved_context=[])
    assert result["upstream_recall"] == 1
    assert result["measured_recall"] is None


def test_empty_context_with_evidence_is_rejected():
    with pytest.raises(LoCoMoError, match="undefined"):
        score_case(annotation(), "cat", retrieved_context=[])


@pytest.mark.parametrize("category", [True, "1", 0, 6])
def test_invalid_category_is_rejected(category):
    with pytest.raises(LoCoMoError):
        score_case(annotation(category), "cat")


def replay_source():
    return [{"sample_id": "synthetic", "conversation": {"session_1": []},
             "qa": [dict(annotation(category, "red blue"), question="Synthetic?")
                    for category in range(1, 6)]}]


def replay_predictions(source):
    from eval.public.adapters.locomo import split_samples
    return [{"question_id": row["question_id"], "decoded_prediction": "red",
             "retrieved_context": ["D1:1"]} for row in split_samples(source)["questions"]]


def test_replay_preserves_all_categories_and_missing_predictions():
    from eval.public.adapters.locomo_scoring import score_prediction_set
    source = replay_source()
    predictions = replay_predictions(source)
    result = score_prediction_set(source, predictions[:-1])
    assert not result["complete"]
    assert len(result["cases"]) == 5
    assert result["cases"][-1]["status"] == "missing-prediction"
    assert result["cases"][-1]["score"] is None
    assert result["categories"]["5"]["source_count"] == 1
    assert result["categories"]["5"]["missing_count"] == 1
    assert result["categories"]["5"]["upstream_denominator_mean"] == 0
    assert result["categories"]["4"]["upstream_denominator_mean"] == .667
    assert "overall" not in result
    assert not result["publication_authorized"]


def test_replay_order_does_not_change_results_and_rounds_before_sum():
    from eval.public.adapters.locomo_scoring import score_prediction_set
    source = replay_source()
    outputs = replay_predictions(source)
    result = score_prediction_set(source, outputs)
    assert result == score_prediction_set(source, outputs[::-1])
    assert result["complete"]
    assert result["categories"]["4"]["rounded_score_sum"] == .667


def test_fallback_recall_is_counted_separately_from_observed_retrieval():
    from eval.public.adapters.locomo_scoring import score_prediction_set
    source = replay_source()
    outputs = replay_predictions(source)
    del outputs[0]["retrieved_context"]
    result = score_prediction_set(source, outputs)
    assert result["categories"]["1"]["fallback_recall_count"] == 1
    assert result["categories"]["1"]["observed_recall_count"] == 0
    assert result["cases"][0]["measured_recall"] is None
    assert result["categories"]["2"]["observed_recall_count"] == 1


@pytest.mark.parametrize("mutation", ["duplicate", "unknown", "extra-field", "null-context"])
def test_replay_rejects_ambiguous_prediction_population(mutation):
    from eval.public.adapters.locomo_scoring import score_prediction_set
    source = replay_source()
    outputs = replay_predictions(source)
    if mutation == "duplicate":
        outputs.append(outputs[0].copy())
    elif mutation == "unknown":
        outputs[0]["question_id"] = "unknown"
    elif mutation == "null-context":
        outputs[0]["retrieved_context"] = None
    else:
        outputs[0]["fabricated_score"] = 1
    with pytest.raises(LoCoMoError):
        score_prediction_set(source, outputs)
