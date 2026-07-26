"""Signed append-only JSONL ledger for leaderboard run outcomes."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature

from leaderboard.validate import validate_record
from mnemosyne.evidence_signing import (
    EvidenceSignatureError,
    _public_key_sha256,
    load_private_key,
    load_public_key,
)
from mnemosyne.journal import _fsync_dir

GENESIS_DIGEST = "sha256:" + "0" * 64
STATUSES = {"succeeded", "failed", "aborted", "discarded", "no_run", "superseded"}


class LedgerError(ValueError):
    """Raised when ledger input or verification fails closed."""


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise LedgerError("ledger entry is not canonical JSON data") from exc


def _digest(entry: dict[str, object]) -> str:
    unsigned = {key: value for key, value in entry.items() if key not in {"entry_digest", "signature"}}
    return "sha256:" + sha256(_canonical(unsigned)).hexdigest()


def _signed_bytes(entry: dict[str, object]) -> bytes:
    return _canonical({key: value for key, value in entry.items() if key != "signature"})


def _load_entries(path: Path, *, repair_torn_tail: bool = False) -> list[dict[str, object]]:
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise LedgerError("ledger could not be read") from exc

    if data and not data.endswith(b"\n"):
        if not repair_torn_tail:
            raise LedgerError("ledger has an unacknowledged torn final fragment")
        keep = data.rfind(b"\n") + 1
        try:
            with path.open("r+b") as handle:
                handle.truncate(keep)
                handle.flush()
                os.fsync(handle.fileno())
            _fsync_dir(path.parent)
        except OSError as exc:
            raise LedgerError("ledger torn final fragment could not be repaired") from exc
        data = data[:keep]

    entries: list[dict[str, object]] = []
    for index, raw in enumerate(data.splitlines(), start=1):
        try:
            entry = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise LedgerError(f"ledger line {index} contains invalid JSON") from exc
        if not isinstance(entry, dict):
            raise LedgerError(f"ledger line {index} must be a JSON object")
        entries.append(entry)
    return entries


def _validate_entry(
    entry: dict[str, object],
    *,
    sequence: int,
    previous_digest: str,
    seen_ids: set[str],
    superseded_ids: set[str],
) -> None:
    required = {
        "entry_id",
        "timestamp",
        "entrant_id",
        "status",
        "run_id",
        "reason",
        "result",
        "supersedes",
        "sequence",
        "previous_digest",
        "entry_digest",
        "signer_key_fingerprint",
        "signature",
    }
    if set(entry) != required:
        raise LedgerError("ledger entry fields are invalid")
    entry_id = entry["entry_id"]
    if not isinstance(entry_id, str) or not entry_id.strip():
        raise LedgerError("ledger entry_id is required")
    if entry_id in seen_ids:
        raise LedgerError(f"duplicate ledger entry_id: {entry_id}")
    for field in ("timestamp", "entrant_id"):
        value = entry[field]
        if not isinstance(value, str) or not value.strip():
            raise LedgerError(f"ledger {field} is required")
    if entry["sequence"] != sequence:
        raise LedgerError(f"ledger sequence is not contiguous at entry {entry_id}")
    if entry["previous_digest"] != previous_digest:
        raise LedgerError(f"ledger hash link is invalid at entry {entry_id}")

    status = entry["status"]
    if status not in STATUSES:
        raise LedgerError(f"ledger status is invalid at entry {entry_id}")
    reason = entry["reason"]
    if status != "succeeded" and (not isinstance(reason, str) or not reason.strip()):
        raise LedgerError(f"ledger reason is required for status {status}")
    if status == "succeeded":
        if reason is not None:
            raise LedgerError("ledger reason must be null for succeeded entries")
        errors = validate_record(entry["result"])
        if errors:
            raise LedgerError("ledger result is invalid: " + ", ".join(errors))
        if not isinstance(entry["run_id"], str) or not entry["run_id"].strip():
            raise LedgerError("ledger run_id is required for succeeded entries")
    elif entry["result"] is not None:
        raise LedgerError(f"ledger result must be null for status {status}")
    if status == "no_run" and entry["run_id"] is not None:
        raise LedgerError("ledger run_id must be null for no_run entries")

    target = entry["supersedes"]
    if status == "superseded":
        if not isinstance(target, str) or not target:
            raise LedgerError("ledger superseded entry requires a supersedes target")
        if target == entry_id:
            raise LedgerError("ledger entry cannot supersede itself")
        if target not in seen_ids:
            raise LedgerError(f"unknown supersession target: {target}")
        if target in superseded_ids:
            raise LedgerError(f"ledger entry is already superseded: {target}")
        superseded_ids.add(target)
    elif target is not None:
        raise LedgerError(f"ledger supersedes must be null for status {status}")


def verify_ledger(ledger_path: Path, public_key_path: Path) -> list[dict[str, object]]:
    """Verify every entry, link, digest, and signature in a ledger."""
    try:
        public_key = load_public_key(Path(public_key_path))
    except EvidenceSignatureError as exc:
        raise LedgerError("ledger public key could not be loaded") from exc
    expected_fingerprint = _public_key_sha256(public_key)
    entries = _load_entries(Path(ledger_path))
    _verify_entries(entries, public_key, expected_fingerprint)
    return entries


def append_entry(
    ledger_path: Path,
    private_key_path: Path,
    *,
    entry_id: str,
    timestamp: str,
    entrant_id: str,
    status: str,
    run_id: str | None = None,
    reason: str | None = None,
    result: dict[str, object] | None = None,
    supersedes: str | None = None,
) -> dict[str, object]:
    """Validate, sign, durably append, and return one ledger entry."""
    path = Path(ledger_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = _load_entries(path, repair_torn_tail=True)
    try:
        private_key = load_private_key(Path(private_key_path))
    except EvidenceSignatureError as exc:
        raise LedgerError("ledger private key could not be loaded") from exc
    public_key = private_key.public_key()
    if entries:
        # Verification with the signing key prevents appending after acknowledged corruption.
        _verify_entries(entries, public_key, _public_key_sha256(public_key))

    entry: dict[str, object] = {
        "entry_id": entry_id,
        "timestamp": timestamp,
        "entrant_id": entrant_id,
        "status": status,
        "run_id": run_id,
        "reason": reason,
        "result": result,
        "supersedes": supersedes,
        "sequence": len(entries),
        "previous_digest": entries[-1]["entry_digest"] if entries else GENESIS_DIGEST,
        "entry_digest": "",
        "signer_key_fingerprint": _public_key_sha256(public_key),
        "signature": "",
    }
    seen_ids = {str(existing["entry_id"]) for existing in entries}
    superseded_ids = {
        str(existing["supersedes"])
        for existing in entries
        if existing["status"] == "superseded"
    }
    _validate_entry(
        entry,
        sequence=len(entries),
        previous_digest=str(entry["previous_digest"]),
        seen_ids=seen_ids,
        superseded_ids=superseded_ids,
    )
    entry["entry_digest"] = _digest(entry)
    entry["signature"] = base64.b64encode(private_key.sign(_signed_bytes(entry))).decode("ascii")
    line = _canonical(entry) + b"\n"
    try:
        with path.open("ab") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_dir(path.parent)
    except OSError as exc:
        raise LedgerError("ledger entry could not be durably appended") from exc
    return entry


def _verify_entries(entries: list[dict[str, object]], public_key: Any, fingerprint: str) -> None:
    seen_ids: set[str] = set()
    superseded_ids: set[str] = set()
    previous_digest = GENESIS_DIGEST
    for sequence, entry in enumerate(entries):
        _validate_entry(
            entry,
            sequence=sequence,
            previous_digest=previous_digest,
            seen_ids=seen_ids,
            superseded_ids=superseded_ids,
        )
        entry_id = str(entry["entry_id"])
        digest = _digest(entry)
        if entry["entry_digest"] != digest:
            raise LedgerError(f"ledger digest is invalid at entry {entry_id}")
        if entry["signer_key_fingerprint"] != fingerprint:
            raise LedgerError(f"ledger key fingerprint is invalid at entry {entry_id}")
        try:
            signature = base64.b64decode(str(entry["signature"]), validate=True)
            public_key.verify(signature, _signed_bytes(entry))
        except (binascii.Error, ValueError, InvalidSignature) as exc:
            raise LedgerError(f"ledger signature is invalid at entry {entry_id}") from exc
        seen_ids.add(entry_id)
        previous_digest = digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m leaderboard.ledger")
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("ledger", type=Path)
    verify_parser.add_argument("public_key", type=Path)
    args = parser.parse_args(argv)
    try:
        entries = verify_ledger(args.ledger, args.public_key)
    except LedgerError as exc:
        print(f"ledger verification failed: {exc}", file=sys.stderr)
        return 1
    noun = "entry" if len(entries) == 1 else "entries"
    print(f"verified {len(entries)} ledger {noun}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
