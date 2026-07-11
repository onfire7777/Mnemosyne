from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from eval.public.bundle import BundleError, reproduce_bundle, verify_bundle
from eval.public.runner import load_registry, run_public_suite
from eval.public.scoring import score_profile


def test_smoke_registry_is_pinned_and_permanently_non_publishable() -> None:
    suite = load_registry()["smoke"]
    assert len(suite["revision"]) == 40
    int(suite["revision"], 16)
    assert len(suite["dataset_sha256"]) == 64
    int(suite["dataset_sha256"], 16)
    assert suite["license"] == "CC0-1.0"
    assert suite["split_role"] == "development-self-test"
    assert suite["family"] == "deterministic-retrieval"
    assert suite["publishable"] is False
    assert suite["pbpp_headline_eligible"] is False
    assert suite["independent_external_reproduction"] is False


def test_smoke_run_writes_verifiable_cli_only_bundle(tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    result = run_public_suite("smoke", out)
    assert result["system_seam"] == "public-cli-subprocess"
    assert result["publishable"] is False
    assert verify_bundle(out)["valid"] is True

    traces = [
        json.loads(line) for line in (out / "traces.jsonl").read_text().splitlines()
    ]
    assert traces
    assert all(t["stored_records"] and "ranked_retrieved_hits" in t for t in traces)
    assert all(t["scoring_family"] == "deterministic-retrieval" for t in traces)
    metrics = json.loads((out / "metrics.json").read_text())
    assert metrics["interval"]["method"] == "wilson"
    assert metrics["trace_count"] == len(traces)


def test_bundle_detects_mutation_links_secrets_and_count_drift(tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    run_public_suite("smoke", out)
    (out / "metrics.json").write_text("{}\n")
    with pytest.raises(BundleError, match="digest"):
        verify_bundle(out)

    out2 = tmp_path / "linked"
    run_public_suite("smoke", out2)
    (out2 / "metrics.json").unlink()
    (out2 / "metrics.json").symlink_to(out / "metrics.json")
    with pytest.raises(BundleError, match="link"):
        verify_bundle(out2)

    out3 = tmp_path / "secret"
    run_public_suite("smoke", out3)
    traces = (
        out3 / "traces.jsonl"
    ).read_text() + '"ghp_abcdefghijklmnopqrstuvwxyz0123456789"\n'
    (out3 / "traces.jsonl").write_text(traces)
    _refresh_digest(out3, "traces.jsonl")
    with pytest.raises(BundleError, match="secret"):
        verify_bundle(out3)

    out3_end = tmp_path / "secret-end"
    run_public_suite("smoke", out3_end)
    traces = (out3_end / "traces.jsonl").read_text() + '"-----END PRIVATE KEY-----"\n'
    (out3_end / "traces.jsonl").write_text(traces)
    _refresh_digest(out3_end, "traces.jsonl")
    with pytest.raises(BundleError, match="secret"):
        verify_bundle(out3_end)

    out4 = tmp_path / "count"
    run_public_suite("smoke", out4)
    metrics = json.loads((out4 / "metrics.json").read_text())
    metrics["trace_count"] += 1
    (out4 / "metrics.json").write_text(
        json.dumps(metrics, sort_keys=True, separators=(",", ":")) + "\n"
    )
    _refresh_digest(out4, "metrics.json")
    with pytest.raises(BundleError, match="count"):
        verify_bundle(out4)


def test_reproduction_uses_bundle_custody_and_is_canonical(tmp_path: Path) -> None:
    source = tmp_path / "source"
    dest = tmp_path / "reproduced"
    run_public_suite("smoke", source)
    reproduce_bundle(source, dest)
    assert verify_bundle(dest)["valid"] is True
    assert (source / "traces.jsonl").read_bytes() == (
        dest / "traces.jsonl"
    ).read_bytes()
    assert (source / "metrics.json").read_bytes() == (
        dest / "metrics.json"
    ).read_bytes()
    with pytest.raises(FileExistsError):
        reproduce_bundle(source, dest)


def test_bundle_rejects_wrong_or_blended_metric_family(tmp_path: Path) -> None:
    wrong = tmp_path / "wrong"
    run_public_suite("smoke", wrong)
    metrics = json.loads((wrong / "metrics.json").read_text())
    metrics["interval"]["method"] = "bootstrap"
    _rewrite_json(wrong / "metrics.json", metrics)
    _refresh_digest(wrong, "metrics.json")
    with pytest.raises(BundleError, match="interval-family"):
        verify_bundle(wrong)

    blended = tmp_path / "blended"
    run_public_suite("smoke", blended)
    traces = [
        json.loads(line) for line in (blended / "traces.jsonl").read_text().splitlines()
    ]
    traces[0]["scoring_family"] = "qa"
    (blended / "traces.jsonl").write_text(
        "".join(
            json.dumps(trace, sort_keys=True, separators=(",", ":")) + "\n"
            for trace in traces
        )
    )
    _refresh_digest(blended, "traces.jsonl")
    with pytest.raises(BundleError, match="blended"):
        verify_bundle(blended)


def test_bundle_rejects_joint_benchmark_and_manifest_tampering(tmp_path: Path) -> None:
    out = tmp_path / "tampered"
    run_public_suite("smoke", out)
    benchmark = json.loads((out / "benchmark.json").read_text())
    benchmark["data"]["corpus"][0]["content"] = "tampered benchmark content"
    benchmark["metadata"]["dataset_sha256"] = _canonical_digest(benchmark["data"])
    _rewrite_json(out / "benchmark.json", benchmark)
    _refresh_digest(out, "benchmark.json")
    with pytest.raises(BundleError, match="registry anchor"):
        verify_bundle(out)


def test_bundle_rejects_metrics_that_do_not_recompute_from_traces(
    tmp_path: Path,
) -> None:
    out = tmp_path / "bad-metrics"
    run_public_suite("smoke", out)
    metrics = json.loads((out / "metrics.json").read_text())
    metrics["successes"] = 0
    metrics["value"] = 0.0
    _rewrite_json(out / "metrics.json", metrics)
    _refresh_digest(out, "metrics.json")
    with pytest.raises(BundleError, match="recompute"):
        verify_bundle(out)


def test_bundle_binds_traces_and_metric_to_anchored_benchmark(tmp_path: Path) -> None:
    out = tmp_path / "unbound-trace"
    run_public_suite("smoke", out)
    traces = [
        json.loads(line) for line in (out / "traces.jsonl").read_text().splitlines()
    ]
    traces[0]["question_id"] = "not-in-anchored-benchmark"
    traces[0]["gold_references"] = ["doc-orchard"]
    (out / "traces.jsonl").write_text(
        "".join(
            json.dumps(trace, sort_keys=True, separators=(",", ":")) + "\n"
            for trace in traces
        )
    )
    _refresh_digest(out, "traces.jsonl")
    with pytest.raises(BundleError, match="anchored benchmark questions"):
        verify_bundle(out)

    metric_out = tmp_path / "unbound-metric"
    run_public_suite("smoke", metric_out)
    metrics = json.loads((metric_out / "metrics.json").read_text())
    metrics["metric"] = "fabricated-label"
    _rewrite_json(metric_out / "metrics.json", metrics)
    _refresh_digest(metric_out, "metrics.json")
    with pytest.raises(BundleError, match="hit_at_k"):
        verify_bundle(metric_out)


def test_registry_rejects_unknown_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = load_registry()
    registry["smoke"]["adapter"] = "not-allowlisted"
    monkeypatch.setattr("eval.public.runner.load_registry", lambda: registry)
    with pytest.raises(ValueError, match="unsupported adapter"):
        run_public_suite("smoke", "/unused")


def test_asset_digest_preflight_runs_before_cli_evaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eval.public import runner

    registry = load_registry()
    registry["longmemeval-retrieval"]["dataset_sha256"] = "0" * 64
    monkeypatch.setattr(runner, "load_registry", lambda: registry)
    monkeypatch.setattr(runner, "load_asset_set", lambda *_args: {})
    monkeypatch.setitem(
        runner._NORMALIZERS, "longmemeval", lambda _value: {"normalized": True}
    )
    monkeypatch.setitem(
        runner._ADAPTERS,
        "longmemeval",
        lambda *_args: pytest.fail("adapter ran before digest preflight"),
    )

    with pytest.raises(ValueError, match="normalized benchmark digest"):
        run_public_suite(
            "longmemeval-retrieval", tmp_path / "out", dataset_dir=tmp_path
        )


def test_reproduction_rejects_canonical_output_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eval.public import runner

    source = tmp_path / "source"
    run_public_suite("smoke", source)
    original = runner._ADAPTERS["smoke"]

    def reordered(benchmark: object, cli: object) -> tuple[list[dict], dict]:
        traces, metrics = original(benchmark, cli)
        return list(reversed(traces)), metrics

    monkeypatch.setitem(runner._ADAPTERS, "smoke", reordered)
    with pytest.raises(BundleError, match="reproduction mismatch"):
        reproduce_bundle(source, tmp_path / "drifted")
    assert not (tmp_path / "drifted").exists()


def test_reproduction_cleans_invalid_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eval.public import runner

    source = tmp_path / "source"
    run_public_suite("smoke", source)
    original = runner._ADAPTERS["smoke"]

    def invalid(benchmark: object, cli: object) -> tuple[list[dict], dict]:
        traces, metrics = original(benchmark, cli)
        traces[0]["answer"] = "outside-corpus"
        return traces, metrics

    monkeypatch.setitem(runner._ADAPTERS, "smoke", invalid)
    destination = tmp_path / "invalid"
    with pytest.raises(BundleError, match="outside anchored benchmark corpus"):
        reproduce_bundle(source, destination)
    assert not destination.exists()


def test_qa_family_requires_disclosed_reader_and_judge(tmp_path: Path) -> None:
    out = tmp_path / "qa-without-judge"
    run_public_suite("smoke", out)
    config = json.loads((out / "config.json").read_text())
    config.update(family="qa", interval_method="bootstrap")
    _rewrite_json(out / "config.json", config)
    metrics = json.loads((out / "metrics.json").read_text())
    metrics.update(family="qa")
    metrics["interval"]["method"] = "bootstrap"
    _rewrite_json(out / "metrics.json", metrics)
    traces = [
        json.loads(line) for line in (out / "traces.jsonl").read_text().splitlines()
    ]
    for trace in traces:
        trace["scoring_family"] = "qa"
    (out / "traces.jsonl").write_text(
        "".join(
            json.dumps(trace, sort_keys=True, separators=(",", ":")) + "\n"
            for trace in traces
        )
    )
    for name in ("config.json", "metrics.json", "traces.jsonl"):
        _refresh_digest(out, name)
    with pytest.raises(BundleError, match="reader and judge"):
        verify_bundle(out)


def test_generalized_registry_profile_recomputes_benchmark_owned_metrics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eval.public.bundle import write_bundle

    benchmark = {
        "corpus": [{"doc_id": "a", "content": "A"}, {"doc_id": "b", "content": "B"}],
        "questions": [{"question_id": "q", "gold_references": ["a", "b"]}],
    }
    traces = [
        {
            "question_id": "q",
            "gold_references": ["a", "b"],
            "ranked_retrieved_hits": ["a", "b"],
            "scoring_family": "deterministic-retrieval",
            "stored_records": ["a", "b"],
            "answer": None,
        }
    ]
    metadata = {
        "adapter": "fixture",
        "dataset_sha256": _canonical_digest(benchmark),
        "family": "deterministic-retrieval",
        "independent_external_reproduction": False,
        "interval_method": "bootstrap",
        "license": "MIT",
        "pbpp_headline_eligible": False,
        "publishable": False,
        "revision": "a" * 40,
        "scoring_profile": "hipporag-retrieval-v1",
        "split_role": "test",
        "suite": "generalized-fixture",
    }
    monkeypatch.setattr(
        "eval.public.runner.load_registry",
        lambda: {"generalized-fixture": dict(metadata)},
    )
    measured = score_profile(
        "hipporag-retrieval-v1",
        [{"question_id": "q", "gold_references": ["a", "b"]}],
        traces,
    )
    out = tmp_path / "generalized"
    write_bundle(
        out, benchmark=benchmark, metadata=metadata, metrics=measured, traces=traces
    )
    assert verify_bundle(out)["valid"] is True
    metrics = json.loads((out / "metrics.json").read_text())
    metrics["metrics"]["recall_at_2"] = 0.0
    _rewrite_json(out / "metrics.json", metrics)
    _refresh_digest(out, "metrics.json")
    with pytest.raises(BundleError, match="anchored scoring profile"):
        verify_bundle(out)


def test_bundle_rejects_config_profile_not_bound_to_registry_metadata(
    tmp_path: Path,
) -> None:
    out = tmp_path / "config-substitution"
    run_public_suite("smoke", out)
    config = json.loads((out / "config.json").read_text())
    config.update(
        interval_method="bootstrap",
        scoring_profile="longmemeval-retrieval-v1",
    )
    _rewrite_json(out / "config.json", config)
    _refresh_digest(out, "config.json")
    with pytest.raises(BundleError, match="config does not match"):
        verify_bundle(out)


def test_external_multi_asset_adapter_reproduces_from_embedded_custody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eval.public import runner
    from eval.public.bundle import reproduce_bundle

    dataset = tmp_path / "dataset"
    dataset.mkdir()
    query_raw = b'[{"id":"q","gold":["a"]}]\n'
    corpus_raw = b'[{"id":"a","text":"alpha"}]\n'
    (dataset / "queries.json").write_bytes(query_raw)
    (dataset / "corpus.json").write_bytes(corpus_raw)
    benchmark = {
        "corpus": [{"doc_id": "a", "content": "alpha"}],
        "questions": [{"question_id": "q", "gold_references": ["a"]}],
    }
    assets = [
        {
            "filename": name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "revision": "b" * 40,
            "license": "MIT",
            "citation": "Fixture et al. (2026)",
            "split_role": "test",
            "contamination": "none known",
        }
        for name, raw in (("queries.json", query_raw), ("corpus.json", corpus_raw))
    ]
    suite = {
        "adapter": "external-fixture",
        "assets": assets,
        "dataset_sha256": _canonical_digest(benchmark),
        "family": "deterministic-retrieval",
        "independent_external_reproduction": False,
        "interval_method": "bootstrap",
        "license": "MIT",
        "pbpp_headline_eligible": False,
        "publishable": False,
        "revision": "b" * 40,
        "scoring_profile": "hipporag-retrieval-v1",
        "split_role": "test",
    }

    def adapter(value: dict, cli: object) -> tuple[dict, list[dict], dict]:
        normalized = benchmark if "assets" in value else value
        traces = [
            {
                "answer": None,
                "gold_references": ["a"],
                "question_id": "q",
                "ranked_retrieved_hits": ["a"],
                "scoring_family": "deterministic-retrieval",
                "stored_records": ["a"],
            }
        ]
        measured = score_profile(
            "hipporag-retrieval-v1",
            [{"question_id": "q", "gold_references": ["a"]}],
            traces,
        )
        return normalized, traces, measured

    monkeypatch.setattr(runner, "load_registry", lambda: {"external-fixture": suite})
    monkeypatch.setitem(runner._ADAPTERS, "external-fixture", adapter)
    monkeypatch.setitem(
        runner._NORMALIZERS, "external-fixture", lambda _value: benchmark
    )
    source, reproduced = tmp_path / "source", tmp_path / "reproduced"
    run_public_suite("external-fixture", source, dataset_dir=dataset)
    reproduce_bundle(source, reproduced)
    assert verify_bundle(reproduced)["valid"] is True
    assert (source / "traces.jsonl").read_bytes() == (
        reproduced / "traces.jsonl"
    ).read_bytes()


def test_qa_bundle_discloses_reader_and_recomputes_benchmark_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eval.public.bundle import write_bundle

    from mnemosyne.ids import evidence_cid
    capture = _capture("The red fox.")
    cid = evidence_cid(capture["content"], tenant_id=capture["tenant_id"], user_id=capture["user_id"], source_type=capture["source_type"], content_pointer=capture["content_pointer"], modality=capture["modality"], sensitivity=capture["sensitivity"])
    benchmark = {
        "corpus": [{"capture": capture, "content": "The red fox.", "doc_id": cid, "source_identity": "synthetic-fixture"}],
        "questions": [{"answers": ["red fox"], "question_id": "q1"}],
    }
    custody = _qa_custody()
    candidate = custody.pop("_candidate")
    metadata = {
        "adapter": "qa-fixture", "dataset_sha256": _canonical_digest(benchmark),
        "family": "qa", "independent_external_reproduction": False,
        "interval_method": "bootstrap", "interval_methods": {"exact_match": "wilson", "token_f1": "bootstrap"}, "license": "MIT",
        "pbpp_headline_eligible": False, "publishable": False,
        "qa_protocol_version": "phase12-candidate-v2", "revision": "c" * 40,
        "reader_custody": custody, "scoring_profile": "qa-em-f1-v1",
        "split_role": "held-out-test", "suite": "qa-fixture",
    }
    canonical = {key: value for key, value in metadata.items() if key not in {"reader_custody", "candidate_manifest"}}
    monkeypatch.setattr("eval.public.runner.load_registry", lambda: {"qa-fixture": canonical})
    monkeypatch.setattr("eval.public.runner.require_clean_candidate_checkout", lambda _sha: None)
    traces = [{
        "abstained": False, "answer": "red fox", "authorized_retrieval_hops": [_hop(0, cid, "The red fox.")],
        "authorized_evidence_fingerprint": _evidence_fingerprint([cid]),
        "claims": [{"evidence_cids": [cid], "text": "red fox"}],
        "question_id": "q1", "scoring_family": "qa",
    }]
    measured = score_profile("qa-em-f1-v1", [{"answers": ["red fox"], "question_id": "q1"}], traces)
    out = tmp_path / "qa"
    candidate_path = tmp_path / "candidate.json"
    _rewrite_json(candidate_path, candidate)
    write_bundle(out, benchmark=benchmark, metadata=metadata, metrics=measured, traces=traces, candidate_manifest_path=candidate_path)
    assert verify_bundle(out) == {"family": "qa", "suite": "qa-fixture", "valid": True}
    judge = json.loads((out / "judge.json").read_text())
    assert judge["custody"] == custody

    import shutil

    for name, mutate, message in (
        ("answer", lambda trace: trace.update(answer="not rendered"), "deterministically"),
        ("fingerprint", lambda trace: trace.update(authorized_evidence_fingerprint="0" * 64), "fingerprint"),
        ("outside", lambda trace: _fabricate_outside(trace), "anchored corpus"),
        ("duplicate", lambda trace: trace.update(authorized_retrieval_hops=[_hop(0, cid, "The red fox."), _hop(1, cid, "The red fox.")]), "duplicate"),
    ):
        attacked = tmp_path / f"qa-{name}"
        shutil.copytree(out, attacked)
        rows = [json.loads(line) for line in (attacked / "traces.jsonl").read_text().splitlines()]
        mutate(rows[0])
        (attacked / "traces.jsonl").write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows))
        _refresh_digest(attacked, "traces.jsonl")
        with pytest.raises(BundleError, match=message):
            verify_bundle(attacked)

    wrong_interval = tmp_path / "qa-interval"
    shutil.copytree(out, wrong_interval)
    metrics = json.loads((wrong_interval / "metrics.json").read_text())
    metrics["intervals"]["exact_match"]["method"] = "bootstrap"
    _rewrite_json(wrong_interval / "metrics.json", metrics)
    _refresh_digest(wrong_interval, "metrics.json")
    with pytest.raises(BundleError, match="mixed interval"):
        verify_bundle(wrong_interval)

    changed_candidate = tmp_path / "qa-candidate"
    shutil.copytree(out, changed_candidate)
    candidate_payload = json.loads((changed_candidate / "candidate-manifest.json").read_text())
    candidate_payload["git_sha"] = "f" * 40
    _rewrite_json(changed_candidate / "candidate-manifest.json", candidate_payload)
    _refresh_digest(changed_candidate, "candidate-manifest.json")
    with pytest.raises(BundleError, match="candidate manifest"):
        verify_bundle(changed_candidate)

    wrong_sha = tmp_path / "qa-self-consistent-wrong-sha"
    shutil.copytree(out, wrong_sha)
    wrong = "f" * 40
    build = json.loads((wrong_sha / "build.json").read_text())
    build["candidate_git_sha"] = wrong
    _rewrite_json(wrong_sha / "build.json", build)
    embedded = json.loads((wrong_sha / "candidate-manifest.json").read_text())
    embedded["git_sha"] = wrong
    _rewrite_json(wrong_sha / "candidate-manifest.json", embedded)
    embedded_digest = hashlib.sha256((wrong_sha / "candidate-manifest.json").read_bytes()).hexdigest()
    benchmark_payload = json.loads((wrong_sha / "benchmark.json").read_text())
    benchmark_payload["metadata"]["reader_custody"].update(candidate_git_sha=wrong, candidate_manifest_sha256=embedded_digest)
    _rewrite_json(wrong_sha / "benchmark.json", benchmark_payload)
    judge_payload = json.loads((wrong_sha / "judge.json").read_text())
    judge_payload["custody"].update(candidate_git_sha=wrong, candidate_manifest_sha256=embedded_digest)
    _rewrite_json(wrong_sha / "judge.json", judge_payload)
    for filename in ("build.json", "candidate-manifest.json", "benchmark.json", "judge.json"):
        _refresh_digest(wrong_sha, filename)
    with pytest.raises(BundleError, match="verifying checkout"):
        verify_bundle(wrong_sha)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("reader", {"name": "grounded-reader", "provider": "ollama", "selector": "latest", "model_revision": "latest", "model_content_sha256": "a" * 64}, "provider and selector"),
        ("prompt", {"aggregate_sha256": "bad", "roles": {}, "serializer_sha256": "b" * 64}, "prompt"),
        ("decoding", {}, "decoding"),
        ("evidence_budget", {}, "evidence budget"),
        ("abstention", {}, "abstention"),
        ("split_role", "development", "split"),
    ),
)
def test_qa_custody_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: object, message: str
) -> None:
    from eval.public.bundle import write_bundle

    benchmark = {"questions": [{"answers": ["x"], "question_id": "q"}]}
    custody = _qa_custody()
    candidate = custody.pop("_candidate")
    custody[field] = value
    metadata = {
        "adapter": "qa-fixture", "dataset_sha256": _canonical_digest(benchmark), "family": "qa",
        "independent_external_reproduction": False, "interval_method": "bootstrap", "interval_methods": {"exact_match": "wilson", "token_f1": "bootstrap"}, "license": "MIT",
        "pbpp_headline_eligible": False, "publishable": False, "qa_protocol_version": "phase12-candidate-v2",
        "revision": "c" * 40, "reader_custody": custody, "scoring_profile": "qa-em-f1-v1",
        "split_role": "held-out-test", "suite": "qa-fixture",
    }
    canonical = {key: nested for key, nested in metadata.items() if key not in {"reader_custody", "candidate_manifest"}}
    monkeypatch.setattr("eval.public.runner.load_registry", lambda: {"qa-fixture": canonical})
    monkeypatch.setattr("eval.public.runner.require_clean_candidate_checkout", lambda _sha: None)
    traces = [{"abstained": True, "answer": "", "authorized_retrieval_hops": [{"hop": 0, "rows": []}], "authorized_evidence_fingerprint": _evidence_fingerprint([]), "claims": [], "question_id": "q", "scoring_family": "qa"}]
    measured = score_profile("qa-em-f1-v1", [{"answers": ["x"], "question_id": "q"}], traces)
    out = tmp_path / field
    candidate_path = tmp_path / f"{field}-candidate.json"
    _rewrite_json(candidate_path, candidate)
    write_bundle(out, benchmark=benchmark, metadata=metadata, metrics=measured, traces=traces, candidate_manifest_path=candidate_path)
    with pytest.raises(BundleError, match=message):
        verify_bundle(out)


