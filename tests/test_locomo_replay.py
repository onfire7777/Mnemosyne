"""Cross-interpreter replay uses synthetic responses, never a model or real data."""
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from eval.harness.cli_driver import MnemoCLI
from eval.public.adapters.locomo import LoCoMoError, split_samples
from eval.public.adapters.locomo_native import _prepare_native_replay, answer_captured_question
from eval.public.adapters.locomo_replay import _decode, replay_in_environment, verify_report_in_environment


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
    reader = {"grounded_reader": {"provider": "synthetic"}}

    def answer(cli, path, *, include_derivation=False):
        request = json.loads(Path(path).read_text())
        cid = next(iter(context["evidence"]))
        start = context["evidence"][cid]["capture"]["content"].index("violet")
        claim = {"text": "violet", "evidence_cids": [cid],
                 "derivation": {"schema_version": "mnemosyne.claim-derivation/v1", "kind": "quotation", "operation": None}, "spans": [{"cid": cid,
                 "start": start, "end": start + 6, "slice_sha256": sha256(b"violet").hexdigest()}]}
        return {"results": [{"question_id": request["question_id"], "answer": "violet",
                             "abstained": False, "claims": [claim], "hops": [{"retrieved_cids": [cid]}],
                             "reader": reader}]}

    monkeypatch.setattr(MnemoCLI, "eval_answer_batch", answer)
    record = answer_captured_question(conversation, split_samples([sample])["questions"][0], sample["qa"][0])
    kwargs = dict(caption_policy="exclude-caption", choice_draws={}, python=executable)
    report = replay_in_environment([sample], [record], **kwargs)
    assert report["categories"]["4"]["qa_source_denominator_mean"] == 1
    assert report["source_population_complete"] and not report["complete"]
    assert not report["publication_authorized"] and not report["runtime_custody_verified"]
    saved = tmp_path / "report.json"
    saved.write_text(json.dumps(report))
    assert verify_report_in_environment(json.loads(saved.read_text()), [sample], [record], **kwargs) == report
    assert report["protocol"]["id"] == "mnemosyne.locomo-native-scoring/v1"
    assert len(report["protocol"]["replay_source_sha256"]) == 11
    for field, changed in (
        ("categories", {}), ("caption_policy", "include-source-caption"),
        ("protocol", {**report["protocol"], "scorer_dependencies": {}}),
        ("protocol_sha256", "0" * 64), ("publication_authorized", 0),
    ):
        with pytest.raises(LoCoMoError, match="saved native report"):
            verify_report_in_environment({**report, field: changed}, [sample], [record], **kwargs)
    missing = replay_in_environment([sample], [], **kwargs)
    assert missing["categories"]["4"]["missing_count"] == 1
    options = {"synthetic": True}
    policy = {"schema_version": "mnemosyne.reader-policy/v1", "candidate_git_sha": "a" * 40,
              "candidate_manifest_sha256": "b" * 64, "reader": {role: {
                  "role": role, "model": "synthetic", "model_content_digest": "c" * 64,
                  "prompt_sha256": "d" * 64, "serializer_sha256": "e" * 64,
                  "decoding_options": options,
                  "decoding_sha256": sha256(b'{"synthetic":true}').hexdigest(),
              } for role in ("query_decomposer", "grounded_reader")}}
    reader = policy["reader"]
    bound_record = answer_captured_question(conversation, split_samples([sample])["questions"][0],
                                            sample["qa"][0], reader_policy=policy)
    assert bound_record["reader_policy_matched"] and not bound_record["runtime_custody_verified"]
    bound_report = replay_in_environment([sample], [bound_record], reader_policy=policy, **kwargs)
    assert bound_report["reader_policy"] == policy

    from copy import deepcopy
    from eval.public.adapters.locomo_config import build_native_run_config, validate_native_run_config
    from eval.public.adapters.locomo_native import iter_native_answers
    config = build_native_run_config([sample], conversation["cli"], reader_policy=policy,
              caption_policy="exclude-caption", choice_draws={},
              runtime_manifest_sha256="1" * 64, resource_manifest_sha256="2" * 64)
    config_digest = validate_native_run_config(config)
    configured_record = answer_captured_question(conversation, split_samples([sample])["questions"][0],
                        sample["qa"][0], reader_policy=policy, run_config=config)
    assert configured_record["run_config_sha256"] == config_digest
    configured_report = replay_in_environment([sample], [configured_record], reader_policy=policy,
                                               run_config=config, **kwargs)
    assert configured_report["run_config"] == config
    assert configured_report["run_config_sha256"] == config_digest
    assert not configured_report["runtime_custody_verified"]
    assert verify_report_in_environment(configured_report, [sample], [configured_record],
                        reader_policy=policy, run_config=config, **kwargs) == configured_report
    for field in ("source_sha256", "normalized_sha256", "replay_protocol_sha256",
                  "runtime_manifest_sha256", "resource_manifest_sha256"):
        damaged = {**config, field: "f" * 64}
        with pytest.raises(LoCoMoError, match="rejected replay"):
            replay_in_environment([sample], [configured_record], reader_policy=policy,
                                    run_config=damaged, **kwargs)
    with pytest.raises(LoCoMoError, match="rejected replay"):
        replay_in_environment([sample], [configured_record], reader_policy=policy, **kwargs)

    def forbidden_capture(*args, **kwargs):
        pytest.fail("configuration drift must fail before public capture")

    monkeypatch.setattr(MnemoCLI, "capture_batch", forbidden_capture)
    for fault in ("timeout", "flags", "source", "choice"):
        damaged = deepcopy(config)
        if fault == "timeout":
            damaged["cli"]["timeout_seconds"] += 1
        elif fault == "flags":
            damaged["cli"]["global_flags_sha256"] = "0" * 64
        elif fault == "source":
            damaged["source_sha256"] = "0" * 64
        else:
            damaged["choice_policy"] = {"id": "python-random-source-order/v1", "seed": 1, "draws": {}}
        with pytest.raises(LoCoMoError):
            list(iter_native_answers([sample], conversation["cli"], caption_policy="exclude-caption",
                    choice_draws={}, reader_policy=policy, run_config=damaged))
    with pytest.raises(LoCoMoError, match="rejected replay"):
        replay_in_environment([sample], [bound_record], **kwargs)
    changed = {**policy, "candidate_manifest_sha256": "f" * 64}
    with pytest.raises(LoCoMoError, match="rejected replay"):
        replay_in_environment([sample], [bound_record], reader_policy=changed, **kwargs)
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


def test_choice_seed_reproduces_across_interpreters():
    from eval.public.adapters.locomo import native_choice_policy
    executable = os.environ.get("MNEMOSYNE_TEST_LOCOMO_PYTHON")
    if not executable:
        pytest.skip("requires explicit pinned scorer Python")
    source = [{"sample_id": "synthetic-seed", "conversation": {
        "session_1_date_time": "Synthetic date", "session_1": [
            {"speaker": "A", "text": "violet kite", "dia_id": "D1:1"}]},
        "qa": [{"question": f"Synthetic {i}?", "answer": "distractor", "category": 5,
                "evidence": []} for i in range(2)]}]
    policy = native_choice_policy(source, choice_seed=1)
    report = replay_in_environment(source, [], caption_policy="exclude-caption",
                                    choice_seed=1, python=executable)
    assert report["choice_policy"] == policy
    assert report["categories"]["5"]["missing_count"] == 2
    assert not report["complete"] and not report["runtime_custody_verified"]
    with pytest.raises(LoCoMoError, match="rejected replay"):
        replay_in_environment(source, [], caption_policy="exclude-caption",
                              choice_seed=1, choice_draws=policy["draws"], python=executable)
