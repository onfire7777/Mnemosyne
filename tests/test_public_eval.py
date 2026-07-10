from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.public.bundle import BundleError, reproduce_bundle, verify_bundle
from eval.public.runner import load_registry, run_public_suite


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

    traces = [json.loads(line) for line in (out / "traces.jsonl").read_text().splitlines()]
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
    traces = (out3 / "traces.jsonl").read_text() + '"ghp_abcdefghijklmnopqrstuvwxyz0123456789"\n'
    (out3 / "traces.jsonl").write_text(traces)
    _refresh_digest(out3, "traces.jsonl")
    with pytest.raises(BundleError, match="secret"):
        verify_bundle(out3)

    out4 = tmp_path / "count"
    run_public_suite("smoke", out4)
    metrics = json.loads((out4 / "metrics.json").read_text())
    metrics["trace_count"] += 1
    (out4 / "metrics.json").write_text(json.dumps(metrics, sort_keys=True, separators=(",", ":")) + "\n")
    _refresh_digest(out4, "metrics.json")
    with pytest.raises(BundleError, match="count"):
        verify_bundle(out4)


def test_reproduction_uses_bundle_custody_and_is_canonical(tmp_path: Path) -> None:
    source = tmp_path / "source"
    dest = tmp_path / "reproduced"
    run_public_suite("smoke", source)
    reproduce_bundle(source, dest)
    assert verify_bundle(dest)["valid"] is True
    assert (source / "traces.jsonl").read_bytes() == (dest / "traces.jsonl").read_bytes()
    assert (source / "metrics.json").read_bytes() == (dest / "metrics.json").read_bytes()
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
    traces = [json.loads(line) for line in (blended / "traces.jsonl").read_text().splitlines()]
    traces[0]["scoring_family"] = "qa"
    (blended / "traces.jsonl").write_text("".join(json.dumps(trace, sort_keys=True, separators=(",", ":")) + "\n" for trace in traces))
    _refresh_digest(blended, "traces.jsonl")
    with pytest.raises(BundleError, match="blended"):
        verify_bundle(blended)


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
    traces = [json.loads(line) for line in (out / "traces.jsonl").read_text().splitlines()]
    for trace in traces:
        trace["scoring_family"] = "qa"
    (out / "traces.jsonl").write_text("".join(json.dumps(trace, sort_keys=True, separators=(",", ":")) + "\n" for trace in traces))
    for name in ("config.json", "metrics.json", "traces.jsonl"):
        _refresh_digest(out, name)
    with pytest.raises(BundleError, match="reader and judge"):
        verify_bundle(out)


def _refresh_digest(bundle: Path, name: str) -> None:
    import hashlib

    manifest_path = bundle / "bundle-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][name] = hashlib.sha256((bundle / name).read_bytes()).hexdigest()
    _rewrite_json(manifest_path, manifest)


def _rewrite_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
