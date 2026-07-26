import copy
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from leaderboard.ledger import LedgerError, append_entry, verify_ledger


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
    run_id: str | None = None,
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
        run_id=run_id or f"run-{entry_id}",
        reason=reason,
        result=_result(f"result-{entry_id}") if status == "succeeded" and result is None else result,
        supersedes=supersedes,
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
    )

    assert entry["run_id"] is None
    assert entry["result"] is None
    assert verify_ledger(ledger_path, public_key) == [entry]


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
    )

    assert ledger_path.read_bytes().startswith(original_bytes)
    assert correction["supersedes"] == original["entry_id"]
    assert verify_ledger(ledger_path, public_key) == [original, correction]


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
        )


def test_rejects_repeated_supersession(
    ledger_path: Path, key_paths: tuple[Path, Path]
) -> None:
    private_key, _ = key_paths
    _append(ledger_path, private_key, entry_id="entry-original")
    for entry_id in ("entry-correction-1", "entry-correction-2"):
        if entry_id.endswith("2"):
            with pytest.raises(LedgerError, match="already superseded"):
                append_entry(
                    ledger_path,
                    private_key,
                    entry_id=entry_id,
                    timestamp="2026-07-25T12:02:00Z",
                    entrant_id="synthetic-entrant",
                    status="superseded",
                    reason="second correction",
                    supersedes="entry-original",
                )
        else:
            append_entry(
                ledger_path,
                private_key,
                entry_id=entry_id,
                timestamp="2026-07-25T12:01:00Z",
                entrant_id="synthetic-entrant",
                status="superseded",
                reason="first correction",
                supersedes="entry-original",
            )


def _rewrite_entries(ledger_path: Path, entries: list[dict[str, object]]) -> None:
    ledger_path.write_text(
        "".join(
            json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n"
            for entry in entries
        )
    )


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
