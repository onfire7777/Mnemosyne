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
these primitives, reproducing ``LocalMemoryEngine``'s flow exactly.

Phase-2 Task 4 adds the scan surfaces — ``vector_search`` (the PACKED-BLOB
dense seam feeding ``dense_scan_packed`` with zero per-call conversion),
``lexical_search`` (FTS5-safe candidate prefilter + shared ``lexical_score``
rescore), and ``graph_ppr`` (live PPR). They keep byte-parity with the
LocalMemoryEngine oracle by hydrating a scoped, policy/adapter-sharing Local
instance from SQL and reusing its exact candidate/graph bodies (see the
``scan surfaces`` block).

Phase-2 Task 5 adds the assertion / bitemporal / remaining-write surface —
``upsert_assertion`` (replay/supersede/contest), ``add_relation``,
``add_preference`` (supersession), ``register_entity``, ``set_calibration`` /
``_calibration_for``, ``as_of`` (half-open [valid_from, valid_to) window over
``dt_to_json`` TEXT), ``correct``, and the ``deep_search`` / ``explain``
delegators. The stateful writes run Local's actual body over a scoped oracle
and persist only new/changed rows (rowid preserved) plus Local's audit rows, so
``export_tenant`` byte-matches the oracle (see the ``assertions`` block). The
remaining ``MemoryEngine`` Protocol methods (``branch`` / ``merge`` /
``discard`` / ``retrieve`` / ``forget``) stay ``NotImplementedError`` stubs
naming their Phase-2 task, so ``isinstance(engine, MemoryEngine)`` already holds
— the runtime_checkable Protocol checks method presence.
"""
from __future__ import annotations

import array
import copy
import hashlib
import json
import re
import secrets
import sqlite3
import threading
import time
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mnemosyne import text as text_kernels
from mnemosyne.access_policy import (
    VECTOR_PARTITION_NONE,
    VECTOR_PARTITION_PUBLIC,
    effective_max_sensitivity,
    filter_export_for_context,
    may_embed_item,
    may_read_item,
    may_use_stored_embedding,
    validate_access_policy,
    vector_partition_for_item,
)
from mnemosyne.calibration import CalibrationSet
from mnemosyne.engine import (
    _CANDIDATE_MEMO_SIZE,
    LocalMemoryEngine,
    _candidate_memo_enabled,
    _merge_relation_state,
    _normalise_privacy_tags,
    _privacy_backfill_access_policy,
    _privacy_backfill_controls,
    _privacy_backfill_metadata,
    _relation_windows_overlap,
)
from mnemosyne.erasure_ids import (
    build_erasure_placeholder_map,
    erasure_deletion_record_id,
    erasure_tombstone_hash,
    redact_erased_cids,
)
from mnemosyne.ids import evidence_cid, evidence_unscoped_cid, new_id
from mnemosyne.journal import CIDJournal, journal_filename, safe_tenant_filename
from mnemosyne.models import (
    Assertion,
    Contradiction,
    Evidence,
    Hit,
    Justification,
    MergeReport,
    Preference,
    Relation,
    RetrievalResult,
    dt_to_json,
    parse_dt,
    utc_now,
)
from mnemosyne.observability import MetricsRegistry
from mnemosyne.pipeline import run_retrieval_pipeline
from mnemosyne.policy import OperatingPolicy
from mnemosyne.privacy import ErasureMode
from mnemosyne.projections import ProjectionRegistry, ProjectionSpec
from mnemosyne.retrieval import (
    HashingEmbeddingProvider,
    LocalSimilarityReranker,
    RetrievalAdapters,
    embed_query,
    validate_adapter_hit_scope,
)
from mnemosyne.security import TrustTier
from mnemosyne.sqlite_schema import (
    ENSURE_STATEMENTS,
    PRAGMA_STATEMENTS,
    SCHEMA_VERSION,
    json_text,
    pack_embedding,
    unpack_embedding,
)
from mnemosyne.standing import standing_erasure_cascade_report
from mnemosyne.text import cosine, lexical_score, tokenize
from mnemosyne.workspace import self_generation_budget_report

LEXICAL_BACKEND = "sqlite-fts5"
GRAPH_BACKEND = "sqlite-cached-ppr"

# A query token is FTS5-safe when it is a bare word under the unicode61
# tokenizer (which we configure with ``tokenchars '_'`` so ``_`` counts too).
_FTS_SAFE_TOKEN = re.compile(r"[a-z0-9_]+")


def fts_safe_query(tokens: list[str]) -> bool:
    """True IFF every query token is unicode61-safe (``[a-z0-9_]+`` after
    :func:`mnemosyne.text.tokenize`).

    Rationale (tokenizer-mismatch): the ``evidence_fts`` index tokenizes with
    unicode61 (``tokenchars '_'``), which splits on ``:+./-`` — characters the
    app-side tokenizer keeps INSIDE a token (URLs, ``v1.2.3``, ``data-only``).
    When a query token carries any of those characters the two tokenizers can
    disagree on the term boundary, so an FTS MATCH could MISS a row that
    ``lexical_score`` would rank > 0 (a recall regression vs the Local oracle,
    which full-scans every candidate). This predicate is the deterministic
    guard: only when EVERY query token is a bare ``[a-z0-9_]+`` word — for
    which unicode61 and the app tokenizer provably agree — is the FTS MATCH
    candidate set a superset of the rescored-positive rows, making the FTS
    prefilter safe. Otherwise the engine full-scans. Empty (no tokens) is
    vacuously true; the caller guards the empty case before building a MATCH.
    """
    return all(bool(_FTS_SAFE_TOKEN.fullmatch(token)) for token in tokens)


def sqlite_vec_available() -> bool:
    """Whether the optional ``sqlitevec`` extra could register a vec0 dense index.

    True only when the ``sqlite_vec`` package imports AND this Python's sqlite3
    build actually permits loadable extensions (``enable_load_extension``). The
    DEFAULT dense path is ALWAYS the packed-BLOB kernel exact scan
    (:func:`SqliteEngine.vector_search` → ``dense_scan_packed``); this detector
    is the gate for the OPTIONAL vec0 approximate candidate index, whose full
    wiring behind the projection registry is deferred to Task 8. It lets tests
    skip vec0-specific paths when the extra is absent without touching the
    default scan (which is unaffected either way).
    """
    try:
        import sqlite_vec  # noqa: F401  # type: ignore[import-not-found]
    except Exception:
        return False
    probe = sqlite3.connect(":memory:")
    try:
        probe.enable_load_extension(True)
        return True
    except (AttributeError, sqlite3.OperationalError, sqlite3.NotSupportedError):
        return False
    finally:
        probe.close()


# --- Task 8 embedding-cache admission (A1) ----------------------------------
#
# The A1 embedding cache never admits an item whose vector partition is ``none``
# (S4, ``embed_ok: false``, ``restricted``, any ``hold``/``hold:*`` flag, an
# unknown access-policy key, or an erased/non-live row — all collapse to
# VECTOR_PARTITION_NONE in ``access_policy.vector_partition_for_item``). S3
# (sensitivity 3) has a non-none partition but is admitted ONLY under a
# sensitive-embedding deployment flag. No such flag exists anywhere in
# ``access_policy.py`` / ``OperatingPolicy`` today (verified 2026-07-02), so S3
# (and, by the partition rule, S4) FAILS CLOSED — never cached. If such a
# deployment flag is introduced later, gate it here rather than inventing new
# salting (the subject-scoped cid already closes the dedup-oracle rail).
_SENSITIVE_EMBEDDING_CACHE_ENABLED = False


def _graph_ppr_seed_hash(seed_set: set[str]) -> str:
    """Order-independent hash of a lowercased seed set — the cached-PPR key
    discipline mirrored from PostgresEngine's materialization path."""
    payload = json.dumps(sorted(seed_set), separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _graph_ppr_as_of_key(as_of: datetime | None, moment: datetime) -> str:
    """Cache partition key for the as-of dimension: ``"live"`` for a ``None``
    as_of (the common ``now()`` traversal) else the fixed-width ``dt_to_json``
    moment (never compared lexically as a window bound — the DATETIME HAZARD)."""
    return "live" if as_of is None else dt_to_json(moment)


def _metadata_patch_tightens_privacy(patch: dict[str, Any]) -> bool:
    """Whether a metadata patch signals a restriction/hold/quarantine change (or
    drops the embedding partition) that must invalidate a cached embedding."""
    for key, value in patch.items():
        name = str(key)
        if name in {"restricted", "hold", "quarantine_reason", "quarantined"} or name.startswith("hold:"):
            return True
        if name == "embedding_partition" and str(value) == "none":
            return True
    return False


_EVIDENCE_INSERT = """
INSERT INTO evidence (
    tenant_id, branch, cid, user_id, actor, source_type, content,
    source_identity, session_id, metadata, content_pointer, modality,
    embedding, signed_provenance, trust_tier, capability_tags, sensitivity,
    access_policy, created_at, erased
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

# Branch row-copy variant: evidence keeps its cid, so an INSERT OR IGNORE on the
# unique key (tenant_id, branch, cid) is the idempotent copy (T6 handoff).
_EVIDENCE_INSERT_OR_IGNORE = _EVIDENCE_INSERT.replace("INSERT INTO", "INSERT OR IGNORE INTO", 1)

# Task-5 assertion / relation column writers. The column order matches
# ``_assertion_from_row`` / ``_relation_from_row`` (which feed the byte-parity
# export). ``_ASSERTION_UPDATE`` rewrites every mutable column in place (rowid
# preserved → ``export_tenant``'s ``ORDER BY rowid`` parity holds) while
# ``_ASSERTION_INSERT`` appends a genuinely new row.
_ASSERTION_INSERT = """
INSERT INTO assertions (
    tenant_id, branch, id, user_id, subject, predicate, object, scope,
    confidence, calibration, valid_from, valid_to, transaction_time, expired_at,
    justification_id, source_evidence_cids, status, version, superseded_by,
    trust_tier, sensitivity, access_policy, last_accessed, access_count
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_ASSERTION_UPDATE = """
UPDATE assertions SET
    user_id = ?, subject = ?, predicate = ?, object = ?, scope = ?,
    confidence = ?, calibration = ?, valid_from = ?, valid_to = ?,
    transaction_time = ?, expired_at = ?, justification_id = ?,
    source_evidence_cids = ?, status = ?, version = ?, superseded_by = ?,
    trust_tier = ?, sensitivity = ?, access_policy = ?, last_accessed = ?,
    access_count = ?
WHERE tenant_id = ? AND branch = ? AND id = ?
"""

_RELATION_INSERT = """
INSERT INTO relations (
    tenant_id, branch, id, source, predicate, target, confidence,
    valid_from, valid_to, source_evidence_cids, access_policy
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_RELATION_UPSERT = _RELATION_INSERT + """
ON CONFLICT (tenant_id, branch, id) DO UPDATE SET
    source = excluded.source,
    predicate = excluded.predicate,
    target = excluded.target,
    confidence = excluded.confidence,
    valid_from = excluded.valid_from,
    valid_to = excluded.valid_to,
    source_evidence_cids = excluded.source_evidence_cids,
    access_policy = excluded.access_policy
"""


def _assertion_insert_values(a: Assertion) -> tuple[Any, ...]:
    """INSERT bind tuple for an ``Assertion`` (dt columns via ``dt_to_json``,
    JSON columns via ``json_text`` — byte-identical to the export round-trip)."""
    return (
        a.tenant_id,
        a.branch,
        a.id,
        a.user_id,
        a.subject,
        a.predicate,
        a.object,
        json_text(a.scope),
        float(a.confidence),
        json_text(a.calibration),
        dt_to_json(a.valid_from),
        dt_to_json(a.valid_to),
        dt_to_json(a.transaction_time),
        dt_to_json(a.expired_at),
        a.justification_id,
        json_text(a.source_evidence_cids),
        a.status,
        int(a.version),
        a.superseded_by,
        int(a.trust_tier),
        int(a.sensitivity),
        json_text(a.access_policy),
        dt_to_json(a.last_accessed),
        int(a.access_count),
    )


def _evidence_insert_values(ev: Evidence) -> tuple[Any, ...]:
    """INSERT bind tuple for an ``Evidence`` row (column order matches
    ``_EVIDENCE_INSERT`` and ``_evidence_from_row``; embedding packed LE f64,
    JSON columns via ``json_text``, timestamps via ``dt_to_json``)."""
    if not ev.cid:
        raise ValueError("sqlite evidence rows require a cid")
    return (
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
    )


def _relation_insert_values(rel: Relation) -> tuple[Any, ...]:
    return (
        rel.tenant_id,
        rel.branch,
        rel.id,
        rel.source,
        rel.predicate,
        rel.target,
        float(rel.confidence),
        dt_to_json(rel.valid_from),
        dt_to_json(rel.valid_to),
        json_text(rel.source_evidence_cids),
        json_text(rel.access_policy),
    )


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
        metrics: MetricsRegistry | None = None,
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
        self._retrieval_result_cache_nonce = secrets.token_hex(16)
        # Task 8: tenant-granular embedding-cache hit/miss telemetry (never
        # per-cid — a per-key counter would itself be a presence oracle), and
        # the per-tenant projection registries (cached-ppr / evidence-fts /
        # optional vec0), built lazily on first use.
        self._cache_telemetry: dict[str, dict[str, int]] = {}
        self._registries: dict[str, ProjectionRegistry] = {}
        # Scan-oracle memo (see _scan_oracle): one SQL hydration serves the
        # dense + lexical channels of a retrieve (and repeats until a write).
        # Keyed on sqlite write fingerprints — conn.total_changes for this
        # engine's own writes, PRAGMA data_version for other connections — so
        # any committed change re-hydrates. Shares the Local candidate-memo
        # kill-switch MNEMOSYNE_CANDIDATE_MEMO=0 (CONFIG-DRIFT-CHECKS.md).
        self._scan_oracle_memo: OrderedDict[
            tuple[Any, ...], tuple[LocalMemoryEngine, dict[str, bytes | None]]
        ] = OrderedDict()
        # Observability checklist §1-3 signals (evidence-durability, rebuild-lag,
        # per-write audit stream, erasure-propagation). The engine emits directly
        # into this registry — durability is the highest SLO (§15) so the loss
        # counter is materialized at zero from construction. Always present so
        # signals are produced even when no external registry is injected.
        self.metrics = metrics or MetricsRegistry()
        self.metrics.increment("sqlite.evidence.durability.loss", 0)

    # --- store core (connections, schema, row marshalling) -------------------

    def _retrieval_result_cache_token(
        self, tenant_id: str, branch: str, effective_filter: dict[str, Any]
    ) -> tuple[Any, ...] | None:
        if not tenant_id:
            return None
        conn = self._connect(tenant_id)
        with self._lock:
            row = conn.execute("PRAGMA data_version").fetchone()
            data_version = int(row[0]) if row is not None else 0
            return (
                "sqlite",
                self._retrieval_result_cache_nonce,
                str(self.root_dir),
                tenant_id,
                branch,
                conn.total_changes,
                data_version,
                effective_filter.get("_retrieval_deep", False),
            )

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
            self._scan_oracle_memo.clear()
            self._retrieval_result_cache_nonce = secrets.token_hex(16)

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
        conn.execute(_EVIDENCE_INSERT, _evidence_insert_values(ev))

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
        tenant_id: str | None,
        actor: str,
        op: str,
        target_id: str | None,
        diff: dict[str, Any],
        *,
        source: str | None = None,
        trust_tier: int | None = None,
        capability_tags: list[str] | None = None,
    ) -> None:
        """Public audit entrypoint matching ``LocalMemoryEngine._audit`` (the
        parity oracle) exactly — no ``conn``/``cur`` first arg — so shared
        consumers that signature-sniff for a Local-shaped ``_audit`` (e.g.
        ``learning.py``'s LearningModule) write through here. Opens its own
        connection + transaction; internal engine methods that already own a
        transaction call :meth:`_audit_row` directly."""
        with self._lock:
            conn = self._connect(tenant_id or "__system__")
            with conn:
                self._audit_row(
                    conn,
                    tenant_id,
                    actor,
                    op,
                    target_id,
                    diff,
                    source=source,
                    trust_tier=trust_tier,
                    capability_tags=capability_tags,
                )

    def record_audit_event(
        self,
        tenant_id: str | None,
        actor: str,
        op: str,
        target_id: str | None,
        diff: dict[str, Any],
        *,
        source: str | None = None,
        trust_tier: int | None = None,
        capability_tags: list[str] | None = None,
    ) -> None:
        self._audit(
            tenant_id,
            actor,
            op,
            target_id,
            diff,
            source=source,
            trust_tier=trust_tier,
            capability_tags=capability_tags,
        )

    def _audit_row(
        self,
        conn: sqlite3.Connection,
        tenant_id: str | None,
        actor: str,
        op: str,
        target_id: str | None,
        diff: dict[str, Any],
        *,
        source: str | None = None,
        trust_tier: int | None = None,
        capability_tags: list[str] | None = None,
    ) -> None:
        """Append an audit row riding the caller's transaction; the record dict
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
        # Security audit stream (§3): every mediated write emits an entry carrying
        # actor · source · trust-tier · diff (all four persisted in `record`);
        # surface the live per-write counter for the observability checklist.
        self.metrics.increment("sqlite.audit.writes")

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
                    self._audit_row(
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
                        self._audit_row(
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
                self._audit_row(
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
                # Evidence-durability signal (§1a, highest SLO): the per-line
                # CIDJournal.append fsyncs — time it as the durability/journal-lag
                # sample so a divergence between ledger and journal is observable.
                journal_start = time.perf_counter()
                CIDJournal(self._journal_dir / journal_filename(stored.tenant_id)).append(
                    {
                        "cid": stored.cid,
                        "tenant_id": stored.tenant_id,
                        "kind": "evidence",
                        "content": stored.content,
                        "created_at": stored.created_at.isoformat(),
                    }
                )
                self.metrics.observe(
                    "sqlite.evidence.durability.journal_lag_ms",
                    (time.perf_counter() - journal_start) * 1000.0,
                )
            # The WAL commit above (synchronous=FULL) is the durable ledger write;
            # count it and keep the evidence-loss counter pinned at zero.
            self.metrics.increment("sqlite.evidence.durability.appends")
            self.metrics.increment("sqlite.evidence.durability.loss", 0)
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
                # Privacy tightening (raised sensitivity / added restriction /
                # nulled embedding) always invalidates any cached vector for this
                # cid — purge unconditionally (restriction/hold purge rail, R4).
                self._purge_embedding_cache_row(conn, tenant_id, cid)
                self._audit_row(
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

    def evidence_is_erased(self, tenant_id: str, cid: str, branch: str = "main") -> bool:
        """Engine-neutral tombstone probe (see ``MemoryEngine.evidence_is_erased``).

        A tombstoned row is retained with ``erased = 1`` as the replay blocklist
        (``_fetch_evidence`` is store-core: no erased/policy masking); a legal
        hard-delete removes the row and returns False.
        """
        ev = self._fetch_evidence(tenant_id, cid, branch)
        return bool(ev and ev.erased)

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
                # A metadata patch that signals a restriction/hold/quarantine
                # change (or drops the embedding partition to "none") invalidates
                # the cached vector for this cid — purge on those paths (R4).
                if _metadata_patch_tightens_privacy(metadata_patch) or not self._embedding_cache_admits(
                    sensitivity=int(ev.sensitivity), access_policy=ev.access_policy, erased=ev.erased
                ):
                    self._purge_embedding_cache_row(conn, tenant_id, cid)
                self._audit_row(
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
                    self._audit_row(
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
                # A1: mirror the just-set embedding into the subject-scoped cache
                # when admissible (same txn; invisible to export parity). The
                # cache_key is the STORED cid (already subject-salted for S2+/PII).
                if self._embedding_cache_admits(
                    sensitivity=int(ev.sensitivity), access_policy=ev.access_policy, erased=ev.erased
                ):
                    self._embedding_cache_store_row(
                        conn, tenant_id, cid, self._model_id(), list(embedding), int(ev.sensitivity)
                    )
                self._audit_row(
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

    # --- scan surfaces (dense / lexical / graph) -----------------------------
    #
    # Parity strategy (Task 4): LocalMemoryEngine is the byte-parity ORACLE.
    # Rather than re-derive the ~200-line candidate/graph security+redaction
    # surface over SQL (a copy that could drift), the scan methods hydrate a
    # SCOPED LocalMemoryEngine from SQL — one that SHARES this engine's policy
    # and adapters — and reuse Local's ACTUAL ``_candidate_hits`` / ``graph_ppr``
    # / ``_embedding_for_hit`` bodies (the strongest form of the task-3
    # "import Local's pure helpers, do not re-derive" rule; it transitively
    # reuses ``_relation_hit_security`` / ``_valid_at`` /
    # ``_filter_graph_adapter_hits`` / ``_projection_reality_monitoring_from_calibration``
    # etc. verbatim). The SQL SELECT is the permitted prefilter; ``may_read_item``
    # + redactions stay the app-side authority inside Local's bodies. The two
    # genuinely SQLite-specific seams — the PACKED-BLOB dense scan and the FTS5
    # lexical prefilter — are implemented directly on top of that oracle.

    def _embed_text(self, text: str) -> list[float]:
        return self.adapters.embedding.embed(text)

    def _candidate_scope_bounds(self, filt: dict[str, Any]) -> tuple[Any, str, int, int]:
        """Replicate ``LocalMemoryEngine._candidate_hits``'s cheap, indexable
        filter bounds (tenant, branch, max_trust_tier, max_sensitivity) VERBATIM
        (engine.py ``_candidate_hits`` head, incl. the ``min_trust_tier`` legacy
        fallback and the ``include_quarantined`` trust ceiling) so the SQL
        prefilter selects EXACTLY the superset ``_candidate_hits`` iterates —
        the app-side ``may_read_item`` + quarantine/retired/redaction authority
        then narrows identically. NOTE: no valid-window bound is computed here —
        ``_candidate_hits`` has none (bitemporal windows live only in
        ``graph_ppr``/``as_of``, kept in Python), so the DATETIME HAZARD never
        touches this path."""
        tenant_id = filt.get("tenant_id")
        branch = str(filt.get("branch", "main"))
        include_quarantined = bool(filt.get("include_quarantined", False))
        default_max_trust = int(TrustTier.UNTRUSTED_EXTERNAL) if include_quarantined else self.policy.max_trust_tier
        max_trust = int(filt.get("max_trust_tier", filt.get("min_trust_tier", default_max_trust)))
        max_sensitivity = effective_max_sensitivity(filt, self.policy.max_sensitivity)
        return tenant_id, branch, max_trust, max_sensitivity

    def _scan_oracle(
        self, filt: dict[str, Any], *, with_blobs: bool = False
    ) -> LocalMemoryEngine | tuple[LocalMemoryEngine, dict[str, bytes | None]]:
        """Memoizing front for :meth:`_hydrate_scan_oracle`.

        One hydration (and, via the oracle's own candidate memo, ONE
        may_read_item+redaction scan) serves both the dense and lexical
        channels of a retrieve. The cache key carries the indexable scope
        bounds plus two sqlite write fingerprints — ``conn.total_changes``
        (this engine's writes go through the one cached tenant connection) and
        ``PRAGMA data_version`` (commits by any other connection) — so any
        committed change re-hydrates; byte parity with an unmemoized hydration
        is proven in tests/test_engine_perf_lanes.py. Kill-switch:
        MNEMOSYNE_CANDIDATE_MEMO=0 (shared with the Local candidate memo).
        """
        if not _candidate_memo_enabled():
            oracle, raw_blobs = self._hydrate_scan_oracle(filt)
            return (oracle, raw_blobs) if with_blobs else oracle
        tenant_id, branch, max_trust, max_sensitivity = self._candidate_scope_bounds(filt)
        cached: tuple[LocalMemoryEngine, dict[str, bytes | None]]
        if tenant_id:
            with self._lock:
                conn = self._connect(tenant_id)
                data_version = conn.execute("PRAGMA data_version").fetchone()[0]
                key = (tenant_id, branch, max_trust, max_sensitivity, conn.total_changes, data_version)
                cached = self._scan_oracle_memo.get(key)
                if cached is None:
                    cached = self._hydrate_scan_oracle(filt)
                    self._scan_oracle_memo[key] = cached
                    self._scan_oracle_memo.move_to_end(key)
                    while len(self._scan_oracle_memo) > _CANDIDATE_MEMO_SIZE:
                        self._scan_oracle_memo.popitem(last=False)
                else:
                    self._scan_oracle_memo.move_to_end(key)
        else:
            cached = self._hydrate_scan_oracle(filt)
        oracle, raw_blobs = cached
        return (oracle, raw_blobs) if with_blobs else oracle

    def _hydrate_scan_oracle(
        self, filt: dict[str, Any]
    ) -> tuple[LocalMemoryEngine, dict[str, bytes | None]]:
        """Hydrate a candidate-scope oracle by SQL-PREDICATE PUSHDOWN (Task 7,
        spec §4.2 binding scale requirement): rather than loading the whole
        (tenant, branch) — O(tenant-rows) — the WHERE pushes the cheap, indexable
        subset of ``_candidate_hits``'s filter (tenant, branch, NOT erased,
        ``trust_tier <= max_trust``, ``sensitivity <= max_sensitivity``, and for
        assertions ``status IN ('active','contested')``) so only the O(candidates)
        superset is read. The scoped oracle then runs Local's ACTUAL
        ``_candidate_hits`` app-side, applying ``may_read_item`` +
        quarantine/retired/redaction — a superset-preserving narrowing, so the
        result is BYTE-IDENTICAL to Local (the Python gate only removes MORE
        rows). ``ORDER BY rowid`` preserves Local's dict-insertion iteration
        order. Preferences stay tenant-scoped (few, tenant-bounded not
        evidence-bounded; their ``status='active'`` lives in the JSON record and
        is filtered app-side). The raw packed embedding BLOBs are always
        collected (cheap row-value references), keyed by evidence key for the
        dense seam; :meth:`_scan_oracle` hands them out on ``with_blobs``."""
        tenant_id, branch, max_trust, max_sensitivity = self._candidate_scope_bounds(filt)
        oracle = LocalMemoryEngine(policy=self.policy, adapters=self.adapters)
        raw_blobs: dict[str, bytes | None] = {}
        if tenant_id:
            conn = self._connect(tenant_id)
            with self._lock:
                # ORDER BY rowid == insertion order, matching LocalMemoryEngine's
                # dict-values iteration order (a bare WHERE would use the PK
                # index and return cid/id order, breaking equal-score tie parity).
                # The trust/sensitivity/erased predicates are the pushed-down
                # superset of _candidate_hits' per-row skips.
                ev_rows = conn.execute(
                    "SELECT * FROM evidence WHERE tenant_id = ? AND branch = ? "
                    "AND erased = 0 AND trust_tier <= ? AND sensitivity <= ? ORDER BY rowid",
                    (tenant_id, branch, max_trust, max_sensitivity),
                ).fetchall()
                a_rows = conn.execute(
                    "SELECT * FROM assertions WHERE tenant_id = ? AND branch = ? "
                    "AND status IN ('active', 'contested') "
                    "AND trust_tier <= ? AND sensitivity <= ? ORDER BY rowid",
                    (tenant_id, branch, max_trust, max_sensitivity),
                ).fetchall()
                p_rows = conn.execute(
                    "SELECT record FROM preferences WHERE tenant_id = ? ORDER BY rowid",
                    (tenant_id,),
                ).fetchall()
            for row in ev_rows:
                ev = _evidence_from_row(row)
                key = oracle._evidence_key(ev.tenant_id, ev.branch, ev.cid or "")
                oracle.evidence[key] = ev
                raw_blobs[key] = row["embedding"]
            for row in a_rows:
                assertion = _assertion_from_row(row)
                oracle.assertions[assertion.id] = assertion
            for row in p_rows:
                pref = Preference.from_dict(json.loads(row["record"]))
                oracle.preferences[pref.id] = pref
        return oracle, raw_blobs

    def _graph_oracle(
        self,
        tenant_id: str | None,
        branch: str | None,
        filt: dict[str, Any] | None,
    ) -> LocalMemoryEngine:
        """Hydrate a graph-scope oracle: relations plus the evidence their
        source-CID security lookups read. Scoped to (tenant, branch) when a
        branch is given, else tenant-wide (Local considers all branches)."""
        target = tenant_id or dict(filt or {}).get("tenant_id")
        oracle = LocalMemoryEngine(policy=self.policy, adapters=self.adapters)
        if not target:
            return oracle
        conn = self._connect(target)
        if branch is not None:
            rel_sql = "SELECT * FROM relations WHERE tenant_id = ? AND branch = ? ORDER BY rowid"
            ev_sql = "SELECT * FROM evidence WHERE tenant_id = ? AND branch = ? ORDER BY rowid"
            params: tuple[str, ...] = (target, branch)
        else:
            rel_sql = "SELECT * FROM relations WHERE tenant_id = ? ORDER BY rowid"
            ev_sql = "SELECT * FROM evidence WHERE tenant_id = ? ORDER BY rowid"
            params = (target,)
        with self._lock:
            rel_rows = conn.execute(rel_sql, params).fetchall()
            ev_rows = conn.execute(ev_sql, params).fetchall()
        for row in rel_rows:
            rel = _relation_from_row(row)
            oracle.relations[rel.id] = rel
        for row in ev_rows:
            ev = _evidence_from_row(row)
            oracle.evidence[oracle._evidence_key(ev.tenant_id, ev.branch, ev.cid or "")] = ev
        return oracle

    def _packed_embedding_for_hit(
        self,
        hit: Hit,
        filt: dict[str, Any] | None,
        dims: int,
        *,
        oracle: LocalMemoryEngine,
        raw_blobs: dict[str, bytes | None],
    ) -> bytes | None:
        """Packed-BLOB analogue of ``LocalMemoryEngine._embedding_for_hit``
        (allow_fallback default): identical gating and identical metadata
        side-effects, but returns the RAW stored packed f64 BLOB (zero per-call
        conversion) when the gate passes, packs a fresh re-embed exactly once for
        the fallback branch, and returns ``None`` where Local returns ``None``.
        The uniform-dims guard in :meth:`vector_search` handles heterogeneous
        BLOB widths."""
        if hit.kind == "evidence":
            key = oracle._evidence_key(hit.tenant_id, hit.branch, hit.id)
            ev = oracle.evidence.get(key)
            if ev and ev.embedding:
                decision = may_read_item(
                    item_tenant_id=ev.tenant_id,
                    sensitivity=int(ev.sensitivity),
                    access_policy=ev.access_policy,
                    context=filt,
                    policy_max_sensitivity=self.policy.max_sensitivity,
                    status="active",
                    erased=ev.erased,
                )
                if may_use_stored_embedding(
                    decision=decision,
                    sensitivity=int(ev.sensitivity),
                    access_policy=ev.access_policy,
                    embedding_partition=ev.metadata.get("embedding_partition"),
                ):
                    hit.metadata["stored_embedding_used"] = True
                    return raw_blobs.get(key)
        partition = str(hit.metadata.get("embedding_partition") or VECTOR_PARTITION_PUBLIC)
        if partition == "none":
            return None
        hit.metadata["stored_embedding_used"] = False
        return array.array("d", self._embed_text(hit.text)).tobytes()

    @staticmethod
    def _apply_dense_channel(hit: Hit, score: float) -> None:
        hit.score = score
        stored_raw = bool(hit.metadata.get("stored_embedding_used"))
        hit.channel = (
            "dense_media" if stored_raw and hit.metadata.get("stored_media_embedding") else "dense_hash"
        )

    def _fts_candidate_cids(
        self, conn: sqlite3.Connection, tenant_id: str, branch: str, tokens: list[str]
    ) -> set[str]:
        """FTS5 MATCH recall set: evidence cids whose content matches ANY query
        token (OR-of-quoted-terms). Prefilter only — never ranking."""
        match_query = " OR ".join(f'"{token}"' for token in tokens)
        with self._lock:
            rows = conn.execute(
                "SELECT cid FROM evidence_fts "
                "WHERE evidence_fts MATCH ? AND tenant_id = ? AND branch = ?",
                (match_query, tenant_id, branch),
            ).fetchall()
        return {row[0] for row in rows}

    def vector_search(self, query: str, k: int, filt: dict[str, Any]) -> list[Hit]:
        """Dense scan over the PACKED-BLOB seam (spec §8 Phase-1 exit item).

        Candidates come from the hydrated-oracle ``_candidate_hits`` (byte
        identical to Local). The native path feeds the RAW stored packed f64
        BLOBs to ``dense_scan_packed`` with ZERO per-call float conversion
        (bit-parity-proven vs ``dense_scan`` over equal-dims inputs); the
        fallback re-embed is packed exactly once. GUARD: if any PRESENT stored
        BLOB length != ``dims*8`` (heterogeneous dims — e.g. a media embedding),
        the whole call falls back to the list ``dense_scan`` path (still native,
        byte-parity) so mixed-width corpora stay correct; a uniform-dims corpus
        hits the packed fast path. Pure mode uses the per-hit ``cosine`` loop.
        Channels: dense_hash / dense_media."""
        query_vec = embed_query(self.adapters.embedding, query)
        dims = len(query_vec)
        oracle, raw_blobs = self._scan_oracle(filt, with_blobs=True)
        candidates = oracle._candidate_hits(filt)
        hits: list[Hit] = []
        if text_kernels.NATIVE is not None:
            chunks = [
                self._packed_embedding_for_hit(hit, filt, dims, oracle=oracle, raw_blobs=raw_blobs)
                for hit in candidates
            ]
            heterogeneous = any(chunk is not None and len(chunk) != dims * 8 for chunk in chunks)
            if heterogeneous:
                # GUARD path: mixed embedding widths — reuse Local's exact list
                # dense_scan fast path (byte-parity), never the packed seam.
                vectors = [oracle._embedding_for_hit(hit, filt) for hit in candidates]
                scores = text_kernels.NATIVE.dense_scan(query_vec, vectors)
                for hit, hit_vec, score in zip(candidates, vectors, scores, strict=True):
                    if hit_vec is None:
                        continue
                    if score > 0:
                        self._apply_dense_channel(hit, score)
                        hits.append(hit)
            else:
                rows_bytes = b"".join(chunk if chunk else b"\x00" * (dims * 8) for chunk in chunks)
                row_mask = bytes(1 if chunk else 0 for chunk in chunks)
                query_bytes = array.array("d", query_vec).tobytes()
                scores = text_kernels.NATIVE.dense_scan_packed(query_bytes, rows_bytes, dims, row_mask)
                for hit, chunk, score in zip(candidates, chunks, scores, strict=True):
                    if chunk is None:
                        continue
                    if score > 0:
                        self._apply_dense_channel(hit, score)
                        hits.append(hit)
        else:
            for hit in candidates:
                hit_vec = oracle._embedding_for_hit(hit, filt)
                if hit_vec is None:
                    continue
                score = cosine(query_vec, hit_vec)
                if score > 0:
                    self._apply_dense_channel(hit, score)
                    hits.append(hit)
        return LocalMemoryEngine._mark_retrieved_text_as_data(
            sorted(hits, key=lambda item: item.score, reverse=True)[:k]
        )

    def lexical_search(self, query: str, k: int, filt: dict[str, Any]) -> list[Hit]:
        """FTS5-prefiltered lexical scan (spec §4.2).

        The adapter branch is honoured first (mirrors Local). Fallback: the FTS5
        MATCH is candidate RECALL ONLY — it never ranks. When every query token
        is :func:`fts_safe_query`-safe the evidence candidates are narrowed to
        the FTS MATCH set (a proven superset of the rows the shared
        ``lexical_score`` would score > 0); otherwise the engine full-scans (the
        unicode61 tokenizer-mismatch guard). Either way the shared
        ``lexical_score`` rescore over the surviving candidates is the SOLE
        ranking authority, so results byte-match Local's full-scan. Assertions
        and preferences are always rescored (never FTS-narrowed — the index
        covers evidence content only). Channel: lexical."""
        tenant_id = str(filt.get("tenant_id") or "")
        branch = str(filt.get("branch") or "main")
        if self.adapters.lexical_retriever is not None:
            hits = self.adapters.lexical_retriever.search(
                query, tenant_id=tenant_id, branch=branch, k=k, filt=filt
            )
            hits = validate_adapter_hit_scope(
                hits, tenant_id=tenant_id, branch=branch, k=k, adapter_name="lexical"
            )
            return LocalMemoryEngine._mark_retrieved_text_as_data(hits)
        oracle = self._scan_oracle(filt)
        candidates = oracle._candidate_hits(filt)
        allowed_evidence_cids: set[str] | None = None
        tokens = tokenize(query)
        if tenant_id and tokens and fts_safe_query(tokens):
            conn = self._connect(tenant_id)
            allowed_evidence_cids = self._fts_candidate_cids(conn, tenant_id, branch, tokens)
        scored = [
            hit
            for hit in candidates
            if not (
                allowed_evidence_cids is not None
                and hit.kind == "evidence"
                and hit.id not in allowed_evidence_cids
            )
        ]
        hits = []
        if text_kernels.NATIVE is not None:
            scores = text_kernels.NATIVE.lexical_scan(query, [hit.text for hit in scored])
            for hit, score in zip(scored, scores, strict=True):
                if score > 0:
                    hit.score = score
                    hit.channel = "lexical"
                    hits.append(hit)
        else:
            for hit in scored:
                score = lexical_score(query, hit.text)
                if score > 0:
                    hit.score = score
                    hit.channel = "lexical"
                    hits.append(hit)
        return LocalMemoryEngine._mark_retrieved_text_as_data(
            sorted(hits, key=lambda item: item.score, reverse=True)[:k]
        )

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
        """Live personalized-PageRank over the relations graph (spec §4.2).

        Delegated to LocalMemoryEngine's exact ``graph_ppr`` body over a
        graph-scope oracle hydrated from SQL (relations + the evidence their
        security lookups read). Seed lowercasing, the bitemporal validity window
        (``_valid_at``), ``_relation_hit_security`` + ``may_read_item`` gating,
        the graph adapter branch, ``ppr_power_iteration``, direct-seed-first Hit
        construction, and ``_mark_retrieved_text_as_data`` are thereby reused
        verbatim — byte-identical to the oracle.

        ``use_cache=True`` (Task 8): when a materialized cached-PPR payload for
        this (branch, seed-set, as-of) exists AND its relations+custody watermark
        still matches AND it holds >= k hits AND the context is the default
        reader, that payload is served (each hit re-tagged
        ``metadata['graph_signal_cached'] = True`` — GraphSignalCache-compatible;
        the hit ``channel`` is unchanged so results are signature-identical to a
        live traversal). Any miss/staleness/elevated-context falls THROUGH to the
        live path, so ``use_cache=False`` and an unpopulated/stale cache are both
        byte-identical to the pre-Task-8 oracle behaviour."""
        if use_cache:
            cached = self._read_ppr_cache(seeds, k, as_of=as_of, tenant_id=tenant_id, branch=branch, filt=filt)
            if cached is not None:
                return cached
        return self._compute_graph_ppr(seeds, k, as_of=as_of, tenant_id=tenant_id, branch=branch, filt=filt)

    def _compute_graph_ppr(
        self,
        seeds: list[str],
        k: int,
        *,
        as_of: datetime | None = None,
        tenant_id: str | None = None,
        branch: str | None = None,
        filt: dict[str, Any] | None = None,
    ) -> list[Hit]:
        """Live traversal (the pre-Task-8 ``graph_ppr`` body). A distinct method
        so ``refresh_graph_ppr_cache`` and the TOCTOU tests can hook the compute
        step between the pre-rebuild fingerprint capture and the payload write."""
        oracle = self._graph_oracle(tenant_id, branch, filt)
        return oracle.graph_ppr(
            seeds,
            k,
            as_of=as_of,
            tenant_id=tenant_id,
            branch=branch,
            use_cache=False,
            filt=filt,
        )

    # --- Task 8: embedding cache (A1) ----------------------------------------
    #
    # A subject-scoped embedding cache keyed by (cache_key, model_id), where
    # cache_key is the STORED evidence cid. ``ids.evidence_cid`` already mixes
    # user_id into the content address for sensitivity >= 2 / detected PII, so
    # two subjects with identical S2+/PII plaintext produce different cids —
    # that reused salt is precisely what closes the dedup-oracle rail (no new
    # salting is invented here). The cache is invisible to ``export_tenant`` /
    # parity: it is a pure recompute-avoidance + privacy surface.

    def _model_id(self) -> str:
        """Stable identity of the active embedding model (cache key component)."""
        provider = self.adapters.embedding
        for attr in ("model_id", "model", "name"):
            value = getattr(provider, attr, None)
            if value:
                return str(value)
        return type(provider).__name__

    def _embedding_cache_admits(
        self, *, sensitivity: int, access_policy: Any, erased: bool = False, status: str = "active"
    ) -> bool:
        """Admission predicate (spec §4.2 A1). Never admits a ``none`` partition
        (S4 / ``embed_ok:false`` / ``restricted`` / ``hold`` / unknown-policy /
        erased). S3 is admitted only under the sensitive-embedding deployment
        flag, which does not exist → S3 fails closed. S0–S2 with a usable
        partition are admitted (their cid is already subject-salted for S2)."""
        partition = vector_partition_for_item(
            sensitivity=int(sensitivity), access_policy=access_policy, status=status, erased=erased
        )
        if partition == VECTOR_PARTITION_NONE:
            return False
        if int(sensitivity) >= 3:
            return _SENSITIVE_EMBEDDING_CACHE_ENABLED
        return True

    @staticmethod
    def _embedding_cache_store_row(
        conn: sqlite3.Connection,
        tenant_id: str,
        cache_key: str,
        model_id: str,
        vector: list[float],
        sensitivity: int,
    ) -> None:
        conn.execute(
            "INSERT OR REPLACE INTO embedding_cache "
            "(tenant_id, cache_key, model_id, embedding, dims, sensitivity, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                tenant_id,
                str(cache_key),
                model_id,
                pack_embedding(list(vector)),
                len(vector),
                int(sensitivity),
                dt_to_json(utc_now()),
            ),
        )

    def _embedding_cache_fetch(
        self, conn: sqlite3.Connection, tenant_id: str, cache_key: str, model_id: str
    ) -> list[float] | None:
        with self._lock:
            row = conn.execute(
                "SELECT embedding FROM embedding_cache WHERE tenant_id = ? AND cache_key = ? AND model_id = ?",
                (tenant_id, str(cache_key), model_id),
            ).fetchone()
        return None if row is None else unpack_embedding(row["embedding"])

    @staticmethod
    def _purge_embedding_cache_row(conn: sqlite3.Connection, tenant_id: str, cache_key: str) -> int:
        cur = conn.execute(
            "DELETE FROM embedding_cache WHERE tenant_id = ? AND cache_key = ?", (tenant_id, str(cache_key))
        )
        return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

    def purge_embedding_cache(self, tenant_id: str, cid: str) -> int:
        """Purge every cached vector for ``cid`` (all model_ids). Exposed for the
        Task-9 ``forget`` wiring and invoked internally by the restriction/hold
        privacy paths. Removes the row entirely so no cid-recoverable trace of
        the erased content survives in the cache (privacy class 13)."""
        with self._lock:
            conn = self._connect(tenant_id)
            with conn:
                removed = self._purge_embedding_cache_row(conn, tenant_id, cid)
        return removed

    def _cache_record(self, tenant_id: str, hit: bool) -> None:
        """Tenant-granular hit/miss telemetry ONLY — a per-cid counter would
        itself be a presence oracle."""
        stats = self._cache_telemetry.setdefault(str(tenant_id), {"hits": 0, "misses": 0})
        stats["hits" if hit else "misses"] += 1

    def cache_stats(self, tenant_id: str) -> dict[str, int]:
        """Tenant-granular embedding-cache hit/miss counters."""
        return dict(self._cache_telemetry.get(str(tenant_id), {"hits": 0, "misses": 0}))

    def cached_embedding(
        self,
        tenant_id: str,
        cid: str,
        text: str,
        *,
        sensitivity: int,
        access_policy: Any,
        erased: bool = False,
        embedding_partition: str | None = None,
        context: dict[str, Any] | None = None,
        model_id: str | None = None,
        store: bool = True,
    ) -> list[float]:
        """A1 read-through embedding cache with ``may_use_stored_embedding``
        read gating. A DENIED context (or a cross-subject cid that isn't present)
        goes through the IDENTICAL miss branch as any genuine miss — the provider
        is always called and the fresh vector returned; it is stored only when
        the read gate permits AND the item is admissible. This makes a
        cross-subject S2+ probe indistinguishable from a miss (class 10)."""
        model = model_id or self._model_id()
        decision = may_read_item(
            item_tenant_id=tenant_id,
            sensitivity=int(sensitivity),
            access_policy=access_policy,
            context=context,
            policy_max_sensitivity=self.policy.max_sensitivity,
            status="active",
            erased=erased,
        )
        gate = may_use_stored_embedding(
            decision=decision,
            sensitivity=int(sensitivity),
            access_policy=access_policy,
            embedding_partition=embedding_partition,
        )
        if gate:
            conn = self._connect(tenant_id)
            cached = self._embedding_cache_fetch(conn, tenant_id, str(cid), model)
            if cached is not None:
                self._cache_record(tenant_id, True)
                return cached
        self._cache_record(tenant_id, False)
        vector = self._embed_text(text)
        if gate and store and self._embedding_cache_admits(
            sensitivity=int(sensitivity), access_policy=access_policy, erased=erased
        ):
            with self._lock:
                conn = self._connect(tenant_id)
                with conn:
                    self._embedding_cache_store_row(conn, tenant_id, str(cid), model, vector, int(sensitivity))
        return vector

    # --- Task 8: cached-PPR projection + projection registry -----------------

    def _relations_fingerprint(self, tenant_id: str, branch: str) -> str:
        """Relations+source-custody watermark for (tenant, branch): a stable hash
        over relation rows AND the custody (trust/sensitivity/metadata/erased/
        access_policy/presence) of their source evidence. Adding/removing/editing
        a relation OR changing a source's custody (quarantine, erasure, backfill)
        changes the digest, so a dependent cached-PPR payload self-invalidates on
        the next read. Timestamps are hashed verbatim (never compared lexically —
        the DATETIME HAZARD does not apply to equality)."""
        conn = self._connect(tenant_id)
        branch_key = str(branch or "main")
        with self._lock:
            rel_rows = conn.execute(
                "SELECT id, source, predicate, target, confidence, valid_from, valid_to, "
                "source_evidence_cids, access_policy FROM relations "
                "WHERE tenant_id = ? AND branch = ? ORDER BY id",
                (tenant_id, branch_key),
            ).fetchall()
            rel_payload: list[tuple[sqlite3.Row, list[str]]] = []
            wanted: set[str] = set()
            for row in rel_rows:
                source_cids = [str(c) for c in json.loads(row["source_evidence_cids"] or "[]") if c]
                wanted.update(source_cids)
                rel_payload.append((row, source_cids))
            custody: dict[str, sqlite3.Row] = {}
            if wanted:
                ordered = sorted(wanted)
                placeholders = ",".join("?" for _ in ordered)
                ev_rows = conn.execute(
                    "SELECT cid, trust_tier, sensitivity, metadata, erased, source_type, actor, access_policy "
                    f"FROM evidence WHERE tenant_id = ? AND branch = ? AND cid IN ({placeholders})",
                    (tenant_id, branch_key, *ordered),
                ).fetchall()
                custody = {row["cid"]: row for row in ev_rows}
        payload = [
            {
                "id": row["id"],
                "source": row["source"],
                "predicate": row["predicate"],
                "target": row["target"],
                "confidence": float(row["confidence"]),
                "valid_from": row["valid_from"],
                "valid_to": row["valid_to"],
                "source_evidence_cids": list(source_cids),
                "access_policy": json.loads(row["access_policy"] or "{}"),
                "source_evidence_custody": [
                    {
                        "cid": cid,
                        "present": cid in custody,
                        "trust_tier": int(custody[cid]["trust_tier"]) if cid in custody else None,
                        "sensitivity": int(custody[cid]["sensitivity"]) if cid in custody else None,
                        "metadata": json.loads(custody[cid]["metadata"] or "{}") if cid in custody else None,
                        "erased": bool(custody[cid]["erased"]) if cid in custody else None,
                        "source_type": str(custody[cid]["source_type"]) if cid in custody else None,
                        "actor": str(custody[cid]["actor"]) if cid in custody else None,
                        "access_policy": json.loads(custody[cid]["access_policy"] or "{}") if cid in custody else None,
                    }
                    for cid in source_cids
                ],
            }
            for row, source_cids in rel_payload
        ]
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _relations_fingerprint_all(self, tenant_id: str) -> str:
        """Tenant-wide relations watermark (all branches) for the registered
        ``cached-ppr`` ProjectionSpec fingerprint."""
        conn = self._connect(tenant_id)
        with self._lock:
            rows = conn.execute(
                "SELECT branch, id, source, predicate, target, confidence, valid_from, valid_to, "
                "source_evidence_cids, access_policy FROM relations WHERE tenant_id = ? ORDER BY branch, id",
                (tenant_id,),
            ).fetchall()
        encoded = json.dumps([list(row) for row in rows], sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _is_default_reader_context(self, filt: dict[str, Any] | None) -> bool:
        """Whether ``filt`` is the default reader visibility the cache was
        materialized under. Any elevation (quarantine, raised trust/sensitivity,
        non-reader role, extra context keys) bypasses the cache and goes live, so
        the cache can never leak elevated-visibility hits to a plain reader."""
        ctx = dict(filt or {})
        if bool(ctx.get("include_quarantined", False)):
            return False
        default_max_trust = int(self.policy.max_trust_tier)
        if "max_trust_tier" in ctx or "min_trust_tier" in ctx:
            max_trust = int(ctx.get("max_trust_tier", ctx.get("min_trust_tier", default_max_trust)))
            if max_trust != default_max_trust:
                return False
        role = str(ctx.get("role") or ctx.get("mnemosyne_role") or "reader").lower()
        if role != "reader":
            return False
        default_reader_sensitivity = effective_max_sensitivity({"role": "reader"}, self.policy.max_sensitivity)
        if effective_max_sensitivity(ctx, self.policy.max_sensitivity) != default_reader_sensitivity:
            return False
        if set(ctx) - {"tenant_id", "tenant", "branch", "role", "mnemosyne_role"}:
            return False
        return True

    @staticmethod
    def _store_ppr_cache(
        conn: sqlite3.Connection,
        tenant_id: str,
        branch: str,
        seed_hash: str,
        as_of_key: str,
        fingerprint: str,
        depth: int,
        seeds: list[str],
        hits: list[Hit],
    ) -> None:
        conn.execute(
            "INSERT OR REPLACE INTO graph_ppr_cache "
            "(tenant_id, branch, seed_hash, as_of_key, relation_fingerprint, cache_depth, seeds, hits, refreshed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                tenant_id,
                branch,
                seed_hash,
                as_of_key,
                fingerprint,
                int(depth),
                json.dumps(list(seeds), separators=(",", ":")),
                json.dumps([hit.to_dict() for hit in hits], separators=(",", ":")),
                dt_to_json(utc_now()),
            ),
        )

    def _read_ppr_cache(
        self,
        seeds: list[str],
        k: int,
        *,
        as_of: datetime | None,
        tenant_id: str | None,
        branch: str | None,
        filt: dict[str, Any] | None = None,
    ) -> list[Hit] | None:
        """Serve a materialized cached-PPR payload iff the seed-set/as-of key
        exists, the relations+custody watermark still matches, the payload holds
        >= k hits, and the context is the default reader. Each served hit is
        re-tagged ``metadata['graph_signal_cached'] = True`` (channel unchanged →
        signature-identical to a live traversal). Any failure returns ``None`` so
        the caller falls through to the live path (byte-parity preserved)."""
        seed_set = {str(seed).lower() for seed in seeds}
        if not seed_set or not tenant_id:
            return None
        if not self._is_default_reader_context(filt):
            return None
        branch_key = str(branch or "main")
        moment = as_of or utc_now()
        moment = moment.astimezone(UTC) if moment.tzinfo else moment.replace(tzinfo=UTC)
        seed_hash = _graph_ppr_seed_hash(seed_set)
        as_of_key = _graph_ppr_as_of_key(as_of, moment)
        fingerprint = self._relations_fingerprint(tenant_id, branch_key)
        conn = self._connect(tenant_id)
        with self._lock:
            row = conn.execute(
                "SELECT relation_fingerprint, cache_depth, hits FROM graph_ppr_cache "
                "WHERE tenant_id = ? AND branch = ? AND seed_hash = ? AND as_of_key = ?",
                (tenant_id, branch_key, seed_hash, as_of_key),
            ).fetchone()
        if row is None or row["relation_fingerprint"] != fingerprint:
            return None
        stored = json.loads(row["hits"] or "[]")
        if int(row["cache_depth"] or 0) < k or len(stored) < k:
            return None
        hits: list[Hit] = []
        for item in stored[:k]:
            data = dict(item)
            metadata = dict(data.get("metadata") or {})
            metadata["graph_signal_cached"] = True
            data["metadata"] = metadata
            hits.append(Hit(**data))
        return hits

    def refresh_graph_ppr_cache(
        self,
        seeds: list[str],
        k: int,
        as_of: datetime | None = None,
        tenant_id: str | None = None,
        branch: str = "main",
    ) -> dict[str, Any]:
        """Materialize the cached-PPR payload for this (seed-set, as-of), mirroring
        PostgresEngine.refresh_graph_ppr_cache. The relations+custody watermark is
        captured BEFORE the live recompute (TOCTOU handoff, Phase-0 T9 review): if
        relations mutate during the compute, the stored fingerprint is the
        pre-mutation snapshot, so the next read recomputes rather than serving a
        payload that never reflected a consistent graph."""
        seed_set = {str(seed).lower() for seed in seeds}
        if not seed_set or not tenant_id:
            return {"refreshed": False, "reason": "missing_seed_or_tenant", "hit_count": 0}
        tenant_id = str(tenant_id)
        branch_key = str(branch or "main")
        moment = as_of or utc_now()
        moment = moment.astimezone(UTC) if moment.tzinfo else moment.replace(tzinfo=UTC)
        seed_hash = _graph_ppr_seed_hash(seed_set)
        as_of_key = _graph_ppr_as_of_key(as_of, moment)
        with self._lock:
            fingerprint = self._relations_fingerprint(tenant_id, branch_key)  # BEFORE compute (TOCTOU)
            hits = self._compute_graph_ppr(seeds, k, as_of=as_of, tenant_id=tenant_id, branch=branch_key)
            conn = self._connect(tenant_id)
            with conn:
                self._store_ppr_cache(
                    conn, tenant_id, branch_key, seed_hash, as_of_key, fingerprint, k, sorted(seed_set), hits
                )
        return {
            "refreshed": True,
            "hit_count": len(hits),
            "seed_hash": seed_hash,
            "as_of_key": as_of_key,
            "relation_fingerprint": fingerprint,
        }

    def _rebuild_cached_ppr(self, tenant_id: str) -> None:
        """ProjectionRegistry rebuild for ``cached-ppr``: re-materialize every
        stored ``live`` payload against the current graph (as-of-pinned payloads
        are left for their own refresh — the original moment isn't recoverable
        from the key alone)."""
        conn = self._connect(tenant_id)
        with self._lock:
            rows = conn.execute(
                "SELECT branch, seeds, cache_depth FROM graph_ppr_cache "
                "WHERE tenant_id = ? AND as_of_key = 'live'",
                (tenant_id,),
            ).fetchall()
        for row in rows:
            seeds = json.loads(row["seeds"] or "[]")
            self.refresh_graph_ppr_cache(seeds, int(row["cache_depth"] or 0), tenant_id=tenant_id, branch=row["branch"])

    def _evidence_fts_fingerprint(self, tenant_id: str) -> str:
        conn = self._connect(tenant_id)
        with self._lock:
            rows = conn.execute(
                "SELECT branch, cid, content FROM evidence WHERE tenant_id = ? ORDER BY branch, cid",
                (tenant_id,),
            ).fetchall()
        encoded = json.dumps(
            [[row["branch"], row["cid"], row["content"]] for row in rows], sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _rebuild_evidence_fts(self, tenant_id: str) -> None:
        """Re-derive the FTS5 candidate-recall index from evidence rows (the
        triggers keep it in lockstep in steady state; this is the disaster/first-
        run rebuild path the ProjectionRegistry drives on a fingerprint miss)."""
        conn = self._connect(tenant_id)
        with self._lock, conn:
            conn.execute("DELETE FROM evidence_fts")
            conn.execute(
                "INSERT INTO evidence_fts(rowid, cid, tenant_id, branch, content) "
                "SELECT rowid, cid, tenant_id, branch, content FROM evidence WHERE tenant_id = ?",
                (tenant_id,),
            )

    def _evidence_vec0_fingerprint(self, tenant_id: str) -> str:  # pragma: no cover - needs sqlite-vec
        conn = self._connect(tenant_id)
        with self._lock:
            rows = conn.execute(
                "SELECT branch, cid FROM evidence WHERE tenant_id = ? AND embedding IS NOT NULL ORDER BY branch, cid",
                (tenant_id,),
            ).fetchall()
        encoded = json.dumps(
            [[row["branch"], row["cid"]] for row in rows], sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _rebuild_evidence_vec0(self, tenant_id: str) -> None:  # pragma: no cover - needs sqlite-vec
        """OPTIONAL dense candidate index (vec0). Only registered/run when
        ``sqlite_vec_available()``; the DEFAULT dense channel is always the
        packed-BLOB kernel exact scan, so this is a pure approximate-recall
        optimization behind the projection registry."""
        import sqlite_vec  # type: ignore[import-not-found]

        conn = self._connect(tenant_id)
        with self._lock, conn:
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
            probe = conn.execute(
                "SELECT embedding FROM evidence WHERE tenant_id = ? AND embedding IS NOT NULL LIMIT 1",
                (tenant_id,),
            ).fetchone()
            if probe is None:
                return
            dims = len(unpack_embedding(probe["embedding"]) or [])
            if dims <= 0:
                return
            conn.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS evidence_vec0 USING vec0(cid TEXT, embedding float[{dims}])")
            conn.execute("DELETE FROM evidence_vec0")
            for row in conn.execute(
                "SELECT cid, embedding FROM evidence WHERE tenant_id = ? AND embedding IS NOT NULL",
                (tenant_id,),
            ).fetchall():
                vector = unpack_embedding(row["embedding"]) or []
                if len(vector) == dims:
                    conn.execute(
                        "INSERT INTO evidence_vec0(cid, embedding) VALUES (?, ?)", (row["cid"], json.dumps(vector))
                    )

    def _projection_registry(self, tenant_id: str) -> ProjectionRegistry:
        """Per-tenant ProjectionRegistry (state in ``<tenant>.proj/projections.json``)
        registering the rebuildable projections: cached-ppr, evidence-fts, and —
        only when ``sqlite_vec_available()`` — the optional evidence-vec0 index."""
        key = str(tenant_id)
        registry = self._registries.get(key)
        if registry is not None:
            return registry
        state_dir = self.root_dir / safe_tenant_filename(key, ".proj")
        registry = ProjectionRegistry(state_dir)
        registry.register(
            ProjectionSpec(
                name="cached-ppr",
                version=1,
                fingerprint=lambda t=key: self._relations_fingerprint_all(t),
                rebuild=lambda t=key: self._rebuild_cached_ppr(t),
            )
        )
        registry.register(
            ProjectionSpec(
                name="evidence-fts",
                version=1,
                fingerprint=lambda t=key: self._evidence_fts_fingerprint(t),
                rebuild=lambda t=key: self._rebuild_evidence_fts(t),
            )
        )
        if sqlite_vec_available():  # pragma: no cover - needs sqlite-vec
            registry.register(
                ProjectionSpec(
                    name="evidence-vec0",
                    version=1,
                    fingerprint=lambda t=key: self._evidence_vec0_fingerprint(t),
                    rebuild=lambda t=key: self._rebuild_evidence_vec0(t),
                )
            )
        self._registries[key] = registry
        return registry

    def ensure_projections(self, tenant_id: str, branch: str = "main") -> dict[str, bool]:
        """Consolidation/maintenance hook: rebuild-on-mismatch for every
        registered projection (mirrors ``refresh_graph_ppr_cache`` for the graph
        signal). Returns which projections were rebuilt this call."""
        registry = self._projection_registry(str(tenant_id))
        rebuilt = {
            "cached-ppr": registry.ensure("cached-ppr"),
            "evidence-fts": registry.ensure("evidence-fts"),
        }
        if sqlite_vec_available():  # pragma: no cover - needs sqlite-vec
            rebuilt["evidence-vec0"] = registry.ensure("evidence-vec0")
        # Per-store rebuild-lag signal (§1b): a projection that was stale on this
        # pass (ensure returned True) had a non-zero watermark delta vs the ledger;
        # gauge 1.0 when it had to rebuild, 0.0 when already fresh, and count the
        # rebuilds so derived-store lag is tracked distinctly from durability.
        for name, was_rebuilt in rebuilt.items():
            self.metrics.gauge(f"sqlite.projection.rebuild_lag.{name}", 1.0 if was_rebuilt else 0.0)
            if was_rebuilt:
                self.metrics.increment("sqlite.projection.rebuilds")
        return rebuilt

    def projection_status(self, tenant_id: str) -> dict[str, dict[str, Any]]:
        """Per-projection ``{version, fresh, stored}`` (observability §rebuild-lag)."""
        return self._projection_registry(str(tenant_id)).status()

    def dense_channel(self, tenant_id: str | None = None) -> str:
        """Active dense retrieval channel: the packed-BLOB kernel exact scan by
        default; ``sqlite-vec-vec0`` only when the optional extra is present AND
        its projection is fresh for the tenant."""
        if tenant_id is not None and sqlite_vec_available():  # pragma: no cover - needs sqlite-vec
            registry = self._projection_registry(str(tenant_id))
            try:
                if registry.check("evidence-vec0"):
                    return "sqlite-vec-vec0"
            except KeyError:
                pass
        return "packed-blob-exact-scan"

    def dense_channel_report(self, tenant_id: str | None = None) -> str:
        """doctor/startup line reporting the active dense channel."""
        vec = "available" if sqlite_vec_available() else "absent"
        return (
            f"[sqlite] dense channel active: {self.dense_channel(tenant_id)} "
            f"(sqlite-vec {vec}; default = packed-BLOB kernel exact scan)"
        )

    # --- assertions / bitemporal / remaining writes (Task 5) -----------------
    #
    # Parity strategy: the graph/scan surfaces already established the
    # "hydrate a scoped LocalMemoryEngine from SQL and reuse its exact body"
    # pattern for read paths. The stateful WRITE paths whose cross-row semantics
    # are non-trivial — ``upsert_assertion`` (replay/supersede/contest +
    # projection-reality-monitoring + schema-fast-path calibration mutation),
    # ``add_preference`` (supersession), ``register_entity`` (merge upsert) —
    # run Local's ACTUAL method over an oracle hydrated from SQL, then persist
    # only the genuinely new/changed rows back (rowid preserved for unchanged
    # rows → ``export_tenant`` ORDER BY rowid parity holds) and replay Local's
    # emitted audit rows verbatim. That guarantees the resulting assertions
    # table + audit_log byte-match ``LocalMemoryEngine.export_tenant``. The
    # simple, single-row writes (``add_relation``, ``set_calibration``,
    # ``correct``) mirror Local's short body directly over SQL.

    def _assertion_oracle(
        self, conn: sqlite3.Connection, tenant_id: str, branch: str
    ) -> LocalMemoryEngine:
        """Hydrate an upsert-scope oracle: the tenant's branch registry (so
        Local's own ``_require_branch`` passes), the (tenant, branch) evidence
        (read by projection-reality-monitoring + independent-corroboration), and
        the (tenant, branch) assertions (the supersede/contest peer set). Keys
        match Local's internal keying exactly (``_evidence_key`` / ``_branch_key``)."""
        oracle = LocalMemoryEngine(policy=self.policy, adapters=self.adapters)
        with self._lock:
            branch_rows = conn.execute(
                "SELECT name, from_branch, kind, created_at FROM branches "
                "WHERE tenant_id = ? ORDER BY rowid",
                (tenant_id,),
            ).fetchall()
            ev_rows = conn.execute(
                "SELECT * FROM evidence WHERE tenant_id = ? AND branch = ? ORDER BY rowid",
                (tenant_id, branch),
            ).fetchall()
            a_rows = conn.execute(
                "SELECT * FROM assertions WHERE tenant_id = ? AND branch = ? ORDER BY rowid",
                (tenant_id, branch),
            ).fetchall()
        for row in branch_rows:
            oracle.branches[row["name"]] = {
                "from": row["from_branch"],
                "kind": row["kind"],
                "created_at": row["created_at"],
            }
        for row in ev_rows:
            ev = _evidence_from_row(row)
            oracle.evidence[oracle._evidence_key(ev.tenant_id, ev.branch, ev.cid or "")] = ev
        for row in a_rows:
            assertion = _assertion_from_row(row)
            oracle.assertions[oracle._branch_key(assertion.tenant_id, assertion.branch, assertion.id)] = assertion
        return oracle

    def _preference_oracle(self, conn: sqlite3.Connection, tenant_id: str) -> LocalMemoryEngine:
        """Hydrate a preference-scope oracle: all of the tenant's preferences
        (supersession is tenant/user/category/scope-scoped, never branch-scoped)."""
        oracle = LocalMemoryEngine(policy=self.policy, adapters=self.adapters)
        with self._lock:
            rows = conn.execute(
                "SELECT record FROM preferences WHERE tenant_id = ? ORDER BY rowid",
                (tenant_id,),
            ).fetchall()
        for row in rows:
            pref = Preference.from_dict(json.loads(row["record"]))
            oracle.preferences[pref.id] = pref
        return oracle

    def _entity_oracle(self, conn: sqlite3.Connection, tenant_id: str) -> LocalMemoryEngine:
        """Hydrate an entity-scope oracle: all of the tenant's entities keyed
        by (tenant_id, canonical) exactly as Local keys them."""
        oracle = LocalMemoryEngine(policy=self.policy, adapters=self.adapters)
        with self._lock:
            rows = conn.execute(
                "SELECT canonical, record FROM entities WHERE tenant_id = ? ORDER BY rowid",
                (tenant_id,),
            ).fetchall()
        for row in rows:
            oracle.entities[(tenant_id, row["canonical"])] = json.loads(row["record"])
        return oracle

    @staticmethod
    def _replay_audit(conn: sqlite3.Connection, records: list[dict[str, Any]]) -> None:
        """Persist the audit rows Local emitted (already in Local's exact shape)
        verbatim, riding the caller's transaction."""
        for record in records:
            conn.execute(
                "INSERT INTO audit_log(tenant_id, record) VALUES (?, ?)",
                (record.get("tenant_id"), json_text(record)),
            )

    def _insert_assertion_row(self, conn: sqlite3.Connection, assertion: Assertion) -> None:
        conn.execute(_ASSERTION_INSERT, _assertion_insert_values(assertion))

    def _update_assertion_row(self, conn: sqlite3.Connection, assertion: Assertion) -> None:
        values = _assertion_insert_values(assertion)
        conn.execute(_ASSERTION_UPDATE, (*values[3:], assertion.tenant_id, assertion.branch, assertion.id))

    def upsert_assertion(self, assertion: Assertion, branch: str = "main") -> str:
        """Replay/supersede/contest over SQL, byte-parity with Local.

        ``validate_access_policy`` (fail-closed, Local-parity error text) →
        ``_require_branch`` (ValueError BEFORE the composite FK can fire) →
        run ``LocalMemoryEngine.upsert_assertion`` over a scoped oracle (so the
        projection-reality-monitoring + schema-fast-path calibration/status
        mutations and the trust/valid_from resolution are byte-identical) →
        write back the new/changed assertion rows and Local's emitted audit rows
        in one transaction. Returns the same id Local returns (winner.id on the
        reinforce path, incoming.id otherwise)."""
        validate_access_policy(
            assertion.access_policy,
            tenant_id=assertion.tenant_id,
            location="assertion.access_policy",
        )
        with self._lock:
            conn = self._connect(assertion.tenant_id)
            self._require_branch(conn, assertion.tenant_id, branch)
            oracle = self._assertion_oracle(conn, assertion.tenant_id, branch)
            before = {item.id: item.to_dict() for item in oracle.assertions.values()}
            result_id = oracle.upsert_assertion(copy.deepcopy(assertion), branch=branch)
            with conn:
                for item in oracle.assertions.values():
                    if item.tenant_id != assertion.tenant_id or item.branch != branch:
                        continue
                    snapshot = before.get(item.id)
                    if snapshot is None:
                        self._insert_assertion_row(conn, item)
                    elif item.to_dict() != snapshot:
                        self._update_assertion_row(conn, item)
                self._replay_audit(conn, oracle.audit_log)
            return result_id

    def add_relation(self, relation: Relation, branch: str = "main") -> str:
        """Single-row relation write mirroring ``LocalMemoryEngine.add_relation``:
        validate policy, require the branch (ValueError before the FK), deepcopy,
        set access_policy/branch, UPSERT + audit atomically, return the id."""
        access_policy = validate_access_policy(
            relation.access_policy,
            tenant_id=relation.tenant_id,
            location="relation.access_policy",
        )
        with self._lock:
            conn = self._connect(relation.tenant_id)
            self._require_branch(conn, relation.tenant_id, branch)
            item = copy.deepcopy(relation)
            item.access_policy = access_policy
            item.branch = branch
            with conn:
                conn.execute(_RELATION_UPSERT, _relation_insert_values(item))
                self._audit_row(
                    conn,
                    item.tenant_id,
                    "engine",
                    "add_relation",
                    item.id,
                    {
                        "relation_source": item.source,
                        "target": item.target,
                        "source_evidence_cids": item.source_evidence_cids,
                    },
                    source="relation",
                )
            return item.id

    def add_justification(self, justification: Justification) -> str:
        """Store a TMS justification (record JSON, PK id), byte-parity with
        ``LocalMemoryEngine.add_justification`` — store-then-audit; the row
        rehydrates through ``Justification.from_dict`` on export."""
        with self._lock:
            item = copy.deepcopy(justification)
            conn = self._connect(item.tenant_id)
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO justifications(id, tenant_id, record) VALUES (?, ?, ?)",
                    (item.id, item.tenant_id, json_text(item.to_dict())),
                )
                self._audit_row(
                    conn,
                    item.tenant_id,
                    "engine",
                    "add_justification",
                    item.id,
                    {
                        "assertion_id": item.assertion_id,
                        "evidence_cids": item.evidence_cids,
                        "dependencies": item.dependency_ids,
                    },
                    source="justification",
                )
            return item.id

    def add_contradiction(self, contradiction: Contradiction) -> str:
        """Store a TMS contradiction with Local's open-dedup: an existing OPEN
        row over the same unordered ``{a, b}`` pair for the tenant returns its id
        without inserting (byte-parity with ``LocalMemoryEngine``)."""
        with self._lock:
            item = copy.deepcopy(contradiction)
            conn = self._connect(item.tenant_id)
            with conn:
                rows = conn.execute(
                    "SELECT record FROM contradictions WHERE tenant_id = ?",
                    (item.tenant_id,),
                ).fetchall()
                for row in rows:
                    existing = Contradiction.from_dict(json.loads(row["record"]))
                    if existing.status == "open" and {existing.a, existing.b} == {item.a, item.b}:
                        return existing.id
                conn.execute(
                    "INSERT OR REPLACE INTO contradictions(id, tenant_id, record) VALUES (?, ?, ?)",
                    (item.id, item.tenant_id, json_text(item.to_dict())),
                )
                self._audit_row(
                    conn,
                    item.tenant_id,
                    "engine",
                    "add_contradiction",
                    item.id,
                    {"a": item.a, "b": item.b},
                    source="contradiction",
                )
            return item.id

    def to_json(self) -> str:
        """Full-store JSON export, byte-shape-identical to
        ``LocalMemoryEngine.to_json`` (``export_all`` + sorted-key indent)."""
        return json.dumps(self.export_all(), indent=2, sort_keys=True)

    def add_preference(self, preference: Preference) -> str:
        """Tenant-scoped preference supersession, byte-parity with Local.

        Runs ``LocalMemoryEngine.add_preference`` (same
        tenant/user/category/scope/active supersession + explicit/retracted
        logic) over an oracle hydrated from every tenant preference, then
        persists the new row and any superseded/retracted rows (record JSON,
        rowid preserved) plus Local's audit rows in one transaction."""
        with self._lock:
            conn = self._connect(preference.tenant_id)
            oracle = self._preference_oracle(conn, preference.tenant_id)
            before = {pref.id: pref.to_dict() for pref in oracle.preferences.values()}
            result_id = oracle.add_preference(copy.deepcopy(preference))
            with conn:
                for pref in oracle.preferences.values():
                    if pref.tenant_id != preference.tenant_id:
                        continue
                    current = pref.to_dict()
                    snapshot = before.get(pref.id)
                    if snapshot is None:
                        conn.execute(
                            "INSERT INTO preferences(id, tenant_id, record) VALUES (?, ?, ?)",
                            (pref.id, pref.tenant_id, json_text(current)),
                        )
                    elif current != snapshot:
                        conn.execute(
                            "UPDATE preferences SET record = ? WHERE id = ?",
                            (json_text(current), pref.id),
                        )
                self._replay_audit(conn, oracle.audit_log)
            return result_id

    def as_of(
        self,
        subject: str,
        predicate: str,
        t: datetime,
        tenant_id: str | None = None,
        branch: str = "main",
    ) -> list[Assertion]:
        """Bitemporal read over the half-open [valid_from, valid_to) UTC window.

        Coerces ``t`` to UTC exactly like Local, loads the subject/predicate-scoped
        candidate rows with the cheap indexable predicates (tenant, branch, subject,
        predicate, status) in SQL, then applies the half-open ``[valid_from,
        valid_to)`` window in Python via :func:`mnemosyne.models.parse_dt` — mirroring
        :meth:`LocalMemoryEngine._valid_at` exactly. The window filter must run in
        Python, NOT as a lexical TEXT comparison in SQL, because ``dt_to_json`` emits
        variable-width fractional seconds (0 or 6 digits): ``'...00Z'`` sorts *after*
        ``'...00.500000Z'`` lexically even though it precedes it chronologically, so a
        SQL TEXT compare would include/exclude sub-second boundary rows differently
        from the Local oracle (a byte-parity divergence). Tenant-optional like Local:
        with a tenant the one file is queried; without one every tenant file is
        scanned. Rows return as deep-copied ``Assertion`` objects sorted by
        ``valid_from``."""
        moment = t.astimezone(UTC) if t.tzinfo else t.replace(tzinfo=UTC)

        def _valid_at(valid_from: datetime | str | None, valid_to: datetime | str | None) -> bool:
            start = parse_dt(valid_from)
            end = parse_dt(valid_to)
            if start is None:
                return False
            if start.tzinfo is None:
                start = start.replace(tzinfo=UTC)
            if end is not None and end.tzinfo is None:
                end = end.replace(tzinfo=UTC)
            return start <= moment and (end is None or moment < end)

        sql = (
            "SELECT * FROM assertions "
            "WHERE tenant_id = ? AND branch = ? AND subject = ? AND predicate = ? "
            "AND status IN ('active', 'superseded', 'contested') "
            "ORDER BY valid_from ASC"
        )
        matches: list[Assertion] = []
        with self._lock:
            if tenant_id:
                conn = self._connect(tenant_id)
                rows = conn.execute(sql, (tenant_id, branch, subject, predicate)).fetchall()
                for row in rows:
                    assertion = _assertion_from_row(row)
                    if _valid_at(assertion.valid_from, assertion.valid_to):
                        matches.append(assertion)
            else:
                for path in self._iter_tenant_db_paths():
                    conn, owned = self._borrow_conn(path)
                    try:
                        for (tid,) in conn.execute("SELECT DISTINCT tenant_id FROM assertions"):
                            rows = conn.execute(sql, (tid, branch, subject, predicate)).fetchall()
                            for row in rows:
                                assertion = _assertion_from_row(row)
                                if _valid_at(assertion.valid_from, assertion.valid_to):
                                    matches.append(assertion)
                    finally:
                        if owned:
                            conn.close()
        return sorted(matches, key=lambda item: item.valid_from)

    def set_calibration(self, calibration: CalibrationSet) -> None:
        """Store the conformal calibration set at PK(tenant_id, memory_type),
        mirroring ``LocalMemoryEngine.set_calibration`` (deepcopy semantics + the
        same audit shape). ON CONFLICT DO UPDATE preserves rowid on replacement."""
        with self._lock:
            conn = self._connect(calibration.tenant_id)
            stored = copy.deepcopy(calibration)
            with conn:
                conn.execute(
                    "INSERT INTO calibrations(tenant_id, memory_type, record) VALUES (?, ?, ?) "
                    "ON CONFLICT(tenant_id, memory_type) DO UPDATE SET record = excluded.record",
                    (stored.tenant_id, stored.memory_type, json_text(stored.to_dict())),
                )
                self._audit_row(
                    conn,
                    calibration.tenant_id,
                    "engine",
                    "set_calibration",
                    calibration.memory_type,
                    {"scores": len(calibration.scores), "target_coverage": calibration.target_coverage},
                )

    def _calibration_for(self, tenant_id: str, memory_type: str) -> CalibrationSet | None:
        """Rehydrate the stored ``CalibrationSet`` (or None), matching Local."""
        with self._lock:
            conn = self._connect(tenant_id)
            row = conn.execute(
                "SELECT record FROM calibrations WHERE tenant_id = ? AND memory_type = ?",
                (tenant_id, memory_type),
            ).fetchone()
        if row is None:
            return None
        return CalibrationSet(**json.loads(row["record"]))

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
        """Entity upsert at PK(tenant_id, canonical), byte-parity with Local.

        Runs ``LocalMemoryEngine.register_entity`` (canonical normalisation,
        alias/source-cid union, access-policy merge on repeat) over an
        entity-scope oracle, persists the resulting record (rowid preserved on
        update via ON CONFLICT DO UPDATE) plus Local's audit, and returns the
        same ``dict`` shape Local returns."""
        with self._lock:
            conn = self._connect(tenant_id)
            oracle = self._entity_oracle(conn, tenant_id)
            row = oracle.register_entity(
                tenant_id,
                canonical,
                alias=alias,
                entity_type=entity_type,
                summary=summary,
                source_evidence_cids=source_evidence_cids,
                access_policy=access_policy,
            )
            key = (tenant_id, canonical.strip() or "unknown-entity")
            record = oracle.entities[key]
            with conn:
                conn.execute(
                    "INSERT INTO entities(tenant_id, canonical, record) VALUES (?, ?, ?) "
                    "ON CONFLICT(tenant_id, canonical) DO UPDATE SET record = excluded.record",
                    (key[0], key[1], json_text(record)),
                )
                self._replay_audit(conn, oracle.audit_log)
            return row

    def deep_search(self, query: str, tenant_id: str, branch: str = "main", filt: dict[str, Any] | None = None) -> RetrievalResult:
        """Thin delegator to :meth:`retrieve` (deep=True), identical to
        ``LocalMemoryEngine.deep_search``. Full behaviour arrives with the
        ``retrieve()`` pipeline in Phase-2 Task 7; until then this raises
        ``NotImplementedError`` transitively (never as a separate stub)."""
        return self.retrieve(query=query, tenant_id=tenant_id, branch=branch, deep=True, filt=filt)

    def explain(self, query: str, tenant_id: str, branch: str = "main") -> dict[str, Any]:
        """Thin delegator to :meth:`retrieve` (deep=True) → ``to_dict()``,
        identical to ``LocalMemoryEngine.explain``. Full behaviour arrives with
        the ``retrieve()`` pipeline in Phase-2 Task 7."""
        return self.retrieve(query=query, tenant_id=tenant_id, branch=branch, deep=True).to_dict()

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
        """Append corrective evidence then upsert the corrected assertion —
        Local's exact body over the now-implemented ledger + assertion writes."""
        cid = self.append_evidence(
            Evidence(
                tenant_id=tenant_id,
                user_id=user_id,
                actor="user",
                source_type="correction",
                content=correction_text,
                trust_tier=0,
                access_policy={"tenant": tenant_id},
            ),
            branch=branch,
        )
        return self.upsert_assertion(
            Assertion(
                tenant_id=tenant_id,
                user_id=user_id,
                subject=subject,
                predicate=predicate,
                object=object_value,
                confidence=confidence,
                source_evidence_cids=[cid],
                status="active",
                trust_tier=0,
                access_policy={"tenant": tenant_id},
            ),
            branch=branch,
        )

    # --- branch / merge / discard (Task 6) -----------------------------------
    #
    # Parity strategy: one SQLite file per tenant means these ops are strictly
    # tenant-scoped (PostgresEngine-style: tenant_id REQUIRED, ValueError when
    # falsy — Local's tenant=None broadcast has no single-file analogue). The
    # branch registry is the per-file ``branches`` table T2 seeded (protected
    # ``main`` per tenant) with the composite FK evidence/assertions/relations
    # reference; the registry row is therefore written BEFORE any row-copy.
    # ``branch`` row-copies verbatim (PG-shaped: evidence keeps its cid via
    # INSERT OR IGNORE, assertions/relations get fresh uuid4 ids). ``merge`` is
    # the Local-style replay-upsert — each frm assertion is cloned onto ``into``
    # and pushed through this engine's OWN :meth:`upsert_assertion` (so the
    # supersede/contest resolution runs), counting added-vs-merged by the
    # (tenant, into) row-count delta; evidence/relations copy with dedup.
    # ``discard`` deletes the branch-scoped rows (child rows BEFORE the registry
    # row — foreign_keys=ON), then prunes justifications/contradictions that
    # referenced now-orphaned assertion ids, mirroring Local's discard body.

    @property
    def branches(self) -> dict[str, dict[str, Any]]:
        """Dict-shaped branch registry aggregated across every tenant file
        (``PromotionGate._reset_branch`` requirement, R3). Shape mirrors
        ``LocalMemoryEngine.branches``: ``{name: {"from", "kind", "created_at"}}``.
        A ``PromotionGate`` binds to one engine and mints per-candidate branch
        names, so single-tenant gate usage sees exactly that tenant's registry."""
        result: dict[str, dict[str, Any]] = {}
        with self._lock:
            for path in self._iter_tenant_db_paths():
                conn, owned = self._borrow_conn(path)
                try:
                    for row in conn.execute(
                        "SELECT name, from_branch, kind, created_at FROM branches ORDER BY rowid"
                    ):
                        result[row["name"]] = {
                            "from": row["from_branch"],
                            "kind": row["kind"],
                            "created_at": row["created_at"],
                        }
                finally:
                    if owned:
                        conn.close()
        return result

    @staticmethod
    def _count_assertions(conn: sqlite3.Connection, tenant_id: str, branch: str) -> int:
        return conn.execute(
            "SELECT COUNT(*) FROM assertions WHERE tenant_id = ? AND branch = ?",
            (tenant_id, branch),
        ).fetchone()[0]

    def branch(self, name: str, frm: str = "main", kind: str = "scratch", tenant_id: str | None = None) -> None:
        """Row-copy branch, tenant-scoped (PG-shaped).

        Registry row FIRST (composite FK), then copy evidence (cid kept, INSERT
        OR IGNORE), assertions and relations (fresh uuid4 ids, PG-style) from
        ``frm`` onto ``name`` — copies include the packed embedding BLOB,
        ``embedding_partition`` (inside evidence metadata), ``last_accessed`` and
        ``access_count``. No-op when ``name == frm`` or the branch already exists
        (idempotent, matching PG's ON CONFLICT..RETURNING skip). ``frm`` must
        exist (``ValueError('unknown branch: ...')``)."""
        if not tenant_id:
            raise ValueError("SqliteEngine.branch requires tenant_id")
        if name == frm:
            return
        with self._lock:
            conn = self._connect(tenant_id)
            self._require_branch(conn, tenant_id, frm)
            if conn.execute(
                "SELECT 1 FROM branches WHERE tenant_id = ? AND name = ?", (tenant_id, name)
            ).fetchone() is not None:
                return
            with conn:
                conn.execute(
                    "INSERT INTO branches(tenant_id, name, from_branch, kind, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (tenant_id, name, frm, kind, dt_to_json(utc_now())),
                )
                for row in conn.execute(
                    "SELECT * FROM evidence WHERE tenant_id = ? AND branch = ? ORDER BY rowid",
                    (tenant_id, frm),
                ).fetchall():
                    ev = _evidence_from_row(row)
                    ev.branch = name
                    conn.execute(_EVIDENCE_INSERT_OR_IGNORE, _evidence_insert_values(ev))
                for row in conn.execute(
                    "SELECT * FROM assertions WHERE tenant_id = ? AND branch = ? ORDER BY rowid",
                    (tenant_id, frm),
                ).fetchall():
                    assertion = _assertion_from_row(row)
                    assertion.branch = name
                    assertion.id = new_id()
                    self._insert_assertion_row(conn, assertion)
                for row in conn.execute(
                    "SELECT * FROM relations WHERE tenant_id = ? AND branch = ? ORDER BY rowid",
                    (tenant_id, frm),
                ).fetchall():
                    rel = _relation_from_row(row)
                    rel.branch = name
                    rel.id = new_id()
                    conn.execute(_RELATION_INSERT, _relation_insert_values(rel))
                self._audit_row(conn, tenant_id, "engine", "branch", name, {"from": frm, "kind": kind})

    def merge(self, frm: str, into: str = "main", tenant_id: str | None = None) -> MergeReport:
        """Local-style replay-upsert merge, tenant-scoped.

        Evidence: non-erased ``frm`` rows copied onto ``into`` with cid-dedup
        (``evidence_added`` counts genuinely new rows; erased rows skipped,
        matching Local not PG). Assertions: each ``frm`` assertion is cloned onto
        ``into`` and pushed through this engine's OWN :meth:`upsert_assertion`
        (supersede/contest runs) — ``assertions_added`` when the (tenant, into)
        row count grows, else ``assertions_merged`` (the reinforce path).
        Relations: overlapping semantic peers reinforce provenance, confidence,
        validity, and restrictive access policy; disjoint windows stay distinct.
        Returns ``MergeReport(frm, into, evidence_added, assertions_added,
        assertions_merged, relations_added, conflicts=[])``
        constructed POSITIONALLY (R1 field order); ``conflicts`` is always ``[]``.
        The report is appended to ``merge_log`` and audited (op ``merge``,
        target ``frm``) so ``export_tenant`` reconstructs the merge_log."""
        if not tenant_id:
            raise ValueError("SqliteEngine.merge requires tenant_id")
        with self._lock:
            conn = self._connect(tenant_id)
            self._require_branch(conn, tenant_id, frm)
            self._require_branch(conn, tenant_id, into)
            report = MergeReport(frm, into, 0, 0, 0, 0, [])
            ev_rows = conn.execute(
                "SELECT * FROM evidence WHERE tenant_id = ? AND branch = ? AND erased = 0 ORDER BY rowid",
                (tenant_id, frm),
            ).fetchall()
            with conn:
                for row in ev_rows:
                    ev = _evidence_from_row(row)
                    if not ev.cid:
                        continue
                    present = conn.execute(
                        "SELECT 1 FROM evidence WHERE tenant_id = ? AND branch = ? AND cid = ?",
                        (tenant_id, into, ev.cid),
                    ).fetchone()
                    if present is None:
                        ev.branch = into
                        self._insert_evidence_row(conn, ev)
                        report.evidence_added += 1
            # Replay-upsert OUTSIDE any open transaction — upsert_assertion opens
            # (and commits) its own per-call transaction on the same connection.
            a_rows = conn.execute(
                "SELECT * FROM assertions WHERE tenant_id = ? AND branch = ? ORDER BY rowid",
                (tenant_id, frm),
            ).fetchall()
            for row in a_rows:
                cloned = copy.deepcopy(_assertion_from_row(row))
                cloned.branch = into
                before = self._count_assertions(conn, tenant_id, into)
                self.upsert_assertion(cloned, branch=into)
                after = self._count_assertions(conn, tenant_id, into)
                if after > before:
                    report.assertions_added += 1
                else:
                    report.assertions_merged += 1
            rel_rows = conn.execute(
                "SELECT * FROM relations WHERE tenant_id = ? AND branch = ? ORDER BY rowid",
                (tenant_id, frm),
            ).fetchall()
            with conn:
                for row in rel_rows:
                    rel = _relation_from_row(row)
                    peers = [
                        _relation_from_row(item)
                        for item in conn.execute(
                            "SELECT * FROM relations WHERE tenant_id = ? AND branch = ? "
                            "AND source = ? AND predicate = ? AND target = ? "
                            "ORDER BY valid_from, id",
                            (tenant_id, into, rel.source, rel.predicate, rel.target),
                        ).fetchall()
                    ]
                    overlapping = [
                        item for item in peers if _relation_windows_overlap(item, rel)
                    ]
                    if overlapping:
                        _merge_relation_state(overlapping[0], rel)
                        conn.execute(
                            _RELATION_UPSERT,
                            _relation_insert_values(overlapping[0]),
                        )
                        continue
                    rel.branch = into
                    id_exists = conn.execute(
                        "SELECT 1 FROM relations WHERE tenant_id = ? AND branch = ? AND id = ?",
                        (tenant_id, into, rel.id),
                    ).fetchone()
                    if id_exists is not None:
                        rel.id = new_id()
                    conn.execute(_RELATION_INSERT, _relation_insert_values(rel))
                    report.relations_added += 1
                conn.execute(
                    "INSERT INTO merge_log(tenant_id, record) VALUES (?, ?)",
                    (tenant_id, json_text(report.to_dict())),
                )
                self._audit_row(conn, tenant_id, "engine", "merge", frm, report.to_dict())
            return report

    def discard(self, branch: str, tenant_id: str | None = None) -> None:
        """Delete a branch and its rows, tenant-scoped.

        Guards ``main`` (``ValueError``). Deletes relations → assertions →
        evidence (child rows before the registry row, since foreign_keys=ON),
        then prunes justifications whose ``assertion_id``/``dependency_ids`` and
        contradictions whose ``a``/``b`` reference assertion ids orphaned by the
        discard (present on no surviving branch), mirroring Local's discard body,
        then deletes the branch registry row and audits."""
        if branch == "main":
            raise ValueError("main branch cannot be discarded")
        if not tenant_id:
            raise ValueError("SqliteEngine.discard requires tenant_id")
        with self._lock:
            conn = self._connect(tenant_id)
            self._require_branch(conn, tenant_id, branch)
            with conn:
                discarded_ids = {
                    row[0]
                    for row in conn.execute(
                        "SELECT id FROM assertions WHERE tenant_id = ? AND branch = ?",
                        (tenant_id, branch),
                    )
                }
                conn.execute("DELETE FROM relations WHERE tenant_id = ? AND branch = ?", (tenant_id, branch))
                conn.execute("DELETE FROM assertions WHERE tenant_id = ? AND branch = ?", (tenant_id, branch))
                conn.execute("DELETE FROM evidence WHERE tenant_id = ? AND branch = ?", (tenant_id, branch))
                if discarded_ids:
                    surviving = {
                        row[0]
                        for row in conn.execute(
                            "SELECT id FROM assertions WHERE tenant_id = ?", (tenant_id,)
                        )
                    }
                    orphaned = discarded_ids - surviving
                    if orphaned:
                        self._prune_dangling(conn, tenant_id, orphaned)
                conn.execute("DELETE FROM branches WHERE tenant_id = ? AND name = ?", (tenant_id, branch))
                self._audit_row(conn, tenant_id, "engine", "discard", branch, {})

    @staticmethod
    def _prune_dangling(conn: sqlite3.Connection, tenant_id: str, orphaned: set[str]) -> None:
        """Prune justifications/contradictions that reference orphaned assertion
        ids (Local discard parity: justification kept iff its assertion_id and
        every dependency_id survive; contradiction kept iff both a and b survive)."""
        for row in conn.execute(
            "SELECT id, record FROM justifications WHERE tenant_id = ?", (tenant_id,)
        ).fetchall():
            record = json.loads(row["record"])
            dependency_ids = set(record.get("dependency_ids") or [])
            if record.get("assertion_id") in orphaned or (dependency_ids & orphaned):
                conn.execute("DELETE FROM justifications WHERE id = ?", (row["id"],))
        for row in conn.execute(
            "SELECT id, record FROM contradictions WHERE tenant_id = ?", (tenant_id,)
        ).fetchall():
            record = json.loads(row["record"])
            if record.get("a") in orphaned or record.get("b") in orphaned:
                conn.execute("DELETE FROM contradictions WHERE id = ?", (row["id"],))

    # --- retrieve() via the shared pipeline (Task 7) -------------------------
    #
    # SqliteEngine satisfies ``pipeline.RetrievalPipelineOps`` so ``retrieve()``
    # is a thin delegation to the SAME ``run_retrieval_pipeline`` orchestrator
    # LocalMemoryEngine and PostgresEngine use (spec §4.0 — no third copy). The
    # channel searches push their candidate filter into SQL (see ``_scan_oracle``
    # / ``graph_ppr``). Every PURE pipeline helper is reused VERBATIM from
    # LocalMemoryEngine (class-attribute aliases below — the spec forbids a third
    # copy of pure pipeline logic); the store-touching helpers run Local's ACTUAL
    # bodies over a hits-scoped oracle (O(hits)) for byte-parity.
    #
    # ``_record_retrieval_access`` is a SYNCHRONOUS write-on-read, matching the
    # shipped Local/Postgres engines (test_shared_engine_contract asserts
    # read_marks["assertions"] >= 1 synchronously); the spec's async-telemetry
    # optimization is DEFERRED here — shipped-behaviour parity wins (ledger).
    retrieval_explain_channel_keys: tuple[str, str, str] = ("dense_hash", "lexical", "graph_ppr")

    # Pure pipeline helpers reused VERBATIM from LocalMemoryEngine (same code,
    # not a re-implementation): _rrf/_calibration_explain are plain methods whose
    # only ``self`` access is ``self.policy`` (present on SqliteEngine) / none;
    # the rest are staticmethods.
    _rrf = LocalMemoryEngine._rrf
    _calibration_explain = LocalMemoryEngine._calibration_explain
    _u_curve_order = staticmethod(LocalMemoryEngine._u_curve_order)
    _fit_budget = staticmethod(LocalMemoryEngine._fit_budget)
    _confidence = staticmethod(LocalMemoryEngine._confidence)
    _prediction_set_size = staticmethod(LocalMemoryEngine._prediction_set_size)
    _mark_retrieved_text_as_data = staticmethod(LocalMemoryEngine._mark_retrieved_text_as_data)
    _merge_schema_fast_path_reports = staticmethod(LocalMemoryEngine._merge_schema_fast_path_reports)

    def _hits_oracle(self, hits: list[Hit]) -> LocalMemoryEngine:
        """Hydrate a minimal oracle with ONLY the evidence rows the given hits
        reference (each hit's own cid when it is evidence, plus its provenance
        and metadata ``source_evidence_cids``) — the exact rows Local's
        ``_embedding_for_hit`` / ``_independent_corroboration_report`` read for
        these hits. O(hits), never O(tenant-rows). Fetched by cid WITHOUT the
        trust/erased prefilter (corroboration inspects erased/low-trust sources
        too), so the store-touching pipeline helpers delegate to Local's ACTUAL
        bodies with byte-identical inputs."""
        oracle = LocalMemoryEngine(policy=self.policy, adapters=self.adapters)
        wanted: dict[str, dict[str, set[str]]] = {}
        for hit in hits:
            cids: set[str] = set()
            if hit.kind == "evidence" and hit.id:
                cids.add(str(hit.id))
            for cid in hit.provenance:
                if cid:
                    cids.add(str(cid))
            raw = hit.metadata.get("source_evidence_cids") if isinstance(hit.metadata, dict) else None
            if isinstance(raw, list | tuple):
                cids.update(str(c) for c in raw if c)
            elif isinstance(raw, str) and raw:
                cids.add(raw)
            if cids and hit.tenant_id:
                wanted.setdefault(hit.tenant_id, {}).setdefault(hit.branch, set()).update(cids)
        for tenant_id, branches in wanted.items():
            conn = self._connect(tenant_id)
            with self._lock:
                for branch, cids in branches.items():
                    for cid in sorted(cids):
                        row = conn.execute(
                            "SELECT * FROM evidence WHERE tenant_id = ? AND branch = ? AND cid = ?",
                            (tenant_id, branch, cid),
                        ).fetchone()
                        if row is not None:
                            ev = _evidence_from_row(row)
                            oracle.evidence[oracle._evidence_key(ev.tenant_id, ev.branch, ev.cid or "")] = ev
        return oracle

    def _mmr(self, query: str, hits: list[Hit], k: int) -> list[Hit]:
        """Security-gated MMR (spec §4.0): Local's ACTUAL ``_mmr`` over a hits-
        scoped oracle so the embedding sourcing (``_embedding_for_hit``,
        stored-embedding gating + metadata side-effects) is byte-identical."""
        return LocalMemoryEngine._mmr(self._hits_oracle(hits), query, hits, k)

    def _apply_standing_scores(self, hits: list[Hit]) -> list[Hit]:
        """Standing re-rank (spec §4.1): Local's ACTUAL body over a hits-scoped
        oracle (independent-corroboration reads only referenced evidence),
        byte-identical to Local."""
        return LocalMemoryEngine._apply_standing_scores(self._hits_oracle(hits), hits)

    def _reality_monitoring_report(self, hits: list[Hit]) -> dict[str, Any]:
        """Reality-monitoring + standing abstention report: Local's ACTUAL body
        over a hits-scoped oracle, byte-identical to Local."""
        return LocalMemoryEngine._reality_monitoring_report(self._hits_oracle(hits), hits)

    def _record_retrieval_access(self, hits: list[Hit]) -> dict[str, int]:
        """SYNCHRONOUS write-on-read, byte-parity with
        ``LocalMemoryEngine._record_retrieval_access`` (the async-telemetry
        optimization is DEFERRED — shipped-engine parity wins). Run Local's
        ACTUAL body over an oracle hydrated with ONLY the assertions and evidence
        the hits reference (O(hits), not O(tenant-rows)), then persist the touched
        assertion lifecycle fields + evidence lifecycle metadata back to SQLite
        and return Local's counts verbatim."""
        if not hits:
            return {"assertions": 0, "evidence": 0}
        oracle = LocalMemoryEngine(policy=self.policy, adapters=self.adapters)
        # 1. assertions referenced by assertion hits, keyed EXACTLY as Local keys
        #    them so oracle.assertions.get(_branch_key(...)) resolves.
        assertion_refs: dict[str, set[tuple[str, str]]] = {}
        for hit in hits:
            if hit.kind == "assertion" and hit.id:
                assertion_refs.setdefault(hit.tenant_id, set()).add((hit.branch, hit.id))
        for tenant_id, refs in assertion_refs.items():
            conn = self._connect(tenant_id)
            with self._lock:
                for branch, aid in refs:
                    row = conn.execute(
                        "SELECT * FROM assertions WHERE tenant_id = ? AND branch = ? AND id = ?",
                        (tenant_id, branch, aid),
                    ).fetchone()
                    if row is not None:
                        a = _assertion_from_row(row)
                        oracle.assertions[oracle._branch_key(a.tenant_id, a.branch, a.id)] = a
        # 2. evidence refs from hits + hydrated assertions' source cids.
        ev_refs: dict[str, set[tuple[str, str]]] = {}

        def _want(tenant: str, branch: str, cid: Any) -> None:
            if tenant and cid:
                ev_refs.setdefault(tenant, set()).add((branch, str(cid)))

        for hit in hits:
            if hit.kind == "evidence" and hit.id:
                _want(hit.tenant_id, hit.branch, hit.id)
            for cid in hit.provenance:
                _want(hit.tenant_id, hit.branch, cid)
        for a in oracle.assertions.values():
            for cid in a.source_evidence_cids:
                _want(a.tenant_id, a.branch, cid)
        for tenant_id, refs in ev_refs.items():
            conn = self._connect(tenant_id)
            with self._lock:
                for branch, cid in refs:
                    row = conn.execute(
                        "SELECT * FROM evidence WHERE tenant_id = ? AND branch = ? AND cid = ?",
                        (tenant_id, branch, cid),
                    ).fetchone()
                    if row is not None:
                        ev = _evidence_from_row(row)
                        oracle.evidence[oracle._evidence_key(ev.tenant_id, ev.branch, ev.cid or "")] = ev
        # 3. Local's exact body mutates the oracle dicts in place (its _persist is
        #    a no-op with no store_path); snapshot for the write-back delta.
        a_before = {key: item.to_dict() for key, item in oracle.assertions.items()}
        ev_before = {key: item.to_dict() for key, item in oracle.evidence.items()}
        result = LocalMemoryEngine._record_retrieval_access(oracle, hits)
        # 4. persist only the genuinely-changed rows, per tenant, in one txn each.
        for tenant_id in {*assertion_refs, *ev_refs}:
            conn = self._connect(tenant_id)
            with self._lock, conn:
                for key, item in oracle.assertions.items():
                    if item.tenant_id == tenant_id and item.to_dict() != a_before.get(key):
                        self._update_assertion_row(conn, item)
                for key, item in oracle.evidence.items():
                    if item.tenant_id == tenant_id and item.to_dict() != ev_before.get(key):
                        self._write_evidence_mutable(conn, item)
        return result

    def retrieve(
        self,
        query: str,
        tenant_id: str,
        branch: str = "main",
        deep: bool = False,
        filt: dict[str, Any] | None = None,
        *,
        record_access: bool = True,
    ) -> RetrievalResult:
        """Delegate to the engine-agnostic shared pipeline exactly as
        ``LocalMemoryEngine.retrieve`` does (spec §4.0). SqliteEngine implements
        ``RetrievalPipelineOps`` via the SQL-pushdown channel searches + the ops
        members above; the workspace strip, activation, u-curve, budget,
        calibration/abstention and explain assembly all live in the shared
        orchestrator."""
        return run_retrieval_pipeline(
            self,
            query=query,
            tenant_id=tenant_id,
            branch=branch,
            deep=deep,
            filt=filt,
            policy=self.policy,
            record_access=record_access,
        )

    def forget(
        self,
        tenant_id: str,
        cid: str,
        branch: str = "main",
        requested_by: str = "user",
        erasure_mode: ErasureMode | str = ErasureMode.TOMBSTONE_RECOMPUTE,
    ) -> dict[str, Any]:
        """Erase evidence + cascade, byte-parity with ``LocalMemoryEngine.forget``.

        A direct SQL port of ``PostgresEngine.forget`` (the derived-evidence plan is
        the shared engine-independent ``postgres_engine._derived_evidence_forget_plan``
        — imported here, ``legal_blind=True`` on a legal shred):

        * ``tombstone_recompute`` — ``UPDATE evidence SET content='', erased=1`` on the
          target + its derived footprint (every other column, incl. the cid, is kept;
          the erased row IS the replay blocklist ``append_evidence`` probes).
        * ``hard_delete_legal`` — ``DELETE`` those rows outright.

        Cascade asymmetry mirrors Local exactly: assertions/relations are
        branch-scoped, preferences/entities tenant-scoped. An operator (non-``legal``)
        hard delete is refused (``min_corroboration_for_delete``) when it would strand
        an active assertion below the corroboration floor. Erasure propagation:
        the embedding cache is purged for every affected cid (both modes, privacy
        class 13), the branch's cached-PPR rows are dropped (targeted invalidation —
        ``evidence_fts`` self-syncs via its UPDATE/DELETE triggers; the relations
        watermark self-invalidates the rest), the deletion_log records an HMAC id for
        hard deletes (spec §7 invariant 13; the cid is kept for tombstones), and the
        CID journal is tombstoned/purged per affected cid AFTER commit so a
        journal-rebuild stays byte-equivalent to a ledger-rebuild.

        BRANCH SCOPE (Local-match, ledgered): Local/Postgres both scope the
        evidence/assertion/relation cascade to the single ``branch`` argument (the
        spec §4.2 ideal is erase-across-all-branches). This port MATCHES the shipped
        oracle rather than diverging; the spec>shipped gap is recorded in the Task-9
        report."""
        mode = ErasureMode(erasure_mode)
        from mnemosyne.postgres_engine import (
            _bytes_to_cid,
            _cid_to_bytes,
            _derived_evidence_forget_plan,
        )

        propagated: dict[str, Any] = {
            "retracted_assertions": [],
            "trimmed_assertions": [],
            "retracted_preferences": [],
            "trimmed_preferences": [],
            "expired_relations": [],
            "trimmed_relations": [],
            "removed_entities": [],
            "trimmed_entities": [],
            "erased_derived_evidence": [],
            "retained_derived_evidence": [],
            "trimmed_derived_evidence": [],
        }
        with self._lock:
            conn = self._connect(tenant_id)
            with conn:
                target = conn.execute(
                    "SELECT cid, source_type, trust_tier, capability_tags, metadata, user_id "
                    "FROM evidence WHERE tenant_id = ? AND branch = ? AND cid = ?",
                    (tenant_id, branch, cid),
                ).fetchone()
                if target is None:
                    return {"erased": False, "reason": "evidence_not_found", "cid": cid, "erasure_mode": mode.value}
                candidate_rows = conn.execute(
                    "SELECT cid, metadata, source_type FROM evidence "
                    "WHERE tenant_id = ? AND branch = ? AND erased = 0 AND cid <> ? ORDER BY rowid",
                    (tenant_id, branch, cid),
                ).fetchall()
                candidates = [
                    (_cid_to_bytes(row["cid"]), json.loads(row["metadata"] or "{}")) for row in candidate_rows
                ]
                cascade_metadata: dict[str, dict[str, Any]] = {
                    cid: {**json.loads(target["metadata"] or "{}"), "source_type": target["source_type"]}
                }
                for row in candidate_rows:
                    cascade_metadata[row["cid"]] = {
                        **json.loads(row["metadata"] or "{}"),
                        "source_type": row["source_type"] or "",
                    }
                legal_blind = mode is ErasureMode.HARD_DELETE_LEGAL and requested_by == "legal"
                if legal_blind:
                    _derived_bytes, derived_cids, retained_metadata = _derived_evidence_forget_plan(
                        cid, candidates, legal_blind=True
                    )
                else:
                    _derived_bytes, derived_cids, retained_metadata = _derived_evidence_forget_plan(cid, candidates)
                affected_cids = {cid, *derived_cids}
                propagated["erased_derived_evidence"] = derived_cids
                propagated["retained_derived_evidence"] = sorted(_bytes_to_cid(item) for item in retained_metadata)
                propagated["trimmed_derived_evidence"] = list(propagated["retained_derived_evidence"])
                retained_cascade_metadata = {
                    _bytes_to_cid(retained_bytes): {
                        **dict(metadata),
                        "source_type": cascade_metadata.get(_bytes_to_cid(retained_bytes), {}).get("source_type", ""),
                    }
                    for retained_bytes, metadata in retained_metadata.items()
                }
                propagated["standing_cascade"] = standing_erasure_cascade_report(
                    source_cid=cid,
                    erasure_mode=mode.value,
                    affected_cids=affected_cids | set(propagated["retained_derived_evidence"]),
                    erased_derived_cids=derived_cids,
                    retained_metadata_by_cid=retained_cascade_metadata,
                    metadata_by_cid=cascade_metadata,
                )
                if mode is ErasureMode.HARD_DELETE_LEGAL and requested_by != "legal":
                    minimum = self.policy.min_corroboration_for_delete
                    blocking: list[str] = []
                    for row in conn.execute(
                        "SELECT id, source_evidence_cids FROM assertions "
                        "WHERE tenant_id = ? AND branch = ? AND status = 'active' ORDER BY rowid",
                        (tenant_id, branch),
                    ).fetchall():
                        sources = set(json.loads(row["source_evidence_cids"] or "[]"))
                        if sources and sources <= affected_cids and len(sources) < minimum:
                            blocking.append(row["id"])
                    if blocking:
                        return {
                            "erased": False,
                            "reason": "min_corroboration_for_delete",
                            "cid": cid,
                            "erasure_mode": mode.value,
                            "min_corroboration_for_delete": minimum,
                            "blocking_assertions": blocking,
                        }
                affected_order = [cid, *derived_cids]
                # Capture original content/user before erasing (needed for the
                # tombstone journal salted-hash — the UPDATE nulls content).
                originals: dict[str, tuple[str, str]] = {}
                if affected_order:
                    placeholders = ",".join("?" for _ in affected_order)
                    for row in conn.execute(
                        f"SELECT cid, content, user_id FROM evidence "
                        f"WHERE tenant_id = ? AND branch = ? AND cid IN ({placeholders})",
                        (tenant_id, branch, *affected_order),
                    ).fetchall():
                        originals[row["cid"]] = (row["content"] or "", row["user_id"] or "")
                if mode is ErasureMode.HARD_DELETE_LEGAL:
                    for affected_cid in affected_order:
                        conn.execute(
                            "DELETE FROM evidence WHERE tenant_id = ? AND branch = ? AND cid = ?",
                            (tenant_id, branch, affected_cid),
                        )
                else:
                    for affected_cid in affected_order:
                        conn.execute(
                            "UPDATE evidence SET content = '', erased = 1 "
                            "WHERE tenant_id = ? AND branch = ? AND cid = ?",
                            (tenant_id, branch, affected_cid),
                        )
                for retained_bytes, metadata in retained_metadata.items():
                    conn.execute(
                        "UPDATE evidence SET metadata = ? WHERE tenant_id = ? AND branch = ? AND cid = ?",
                        (json_text(metadata), tenant_id, branch, _bytes_to_cid(retained_bytes)),
                    )
                # Assertions (branch-scoped): trim surviving sources or retract.
                for row in conn.execute(
                    "SELECT id, source_evidence_cids FROM assertions "
                    "WHERE tenant_id = ? AND branch = ? ORDER BY rowid",
                    (tenant_id, branch),
                ).fetchall():
                    sources = json.loads(row["source_evidence_cids"] or "[]")
                    if not affected_cids.intersection(sources):
                        continue
                    surviving = [item for item in sources if item not in affected_cids]
                    if surviving:
                        conn.execute(
                            "UPDATE assertions SET source_evidence_cids = ? "
                            "WHERE tenant_id = ? AND branch = ? AND id = ?",
                            (json_text(surviving), tenant_id, branch, row["id"]),
                        )
                        propagated["trimmed_assertions"].append(row["id"])
                    else:
                        conn.execute(
                            "UPDATE assertions SET status = 'retracted', expired_at = ?, source_evidence_cids = ? "
                            "WHERE tenant_id = ? AND branch = ? AND id = ?",
                            (dt_to_json(utc_now()), json_text([]), tenant_id, branch, row["id"]),
                        )
                        propagated["retracted_assertions"].append(row["id"])
                # Preferences (tenant-scoped): rehydrate to keep the record byte-shape.
                for row in conn.execute(
                    "SELECT id, record FROM preferences WHERE tenant_id = ? ORDER BY rowid",
                    (tenant_id,),
                ).fetchall():
                    pref = Preference.from_dict(json.loads(row["record"]))
                    sources = list(pref.source_evidence_cids)
                    if not affected_cids.intersection(sources):
                        continue
                    surviving = [item for item in sources if item not in affected_cids]
                    if surviving:
                        pref.source_evidence_cids = surviving
                        propagated["trimmed_preferences"].append(pref.id)
                    else:
                        pref.status = "retracted"
                        pref.valid_to = utc_now()
                        pref.source_evidence_cids = []
                        propagated["retracted_preferences"].append(pref.id)
                    conn.execute(
                        "UPDATE preferences SET record = ? WHERE id = ?",
                        (json_text(pref.to_dict()), pref.id),
                    )
                # Relations (branch-scoped).
                for row in conn.execute(
                    "SELECT id, source_evidence_cids FROM relations "
                    "WHERE tenant_id = ? AND branch = ? ORDER BY rowid",
                    (tenant_id, branch),
                ).fetchall():
                    sources = json.loads(row["source_evidence_cids"] or "[]")
                    if not affected_cids.intersection(sources):
                        continue
                    surviving = [item for item in sources if item not in affected_cids]
                    if surviving:
                        conn.execute(
                            "UPDATE relations SET source_evidence_cids = ? "
                            "WHERE tenant_id = ? AND branch = ? AND id = ?",
                            (json_text(surviving), tenant_id, branch, row["id"]),
                        )
                        propagated["trimmed_relations"].append(row["id"])
                    else:
                        conn.execute(
                            "UPDATE relations SET valid_to = ?, source_evidence_cids = ? "
                            "WHERE tenant_id = ? AND branch = ? AND id = ?",
                            (dt_to_json(utc_now()), json_text([]), tenant_id, branch, row["id"]),
                        )
                        propagated["expired_relations"].append(row["id"])
                # Entities (tenant-scoped, plain dict record).
                for row in conn.execute(
                    "SELECT canonical, record FROM entities WHERE tenant_id = ? ORDER BY rowid",
                    (tenant_id,),
                ).fetchall():
                    record = json.loads(row["record"])
                    sources = list(record.get("source_evidence_cids") or [])
                    if not sources or not affected_cids.intersection(sources):
                        continue
                    surviving = [item for item in sources if item not in affected_cids]
                    if surviving:
                        record["source_evidence_cids"] = surviving
                        record["updated_at"] = utc_now().isoformat()
                        conn.execute(
                            "UPDATE entities SET record = ? WHERE tenant_id = ? AND canonical = ?",
                            (json_text(record), tenant_id, row["canonical"]),
                        )
                        propagated["trimmed_entities"].append(record["canonical"])
                    else:
                        conn.execute(
                            "DELETE FROM entities WHERE tenant_id = ? AND canonical = ?",
                            (tenant_id, row["canonical"]),
                        )
                        propagated["removed_entities"].append(record["canonical"])
                # deletion_log — spec §7 invariant 13: NO retained record for a hard
                # delete may carry the erased cid (deletion evidence_cid, the
                # provenance/standing-cascade refs inside `propagated`, or the audit
                # target_id). Redact every retained copy with one per-erasure
                # placeholder map (stable within the record, non-recomputable); the
                # dict RETURNED to the caller keeps the real cids. A tombstone keeps
                # the cid (the row still exists as the replay blocklist).
                if mode is ErasureMode.HARD_DELETE_LEGAL:
                    placeholder_map = build_erasure_placeholder_map({cid, *derived_cids}, tenant_id)
                    stored_propagated = redact_erased_cids(propagated, placeholder_map)
                    deletion_record_cid = erasure_deletion_record_id(cid, tenant_id, target["user_id"] or "")
                    audit_target_id = placeholder_map[cid]
                else:
                    stored_propagated = propagated
                    deletion_record_cid = cid
                    audit_target_id = cid
                entry = {
                    "id": new_id(),
                    "tenant_id": tenant_id,
                    "evidence_cid": deletion_record_cid,
                    "requested_by": requested_by,
                    "erasure_mode": mode.value,
                    "propagated": stored_propagated,
                    "at": utc_now().isoformat(),
                }
                conn.execute(
                    "INSERT INTO deletion_log(tenant_id, record) VALUES (?, ?)",
                    (tenant_id, json_text(entry)),
                )
                self._audit_row(
                    conn,
                    tenant_id,
                    requested_by,
                    "forget",
                    audit_target_id,
                    {**stored_propagated, "erasure_mode": mode.value, "source_type": target["source_type"]},
                    source=target["source_type"],
                    trust_tier=target["trust_tier"],
                    capability_tags=json.loads(target["capability_tags"] or "[]"),
                )
                # Erasure propagation (both modes): purge every affected cid's cached
                # vector, then drop this branch's cached-PPR payloads (targeted — no
                # full projection rebuild; the relations watermark handles the rest).
                for affected_cid in affected_order:
                    self._purge_embedding_cache_row(conn, tenant_id, affected_cid)
                conn.execute(
                    "DELETE FROM graph_ppr_cache WHERE tenant_id = ? AND branch = ?",
                    (tenant_id, branch),
                )
            # Journal AFTER commit (append-parity): tombstone keeps a salted-hash
            # marker per affected cid; a hard delete purges the lines outright.
            if self._journal_dir is not None:
                journal = CIDJournal(self._journal_dir / journal_filename(tenant_id))
                erased_at = utc_now().isoformat()
                for affected_cid in affected_order:
                    if mode is ErasureMode.HARD_DELETE_LEGAL:
                        journal.purge(affected_cid)
                    else:
                        original_content, original_user = originals.get(affected_cid, ("", ""))
                        journal.tombstone(
                            affected_cid,
                            salted_hash=erasure_tombstone_hash(original_content, tenant_id, original_user),
                            erased_at=erased_at,
                        )
        # Erasure / deletion-propagation signal (§3): an erasure produces a
        # traceable propagation log — the deletion_log entry plus the crypto-shred
        # / transitive-invalidation steps across derived projections. Surface the
        # cache-purge and journal (compaction/tombstone) step counts so a purge is
        # observable live, distinct from the returned `propagated` cascade dict
        # (which stays byte-parity with Local/Postgres — no new keys added there).
        self.metrics.increment("sqlite.erasure.propagations")
        self.metrics.observe("sqlite.erasure.propagation.cache_purges", float(len(affected_order)))
        journal_steps = float(len(affected_order)) if self._journal_dir is not None else 0.0
        self.metrics.observe("sqlite.erasure.propagation.journal_steps", journal_steps)
        return {"erased": True, "cid": cid, "erasure_mode": mode.value, "propagated": propagated}
