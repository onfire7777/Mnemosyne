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

The 21 ``MemoryEngine`` Protocol methods (plus the three contract-required
extras ``get_evidence`` / ``set_evidence_embedding`` /
``update_evidence_metadata``) exist as ``NotImplementedError`` stubs naming
the Phase-2 task that implements them, so
``isinstance(engine, MemoryEngine)`` already holds — the runtime_checkable
Protocol checks method presence.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from mnemosyne.calibration import CalibrationSet
from mnemosyne.journal import safe_tenant_filename
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
        """Store-core evidence row write (Task 3's append_evidence layers
        CID computation, policy gates, dedup, and journal wiring on top)."""
        if not ev.cid:
            raise ValueError("sqlite evidence rows require a cid")
        conn = self._connect(ev.tenant_id)
        with self._lock, conn:
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
        raise NotImplementedError("SqliteEngine.append_evidence lands in Phase-2 Task 3")

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
        raise NotImplementedError("SqliteEngine.backfill_evidence_privacy lands in Phase-2 Task 3")

    def get_evidence(self, tenant_id: str, cid: str, branch: str = "main") -> Evidence | None:
        raise NotImplementedError("SqliteEngine.get_evidence lands in Phase-2 Task 3")

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
        raise NotImplementedError("SqliteEngine.update_evidence_metadata lands in Phase-2 Task 3")

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
        raise NotImplementedError("SqliteEngine.set_evidence_embedding lands in Phase-2 Task 3")

    def export_tenant(self, tenant_id: str) -> dict[str, Any]:
        raise NotImplementedError("SqliteEngine.export_tenant lands in Phase-2 Task 3")

    def export_tenant_filtered(self, tenant_id: str, access_context: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("SqliteEngine.export_tenant_filtered lands in Phase-2 Task 3")

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
