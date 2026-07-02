"""SQLite MemoryEngine backend — one WAL database file per tenant (spec §4.2).

Phase-2 Task 2 ships the store core: construction (kwargs mirror
``LocalMemoryEngine``), per-tenant file mapping through
``journal.safe_tenant_filename`` (hostile tenant ids hash into the root
directory, never out of it), pragma discipline on every connect
(``journal_mode=WAL``, ``synchronous=FULL``, ``foreign_keys=ON``,
``busy_timeout=5000`` plus a ``PRAGMA integrity_check`` on first open per
file), the 13-collection schema (:mod:`mnemosyne.sqlite_schema`), and Evidence
row marshalling that round-trips byte-identically against the
LocalMemoryEngine oracle.

Decisions locked by the Phase-2 grounding (do not relitigate):

* external tenant/user/session ids stored VERBATIM — no uuid5 mapping (CR-03);
* every TEXT timestamp is a ``models.dt_to_json`` string (trailing ``"Z"``)
  and every SQL comparison parameter must use the same serializer — never raw
  ``datetime.isoformat()`` output;
* CIDs stored as TEXT hex; embeddings as packed little-endian f64 BLOBs;
* backend names ``sqlite-fts5`` / ``sqlite-cached-ppr`` (outside the
  ``local-`` forbid_local denylist).

Phase-2 Task 3 adds the ledger surface (``append_evidence`` with the
erased-replay blocklist + CID-journal wiring, ``get_evidence``,
``update_evidence_metadata``, ``set_evidence_embedding``,
``backfill_evidence_privacy``, and the ``export_tenant`` /
``export_tenant_filtered`` / ``export_all`` byte-compatible exports) over
these primitives, reproducing ``LocalMemoryEngine``'s flow exactly. The
remaining ``MemoryEngine`` Protocol methods stay ``NotImplementedError`` stubs
naming their Phase-2 task, so ``isinstance(engine, MemoryEngine)`` already
holds — the runtime_checkable Protocol checks method presence.
"""
from __future__ import annotations

import copy
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from mnemosyne.access_policy import (
    filter_export_for_context,
    may_embed_item,
    validate_access_policy,
    vector_partition_for_item,
)
from mnemosyne.calibration import CalibrationSet
from mnemosyne.engine import (
    LocalMemoryEngine,
    _normalise_privacy_tags,
    _privacy_backfill_access_policy,
    _privacy_backfill_controls,
    _privacy_backfill_metadata,
)
from mnemosyne.ids import evidence_cid, evidence_unscoped_cid, new_id
from mnemosyne.journal import CIDJournal, journal_filename, safe_tenant_filename
from mnemosyne.models import (
    Assertion,
    Evidence,
    Hit,
    MergeReport,
    Preference,
    Relation,
    RetrievalResult,
    dt_to_json,
    utc_now,
)
from mnemosyne.policy import OperatingPolicy
from mnemosyne.privacy import ErasureMode
from mnemosyne.retrieval import (
    HashingEmbeddingProvider,
    LocalSimilarityReranker,
    RetrievalAdapters,
)
from mnemosyne.sqlite_schema import (
    ENSURE_STATEMENTS,
    PRAGMA_STATEMENTS,
    SCHEMA_VERSION,
    json_text,
    pack_embedding,
    unpack_embedding,
)
from mnemosyne.workspace import self_generation_budget_report

LEXICAL_BACKEND = "sqlite-fts5"
GRAPH_BACKEND = "sqlite-cached-ppr"

