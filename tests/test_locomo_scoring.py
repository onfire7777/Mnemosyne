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
