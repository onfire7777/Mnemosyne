from concurrent.futures import as_completed as real_as_completed
from threading import Event, Lock

import pytest

from eval import controlled_comparison as runner


def prepare(monkeypatch, tmp_path):
    manifest = {"manifest_sha256": "a" * 64}
    rows = [{"question_id": f"case{i}", "question": "What color?", "question_date": "2026-10-22",
             "question_type": "single-session-user", "answer": "blue"} for i in range(2)]
    monkeypatch.setattr(runner, "check_frozen", lambda *args: (manifest, rows))
    monkeypatch.setattr(runner, "check_local_runtime", lambda *args: None)
    monkeypatch.setattr(runner, "dataset", lambda *args: rows)
    run, contexts = tmp_path / "run", tmp_path / "contexts"
    for row in rows:
        for arm in runner.ARMS:
            runner.write_new(contexts / arm / (row["question_id"] + ".json"), {
                "question_id": row["question_id"], "arm": arm, "status": "completed",
                "candidate_texts": ["The color is blue."], "stage_seconds": {"retain": .1, "recall": .1},
                **manifest,
            })
    return run, contexts


def response(prompt):
    return {"answer": "blue" if "Retrieved memories:" in prompt else "yes", "elapsed_seconds": .1,
            "usage": {"input_tokens": 10}, "requested_model": runner.MODEL,
            "requested_reasoning_effort": runner.REASONING_EFFORT}


def test_interrupt_drains_admitted_readers_cancels_queue_and_resumes_only_pending(monkeypatch, tmp_path):
    run, contexts = prepare(monkeypatch, tmp_path)
    started = Event()
    mutex = Lock()
    calls = []
    cancellations = []
    original_job = runner._run_answer_job

    def capture_event(*args):
        with mutex:
            cancellations.append(args[-1])
        return original_job(*args)

    def provider(prompt, **kwargs):
        with mutex:
            calls.append(prompt)
            if len(calls) == 2:
                started.set()
        assert cancellations[0].wait(5), "the runner must signal cancellation before draining"
        return response(prompt)

    def interrupt(futures):
        assert started.wait(5), "both worker slots should be reading"
        raise KeyboardInterrupt()

    monkeypatch.setattr(runner, "_run_answer_job", capture_event)
    monkeypatch.setattr(runner, "read_with_codex", provider)
    monkeypatch.setattr(runner, "as_completed", interrupt)
    with pytest.raises(KeyboardInterrupt):
        runner.run_answers(tmp_path, run, tmp_path, contexts)

    assert len(calls) == 2  # No queued reader and no judge starts after cancellation.
    saved = list((run / "answers").glob("*.json"))
    assert len(saved) == 2
    preserved = {path.name: path.read_bytes() for path in saved}
    for path in saved:
        record = runner.read_json(path)
        assert record["status"] == "failed" and record["error_kind"] == "cancelled"
        assert record["receipts"]["reader"]["answer"] == "blue"
        assert record["usage"]["input_tokens"] == 10
        assert "judge" not in record["receipts"]
    assert len(list((run / "answers/attempts").glob("*.json"))) == 2

    resumed = []
    def finish(prompt, **kwargs):
        resumed.append(prompt)
        return response(prompt)
    monkeypatch.setattr(runner, "read_with_codex", finish)
    monkeypatch.setattr(runner, "as_completed", real_as_completed)
    runner.run_answers(tmp_path, run, tmp_path, contexts)
    assert len(resumed) == 4  # Only the two previously queued jobs run.
    assert len(list((run / "answers").glob("*.json"))) == 4
    for name, content in preserved.items():
        assert (run / "answers" / name).read_bytes() == content


def test_worker_publishes_before_observer_collects_results(monkeypatch, tmp_path):
    run, contexts = prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(runner, "read_with_codex", lambda prompt, **kwargs: response(prompt))

    def delayed_observer(futures):
        for future in futures:
            future.result(timeout=5)
        assert len(list((run / "answers").glob("*.json"))) == 4
        raise KeyboardInterrupt()

    monkeypatch.setattr(runner, "as_completed", delayed_observer)
    with pytest.raises(KeyboardInterrupt):
        runner.run_answers(tmp_path, run, tmp_path, contexts)
    for path in (run / "answers").glob("*.json"):
        record = runner.read_json(path)
        assert record["status"] == "completed" and record["judge_label"] is True
        assert set(record["receipts"]) == {"reader", "judge"}


@pytest.mark.parametrize("stage", ["reader", "judge"])
def test_cancellation_during_prompt_preparation_does_not_admit_provider(monkeypatch, stage):
    cancelled = Event()
    calls = []
    context = {"question_id": "case", "arm": "mnemosyne", "status": "completed",
               "candidate_texts": ["The color is blue."]}

    def cancel_after(callback):
        def prepare(*args, **kwargs):
            value = callback(*args, **kwargs)
            cancelled.set()
            return value
        return prepare

    def provider(prompt, **kwargs):
        calls.append(prompt)
        return response(prompt)

    preparation = "pack_context" if stage == "reader" else "judge_prompt"
    monkeypatch.setattr(runner, preparation, cancel_after(getattr(runner, preparation)))
    monkeypatch.setattr(runner, "read_with_codex", provider)
    record = runner.answer_one(
        {"question": "What color?", "question_date": "2026-10-22"},
        {"question_id": "case", "question": "What color?", "question_type": "single-session-user", "answer": "blue"},
        context, {"manifest_sha256": "a" * 64}, cancel_event=cancelled,
    )
    assert len(calls) == (0 if stage == "reader" else 1)
    assert record["status"] == "failed" and record["error_kind"] == "cancelled"
    assert set(record["receipts"]) == (set() if stage == "reader" else {"reader"})
