"""Synthetic result assembly never substitutes for a measured native run."""
from copy import deepcopy
from hashlib import sha256
import json
import os

import pytest

from eval.harness.cli_driver import MnemoCLI
from eval.public.adapters.locomo import LoCoMoError, UPSTREAM_REVISION
from eval.public.adapters.locomo_config import build_native_run_config
from eval.public.adapters.locomo_replay import replay_in_environment
from eval.public.adapters.locomo_results import assemble_development_result
from leaderboard.validate import DIGEST_PAYLOAD_NAMES, validate_record, verify_result_digests
from tests.test_leaderboard_result_contract import _v2_development_record


def encode(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def inventory(payloads):
    payloads["bundle-manifest.json"] = encode({"version": 1, "files": {
        name: sha256(raw).hexdigest() for name, raw in payloads.items() if name != "bundle-manifest.json"}})


@pytest.fixture
def inputs():
    python = os.environ.get("MNEMOSYNE_TEST_LOCOMO_PYTHON")
    if not python:
        pytest.skip("requires explicit pinned scorer Python")
    source = [{"sample_id": "synthetic", "conversation": {"session_1_date_time": "Synthetic date",
        "session_1": [{"dia_id": "D1:1", "speaker": "A", "text": "synthetic input"}]},
        "qa": [{"question": "Synthetic?", "answer": "unused", "category": 4, "evidence": []}]}]
    policy = {"schema_version": "mnemosyne.reader-policy/v1", "candidate_git_sha": "a" * 40,
              "candidate_manifest_sha256": "b" * 64, "reader": {role: {
                  "role": role, "model": "synthetic", "model_content_digest": "c" * 64,
                  "prompt_sha256": "d" * 64, "serializer_sha256": "e" * 64,
                  "decoding_options": {"synthetic": True},
                  "decoding_sha256": sha256(b'{"synthetic":true}').hexdigest(),
              } for role in ("query_decomposer", "grounded_reader")}}
    config = build_native_run_config(source, MnemoCLI(store="unused"), caption_policy="exclude-caption",
        choice_seed=1, reader_policy=policy, runtime_manifest_sha256="1" * 64, resource_manifest_sha256="2" * 64)
    report = replay_in_environment(source, [], caption_policy="exclude-caption", choice_seed=1,
                                   reader_policy=policy, run_config=config, python=python)
    payloads = {"benchmark.json": encode({"data": source, "metadata": {"synthetic": True}}),
                "build.json": encode({"candidate_git_sha": "a" * 40, "system_seam": "public-cli-subprocess"}),
                "config.json": encode({"family": "native-memory-qa", "scoring_profile": "locomo-native-v1", "native_run": config}),
                "traces.jsonl": b"", "native-replay.json": encode(report)}
    inventory(payloads)
    metadata = _v2_development_record()
    for field in ("schema_version", "metrics", *DIGEST_PAYLOAD_NAMES):
        metadata.pop(field)
    metadata.update(run_commit="a" * 40, benchmark="locomo-native", benchmark_version=UPSTREAM_REVISION,
        resources={"treatment": "resource-unverified"}, attempt_outcome="not-measured",
        safety_gates=[{"name": "runtime-admission", "status": "not-measured"}])
    metadata["identity"].update(system_id="mnemosyne", adapter_id="mnemosyne-locomo-native",
        adapter_version=report["protocol_sha256"], benchmark_id="locomo-native", benchmark_version=UPSTREAM_REVISION,
        backend_id="local", dataset_split_digest="sha256:" + report["source_sha256"])
    return metadata, payloads, python


def test_assemble_one_atomic_native_qa_result_and_retain_recall_artifact(inputs):
    metadata, payloads, python = inputs
    before = deepcopy(metadata)
    result = assemble_development_result(metadata, payloads, scorer_python=python)
    assert validate_record(result) == [] and verify_result_digests(result, payloads) == []
    assert result["identity"] == before["identity"] and metadata == before
    assert {metric["family"] for metric in result["metrics"]} == {"reference_qa"}
    assert len(result["metrics"]) == 5
    assert result["metrics"][3]["value"] == 0 and result["metrics"][3]["status"] == "incomplete"
    assert result["attempt_outcome"] == "not-measured" and not result["publication"]["publishable"]
    assert len(json.loads(payloads["native-replay.json"])["category_metrics"]["retrieval"]) == 5


@pytest.mark.parametrize("fault", ["commit", "seed", "adapter", "source_identity", "resources", "safety", "outcome", "derived", "inventory", "source", "report"])
def test_native_assembly_rejects_metadata_drift_and_rehashed_false_evidence(inputs, fault):
    metadata, payloads, python = inputs
    if fault == "commit":
        metadata["run_commit"] = "f" * 40
    elif fault == "seed":
        metadata["identity"]["seed"] = 2
    elif fault == "adapter":
        metadata["identity"]["adapter_version"] = "floating"
    elif fault == "source_identity":
        metadata["identity"]["dataset_split_digest"] = "sha256:" + "f" * 64
    elif fault == "resources":
        metadata["resources"]["treatment"] = "verified"
    elif fault == "safety":
        metadata["safety_gates"][0]["status"] = "passed"
    elif fault == "outcome":
        metadata["attempt_outcome"] = "measured"
    elif fault == "derived":
        metadata["metrics"] = []
    elif fault == "inventory":
        payloads["traces.jsonl"] = b"changed"
    elif fault == "source":
        source = json.loads(payloads["benchmark.json"])
        source["data"][0]["conversation"]["session_1"][0]["text"] = "changed"
        payloads["benchmark.json"] = encode(source)
        inventory(payloads)
    else:
        report = json.loads(payloads["native-replay.json"])
        report["complete"] = True
        payloads["native-replay.json"] = encode(report)
        inventory(payloads)
    with pytest.raises(LoCoMoError):
        assemble_development_result(metadata, payloads, scorer_python=python)


def test_answered_replay_does_not_become_verified_model_execution(inputs, tmp_path, monkeypatch):
    from eval.public.adapters.locomo import split_samples
    from eval.public.adapters.locomo_native import _prepare_native_replay, answer_captured_question
    metadata, payloads, python = inputs
    source = json.loads(payloads["benchmark.json"])["data"]
    config = json.loads(payloads["config.json"])["native_run"]
    context = _prepare_native_replay(source[0], caption_policy=config["caption_policy"])
    store = tmp_path / "synthetic-store"
    store.write_bytes(b"synthetic transport only")
    question = split_samples(source)["questions"][0]

    def answer(cli, path, *, include_derivation=False):
        return {"results": [{"question_id": question["question_id"], "answer": None,
            "abstained": True, "claims": [], "hops": [], "reader": config["reader_policy"]["reader"]}]}

    monkeypatch.setattr(MnemoCLI, "eval_answer_batch", answer)
    conversation = {"sample_id": source[0]["sample_id"], "tenant_id": context["tenant"],
                    "evidence": context["evidence"], "cli": MnemoCLI(store=str(store))}
    record = answer_captured_question(conversation, question, source[0]["qa"][0],
                                     reader_policy=config["reader_policy"], run_config=config)
    report = replay_in_environment(source, [record], caption_policy=config["caption_policy"],
        reader_policy=config["reader_policy"], run_config=config, choice_seed=1, python=python)
    assert report["source_population_complete"]
    payloads["traces.jsonl"] = encode(record)
    payloads["native-replay.json"] = encode(report)
    inventory(payloads)
    result = assemble_development_result(metadata, payloads, scorer_python=python)
    assert result["metrics"][3]["observed_count"] == 1
    assert result["attempt_outcome"] == "not-measured"
    assert result["resources"]["treatment"] == "resource-unverified"
