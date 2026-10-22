import copy
import json

import pytest

from eval import controlled_comparison as runner
from eval.comparison_protocol import pack_context


def sample():
    return {"question_id": "fixture", "question": "When does Zephyr launch?",
            "question_date": "2026-10-22T12:00:00Z", "sessions": [
                {"session_id": "s1", "date": "2026-10-20T12:00:00Z", "turns": [
                    {"role": "user", "content": "Project Zephyr launches Friday."},
                    {"role": "assistant", "content": "I will remember the launch date."},
                ]},
                {"session_id": "s2", "date": "2026-10-21T12:00:00Z", "turns": [
                    {"role": "user", "content": "The weather is sunny."},
                ]},
            ]}


def test_native_mnemosyne_context_retains_sources_and_dates_without_mutation():
    row = sample()
    before = copy.deepcopy(row)
    result = runner.mnemosyne_context(row)
    assert row == before
    assert result["status"] == "completed" and result["retained_rounds"] == 2
    assert "Project Zephyr launches Friday." in pack_context(result["candidate_texts"])["text"]
    assert result["candidate_metadata"][0]["session_id"] == "s1"
    assert result["stage_seconds"]["retain"] >= 0


def test_reader_never_receives_gold_and_judge_never_receives_arm(monkeypatch):
    calls = []

    def fake(prompt, **kwargs):
        calls.append(prompt)
        return {"answer": "Friday" if len(calls) == 1 else "yes", "elapsed_seconds": 1,
                "requested_model": runner.MODEL, "requested_reasoning_effort": runner.REASONING_EFFORT,
                "usage": {"input_tokens": 10}}

    monkeypatch.setattr(runner, "read_with_codex", fake)
    row = sample() | {"answer": "GOLD_ONLY_MARKER", "question_type": "single-session-user"}
    context = {"question_id": "fixture", "arm": "mnemosyne", "status": "completed", "candidate_texts": ["Launch Friday."],
               "stage_seconds": {"retain": 2, "recall": 3}}
    reader = {"question": row["question"], "question_date": row["question_date"]}
    result = runner.answer_one(reader, row, context, {"manifest_sha256": "a" * 64})
    assert "GOLD_ONLY_MARKER" not in calls[0] and "GOLD_ONLY_MARKER" in calls[1]
    assert "mnemosyne" not in calls[1] and "hindsight" not in calls[1]
    assert result["status"] == "completed" and result["judge_label"] is True
    assert result["usage"]["input_tokens"] == 20


def test_failed_native_context_never_calls_reader(monkeypatch):
    monkeypatch.setattr(runner, "read_with_codex", lambda *a, **kw: pytest.fail("reader called"))
    result = runner.answer_one(sample(), {}, {"question_id": "fixture", "arm": "hindsight", "status": "failed"},
                               {"manifest_sha256": "a" * 64})
    assert result["status"] == "failed" and "judge_label" not in result


def test_receipts_cannot_be_overwritten(tmp_path):
    path = tmp_path / "receipt.json"
    runner.write_new(path, {"attempt": 1})
    with pytest.raises(FileExistsError):
        runner.write_new(path, {"attempt": 2})
    assert json.loads(path.read_text())["attempt"] == 1


def test_interrupted_answer_is_failed_without_retry_and_missing_context_is_pending(monkeypatch, tmp_path):
    manifest = {"manifest_sha256": "a" * 64}
    row = sample()
    monkeypatch.setattr(runner, "check_frozen", lambda *a: (manifest, [row]))
    monkeypatch.setattr(runner, "check_local_runtime", lambda *a: None)
    monkeypatch.setattr(runner, "dataset", lambda *a: [row])
    monkeypatch.setattr(runner, "read_with_codex", lambda *a, **kw: pytest.fail("retried interrupted attempt"))
    run, contexts = tmp_path / "run", tmp_path / "contexts"
    runner.write_new(contexts / "mnemosyne/fixture.json", {
        "question_id": "fixture", "arm": "mnemosyne", "status": "completed", **manifest,
    })
    runner.write_new(run / "answers/attempts/fixture-mnemosyne.json", manifest)
    runner.run_answers(tmp_path, run, tmp_path, contexts)
    result = runner.read_json(run / "answers/fixture-mnemosyne.json")
    assert result["status"] == "failed" and result["error_kind"] == "interrupted"
    assert not (run / "answers/fixture-hindsight.json").exists()


def test_native_error_retained_as_failure_without_aborting_other_cases(monkeypatch, tmp_path):
    manifest = {"manifest_sha256": "a" * 64}
    rows = [sample(), sample() | {"question_id": "second"}]
    monkeypatch.setattr(runner, "check_frozen", lambda *a: (manifest, rows))
    monkeypatch.setattr(runner, "check_local_runtime", lambda *a: None)

    def fail(row):
        raise RuntimeError("fixture failure")

    monkeypatch.setattr(runner, "mnemosyne_context", fail)
    runner.run_mnemosyne(tmp_path, tmp_path, tmp_path)
    for row in rows:
        result = runner.read_json(tmp_path / "mnemosyne" / (row["question_id"] + ".json"))
        assert result["status"] == "failed" and result["error_kind"] == "RuntimeError"
