"""Cross-interpreter replay uses synthetic responses, never a model or real data."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from eval.harness.cli_driver import MnemoCLI
from eval.public.adapters.locomo import LoCoMoError, split_samples
from eval.public.adapters.locomo_native import _prepare_native_replay, answer_captured_question
from eval.public.adapters.locomo_replay import _decode, replay_in_environment


def test_cross_environment_native_replay(tmp_path, monkeypatch):
    executable = os.environ.get("MNEMOSYNE_TEST_LOCOMO_PYTHON")
    if not executable:
        pytest.skip("requires explicit pinned scorer Python")
    sample = {"sample_id": "synthetic", "conversation": {
        "session_1_date_time": "Synthetic date", "session_1": [
            {"speaker": "A", "text": "violet kite", "dia_id": "D1:1"}]},
        "qa": [{"question": "What color?", "answer": "violet", "category": 4, "evidence": ["D1:1"]}]}
    context = _prepare_native_replay(sample, caption_policy="exclude-caption")
    store = tmp_path / "synthetic-store"
    store.write_text("synthetic transport only")
    conversation = {"sample_id": "synthetic", "tenant_id": context["tenant"],
                    "cli": MnemoCLI(store=str(store)), "evidence": context["evidence"]}

    def answer(cli, path):
        request = json.loads(Path(path).read_text())
        return {"results": [{"question_id": request["question_id"], "answer": "violet",
                             "abstained": False, "claims": [], "hops": [],
                             "reader": {"grounded_reader": {"provider": "synthetic"}}}]}

    monkeypatch.setattr(MnemoCLI, "eval_answer_batch", answer)
    record = answer_captured_question(conversation, split_samples([sample])["questions"][0], sample["qa"][0])
    kwargs = dict(caption_policy="exclude-caption", choice_draws={}, python=executable)
    report = replay_in_environment([sample], [record], **kwargs)
    assert report["categories"]["4"]["qa_source_denominator_mean"] == 1
    assert report["source_population_complete"] and not report["complete"]
    assert not report["publication_authorized"] and not report["runtime_custody_verified"]
    missing = replay_in_environment([sample], [], **kwargs)
    assert missing["categories"]["4"]["missing_count"] == 1
    record["decoded_prediction"] = "tampered"
    with pytest.raises(LoCoMoError, match="rejected replay"):
        replay_in_environment([sample], [record], **kwargs)


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}',
                               b'{"a":1e999}', b'not json'])
def test_replay_transport_rejects_ambiguous_json(raw):
    with pytest.raises(LoCoMoError):
        _decode(raw)


def test_replay_transport_rejects_wrong_response_and_timeout(monkeypatch):
    def wrong_response(argv, **kwargs):
        kwargs["stdout"].write(json.dumps({"request_sha256": "0" * 64, "report": {}}).encode())
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", wrong_response)
    with pytest.raises(LoCoMoError, match="bind the request"):
        replay_in_environment([], [], caption_policy="exclude-caption", choice_draws={}, python=sys.executable)

    def timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(LoCoMoError, match="timed out"):
        replay_in_environment([], [], caption_policy="exclude-caption", choice_draws={}, python=sys.executable)
