import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def runner(monkeypatch, tmp_path):
    path = Path(__file__).resolve().parents[1] / "eval/longmemeval_s/run_bench_LongMemEval.py"
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location("longmemeval_dry_run_test_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "HERE", tmp_path / "results")

    def unexpected_call(*args, **kwargs):
        pytest.fail("a dry run must not call a model or open an embedding cache")

    monkeypatch.setattr(module, "open_cache", unexpected_call)
    monkeypatch.setattr(module, "openrouter", unexpected_call)
    monkeypatch.setattr(module, "read_with_codex", unexpected_call)
    monkeypatch.setattr(module.urllib.request, "urlopen", unexpected_call)
    return module


def dataset(tmp_path):
    row = {
        "question_id": "synthetic-q1",
        "question_type": "single-session-user",
        "question": "Which city is my destination?",
        "question_date": "2026/10/22 (Thu) 12:00",
        "answer": "Vienna",
        "answer_session_ids": ["session-1"],
        "haystack_session_ids": ["session-1"],
        "haystack_dates": ["2026/10/21 (Wed) 12:00"],
        "haystack_sessions": [[{
            "role": "user", "content": "My destination city is Vienna.", "has_answer": True,
        }]],
    }
    path = tmp_path / "longmemeval_s_cleaned.json"
    path.write_text(json.dumps([row]), encoding="utf-8")
    (tmp_path / "longmemeval_oracle.json").write_text(json.dumps([row]), encoding="utf-8")
    return path


@pytest.mark.parametrize("provider", ["cloud", "local"])
@pytest.mark.parametrize("has_key", [False, True])
def test_dense_dry_run_rejects_before_opening_or_populating_cache(
    runner, monkeypatch, tmp_path, provider, has_key,
):
    path = dataset(tmp_path)
    cache_file = tmp_path / "embedding-cache"
    calls = []

    def ensure(texts, **kwargs):
        calls.append("embedding-call")
        cache_file.write_text("fake generated embeddings", encoding="utf-8")
        pytest.fail("dense dry run generated missing embeddings")

    def open_cache(*args):
        calls.append("cache-open")
        return SimpleNamespace(
            model="fake", estimate_usd=lambda texts: (len(texts), 0.01), ensure=ensure,
        )

    monkeypatch.setattr(runner, "open_cache", open_cache)
    if has_key:
        monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-test-key")
    else:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", [
        "longmemeval", "--data", str(path), "--mode", "dense", "--embed", provider,
        "--dry-run", "--run", "safety-test",
    ])

    with pytest.raises(SystemExit, match="dense.*dry-run"):
        runner.main()

    assert calls == []
    assert not cache_file.exists()
    assert not runner.HERE.exists()


@pytest.mark.parametrize("mode", ["default", "passages"])
@pytest.mark.parametrize("context", ["sessions", "rounds"])
def test_supported_dry_runs_retrieve_without_model_calls(
    runner, monkeypatch, tmp_path, mode, context,
):
    path = dataset(tmp_path)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", [
        "longmemeval", "--data", str(path), "--mode", mode, "--context", context,
        "--dry-run", "--run", "safety-test",
    ])

    runner.main()

    report = json.loads((runner.HERE / "LongMemEval-results/safety-test.dryrun.json").read_text())
    assert report["questions"] == 1
    assert report["mode"] == mode
    assert report["context"] == context
    assert not list(runner.HERE.rglob("*.sqlite"))
    assert not list(runner.HERE.rglob("*.jsonl"))


def test_dense_live_run_still_prepares_embeddings_and_calls_reader_and_judge(
    runner, monkeypatch, tmp_path,
):
    path = dataset(tmp_path)
    calls = []
    cache = SimpleNamespace(
        model="fake", estimate_usd=lambda texts: (len(texts), 0.01),
        ensure=lambda texts, **kwargs: calls.append(("embedding", list(texts))),
        tokens=10, cost=0.01,
    )
    monkeypatch.setattr(runner, "open_cache", lambda *args: cache)
    monkeypatch.setattr(runner, "CachedProvider", lambda value: value)
    monkeypatch.setattr(runner, "retrieve", lambda *args: [0])

    def model_call(model, *args):
        calls.append((model,))
        return ("Vienna" if model == "fake-reader" else "yes", 0.0, "stop")

    monkeypatch.setattr(runner, "openrouter", model_call)
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(sys, "argv", [
        "longmemeval", "--data", str(path), "--mode", "dense", "--run", "safety-test",
        "--reader", "fake-reader", "--judge", "fake-judge",
    ])

    runner.main()

    assert [call[0] for call in calls] == ["embedding", "fake-reader", "fake-judge"]
    summary = json.loads((runner.HERE / "LongMemEval-results/safety-test.summary.json").read_text())
    assert summary["accuracy"] == 1.0
    assert summary["embedding"] == "cloud:fake"


def _codex_receipt(answer):
    return {
        "answer": answer, "requested_model": "fake-codex", "resolved_model": None,
        "requested_reasoning_effort": "low", "codex_version": "fake-version",
        "usage": {"input_tokens": 20, "output_tokens": 4}, "elapsed_seconds": 0.1,
    }


