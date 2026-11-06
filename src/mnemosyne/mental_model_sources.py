"""Incremental, authorization-scoped source snapshots for maintained answers.

Database changes commit with their source transaction. Native writes supply
precise changes where supported and otherwise request a verified full rebuild.
Cached rows are private implementation data.
"""
from __future__ import annotations

import hashlib
import heapq
import json
import threading
import weakref
from contextlib import nullcontext
from datetime import datetime
from typing import Any

from mnemosyne.access_policy import expiry_deadline, filter_export_for_context
from mnemosyne.retrieval import classify_scoped_evidence, derived_evidence_readable, derived_source_cids

COLLECTIONS = ("evidence", "assertions", "relations", "preferences")
TELEMETRY = frozenset({"access_count", "last_accessed", "last_accessed_at", "salience"})
RowKey = tuple[str, str, str]
_ENGINES: weakref.WeakSet[Any] = weakref.WeakSet()
_REGISTRY_LOCK = threading.RLock()


def register_source_cache_engine(engine: Any) -> None:
    with _REGISTRY_LOCK:
        _ENGINES.add(engine)


def _storage_namespace(engine: Any) -> tuple[Any, ...]:
    if hasattr(engine, "root_dir"):
        return "sqlite", str(engine.root_dir.resolve())
    if hasattr(engine, "dsn"):
        from psycopg.conninfo import conninfo_to_dict
        params = conninfo_to_dict(engine.dsn)
        return "postgres", params.get("host", ""), params.get("port", "5432"), params.get("dbname", "")
    path = getattr(engine, "store_path", None)
    return ("local", str(path.resolve())) if path is not None else ("memory", id(engine))


def purge_source_snapshot_caches(engine: Any, tenant_id: str) -> None:
    """Drop revoked plaintext from live engines sharing this storage locator."""
    namespace = _storage_namespace(engine)
    with _REGISTRY_LOCK:
        engines = [item for item in _ENGINES if _storage_namespace(item) == namespace]
    for item in engines:
        # Use the same lock as snapshot publication. A cold snapshot may still
        # exist only in a reader's local variable when the source write commits.
        # Wait for its publication, then purge it before erasure returns.
        with getattr(item, "_mental_model_source_lock", None) or nullcontext():
            source_cache = getattr(item, "_mental_model_source_cache", {})
            for key in list(source_cache):
                if key[0] == tenant_id:
                    state = source_cache.pop(key, None)
                    if state is not None:
                        state.clear()
            snapshot_cache = getattr(item, "_mental_model_snapshot_cache", {})
            for key in list(snapshot_cache):
                if key[0] == tenant_id:
                    snapshot = snapshot_cache.pop(key, None)
                    if snapshot is not None:
                        snapshot[2][1].clear()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False, default=lambda item: item.isoformat())


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _stable(item) for key, item in value.items() if key not in TELEMETRY}
    if isinstance(value, (list, tuple)):
        return [_stable(item) for item in value]
    return value


def row_key(collection: str, row: dict[str, Any]) -> RowKey:
    return collection, str(row.get("branch") or "*"), str(row["cid" if collection == "evidence" else "id"])


