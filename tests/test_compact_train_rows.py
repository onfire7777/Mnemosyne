from copy import deepcopy
import pytest
from eval.compact_answering.train_rows import stage_row, normalize


def test_squad_keeps_unicode_exact_and_upstream_null_separate():
    row = {
        "id": "a",
        "question": "where?",
        "title": "t",
        "context": "é café café",
        "answers": {"text": ["café"], "answer_start": [7]},
    }
    result = stage_row(row, "squad")
    found = result["spans"][0]
    assert (found["char_start"], found["char_end"]) == (7, 11)
    assert (
        row["context"].encode()[found["byte_start"] : found["byte_end"]].decode()
        == "café"
    )
    assert not result["training_admitted"] and result["overlap_verdict"] == "unchecked"
    row["answers"]["answer_start"] = [2]
    assert stage_row(row, "squad")["spans"][0]["char_start"] == 2
    row["answers"]["answer_start"] = [3]
    with pytest.raises(ValueError):
        stage_row(row, "squad")
    row["answers"] = {"text": [], "answer_start": []}
    assert stage_row(row, "squad")["target_kind"] == "null"
    assert normalize(" CAFE\u0301\n X ") == "café x"


def hotpot():
    return {
        "id": "b",
        "question": "where?",
        "answer": "café",
        "context": {
            "title": ["support", "distractor"],
            "sentences": [["é ", "café café"], ["café"]],
        },
        "supporting_facts": {"title": ["support"], "sent_id": [1]},
    }


def test_hotpot_only_exact_support_spans_and_no_invented_nulls():
    row = hotpot()
    result = stage_row(row, "hotpot")
    assert [s["char_start"] for s in result["spans"]] == [2, 7]
    assert all(s["document"] == 0 for s in result["spans"])
    assert result["documents"][0]["context"] == "é café café"
    for answer in ["yes", "no", "Café", "absent"]:
        row["answer"] = answer
        assert stage_row(row, "hotpot")["target_kind"] == "ranking-only"


def test_bad_support_or_duplicate_title_never_becomes_span_data():
    row = hotpot()
    for ids in [[-1], [2], [True], []]:
        bad = deepcopy(row)
        bad["supporting_facts"]["sent_id"] = ids
        with pytest.raises(ValueError):
            stage_row(bad, "hotpot")
    row["context"]["title"] = ["support", "support"]
    with pytest.raises(ValueError):
        stage_row(row, "hotpot")