def _qa_custody() -> dict[str, object]:
    from eval.public.runner import load_qa_protocol, qa_protocol_digests
    from mnemosyne.providers.grounded_protocol import PROMPT_BUNDLES, role_digests

    protocol = load_qa_protocol()
    digests = qa_protocol_digests(protocol)
    candidate = {
        "candidate_version": protocol["version"], "created_at_utc": "2026-07-11T00:00:00Z",
        "git_sha": __import__("subprocess").run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip(), "model_content_sha256": "a" * 64,
        **digests, "transport_retries": 0,
    }
    custody = {
        "abstention": protocol["abstention"],
        "candidate_git_sha": candidate["git_sha"],
        "candidate_manifest_sha256": _canonical_digest(candidate),
        "decoding": protocol["decoding"],
        "evidence_budget": protocol["evidence_budget"],
        "prompt": {
            "aggregate_sha256": digests["prompt_sha256"],
            "roles": {
                role: {"template_sha256": role_digests(role)["prompt_sha256"]}
                for role in sorted(PROMPT_BUNDLES)
            },
            "serializer_sha256": digests["serializer_sha256"],
        },
        "protocol_version": protocol["version"],
        "reader": {"model_content_sha256": "a" * 64, "model_revision": "qwen3:4b", "name": "grounded-reader", "provider": "ollama", "selector": "qwen3:4b"},
        "split_role": "held-out-test",
        "transport_retries": 0,
    }
    custody["_candidate"] = candidate
    return custody


