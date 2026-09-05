import base64
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import leaderboard.publish as publication
from leaderboard.ledger import append_entry
from leaderboard.publish import PublicationError, main, publish_site
from leaderboard.render import render_site
from leaderboard.validate import DIGEST_PAYLOAD_NAMES
from tests.test_leaderboard_result_contract import (
    _v2_development_record,
    _v2_successor_record,
)

_TRACE_TEXT = (
    json.dumps(
        {
            "answer": "doc-1",
            "gold_references": ["doc-1"],
            "question_id": "question-001",
            "ranked_retrieved_hits": ["doc-1", "doc-2"],
            "scoring_family": "deterministic-retrieval",
            "stored_records": ["doc-1", "doc-2"],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    + "\n"
)


@pytest.fixture
def key_paths(tmp_path: Path) -> tuple[Path, Path]:
    private_key = Ed25519PrivateKey.generate()
    private_path = tmp_path / "ledger-private.pem"
    public_path = tmp_path / "ledger-public.pem"
    private_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private_path, public_path


def _result(record_id: str) -> dict[str, object]:
    return {
        "schema_version": "mnemosyne.leaderboard.result/v1",
        "record_id": record_id,
        "system": "mnemosyne",
        "track": "development",
        "benchmark": "synthetic-retrieval",
        "benchmark_version": "1",
        "run_commit": "0123456789abcdef0123456789abcdef01234567",
        "build_fingerprint": f"sha256:{'1' * 64}",
        "config_digest": f"sha256:{'2' * 64}",
        "bundle_digest": f"sha256:{'3' * 64}",
        "trace_index_digest": "sha256:"
        + hashlib.sha256(_TRACE_TEXT.encode()).hexdigest(),
        "metrics": [
            {
                "name": "recall_at_10",
                "family": "retrieval",
                "value": 0.75,
                "unit": "ratio",
                "confidence_interval": {"low": 0.60, "high": 0.85},
            }
        ],
        "publication": {"publishable": False, "label": "operator-run"},
        "operator_entry": {"operator": "synthetic-test", "disclosed": True},
        "history": {"supersedes": None},
    }


def _trace(path: Path) -> Path:
    path.write_text(_TRACE_TEXT, encoding="utf-8")
    return path


def _append(
    ledger: Path,
    private_key: Path,
    *,
    entry_id: str,
    entrant_id: str,
    roster: set[str],
    status: str = "succeeded",
    result: dict[str, object] | None = None,
    supersedes: str | None = None,
) -> None:
    append_entry(
        ledger,
        private_key,
        entry_id=entry_id,
        timestamp=f"2026-07-25T12:00:{len(ledger.read_bytes().splitlines()):02d}Z"
        if ledger.exists()
        else "2026-07-25T12:00:00Z",
        entrant_id=entrant_id,
        status=status,
        run_id=f"run-{entry_id}" if status not in {"no_run", "superseded"} else None,
        reason="synthetic non-success" if status != "succeeded" else None,
        result=result,
        supersedes=supersedes,
        roster=roster,
    )


def _corrupt_signature(ledger: Path) -> None:
    entries = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    entries[0]["signature"] = base64.b64encode(b"\0" * 64).decode("ascii")
    ledger.write_text(
        "".join(
            json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n"
            for entry in entries
        ),
        encoding="utf-8",
    )


def test_publishes_only_active_successes(
    tmp_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, public_key = key_paths
    ledger = tmp_path / "runs.jsonl"
    roster = {"successful", "failed"}
    _append(
        ledger,
        private_key,
        entry_id="entry-success",
        entrant_id="successful",
        roster=roster,
        result=_result("result-success"),
    )
    _append(
        ledger,
        private_key,
        entry_id="entry-failed",
        entrant_id="failed",
        roster=roster,
        status="failed",
    )
    destination = tmp_path / "site"

    publish_site(
        ledger,
        public_key,
        {"result-success": _trace(tmp_path / "trace.jsonl")},
        destination,
    )

    index = (destination / "index.html").read_text(encoding="utf-8")
    assert "result-success" in index
    assert "entry-failed" not in index


def test_publishes_multiple_active_successes(
    tmp_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, public_key = key_paths
    ledger = tmp_path / "runs.jsonl"
    roster = {"entrant-a", "entrant-b"}
    traces: dict[str, Path] = {}
    for entrant in sorted(roster):
        record_id = f"result-{entrant}"
        _append(
            ledger,
            private_key,
            entry_id=f"entry-{entrant}",
            entrant_id=entrant,
            roster=roster,
            result=_result(record_id),
        )
        traces[record_id] = _trace(tmp_path / f"{record_id}.jsonl")

    destination = tmp_path / "site"
    publish_site(ledger, public_key, traces, destination)

    index = (destination / "index.html").read_text(encoding="utf-8")
    assert "result-entrant-a" in index
    assert "result-entrant-b" in index


def test_excludes_a_superseded_success(
    tmp_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, public_key = key_paths
    ledger = tmp_path / "runs.jsonl"
    roster = {"synthetic-entrant"}
    _append(
        ledger,
        private_key,
        entry_id="entry-original",
        entrant_id="synthetic-entrant",
        roster=roster,
        result=_result("result-original"),
    )
    _append(
        ledger,
        private_key,
        entry_id="entry-correction",
        entrant_id="synthetic-entrant",
        roster=roster,
        status="superseded",
        supersedes="entry-original",
    )
    _append(
        ledger,
        private_key,
        entry_id="entry-replacement",
        entrant_id="synthetic-entrant",
        roster=roster,
        result=_result("result-replacement"),
    )
    destination = tmp_path / "site"

    publish_site(
        ledger,
        public_key,
        {"result-replacement": _trace(tmp_path / "trace.jsonl")},
        destination,
    )

    index = (destination / "index.html").read_text(encoding="utf-8")
    assert "result-replacement" in index
    assert "result-original" not in index


def test_rejects_an_invalid_signature_before_mutating_destination(
    tmp_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, public_key = key_paths
    ledger = tmp_path / "runs.jsonl"
    _append(
        ledger,
        private_key,
        entry_id="entry-success",
        entrant_id="synthetic-entrant",
        roster={"synthetic-entrant"},
        result=_result("result-success"),
    )
    _corrupt_signature(ledger)
    destination = tmp_path / "site"
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("unchanged\n", encoding="utf-8")

    with pytest.raises(PublicationError, match="signature"):
        publish_site(
            ledger,
            public_key,
            {"result-success": _trace(tmp_path / "trace.jsonl")},
            destination,
        )

    assert marker.read_text(encoding="utf-8") == "unchanged\n"
    assert sorted(destination.iterdir()) == [marker]


def test_rejects_trace_evidence_not_bound_to_the_signed_result(
    tmp_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, public_key = key_paths
    ledger = tmp_path / "runs.jsonl"
    _append(
        ledger,
        private_key,
        entry_id="entry-success",
        entrant_id="synthetic-entrant",
        roster={"synthetic-entrant"},
        result=_result("result-success"),
    )
    trace = _trace(tmp_path / "trace.jsonl")
    trace.write_text(_TRACE_TEXT.replace("doc-1", "unrelated"), encoding="utf-8")
    destination = tmp_path / "site"

    with pytest.raises(PublicationError, match="trace digest mismatch"):
        publish_site(
            ledger,
            public_key,
            {"result-success": trace},
            destination,
        )

    assert not destination.exists()


def test_renders_the_verified_trace_snapshot(
    tmp_path: Path,
    key_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key, public_key = key_paths
    ledger = tmp_path / "runs.jsonl"
    _append(
        ledger,
        private_key,
        entry_id="entry-success",
        entrant_id="synthetic-entrant",
        roster={"synthetic-entrant"},
        result=_result("result-success"),
    )
    trace = _trace(tmp_path / "trace.jsonl")

    def replace_source_then_render(
        results: str | Path,
        traces: dict[str, str | Path],
        destination: str | Path,
    ) -> None:
        trace.write_text(_TRACE_TEXT.replace("doc-1", "unrelated"), encoding="utf-8")
        render_site(results, traces, destination)

    monkeypatch.setattr(publication, "render_site", replace_source_then_render)
    destination = tmp_path / "site"
    publish_site(
        ledger,
        public_key,
        {"result-success": trace},
        destination,
    )

    result_dir = hashlib.sha256(b"result-success").hexdigest()
    trace_page = hashlib.sha256(b"question-001").hexdigest() + ".html"
    page = (destination / "traces" / result_dir / trace_page).read_text(
        encoding="utf-8"
    )
    assert "doc-1" in page
    assert "unrelated" not in page


@pytest.mark.parametrize("status", ["failed", "aborted", "discarded", "no_run"])
def test_rejects_a_verified_ledger_without_an_active_success(
    tmp_path: Path, key_paths: tuple[Path, Path], status: str
) -> None:
    private_key, public_key = key_paths
    ledger = tmp_path / "runs.jsonl"
    _append(
        ledger,
        private_key,
        entry_id=f"entry-{status}",
        entrant_id="synthetic-entrant",
        roster={"synthetic-entrant"},
        status=status,
    )

    with pytest.raises(PublicationError, match="no active successful"):
        publish_site(ledger, public_key, {}, tmp_path / "site")

    assert not (tmp_path / "site").exists()


def test_rejects_duplicate_active_result_records(
    tmp_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, public_key = key_paths
    ledger = tmp_path / "runs.jsonl"
    roster = {"entrant-a", "entrant-b"}
    for entrant in sorted(roster):
        _append(
            ledger,
            private_key,
            entry_id=f"entry-{entrant}",
            entrant_id=entrant,
            roster=roster,
            result=_result("duplicate-result"),
        )

    with pytest.raises(PublicationError, match="duplicate active result"):
        publish_site(
            ledger,
            public_key,
            {"duplicate-result": _trace(tmp_path / "trace.jsonl")},
            tmp_path / "site",
        )

    assert not (tmp_path / "site").exists()


def test_rejects_an_unlinked_trace_source(
    tmp_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, public_key = key_paths
    ledger = tmp_path / "runs.jsonl"
    _append(
        ledger,
        private_key,
        entry_id="entry-success",
        entrant_id="synthetic-entrant",
        roster={"synthetic-entrant"},
        result=_result("result-success"),
    )
    destination = tmp_path / "site"

    with pytest.raises(PublicationError, match="unlinked trace source: extra"):
        publish_site(
            ledger,
            public_key,
            {
                "result-success": _trace(tmp_path / "trace.jsonl"),
                "extra": tmp_path / "unused.jsonl",
            },
            destination,
        )

    assert not destination.exists()


def test_rejects_a_missing_trace_source(
    tmp_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, public_key = key_paths
    ledger = tmp_path / "runs.jsonl"
    _append(
        ledger,
        private_key,
        entry_id="entry-success",
        entrant_id="synthetic-entrant",
        roster={"synthetic-entrant"},
        result=_result("result-success"),
    )
    destination = tmp_path / "site"

    with pytest.raises(
        PublicationError, match="missing trace source: result-success"
    ):
        publish_site(ledger, public_key, {}, destination)

    assert not destination.exists()


def test_cli_publishes_valid_input_and_reports_invalid_input_without_traceback(
    tmp_path: Path,
    key_paths: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_key, public_key = key_paths
    ledger = tmp_path / "runs.jsonl"
    _append(
        ledger,
        private_key,
        entry_id="entry-success",
        entrant_id="synthetic-entrant",
        roster={"synthetic-entrant"},
        result=_result("result-success"),
    )
    traces = _trace(tmp_path / "trace.jsonl")
    mapping = f"result-success={traces}"

    assert main([str(ledger), str(public_key), str(tmp_path / "site"), mapping]) == 0
    assert (tmp_path / "site" / "index.html").is_file()

    _corrupt_signature(ledger)
    assert (
        main([str(ledger), str(public_key), str(tmp_path / "other-site"), mapping])
        == 2
    )
    error = capsys.readouterr().err
    assert error.startswith("error: ")
    assert "signature" in error
    assert "Traceback" not in error
    assert not (tmp_path / "other-site").exists()


def test_cli_reports_usage_for_too_few_arguments(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([]) == 2
    assert capsys.readouterr().err == (
        "usage: python -m leaderboard.publish "
        "LEDGER PUBLIC_KEY DESTINATION RECORD_ID=TRACES [...]\n"
    )


@pytest.mark.parametrize(
    "mappings",
    [
        ["missing-separator"],
        ["=trace.jsonl"],
        ["result="],
        ["result=one.jsonl", "result=two.jsonl"],
    ],
)
def test_cli_rejects_invalid_trace_mappings_without_mutating_destination(
    tmp_path: Path,
    key_paths: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    mappings: list[str],
) -> None:
    private_key, public_key = key_paths
    ledger = tmp_path / "runs.jsonl"
    _append(
        ledger,
        private_key,
        entry_id="entry-success",
        entrant_id="synthetic-entrant",
        roster={"synthetic-entrant"},
        result=_result("result-success"),
    )
    destination = tmp_path / "site"

    assert main([str(ledger), str(public_key), str(destination), *mappings]) == 2

    error = capsys.readouterr().err
    assert error.startswith("error: invalid trace mapping: ")
    assert "Traceback" not in error
    assert not destination.exists()


def _v2_bound_result(tmp_path: Path, record: dict[str, object]) -> dict[str, Path]:
    payloads = {
        "build.json": b'{"build":true}\n',
        "config.json": b'{"config":true}\n',
        "bundle-manifest.json": b'{"bundle":true}\n',
        "traces.jsonl": _TRACE_TEXT.encode(),
    }
    paths: dict[str, Path] = {}
    for name, content in payloads.items():
        path = tmp_path / name
        path.write_bytes(content)
        paths[name] = path
    for field, name in DIGEST_PAYLOAD_NAMES.items():
        record[field] = "sha256:" + hashlib.sha256(payloads[name]).hexdigest()
    return paths


def test_publishes_v2_after_verifying_four_digest_payloads(
    tmp_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, public_key = key_paths
    ledger = tmp_path / "runs.jsonl"
    record = _v2_development_record()
    artifacts = _v2_bound_result(tmp_path, record)
    _append(
        ledger,
        private_key,
        entry_id="entry-v2",
        entrant_id="synthetic-entrant",
        roster={"synthetic-entrant"},
        result=record,
    )
    destination = tmp_path / "site"

    publish_site(
        ledger,
        public_key,
        {str(record["record_id"]): artifacts["traces.jsonl"]},
        destination,
        artifacts={
            str(record["record_id"]): {
                "build": artifacts["build.json"],
                "config": artifacts["config.json"],
                "bundle": artifacts["bundle-manifest.json"],
            }
        },
    )

    index = (destination / "index.html").read_text(encoding="utf-8")
    assert str(record["record_id"]) in index
    assert "DEVELOPMENT" in index


def test_rejects_v2_publish_on_digest_mismatch(
    tmp_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, public_key = key_paths
    ledger = tmp_path / "runs.jsonl"
    record = _v2_development_record()
    artifacts = _v2_bound_result(tmp_path, record)
    artifacts["config.json"].write_bytes(b'{"config":false}\n')
    _append(
        ledger,
        private_key,
        entry_id="entry-v2",
        entrant_id="synthetic-entrant",
        roster={"synthetic-entrant"},
        result=record,
    )

    with pytest.raises(PublicationError, match="digest"):
        publish_site(
            ledger,
            public_key,
            {str(record["record_id"]): artifacts["traces.jsonl"]},
            tmp_path / "site",
            artifacts={
                str(record["record_id"]): {
                    "build": artifacts["build.json"],
                    "config": artifacts["config.json"],
                    "bundle": artifacts["bundle-manifest.json"],
                }
            },
        )
    assert not (tmp_path / "site").exists()


def test_rejects_mixed_v1_and_v2_publication(
    tmp_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, public_key = key_paths
    ledger = tmp_path / "runs.jsonl"
    roster = {"entrant-a", "entrant-b"}
    v2 = _v2_development_record()
    artifacts = _v2_bound_result(tmp_path, v2)
    _append(
        ledger,
        private_key,
        entry_id="entry-v1",
        entrant_id="entrant-a",
        roster=roster,
        result=_result("result-v1"),
    )
    _append(
        ledger,
        private_key,
        entry_id="entry-v2",
        entrant_id="entrant-b",
        roster=roster,
        result=v2,
    )

    with pytest.raises(PublicationError, match="mixed result schema"):
        publish_site(
            ledger,
            public_key,
            {
                "result-v1": _trace(tmp_path / "v1.jsonl"),
                str(v2["record_id"]): artifacts["traces.jsonl"],
            },
            tmp_path / "site",
            artifacts={
                str(v2["record_id"]): {
                    "build": artifacts["build.json"],
                    "config": artifacts["config.json"],
                    "bundle": artifacts["bundle-manifest.json"],
                }
            },
        )
    assert not (tmp_path / "site").exists()


def test_publishes_only_active_v2_after_v1_supersession(
    tmp_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, public_key = key_paths
    ledger = tmp_path / "runs.jsonl"
    roster = {"synthetic-entrant"}
    original_bytes_path = tmp_path / "original.jsonl"
    _append(
        ledger,
        private_key,
        entry_id="entry-v1",
        entrant_id="synthetic-entrant",
        roster=roster,
        result=_result("result-v1"),
    )
    original_bytes_path.write_bytes(ledger.read_bytes())
    _append(
        ledger,
        private_key,
        entry_id="entry-v1-superseded",
        entrant_id="synthetic-entrant",
        roster=roster,
        status="superseded",
        supersedes="entry-v1",
    )
    successor = _v2_successor_record()
    artifacts = _v2_bound_result(tmp_path, successor)
    _append(
        ledger,
        private_key,
        entry_id="entry-v2",
        entrant_id="synthetic-entrant",
        roster=roster,
        result=successor,
    )
    destination = tmp_path / "site"

    publish_site(
        ledger,
        public_key,
        {str(successor["record_id"]): artifacts["traces.jsonl"]},
        destination,
        artifacts={
            str(successor["record_id"]): {
                "build": artifacts["build.json"],
                "config": artifacts["config.json"],
                "bundle": artifacts["bundle-manifest.json"],
            }
        },
    )

    assert ledger.read_bytes().startswith(original_bytes_path.read_bytes())
    index = (destination / "index.html").read_text(encoding="utf-8")
    assert str(successor["record_id"]) in index
    assert "result-v1" not in index