class SourceSnapshot:
    """A source dependency index and incrementally maintained corpus digest."""

    def __init__(self, engine: Any, context: Any, scope: dict[str, Any], revision: int):
        self.engine, self.context, self.scope = engine, context, scope
        self.revision = revision
        self.raw: dict[RowKey, dict[str, Any]] = {}
        self.filtered: dict[RowKey, dict[str, Any]] = {}
        self.evidence: dict[str, dict[str, Any]] = {}
        self.dependencies: dict[RowKey, set[str]] = {}
        self.dependents: dict[str, set[RowKey]] = {}
        self.hashes: dict[RowKey, int] = {}
        self.total = 0
        self.expiries: list[tuple[datetime, RowKey]] = []
        self.policy = _json(engine.policy.to_dict())
        self.legacy_fingerprint: str | None = None
        self.baseline_fingerprint: str | None = None

    def _put(self, key: RowKey, row: dict[str, Any] | None) -> None:
        for cid in self.dependencies.pop(key, set()):
            users = self.dependents[cid]
            users.discard(key)
            if not users:
                del self.dependents[cid]
        self.raw.pop(key, None)
        if row is None:
            return
        self.raw[key] = row
        source_ids = row.get("source_evidence_cids", [])
        if key[0] == "evidence":
            source_ids, _ = derived_source_cids(row)
        deps = {cid for cid in source_ids if isinstance(cid, str)} if isinstance(source_ids, (list, tuple)) else set()
        self.dependencies[key] = deps
        for cid in deps:
            self.dependents.setdefault(cid, set()).add(key)
        policy = row.get("access_policy")
        expires = expiry_deadline(policy.get("expires_at")) if isinstance(policy, dict) else None
        if expires is not None:
            heapq.heappush(self.expiries, (expires, key))

    def clear(self) -> None:
        for data in (self.raw, self.filtered, self.evidence, self.dependencies,
                     self.dependents, self.hashes, self.expiries):
            data.clear()
        self.total = 0
        self.legacy_fingerprint = self.baseline_fingerprint = None

    def _closure(self, changed: set[RowKey]) -> set[RowKey]:
        affected = set(changed)
        pending = [key[2] for key in changed if key[0] == "evidence"]
        while pending:
            cid = pending.pop()
            for key in self.dependents.get(cid, ()):
                if key not in affected:
                    affected.add(key)
                    if key[0] == "evidence":
                        pending.append(key[2])
        return affected

    def expired(self, now: datetime) -> set[RowKey]:
        due: set[RowKey] = set()
        while self.expiries and self.expiries[0][0] <= now:
            _, key = heapq.heappop(self.expiries)
            if key in self.raw:
                due.add(key)
        return due

    def load(self, exported: dict[str, Any]) -> None:
        for collection in COLLECTIONS:
            for row in exported.get(collection, []):
                if row.get("branch", self.context.branch) == self.context.branch:
                    self._put(row_key(collection, row), row)
        self.refresh(set(self.raw))
        corpus = {"scope": self.scope, "policy": self.engine.policy.to_dict()}
        for collection in COLLECTIONS:
            corpus[collection] = sorted(
                (_stable(row) for key, row in self.filtered.items() if key[0] == collection),
                key=_json,
            )
        self.legacy_fingerprint = hashlib.sha256(_json(corpus).encode()).hexdigest()
        self.baseline_fingerprint = self.result()[0]

    def patch(self, changes: list[tuple[str, str, str]], rows: list[dict[str, Any]]) -> None:
        keys = {tuple(change) for change in changes}
        affected = self._closure(keys)
        replacements = {tuple(row["key"]): row["record"] for row in rows}
        for key in keys:
            self._put(key, replacements.get(key))
        self.refresh(affected | self._closure(keys))

    def refresh(self, affected: set[RowKey]) -> None:
        affected = self._closure(affected)
        inputs = {key for key in affected if key in self.raw}
        pending = list(inputs)
        while pending:
            key = pending.pop()
            for cid in self.dependencies.get(key, ()):
                source_key = ("evidence", self.context.branch, cid)
                if source_key in self.raw and source_key not in inputs:
                    inputs.add(source_key)
                    pending.append(source_key)
        exported: dict[str, Any] = {"tenant_id": self.context.tenant_id,
                                    **{collection: [] for collection in COLLECTIONS}}
        for key in inputs:
            exported[key[0]].append(self.raw[key])
        filt = self.context.to_filter()
        filtered = filter_export_for_context(
            exported, filt, policy_max_sensitivity=self.engine.policy.max_sensitivity,
            evidence_gate=lambda row: classify_scoped_evidence(
                row, tenant_id=self.context.tenant_id, branch=self.context.branch,
                filt=filt, policy=self.engine.policy)[0] and derived_evidence_readable(
                    self.engine, row, tenant_id=self.context.tenant_id,
                    branch=self.context.branch, filt=filt, policy=self.engine.policy),
        )
        replacements = {row_key(collection, row): row for collection in COLLECTIONS
                        for row in filtered.get(collection, [])}
        for key in affected:
            self.total -= self.hashes.pop(key, 0)
            self.filtered.pop(key, None)
            if key[0] == "evidence":
                self.evidence.pop(key[2], None)
            row = replacements.get(key)
            if row is None:
                continue
            if key[0] == "evidence":
                raw = self.raw[key]
                if not row.get("content"):
                    continue
                if self.context.as_of is not None and datetime.fromisoformat(raw["created_at"].replace("Z", "+00:00")) > self.context.as_of:
                    continue
                row = {**row, "source_policy_sha256": hashlib.sha256(_json(raw.get("access_policy", {})).encode()).hexdigest()}
            self.filtered[key] = row
            if key[0] == "evidence":
                self.evidence[key[2]] = row
            digest = int.from_bytes(hashlib.sha256(_json([key, _stable(row)]).encode()).digest(), "big")
            self.hashes[key] = digest
            self.total += digest
        self.policy = _json(self.engine.policy.to_dict())

    def result(self) -> tuple[str, dict[str, dict[str, Any]]]:
        # The key is included in each leaf, so equal text in distinct sources
        # remains distinct. Modular addition allows changed leaves to be removed.
        digest = hashlib.sha256(_json([
            "mnemosyne.source-corpus/v2", self.scope, self.policy,
            len(self.hashes), f"{self.total % (1 << 256):064x}",
        ]).encode()).hexdigest()
        return digest, self.evidence