def _codex_arguments(path, out):
    return [
        "longmemeval", "--data", str(path), "--out-dir", str(out), "--run", "codex-test",
        "--inference-provider", "codex", "--codex-model", "fake-codex",
        "--codex-reasoning-effort", "low", "--mode", "passages", "--workers", "1",
        "--split", "dev", "--limit", "5",
    ]


def test_codex_run_records_receipts_and_allows_only_matching_resume(runner, monkeypatch, tmp_path):
    path = dataset(tmp_path)
    out = tmp_path / "explicit-results"
    argv = _codex_arguments(path, out)
    calls = []

    def read(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return _codex_receipt("Vienna" if len(calls) == 1 else "yes")

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(runner, "read_with_codex", read)
    monkeypatch.setattr(sys, "argv", argv)
    runner.main()

    assert len(calls) == 2
    assert "Correct Answer:" not in calls[0][0]
    assert "Correct Answer: Vienna" in calls[1][0]
    assert all(kwargs == {"model": "fake-codex", "reasoning_effort": "low"} for _, kwargs in calls)
    record = json.loads((out / "codex-test.jsonl").read_text())
    assert record["cost_usd"] is None
    assert record["reader_tokens"] is None and record["reader_tokens_enforced"] is False
    assert record["judge_tokens"] is None and record["judge_tokens_enforced"] is False
    assert record["autoeval_label"] == {"model": None, "requested_model": "fake-codex", "label": True}
    for role in ("reader", "judge"):
        receipt = record["inference_receipts"][role]
        assert receipt["resolved_model"] is None
        assert receipt["codex_version"] == "fake-version"
        assert len(receipt["prompt_sha256"]) == 64
    manifest = json.loads((out / "codex-test.manifest.json").read_text())
    assert manifest["selected_question_ids"] == ["synthetic-q1"]
    assert len(manifest["dataset"]["sha256"][path.name]) == 64
    assert "src/mnemosyne/retrieval.py" in manifest["source_sha256"]
    summary = json.loads((out / "codex-test.summary.json").read_text())
    assert summary["accuracy"] == 1.0 and summary["cost_usd"] is None
    assert summary["accuracy_ci_method"] == "wilson"
    assert 0 < summary["accuracy_ci95"][0] < 1
    assert summary["accuracy_ci95"][1] == 1
    assert summary["complete"] is True

    runner.main()
    assert len(calls) == 2
    monkeypatch.setattr(sys, "argv", argv + ["--codex-model", "changed-model"])
    with pytest.raises(ValueError, match="manifest differs"):
        runner.main()
    assert len(calls) == 2


@pytest.mark.parametrize("reply", ["yes.", "I think yes", "maybe", "yesterday"])
def test_codex_invalid_judge_is_retained_as_failure_without_scoring(runner, monkeypatch, tmp_path, reply):
    path = dataset(tmp_path)
    out = tmp_path / "explicit-results"
    responses = iter([_codex_receipt("Vienna"), _codex_receipt(reply)])
    monkeypatch.setattr(runner, "read_with_codex", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(sys, "argv", _codex_arguments(path, out))

    with pytest.raises(SystemExit, match="no aggregate score"):
        runner.main()

    failure = json.loads((out / "codex-test.failures.jsonl").read_text())
    assert failure["status"] == "failed"
    assert failure["inference_receipts"]["reader"]["answer"] == "Vienna"
    assert failure["inference_receipts"]["judge"]["answer"] == reply
    assert "autoeval_label" not in failure
    assert not (out / "codex-test.summary.json").exists()
    assert not (out / "codex-test.jsonl").exists()
    with pytest.raises(ValueError, match="failed attempts"):
        runner.main()


def test_codex_refuses_unmanifested_results(runner, monkeypatch, tmp_path):
    path = dataset(tmp_path)
    out = tmp_path / "explicit-results"
    out.mkdir()
    (out / "codex-test.jsonl").write_text('{}\n')
    monkeypatch.setattr(sys, "argv", _codex_arguments(path, out))
    with pytest.raises(ValueError, match="without a matching manifest"):
        runner.main()


def test_codex_dry_run_never_calls_models_and_dense_is_rejected(runner, monkeypatch, tmp_path):
    path = dataset(tmp_path)
    out = tmp_path / "explicit-results"
    argv = _codex_arguments(path, out)
    monkeypatch.setattr(sys, "argv", argv + ["--dry-run"])
    runner.main()
    assert not (out / "codex-test.manifest.json").exists()
    monkeypatch.setattr(sys, "argv", argv + ["--mode", "dense"])
    with pytest.raises(SystemExit, match="separate provider"):
        runner.main()


def test_answer_runner_uses_historical_dates_for_sessions_and_rounds(runner, tmp_path):
    path = dataset(tmp_path)
    row = json.loads(path.read_text())[0]
    row["question"] = "What did I say about Vienna yesterday?"
    row["question_date"] = "2024/08/13 (Tue) 12:00"
    row["haystack_dates"] = ["2024/08/12 (Mon) 12:00"]
    assert runner.retrieve(row, 5, "passages") == [0]
    assert runner.retrieve_rounds(row, "passages") == [(0, [0])]
