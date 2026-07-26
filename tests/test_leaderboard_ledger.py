import copy
import base64
import fcntl
import json
import multiprocessing
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from leaderboard.ledger import LedgerError, append_entry, verify_ledger


_DEFAULT_RUN_ID = object()


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


@pytest.fixture
def ledger_path(tmp_path: Path) -> Path:
    return tmp_path / "runs.jsonl"


def _result(record_id: str = "synthetic-result-001") -> dict[str, object]:
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
        "trace_index_digest": f"sha256:{'4' * 64}",
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


def _append(
    ledger_path: Path,
    private_key_path: Path,
    *,
    entry_id: str,
    status: str = "succeeded",
    entrant_id: str = "synthetic-entrant",
    run_id: str | None | object = _DEFAULT_RUN_ID,
    reason: str | None = None,
    result: dict[str, object] | None = None,
    supersedes: str | None = None,
) -> dict[str, object]:
    return append_entry(
        ledger_path,
        private_key_path,
        entry_id=entry_id,
        timestamp="2026-07-25T12:00:00Z",
        entrant_id=entrant_id,
        status=status,
        run_id=f"run-{entry_id}" if run_id is _DEFAULT_RUN_ID else run_id,
        reason=reason,
        result=_result(f"result-{entry_id}") if status == "succeeded" and result is None else result,
        supersedes=supersedes,
        roster={"synthetic-entrant"},
    )


@pytest.mark.parametrize("status", ["succeeded", "failed", "aborted", "discarded"])
def test_accepts_run_outcomes(
    ledger_path: Path, key_paths: tuple[Path, Path], status: str
) -> None:
    private_key, public_key = key_paths
    entry = _append(
        ledger_path,
        private_key,
        entry_id=f"entry-{status}",
        status=status,
        reason=None if status == "succeeded" else f"synthetic {status}",
    )

    assert verify_ledger(ledger_path, public_key) == [entry]


