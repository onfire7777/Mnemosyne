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
