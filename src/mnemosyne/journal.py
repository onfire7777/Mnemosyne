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


@dataclass
class JournalDivergence:
    missing_from_journal: list[str] = field(default_factory=list)
    journal_only: list[str] = field(default_factory=list)

    @property
    def diverged(self) -> bool:
        return bool(self.missing_from_journal or self.journal_only)


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

    def records(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)

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
        journal_cids = {r["cid"] for r in self.records()}
        return JournalDivergence(
            missing_from_journal=sorted(ledger_cids - journal_cids),
            journal_only=sorted(journal_cids - ledger_cids),
        )