def test_writes_canonical_newline_terminated_jsonl(
    ledger_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, _ = key_paths
    entry = _append(ledger_path, private_key, entry_id="entry-canonical")

    raw = ledger_path.read_bytes()
    assert raw.endswith(b"\n")
    assert raw == (
        json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode()


def test_verify_rejects_noncanonical_json_bytes(
    ledger_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, public_key = key_paths
    entry = _append(ledger_path, private_key, entry_id="entry-noncanonical")
    ledger_path.write_text(json.dumps(entry, sort_keys=False, separators=(", ", ": ")) + "\n")

    with pytest.raises(LedgerError, match="non-canonical"):
        verify_ledger(ledger_path, public_key)


def test_verify_rejects_crlf_ledger_bytes(
    ledger_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, public_key = key_paths
    _append(ledger_path, private_key, entry_id="entry-crlf")
    ledger_path.write_bytes(ledger_path.read_bytes().replace(b"\n", b"\r\n"))

    with pytest.raises(LedgerError, match="non-canonical"):
        verify_ledger(ledger_path, public_key)


@pytest.mark.parametrize(
    "timestamp",
    [
        "tomorrow",
        "2026-07-25 12:00:00Z",
        "2026-07-25T12:00:00+00:00",
        "2026-02-30T12:00:00Z",
    ],
)
def test_rejects_invalid_or_noncanonical_utc_timestamps(
    ledger_path: Path,
    key_paths: tuple[Path, Path],
    timestamp: str,
) -> None:
    private_key, _ = key_paths

    with pytest.raises(LedgerError, match="timestamp"):
        append_entry(
            ledger_path,
            private_key,
            entry_id="entry-invalid-timestamp",
            timestamp=timestamp,
            entrant_id="synthetic-entrant",
            status="failed",
            run_id="run-invalid-timestamp",
            reason="synthetic failure",
            roster={"synthetic-entrant"},
        )


def test_builds_contiguous_sequence_and_hash_links_with_signatures(
    ledger_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, public_key = key_paths
    first = _append(ledger_path, private_key, entry_id="entry-001")
    second = _append(ledger_path, private_key, entry_id="entry-002")

    assert first["sequence"] == 0
    assert second["sequence"] == 1
    assert first["previous_digest"] == f"sha256:{'0' * 64}"
    assert second["previous_digest"] == first["entry_digest"]
    assert all(entry["signature"] for entry in (first, second))
    assert all(entry["signer_key_fingerprint"] for entry in (first, second))
    assert verify_ledger(ledger_path, public_key) == [first, second]


@pytest.mark.parametrize("status", ["failed", "aborted", "discarded", "no_run"])
@pytest.mark.parametrize("reason", [None, "", "   "])
def test_requires_reason_for_non_success_and_recorded_absence(
    ledger_path: Path,
    key_paths: tuple[Path, Path],
    status: str,
    reason: str | None,
) -> None:
    private_key, _ = key_paths

    with pytest.raises(LedgerError, match="reason"):
        _append(
            ledger_path,
            private_key,
            entry_id=f"entry-{status}",
            status=status,
            reason=reason,
            result=None,
        )


@pytest.mark.parametrize("status", ["succeeded", "failed", "aborted", "discarded"])
@pytest.mark.parametrize("run_id", [None, "", "   "])
def test_requires_run_id_for_actual_run_outcomes(
    ledger_path: Path,
    key_paths: tuple[Path, Path],
    status: str,
    run_id: str | None,
) -> None:
    private_key, _ = key_paths

    with pytest.raises(LedgerError, match="run_id"):
        _append(
            ledger_path,
            private_key,
            entry_id=f"entry-{status}",
            status=status,
            run_id=run_id,
            reason=None if status == "succeeded" else "synthetic failure",
        )


def test_accepts_recorded_absence_without_fabricating_a_run(
    ledger_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, public_key = key_paths
    entry = append_entry(
        ledger_path,
        private_key,
        entry_id="entry-no-run",
        timestamp="2026-07-25T12:00:00Z",
        entrant_id="rostered-entrant",
        status="no_run",
        reason="adapter unavailable",
        roster={"rostered-entrant"},
    )

    assert entry["run_id"] is None
    assert entry["result"] is None
    assert verify_ledger(ledger_path, public_key) == [entry]


def test_recorded_absence_is_bound_to_complete_preregistered_roster(
    ledger_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, public_key = key_paths
    append_entry(
        ledger_path,
        private_key,
        entry_id="entry-no-run",
        timestamp="2026-07-25T12:00:00Z",
        entrant_id="synthetic-entrant",
        status="no_run",
        reason="entrant was pre-registered but not run",
        roster={"synthetic-entrant", "omitted-entrant"},
    )

    with pytest.raises(LedgerError, match="omitted-entrant"):
        verify_ledger(ledger_path, public_key)


def test_rejects_entrant_absent_from_preregistered_roster(
    ledger_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, _ = key_paths

    with pytest.raises(LedgerError, match="pre-registered roster"):
        append_entry(
            ledger_path,
            private_key,
            entry_id="entry-fabricated",
            timestamp="2026-07-25T12:00:00Z",
            entrant_id="fabricated-entrant",
            status="no_run",
            reason="fabricated absence",
            roster={"actual-entrant"},
        )


def test_rejects_invalid_success_result(
    ledger_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, _ = key_paths
    invalid = _result()
    del invalid["bundle_digest"]

    with pytest.raises(LedgerError, match="/bundle_digest"):
        _append(
            ledger_path,
            private_key,
            entry_id="entry-invalid-result",
            result=invalid,
        )


def test_supersession_appends_without_rewriting_history(
    ledger_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, public_key = key_paths
    original = _append(ledger_path, private_key, entry_id="entry-original")
    original_bytes = ledger_path.read_bytes()
    correction = append_entry(
        ledger_path,
        private_key,
        entry_id="entry-correction",
        timestamp="2026-07-25T12:01:00Z",
        entrant_id="synthetic-entrant",
        status="superseded",
        reason="result metadata was incorrect",
        supersedes="entry-original",
        roster={"synthetic-entrant"},
    )

    assert ledger_path.read_bytes().startswith(original_bytes)
    assert correction["supersedes"] == original["entry_id"]
    assert verify_ledger(ledger_path, public_key) == [original, correction]


def test_rejects_cross_entrant_supersession(
    ledger_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, _ = key_paths
    append_entry(
        ledger_path,
        private_key,
        entry_id="entry-a",
        timestamp="2026-07-25T12:00:00Z",
        entrant_id="entrant-a",
        status="failed",
        run_id="run-a",
        reason="synthetic failure",
        roster={"entrant-a", "entrant-b"},
    )

    with pytest.raises(LedgerError, match="same entrant"):
        append_entry(
            ledger_path,
            private_key,
            entry_id="entry-b-correction",
            timestamp="2026-07-25T12:01:00Z",
            entrant_id="entrant-b",
            status="superseded",
            reason="cross-entrant correction",
            supersedes="entry-a",
            roster={"entrant-a", "entrant-b"},
        )


@pytest.mark.parametrize(
    ("target", "match"),
    [
        ("missing-entry", "unknown supersession"),
        ("entry-correction", "self"),
    ],
)
def test_rejects_unknown_or_self_supersession(
    ledger_path: Path,
    key_paths: tuple[Path, Path],
    target: str,
    match: str,
) -> None:
    private_key, _ = key_paths
    _append(ledger_path, private_key, entry_id="entry-original")

    with pytest.raises(LedgerError, match=match):
        append_entry(
            ledger_path,
            private_key,
            entry_id="entry-correction",
            timestamp="2026-07-25T12:01:00Z",
            entrant_id="synthetic-entrant",
            status="superseded",
            reason="synthetic correction",
            supersedes=target,
            roster={"synthetic-entrant"},
        )


def test_rejects_repeated_supersession(
    ledger_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, _ = key_paths
    _append(ledger_path, private_key, entry_id="entry-original")
    append_entry(
        ledger_path,
        private_key,
        entry_id="entry-correction-1",
        timestamp="2026-07-25T12:01:00Z",
        entrant_id="synthetic-entrant",
        status="superseded",
        reason="first correction",
        supersedes="entry-original",
        roster={"synthetic-entrant"},
    )

    with pytest.raises(LedgerError, match="already superseded"):
        append_entry(
            ledger_path,
            private_key,
            entry_id="entry-correction-2",
            timestamp="2026-07-25T12:02:00Z",
            entrant_id="synthetic-entrant",
            status="superseded",
            reason="second correction",
            supersedes="entry-original",
            roster={"synthetic-entrant"},
        )


def _rewrite_entries(ledger_path: Path, entries: list[dict[str, object]]) -> None:
    ledger_path.write_text(
        "".join(
            json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n"
            for entry in entries
        )
    )


def _resign_entries_and_head(
    ledger_path: Path,
    private_key_path: Path,
    entries: list[dict[str, object]],
) -> None:
    from leaderboard import ledger

    private_key = ledger.load_private_key(private_key_path)
    previous_digest = ledger.GENESIS_DIGEST
    for entry in entries:
        entry["previous_digest"] = previous_digest
        entry["entry_digest"] = ledger._digest(entry)
        entry["signature"] = base64.b64encode(
            private_key.sign(ledger._signed_bytes(entry))
        ).decode("ascii")
        previous_digest = str(entry["entry_digest"])
    _rewrite_entries(ledger_path, entries)

    head_path = ledger_path.with_suffix(ledger_path.suffix + ".head.json")
    head = json.loads(head_path.read_bytes())
    head["sequence"] = entries[-1]["sequence"]
    head["entry_digest"] = entries[-1]["entry_digest"]
    head["signature"] = base64.b64encode(
        private_key.sign(ledger._signed_bytes(head))
    ).decode("ascii")
    head_path.write_bytes(ledger._canonical(head) + b"\n")


def test_verification_rejects_boolean_sequence(
    ledger_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, public_key = key_paths
    entries = [_append(ledger_path, private_key, entry_id="entry-boolean-sequence")]
    entries[0]["sequence"] = False
    _resign_entries_and_head(ledger_path, private_key, entries)

    with pytest.raises(LedgerError, match="sequence"):
        verify_ledger(ledger_path, public_key)


def test_verification_rejects_off_roster_supersession(
    ledger_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, public_key = key_paths
    original = _append(ledger_path, private_key, entry_id="entry-original")
    correction = append_entry(
        ledger_path,
        private_key,
        entry_id="entry-correction",
        timestamp="2026-07-25T12:01:00Z",
        entrant_id="synthetic-entrant",
        status="superseded",
        reason="synthetic correction",
        supersedes="entry-original",
        roster={"synthetic-entrant"},
    )
    entries = [original, correction]
    entries[0]["entrant_id"] = "off-roster-entrant"
    entries[1]["entrant_id"] = "off-roster-entrant"
    _resign_entries_and_head(ledger_path, private_key, entries)

    with pytest.raises(LedgerError, match="pre-registered roster"):
        verify_ledger(ledger_path, public_key)


def test_verification_rejects_missing_ledger_and_head(
    ledger_path: Path, key_paths: tuple[Path, Path]
) -> None:
    _, public_key = key_paths

    with pytest.raises(LedgerError, match="missing"):
        verify_ledger(ledger_path, public_key)


def _seed_three_entries(
    ledger_path: Path, private_key: Path
) -> list[dict[str, object]]:
    return [
        _append(ledger_path, private_key, entry_id=f"entry-{index:03d}")
        for index in range(3)
    ]


@pytest.mark.parametrize(
    ("tamper", "match"),
    [
        (lambda entries: entries[0].update(entrant_id="mutated"), "digest"),
        (lambda entries: entries.pop(1), "sequence|link"),
        (lambda entries: entries.reverse(), "sequence"),
        (
            lambda entries: entries[1].update(entry_id=entries[0]["entry_id"]),
            "duplicate",
        ),
        (
            lambda entries: entries[0]["result"].pop("bundle_digest"),
            "result|bundle_digest",
        ),
    ],
)
def test_verification_rejects_tampering(
    ledger_path: Path,
    key_paths: tuple[Path, Path],
    tamper: Callable[[list[dict[str, object]]], object],
    match: str,
) -> None:
    private_key, public_key = key_paths
    entries = copy.deepcopy(_seed_three_entries(ledger_path, private_key))
    tamper(entries)
    _rewrite_entries(ledger_path, entries)

    with pytest.raises(LedgerError, match=match):
        verify_ledger(ledger_path, public_key)


def test_verification_rejects_deleted_final_entry(
    ledger_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, public_key = key_paths
    _seed_three_entries(ledger_path, private_key)
    lines = ledger_path.read_bytes().splitlines(keepends=True)
    ledger_path.write_bytes(b"".join(lines[:-1]))

    with pytest.raises(LedgerError, match="head"):
        verify_ledger(ledger_path, public_key)


def test_rejects_duplicate_entry_id_on_append(
    ledger_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, _ = key_paths
    _append(ledger_path, private_key, entry_id="entry-duplicate")

    with pytest.raises(LedgerError, match="duplicate"):
        _append(ledger_path, private_key, entry_id="entry-duplicate")


def test_verification_rejects_wrong_public_key(
    ledger_path: Path, key_paths: tuple[Path, Path], tmp_path: Path
) -> None:
    private_key, _ = key_paths
    _append(ledger_path, private_key, entry_id="entry-signed")
    wrong_key = Ed25519PrivateKey.generate().public_key()
    wrong_public_path = tmp_path / "wrong-public.pem"
    wrong_public_path.write_bytes(
        wrong_key.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )

    with pytest.raises(LedgerError, match="key fingerprint|signature"):
        verify_ledger(ledger_path, wrong_public_path)


def test_append_repairs_only_a_torn_final_fragment(
    ledger_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, public_key = key_paths
    first = _append(ledger_path, private_key, entry_id="entry-complete")
    acknowledged = ledger_path.read_bytes()
    pending_path = ledger_path.with_suffix(ledger_path.suffix + ".pending.json")
    pending_path.write_text('{"prior_count":1}\n')
    ledger_path.write_bytes(acknowledged + b'{"entry_id":"unacknowledged')

    second = _append(ledger_path, private_key, entry_id="entry-after-repair")

    assert ledger_path.read_bytes().startswith(acknowledged)
    assert verify_ledger(ledger_path, public_key) == [first, second]


def test_append_preserves_a_torn_acknowledged_entry_without_pending_intent(
    ledger_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, _ = key_paths
    _append(ledger_path, private_key, entry_id="entry-acknowledged")
    torn = ledger_path.read_bytes()[:-10]
    ledger_path.write_bytes(torn)

    with pytest.raises(LedgerError, match="torn final fragment"):
        _append(ledger_path, private_key, entry_id="entry-rejected")

    assert ledger_path.read_bytes() == torn


def test_append_rejects_complete_final_entry_missing_only_newline(
    ledger_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, _ = key_paths
    _append(ledger_path, private_key, entry_id="entry-complete")
    without_newline = ledger_path.read_bytes().removesuffix(b"\n")
    ledger_path.write_bytes(without_newline)

    with pytest.raises(LedgerError, match="unterminated"):
        _append(ledger_path, private_key, entry_id="entry-rejected")

    assert ledger_path.read_bytes() == without_newline


def _append_after_start(
    ledger_path: str,
    private_key: str,
    started: Any,
    start: Any,
) -> None:
    started.set()
    start.wait()
    append_entry(
        Path(ledger_path),
        Path(private_key),
        entry_id="entry-concurrent",
        timestamp="2026-07-25T12:00:00Z",
        entrant_id="synthetic-entrant",
        status="failed",
        run_id="run-concurrent",
        reason="synthetic failure",
        roster={"synthetic-entrant"},
    )


def _verify_after_start(
    ledger_path: str,
    public_key: str,
    started: Any,
    result: Any,
) -> None:
    started.set()
    result.put(len(verify_ledger(Path(ledger_path), Path(public_key))))


def test_append_serializes_on_sibling_process_lock(
    ledger_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, public_key = key_paths
    context = multiprocessing.get_context("spawn")
    started = context.Event()
    start = context.Event()
    process = context.Process(
        target=_append_after_start,
        args=(str(ledger_path), str(private_key), started, start),
    )
    lock_path = ledger_path.with_suffix(ledger_path.suffix + ".lock")
    lock_path.touch()

    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        process.start()
        assert started.wait(timeout=5)
        start.set()
        process.join(timeout=1)
        assert process.is_alive()
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    process.join(timeout=5)
    assert process.exitcode == 0
    assert len(verify_ledger(ledger_path, public_key)) == 1


def test_verify_serializes_on_sibling_process_lock(
    ledger_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, public_key = key_paths
    _append(ledger_path, private_key, entry_id="entry-existing")
    context = multiprocessing.get_context("spawn")
    started = context.Event()
    result = context.Queue()
    process = context.Process(
        target=_verify_after_start,
        args=(str(ledger_path), str(public_key), started, result),
    )
    lock_path = ledger_path.with_suffix(ledger_path.suffix + ".lock")

    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        process.start()
        assert started.wait(timeout=5)
        process.join(timeout=1)
        assert process.is_alive()
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    process.join(timeout=5)
    assert process.exitcode == 0
    assert result.get(timeout=1) == 1


def test_append_reports_fsync_failure_without_rewriting_prefix(
    ledger_path: Path,
    key_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key, _ = key_paths
    _append(ledger_path, private_key, entry_id="entry-complete")
    acknowledged = ledger_path.read_bytes()

    def fail_fsync(_fd: int) -> None:
        raise OSError("synthetic fsync failure")

    monkeypatch.setattr(os, "fsync", fail_fsync)
    with pytest.raises(LedgerError, match="durably appended"):
        _append(ledger_path, private_key, entry_id="entry-unacknowledged")

    assert ledger_path.read_bytes().startswith(acknowledged)


def test_append_recovers_complete_entry_left_before_head_commit(
    ledger_path: Path,
    key_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key, public_key = key_paths
    first = _append(ledger_path, private_key, entry_id="entry-complete")
    from leaderboard import ledger

    write_head = ledger._write_head

    def fail_write_head(*_args: object, **_kwargs: object) -> None:
        raise LedgerError("synthetic head failure")

    monkeypatch.setattr(ledger, "_write_head", fail_write_head)
    with pytest.raises(LedgerError, match="head failure"):
        _append(ledger_path, private_key, entry_id="entry-unacknowledged")

    monkeypatch.setattr(ledger, "_write_head", write_head)
    second = _append(ledger_path, private_key, entry_id="entry-after-recovery")

    assert verify_ledger(ledger_path, public_key) == [first, second]


@pytest.mark.parametrize(
    ("field", "value"),
    [("status", []), ("status", {})],
)
def test_verification_rejects_unhashable_fields_with_ledger_error(
    ledger_path: Path,
    key_paths: tuple[Path, Path],
    field: str,
    value: object,
) -> None:
    private_key, public_key = key_paths
    entries = [_append(ledger_path, private_key, entry_id="entry-malformed")]
    entries[0][field] = value
    _rewrite_entries(ledger_path, entries)

    with pytest.raises(LedgerError, match=field):
        verify_ledger(ledger_path, public_key)


def test_append_rejects_corruption_in_acknowledged_bytes(
    ledger_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, _ = key_paths
    _append(ledger_path, private_key, entry_id="entry-complete")
    ledger_path.write_bytes(b"not-json\n")

    with pytest.raises(LedgerError, match="invalid JSON"):
        _append(ledger_path, private_key, entry_id="entry-rejected")

    assert ledger_path.read_bytes() == b"not-json\n"


def test_module_verify_command_has_deterministic_exit_status(
    ledger_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, public_key = key_paths
    _append(ledger_path, private_key, entry_id="entry-cli")

    command = [
        sys.executable,
        "-m",
        "leaderboard.ledger",
        "verify",
        str(ledger_path),
        str(public_key),
    ]
    valid = subprocess.run(command, capture_output=True, text=True, check=False)
    ledger_path.write_bytes(ledger_path.read_bytes().replace(b"synthetic-entrant", b"mutated-entrant"))
    invalid = subprocess.run(command, capture_output=True, text=True, check=False)

    assert valid.returncode == 0
    assert valid.stdout == "verified 1 ledger entry\n"
    assert valid.stderr == ""
    assert invalid.returncode == 1
    assert invalid.stdout == ""
    assert invalid.stderr.startswith("ledger verification failed: ")


def test_module_verify_command_handles_unhashable_status(
    ledger_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, public_key = key_paths
    entries = [_append(ledger_path, private_key, entry_id="entry-cli")]
    entries[0]["status"] = []
    _rewrite_entries(ledger_path, entries)

    invalid = subprocess.run(
        [
            sys.executable,
            "-m",
            "leaderboard.ledger",
            "verify",
            str(ledger_path),
            str(public_key),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert invalid.returncode == 1
    assert invalid.stdout == ""
    assert invalid.stderr == "ledger verification failed: ledger status is invalid at entry entry-cli\n"
