import copy
import json
import sys
from datetime import UTC, datetime

import pytest

from eval import longmemeval_recall as runner


def _question(qid="question-1"):
    return {
        "question_id": qid,
        "question_type": "temporal-reasoning",
        "question": "What did I say about Vienna yesterday?",
        "question_date": "2024/08/13 (Tue) 12:00",
        "answer_session_ids": ["session-1"],
        "haystack_session_ids": ["session-1"],
        "haystack_dates": ["2024/08/12 (Mon) 12:00"],
        "haystack_sessions": [[{
            "role": "user", "content": "I said my destination city was Vienna.", "has_answer": True,
        }]],
    }


def _run(tmp_path, monkeypatch, questions, *arguments):
    for name in ("longmemeval_s_cleaned.json", "longmemeval_oracle.json"):
        (tmp_path / name).write_text(json.dumps(questions), encoding="utf-8")
    out = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", [
        "longmemeval_recall", "--data", str(tmp_path), "--out", str(out), *arguments,
    ])
    runner.main()
    return json.loads(out.read_text(encoding="utf-8"))


def test_temporal_recall_preserves_session_and_question_dates(tmp_path, monkeypatch):
    report = _run(tmp_path, monkeypatch, [_question()], "--split", "dev", "--modes", "passages")

    assert report["rows"][0]["passages"] == 1.0
    assert report["rows"][0]["question_date"] == "2024-08-13T12:00:00+00:00"
    assert report["timestamp_timezone"] == "UTC"


@pytest.mark.parametrize("timestamp,expected", [
    ("2024/08/13 (Tue) 12:00", "2024-08-13T12:00:00+00:00"),
    ("2024/08/13 (Tue) 12:00:30", "2024-08-13T12:00:30+00:00"),
    ("2024-08-13T12:00:00", "2024-08-13T12:00:00+00:00"),
    ("2024-08-13T12:00:00+09:00", "2024-08-13T03:00:00+00:00"),
])
def test_benchmark_timestamp_is_explicitly_utc(timestamp, expected):
    assert runner.benchmark_timestamp(timestamp, "test").isoformat() == expected


@pytest.mark.parametrize("timestamp", [None, "", "not-a-date", "2024/02/30 (Fri) 12:00"])
def test_invalid_timestamp_has_field_context(timestamp):
    with pytest.raises(ValueError, match="question_date"):
        runner.benchmark_timestamp(timestamp, "question_date")


def test_duplicate_filler_sessions_keep_dates_by_occurrence(tmp_path, monkeypatch):
    question = _question()
    question["haystack_session_ids"] += ["filler", "filler"]
    question["haystack_dates"] += ["2024/08/10 (Sat) 12:00", "2024/08/11 (Sun) 12:00"]
    question["haystack_sessions"] += [
        [{"role": "user", "content": "I mentioned Paris."}],
        [{"role": "user", "content": "I mentioned Rome."}],
    ]
    seen = []
    engine_class = runner.LocalMemoryEngine

    class RecordingEngine(engine_class):
        def append_evidence(self, evidence, *args, **kwargs):
            seen.append((evidence.source_identity, evidence.created_at))
            return super().append_evidence(evidence, *args, **kwargs)

    monkeypatch.setattr(runner, "LocalMemoryEngine", RecordingEngine)
    _run(tmp_path, monkeypatch, [question], "--modes", "passages")

    assert seen == [
        ("session-1", datetime(2024, 8, 12, 12, tzinfo=UTC)),
        ("filler#occurrence-0", datetime(2024, 8, 10, 12, tzinfo=UTC)),
        ("filler#occurrence-1", datetime(2024, 8, 11, 12, tzinfo=UTC)),
    ]


def test_unanswerable_questions_are_excluded_before_gold_validation(tmp_path, monkeypatch):
    unanswerable = {"question_id": "question-2_abs", "answer_session_ids": []}
    report = _run(tmp_path, monkeypatch, [_question(), unanswerable], "--modes", "passages")

    assert report["excluded_question_ids"] == ["question-2_abs"]
    assert report["eligible_questions"] == 1
    assert [row["question_id"] for row in report["rows"]] == ["question-1"]
    assert report["summary"]["dev"]["questions"] == 1


def test_limit_preserves_split_from_complete_question_set(tmp_path, monkeypatch):
    questions = [_question(f"question-{number}") for number in range(125)]
    original_split = runner.split_of([q["question_id"] for q in questions])
    heldout = [q["question_id"] for q in questions if original_split[q["question_id"]] == "heldout"]
    report = _run(
        tmp_path, monkeypatch, questions, "--split", "heldout", "--limit", "2", "--modes", "passages",
    )

    assert [row["question_id"] for row in report["rows"]] == heldout[:2]
    assert all(row["split"] == "heldout" for row in report["rows"])
    assert report["eligible_questions"] == 25
    assert report["evaluated_questions"] == 2
    assert report["limit"] == 2


def test_empty_eligible_selection_reports_no_scores(tmp_path, monkeypatch):
    report = _run(tmp_path, monkeypatch, [{"question_id": "only_abs"}])
    assert report["excluded_question_ids"] == ["only_abs"]
    assert report["rows"] == []
    assert report["summary"] == {}
    assert report["evaluated_questions"] == 0


@pytest.mark.parametrize("field,value", [
    ("question_date", "invalid"),
    ("haystack_dates", []),
    ("haystack_dates", ["invalid"]),
])
def test_invalid_selected_dates_fail_before_creating_engines(tmp_path, monkeypatch, field, value):
    question = copy.deepcopy(_question())
    question[field] = value
    monkeypatch.setattr(runner, "LocalMemoryEngine", lambda **kwargs: pytest.fail("created engine before validation"))
    with pytest.raises(ValueError, match=field):
        _run(tmp_path, monkeypatch, [question])
