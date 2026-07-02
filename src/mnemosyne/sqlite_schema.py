"""SqliteEngine per-tenant schema — applied idempotently on open (Phase-2 Task 2).

Why this DDL lives in Python instead of ``sql/schema.sql``
----------------------------------------------------------
The Postgres convention does not transfer: Postgres base DDL is applied
EXTERNALLY (the compose ``docker-entrypoint-initdb.d`` mount) and Python only
runs incremental ``_ensure_*_schema`` statements inside operations. SQLite has
no external provisioning step, so SqliteEngine is the repo's first Python-side
base-DDL creator: every statement below is ``CREATE ... IF NOT EXISTS`` and the
engine applies the whole list on first open of each tenant file. Keeping the
DDL out of ``sql/schema.sql`` is also load-bearing — that file is doubly
pinned as Postgres-only by config-drift check G (``CREATE TABLE`` names are
regex-mirrored into ``config/drift-baseline.toml`` ``[schema].required_tables``)
and by ``tests/test_nfrs_and_schema.py``'s string pins.

Storage conventions (locked by the Phase-2 grounding, R7)
---------------------------------------------------------
* One SQLite file per tenant: ``tenant_id`` columns are constant within a
  file but kept so SQL stays portable with the Postgres shapes; Postgres RLS
  is replaced by file-per-tenant isolation.
* External tenant/user/session ids are stored VERBATIM (no uuid5 mapping).
* JSON values are TEXT via ``json.dumps(sort_keys=True)`` (:func:`json_text`).
* Timestamps are TEXT via ``models.dt_to_json`` (trailing ``"Z"``) — never
  ``datetime.isoformat()`` output, whose ``"+00:00"`` suffix sorts differently
  and would corrupt lexicographic window predicates.
* CIDs are TEXT hex (exports and ``Hit.id`` use hex strings).
* Embeddings are packed little-endian f64 BLOBs (:func:`pack_embedding`), the
  Phase-1 handoff consumed zero-copy by the Task-4 dense-scan seam.

The 13 ``LocalMemoryEngine._persist`` collections map to: ``meta['policy']``
(policy), the ``branches`` registry table, eight item tables (evidence,
assertions, relations, preferences, justifications, contradictions,
calibrations, entities) with exactly the uniqueness keys the Local dicts
encode, and three append-ordered log tables (audit_log, deletion_log,
merge_log). ``runtime_jobs`` mirrors PostgresQueue's DDL shape for the
durable queue lane (Task 6); ``meta`` carries ``schema_version`` and
projection watermarks (Task 8). Task 4 adds ``evidence_fts`` (an FTS5 virtual
table + INSERT/UPDATE/DELETE sync triggers) as the lexical candidate-recall
index; it is prefilter-only — the shared ``lexical_score`` rescore is the sole
ranking authority.
"""
from __future__ import annotations

import array
import json
import sys
from typing import Any

SCHEMA_VERSION = 1

# Applied on every connect (spec §4.2): durable WAL writes, enforced FKs, and
# a bounded busy wait so concurrent per-tenant access degrades loudly.
PRAGMA_STATEMENTS: tuple[str, ...] = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=FULL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA busy_timeout=5000",
)

