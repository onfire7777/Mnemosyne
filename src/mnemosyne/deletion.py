"""Synthetic deletion orchestration with fail-closed, resumable receipts.

This module coordinates existing engine erasure and explicitly registered
synthetic surfaces.  Its in-memory ledger is intentionally not durable; D5
owns the durable SQLite ledger and production semantic verifier.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, Sequence
from uuid import UUID
from weakref import WeakKeyDictionary

from .evidence_signing import sign_evidence_manifest
from .models import Evidence
from .security import SecurityPolicy, SessionIdentity

SCHEMA = "mnemosyne.deletion_manifest.v1"
_OPAQUE_KEY = secrets.token_bytes(32)


class DeletionStore(Protocol):
    """Minimal surface contract used by the coordinator."""

    def delete(self, tenant: str, source_ref: str) -> dict[str, Any]: ...
    def probe(self, tenant: str, source_ref: str) -> bool: ...


@dataclass(slots=True)
class SurfaceReceipt:
    surface: str
    state: str = "pending"
    attempts: int = 0
    checkpoint: str | None = None
    error_code: str | None = None
    verified_removed: bool = False
    action: str = "deleted"


@dataclass(slots=True)
class LedgerRecord:
    operation_id: str
    fingerprint: str
    tenant_id: str
    generation: int
    receipts: dict[str, SurfaceReceipt] = field(default_factory=dict)
    manifest: dict[str, Any] | None = None


class DeletionLedger(Protocol):
    durable: bool

    def begin(self, operation_id: str, fingerprint: str, tenant_id: str) -> LedgerRecord: ...
    def current_generation(self, tenant_id: str) -> int: ...


class InMemoryDeletionLedger:
    """Process-local CAS ledger.  D5 replaces this with durable SQLite."""

    durable = False

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[str, LedgerRecord] = {}
        self._generations: dict[str, int] = {}

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def begin(self, operation_id: str, fingerprint: str, tenant_id: str) -> LedgerRecord:
        with self._lock:
            existing = self._records.get(operation_id)
            if existing is not None:
                if existing.fingerprint != fingerprint:
                    raise ValueError("operation_id replay conflicts with canonical request")
                return existing
            generation = self._generations.get(tenant_id, 0) + 1
            self._generations[tenant_id] = generation
            record = LedgerRecord(operation_id, fingerprint, tenant_id, generation)
            self._records[operation_id] = record
            return record

    def current_generation(self, tenant_id: str) -> int:
        with self._lock:
            return self._generations.get(tenant_id, 0)


@dataclass(frozen=True, slots=True)
class _FenceCapability:
    token: str


_SHARED_LEDGERS: WeakKeyDictionary[Any, InMemoryDeletionLedger] = WeakKeyDictionary()
_SHARED_LEDGERS_LOCK = threading.Lock()


def _shared_ledger(engine: Any) -> InMemoryDeletionLedger:
    with _SHARED_LEDGERS_LOCK:
        ledger = _SHARED_LEDGERS.get(engine)
        if ledger is None:
            ledger = InMemoryDeletionLedger()
            _SHARED_LEDGERS[engine] = ledger
        return ledger


def _opaque(kind: str, value: str) -> str:
    digest = hmac.new(_OPAQUE_KEY, f"{kind}\0{value}".encode(), hashlib.sha256).hexdigest()
    return f"opaque:{digest}"


def _canonical_fingerprint(request: dict[str, Any]) -> str:
    encoded = json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class DeletionCoordinator:
    """Forward-only deletion saga over explicitly registered surfaces."""

    def __init__(
        self,
        *,
        engine: Any,
        stores: dict[str, DeletionStore] | None = None,
        process_cache: dict[str, Any] | None = None,
        object_keys: dict[str, bytes | None] | None = None,
        backup_snapshots: list[dict[str, Any]] | None = None,
        session_identity: SessionIdentity | None = None,
        security_policy: SecurityPolicy | None = None,
        ledger: DeletionLedger | None = None,
    ) -> None:
        self.engine = engine
        self.stores = stores if stores is not None else {}
        self.process_cache = process_cache if process_cache is not None else {}
        self.object_keys = object_keys if object_keys is not None else {}
        self.backup_snapshots = backup_snapshots if backup_snapshots is not None else []
        self.identity = session_identity
        self.policy = security_policy or SecurityPolicy()
        self.ledger = ledger or _shared_ledger(engine)
        self._capabilities: dict[str, tuple[str, int]] = {}

    def delete(
        self,
        *,
        schema: str,
        operation_id: str,
        tenant_id: str,
        user_id: str,
        source_refs: Sequence[str],
        branch_scope: str,
        mode: str,
        requested_by_role: str,
        reason: str,
        manifest_path: str | None = None,
        signing_private_key_path: str | None = None,
    ) -> dict[str, Any]:
        request = self._validate_request(
            schema=schema,
            operation_id=operation_id,
            tenant_id=tenant_id,
            user_id=user_id,
            source_refs=source_refs,
            branch_scope=branch_scope,
            mode=mode,
            requested_by_role=requested_by_role,
            reason=reason,
        )
        fingerprint = _canonical_fingerprint(request)
        record = self.ledger.begin(operation_id, fingerprint, tenant_id)
        lock = getattr(self.ledger, "lock", threading.RLock())
        with lock:
            if record.manifest is not None and record.manifest["summary"]["complete"]:
                self._persist_manifest(record.manifest, manifest_path, signing_private_key_path)
                return deepcopy(record.manifest)
            manifest = self._run(record, request)
            self._persist_manifest(manifest, manifest_path, signing_private_key_path)
            record.manifest = deepcopy(manifest)
            return deepcopy(manifest)

    @staticmethod
    def _persist_manifest(
        manifest: dict[str, Any],
        manifest_path: str | None,
        signing_private_key_path: str | None,
    ) -> None:
        if manifest_path is None or not manifest["summary"]["complete"]:
            return
        if signing_private_key_path is None:
            raise ValueError("signing_private_key_path is required with manifest_path")
        path = Path(manifest_path)
        path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
        sign_evidence_manifest(path, Path(signing_private_key_path))

    def _validate_request(self, **raw: Any) -> dict[str, Any]:
        identity = self.identity
        if identity is None:
            raise PermissionError("verified session identity is required")
        if identity.expires_at is not None and identity.expires_at <= int(time.time()):
            raise PermissionError("verified session identity is expired")
        if not raw["tenant_id"] or raw["tenant_id"] != identity.tenant_id:
            raise PermissionError("tenant ownership does not match verified session identity")
        if not raw["user_id"] or raw["user_id"] != identity.user_id:
            raise PermissionError("user ownership does not match verified session identity")
        decision = self.policy.authorize_write(
            "deletion.hard_delete_legal",
            identity.role,
            identity.source_trust_tier,
            destructive=True,
        )
        if not decision.allowed:
            raise PermissionError(decision.reason)
        if raw["requested_by_role"] != "legal":
            raise PermissionError("legal deletion requires the legal override policy")
        if raw["schema"] != SCHEMA:
            raise ValueError("unsupported deletion schema")
        try:
            parsed = UUID(str(raw["operation_id"]))
        except (TypeError, ValueError) as exc:
            raise ValueError("operation_id must be a UUID") from exc
        if parsed.version is None:
            raise ValueError("operation_id must be a UUID")
        refs = raw["source_refs"]
        if isinstance(refs, (str, bytes)) or not refs:
            raise ValueError("source_refs must be a nonempty sequence")
        normalized_refs = [str(ref).strip() for ref in refs]
        if any(not ref for ref in normalized_refs) or len(set(normalized_refs)) != len(normalized_refs):
            raise ValueError("source_refs must be nonempty and deduplicated")
        if raw["branch_scope"] not in {"main", "all"}:
            raise ValueError("branch_scope must be exactly main or all")
        if raw["mode"] != "hard_delete_legal":
            raise ValueError("unsupported deletion mode")
        if not isinstance(raw["reason"], str) or not raw["reason"].strip():
            raise ValueError("reason is required")
        return {**raw, "source_refs": normalized_refs}

    def _run(self, record: LedgerRecord, request: dict[str, Any]) -> dict[str, Any]:
        tenant = request["tenant_id"]
        refs = request["source_refs"]
        required = self._surface_names(tenant, refs)
        for name in required:
            record.receipts.setdefault(name, SurfaceReceipt(surface=name))

        # Boundary stores must be available before other external effects.  This
        # is a precondition gate, not rollback; verified deletions are never restored.
        boundary = [name for name in ("journal", "manifest_store") if name in self.stores]
        boundary += ["object_storage"] if (
            "object_storage" in self.stores or any(self._target_object_keys(tenant, refs))
        ) else []
        for name in boundary:
            if not self._attempt(record, name, tenant, refs):
                return self._manifest(record, request)

        for name in required:
            if name in {"source_evidence", "sqlite", *boundary}:
                continue
            self._attempt(record, name, tenant, refs)

        externals_verified = all(
            receipt.verified_removed
            for name, receipt in record.receipts.items()
            if name not in {"source_evidence", "sqlite"}
        )
        if externals_verified:
            self._attempt_engine(record, request)
        return self._manifest(record, request)

    def _surface_names(self, tenant: str, refs: list[str]) -> list[str]:
        names = [self._store_surface(name) for name in self.stores]
        names.extend(
            f"cache:{key}"
            for key, value in self.process_cache.items()
            if isinstance(value, dict)
            and value.get("tenant_id") == tenant
            and value.get("source_ref") in refs
        )
        if self._target_object_keys(tenant, refs):
            names.append("object_storage")
        if any(row.get("tenant_id") == tenant and row.get("source_ref") in refs for row in self.backup_snapshots):
            names.append("backups")
        engine_surface = "sqlite" if self.engine.__class__.__name__ == "SqliteEngine" else "source_evidence"
        names.append(engine_surface)
        return list(dict.fromkeys(names))

    @staticmethod
    def _store_surface(name: str) -> str:
        return "runtime_user_model" if name == "runtime_state" else name

    def _attempt(self, record: LedgerRecord, surface: str, tenant: str, refs: list[str]) -> bool:
        receipt = record.receipts[surface]
        if receipt.verified_removed:
            return True
        receipt.state = "deleting"
        receipt.attempts += 1
        receipt.error_code = None
        try:
            if surface == "object_storage" and self._target_object_keys(tenant, refs):
                return self._delete_objects(receipt, tenant, refs)
            if surface == "backups":
                return self._delete_backups(receipt, tenant, refs)
            cache_name = surface.removeprefix("cache:") if surface.startswith("cache:") else None
            cache_keys = [
                key
                for key, value in self.process_cache.items()
                if key == cache_name
                and isinstance(value, dict)
                and value.get("tenant_id") == tenant
                and value.get("source_ref") in refs
            ]
            if cache_keys:
                for key in cache_keys:
                    del self.process_cache[key]
                receipt.action = "invalidated"
                return self._verified(receipt)
            store_name = "runtime_state" if surface == "runtime_user_model" else surface
            store = self.stores[store_name]
            for ref in refs:
                store.delete(tenant, ref)
            if not self._probe_store(store, tenant, refs):
                receipt.error_code = "probe_failed"
                receipt.state = "failed"
                return False
            return self._verified(receipt)
        except ConnectionError:
            receipt.error_code = "store_unavailable"
        except Exception:
            receipt.error_code = "delete_failed"
        receipt.state = "failed"
        return False

    @staticmethod
    def _probe_store(store: Any, tenant: str, refs: list[str]) -> bool:
        probe = getattr(store, "probe", None)
        if callable(probe):
            return all(probe(tenant, ref) is False for ref in refs)
        rows = getattr(store, "rows", None)
        if isinstance(rows, list):
            return not any(row.get("tenant_id") == tenant and row.get("source_ref") in refs for row in rows)
        return False

    def _target_object_keys(self, tenant: str, refs: list[str]) -> list[str]:
        targets = {
            f"{scheme}://{tenant}/{ref}"
            for ref in refs
            for scheme in ("local_encrypted", "s3_encrypted", "plain")
        }
        return [
            key
            for key in self.object_keys
            if key in targets
        ]

    def _delete_objects(self, receipt: SurfaceReceipt, tenant: str, refs: list[str]) -> bool:
        keys = self._target_object_keys(tenant, refs)
        if any(key.startswith("plain://") for key in keys):
            receipt.error_code = "not_crypto_shreddable"
            receipt.state = "failed"
            return False
        kms = self.stores.get("kms")
        if kms is not None and not getattr(kms, "available", True):
            receipt.error_code = "store_unavailable"
            receipt.state = "failed"
            return False
        for key in keys:
            self.object_keys[key] = None
        receipt.action = "crypto_shredded"
        return self._verified(receipt)

    def _delete_backups(self, receipt: SurfaceReceipt, tenant: str, refs: list[str]) -> bool:
        targets = [row for row in self.backup_snapshots if row.get("tenant_id") == tenant and row.get("source_ref") in refs]
        if any(not row.get("available", True) or row.get("immutable", False) for row in targets):
            receipt.error_code = "retention_exception"
            receipt.state = "failed"
            return False
        self.backup_snapshots[:] = [row for row in self.backup_snapshots if row not in targets]
        return self._verified(receipt)

    @staticmethod
    def _verified(receipt: SurfaceReceipt) -> bool:
        receipt.state = "deleted"
        receipt.state = "verified"
        receipt.verified_removed = True
        receipt.checkpoint = secrets.token_hex(8)
        return True

    def _attempt_engine(self, record: LedgerRecord, request: dict[str, Any]) -> None:
        surface = "sqlite" if self.engine.__class__.__name__ == "SqliteEngine" else "source_evidence"
        receipt = record.receipts[surface]
        if receipt.verified_removed:
            return
        receipt.state = "deleting"
        receipt.attempts += 1
        branches = ["main"]
        if request["branch_scope"] == "all":
            branches = list(getattr(self.engine, "branches", {"main": {}}))
        try:
            for branch in branches:
                for ref in request["source_refs"]:
                    self.engine.forget(
                        request["tenant_id"],
                        ref,
                        branch=branch,
                        requested_by="legal",
                        erasure_mode="hard_delete_legal",
                    )
            if any(
                self.engine.get_evidence(request["tenant_id"], ref, branch=branch) is not None
                for branch in branches
                for ref in request["source_refs"]
            ):
                receipt.error_code = "probe_failed"
                receipt.state = "failed"
                return
            self._verified(receipt)
        except Exception:
            receipt.error_code = "delete_failed"
            receipt.state = "failed"

    def _manifest(self, record: LedgerRecord, request: dict[str, Any]) -> dict[str, Any]:
        rows = []
        unavailable = failed = verified = 0
        for name, receipt in record.receipts.items():
            unavailable += receipt.error_code == "store_unavailable"
            failed += receipt.state == "failed" and receipt.error_code != "store_unavailable"
            verified += receipt.verified_removed
            rows.append(
                {
                    "surface": name,
                    "backend": "synthetic",
                    "tenant_ref": _opaque("tenant", request["tenant_id"]),
                    "object_ref": _opaque("surface", f"{record.operation_id}:{name}"),
                    "action": receipt.action,
                    "state": receipt.state,
                    "attempts": receipt.attempts,
                    "checkpoint": receipt.checkpoint,
                    "verified_removed": receipt.verified_removed,
                    "error_code": receipt.error_code,
                }
            )
        complete = bool(rows) and verified == len(rows)
        expected = len(rows)
        retention_exceptions = []
        if "backups" in record.receipts and not record.receipts["backups"].verified_removed:
            retention_exceptions.append(
                {
                    "surface": "backups",
                    "restore_block_fence": record.generation,
                    "deadline": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
                }
            )
        return {
            "schema": request["schema"],
            "operation_id": record.operation_id,
            "mode": request["mode"],
            "requested_by_role": request["requested_by_role"],
            "tenant_ref": _opaque("tenant", request["tenant_id"]),
            "user_scope": _opaque("user", request["user_id"]),
            "branch_scope": request["branch_scope"],
            "source_refs": [_opaque("source", ref) for ref in request["source_refs"]],
            "fence": {"generation": record.generation, "ledger_position": record.generation, "durable": self.ledger.durable},
            "surfaces": rows,
            "retention_exceptions": retention_exceptions,
            "summary": {
                "expected": expected,
                "visited": sum(receipt.attempts > 0 for receipt in record.receipts.values()),
                "verified": verified,
                "failed": failed,
                "unavailable": unavailable,
                "cascade_percent": 100 if complete else int(verified * 100 / expected) if expected else 0,
                "recoverable_residue_count": expected - verified,
                "cross_tenant_mutations": 0,
                "complete": complete,
            },
        }

    def issue_write_capability(self, *, identity: SessionIdentity, tenant_id: str) -> _FenceCapability:
        if self.identity is None or identity != self.identity or tenant_id != identity.tenant_id:
            raise PermissionError("verified session identity is required")
        decision = self.policy.authorize_write("deletion.restore", identity.role, identity.source_trust_tier, destructive=True)
        if not decision.allowed:
            raise PermissionError(decision.reason)
        token = secrets.token_urlsafe(32)
        self._capabilities[token] = (tenant_id, self.ledger.current_generation(tenant_id))
        return _FenceCapability(token)

    def _require_capability(self, tenant_id: str, capability: object | None) -> None:
        if not isinstance(capability, _FenceCapability):
            raise PermissionError("deletion fence capability required")
        issued = self._capabilities.get(capability.token)
        current = self.ledger.current_generation(tenant_id)
        if issued != (tenant_id, current):
            raise PermissionError("deletion fence capability is stale or forged")

    def append_evidence(
        self,
        evidence: Evidence,
        *,
        branch: str = "main",
        capability: object | None = None,
    ) -> str:
        self._require_capability(evidence.tenant_id, capability)
        return self.engine.append_evidence(evidence, branch=branch)

    def restore_backup(
        self,
        *,
        tenant_id: str,
        snapshot: dict[str, Any],
        capability: object | None = None,
    ) -> None:
        self._require_capability(tenant_id, capability)
        if snapshot.get("tenant_id") != tenant_id:
            raise PermissionError("snapshot tenant does not match capability")
        self.backup_snapshots.append(deepcopy(snapshot))
