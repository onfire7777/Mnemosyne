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
``scan surfaces`` block). The remaining ``MemoryEngine`` Protocol methods stay
``NotImplementedError`` stubs naming their Phase-2 task, so
``isinstance(engine, MemoryEngine)`` already holds — the runtime_checkable
Protocol checks method presence.
"""
from __future__ import annotations

import array
import copy
import json
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from mnemosyne import text as text_kernels
from mnemosyne.access_policy import (
    VECTOR_PARTITION_PUBLIC,
    filter_export_for_context,
    may_embed_item,
    may_read_item,
    may_use_stored_embedding,
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
    validate_adapter_hit_scope,
)
from mnemosyne.sqlite_schema import (
    ENSURE_STATEMENTS,
    PRAGMA_STATEMENTS,
    SCHEMA_VERSION,
    json_text,
    pack_embedding,
    unpack_embedding,
)
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

    def _scan_oracle(
        self, filt: dict[str, Any], *, with_blobs: bool = False
    ) -> LocalMemoryEngine | tuple[LocalMemoryEngine, dict[str, bytes | None]]:
        """Hydrate a candidate-scope oracle: evidence + assertions for
        (tenant, branch) and preferences for the tenant. ``with_blobs`` also
        returns the raw packed-embedding BLOBs keyed by evidence key, so the
        dense seam can feed them to ``dense_scan_packed`` with zero conversion."""
        tenant_id = filt.get("tenant_id")
        branch = str(filt.get("branch", "main"))
        oracle = LocalMemoryEngine(policy=self.policy, adapters=self.adapters)
        raw_blobs: dict[str, bytes | None] = {}
        if tenant_id:
            conn = self._connect(tenant_id)
            with self._lock:
                # ORDER BY rowid == insertion order, matching LocalMemoryEngine's
                # dict-values iteration order (a bare WHERE would use the PK
                # index and return cid/id order, breaking equal-score tie parity).
                ev_rows = conn.execute(
                    "SELECT * FROM evidence WHERE tenant_id = ? AND branch = ? ORDER BY rowid",
                    (tenant_id, branch),
                ).fetchall()
                a_rows = conn.execute(
                    "SELECT * FROM assertions WHERE tenant_id = ? AND branch = ? ORDER BY rowid",
                    (tenant_id, branch),
                ).fetchall()
                p_rows = conn.execute(
                    "SELECT record FROM preferences WHERE tenant_id = ? ORDER BY rowid",
                    (tenant_id,),
                ).fetchall()
            for row in ev_rows:
                ev = _evidence_from_row(row)
                key = oracle._evidence_key(ev.tenant_id, ev.branch, ev.cid or "")
                oracle.evidence[key] = ev
                if with_blobs:
                    raw_blobs[key] = row["embedding"]
            for row in a_rows:
                assertion = _assertion_from_row(row)
                oracle.assertions[assertion.id] = assertion
            for row in p_rows:
                pref = Preference.from_dict(json.loads(row["record"]))
                oracle.preferences[pref.id] = pref
        return (oracle, raw_blobs) if with_blobs else oracle

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
        query_vec = self._embed_text(query)
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
        verbatim — byte-identical to the oracle. ``use_cache`` matches Local
        (computes live; the durable cached-PPR read lands in Task 8)."""
        oracle = self._graph_oracle(tenant_id, branch, filt)
        return oracle.graph_ppr(
            seeds,
            k,
            as_of=as_of,
            tenant_id=tenant_id,
            branch=branch,
            use_cache=use_cache,
            filt=filt,
        )

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
