"""Per-tenant append-only CID journal (spec §4.0).

Dual-durability copy of the evidence ledger: engine commit happens FIRST,
journal append SECOND; on divergence the engine ledger is authoritative and
journal segments are re-derived, while journal-only CIDs are an alarm.
Erasure is mode-aware: tombstone_recompute keeps a tombstone line (salted
hash + timestamps), hard_delete_legal removes the line entirely.
Stdlib only. CIDs are never computed here.
"""
from __future__ import annotations

import json
import os
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

    def append(self, record: dict[str, Any]) -> None:
        if "cid" not in record:
            raise ValueError("journal records must carry a cid")
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
