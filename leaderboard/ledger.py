"""Signed append-only JSONL ledger for leaderboard run outcomes."""

from __future__ import annotations

import argparse
import base64
import binascii
import fcntl
import json
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from collections.abc import Collection
from typing import Any, Iterator

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
RUN_STATUSES = {"succeeded", "failed", "aborted", "discarded"}
UTC_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z")
HEAD_VERSION = "mnemosyne.leaderboard.ledger-head/v1"


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


def _head_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".head.json")


def _pending_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".pending.json")


def _write_pending(path: Path, prior_count: int) -> None:
    pending_path = _pending_path(path)
    temporary = pending_path.with_suffix(pending_path.suffix + ".tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(_canonical({"prior_count": prior_count}) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, pending_path)
        _fsync_dir(path.parent)
    except OSError as exc:
        raise LedgerError("ledger entry could not be durably appended") from exc


def _load_pending(path: Path) -> int | None:
    try:
        raw = _pending_path(path).read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise LedgerError("ledger append intent could not be read") from exc
    try:
        pending = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LedgerError("ledger append intent contains invalid JSON") from exc
    if (
        not isinstance(pending, dict)
        or set(pending) != {"prior_count"}
        or not isinstance(pending["prior_count"], int)
        or pending["prior_count"] < 0
        or raw != _canonical(pending) + b"\n"
    ):
        raise LedgerError("ledger append intent is invalid")
    return pending["prior_count"]


def _clear_pending(path: Path) -> None:
    try:
        _pending_path(path).unlink(missing_ok=True)
        _fsync_dir(path.parent)
    except OSError as exc:
        raise LedgerError("ledger append intent could not be cleared") from exc


def _normalize_roster(roster: Collection[str]) -> list[str]:
    if not roster or any(not isinstance(item, str) or not item.strip() for item in roster):
        raise LedgerError("pre-registered roster must contain non-empty entrant IDs")
    normalized = sorted(roster)
    if len(normalized) != len(set(normalized)):
        raise LedgerError("pre-registered roster contains duplicate entrant IDs")
    return normalized


def _load_head(path: Path) -> dict[str, object] | None:
    head_path = _head_path(path)
    try:
        raw = head_path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise LedgerError("ledger head could not be read") from exc
    try:
        head = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LedgerError("ledger head contains invalid JSON") from exc
    if not isinstance(head, dict) or raw != _canonical(head) + b"\n":
        raise LedgerError("ledger head is not canonical JSON")
    return head


def _verify_active_dispositions(entries: list[dict[str, object]]) -> None:
    superseded_ids = {
        str(entry["supersedes"])
        for entry in entries
        if entry["status"] == "superseded"
    }
    active: dict[str, set[str]] = {}
    for entry in entries:
        if entry["entry_id"] in superseded_ids:
            continue
        status = str(entry["status"])
        if status in RUN_STATUSES | {"no_run"}:
            active.setdefault(str(entry["entrant_id"]), set()).add(status)
    contradictory = sorted(
        entrant
        for entrant, statuses in active.items()
        if "no_run" in statuses and statuses & RUN_STATUSES
    )
    if contradictory:
        raise LedgerError(
            "ledger has contradictory active dispositions for entrant: "
            + ", ".join(contradictory)
        )


def _verify_head(
    head: dict[str, object] | None,
    entries: list[dict[str, object]],
    public_key: Any,
    fingerprint: str,
    *,
    require_complete_roster: bool,
) -> list[str]:
    if head is None:
        if entries:
            raise LedgerError("ledger head is missing")
        return []
    required = {
        "version",
        "sequence",
        "entry_digest",
        "roster",
        "signer_key_fingerprint",
        "signature",
    }
    if set(head) != required or head["version"] != HEAD_VERSION:
        raise LedgerError("ledger head fields are invalid")
    roster_value = head["roster"]
    if not isinstance(roster_value, list):
        raise LedgerError("ledger head roster is invalid")
    roster = _normalize_roster(roster_value)
    if head["signer_key_fingerprint"] != fingerprint:
        raise LedgerError("ledger head key fingerprint is invalid")
    try:
        signature = base64.b64decode(str(head["signature"]), validate=True)
        public_key.verify(signature, _signed_bytes(head))
    except (binascii.Error, ValueError, InvalidSignature) as exc:
        raise LedgerError("ledger head signature is invalid") from exc
    if not entries:
        raise LedgerError("ledger head does not match an empty ledger")
    if (
        type(head["sequence"]) is not int
        or head["sequence"] != len(entries) - 1
        or head["entry_digest"] != entries[-1]["entry_digest"]
    ):
        raise LedgerError("ledger head does not match the final entry")
    unknown = {str(entry["entrant_id"]) for entry in entries} - set(roster)
    if unknown:
        raise LedgerError(
            "ledger entrant is absent from pre-registered roster: " + ", ".join(sorted(unknown))
        )
    _verify_active_dispositions(entries)
    covered = {
        str(entry["entrant_id"])
        for entry in entries
        if entry["status"] in RUN_STATUSES | {"no_run"}
    }
    if require_complete_roster:
        missing = set(roster) - covered
        if missing:
            raise LedgerError(
                "pre-registered roster entrant is omitted from ledger: "
                + ", ".join(sorted(missing))
            )
    return roster


def _write_head(
    path: Path,
    entry: dict[str, object],
    roster: list[str],
    private_key: Any,
    fingerprint: str,
) -> None:
    head: dict[str, object] = {
        "version": HEAD_VERSION,
        "sequence": entry["sequence"],
        "entry_digest": entry["entry_digest"],
        "roster": roster,
        "signer_key_fingerprint": fingerprint,
        "signature": "",
    }
    head["signature"] = base64.b64encode(private_key.sign(_signed_bytes(head))).decode("ascii")
    head_path = _head_path(path)
    temporary = head_path.with_suffix(head_path.suffix + ".tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(_canonical(head) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, head_path)
        _fsync_dir(path.parent)
    except OSError as exc:
        raise LedgerError("ledger head could not be durably committed") from exc


@contextmanager
def _ledger_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    try:
        with lock_path.open("a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        raise LedgerError("ledger lock could not be acquired") from exc


def _parse_entries(data: bytes) -> list[dict[str, object]]:
    if b"\r" in data:
        raise LedgerError("ledger contains non-canonical line endings")
    entries: list[dict[str, object]] = []
    for index, raw in enumerate(data.splitlines(), start=1):
        try:
            entry = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise LedgerError(f"ledger line {index} contains invalid JSON") from exc
        if not isinstance(entry, dict):
            raise LedgerError(f"ledger line {index} must be a JSON object")
        if raw != _canonical(entry):
            raise LedgerError(f"ledger line {index} contains non-canonical JSON")
        entries.append(entry)
    return entries


def _load_entries(path: Path) -> list[dict[str, object]]:
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise LedgerError("ledger could not be read") from exc

    if data and not data.endswith(b"\n"):
        fragment = data[data.rfind(b"\n") + 1 :]
        try:
            json.loads(fragment)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
        else:
            raise LedgerError("ledger has a complete unterminated final entry")
        raise LedgerError("ledger has an unacknowledged torn final fragment")
    return _parse_entries(data)


def _validate_entry(
    entry: dict[str, object],
    *,
    sequence: int,
    previous_digest: str,
    seen_entrants: dict[str, str],
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
    if entry_id in seen_entrants:
        raise LedgerError(f"duplicate ledger entry_id: {entry_id}")
    timestamp = entry["timestamp"]
    if not isinstance(timestamp, str) or UTC_TIMESTAMP.fullmatch(timestamp) is None:
        raise LedgerError("ledger timestamp must be canonical RFC3339 UTC")
    try:
        datetime.fromisoformat(timestamp.removesuffix("Z"))
    except ValueError as exc:
        raise LedgerError("ledger timestamp must be canonical RFC3339 UTC") from exc
    entrant_id = entry["entrant_id"]
    if not isinstance(entrant_id, str) or not entrant_id.strip():
        raise LedgerError("ledger entrant_id is required")
    if type(entry["sequence"]) is not int or entry["sequence"] != sequence:
        raise LedgerError(f"ledger sequence is not contiguous at entry {entry_id}")
    if entry["previous_digest"] != previous_digest:
        raise LedgerError(f"ledger hash link is invalid at entry {entry_id}")

    status = entry["status"]
    if not isinstance(status, str) or status not in STATUSES:
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
    elif entry["result"] is not None:
        raise LedgerError(f"ledger result must be null for status {status}")
    if status in RUN_STATUSES and (
        not isinstance(entry["run_id"], str) or not entry["run_id"].strip()
    ):
        raise LedgerError(f"ledger run_id is required for {status} entries")
    if status == "no_run" and entry["run_id"] is not None:
        raise LedgerError("ledger run_id must be null for no_run entries")

    target = entry["supersedes"]
    if status == "superseded":
        if not isinstance(target, str) or not target:
            raise LedgerError("ledger superseded entry requires a supersedes target")
        if target == entry_id:
            raise LedgerError("ledger entry cannot supersede itself")
        if target not in seen_entrants:
            raise LedgerError(f"unknown supersession target: {target}")
        if target in superseded_ids:
            raise LedgerError(f"ledger entry is already superseded: {target}")
        if seen_entrants[target] != entrant_id:
            raise LedgerError("ledger supersession must target the same entrant")
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
    path = Path(ledger_path)
    with _ledger_lock(path):
        if not path.is_file():
            raise LedgerError("ledger is missing")
        entries = _load_entries(path)
        if not entries:
            raise LedgerError("ledger is empty")
        _verify_entries(entries, public_key, expected_fingerprint)
        _verify_head(
            _load_head(path),
            entries,
            public_key,
            expected_fingerprint,
            require_complete_roster=True,
        )
    return entries


def _repair_pending_torn_tail(
    path: Path,
    head: dict[str, object] | None,
    public_key: Any,
    fingerprint: str,
) -> None:
    prior_count = _load_pending(path)
    if prior_count is None:
        return
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        data = b""
    except OSError as exc:
        raise LedgerError("ledger could not be read") from exc
    if not data or data.endswith(b"\n"):
        return
    complete = _parse_entries(data[: data.rfind(b"\n") + 1])
    if prior_count > len(complete):
        raise LedgerError("ledger append intent exceeds ledger length")
    prefix = complete[:prior_count]
    _verify_entries(prefix, public_key, fingerprint)
    _verify_head(
        head,
        prefix,
        public_key,
        fingerprint,
        require_complete_roster=False,
    )
    keep = sum(len(_canonical(entry)) + 1 for entry in prefix)
    try:
        with path.open("r+b") as handle:
            handle.truncate(keep)
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_dir(path.parent)
    except OSError as exc:
        raise LedgerError("unacknowledged ledger append could not be repaired") from exc


def _recover_pending_append(
    path: Path,
    head: dict[str, object] | None,
    entries: list[dict[str, object]],
    public_key: Any,
    fingerprint: str,
) -> list[dict[str, object]]:
    prior_count = _load_pending(path)
    if prior_count is None:
        return entries
    if (
        head is not None
        and entries
        and head.get("sequence") == len(entries) - 1
        and head.get("entry_digest") == entries[-1].get("entry_digest")
    ):
        _verify_entries(entries, public_key, fingerprint)
        _verify_head(
            head,
            entries,
            public_key,
            fingerprint,
            require_complete_roster=False,
        )
        _clear_pending(path)
        return entries
    if prior_count > len(entries):
        raise LedgerError("ledger append intent exceeds ledger length")
    prefix = entries[:prior_count]
    _verify_entries(prefix, public_key, fingerprint)
    _verify_head(
        head,
        prefix,
        public_key,
        fingerprint,
        require_complete_roster=False,
    )
    keep = sum(len(_canonical(entry)) + 1 for entry in prefix)
    try:
        with path.open("r+b") as handle:
            handle.truncate(keep)
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_dir(path.parent)
    except OSError as exc:
        raise LedgerError("unacknowledged ledger append could not be repaired") from exc
    _clear_pending(path)
    return prefix


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
    roster: Collection[str],
) -> dict[str, object]:
    """Validate, sign, durably append, and return one ledger entry."""
    path = Path(ledger_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        private_key = load_private_key(Path(private_key_path))
    except EvidenceSignatureError as exc:
        raise LedgerError("ledger private key could not be loaded") from exc
    public_key = private_key.public_key()
    fingerprint = _public_key_sha256(public_key)
    with _ledger_lock(path):
        head = _load_head(path)
        _repair_pending_torn_tail(path, head, public_key, fingerprint)
        entries = _load_entries(path)
        entries = _recover_pending_append(path, head, entries, public_key, fingerprint)
        if entries:
            # Verification with the signing key prevents appending after acknowledged corruption.
            _verify_entries(entries, public_key, fingerprint)
            existing_roster = _verify_head(
                head,
                entries,
                public_key,
                fingerprint,
                require_complete_roster=False,
            )
            normalized_roster = _normalize_roster(roster)
            if normalized_roster != existing_roster:
                raise LedgerError("pre-registered roster cannot change after the first entry")
        else:
            if head is not None:
                raise LedgerError("ledger head does not match an empty ledger")
            normalized_roster = _normalize_roster(roster)
        if entrant_id not in normalized_roster:
            raise LedgerError("ledger entrant is absent from pre-registered roster")

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
            "signer_key_fingerprint": fingerprint,
            "signature": "",
        }
        seen_entrants = {
            str(existing["entry_id"]): str(existing["entrant_id"]) for existing in entries
        }
        superseded_ids = {
            str(existing["supersedes"])
            for existing in entries
            if existing["status"] == "superseded"
        }
        _validate_entry(
            entry,
            sequence=len(entries),
            previous_digest=str(entry["previous_digest"]),
            seen_entrants=seen_entrants,
            superseded_ids=superseded_ids,
        )
        _verify_active_dispositions([*entries, entry])
        entry["entry_digest"] = _digest(entry)
        entry["signature"] = base64.b64encode(private_key.sign(_signed_bytes(entry))).decode("ascii")
        line = _canonical(entry) + b"\n"
        _write_pending(path, len(entries))
        try:
            with path.open("ab") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            _fsync_dir(path.parent)
            _write_head(path, entry, normalized_roster, private_key, fingerprint)
        except OSError as exc:
            raise LedgerError("ledger entry could not be durably appended") from exc
        _clear_pending(path)
        return entry


def _verify_entries(entries: list[dict[str, object]], public_key: Any, fingerprint: str) -> None:
    seen_entrants: dict[str, str] = {}
    superseded_ids: set[str] = set()
    previous_digest = GENESIS_DIGEST
    for sequence, entry in enumerate(entries):
        _validate_entry(
            entry,
            sequence=sequence,
            previous_digest=previous_digest,
            seen_entrants=seen_entrants,
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
        seen_entrants[entry_id] = str(entry["entrant_id"])
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
