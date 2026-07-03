"""Per-tenant append-only CID journal (spec §4.0).

Dual-durability copy of the evidence ledger: engine commit happens FIRST,
journal append SECOND; on divergence the engine ledger is authoritative and
journal segments are re-derived, while journal-only CIDs are an alarm.
``tombstone``/``purge`` are the Phase-2 erasure primitives (mode-aware:
tombstone_recompute keeps a tombstone line — salted hash + timestamps —
while hard_delete_legal removes the line entirely). As of Phase-2 Task 9
``SqliteEngine.forget`` drives them: a tombstone_recompute erasure rewrites
each affected cid's line to a ``salted_hash`` marker (no plaintext), and a
hard_delete_legal erasure purges the lines outright, so a post-erasure
journal-rebuild stays byte-equivalent to a ledger-rebuild. ``append`` is
repair-before-append: it truncates an unfsynced torn tail (Phase-0 T8) before
writing so a crash-torn final fragment can never wedge later appends.
Stdlib only. CIDs are never computed here.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _canonical(record: dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"))


def _fsync_dir(path: Path) -> None:
    """Best-effort directory fsync so a rename survives power loss.

    Some platforms/filesystems reject fsync on directories; ignore OSError.
    """
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass  # best-effort: directory fsync unsupported here
    finally:
        os.close(fd)


_SAFE_TENANT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def safe_tenant_filename(tenant_id: str, suffix: str) -> str:
    """Map a tenant id to a filesystem-safe filename ``<tenant_id><suffix>``.

    Filesystem-safe ids (``^[A-Za-z0-9][A-Za-z0-9._-]*$``, and not ``.`` or
    ``..``) map verbatim to ``<tenant_id><suffix>``, preserving existing
    filenames for every sane id. Anything else (path separators, traversal
    sequences, leading dots, empty strings, ...) maps to the stable hashed
    name ``t-<sha256(tenant_id)[:32]><suffix>`` so a hostile tenant id can
    never name a file outside the target directory. Shared by the per-tenant
    CID journals (``.journal``) and SqliteEngine tenant databases (``.db``).
    """
    if tenant_id not in (".", "..") and _SAFE_TENANT_ID.fullmatch(tenant_id):
        return f"{tenant_id}{suffix}"
    return "t-" + hashlib.sha256(tenant_id.encode()).hexdigest()[:32] + suffix


def journal_filename(tenant_id: str) -> str:
    """Map a tenant id to a filesystem-safe journal filename.

    Thin wrapper over :func:`safe_tenant_filename` with the ``.journal``
    suffix; the containment rule and resulting filenames are unchanged.
    """
    return safe_tenant_filename(tenant_id, ".journal")


@dataclass
class JournalDivergence:
    missing_from_journal: list[str] = field(default_factory=list)
    journal_only: list[str] = field(default_factory=list)
    torn_tail: bool = False

    @property
    def diverged(self) -> bool:
        return bool(self.missing_from_journal or self.journal_only or self.torn_tail)


class CIDJournal:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _repair_torn_tail(self) -> None:
        """Truncate an unfsynced torn final fragment before appending (Phase-0 T8).

        ``append`` writes each record as one ``\\n``-terminated line and fsyncs
        it, so a fully-committed record ALWAYS ends in ``\\n``. A crash in the
        write→flush→fsync window can leave a trailing fragment with no
        terminating newline (and possibly unparseable JSON). That fragment is by
        construction unacknowledged, so truncating it back to the last complete
        newline (byte offset 0 when there is none) is loss-free and restores an
        append-safe tail — otherwise a subsequent ``append`` would leave the torn
        fragment as a NON-final line, which ``_read`` rejects as real corruption."""
        if not self.path.exists():
            return
        data = self.path.read_bytes()
        if not data or data.endswith(b"\n"):
            return
        keep = data.rfind(b"\n") + 1  # 0 when no complete line precedes the fragment
        with open(self.path, "r+b") as fh:
            fh.truncate(keep)
            fh.flush()
            os.fsync(fh.fileno())
        _fsync_dir(self.path.parent)

    def append(self, record: dict[str, Any]) -> None:
        if "cid" not in record:
            raise ValueError("journal records must carry a cid")
        self._repair_torn_tail()
        line = _canonical(record) + "\n"
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())

    def _read(self) -> tuple[list[dict[str, Any]], bool]:
        """Parse the journal; return ``(records, torn_tail)``.

        Because ``append`` fsyncs every line, only the FINAL line can be
        legitimately torn (crash in the buffered-write-to-fsync window), so an
        unparseable final line stops iteration cleanly while an unparseable
        non-final line is real corruption and raises json.JSONDecodeError.
        """
        records: list[dict[str, Any]] = []
        if not self.path.exists():
            return records, False
        with open(self.path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        last = len(lines) - 1
        for i, raw in enumerate(lines):
            line = raw.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                if i == last:
                    return records, True
                raise
        return records, False

    def records(self) -> Iterator[dict[str, Any]]:
        """Yield complete records, tolerating a torn trailing line.

        A torn FINAL line (post-crash) yields the complete records then stops;
        a bad non-final line raises json.JSONDecodeError. Callers needing the
        loud signal use ``verify_against(...).torn_tail``.
        """
        records, _ = self._read()
        yield from records

    def _rewrite(self, transform: Callable[[dict[str, Any]], dict[str, Any] | None]) -> None:
        """Atomic rewrite-and-swap: write tmp, fsync, rename over original."""
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            for record in self.records():
                out = transform(record)
                if out is not None:
                    fh.write(_canonical(out) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)
        _fsync_dir(self.path.parent)

    def tombstone(self, cid: str, *, salted_hash: str, erased_at: str) -> None:
        def transform(record: dict[str, Any]) -> dict[str, Any] | None:
            if record.get("cid") != cid:
                return record
            return {
                "cid": cid,
                "erased": True,
                "salted_hash": salted_hash,
                "erased_at": erased_at,
                "tenant_id": record.get("tenant_id"),
                "kind": record.get("kind"),
            }

        self._rewrite(transform)

    def purge(self, cid: str) -> None:
        self._rewrite(lambda r: None if r.get("cid") == cid else r)

    def verify_against(self, ledger_cids: set[str]) -> JournalDivergence:
        records, torn_tail = self._read()
        journal_cids = {r["cid"] for r in records}
        return JournalDivergence(
            missing_from_journal=sorted(ledger_cids - journal_cids),
            journal_only=sorted(journal_cids - ledger_cids),
            torn_tail=torn_tail,
        )
