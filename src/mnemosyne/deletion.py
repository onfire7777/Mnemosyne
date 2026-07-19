"""Synthetic deletion orchestration with fail-closed, resumable receipts.

This module coordinates existing engine erasure and explicitly registered
synthetic surfaces.  The in-memory ledger is non-durable (tests/dev);
``SQLiteDeletionLedger`` is the durable resumable operation journal, and
``deletion_manifest`` provides the fail-closed semantic verifier.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, Sequence
from uuid import UUID
from weakref import WeakKeyDictionary

from .deletion_manifest import is_safe_surface_label
from .models import Evidence
from .security import SecurityPolicy, SessionIdentity

SCHEMA = "mnemosyne.deletion_manifest.v1"
_OPAQUE_KEY = secrets.token_bytes(32)
# Object schemes whose keys are envelope-encrypted, so dropping the key really
# does render the object unrecoverable.  Everything else fails closed.
_CRYPTO_SHREDDABLE_SCHEMES = frozenset({"local_encrypted", "s3_encrypted"})
# Structural vocabulary of retained custody records: audit/deletion/merge rows,
# the evidence fields their diffs embed, working-memory descriptors, and forget
# propagation summaries. A deleted metadata key that collides with one of these
# generic schema words is not custody-bearing, and opaquing it would rename the
# retained rows' own keys — structurally corrupting the custody history the
# scrub is required to preserve. Colliding *values* still scrub by needle.
_RETAINED_SCHEMA_KEYS = {
    "access_policy",
    "actor",
    "assertions_added",
    "assertions_merged",
    "at",
    "blocking_assertions",
    "branch",
    "capability_tags",
    "cid",
    "conflicts",
    "content",
    "content_pointer",
    "created_at",
    "diff",
    "embedding",
    "embedding_partition",
    "erased",
    "erased_derived_evidence",
    "erasure_mode",
    "evidence_added",
    "evidence_cid",
    "evidence_ids",
    "expired_relations",
    "from_branch",
    "id",
    "into_branch",
    "item_id",
    "metadata",
    "min_corroboration_for_delete",
    "modality",
    "op",
    "propagated",
    "reality_class",
    "reason",
    "relations_added",
    "removed_entities",
    "removed_intentions",
    "removed_working_items",
    "requested_by",
    "retained_derived_evidence",
    "retracted_assertions",
    "retracted_preferences",
    "sensitivity",
    "session_id",
    "signed_provenance",
    "source",
    "source_identity",
    "source_type",
    "target_id",
    "tenant_id",
    "trimmed_assertions",
    "trimmed_derived_evidence",
    "trimmed_entities",
    "trimmed_preferences",
    "trimmed_relations",
    "trimmed_working_items",
    "trust_tier",
    "user_id",
    "working_digest",
    "working_item_digest",
}


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
    attempted_at: str | None = None
    verified_at: str | None = None
    cross_tenant_mutations: int = 0
    # Persisted proof that this surface's destructive step actually ran.  Only
    # surfaces whose removal erases the target from its own registry need it, to
    # tell "already spliced" from "registry unreachable" on a crash resume.
    destructive_done: bool = False


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
    def opaque_name(self, kind: str, value: str) -> str: ...


class InMemoryDeletionLedger:
    """Process-local CAS ledger.  D5 replaces this with durable SQLite."""

    durable = False

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[str, LedgerRecord] = {}
        self._generations: dict[str, int] = {}

    def opaque_name(self, kind: str, value: str) -> str:
        return _opaque(kind, value)

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
        # Fail at construction, not mid-saga, on platforms without POSIX flock.
        import fcntl

        self._fcntl = fcntl
        self.path = Path(path)
        parent_created = not self.path.parent.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if parent_created:
            self.path.parent.chmod(0o700)
        # The ledger persists the opaque-name HMAC key; the DB (whose mode the
        # WAL/SHM sidecars inherit) and the lock file must stay owner-only or
        # any local reader gets the key plus the digests and can run the
        # offline dictionary attack the keyed opaquing exists to prevent.
        for artifact in (self.path, self.path.with_suffix(self.path.suffix + ".lock")):
            artifact.touch(mode=0o600, exist_ok=True)
            artifact.chmod(0o600)
        # Concurrent constructions (threads or other processes) race the initial
        # WAL conversion and schema/key bootstrap; serialize them under the same
        # cross-process lock that serializes operations.
        with self.operation_lock(), self._connection() as connection:
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

    @contextmanager
    def _connection(self) -> Any:
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            with connection:
                yield connection
        finally:
            connection.close()

    def opaque_name(self, kind: str, value: str) -> str:
        digest = hmac.new(self._opaque_key, f"{kind}\0{value}".encode(), hashlib.sha256).hexdigest()
        return f"opaque:{digest}"

    @contextmanager
    def operation_lock(self) -> Any:
        """Serialize coordinators sharing this ledger, including other processes."""
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        with lock_path.open("a+b") as lock_file:
            self._fcntl.flock(lock_file.fileno(), self._fcntl.LOCK_EX)
            try:
                yield
            finally:
                self._fcntl.flock(lock_file.fileno(), self._fcntl.LOCK_UN)

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
        stored_fingerprint = self.opaque_name("request", fingerprint)
        stored_tenant = self.opaque_name("tenant", tenant_id)
        with self._connection() as connection:
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
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE deletion_operations SET receipts_json = ?, manifest_json = ?, "
                "revision = revision + 1 WHERE operation_id = ? AND fingerprint = ? AND revision = ?",
                (
                    self._receipts(record),
                    json.dumps(record.manifest, sort_keys=True) if record.manifest is not None else None,
                    record.operation_id,
                    self.opaque_name("request", record.fingerprint),
                    record.revision,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("deletion ledger checkpoint conflict")
            record.revision += 1

    def current_generation(self, tenant_id: str) -> int:
        with self._connection() as connection:
            return connection.execute(
                "SELECT COALESCE(MAX(generation), 0) FROM deletion_operations WHERE tenant_id = ?",
                (self.opaque_name("tenant", tenant_id),),
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
        with self.ledger.operation_lock():
            record = self.ledger.begin(request["operation_id"], fingerprint, tenant_id)
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
        return {
            **raw,
            "operation_id": str(parsed),
            "source_refs": normalized_refs,
        }

    def _run(self, record: LedgerRecord, request: dict[str, Any]) -> dict[str, Any]:
        tenant = request["tenant_id"]
        refs = request["source_refs"]
        required = list(dict.fromkeys([*self._surface_ids(tenant, refs), *record.receipts]))
        for surface_id in required:
            record.receipts.setdefault(surface_id, SurfaceReceipt(surface=self._surface_label(surface_id)))
        self.ledger.checkpoint(record)

        # Boundary stores must be available before other external effects.  This
        # is a precondition gate, not rollback; verified deletions are never restored.
        # The object surface joins the boundary only when a receipt exists for it,
        # i.e. under the same condition _surface_ids uses.
        boundary = [
            ("store", self._store_surface_name(name))
            for name in ("journal", "manifest_store")
            if name in self.stores
        ]
        if self._target_object_keys(tenant, refs):
            boundary.append(("object", "object_storage"))
        for surface_id in boundary:
            attempted = self._attempt(record, surface_id, tenant, refs)
            self.ledger.checkpoint(record)
            if not attempted:
                return self._manifest(record, request)

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

    def _is_sqlite_engine(self) -> bool:
        # Lazy import keeps this module light; isinstance (not class-name text)
        # keeps SqliteEngine subclasses on the SQL scrub path instead of silently
        # falling through to the in-memory attribute scan.
        from .sqlite_engine import SqliteEngine

        return isinstance(self.engine, SqliteEngine)

    def _evidence_present(self, tenant_id: str, ref: str, branch: str) -> bool:
        # ``get_evidence`` masks erased tombstones, but a tombstone row still
        # holds every column except content and must count as present until the
        # legal shred removes it — otherwise a resume skips it and the manifest
        # attests zero residue over a recoverable row.
        return (
            self.engine.get_evidence(tenant_id, ref, branch=branch) is not None
            or self.engine.evidence_is_erased(tenant_id, ref, branch=branch)
        )

    def _fetch_evidence_unmasked(self, tenant_id: str, ref: str, branch: str) -> Evidence | None:
        """Store-core row fetch feeding the scrub needles.

        A previously tombstoned target is invisible to ``get_evidence`` yet its
        surviving columns (metadata, source_identity, session_id,
        content_pointer) are exactly the custody values the retained-history
        scrub must opaque before the legal shred destroys the only copy.
        """
        evidence = self.engine.get_evidence(tenant_id, ref, branch=branch)
        if evidence is not None:
            return evidence
        if not self.engine.evidence_is_erased(tenant_id, ref, branch=branch):
            return None
        if self._is_sqlite_engine():
            with self.engine._lock:
                return self.engine._fetch_evidence(tenant_id, ref, branch)
        rows = getattr(self.engine, "evidence", None)
        if isinstance(rows, dict):
            with self.engine._lock:
                row = rows.get(self.engine._evidence_key(tenant_id, branch, ref))
                return deepcopy(row) if row is not None else None
        return None

    def _surface_ids(self, tenant: str, refs: list[str]) -> list[tuple[str, str]]:
        surface_ids = [("store", self._store_surface_name(name)) for name in self.stores]
        surface_ids.extend(
            ("cache", self._cache_surface_name(key))
            for key, value in self.process_cache.items()
            if isinstance(value, dict)
            and value.get("tenant_id") == tenant
            and value.get("source_ref") in refs
        )
        if self._target_object_keys(tenant, refs):
            surface_ids.append(("object", "object_storage"))
        if any(row.get("tenant_id") == tenant and row.get("source_ref") in refs for row in self.backup_snapshots):
            surface_ids.append(("backup", "backups"))
        engine_surface = "sqlite" if self._is_sqlite_engine() else "source_evidence"
        surface_ids.append(("engine", engine_surface))
        return list(dict.fromkeys(surface_ids))

    def _surface_label(self, surface_id: tuple[str, str]) -> str:
        kind, name = surface_id
        if kind == "cache":
            return f"cache:{name}"
        if kind == "store":
            name = self._store_for_surface(name) or name
            # The alias would collide with a real runtime_user_model store and
            # make an otherwise complete deletion permanently unattestable
            # (the verifier rejects duplicate labels); opaque the alias instead.
            if name == "runtime_state" and "runtime_user_model" not in self.stores:
                return "runtime_user_model"
        return name if is_safe_surface_label(name) else _opaque("surface-label", name)

    def _cache_surface_name(self, key: str) -> str:
        # Keyed by the ledger so a manifest holder cannot confirm a guessed cache
        # key offline; the durable ledger persists its key, keeping resume stable.
        return self.ledger.opaque_name("cache-surface", key)

    def _store_surface_name(self, name: str) -> str:
        # Store names are caller-registered and may carry identifiers; only the
        # ledger-keyed opaque name may reach the durable journal.
        return self.ledger.opaque_name("store-surface", name)

    def _store_for_surface(self, surface_name: str) -> str | None:
        return next(
            (name for name in self.stores if self._store_surface_name(name) == surface_name),
            None,
        )

    def _attempt(self, record: LedgerRecord, surface_id: tuple[str, str], tenant: str, refs: list[str]) -> bool:
        kind, name = surface_id
        receipt = record.receipts[surface_id]
        if receipt.verified_removed:
            return True
        # A persisted "deleting" state is a crash mid-attempt; a persisted
        # "failed" state is a completed fail-closed outcome that a plain retry
        # must not soften into a resume.
        crash_resuming = receipt.attempts > 0 and receipt.state == "deleting"
        resuming = receipt.attempts > 0
        receipt.state = "deleting"
        receipt.error_code = None
        if kind in {"object", "backup", "cache"}:
            receipt.attempts += 1
            receipt.attempted_at = datetime.now(UTC).isoformat()
            # Ledger checkpoint faults are journal infrastructure failures and
            # propagate; only surface interactions are recorded on the receipt.
            self.ledger.checkpoint(record)
            try:
                if kind == "object":
                    return self._delete_objects(receipt, tenant, refs)
                if kind == "backup":
                    return self._delete_backups(record, receipt, tenant, refs)
                cache_key = next(
                    (key for key in self.process_cache if self._cache_surface_name(key) == name),
                    None,
                )
                if cache_key is not None:
                    del self.process_cache[cache_key]
                elif not crash_resuming:
                    receipt.error_code = "probe_failed"
                    receipt.state = "failed"
                    return False
                receipt.action = "invalidated"
                return self._verified(receipt)
            except ConnectionError:
                receipt.error_code = "store_unavailable"
            except Exception:
                receipt.error_code = "delete_failed"
            receipt.state = "failed"
            return False
        store_name = self._store_for_surface(name)
        if store_name is None:
            receipt.error_code = "store_unavailable"
            receipt.state = "failed"
            return False
        store = self.stores[store_name]
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
            if not destructive_attempted:
                receipt.attempts += 1
                destructive_attempted = True
                receipt.attempted_at = datetime.now(UTC).isoformat()
                # Persist ambiguity before the external side effect.  A crash
                # after commit therefore resumes by probing every reference.
                self.ledger.checkpoint(record)
            try:
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
            except ConnectionError:
                receipt.error_code = "store_unavailable"
                receipt.state = "failed"
                return False
            except Exception:
                receipt.error_code = "delete_failed"
                receipt.state = "failed"
                return False
        if len(probed_absent) == len(refs):
            return self._verified(receipt)
        try:
            if not self._probe_store(store, tenant, refs):
                receipt.error_code = "probe_failed"
                receipt.state = "failed"
                return False
        except ConnectionError:
            receipt.error_code = "store_unavailable"
            receipt.state = "failed"
            return False
        except Exception:
            receipt.error_code = "delete_failed"
            receipt.state = "failed"
            return False
        return self._verified(receipt)

    @staticmethod
    def _probe_ref(store: Any, tenant: str, ref: str) -> bool:
        probe = getattr(store, "probe", None)
        if callable(probe):
            return probe(tenant, ref) is False
        rows = getattr(store, "rows", None)
        if isinstance(rows, list):
            return not any(row.get("tenant_id") == tenant and row.get("source_ref") == ref for row in rows)
        return False

    @classmethod
    def _probe_store(cls, store: Any, tenant: str, refs: list[str]) -> bool:
        # Absence of every ref is exactly the conjunction of the per-ref probe,
        # for both backend shapes.  Deriving it keeps one duck-typing ladder, so
        # a third backend shape cannot be taught to _probe_ref alone and leave
        # this one silently reporting "not absent" for it.  `refs` is guarded
        # because an empty conjunction is vacuously true, and this probe must
        # fail closed rather than attest absence it never observed.
        return bool(refs) and all(cls._probe_ref(store, tenant, ref) for ref in refs)

    def _target_object_keys(self, tenant: str, refs: list[str]) -> list[str]:
        # Enumerate by tenant/ref path, not by a scheme allow-list: a key stored
        # under an unrecognised scheme is still this tenant's object and must
        # surface as an un-shreddable target.  Filtering it out here would drop
        # the object_storage surface entirely and let the manifest attest 100%
        # cascade with zero residue while the object survives intact.
        targets = {f"{tenant}/{ref}" for ref in refs}
        return [
            key
            for key in self.object_keys
            if key.partition("://")[1] and key.partition("://")[2] in targets
        ]

    def _delete_objects(
        self, receipt: SurfaceReceipt, tenant: str, refs: list[str]
    ) -> bool:
        keys = self._target_object_keys(tenant, refs)
        if not keys:
            # A receipt for this surface exists, so targets were enumerated when
            # the operation began.  Finding none now means this coordinator was
            # rebuilt without the object registry (a durable resume in a fresh
            # process), not that the shred succeeded -- crypto-shredding nothing
            # must never attest that the keys are gone.
            #
            # There is deliberately no crash-resume exemption here: the shred
            # blanks the key's *value* and leaves the registry entry in place,
            # and _target_object_keys matches on the tenant/ref path alone, so a
            # successfully shredded key is still enumerated on a re-attempt.  An
            # empty set is therefore always an unreachable registry, and
            # exempting a resume would let a crash mid-shred attest
            # crypto_shredded over key material that survives intact.
            receipt.error_code = "probe_failed"
            receipt.state = "failed"
            return False
        if any(key.partition("://")[0] not in _CRYPTO_SHREDDABLE_SCHEMES for key in keys):
            # Fail closed on "plain://" and on any scheme this coordinator has no
            # shred procedure for; dropping the key to None only destroys a
            # reference, so attesting removal would be false.
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

    def _delete_backups(
        self, record: LedgerRecord, receipt: SurfaceReceipt, tenant: str, refs: list[str]
    ) -> bool:
        targets = [row for row in self.backup_snapshots if row.get("tenant_id") == tenant and row.get("source_ref") in refs]
        if not targets and not receipt.destructive_done:
            # Unlike the object shred, the splice removes its targets from the
            # registry, so an empty set is genuinely ambiguous: either the
            # snapshots were already spliced or the registry is unreachable.
            # Only the persisted destructive_done marker distinguishes them.
            # Without it, fail closed -- a crash before the marker was
            # checkpointed costs a re-attempt, whereas trusting the empty set
            # would attest a removal this coordinator never made.
            receipt.error_code = "probe_failed"
            receipt.state = "failed"
            return False
        if any(not row.get("available", True) or row.get("immutable", False) for row in targets):
            receipt.error_code = "retention_exception"
            receipt.state = "failed"
            return False
        self.backup_snapshots[:] = [row for row in self.backup_snapshots if row not in targets]
        # Persist the marker before attesting so a crash between the splice and
        # the verified checkpoint resumes as "already spliced" rather than as an
        # unreachable registry.
        receipt.destructive_done = True
        self.ledger.checkpoint(record)
        return self._verified(receipt)

    @staticmethod
    def _verified(receipt: SurfaceReceipt) -> bool:
        receipt.state = "verified"
        # Recovery paths (e.g. timeout confirmed absent by probe) may have set a
        # transient error code; a verified surface must not carry one.
        receipt.error_code = None
        receipt.verified_removed = True
        receipt.verified_at = datetime.now(UTC).isoformat()
        receipt.checkpoint = secrets.token_hex(8)
        return True

    def _attempt_engine(self, record: LedgerRecord, request: dict[str, Any]) -> None:
        surface = "sqlite" if self._is_sqlite_engine() else "source_evidence"
        receipt = record.receipts[("engine", surface)]
        if receipt.verified_removed:
            return
        # Any prior attempt means targets may already be gone, so probe before
        # re-forgetting.  But only a persisted "deleting" state is a crash
        # mid-attempt; a completed "failed" outcome retried here is a *new*
        # destructive pass and must re-stamp and re-checkpoint like the first.
        resuming = receipt.attempts > 0
        crash_resuming = resuming and receipt.state == "deleting"
        receipt.state = "deleting"
        branches = ["main"]
        if request["branch_scope"] == "all":
            branches = list(getattr(self.engine, "branches", {"main": {}}))
        # Tenant custody keys must remain intact so retained audit rows remain
        # discoverable by their owning tenant; the durable journal stores only
        # a keyed opaque tenant reference.
        sensitive = {request["user_id"], *request["source_refs"]}
        sensitive_keys: set[str] = set()
        for branch in branches:
            for ref in request["source_refs"]:
                evidence = self._fetch_evidence_unmasked(request["tenant_id"], ref, branch)
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
                    sensitive.update(self._strings(evidence.metadata))
                    sensitive_keys.update(
                        self._mapping_keys(evidence.metadata) - _RETAINED_SCHEMA_KEYS
                    )
        sensitive.update(hashlib.sha256(value.encode()).hexdigest() for value in tuple(sensitive) if value)
        try:
            # Scrub while the evidence still exists so a crash after forget cannot
            # destroy the only copy of payload-derived scrub inputs. Replay can
            # always scrub the new forget custody rows from request-owned refs.
            receipt.cross_tenant_mutations = self._scrub_retained_history(
                request["tenant_id"], sensitive, sensitive_keys
            )
        except Exception:
            receipt.error_code = "delete_failed"
            receipt.state = "failed"
            return
        if not crash_resuming:
            receipt.attempts += 1
            receipt.attempted_at = datetime.now(UTC).isoformat()
            # Persist the ambiguous state before the engine side effect. A
            # restarted operation probes each target before deciding whether
            # another destructive call is necessary.  Ledger checkpoint faults
            # are journal infrastructure failures and propagate.
            self.ledger.checkpoint(record)
        try:
            for branch in branches:
                for ref in request["source_refs"]:
                    if resuming and not self._evidence_present(
                        request["tenant_id"], ref, branch
                    ):
                        continue
                    self.engine.forget(
                        request["tenant_id"],
                        ref,
                        branch=branch,
                        requested_by="legal",
                        erasure_mode="hard_delete_legal",
                    )
            receipt.cross_tenant_mutations += self._scrub_retained_history(
                request["tenant_id"], sensitive, sensitive_keys
            )
            if any(
                self._evidence_present(request["tenant_id"], ref, branch)
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
    def _strings(cls, value: Any) -> set[str]:
        if isinstance(value, str):
            return {value}
        if isinstance(value, dict):
            return {item for nested in value.values() for item in cls._strings(nested)}
        if isinstance(value, (list, tuple, set)):
            return {item for nested in value for item in cls._strings(nested)}
        return set()

    @classmethod
    def _mapping_keys(cls, value: Any) -> set[str]:
        if isinstance(value, dict):
            return {
                *[key for key in value if isinstance(key, str)],
                *[
                    key
                    for nested in value.values()
                    for key in cls._mapping_keys(nested)
                ],
            }
        if isinstance(value, (list, tuple, set)):
            return {
                key for nested in value for key in cls._mapping_keys(nested)
            }
        return set()

    @classmethod
    def _scrub_value(cls, value: Any, sensitive: set[str], sensitive_keys: set[str]) -> Any:
        if isinstance(value, str) and any(
            needle and (value == needle or (len(needle) >= 8 and needle in value))
            for needle in sensitive
        ):
            return _opaque("retained-audit", value)
        if isinstance(value, dict):
            scrubbed = {}
            for key, item in value.items():
                if key == "tenant_id":
                    # Tenant attribution is structural custody, not payload: both
                    # scrub paths select rows by it, so opaquing it would hide the
                    # row from every later deletion while the manifest still
                    # attests zero residue.  Deleted metadata may *contain* the
                    # tenant id (or an >=8-char substring of it) and would
                    # otherwise seed a needle that rewrites this field.
                    scrubbed[key] = item
                    continue
                scrubbed_key = (
                    _opaque("retained-audit-key", key)
                    if isinstance(key, str) and key in sensitive_keys
                    else cls._scrub_value(key, sensitive, sensitive_keys)
                )
                if scrubbed_key in scrubbed:
                    scrubbed_key = _opaque("retained-audit-key", repr(key))
                if scrubbed_key in scrubbed:
                    # Both the scrubbed key and its disambiguated form are
                    # occupied (a planted audit row can hold either).  Dropping
                    # one would silently delete a field from the custody record
                    # this scrub must preserve, so fail closed instead;
                    # _attempt_engine turns this into a delete_failed receipt
                    # before any destructive forget call.
                    raise ValueError("retained-history scrub key collision")
                scrubbed[scrubbed_key] = cls._scrub_value(item, sensitive, sensitive_keys)
            return scrubbed
        if isinstance(value, list):
            return [cls._scrub_value(item, sensitive, sensitive_keys) for item in value]
        if isinstance(value, tuple):
            return tuple(cls._scrub_value(item, sensitive, sensitive_keys) for item in value)
        return value

    def _scrub_retained_history(
        self, tenant_id: str, sensitive: set[str], sensitive_keys: set[str]
    ) -> int:
        """Retain custody events while removing payload and correlatable references.

        Returns the number of rows actually rewritten that are not attributed to
        this tenant, so the manifest can report a measured cross-tenant mutation
        count instead of asserting zero.
        """
        cross_tenant = 0
        if self._is_sqlite_engine():
            # The engine shares one cached connection per tenant and serializes all
            # access through its lock; hold it so this scrub transaction cannot
            # interleave with (or commit/roll back) another thread's engine write.
            with self.engine._lock:
                connection = self.engine._connect(tenant_id)
                with connection:
                    for table in ("audit_log", "deletion_log", "merge_log"):
                        # Select on the tenant_id *column*, which this scrub never
                        # rewrites.  Gating on the JSON copy would let a scrubbed
                        # attribution field permanently hide the row from later
                        # deletions of the same tenant.
                        rows = connection.execute(
                            f"SELECT seq, tenant_id, record FROM {table}"
                        ).fetchall()
                        for row in rows:
                            record = json.loads(row["record"])
                            # Merge records embed no tenant_id and engine merges
                            # may audit under the "*" wildcard; both are custody
                            # rows of this tenant's own database and must scrub.
                            if row["tenant_id"] not in (tenant_id, "*", None):
                                continue
                            scrubbed = self._scrub_value(record, sensitive, sensitive_keys)
                            if scrubbed == record:
                                continue
                            # Rows reaching here passed the selection filter, so
                            # they are this tenant's own custody -- its rows, its
                            # merge rows, its wildcard audits.  Count only a
                            # genuinely foreign owner so the manifest reports a
                            # measured zero instead of an asserted one; counting
                            # the wildcard/merge rows here would make every
                            # deletion of a tenant with merge history fail the
                            # verifier's cross_tenant_mutations == 0 requirement
                            # and become permanently unsignable.
                            if row["tenant_id"] is not None and row["tenant_id"] not in (tenant_id, "*"):
                                cross_tenant += 1
                            connection.execute(
                                f"UPDATE {table} SET record = ? WHERE seq = ?",
                                (json.dumps(scrubbed, sort_keys=True), row["seq"]),
                            )
                    # Retracted/trimmed assertions survive forget with their
                    # calibration JSON; scrub it exactly like the in-memory
                    # engine's assertions below.  Untouched rows keep their
                    # canonical bytes (json_text sorts keys the same way).
                    for row in connection.execute(
                        "SELECT rowid, calibration FROM assertions WHERE tenant_id = ?",
                        (tenant_id,),
                    ).fetchall():
                        calibration = json.loads(row["calibration"])
                        scrubbed = self._scrub_value(calibration, sensitive, sensitive_keys)
                        if scrubbed != calibration:
                            connection.execute(
                                "UPDATE assertions SET calibration = ? WHERE rowid = ?",
                                (json.dumps(scrubbed, sort_keys=True), row["rowid"]),
                            )
            return cross_tenant
        logs = [
            getattr(self.engine, attribute, None)
            for attribute in ("audit_log", "deletion_log", "merge_log")
        ]
        assertions = getattr(self.engine, "assertions", None)
        if (
            not all(isinstance(rows, list) for rows in logs)
            or not isinstance(assertions, dict)
            or not isinstance(getattr(self.engine, "evidence", None), dict)
        ):
            # Fail closed: an engine whose custody history this scrub cannot
            # reach (e.g. a PostgreSQL backend keeping logs in server-side
            # tables) must fail the engine receipt rather than let the
            # manifest attest a scrub that never happened.  PostgreSQL
            # retained-history support is a recorded D5B/D6 obligation.
            raise TypeError(
                "retained-history scrub supports only SqliteEngine or "
                f"in-memory engines, not {type(self.engine).__name__}"
            )
        # Hold the engine lock for the same reason the SQLite branch does: the
        # engine guards all its own writes with it and in places rebinds
        # audit_log wholesale, so an unlocked scrub can miss a row appended
        # mid-scan (while the manifest still attests zero residue) or be undone
        # by a rollback restoring pre-scrub contents.
        lock = getattr(self.engine, "_lock", nullcontext())
        with lock:
            for rows in logs:
                # Rows attributed to another tenant stay byte-identical; merge
                # rows (no tenant_id) and "*" wildcard audits are unattributable
                # shared custody and must scrub by needle.
                for index, row in enumerate(rows):
                    owner = row.get("tenant_id")
                    if owner not in (tenant_id, "*", None):
                        continue
                    scrubbed = self._scrub_value(row, sensitive, sensitive_keys)
                    if scrubbed == row:
                        continue
                    # See the SQLite branch: wildcard and merge rows are this
                    # tenant's own custody, not another tenant's mutation.
                    if owner is not None and owner not in (tenant_id, "*"):
                        cross_tenant += 1
                    rows[index] = scrubbed
            for assertion in assertions.values():
                if getattr(assertion, "tenant_id", None) == tenant_id:
                    assertion.calibration = self._scrub_value(
                        assertion.calibration, sensitive, sensitive_keys
                    )
        return cross_tenant

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
                    "attempted_at": receipt.attempted_at,
                    "verified_at": receipt.verified_at if receipt.verified_removed else None,
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
                "required_surfaces": [
                    {"surface_type": surface_id[0], "surface": receipt.surface}
                    for surface_id, receipt in record.receipts.items()
                ],
            },
            "fence": {"generation": record.generation, "ledger_position": record.generation, "durable": self.ledger.durable},
            "surfaces": rows,
            "stores": [
                {
                    "store": receipt.surface,
                    "surface_type": surface_id[0],
                    "expected": 1,
                    "discovered": 1,
                    "visited": int(receipt.attempts > 0),
                    "available": receipt.error_code != "store_unavailable",
                    "checkpoint": receipt.checkpoint,
                }
                for surface_id, receipt in record.receipts.items()
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
                "cross_tenant_mutations": sum(
                    receipt.cross_tenant_mutations for receipt in record.receipts.values()
                ),
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