def _evidence_fingerprint(cids: list[str]) -> str:
    return _canonical_digest(sorted(cids))


def _hop(index: int, cid: str, content: str) -> dict[str, object]:
    return {"hop": index, "rows": [{"capture": _capture(content), "cid": cid}]}


def _capture(content: str) -> dict[str, object]:
    return {"actor": "user", "content": content, "content_pointer": None, "modality": "text", "sensitivity": 0, "source_identity": "synthetic-fixture", "source_type": "benchmark", "tenant_id": "qa-test", "user_id": "benchmark-user"}


def _fabricate_outside(trace: dict[str, object]) -> None:
    from mnemosyne.ids import evidence_cid
    capture = _capture("outside")
    cid = evidence_cid(capture["content"], tenant_id=capture["tenant_id"], user_id=capture["user_id"], source_type=capture["source_type"], content_pointer=capture["content_pointer"], modality=capture["modality"], sensitivity=capture["sensitivity"])
    trace.update(authorized_retrieval_hops=[_hop(0, cid, "outside")], authorized_evidence_fingerprint=_evidence_fingerprint([cid]))
    trace["claims"][0].update(evidence_cids=[cid])


@pytest.mark.parametrize(
    ("hops", "budget", "message"),
    (
        (
            [{"hop": index, "rows": []} for index in range(4)],
            {"max_characters": 24000, "max_hops": 3, "max_records": 20},
            "hop budget",
        ),
        (
            [{"hop": 0, "rows": []}],
            {"max_characters": 24000, "max_hops": 3, "max_records": 20},
            "record budget",
        ),
        (
            [{"hop": 0, "rows": []}],
            {"max_characters": 24000, "max_hops": 3, "max_records": 20},
            "character budget",
        ),
        (
            [{"hop": 1, "rows": []}],
            {"max_characters": 24000, "max_hops": 3, "max_records": 20},
            "ordered and contiguous",
        ),
        (
            [{"hop": False, "rows": []}],
            {"max_characters": 24000, "max_hops": 3, "max_records": 20},
            "hop schema",
        ),
    ),
)
def test_qa_authorized_retrieval_enforces_frozen_evidence_budget(
    hops: list[dict[str, object]],
    budget: dict[str, int],
    message: str,
) -> None:
    from eval.public.bundle import _authorized_cids_from_hops
    from mnemosyne.ids import evidence_cid

    count = 21 if message == "record budget" else 1
    content = "x" * 24001 if message == "character budget" else "evidence"
    corpus = []
    rows = []
    for index in range(count):
        capture = _capture(f"{content}{index}")
        cid = evidence_cid(
            capture["content"],
            tenant_id=capture["tenant_id"],
            user_id=capture["user_id"],
            source_type=capture["source_type"],
            content_pointer=capture["content_pointer"],
            modality=capture["modality"],
            sensitivity=capture["sensitivity"],
        )
        corpus.append(
            {
                "capture": capture,
                "content": capture["content"],
                "doc_id": cid,
                "source_identity": capture["source_identity"],
            }
        )
        rows.append({"capture": capture, "cid": cid})
    if message in {"record budget", "character budget"}:
        hops[0]["rows"] = rows
    with pytest.raises(BundleError, match=message):
        _authorized_cids_from_hops(hops, {"corpus": corpus}, budget)


def _refresh_digest(bundle: Path, name: str) -> None:
    import hashlib

    manifest_path = bundle / "bundle-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][name] = hashlib.sha256((bundle / name).read_bytes()).hexdigest()
    _rewrite_json(manifest_path, manifest)


def _rewrite_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def _canonical_digest(value: object) -> str:
    import hashlib

    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return hashlib.sha256(raw).hexdigest()