ENSURE_STATEMENTS: list[str] = [
    # branch registry (PG-shaped: sql/schema.sql branches table, head included
    # for portability); the engine seeds a protected 'main' row per tenant.
    """
    CREATE TABLE IF NOT EXISTS branches (
        tenant_id TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT 'main',
        from_branch TEXT,
        kind TEXT NOT NULL DEFAULT 'scratch',
        head BLOB,
        created_at TEXT NOT NULL,
        PRIMARY KEY (tenant_id, name)
    )
    """,
    # evidence — UNIQUE(tenant_id, branch, cid); columns mirror the Evidence
    # model field-for-field so rows rehydrate through Evidence.from_dict.
    """
    CREATE TABLE IF NOT EXISTS evidence (
        tenant_id TEXT NOT NULL,
        branch TEXT NOT NULL DEFAULT 'main',
        cid TEXT NOT NULL,
        user_id TEXT NOT NULL,
        actor TEXT NOT NULL,
        source_type TEXT NOT NULL,
        content TEXT NOT NULL,
        source_identity TEXT,
        session_id TEXT,
        metadata TEXT NOT NULL DEFAULT '{}',
        content_pointer TEXT,
        modality TEXT NOT NULL DEFAULT 'text',
        embedding BLOB,
        signed_provenance TEXT,
        trust_tier INTEGER NOT NULL DEFAULT 0,
        capability_tags TEXT NOT NULL DEFAULT '[]',
        sensitivity INTEGER NOT NULL DEFAULT 0,
        access_policy TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        erased INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (tenant_id, branch, cid),
        FOREIGN KEY (tenant_id, branch) REFERENCES branches(tenant_id, name)
    )
    """,
    # assertions — UNIQUE(tenant_id, branch, id); columns mirror the Assertion
    # model (datetimes as dt_to_json TEXT for lexicographic as-of windows).
    """
    CREATE TABLE IF NOT EXISTS assertions (
        tenant_id TEXT NOT NULL,
        branch TEXT NOT NULL DEFAULT 'main',
        id TEXT NOT NULL,
        user_id TEXT,
        subject TEXT NOT NULL,
        predicate TEXT NOT NULL,
        object TEXT NOT NULL,
        scope TEXT NOT NULL DEFAULT '{}',
        confidence REAL NOT NULL DEFAULT 0.7,
        calibration TEXT NOT NULL DEFAULT '{}',
        valid_from TEXT NOT NULL,
        valid_to TEXT,
        transaction_time TEXT NOT NULL,
        expired_at TEXT,
        justification_id TEXT,
        source_evidence_cids TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'candidate' CHECK (
            status IN ('candidate', 'active', 'superseded', 'contested', 'quarantined', 'retracted')
        ),
        version INTEGER NOT NULL DEFAULT 1,
        superseded_by TEXT,
        trust_tier INTEGER NOT NULL DEFAULT 0,
        sensitivity INTEGER NOT NULL DEFAULT 0,
        access_policy TEXT NOT NULL DEFAULT '{}',
        last_accessed TEXT,
        access_count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (tenant_id, branch, id),
        FOREIGN KEY (tenant_id, branch) REFERENCES branches(tenant_id, name)
    )
    """,
    # relations — UNIQUE(tenant_id, branch, id); mirrors the Relation model.
    """
    CREATE TABLE IF NOT EXISTS relations (
        tenant_id TEXT NOT NULL,
        branch TEXT NOT NULL DEFAULT 'main',
        id TEXT NOT NULL,
        source TEXT NOT NULL,
        predicate TEXT NOT NULL,
        target TEXT NOT NULL,
        confidence REAL NOT NULL DEFAULT 0.7,
        valid_from TEXT NOT NULL,
        valid_to TEXT,
        source_evidence_cids TEXT NOT NULL DEFAULT '[]',
        access_policy TEXT NOT NULL DEFAULT '{}',
        PRIMARY KEY (tenant_id, branch, id),
        FOREIGN KEY (tenant_id, branch) REFERENCES branches(tenant_id, name)
    )
    """,
    # preferences / justifications / contradictions — PK(id); the record
    # column holds the full to_dict() JSON so rows rehydrate through the
    # exact model constructors (Preference.from_dict etc.), byte-identically
    # to LocalMemoryEngine's JSON store round-trip.
    """
    CREATE TABLE IF NOT EXISTS preferences (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        record TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS justifications (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        record TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS contradictions (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        record TEXT NOT NULL
    )
    """,
    # calibrations — PK(tenant_id, memory_type); record rehydrates via
    # CalibrationSet(**json.loads(record)).
    """
    CREATE TABLE IF NOT EXISTS calibrations (
        tenant_id TEXT NOT NULL,
        memory_type TEXT NOT NULL,
        record TEXT NOT NULL,
        PRIMARY KEY (tenant_id, memory_type)
    )
    """,
    # entities — PK(tenant_id, canonical); plain dict rows (dict(row) shape).
    """
    CREATE TABLE IF NOT EXISTS entities (
        tenant_id TEXT NOT NULL,
        canonical TEXT NOT NULL,
        record TEXT NOT NULL,
        PRIMARY KEY (tenant_id, canonical)
    )
    """,
    # audit/deletion/merge logs — append-ordered plain dict rows persisted
    # verbatim (seq preserves LocalMemoryEngine's list ordering).
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT,
        record TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS deletion_log (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT,
        record TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS merge_log (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT,
        record TEXT NOT NULL
    )
    """,
    # runtime_jobs — PostgresQueue's runtime_jobs DDL adapted for SQLite
    # (UUID -> TEXT id, JSONB -> TEXT, timestamptz -> dt_to_json TEXT; the RLS
    # policy is replaced by file-per-tenant isolation). Consumed by Task 6's
    # SqliteQueue.
    """
    CREATE TABLE IF NOT EXISTS runtime_jobs (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        payload TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'queued' CHECK (
            status IN ('queued', 'running', 'retry', 'complete', 'dead')
        ),
        attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
        max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
        last_error TEXT,
        result TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS runtime_jobs_tenant_status_kind_idx
        ON runtime_jobs(tenant_id, status, kind, created_at)
    """,
    # meta — schema_version, the serialized OperatingPolicy, and projection
    # watermarks (Task 8).
    """
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    # evidence_fts (Task 4) — FTS5 candidate-recall index over evidence.content.
    #
    # The unicode61 tokenizer is configured with ``tokenchars '_'`` so an
    # underscore is a token character on BOTH sides (matching mnemosyne.text's
    # tokenizer, whose TOKEN_RE keeps ``_``). That makes the ``[a-z0-9_]+``
    # ``fts_safe_query`` predicate sound: for a query whose every token is
    # unicode61-safe, the FTS MATCH candidate set is a SUPERSET of the rows
    # ``lexical_score`` would score > 0, so the app-side rescore (which is the
    # ONLY ranking authority — FTS5 never ranks) reproduces LocalMemoryEngine's
    # full-scan result exactly. Tokens carrying ``:+./-`` are unsafe (unicode61
    # would split them differently) → the engine full-scans instead of
    # prefiltering. The shadow tables (evidence_fts_{data,idx,content,docsize,
    # config}) are created implicitly; table-presence assertions use ``<=`` so
    # they are additive.
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts USING fts5(
        cid UNINDEXED,
        tenant_id UNINDEXED,
        branch UNINDEXED,
        content,
        tokenize = "unicode61 tokenchars '_'"
    )
    """,
    # Keep evidence_fts in lockstep with the evidence table (standard external
    # trigger pattern). rowid mirrors evidence.rowid so lookups can join back.
    """
    CREATE TRIGGER IF NOT EXISTS evidence_fts_ai AFTER INSERT ON evidence BEGIN
        INSERT INTO evidence_fts(rowid, cid, tenant_id, branch, content)
        VALUES (new.rowid, new.cid, new.tenant_id, new.branch, new.content);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS evidence_fts_ad AFTER DELETE ON evidence BEGIN
        DELETE FROM evidence_fts WHERE rowid = old.rowid;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS evidence_fts_au AFTER UPDATE ON evidence BEGIN
        DELETE FROM evidence_fts WHERE rowid = old.rowid;
        INSERT INTO evidence_fts(rowid, cid, tenant_id, branch, content)
        VALUES (new.rowid, new.cid, new.tenant_id, new.branch, new.content);
    END
    """,
]


def json_text(value: Any) -> str:
    """Canonical JSON TEXT for SQLite columns (sorted keys, Local-store shape)."""
    return json.dumps(value, sort_keys=True)


def pack_embedding(embedding: list[float] | None) -> bytes | None:
    """Pack an embedding as a little-endian f64 BLOB (Phase-1 dense-scan seam)."""
    if embedding is None:
        return None
    packed = array.array("d", (float(value) for value in embedding))
    if sys.byteorder == "big":  # pragma: no cover — no supported big-endian target
        packed.byteswap()
    return packed.tobytes()


def unpack_embedding(blob: bytes | None) -> list[float] | None:
    """Inverse of :func:`pack_embedding`; exact f64 round-trip."""
    if blob is None:
        return None
    unpacked = array.array("d")
    unpacked.frombytes(blob)
    if sys.byteorder == "big":  # pragma: no cover — no supported big-endian target
        unpacked.byteswap()
    return list(unpacked)