_EVIDENCE_INSERT = """
INSERT INTO evidence (
    tenant_id, branch, cid, user_id, actor, source_type, content,
    source_identity, session_id, metadata, content_pointer, modality,
    embedding, signed_provenance, trust_tier, capability_tags, sensitivity,
    access_policy, created_at, erased
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _evidence_from_row(row: sqlite3.Row) -> Evidence:
    """Rehydrate an evidence row through the exact model constructor."""
    signed_provenance = row["signed_provenance"]
    return Evidence.from_dict(
        {
            "tenant_id": row["tenant_id"],
            "user_id": row["user_id"],
            "actor": row["actor"],
            "source_type": row["source_type"],
            "content": row["content"],
            "source_identity": row["source_identity"],
            "session_id": row["session_id"],
            "metadata": json.loads(row["metadata"]),
            "content_pointer": row["content_pointer"],
            "modality": row["modality"],
            "embedding": unpack_embedding(row["embedding"]),
            "signed_provenance": None if signed_provenance is None else json.loads(signed_provenance),
            "trust_tier": row["trust_tier"],
            "capability_tags": json.loads(row["capability_tags"]),
            "sensitivity": row["sensitivity"],
            "access_policy": json.loads(row["access_policy"]),
            "branch": row["branch"],
            "cid": row["cid"],
            "created_at": row["created_at"],
            "erased": bool(row["erased"]),
        }
    )


def _assertion_from_row(row: sqlite3.Row) -> Assertion:
    """Rehydrate an assertion row through ``Assertion.from_dict`` (Task-5 writers
    populate these columns; Task-3 export reads them so exports stay complete)."""
    return Assertion.from_dict(
        {
            "tenant_id": row["tenant_id"],
            "branch": row["branch"],
            "id": row["id"],
            "user_id": row["user_id"],
            "subject": row["subject"],
            "predicate": row["predicate"],
            "object": row["object"],
            "scope": json.loads(row["scope"]),
            "confidence": row["confidence"],
            "calibration": json.loads(row["calibration"]),
            "valid_from": row["valid_from"],
            "valid_to": row["valid_to"],
            "transaction_time": row["transaction_time"],
            "expired_at": row["expired_at"],
            "justification_id": row["justification_id"],
            "source_evidence_cids": json.loads(row["source_evidence_cids"]),
            "status": row["status"],
            "version": row["version"],
            "superseded_by": row["superseded_by"],
            "trust_tier": row["trust_tier"],
            "sensitivity": row["sensitivity"],
            "access_policy": json.loads(row["access_policy"]),
            "last_accessed": row["last_accessed"],
            "access_count": row["access_count"],
        }
    )


def _relation_from_row(row: sqlite3.Row) -> Relation:
    """Rehydrate a relation row through ``Relation.from_dict``."""
    return Relation.from_dict(
        {
            "tenant_id": row["tenant_id"],
            "branch": row["branch"],
            "id": row["id"],
            "source": row["source"],
            "predicate": row["predicate"],
            "target": row["target"],
            "confidence": row["confidence"],
            "valid_from": row["valid_from"],
            "valid_to": row["valid_to"],
            "source_evidence_cids": json.loads(row["source_evidence_cids"]),
            "access_policy": json.loads(row["access_policy"]),
        }
    )


class SqliteEngine:
    """One-SQLite-file-per-tenant engine; LocalMemoryEngine is the parity oracle."""

    def __init__(
        self,
        root_dir: str | Path,
        policy: OperatingPolicy | None = None,
        adapters: RetrievalAdapters | None = None,
        journal_dir: str | Path | None = None,
    ):
        self.root_dir = Path(root_dir).expanduser()
        root_created = not self.root_dir.exists()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        if root_created:
            self.root_dir.chmod(0o700)
        self._journal_dir = Path(journal_dir).expanduser() if journal_dir else None
        self.policy = policy or OperatingPolicy()
        if adapters is None:
            embedding = HashingEmbeddingProvider()
            adapters = RetrievalAdapters(
                embedding=embedding,
                reranker=LocalSimilarityReranker(embedding_provider=embedding),
                lexical_backend=LEXICAL_BACKEND,
                graph_backend=GRAPH_BACKEND,
            )
        self.adapters = adapters
        self._lock = threading.RLock()
        self._connections: dict[str, sqlite3.Connection] = {}
        self._integrity_checked: set[str] = set()

    # --- store core (connections, schema, row marshalling) -------------------

    def _tenant_db_path(self, tenant_id: str) -> Path:
        """Per-tenant database path; hostile ids hash inside ``root_dir``."""
        return self.root_dir / safe_tenant_filename(tenant_id, ".db")

    def _connect(self, tenant_id: str) -> sqlite3.Connection:
        """Open (or reuse) the tenant connection with pragmas + schema applied."""
        with self._lock:
            path = self._tenant_db_path(tenant_id)
            key = str(path)
            cached = self._connections.get(key)
            if cached is not None:
                return cached
            existed = path.exists()
            conn = sqlite3.connect(path, check_same_thread=False)
            try:
                conn.row_factory = sqlite3.Row
                try:
                    for pragma in PRAGMA_STATEMENTS:
                        conn.execute(pragma)
                    if key not in self._integrity_checked:
                        self._run_integrity_check(conn, path)
                        self._integrity_checked.add(key)
                    self._ensure_schema(conn, tenant_id)
                except sqlite3.DatabaseError as exc:
                    raise RuntimeError(f"sqlite store failed to open cleanly at {path}: {exc}") from exc
            except Exception:
                conn.close()
                raise
            if not existed:
                path.chmod(0o600)
            self._connections[key] = conn
            return conn

    @staticmethod
    def _run_integrity_check(conn: sqlite3.Connection, path: Path) -> None:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        result = row[0] if row else "missing integrity_check result"
        if result != "ok":
            raise RuntimeError(f"sqlite integrity_check failed for {path}: {result}")

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection, tenant_id: str) -> None:
        with conn:
            for statement in ENSURE_STATEMENTS:
                conn.execute(statement)
            conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            conn.execute(
                "INSERT OR IGNORE INTO branches(tenant_id, name, from_branch, kind, created_at) "
                "VALUES (?, 'main', NULL, 'protected', ?)",
                (tenant_id, dt_to_json(utc_now())),
            )

    def close(self) -> None:
        """Close every cached tenant connection (tests / shutdown)."""
        with self._lock:
            for conn in self._connections.values():
                conn.close()
            self._connections.clear()

    def _insert_evidence(self, ev: Evidence) -> None:
        """Store-core evidence row write (append_evidence layers CID computation,
        policy gates, dedup, and journal wiring on top). Opens its own
        transaction; ``append_evidence`` uses :meth:`_insert_evidence_row` to
        share one commit with the audit write."""
        conn = self._connect(ev.tenant_id)
        with self._lock, conn:
            self._insert_evidence_row(conn, ev)

    @staticmethod
    def _insert_evidence_row(conn: sqlite3.Connection, ev: Evidence) -> None:
        """Execute the evidence INSERT on ``conn`` without owning the transaction."""
        if not ev.cid:
            raise ValueError("sqlite evidence rows require a cid")
        conn.execute(
            _EVIDENCE_INSERT,
            (
                ev.tenant_id,
                ev.branch,
                ev.cid,
                ev.user_id,
                ev.actor,
                ev.source_type,
                ev.content,
                ev.source_identity,
                ev.session_id,
                json_text(ev.metadata),
                ev.content_pointer,
                ev.modality,
                pack_embedding(ev.embedding),
                None if ev.signed_provenance is None else json_text(ev.signed_provenance),
                int(ev.trust_tier),
                json_text(ev.capability_tags),
                int(ev.sensitivity),
                json_text(ev.access_policy),
                dt_to_json(ev.created_at),
                int(bool(ev.erased)),
            ),
        )

    @staticmethod
    def _write_evidence_mutable(conn: sqlite3.Connection, ev: Evidence) -> None:
        """Rewrite the mutable evidence columns from ``ev`` (content/erased kept
        for forget reuse; Task-3 metadata/embedding/sensitivity/access_policy
        paths pass current values for the untouched columns)."""
        conn.execute(
            "UPDATE evidence SET content = ?, metadata = ?, embedding = ?, "
            "sensitivity = ?, access_policy = ?, erased = ? "
            "WHERE tenant_id = ? AND branch = ? AND cid = ?",
            (
                ev.content,
                json_text(ev.metadata),
                pack_embedding(ev.embedding),
                int(ev.sensitivity),
                json_text(ev.access_policy),
                int(bool(ev.erased)),
                ev.tenant_id,
                ev.branch,
                ev.cid,
            ),
        )

    def _require_branch(self, conn: sqlite3.Connection, tenant_id: str, branch: str) -> None:
        """Local-parity branch guard — raises BEFORE the composite FK can fire
        so hostile/unknown branches surface as ``ValueError`` not IntegrityError."""
        row = conn.execute(
            "SELECT 1 FROM branches WHERE tenant_id = ? AND name = ?",
            (tenant_id, branch),
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown branch: {branch}")

    def _audit(
        self,
        conn: sqlite3.Connection,
        tenant_id: str,
        actor: str,
        op: str,
        target_id: str | None,
        diff: dict[str, Any],
        *,
        source: str | None = None,
        trust_tier: int | None = None,
        capability_tags: list[str] | None = None,
    ) -> None:
        """Append an audit row rideing the caller's transaction; the record dict
        byte-matches ``LocalMemoryEngine._audit`` (round-trips via export)."""
        normalized_tags = sorted(set(capability_tags or []))
        audit_diff = dict(diff)
        audit_diff.setdefault("source", source or actor)
        if trust_tier is not None:
            audit_diff.setdefault("trust_tier", trust_tier)
        if normalized_tags:
            audit_diff.setdefault("capability_tags", normalized_tags)
        record = {
            "id": new_id(),
            "tenant_id": tenant_id,
            "actor": actor,
            "op": op,
            "target_id": target_id,
            "source": source or actor,
            "trust_tier": trust_tier,
            "capability_tags": normalized_tags,
            "diff": audit_diff,
            "at": utc_now().isoformat(),
        }
        conn.execute(
            "INSERT INTO audit_log(tenant_id, record) VALUES (?, ?)",
            (tenant_id, json_text(record)),
        )

    def _erased_evidence_rows(
        self, conn: sqlite3.Connection, tenant_id: str, branch: str
    ) -> list[Evidence]:
        """Erased evidence for the erased-replay blocklist probe (insertion order
        matches Local's dict iteration so 'first match' semantics are identical)."""
        rows = conn.execute(
            "SELECT * FROM evidence WHERE tenant_id = ? AND branch = ? AND erased = 1 ORDER BY rowid",
            (tenant_id, branch),
        ).fetchall()
        return [_evidence_from_row(row) for row in rows]

    def _self_generation_budget_usage(
        self, conn: sqlite3.Connection, *, tenant_id: str, branch: str
    ) -> tuple[int, int]:
        """Non-erased self-generated/simulated event + byte counts (Local parity)."""
        events = 0
        byte_count = 0
        rows = conn.execute(
            "SELECT * FROM evidence WHERE tenant_id = ? AND branch = ? AND erased = 0",
            (tenant_id, branch),
        ).fetchall()
        for row in rows:
            item = _evidence_from_row(row)
            if LocalMemoryEngine._classify_evidence_reality(item) not in {"self_generated", "simulated"}:
                continue
            events += 1
            byte_count += len(item.content or "")
        return events, byte_count

    def _fetch_evidence(self, tenant_id: str, cid: str, branch: str = "main") -> Evidence | None:
        """Store-core evidence row read (no policy filtering — Task 3's
        get_evidence adds the erased/deepcopy contract)."""
        conn = self._connect(tenant_id)
        with self._lock:
            row = conn.execute(
                "SELECT * FROM evidence WHERE tenant_id = ? AND branch = ? AND cid = ?",
                (tenant_id, branch, cid),
            ).fetchone()
        if row is None:
            return None
        return _evidence_from_row(row)

    # --- MemoryEngine Protocol surface (stubs name their implementing task) --

    def append_evidence(self, ev: Evidence, branch: str = "main") -> str:
        """Ledger write mirroring ``LocalMemoryEngine.append_evidence`` over SQL:
        validate policy, require the branch (ValueError before the FK), compute the
        subject-scoped CID, apply the erased-replay blocklist (scoped + legacy
        unscoped probes), honour the self-generation budget, then commit the row +
        audit atomically and journal AFTER commit (success path only, exactly once)."""
        access_policy = validate_access_policy(
            ev.access_policy, tenant_id=ev.tenant_id, location="evidence.access_policy"
        )
        with self._lock:
            conn = self._connect(ev.tenant_id)
            self._require_branch(conn, ev.tenant_id, branch)
            cid = evidence_cid(
                ev.content,
                tenant_id=ev.tenant_id,
                user_id=ev.user_id,
                source_type=ev.source_type,
                content_pointer=ev.content_pointer,
                modality=ev.modality,
                sensitivity=int(ev.sensitivity),
            )
            unscoped_cid = evidence_unscoped_cid(
                ev.content,
                tenant_id=ev.tenant_id,
                source_type=ev.source_type,
                content_pointer=ev.content_pointer,
                modality=ev.modality,
            )
            for existing in self._erased_evidence_rows(conn, ev.tenant_id, branch):
                if (
                    existing.source_type == ev.source_type
                    and existing.content_pointer == ev.content_pointer
                    and existing.modality == ev.modality
                    and existing.cid
                ):
                    replay_cid = evidence_cid(
                        ev.content,
                        tenant_id=ev.tenant_id,
                        user_id=existing.user_id,
                        source_type=ev.source_type,
                        content_pointer=ev.content_pointer,
                        modality=ev.modality,
                        sensitivity=int(existing.sensitivity),
                    )
                    if replay_cid == existing.cid or unscoped_cid == existing.cid:
                        cid = existing.cid
                        break
            existing = self._fetch_evidence(ev.tenant_id, cid, branch)
            reality_class = LocalMemoryEngine._classify_evidence_reality(ev)
            if existing is not None:
                op = "append_evidence.blocked_erased_replay" if existing.erased else "append_evidence.noop_dedup"
                with conn:
                    self._audit(
                        conn,
                        ev.tenant_id,
                        ev.actor,
                        op,
                        cid,
                        {"branch": branch, "source_type": ev.source_type, "source_identity": ev.source_identity},
                        source=ev.source_type,
                        trust_tier=ev.trust_tier,
                        capability_tags=ev.capability_tags,
                    )
                return cid
            budget_report: dict[str, Any] | None = None
            if reality_class in {"self_generated", "simulated"}:
                current_events, current_bytes = self._self_generation_budget_usage(
                    conn, tenant_id=ev.tenant_id, branch=branch
                )
                budget_report = self_generation_budget_report(
                    current_events=current_events,
                    incoming_events=1,
                    current_bytes=current_bytes,
                    incoming_bytes=len(ev.content),
                    max_events=self.policy.self_generation_budget_max_events,
                    window_ticks=self.policy.self_generation_budget_window_ticks,
                )
                if not budget_report["allowed"]:
                    with conn:
                        self._audit(
                            conn,
                            ev.tenant_id,
                            ev.actor,
                            "append_evidence.self_generation_budget_deferred",
                            cid,
                            {
                                "branch": branch,
                                "source_type": ev.source_type,
                                "source_identity": ev.source_identity,
                                "reality_class": reality_class,
                                "self_generation_budget": budget_report,
                                "stored": False,
                                "reversible_pointer_preserved": bool(ev.content_pointer),
                            },
                            source=ev.source_type,
                            trust_tier=ev.trust_tier,
                            capability_tags=ev.capability_tags,
                        )
                    return cid
            stored = copy.deepcopy(ev)
            stored.cid = cid
            stored.branch = branch
            stored.access_policy = access_policy
            if stored.embedding and not may_embed_item(
                sensitivity=int(stored.sensitivity),
                access_policy=stored.access_policy,
            ):
                stored.embedding = None
            stored.metadata = dict(stored.metadata)
            stored.metadata.setdefault("reality_class", reality_class)
            stored.metadata["embedding_partition"] = vector_partition_for_item(
                sensitivity=int(stored.sensitivity),
                access_policy=stored.access_policy,
            )
            if budget_report is not None:
                stored.metadata["self_generation_budget"] = budget_report
                stored.metadata["self_generation_lifecycle"] = {
                    "status": "budgeted_low_groundedness",
                    "demotable": True,
                    "gc_after_idle_ticks": self.policy.self_generation_gc_after_idle_ticks,
                    "pointer_preserved": bool(stored.content_pointer or stored.cid),
                    "critical_path_allowed": False,
                }
            with conn:
                self._insert_evidence_row(conn, stored)
                self._audit(
                    conn,
                    ev.tenant_id,
                    ev.actor,
                    "append_evidence",
                    cid,
                    {"source_type": ev.source_type, "source_identity": ev.source_identity, "branch": branch},
                    source=ev.source_type,
                    trust_tier=ev.trust_tier,
                    capability_tags=ev.capability_tags,
                )
            if self._journal_dir is not None:
                CIDJournal(self._journal_dir / journal_filename(stored.tenant_id)).append(
                    {
                        "cid": stored.cid,
                        "tenant_id": stored.tenant_id,
                        "kind": "evidence",
                        "content": stored.content,
                        "created_at": stored.created_at.isoformat(),
                    }
                )
            return cid

    def backfill_evidence_privacy(
        self,
        tenant_id: str,
        cid: str,
        pii_tags: list[str],
        branch: str = "main",
        *,
        pii_sensitivity: int = 3,
        actor: str = "privacy_backfill",
        source: str = "privacy_backfill",
    ) -> bool:
        tags = _normalise_privacy_tags(pii_tags)
        if tags and int(pii_sensitivity) < 3:
            raise ValueError("pii_sensitivity must be at least 3 for detected PII")
        with self._lock:
            conn = self._connect(tenant_id)
            ev = self._fetch_evidence(tenant_id, cid, branch)
            if ev is None or ev.erased:
                return False
            before = _privacy_backfill_controls(ev.sensitivity, ev.access_policy, ev.metadata)
            target_sensitivity = max(int(ev.sensitivity), int(pii_sensitivity) if tags else int(ev.sensitivity))
            access_policy = _privacy_backfill_access_policy(
                ev.access_policy,
                tenant_id=tenant_id,
                pii_tags=tags,
                target_sensitivity=target_sensitivity,
            )
            embedding_partition = vector_partition_for_item(
                sensitivity=target_sensitivity,
                access_policy=access_policy,
            )
            ev.sensitivity = target_sensitivity
            ev.access_policy = access_policy
            ev.metadata = _privacy_backfill_metadata(
                ev.metadata,
                access_policy=access_policy,
                pii_tags=tags,
                embedding_partition=embedding_partition,
            )
            if embedding_partition == "none":
                ev.embedding = None
            with conn:
                self._write_evidence_mutable(conn, ev)
                self._audit(
                    conn,
                    tenant_id,
                    actor,
                    "backfill_evidence_privacy",
                    cid,
                    {
                        "branch": branch,
                        "pii_tags": tags,
                        "before": before,
                        "after": _privacy_backfill_controls(ev.sensitivity, ev.access_policy, ev.metadata),
                        "source_type": ev.source_type,
                    },
                    source=source,
                    trust_tier=ev.trust_tier,
                    capability_tags=ev.capability_tags,
                )
            return True

    def get_evidence(self, tenant_id: str, cid: str, branch: str = "main") -> Evidence | None:
        with self._lock:
            ev = self._fetch_evidence(tenant_id, cid, branch)
            if ev and not ev.erased:
                return ev
            return None

    def update_evidence_metadata(
        self,
        tenant_id: str,
        cid: str,
        metadata_patch: dict[str, Any],
        branch: str = "main",
        *,
        actor: str = "consolidation",
        source: str = "metadata_update",
    ) -> bool:
        if "access_policy" in metadata_patch:
            raise ValueError("metadata_patch.access_policy cannot shadow evidence.access_policy")
        with self._lock:
            conn = self._connect(tenant_id)
            ev = self._fetch_evidence(tenant_id, cid, branch)
            if ev is None or ev.erased:
                return False
            before_keys = sorted(ev.metadata.keys())
            ev.metadata = {**ev.metadata, **metadata_patch}
            with conn:
                self._write_evidence_mutable(conn, ev)
                self._audit(
                    conn,
                    tenant_id,
                    actor,
                    "update_evidence_metadata",
                    cid,
                    {
                        "branch": branch,
                        "patch": metadata_patch,
                        "before_keys": before_keys,
                        "after_keys": sorted(ev.metadata.keys()),
                        "source_type": ev.source_type,
                    },
                    source=source,
                    trust_tier=ev.trust_tier,
                    capability_tags=ev.capability_tags,
                )
            return True

    def set_evidence_embedding(
        self,
        tenant_id: str,
        cid: str,
        embedding: list[float],
        branch: str = "main",
        *,
        actor: str = "consolidation",
        source: str = "embedder",
    ) -> bool:
        with self._lock:
            conn = self._connect(tenant_id)
            ev = self._fetch_evidence(tenant_id, cid, branch)
            if ev is None or ev.erased:
                return False
            if not may_embed_item(
                sensitivity=int(ev.sensitivity),
                access_policy=ev.access_policy,
                erased=ev.erased,
            ):
                with conn:
                    self._audit(
                        conn,
                        tenant_id,
                        actor,
                        "set_evidence_embedding.blocked_policy",
                        cid,
                        {"branch": branch, "source_type": ev.source_type, "reason": "embedding_not_allowed"},
                        source=source,
                        trust_tier=ev.trust_tier,
                        capability_tags=ev.capability_tags,
                    )
                return False
            ev.embedding = list(embedding)
            ev.metadata = dict(ev.metadata)
            ev.metadata["embedding_partition"] = vector_partition_for_item(
                sensitivity=int(ev.sensitivity),
                access_policy=ev.access_policy,
            )
            with conn:
                self._write_evidence_mutable(conn, ev)
                self._audit(
                    conn,
                    tenant_id,
                    actor,
                    "set_evidence_embedding",
                    cid,
                    {"branch": branch, "embedding_dims": len(embedding), "source_type": ev.source_type},
                    source=source,
                    trust_tier=ev.trust_tier,
                    capability_tags=ev.capability_tags,
                )
            return True

    def export_tenant(self, tenant_id: str) -> dict[str, Any]:
        conn = self._connect(tenant_id)
        with self._lock:
            evidence = [
                _evidence_from_row(row).to_dict()
                for row in conn.execute(
                    "SELECT * FROM evidence WHERE tenant_id = ? AND erased = 0 ORDER BY rowid",
                    (tenant_id,),
                )
            ]
            assertions = [
                _assertion_from_row(row).to_dict()
                for row in conn.execute(
                    "SELECT * FROM assertions WHERE tenant_id = ? ORDER BY rowid", (tenant_id,)
                )
            ]
            relations = [
                _relation_from_row(row).to_dict()
                for row in conn.execute(
                    "SELECT * FROM relations WHERE tenant_id = ? ORDER BY rowid", (tenant_id,)
                )
            ]
            preferences = self._records(conn, "preferences", tenant_id)
            calibrations = self._records(conn, "calibrations", tenant_id)
            entities = self._records(conn, "entities", tenant_id)
            justifications = self._records(conn, "justifications", tenant_id)
            contradictions = self._records(conn, "contradictions", tenant_id)
            all_audit = [
                json.loads(row["record"])
                for row in conn.execute("SELECT record FROM audit_log ORDER BY seq")
            ]
            deletion_log = [
                item
                for item in (
                    json.loads(row["record"])
                    for row in conn.execute("SELECT record FROM deletion_log ORDER BY seq")
                )
                if item.get("tenant_id") == tenant_id
            ]
            merge_records = [
                json.loads(row["record"])
                for row in conn.execute("SELECT record FROM merge_log ORDER BY seq")
            ]
        audit_log = [item for item in all_audit if item.get("tenant_id") == tenant_id]
        merge_log = [
            item
            for item in merge_records
            if any(
                audit.get("op") == "merge"
                and audit.get("target_id") == item.get("from_branch")
                and audit.get("tenant_id") in {tenant_id, "*"}
                for audit in all_audit
            )
        ]
        return {
            "tenant_id": tenant_id,
            "evidence": evidence,
            "assertions": assertions,
            "relations": relations,
            "preferences": preferences,
            "calibrations": calibrations,
            "entities": entities,
            "justifications": justifications,
            "contradictions": contradictions,
            "audit_log": audit_log,
            "deletion_log": deletion_log,
            "merge_log": merge_log,
        }

    def export_tenant_filtered(self, tenant_id: str, access_context: dict[str, Any]) -> dict[str, Any]:
        return filter_export_for_context(
            self.export_tenant(tenant_id),
            {**dict(access_context or {}), "tenant_id": tenant_id},
            policy_max_sensitivity=self.policy.max_sensitivity,
        )

    @staticmethod
    def _records(conn: sqlite3.Connection, table: str, tenant_id: str) -> list[dict[str, Any]]:
        """JSON-record collections rehydrate to the exact ``to_dict()`` shape."""
        return [
            json.loads(row["record"])
            for row in conn.execute(
                f"SELECT record FROM {table} WHERE tenant_id = ? ORDER BY rowid", (tenant_id,)
            )
        ]

    def _iter_tenant_db_paths(self) -> list[Path]:
        return sorted(self.root_dir.glob("*.db"))

    def _borrow_conn(self, path: Path) -> tuple[sqlite3.Connection, bool]:
        """Return (connection, owned); a cached connection is reused (owned=False),
        otherwise a short-lived read connection is opened (owned=True → caller closes)."""
        cached = self._connections.get(str(path))
        if cached is not None:
            return cached, False
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn, True

    def _all_tenant_ids(self) -> list[str]:
        """Every real tenant id across the per-tenant files (excludes None/'*'),
        mirroring ``LocalMemoryEngine.export_all``'s tenant discovery."""
        tables = (
            "branches",
            "evidence",
            "assertions",
            "relations",
            "preferences",
            "justifications",
            "contradictions",
            "calibrations",
            "entities",
            "audit_log",
            "deletion_log",
            "merge_log",
        )
        found: set[str] = set()
        for path in self._iter_tenant_db_paths():
            conn, owned = self._borrow_conn(path)
            try:
                for table in tables:
                    for (tenant_id,) in conn.execute(f"SELECT DISTINCT tenant_id FROM {table}"):
                        if tenant_id and tenant_id != "*":
                            found.add(tenant_id)
            finally:
                if owned:
                    conn.close()
        return sorted(found)

    def _export_branches(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in self._iter_tenant_db_paths():
            conn, owned = self._borrow_conn(path)
            try:
                for row in conn.execute(
                    "SELECT tenant_id, name, from_branch, kind, created_at FROM branches ORDER BY rowid"
                ):
                    rows.append(
                        {
                            "tenant_id": row["tenant_id"],
                            "name": row["name"],
                            "from_branch": row["from_branch"],
                            "kind": row["kind"],
                            "head": None,
                            "created_at": row["created_at"],
                        }
                    )
            finally:
                if owned:
                    conn.close()
        return rows

    def export_all(self) -> dict[str, Any]:
        tenant_exports = [self.export_tenant(tenant_id) for tenant_id in self._all_tenant_ids()]
        merge_log: list[dict[str, Any]] = []
        for path in self._iter_tenant_db_paths():
            conn, owned = self._borrow_conn(path)
            try:
                merge_log.extend(
                    json.loads(row["record"])
                    for row in conn.execute("SELECT record FROM merge_log ORDER BY seq")
                )
            finally:
                if owned:
                    conn.close()
        return {
            "policy": self.policy.to_dict(),
            "branches": self._export_branches(),
            "evidence": [item for exported in tenant_exports for item in exported["evidence"]],
            "assertions": [item for exported in tenant_exports for item in exported["assertions"]],
            "relations": [item for exported in tenant_exports for item in exported["relations"]],
            "preferences": [item for exported in tenant_exports for item in exported["preferences"]],
            "justifications": [item for exported in tenant_exports for item in exported["justifications"]],
            "contradictions": [item for exported in tenant_exports for item in exported["contradictions"]],
            "calibrations": [item for exported in tenant_exports for item in exported["calibrations"]],
            "entities": [item for exported in tenant_exports for item in exported["entities"]],
            "audit_log": [item for exported in tenant_exports for item in exported["audit_log"]],
            "deletion_log": [item for exported in tenant_exports for item in exported["deletion_log"]],
            "merge_log": merge_log,
            "tenants": tenant_exports,
        }

    def vector_search(self, query: str, k: int, filt: dict[str, Any]) -> list[Hit]:
        raise NotImplementedError("SqliteEngine.vector_search lands in Phase-2 Task 4")

    def lexical_search(self, query: str, k: int, filt: dict[str, Any]) -> list[Hit]:
        raise NotImplementedError("SqliteEngine.lexical_search lands in Phase-2 Task 4")

    def graph_ppr(
        self,
        seeds: list[str],
        k: int,
        as_of: datetime | None = None,
        tenant_id: str | None = None,
        branch: str | None = None,
        use_cache: bool = False,
        filt: dict[str, Any] | None = None,
    ) -> list[Hit]:
        raise NotImplementedError("SqliteEngine.graph_ppr lands in Phase-2 Task 4")

    def upsert_assertion(self, assertion: Assertion, branch: str = "main") -> str:
        raise NotImplementedError("SqliteEngine.upsert_assertion lands in Phase-2 Task 5")

    def add_relation(self, relation: Relation, branch: str = "main") -> str:
        raise NotImplementedError("SqliteEngine.add_relation lands in Phase-2 Task 5")

    def add_preference(self, preference: Preference) -> str:
        raise NotImplementedError("SqliteEngine.add_preference lands in Phase-2 Task 5")

    def as_of(self, subject: str, predicate: str, t: datetime, tenant_id: str | None = None, branch: str = "main") -> list[Assertion]:
        raise NotImplementedError("SqliteEngine.as_of lands in Phase-2 Task 5")

    def set_calibration(self, calibration: CalibrationSet) -> None:
        raise NotImplementedError("SqliteEngine.set_calibration lands in Phase-2 Task 5")

    def register_entity(
        self,
        tenant_id: str,
        canonical: str,
        *,
        alias: str | None = None,
        entity_type: str = "unknown",
        summary: str | None = None,
        source_evidence_cids: list[str] | None = None,
        access_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError("SqliteEngine.register_entity lands in Phase-2 Task 5")

    def deep_search(self, query: str, tenant_id: str, branch: str = "main", filt: dict[str, Any] | None = None) -> RetrievalResult:
        raise NotImplementedError("SqliteEngine.deep_search lands in Phase-2 Task 5")

    def explain(self, query: str, tenant_id: str, branch: str = "main") -> dict[str, Any]:
        raise NotImplementedError("SqliteEngine.explain lands in Phase-2 Task 5")

    def correct(
        self,
        tenant_id: str,
        user_id: str,
        subject: str,
        predicate: str,
        object_value: str,
        correction_text: str,
        branch: str = "main",
        confidence: float = 0.95,
    ) -> str:
        raise NotImplementedError("SqliteEngine.correct lands in Phase-2 Task 5")

    def branch(self, name: str, frm: str = "main", kind: str = "scratch", tenant_id: str | None = None) -> None:
        raise NotImplementedError("SqliteEngine.branch lands in Phase-2 Task 6")

    def merge(self, frm: str, into: str = "main", tenant_id: str | None = None) -> MergeReport:
        raise NotImplementedError("SqliteEngine.merge lands in Phase-2 Task 6")

    def discard(self, branch: str, tenant_id: str | None = None) -> None:
        raise NotImplementedError("SqliteEngine.discard lands in Phase-2 Task 6")

    def retrieve(self, query: str, tenant_id: str, branch: str = "main", deep: bool = False, filt: dict[str, Any] | None = None) -> RetrievalResult:
        raise NotImplementedError("SqliteEngine.retrieve lands in Phase-2 Task 7")

    def forget(
        self,
        tenant_id: str,
        cid: str,
        branch: str = "main",
        requested_by: str = "user",
        erasure_mode: ErasureMode | str = ErasureMode.TOMBSTONE_RECOMPUTE,
    ) -> dict[str, Any]:
        raise NotImplementedError("SqliteEngine.forget lands in Phase-2 Task 9")
