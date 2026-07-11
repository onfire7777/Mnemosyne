from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
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
    assert [hit["id"] for hit in results[0][0]["hits"]] == [
        hit["id"] for hit in ordinary_search["hits"]
    ]
    assert results[0][1]["explain"].get("channels") == ordinary_search["explain"].get(
        "channels"
    )
    assert {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in state_files
    } == before
    assert {path.name for path in tmp_path.iterdir()} == before_names | {
        "ordinary.json",
        "ordinary.json.runtime.json",
    }
    with pytest.raises(CLIError, match="restricted to local evaluation query"):
        read_only.capture_batch(rows)


def test_evaluation_query_batch_matches_public_search_explain_and_is_read_only(
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
    queries = tmp_path / "queries.jsonl"
    query_rows = [
        {"question_id": "q1", "tenant": "t", "query": "alpha"},
        {"question_id": "q2", "tenant": "t", "query": "graph"},
    ]
    queries.write_text("".join(json.dumps(row) + "\n" for row in query_rows))
    reversed_queries = tmp_path / "reversed.jsonl"
    reversed_queries.write_text(
        "".join(json.dumps(row) + "\n" for row in reversed(query_rows))
    )
    singles = []
    for index, row in enumerate(query_rows):
        path = tmp_path / f"single-{index}.jsonl"
        path.write_text(json.dumps(row) + "\n")
        singles.append(path)
    duplicate = tmp_path / "duplicate.jsonl"
    duplicate.write_text(
        '{"question_id":"q","question_id":"other","tenant":"t","query":"x"}\n'
    )
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    read_only = replace(cli, global_flags=["--evaluation-read-only"])
    result = read_only.eval_query_batch(queries)
    assert result["count"] == 2
    assert [row["question_id"] for row in result["results"]] == ["q1", "q2"]
    assert all(row["search"]["hits"] for row in result["results"])
    reversed_result = read_only.eval_query_batch(reversed_queries)
    single_results = [read_only.eval_query_batch(path) for path in singles]

    def projections(payloads: list[dict]) -> dict[str, tuple[list[str], object]]:
        return {
            row["question_id"]: (
                [hit["id"] for hit in row["search"]["hits"]],
                row["explanation"].get("channels"),
            )
            for payload in payloads
            for row in payload["results"]
        }

    assert projections([result]) == projections([reversed_result])
    assert projections([result]) == projections(single_results)
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before

    with pytest.raises(CLIError, match="invalid JSON"):
        read_only.eval_query_batch(duplicate)
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


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
            self.engine = self

        def defer_persistence(self):
            return nullcontext()

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


def test_local_engine_deferred_persistence_flushes_once_or_discards(
    tmp_path: Path,
) -> None:
    from mnemosyne.engine import LocalMemoryEngine

    committed = tmp_path / "committed.json"
    engine = LocalMemoryEngine(store_path=committed)
    with engine.defer_persistence():
        with engine.defer_persistence():
            engine._persist()
            engine._persist()
            assert not committed.exists()
        assert not committed.exists()
    assert committed.is_file()

    discarded = tmp_path / "discarded.json"
    engine = LocalMemoryEngine(store_path=discarded)
    with pytest.raises(RuntimeError, match="abort"):
        with engine.defer_persistence():
            engine._persist()
            raise RuntimeError("abort")
    assert not discarded.exists()
    with pytest.raises(RuntimeError, match="transaction was aborted"):
        engine._persist()


def test_cli_qa_run_verify_reproduce_and_report_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess
    from eval.public.runner import load_qa_protocol, qa_protocol_digests
    import eval.public.runner as public_runner
    from mnemosyne.cli import main

    protocol, digests = load_qa_protocol(), qa_protocol_digests()
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    candidate = {
        "candidate_version": protocol["version"], "created_at_utc": "2026-07-11T00:00:00Z",
        "git_sha": head, "model_content_sha256": "a" * 64, **digests, "transport_retries": 0,
    }
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(candidate, sort_keys=True, separators=(",", ":")) + "\n")
    source, reproduced = tmp_path / "qa-source", tmp_path / "qa-reproduced"
    report, note = tmp_path / "qa-report.json", tmp_path / "qa-report.md"
    monkeypatch.setattr(public_runner, "require_clean_candidate_checkout", lambda _sha: None)
    assert main(["eval-public", "--suite", "qa-smoke", "--candidate-manifest", str(candidate_path), "--out-dir", str(source)]) == 0
    assert main(["eval-public", "--verify-bundle", str(source)]) == 0
    assert main(["eval-public", "--reproduce-bundle", str(source), "--out-dir", str(reproduced)]) == 0
    assert (source / "candidate-manifest.json").read_bytes() == (reproduced / "candidate-manifest.json").read_bytes()
    assert main(["eval-public", "--write-report", str(source), "--reproduced-bundle", str(reproduced), "--report-output", str(report), "--report-note", str(note)]) == 0
    assert main(["eval-public", "--verify-report", str(report), "--report-note", str(note)]) == 0
