from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from eval.harness.cli_driver import CLIError, MnemoCLI
from eval.public.bundle import BundleError, verify_report, write_report
from eval.public.runner import run_public_suite


def test_report_requires_matching_verified_reproduction_and_binds_note(
    tmp_path: Path,
) -> None:
    source, reproduced = tmp_path / "source", tmp_path / "reproduced"
    run_public_suite("smoke", source)
    from eval.public.bundle import reproduce_bundle

    reproduce_bundle(source, reproduced)
    report, note = tmp_path / "report.json", tmp_path / "report.md"
    result = write_report(source, reproduced, report, note)
    assert result["sha256"] == hashlib.sha256(report.read_bytes()).hexdigest()
    assert verify_report(report, note)["valid"] is True
    assert result["sha256"] in note.read_text()
    payload = json.loads(report.read_text())
    assert payload["evidence"]["assets"][0]["dataset_sha256"]
    assert payload["evidence"]["counts"] == {"eligible": 2, "excluded": 0, "traces": 2}
    assert payload["evidence"]["metrics"]["trace_count"] == 2
    assert payload["evidence"]["reproduction"]["verified"] is True
    assert payload["generated_at"].endswith("Z")
    assert payload["command"][0:2] == ["mneme", "eval-public"]

    note.write_text(note.read_text().replace(result["sha256"], "0" * 64))
    with pytest.raises(BundleError, match="note binding"):
        verify_report(report, note)

    # Canonical byte equality rejects plausible-looking prefix/suffix text too.
    note.write_bytes(b"trusted\n" + note.read_bytes())
    with pytest.raises(BundleError, match="canonical"):
        verify_report(report, note)


def test_report_refuses_mismatched_reproduction(tmp_path: Path) -> None:
    source, reproduced = tmp_path / "source", tmp_path / "reproduced"
    run_public_suite("smoke", source)
    run_public_suite("smoke", reproduced)
    traces = reproduced / "traces.jsonl"
    traces.write_bytes(
        b"".join(reversed(traces.read_bytes().splitlines(keepends=True)))
    )
    manifest = json.loads((reproduced / "bundle-manifest.json").read_text())
    manifest["files"]["traces.jsonl"] = hashlib.sha256(traces.read_bytes()).hexdigest()
    (reproduced / "bundle-manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    )
    with pytest.raises(BundleError):
        write_report(source, reproduced, tmp_path / "report.json", tmp_path / "note.md")


def test_capture_batch_matches_capture_and_rejects_schema_before_writes(
    tmp_path: Path,
) -> None:
    cli = MnemoCLI(store=str(tmp_path / "store.json"))
    rows = tmp_path / "rows.jsonl"
    rows.write_text(
        json.dumps(
            {"tenant": "t", "user": "u", "source_type": "benchmark", "content": "alpha"}
        )
        + "\n"
        + json.dumps(
            {
                "tenant": "t",
                "user": "u",
                "source_type": "benchmark",
                "content": "beta",
                "trust_tier": 1,
            }
        )
        + "\n"
    )
    result = cli.capture_batch(rows)
    assert result["ok"] is True and result["count"] == 2
    assert len(result["results"]) == 2

    bad = tmp_path / "bad.jsonl"
    bad.write_text(
        json.dumps(
            {"tenant": "t", "user": "u", "source_type": "benchmark", "content": "gamma"}
        )
        + "\n{}\n"
    )
    before = cli.search("t", "gamma")
    with pytest.raises(CLIError, match="invalid schema"):
        cli.capture_batch(bad)
    after = cli.search("t", "gamma")
    assert before == after


def test_capture_batch_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.jsonl"
    target.write_text(
        json.dumps({"tenant": "t", "user": "u", "source_type": "x", "content": "x"})
        + "\n"
    )
    linked = tmp_path / "linked.jsonl"
    linked.symlink_to(target)
    with pytest.raises(CLIError, match="real file"):
        MnemoCLI(store=str(tmp_path / "store.json")).capture_batch(linked)


def test_evaluation_read_only_allows_concurrent_queries_without_store_writes(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store.json"
    cli = MnemoCLI(store=str(store))
    rows = tmp_path / "rows.jsonl"
    rows.write_text(
        json.dumps(
            {
                "tenant": "t",
                "user": "u",
                "source_type": "benchmark",
                "content": "alpha graph evidence",
            }
        )
        + "\n"
    )
    cli.capture_batch(rows)
    state_files = [store, *tmp_path.glob("store.json.runtime.json")]
    before_names = {path.name for path in tmp_path.iterdir()}
    before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in state_files
    }
    read_only = replace(cli, global_flags=["--evaluation-read-only"])

    def query(_: int) -> tuple[dict, dict]:
        return read_only.search("t", "alpha"), read_only.explain("t", "alpha")

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(query, range(8)))

    assert all(search["hits"] for search, _ in results)
    ordinary_store = tmp_path / "ordinary.json"
    ordinary_store.write_bytes(store.read_bytes())
    ordinary = MnemoCLI(store=str(ordinary_store))
    ordinary_search = ordinary.search("t", "alpha")
    ordinary_explain = ordinary.explain("t", "alpha")
    assert [hit["id"] for hit in results[0][0]["hits"]] == [
        hit["id"] for hit in ordinary_search["hits"]
    ]
    assert results[0][1].get("channels") == ordinary_explain.get("channels")
    assert {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in state_files
    } == before
    assert {path.name for path in tmp_path.iterdir()} == before_names | {
        "ordinary.json",
        "ordinary.json.runtime.json",
    }
    with pytest.raises(CLIError, match="restricted to local search and explain"):
        read_only.capture_batch(rows)


def test_capture_batch_rolls_back_a_later_capture_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse
    from mnemosyne import cli as cli_module

    store = tmp_path / "store.json"
    store.write_text('{"original":true}\n')
    rows = tmp_path / "rows.jsonl"
    rows.write_text(
        "".join(
            json.dumps(
                {"tenant": "t", "user": "u", "source_type": "x", "content": value}
            )
            + "\n"
            for value in ("one", "two")
        )
    )

    class FailingTools:
        def __init__(self, staged: Path) -> None:
            self.staged = staged
            self.calls = 0

        def capture(self, **kwargs: object) -> dict[str, object]:
            self.calls += 1
            self.staged.write_text(json.dumps({"captured": self.calls}))
            if self.calls == 2:
                raise RuntimeError("injected later failure")
            return {"ok": True}

    monkeypatch.setattr(
        cli_module, "load_tools", lambda args: FailingTools(Path(args.store))
    )
    args = argparse.Namespace(
        backend="local",
        store=str(store),
        input_jsonl=rows,
        max_records=10,
        max_ingest_bytes=1024 * 1024,
    )
    with pytest.raises(RuntimeError, match="injected"):
        cli_module.cmd_capture_batch(args)
    assert store.read_text() == '{"original":true}\n'
    assert not list(tmp_path.glob(".store.json-batch-*"))
