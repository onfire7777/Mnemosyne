"""Synthetic ingestion tests; no held-out LoCoMo examples or scores."""
from copy import deepcopy
import json

import pytest

from eval.public.adapters.locomo import LoCoMoError, split_samples


def sample(sample_id="synthetic"):
    return {"sample_id": sample_id,
            "conversation": {"speaker_a": "A", "speaker_b": "B", "session_1_date_time": "test date",
                             "session_1": [{"speaker": "A", "dia_id": "D1:1", "text": "Input conversation."}]},
            "observation": "GENERATED_NOT_INPUT", "session_summary": "SUMMARY_NOT_INPUT",
            "qa": [{"question": "Synthetic question?", "category": c, "answer": "SCORER_SECRET",
                    "evidence": ["(D1:1)"] if c != 5 else [], "extra_annotation": "KEEP_LABEL"}
                   for c in range(1, 6)]}


def test_separates_inputs_without_rewriting_or_dropping_source_annotations():
    source = [sample()]
    before = deepcopy(source)
    result = split_samples(source)
    inputs = json.dumps([result["conversations"], result["questions"]])
    assert all(token not in inputs for token in ["SCORER_SECRET", "GENERATED_NOT_INPUT", "SUMMARY_NOT_INPUT", "KEEP_LABEL"])
    assert result["conversations"][0]["conversation"] == source[0]["conversation"]
    assert [row["annotation"] for row in result["annotations"]] == source[0]["qa"]
    assert source == before
    assert result == split_samples(source)
    assert len({q["question_id"] for q in result["questions"]}) == 5
    assert [q["question_id"] for q in result["questions"]] == [a["question_id"] for a in result["annotations"]]
    result["annotations"][0]["annotation"]["answer"] = "changed"
    result["conversations"][0]["conversation"]["speaker_a"] = "changed"
    assert source == before


def test_sample_identity_is_collision_safe_and_order_independent():
    a, b = sample("a:0"), sample("a")
    result, reversed_result = split_samples([a, b]), split_samples([b, a])
    def key(q):
        return q["question_id"]
    assert sorted(result["questions"], key=key) == sorted(reversed_result["questions"], key=key)
    assert len({q["question_id"] for q in result["questions"]}) == 10


@pytest.mark.parametrize("category", [True, 0, 6, 1.0, "1", None])
def test_rejects_invalid_category(category):
    source = sample()
    source["qa"][0]["category"] = category
    with pytest.raises(LoCoMoError, match="category"):
        split_samples([source])


@pytest.mark.parametrize("source", [None, [], {}, [None], [sample(), sample()]])
def test_rejects_ambiguous_or_missing_samples(source):
    with pytest.raises(LoCoMoError):
        split_samples(source)


@pytest.mark.parametrize("field,value", [("question", ""), ("evidence", None), ("evidence", [1]), ("answer", float("nan"))])
def test_rejects_malformed_annotations(field, value):
    source = sample()
    source["qa"][0][field] = value
    with pytest.raises(LoCoMoError):
        split_samples([source])
