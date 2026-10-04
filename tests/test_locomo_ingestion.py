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


def test_question_transformation_is_replayable_and_does_not_use_global_randomness(monkeypatch):
    from eval.public.adapters.locomo import prepare_upstream_question
    import random

    def forbidden():
        raise AssertionError("hidden randomness")
    monkeypatch.setattr(random, "random", forbidden)
    annotation = sample()["qa"][4]
    for draw in (0, 0.499999, 0.5, 0.999999):
        prepared = prepare_upstream_question(annotation, choice_draw=draw)
        assert prepared == prepare_upstream_question(annotation, choice_draw=draw)
        abstain = "a" if draw < 0.5 else "b"
        assert prepared["answer_key"][abstain] == "Not mentioned in the conversation"
        assert prepared["choice_draw"] == draw
        assert prepared["query"].endswith(f"(a) {prepared['answer_key']['a']} (b) {prepared['answer_key']['b']}. ")


@pytest.mark.parametrize("draw", [None, True, -0.1, 1, float("nan"), float("inf"), "0.2"])
def test_adversarial_choice_requires_valid_recorded_draw(draw):
    from eval.public.adapters.locomo import prepare_upstream_question
    with pytest.raises(LoCoMoError):
        prepare_upstream_question(sample()["qa"][4], choice_draw=draw)


def test_non_adversarial_transformation_does_not_expose_answer():
    from eval.public.adapters.locomo import prepare_upstream_question
    for annotation in sample()["qa"][:4]:
        result = prepare_upstream_question(annotation)
        assert "SCORER_SECRET" not in json.dumps(result)
        assert result["answer_key"] is None
        assert ("Use DATE" in result["query"]) == (annotation["category"] == 2)
        with pytest.raises(LoCoMoError):
            prepare_upstream_question(annotation, choice_draw=0.1)


@pytest.mark.parametrize("raw,expected", [(" A ", "first"), ("(A)", "first"), ("b", "second"),
                                         ("x", "second"), ("yes", "second"), ("(b)", "second"),
                                         ("", ""), (" No Information Available ", "no information available")])
def test_upstream_decoder_retains_raw_and_short_output_semantics(raw, expected):
    from eval.public.adapters.locomo import decode_upstream_category5
    result = decode_upstream_category5(raw, {"a": "first", "b": "second"})
    assert result["raw_prediction"] == raw
    assert result["decoded_prediction"] == expected
