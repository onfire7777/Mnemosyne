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
import sqlite3
import threading
import time
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, Sequence
from uuid import UUID
from weakref import WeakKeyDictionary

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
    requested_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    receipts: dict[tuple[str, str], SurfaceReceipt] = field(default_factory=dict)
    manifest: dict[str, Any] | None = None
    revision: int = 0


class DeletionLedger(Protocol):
    durable: bool

    def begin(self, operation_id: str, fingerprint: str, tenant_id: str) -> LedgerRecord: ...
    def current_generation(self, tenant_id: str) -> int: ...
    def checkpoint(self, record: LedgerRecord) -> None: ...
    def operation_lock(self) -> Any: ...


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

    def checkpoint(self, record: LedgerRecord) -> None:
        """The process-local record is already the authoritative value."""

    def operation_lock(self) -> threading.RLock:
        return self._lock


class SQLiteDeletionLedger:
    """Durable operation journal used to resume deletion sagas after restart."""

    durable = True

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS deletion_operations (
                    operation_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    requested_at TEXT NOT NULL,
                    receipts_json TEXT NOT NULL,
                    manifest_json TEXT,
                    revision INTEGER NOT NULL DEFAULT 0
                );
                CREATE UNIQUE INDEX IF NOT EXISTS deletion_tenant_generation
                ON deletion_operations(tenant_id, generation);
                CREATE TABLE IF NOT EXISTS deletion_ledger_metadata (
                    key TEXT PRIMARY KEY,
                    value BLOB NOT NULL
                );
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO deletion_ledger_metadata(key, value) VALUES ('opaque_key', ?)",
                (secrets.token_bytes(32),),
            )
            self._opaque_key = bytes(
                connection.execute(
                    "SELECT value FROM deletion_ledger_metadata WHERE key = 'opaque_key'"
                ).fetchone()[0]
            )
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(deletion_operations)")
            }
            if "revision" not in columns:
                connection.execute(
                    "ALTER TABLE deletion_operations ADD COLUMN revision INTEGER NOT NULL DEFAULT 0"
                )

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _opaque(self, kind: str, value: str) -> str:
        digest = hmac.new(self._opaque_key, f"{kind}\0{value}".encode(), hashlib.sha256).hexdigest()
        return f"opaque:{digest}"

    @contextmanager
    def operation_lock(self) -> Any:
        """Serialize coordinators sharing this ledger, including other processes."""
        import fcntl

        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        with lock_path.open("a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _receipts(record: LedgerRecord) -> str:
        rows = [
            {"kind": key[0], "name": key[1], **asdict(receipt)}
            for key, receipt in record.receipts.items()
        ]
        return json.dumps(rows, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _record(row: sqlite3.Row, *, fingerprint: str, tenant_id: str) -> LedgerRecord:
        receipts = {}
        for item in json.loads(row[5]):
            key = (item.pop("kind"), item.pop("name"))
            receipts[key] = SurfaceReceipt(**item)
        return LedgerRecord(
            operation_id=row[0],
            fingerprint=fingerprint,
            tenant_id=tenant_id,
            generation=row[3],
            requested_at=row[4],
            receipts=receipts,
            manifest=json.loads(row[6]) if row[6] is not None else None,
            revision=row[7],
        )

    def begin(self, operation_id: str, fingerprint: str, tenant_id: str) -> LedgerRecord:
        stored_fingerprint = self._opaque("request", fingerprint)
        stored_tenant = self._opaque("tenant", tenant_id)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT operation_id, fingerprint, tenant_id, generation, requested_at, "
                "receipts_json, manifest_json, revision FROM deletion_operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if row is not None:
                if not hmac.compare_digest(row[1], stored_fingerprint):
                    raise ValueError("operation_id replay conflicts with canonical request")
                return self._record(row, fingerprint=fingerprint, tenant_id=tenant_id)
            generation = connection.execute(
                "SELECT COALESCE(MAX(generation), 0) + 1 FROM deletion_operations WHERE tenant_id = ?",
                (stored_tenant,),
            ).fetchone()[0]
            requested_at = datetime.now(UTC).isoformat()
            connection.execute(
                "INSERT INTO deletion_operations "
                "(operation_id, fingerprint, tenant_id, generation, requested_at, receipts_json, manifest_json, revision) "
                "VALUES (?, ?, ?, ?, ?, '[]', NULL, 0)",
                (operation_id, stored_fingerprint, stored_tenant, generation, requested_at),
            )
            return LedgerRecord(operation_id, fingerprint, tenant_id, generation, requested_at)

    def checkpoint(self, record: LedgerRecord) -> None:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE deletion_operations SET receipts_json = ?, manifest_json = ?, "
                "revision = revision + 1 WHERE operation_id = ? AND fingerprint = ? AND revision = ?",
                (
                    self._receipts(record),
                    json.dumps(record.manifest, sort_keys=True) if record.manifest is not None else None,
                    record.operation_id,
                    self._opaque("request", record.fingerprint),
                    record.revision,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("deletion ledger checkpoint conflict")
            record.revision += 1

    def current_generation(self, tenant_id: str) -> int:
        with self._lock, self._connect() as connection:
            return connection.execute(
                "SELECT COALESCE(MAX(generation), 0) FROM deletion_operations WHERE tenant_id = ?",
                (self._opaque("tenant", tenant_id),),
            ).fetchone()[0]


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
        lock = getattr(self.ledger, "operation_lock", None)
        operation_lock = lock() if callable(lock) else getattr(self.ledger, "lock", threading.RLock())
        with operation_lock:
            record = self.ledger.begin(operation_id, fingerprint, tenant_id)
            if record.manifest is not None and record.manifest["summary"]["complete"]:
                return deepcopy(record.manifest)
            manifest = self._run(record, request)
            record.manifest = deepcopy(manifest)
            self.ledger.checkpoint(record)
            return deepcopy(manifest)

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
        required = list(dict.fromkeys([*self._surface_ids(tenant, refs), *record.receipts]))
        for surface_id in required:
            record.receipts.setdefault(surface_id, SurfaceReceipt(surface=self._surface_label(surface_id)))
        self.ledger.checkpoint(record)

        # Boundary stores must be available before other external effects.  This
        # is a precondition gate, not rollback; verified deletions are never restored.
        boundary = [("store", name) for name in ("journal", "manifest_store") if name in self.stores]
        boundary += [("object", "object_storage")] if (
            "object_storage" in self.stores or any(self._target_object_keys(tenant, refs))
        ) else []
        for surface_id in boundary:
            if not self._attempt(record, surface_id, tenant, refs):
                self.ledger.checkpoint(record)
                return self._manifest(record, request)
            self.ledger.checkpoint(record)

        engine_ids = {("engine", "source_evidence"), ("engine", "sqlite")}
        for surface_id in required:
            if surface_id in engine_ids or surface_id in boundary:
                continue
            self._attempt(record, surface_id, tenant, refs)
            self.ledger.checkpoint(record)

        externals_verified = all(
            receipt.verified_removed
            for surface_id, receipt in record.receipts.items()
            if surface_id not in engine_ids
        )
        if externals_verified:
            self._attempt_engine(record, request)
            self.ledger.checkpoint(record)
        return self._manifest(record, request)

    def _surface_ids(self, tenant: str, refs: list[str]) -> list[tuple[str, str]]:
        surface_ids = [("store", name) for name in self.stores]
        surface_ids.extend(
            ("cache", key)
            for key, value in self.process_cache.items()
            if isinstance(value, dict)
            and value.get("tenant_id") == tenant
            and value.get("source_ref") in refs
        )
        if self._target_object_keys(tenant, refs):
            surface_ids.append(("object", "object_storage"))
        if any(row.get("tenant_id") == tenant and row.get("source_ref") in refs for row in self.backup_snapshots):
            surface_ids.append(("backup", "backups"))
        engine_surface = "sqlite" if self.engine.__class__.__name__ == "SqliteEngine" else "source_evidence"
        surface_ids.append(("engine", engine_surface))
        return list(dict.fromkeys(surface_ids))

    @staticmethod
    def _surface_label(surface_id: tuple[str, str]) -> str:
        kind, name = surface_id
        if kind == "cache":
            return f"cache:{name}"
        if kind == "store" and name == "runtime_state":
            return "runtime_user_model"
        return name

    def _attempt(self, record: LedgerRecord, surface_id: tuple[str, str], tenant: str, refs: list[str]) -> bool:
        kind, name = surface_id
        receipt = record.receipts[surface_id]
        if receipt.verified_removed:
            return True
        resuming = receipt.attempts > 0
        receipt.state = "deleting"
        receipt.error_code = None
        try:
            if kind == "object":
                receipt.attempts += 1
                self.ledger.checkpoint(record)
                return self._delete_objects(receipt, tenant, refs)
            if kind == "backup":
                receipt.attempts += 1
                self.ledger.checkpoint(record)
                return self._delete_backups(receipt, tenant, refs)
            if kind == "cache":
                receipt.attempts += 1
                self.ledger.checkpoint(record)
                if name in self.process_cache:
                    del self.process_cache[name]
                elif not resuming:
                    receipt.error_code = "probe_failed"
                    receipt.state = "failed"
                    return False
                receipt.action = "invalidated"
                return self._verified(receipt)
            store = self.stores[name]
            probed_absent: set[str] = set()
            destructive_attempted = False
            for ref in refs:
                if resuming:
                    try:
                        if self._probe_ref(store, tenant, ref):
                            probed_absent.add(ref)
                            continue
                    except Exception:
                        receipt.error_code = "probe_failed"
                        receipt.state = "failed"
                        return False
                try:
                    if not destructive_attempted:
                        receipt.attempts += 1
                        destructive_attempted = True
                        # Persist ambiguity before the external side effect.  A crash
                        # after commit therefore resumes by probing every reference.
                        self.ledger.checkpoint(record)
                    store.delete(tenant, ref)
                except TimeoutError:
                    receipt.error_code = "delete_ambiguous"
                    try:
                        if self._probe_ref(store, tenant, ref):
                            probed_absent.add(ref)
                            continue
                    except Exception:
                        pass
                    receipt.state = "failed"
                    return False
            if len(probed_absent) == len(refs):
                return self._verified(receipt)
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
    def _probe_ref(store: Any, tenant: str, ref: str) -> bool:
        probe = getattr(store, "probe", None)
        if callable(probe):
            return probe(tenant, ref) is False
        rows = getattr(store, "rows", None)
        if isinstance(rows, list):
            return not any(row.get("tenant_id") == tenant and row.get("source_ref") == ref for row in rows)
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
        receipt = record.receipts[("engine", surface)]
        if receipt.verified_removed:
            return
        receipt.state = "deleting"
        receipt.attempts += 1
        branches = ["main"]
        if request["branch_scope"] == "all":
            branches = list(getattr(self.engine, "branches", {"main": {}}))
        # Tenant custody keys must remain intact so retained audit rows remain
        # discoverable by their owning tenant; the durable journal stores only
        # a keyed opaque tenant reference.
        sensitive = {request["user_id"], *request["source_refs"]}
        for branch in branches:
            for ref in request["source_refs"]:
                evidence = self.engine.get_evidence(request["tenant_id"], ref, branch=branch)
                if evidence is not None:
                    sensitive.update(
                        self._strings(
                            (
                                evidence.content,
                                evidence.source_identity,
                                evidence.session_id,
                                evidence.content_pointer,
                            )
                        )
                    )
                    sensitive.update(self._strings(evidence.metadata, include_keys=True))
        sensitive.update(hashlib.sha256(value.encode()).hexdigest() for value in tuple(sensitive) if value)
        try:
            # Scrub while the evidence still exists so a crash after forget cannot
            # destroy the only copy of payload-derived scrub inputs. Replay can
            # always scrub the new forget custody rows from request-owned refs.
            self._scrub_retained_history(request["tenant_id"], sensitive)
            for branch in branches:
                for ref in request["source_refs"]:
                    self.engine.forget(
                        request["tenant_id"],
                        ref,
                        branch=branch,
                        requested_by="legal",
                        erasure_mode="hard_delete_legal",
                    )
            self._scrub_retained_history(request["tenant_id"], sensitive)
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

    @classmethod
    def _strings(cls, value: Any, *, include_keys: bool = False) -> set[str]:
        if isinstance(value, str):
            return {value}
        if isinstance(value, dict):
            strings = {
                item
                for nested in value.values()
                for item in cls._strings(nested, include_keys=include_keys)
            }
            if include_keys:
                strings.update(key for key in value if isinstance(key, str))
            return strings
        if isinstance(value, (list, tuple, set)):
            return {
                item
                for nested in value
                for item in cls._strings(nested, include_keys=include_keys)
            }
        return set()

    @classmethod
    def _scrub_value(cls, value: Any, sensitive: set[str]) -> Any:
        if isinstance(value, str) and any(needle and needle in value for needle in sensitive):
            return _opaque("retained-audit", value)
        if isinstance(value, dict):
            scrubbed = {}
            for key, item in value.items():
                scrubbed_key = cls._scrub_value(key, sensitive)
                if scrubbed_key in scrubbed:
                    scrubbed_key = _opaque("retained-audit-key", repr(key))
                scrubbed[scrubbed_key] = cls._scrub_value(item, sensitive)
            return scrubbed
        if isinstance(value, list):
            return [cls._scrub_value(item, sensitive) for item in value]
        if isinstance(value, tuple):
            return tuple(cls._scrub_value(item, sensitive) for item in value)
        return value

    def _scrub_retained_history(self, tenant_id: str, sensitive: set[str]) -> None:
        """Retain custody events while removing payload and correlatable references."""
        connect = getattr(self.engine, "_connect", None)
        if callable(connect) and self.engine.__class__.__name__ == "SqliteEngine":
            connection = connect(tenant_id)
            with connection:
                for table in ("audit_log", "deletion_log", "merge_log"):
                    for row in connection.execute(f"SELECT seq, record FROM {table}").fetchall():
                        record = json.loads(row["record"])
                        if record.get("tenant_id") != tenant_id:
                            continue
                        connection.execute(
                            f"UPDATE {table} SET record = ? WHERE seq = ?",
                            (json.dumps(self._scrub_value(record, sensitive), sort_keys=True), row["seq"]),
                        )
            return
        for attribute in ("audit_log", "deletion_log", "merge_log"):
            rows = getattr(self.engine, attribute, None)
            if isinstance(rows, list):
                rows[:] = [
                    self._scrub_value(row, sensitive) if row.get("tenant_id") == tenant_id else row
                    for row in rows
                ]

    def _manifest(self, record: LedgerRecord, request: dict[str, Any]) -> dict[str, Any]:
        rows = []
        unavailable = failed = verified = 0
        for surface_id, receipt in record.receipts.items():
            unavailable += receipt.error_code == "store_unavailable"
            failed += receipt.state == "failed" and receipt.error_code != "store_unavailable"
            verified += receipt.verified_removed
            rows.append(
                {
                    "surface": receipt.surface,
                    "surface_type": surface_id[0],
                    "backend": "synthetic",
                    "tenant_ref": _opaque("tenant", request["tenant_id"]),
                    "object_ref": _opaque("surface", f"{record.operation_id}:{surface_id!r}"),
                    "action": receipt.action,
                    "precondition_present": True,
                    "attempted_at": record.requested_at,
                    "verified_at": datetime.now(UTC).isoformat() if receipt.verified_removed else None,
                    "verification_method": "direct_and_public_probe",
                    "state": receipt.state,
                    "attempts": receipt.attempts,
                    "checkpoint": receipt.checkpoint,
                    "verified_removed": receipt.verified_removed,
                    "residue_probe": 0 if receipt.verified_removed else 1,
                    "durability_checkpoint": receipt.checkpoint,
                    "error_code": receipt.error_code,
                }
            )
        complete = bool(rows) and verified == len(rows)
        expected = len(rows)
        retention_exceptions = []
        backup_id = ("backup", "backups")
        if backup_id in record.receipts and not record.receipts[backup_id].verified_removed:
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
            "request_id": record.operation_id,
            "requested_at": record.requested_at,
            "completed_at": datetime.now(UTC).isoformat() if complete else None,
            "mode": request["mode"],
            "requested_by_role": request["requested_by_role"],
            "reason": _opaque("reason", request["reason"]),
            "tenant_ref": _opaque("tenant", request["tenant_id"]),
            "user_scope": _opaque("user", request["user_id"]),
            "branch_scope": request["branch_scope"],
            "source_refs": [_opaque("source", ref) for ref in request["source_refs"]],
            "policy": {
                "version": "w2",
                "required_surfaces": [receipt.surface for receipt in record.receipts.values()],
            },
            "fence": {"generation": record.generation, "ledger_position": record.generation, "durable": self.ledger.durable},
            "surfaces": rows,
            "stores": [
                {
                    "store": receipt.surface,
                    "expected": 1,
                    "discovered": 1,
                    "visited": int(receipt.attempts > 0),
                    "available": receipt.error_code != "store_unavailable",
                    "checkpoint": receipt.checkpoint,
                }
                for receipt in record.receipts.values()
            ],
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
