"""PostgreSQL-backed Mnemosyne engine adapter."""

from __future__ import annotations

import copy
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from mnemosyne.access_policy import (
    apply_relation_redactions,
    apply_statement_redactions,
    apply_text_redactions,
    effective_max_sensitivity,
    filter_export_for_context,
    may_embed_item,
    may_read_item,
    may_use_stored_embedding,
    merge_access_policies,
    validate_access_policy,
    vector_partition_for_item,
)
from mnemosyne.algorithms import fit_budget, mmr_select, ppr_power_iteration, rrf_fuse, u_curve_order
from mnemosyne.calibration import CalibrationSet
from mnemosyne.consciousness import RealityMonitor
from mnemosyne.engine import (
    _normalise_privacy_tags,
    _privacy_backfill_access_policy,
    _privacy_backfill_controls,
    _privacy_backfill_metadata,
)
from mnemosyne.erasure_ids import (
    build_erasure_placeholder_map,
    erasure_deletion_record_id,
    redact_erased_cids,
)
from mnemosyne.ids import evidence_cid, evidence_unscoped_cid
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
from mnemosyne.pipeline import run_retrieval_pipeline
from mnemosyne.policy import OperatingPolicy
from mnemosyne.postgres_security import assert_postgres_safe_role, postgres_safe_role_required
from mnemosyne.privacy import ErasureMode
from mnemosyne.retrieval import (
    HashingEmbeddingProvider,
    LocalSimilarityReranker,
    QUERY_SUPPORT_THRESHOLD,
    RetrievalAdapters,
    embed_query,
    is_retired_summary_metadata,
    query_support,
    validate_adapter_hit_scope,
)
from mnemosyne.security import TrustTier, is_write_tainted, sanitize_retrieved_text, trust_weight
from mnemosyne.standing import (
    standing,
    standing_abstention_report,
    standing_erasure_cascade_report,
    standing_observability_record,
)
from mnemosyne.text import cosine, hashing_embedding, lexical_score, tokenize
from mnemosyne.workspace import self_generation_budget_report


class PostgresUnavailableError(RuntimeError):
    """Raised when the optional psycopg dependency is not installed."""


def _require_psycopg() -> tuple[Any, Any]:
    try:
        import psycopg  # type: ignore[import-not-found]
        from psycopg.types.json import Jsonb  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised when optional dep absent.
        raise PostgresUnavailableError("Install mnemosyne-memory[postgres] to use PostgresEngine.") from exc
    return psycopg, Jsonb


class PostgresEngine:
    """Production storage adapter for the canonical PostgreSQL schema.

    This adapter implements the core MemoryEngine operations against
    sql/schema.sql. It writes deterministic evidence/assertion embeddings and
    lexemes so fresh local deployments exercise the same Postgres full-text,
    pgvector, and graph contracts that production model providers can later
    replace.
    """

    def __init__(
        self,
        dsn: str,
        policy: OperatingPolicy | None = None,
        adapters: RetrievalAdapters | None = None,
        require_safe_role: bool | None = None,
    ):
        self.dsn = dsn
        self.policy = policy or OperatingPolicy()
        self.require_safe_role = (
            postgres_safe_role_required() if require_safe_role is None else bool(require_safe_role)
        )
        if adapters is None:
            embedding = HashingEmbeddingProvider(dims=1024)
            adapters = RetrievalAdapters(
                embedding=embedding,
                reranker=LocalSimilarityReranker(embedding_provider=embedding),
                lexical_backend="postgres-fts",
                graph_backend="postgres-recursive-ppr",
            )
        self.adapters = adapters
        self._psycopg: Any = None
        self._jsonb: Any = None

    def connect(self) -> Any:
        if self._psycopg is None or self._jsonb is None:
            self._psycopg, self._jsonb = _require_psycopg()
        conn = self._psycopg.connect(self.dsn)
        if self.require_safe_role:
            assert_postgres_safe_role(conn, surface="PostgresEngine")
        return conn

    @staticmethod
    def _set_tenant(cur: Any, db_tenant_id: str) -> None:
        cur.execute("SELECT set_config('mnemosyne.tenant_id', %s, true)", (str(db_tenant_id),))

    @staticmethod
    def _ensure_entity_registry_schema(cur: Any) -> None:
        cur.execute("ALTER TABLE entities ADD COLUMN IF NOT EXISTS source_evidence_cids BYTEA[] NOT NULL DEFAULT '{}'")
        cur.execute("ALTER TABLE entities ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS entities_tenant_canonical_unique ON entities (tenant_id, canonical)")

    @staticmethod
    def _ensure_evidence_vector_schema(cur: Any) -> None:
        cur.execute("ALTER TABLE evidence ADD COLUMN IF NOT EXISTS embedding VECTOR(1024)")
        cur.execute("ALTER TABLE evidence ADD COLUMN IF NOT EXISTS embedding_partition TEXT NOT NULL DEFAULT 'none'")
        cur.execute("ALTER TABLE assertions ADD COLUMN IF NOT EXISTS embedding_partition TEXT NOT NULL DEFAULT 'none'")
        cur.execute("ALTER TABLE evidence ALTER COLUMN embedding_partition SET DEFAULT 'none'")
        cur.execute("ALTER TABLE assertions ALTER COLUMN embedding_partition SET DEFAULT 'none'")
        cur.execute(
            """
            DO $$
            BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'evidence_embedding_partition_check'
              ) THEN
                ALTER TABLE evidence
                  ADD CONSTRAINT evidence_embedding_partition_check
                  CHECK (embedding_partition IN ('public', 'private', 'none'));
              END IF;
              IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'assertions_embedding_partition_check'
              ) THEN
                ALTER TABLE assertions
                  ADD CONSTRAINT assertions_embedding_partition_check
                  CHECK (embedding_partition IN ('public', 'private', 'none'));
              END IF;
            END $$;
            """
        )
        cur.execute(
            """
            UPDATE evidence
            SET embedding_partition = CASE
                  WHEN erased
                    OR sensitivity >= 4
                    OR COALESCE(access_policy ? 'unknown', false)
                    OR access_policy->'restricted' = 'true'::jsonb
                    OR access_policy->'hold' = 'true'::jsonb
                    OR access_policy->'embed_ok' = 'false'::jsonb
                    OR access_policy ? 'allow_principals'
                    OR access_policy ? 'redact_fields'
                    OR access_policy ? 'min_role_for_raw'
                    THEN 'none'
                  WHEN sensitivity >= 2
                    OR COALESCE(access_policy->>'data_class', '') <> ''
                       AND COALESCE(access_policy->>'data_class', '') <> 'standard'
                    THEN 'private'
                  ELSE 'public'
                END
            WHERE embedding_partition IS NULL
               OR embedding_partition NOT IN ('public', 'private', 'none')
               OR (
                    embedding_partition <> 'none'
                    AND (
                      erased
                      OR sensitivity >= 4
                      OR COALESCE(access_policy ? 'unknown', false)
                      OR access_policy->'restricted' = 'true'::jsonb
                      OR access_policy->'hold' = 'true'::jsonb
                      OR access_policy->'embed_ok' = 'false'::jsonb
                      OR access_policy ? 'allow_principals'
                      OR access_policy ? 'redact_fields'
                      OR access_policy ? 'min_role_for_raw'
                    )
                  )
               OR (
                    embedding_partition = 'public'
                    AND (
                      sensitivity >= 2
                      OR COALESCE(access_policy->>'data_class', '') <> ''
                         AND COALESCE(access_policy->>'data_class', '') <> 'standard'
                    )
                  )
            """
        )
        cur.execute("UPDATE evidence SET embedding = NULL WHERE embedding_partition = 'none'")
        cur.execute(
            """
            UPDATE assertions
            SET embedding_partition = CASE
                  WHEN status NOT IN ('active', 'candidate', 'contested')
                    OR sensitivity >= 4
                    OR COALESCE(access_policy ? 'unknown', false)
                    OR access_policy->'restricted' = 'true'::jsonb
                    OR access_policy->'hold' = 'true'::jsonb
                    OR access_policy->'embed_ok' = 'false'::jsonb
                    OR access_policy ? 'allow_principals'
                    OR access_policy ? 'redact_fields'
                    OR access_policy ? 'min_role_for_raw'
                    THEN 'none'
                  WHEN sensitivity >= 2
                    OR COALESCE(access_policy->>'data_class', '') <> ''
                       AND COALESCE(access_policy->>'data_class', '') <> 'standard'
                    THEN 'private'
                  ELSE 'public'
                END
            WHERE embedding_partition IS NULL
               OR embedding_partition NOT IN ('public', 'private', 'none')
               OR (
                    embedding_partition <> 'none'
                    AND (
                      status NOT IN ('active', 'candidate', 'contested')
                      OR sensitivity >= 4
                      OR COALESCE(access_policy ? 'unknown', false)
                      OR access_policy->'restricted' = 'true'::jsonb
                      OR access_policy->'hold' = 'true'::jsonb
                      OR access_policy->'embed_ok' = 'false'::jsonb
                      OR access_policy ? 'allow_principals'
                      OR access_policy ? 'redact_fields'
                      OR access_policy ? 'min_role_for_raw'
                    )
                  )
               OR (
                    embedding_partition = 'public'
                    AND (
                      sensitivity >= 2
                      OR COALESCE(access_policy->>'data_class', '') <> ''
                         AND COALESCE(access_policy->>'data_class', '') <> 'standard'
                    )
                  )
            """
        )
        cur.execute("UPDATE assertions SET embedding = NULL WHERE embedding_partition = 'none'")
        cur.execute("DROP INDEX IF EXISTS evidence_embedding_hnsw")
        cur.execute("DROP INDEX IF EXISTS assertions_embedding_hnsw")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS evidence_embedding_public_hnsw ON evidence USING hnsw (embedding vector_cosine_ops) WHERE embedding_partition = 'public'"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS assertions_embedding_public_hnsw ON assertions USING hnsw (embedding vector_cosine_ops) WHERE embedding_partition = 'public'"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS evidence_embedding_private_hnsw ON evidence USING hnsw (embedding vector_cosine_ops) WHERE embedding_partition = 'private'"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS assertions_embedding_private_hnsw ON assertions USING hnsw (embedding vector_cosine_ops) WHERE embedding_partition = 'private'"
        )

    @staticmethod
    def _ensure_preference_access_policy_schema(cur: Any) -> None:
        cur.execute("ALTER TABLE preferences ADD COLUMN IF NOT EXISTS access_policy JSONB NOT NULL DEFAULT '{}'::jsonb")

    @staticmethod
    def _ensure_graph_ppr_cache_schema(cur: Any) -> None:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS graph_ppr_cache (
              tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
              branch TEXT NOT NULL DEFAULT 'main',
              seed_hash TEXT NOT NULL,
              as_of_key TEXT NOT NULL,
              as_of TIMESTAMPTZ,
              relation_fingerprint TEXT NOT NULL,
              cache_depth INTEGER NOT NULL DEFAULT 0 CHECK (cache_depth >= 0),
              hits JSONB NOT NULL DEFAULT '[]'::jsonb,
              refreshed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              PRIMARY KEY (tenant_id, branch, seed_hash, as_of_key),
              FOREIGN KEY (tenant_id, branch) REFERENCES branches(tenant_id, name)
            )
            """
        )
        cur.execute("ALTER TABLE graph_ppr_cache ADD COLUMN IF NOT EXISTS cache_depth INTEGER NOT NULL DEFAULT 0")
        cur.execute(
            """
            DO $$
            BEGIN
              IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'graph_ppr_cache_cache_depth_check'
              ) THEN
                ALTER TABLE graph_ppr_cache
                  ADD CONSTRAINT graph_ppr_cache_cache_depth_check CHECK (cache_depth >= 0);
              END IF;
            END $$;
            """
        )
        cur.execute("ALTER TABLE graph_ppr_cache ENABLE ROW LEVEL SECURITY")
        cur.execute("ALTER TABLE graph_ppr_cache FORCE ROW LEVEL SECURITY")
        cur.execute("DROP POLICY IF EXISTS graph_ppr_cache_tenant_isolation ON graph_ppr_cache")
        cur.execute(
            """
            CREATE POLICY graph_ppr_cache_tenant_isolation ON graph_ppr_cache
              USING (tenant_id = mnemosyne_current_tenant())
              WITH CHECK (tenant_id = mnemosyne_current_tenant())
            """
        )

    def ensure_tenant_and_branch(self, tenant_id: str, branch: str = "main", kind: str = "protected") -> None:
        db_tenant_id = _stable_uuid("tenant", tenant_id)
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO tenants(id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                    (db_tenant_id, tenant_id),
                )
                self._set_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    INSERT INTO branches(tenant_id, name, kind)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (tenant_id, name) DO NOTHING
                    """,
                    (db_tenant_id, branch, kind),
                )

    def append_evidence(self, ev: Evidence, branch: str = "main") -> str:
        access_policy = validate_access_policy(ev.access_policy, tenant_id=ev.tenant_id, location="evidence.access_policy")
        self.ensure_tenant_and_branch(ev.tenant_id, branch)
        db_tenant_id = _stable_uuid("tenant", ev.tenant_id)
        db_user_id = _stable_uuid("user", ev.user_id)
        db_session_id = _stable_uuid("session", ev.session_id) if ev.session_id else None
        metadata = {**ev.metadata, "_external_tenant_id": ev.tenant_id, "_external_user_id": ev.user_id}
        reality_class = self._classify_evidence_reality(ev)
        metadata.setdefault("reality_class", reality_class)
        if ev.session_id:
            metadata["_external_session_id"] = ev.session_id
        cid = evidence_cid(
            ev.content,
            tenant_id=ev.tenant_id,
            user_id=ev.user_id,
            source_type=ev.source_type,
            content_pointer=ev.content_pointer,
            modality=ev.modality,
            sensitivity=int(ev.sensitivity),
        )
        cid_bytes = _cid_to_bytes(cid)
        with self.connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur, db_tenant_id)
                self._ensure_evidence_vector_schema(cur)
                replay_cid = self._erased_replay_cid(
                    cur,
                    external_tenant_id=ev.tenant_id,
                    tenant_id=db_tenant_id,
                    branch=branch,
                    content=ev.content,
                    source_type=ev.source_type,
                    content_pointer=ev.content_pointer,
                    modality=ev.modality,
                )
                if replay_cid is not None:
                    cid = replay_cid
                    cid_bytes = _cid_to_bytes(cid)
                duplicate_noop = self._evidence_row_exists(
                    cur,
                    tenant_id=db_tenant_id,
                    branch=branch,
                    cid_bytes=cid_bytes,
                )
                budget_report: dict[str, Any] | None = None
                if reality_class in {"self_generated", "simulated"}:
                    current_events, current_bytes = self._self_generation_budget_usage(
                        cur,
                        tenant_id=db_tenant_id,
                        branch=branch,
                    )
                    budget_report = self_generation_budget_report(
                        current_events=current_events,
                        incoming_events=1,
                        current_bytes=current_bytes,
                        incoming_bytes=len(ev.content),
                        max_events=self.policy.self_generation_budget_max_events,
                        window_ticks=self.policy.self_generation_budget_window_ticks,
                        duplicate_noop=duplicate_noop,
                    )
                    if not budget_report["allowed"]:
                        self._audit(
                            cur,
                            db_tenant_id,
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
                    if not duplicate_noop:
                        metadata["self_generation_budget"] = budget_report
                        metadata["self_generation_lifecycle"] = {
                            "status": "budgeted_low_groundedness",
                            "demotable": True,
                            "gc_after_idle_ticks": self.policy.self_generation_gc_after_idle_ticks,
                            "pointer_preserved": bool(ev.content_pointer or cid),
                            "critical_path_allowed": False,
                        }
                embedding_partition = vector_partition_for_item(
                    sensitivity=int(ev.sensitivity),
                    access_policy=access_policy,
                )
                metadata["embedding_partition"] = embedding_partition
                if embedding_partition == "none":
                    embedding = None
                elif ev.embedding is not None:
                    metadata["_mnemosyne_embedding_explicit"] = True
                    embedding = _vector_literal(ev.embedding)
                elif embedding_partition == "public":
                    embedding = _vector_literal(self.adapters.embedding.embed(ev.content)) if ev.content else None
                else:
                    embedding = None
                cur.execute(
                    """
                    INSERT INTO evidence (
                      cid, branch, tenant_id, user_id, session_id, actor, source_type,
                      source_identity, content, content_pointer, modality, metadata,
                      trust_tier, capability_tags, sensitivity, signed_provenance,
                      access_policy, embedding, embedding_partition, erased, created_at
                    )
                    VALUES (
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s, false, %s
                    )
                    ON CONFLICT (tenant_id, branch, cid) DO NOTHING
                    """,
                    (
                        cid_bytes,
                        branch,
                        db_tenant_id,
                        db_user_id,
                        db_session_id,
                        ev.actor,
                        ev.source_type,
                        ev.source_identity,
                        ev.content,
                        ev.content_pointer,
                        ev.modality,
                        self._jsonb(metadata),
                        ev.trust_tier,
                        ev.capability_tags,
                        ev.sensitivity,
                        self._jsonb(ev.signed_provenance) if ev.signed_provenance else None,
                        self._jsonb(access_policy),
                        embedding,
                        embedding_partition,
                        ev.created_at,
                    ),
                )
                self._audit(
                    cur,
                    db_tenant_id,
                    ev.actor,
                    "append_evidence",
                    cid,
                    {"branch": branch, "source_type": ev.source_type, "source_identity": ev.source_identity},
                    source=ev.source_type,
                    trust_tier=ev.trust_tier,
                    capability_tags=ev.capability_tags,
                )
        return cid

    def _evidence_row_exists(self, cur: Any, *, tenant_id: UUID, branch: str, cid_bytes: bytes) -> bool:
        cur.execute(
            "SELECT 1 FROM evidence WHERE tenant_id = %s AND branch = %s AND cid = %s LIMIT 1",
            (tenant_id, branch, cid_bytes),
        )
        return cur.fetchone() is not None

    def _erased_replay_cid(
        self,
        cur: Any,
        *,
        external_tenant_id: str,
        tenant_id: UUID,
        branch: str,
        content: str,
        source_type: str,
        content_pointer: str | None,
        modality: str,
    ) -> str | None:
        unscoped_cid = evidence_unscoped_cid(
            content,
            tenant_id=external_tenant_id,
            source_type=source_type,
            content_pointer=content_pointer,
            modality=modality,
        )
        cur.execute(
            """
            SELECT cid, sensitivity, metadata
            FROM evidence
            WHERE tenant_id = %s
              AND branch = %s
              AND erased = true
              AND source_type = %s
              AND content_pointer IS NOT DISTINCT FROM %s
              AND modality = %s
            """,
            (tenant_id, branch, source_type, content_pointer, modality),
        )
        for row in cur.fetchall():
            row_cid = _bytes_to_cid(row[0])
            metadata = dict(row[2] or {})
            row_user_id = metadata.get("_external_user_id")
            if unscoped_cid == row_cid:
                return row_cid
            if not isinstance(row_user_id, str) or not row_user_id:
                continue
            scoped_cid = evidence_cid(
                content,
                tenant_id=external_tenant_id,
                user_id=row_user_id,
                source_type=source_type,
                content_pointer=content_pointer,
                modality=modality,
                sensitivity=int(row[1]),
            )
            if scoped_cid == row_cid:
                return row_cid
        return None

    def _self_generation_budget_usage(self, cur: Any, *, tenant_id: UUID, branch: str) -> tuple[int, int]:
        cur.execute(
            """
            SELECT COUNT(*)::int AS event_count,
                   COALESCE(SUM(LENGTH(COALESCE(content, ''))), 0)::int AS byte_count
            FROM evidence
            WHERE tenant_id = %s
              AND branch = %s
              AND erased = false
              AND (
                COALESCE(metadata->>'reality_class', '') IN ('self_generated', 'simulated')
                OR lower(actor::text) = 'assistant'
                OR lower(source_type) LIKE '%%summary%%'
                OR lower(source_type) LIKE '%%trace%%'
                OR lower(source_type) LIKE '%%analysis%%'
                OR lower(source_type) LIKE '%%consolidation%%'
                OR lower(source_type) LIKE '%%simulation%%'
                OR lower(source_type) LIKE '%%synthetic%%'
                OR lower(source_type) LIKE '%%hypothesis%%'
              )
            """,
            (tenant_id, branch),
        )
        row = cur.fetchone()
        if not row:
            return 0, 0
        return int(row[0] or 0), int(row[1] or 0)

    def get_evidence(self, tenant_id: str, cid: str, branch: str = "main") -> Evidence | None:
        db_tenant_id = _stable_uuid("tenant", tenant_id)
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                self._ensure_entity_registry_schema(cur)
                self._set_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    SELECT e.*, t.name AS tenant_name
                    FROM evidence e
                    JOIN tenants t ON t.id = e.tenant_id
                    WHERE e.tenant_id = %s AND e.branch = %s AND e.cid = %s AND e.erased = false
                    """,
                    (db_tenant_id, branch, _cid_to_bytes(cid)),
                )
                row = cur.fetchone()
        return _row_to_evidence(row, cid) if row else None

    def evidence_is_erased(self, tenant_id: str, cid: str, branch: str = "main") -> bool:
        """Engine-neutral tombstone probe (see ``MemoryEngine.evidence_is_erased``).

        A tombstoned row is retained with ``erased = true`` as the replay
        blocklist; a legal hard-delete removes the row and returns False. This
        closes the pre-existing gap where the poison corpus reached into
        ``LocalMemoryEngine`` internals and so never ran against PostgresEngine.
        """
        db_tenant_id = _stable_uuid("tenant", tenant_id)
        with self.connect() as conn:
            with conn.cursor() as cur:
                self._ensure_entity_registry_schema(cur)
                self._set_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    SELECT erased FROM evidence
                    WHERE tenant_id = %s AND branch = %s AND cid = %s
                    """,
                    (db_tenant_id, branch, _cid_to_bytes(cid)),
                )
                row = cur.fetchone()
        return bool(row) and bool(row[0])

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
        db_tenant_id = _stable_uuid("tenant", tenant_id)
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                self._set_tenant(cur, db_tenant_id)
                self._ensure_evidence_vector_schema(cur)
                cur.execute(
                    """
                    SELECT source_type, trust_tier, capability_tags, sensitivity, access_policy
                    FROM evidence
                    WHERE tenant_id = %s AND branch = %s AND cid = %s AND erased = false
                    """,
                    (db_tenant_id, branch, _cid_to_bytes(cid)),
                )
                row = cur.fetchone()
                if row is None:
                    return False
                embedding_partition = vector_partition_for_item(
                    sensitivity=int(row["sensitivity"]),
                    access_policy=dict(row["access_policy"] or {}),
                )
                if embedding_partition == "none":
                    self._audit(
                        cur,
                        db_tenant_id,
                        actor,
                        "set_evidence_embedding.blocked_policy",
                        cid,
                        {"branch": branch, "source_type": row["source_type"], "reason": "embedding_not_allowed"},
                        source=source,
                        trust_tier=row["trust_tier"],
                        capability_tags=list(row["capability_tags"] or []),
                    )
                    return False
                cur.execute(
                    """
                    UPDATE evidence
                    SET embedding = %s::vector,
                        embedding_partition = %s,
                        metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb
                    WHERE tenant_id = %s AND branch = %s AND cid = %s AND erased = false
                    """,
                    (
                        _vector_literal(embedding),
                        embedding_partition,
                        self._jsonb(
                            {
                                "_mnemosyne_embedding_explicit": True,
                                "embedding_partition": embedding_partition,
                            }
                        ),
                        db_tenant_id,
                        branch,
                        _cid_to_bytes(cid),
                    ),
                )
                self._audit(
                    cur,
                    db_tenant_id,
                    actor,
                    "set_evidence_embedding",
                    cid,
                    {"branch": branch, "embedding_dims": len(embedding), "source_type": row["source_type"]},
                    source=source,
                    trust_tier=row["trust_tier"],
                    capability_tags=list(row["capability_tags"] or []),
                )
        return True

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
        db_tenant_id = _stable_uuid("tenant", tenant_id)
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                self._set_tenant(cur, db_tenant_id)
                self._ensure_preference_access_policy_schema(cur)
                cur.execute(
                    """
                    SELECT metadata, source_type, trust_tier, capability_tags
                    FROM evidence
                    WHERE tenant_id = %s AND branch = %s AND cid = %s AND erased = false
                    """,
                    (db_tenant_id, branch, _cid_to_bytes(cid)),
                )
                row = cur.fetchone()
                if row is None:
                    return False
                metadata = dict(row["metadata"] or {})
                before_keys = sorted(_public_evidence_metadata(metadata).keys())
                metadata.update(metadata_patch)
                cur.execute(
                    """
                    UPDATE evidence
                    SET metadata = %s
                    WHERE tenant_id = %s AND branch = %s AND cid = %s AND erased = false
                    """,
                    (self._jsonb(metadata), db_tenant_id, branch, _cid_to_bytes(cid)),
                )
                self._audit(
                    cur,
                    db_tenant_id,
                    actor,
                    "update_evidence_metadata",
                    cid,
                    {
                        "branch": branch,
                        "patch": metadata_patch,
                        "before_keys": before_keys,
                        "after_keys": sorted(_public_evidence_metadata(metadata).keys()),
                        "source_type": row["source_type"],
                    },
                    source=source,
                    trust_tier=row["trust_tier"],
                    capability_tags=list(row["capability_tags"] or []),
                )
        return True

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
        db_tenant_id = _stable_uuid("tenant", tenant_id)
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                self._set_tenant(cur, db_tenant_id)
                self._ensure_evidence_vector_schema(cur)
                cur.execute(
                    """
                    SELECT metadata, source_type, trust_tier, capability_tags,
                           sensitivity, access_policy, embedding_partition
                    FROM evidence
                    WHERE tenant_id = %s AND branch = %s AND cid = %s AND erased = false
                    """,
                    (db_tenant_id, branch, _cid_to_bytes(cid)),
                )
                row = cur.fetchone()
                if row is None:
                    return False
                before = _privacy_backfill_controls(
                    int(row["sensitivity"]),
                    dict(row["access_policy"] or {}),
                    dict(row["metadata"] or {}),
                )
                target_sensitivity = max(
                    int(row["sensitivity"]),
                    int(pii_sensitivity) if tags else int(row["sensitivity"]),
                )
                access_policy = _privacy_backfill_access_policy(
                    dict(row["access_policy"] or {}),
                    tenant_id=tenant_id,
                    pii_tags=tags,
                    target_sensitivity=target_sensitivity,
                )
                embedding_partition = vector_partition_for_item(
                    sensitivity=target_sensitivity,
                    access_policy=access_policy,
                )
                metadata = _privacy_backfill_metadata(
                    dict(row["metadata"] or {}),
                    access_policy=access_policy,
                    pii_tags=tags,
                    embedding_partition=embedding_partition,
                )
                cur.execute(
                    """
                    UPDATE evidence
                    SET sensitivity = %s,
                        access_policy = %s,
                        metadata = %s,
                        embedding_partition = %s,
                        embedding = CASE WHEN %s = 'none' THEN NULL ELSE embedding END
                    WHERE tenant_id = %s AND branch = %s AND cid = %s AND erased = false
                    """,
                    (
                        target_sensitivity,
                        self._jsonb(access_policy),
                        self._jsonb(metadata),
                        embedding_partition,
                        embedding_partition,
                        db_tenant_id,
                        branch,
                        _cid_to_bytes(cid),
                    ),
                )
                self._audit(
                    cur,
                    db_tenant_id,
                    actor,
                    "backfill_evidence_privacy",
                    cid,
                    {
                        "branch": branch,
                        "pii_tags": tags,
                        "before": before,
                        "after": _privacy_backfill_controls(target_sensitivity, access_policy, metadata),
                        "source_type": row["source_type"],
                    },
                    source=source,
                    trust_tier=row["trust_tier"],
                    capability_tags=list(row["capability_tags"] or []),
                )
        return True

    def _apply_schema_fast_path_projection_status(
        self,
        incoming: Assertion,
        *,
        requested_status: str,
        cur: Any | None = None,
        db_tenant_id: str | None = None,
    ) -> None:
        if not bool(getattr(self.policy, "schema_fast_path_enabled", True)):
            return
        if requested_status not in {"candidate", "active"}:
            return
        calibration = dict(incoming.calibration)
        schema_fast_path = calibration.get("schema_fast_path")
        schema_fast_path = dict(schema_fast_path) if isinstance(schema_fast_path, dict) else {}
        scope = incoming.scope if isinstance(incoming.scope, dict) else {}
        congruent = bool(
            calibration.get("schema_congruent")
            or schema_fast_path.get("schema_congruent")
            or scope.get("schema_congruent")
            or scope.get("schema_fast_path")
        )
        if not congruent:
            return
        minimum = max(1, int(getattr(self.policy, "schema_fast_path_min_corroboration", 2)))
        if cur is not None and db_tenant_id is not None:
            corroboration_report = self._independent_corroboration_report(
                cur,
                tenant_id=incoming.tenant_id,
                branch=incoming.branch,
                db_tenant_id=db_tenant_id,
                source_evidence_cids=incoming.source_evidence_cids,
            )
        else:
            raw_count = len({cid for cid in incoming.source_evidence_cids if cid})
            corroboration_report = {
                "independent_corroboration_count": raw_count,
                "independent_corroboration_weight": min(raw_count, 5) / 5.0,
                "rejected_corroboration_count": 0,
                "rejected_corroborators": [],
            }
        corroboration = int(corroboration_report["independent_corroboration_count"])
        schema_fast_path.update(
            {
                "schema_congruent": True,
                "corroboration_count": corroboration,
                "raw_source_count": len({cid for cid in incoming.source_evidence_cids if cid}),
                "independent_corroboration_weight": corroboration_report["independent_corroboration_weight"],
                "rejected_corroboration_count": corroboration_report["rejected_corroboration_count"],
                "rejected_corroborators": corroboration_report["rejected_corroborators"],
                "min_corroboration": minimum,
            }
        )
        if corroboration < minimum:
            incoming.status = "contested"
            schema_fast_path["reason"] = "uncorroborated_but_congruent"
        else:
            schema_fast_path["reason"] = "corroborated_schema_fast_path"
        calibration["schema_fast_path"] = schema_fast_path
        incoming.calibration = calibration

    def _apply_projection_reality_monitoring(self, cur: Any, incoming: Assertion, db_tenant_id: str) -> None:
        calibration = dict(incoming.calibration)
        monitoring = self._projection_reality_monitoring_for_sources(
            cur,
            tenant_id=incoming.tenant_id,
            branch=incoming.branch,
            db_tenant_id=db_tenant_id,
            source_evidence_cids=incoming.source_evidence_cids,
        )
        calibration["reality_monitoring"] = monitoring
        calibration["reality_class"] = monitoring["reality_class"]
        incoming.calibration = calibration

    def _projection_reality_monitoring_for_sources(
        self,
        cur: Any,
        *,
        tenant_id: str,
        branch: str,
        db_tenant_id: str,
        source_evidence_cids: list[str],
    ) -> dict[str, Any]:
        classes: dict[str, int] = {}
        source_classes: dict[str, str] = {}
        source_cids = sorted({str(item) for item in source_evidence_cids if item})
        if source_cids:
            cur.execute(
                """
                SELECT cid, actor, source_type, metadata, trust_tier
                FROM evidence
                WHERE tenant_id = %s AND branch = %s AND cid = ANY(%s) AND erased = false
                """,
                (db_tenant_id, branch, _cid_list_to_bytes(source_cids)),
            )
            rows = list(cur.fetchall())
        else:
            rows = []
        for row in rows:
            metadata = dict(row["metadata"] or {})
            reality_class = self._classify_evidence_row_reality(row, metadata)
            cid = _bytes_to_cid(row["cid"])
            classes[reality_class] = classes.get(reality_class, 0) + 1
            source_classes[cid] = reality_class
        for missing_cid in source_cids:
            if missing_cid not in source_classes:
                classes["unknown"] = classes.get("unknown", 0) + 1
                source_classes[missing_cid] = "unknown"
        risky = {"self_generated", "simulated", "externally_suggested"}
        grounded_count = classes.get("grounded", 0)
        risky_count = sum(classes.get(item, 0) for item in risky)
        if not source_classes:
            reality_class = "unknown"
        elif grounded_count:
            reality_class = "grounded"
        elif classes.get("simulated", 0):
            reality_class = "simulated"
        elif classes.get("self_generated", 0):
            reality_class = "self_generated"
        elif classes.get("externally_suggested", 0):
            reality_class = "externally_suggested"
        else:
            reality_class = "unknown"
        return {
            "source": "g1_projection_reality_monitoring",
            "applied": True,
            "reality_class": reality_class,
            "classes": classes,
            "source_classes": source_classes,
            "source_count": len(source_classes),
            "grounded_source_count": grounded_count,
            "risky_source_count": risky_count,
            "missing_source_count": classes.get("unknown", 0),
            "mixed": bool(grounded_count and risky_count),
        }

    @classmethod
    def _projection_reality_monitoring_from_calibration(cls, calibration: dict[str, Any]) -> dict[str, Any]:
        monitoring = calibration.get("reality_monitoring") if isinstance(calibration, dict) else None
        if isinstance(monitoring, dict):
            normalized = cls._normalise_reality_class(monitoring.get("reality_class")) or "unknown"
            return {**monitoring, "reality_class": normalized}
        normalized = cls._normalise_reality_class(monitoring) or cls._normalise_reality_class(
            calibration.get("reality_class") if isinstance(calibration, dict) else None
        )
        return {
            "source": "legacy_or_unclassified_projection",
            "applied": False,
            "reality_class": normalized or "unknown",
        }

    def upsert_assertion(self, assertion: Assertion, branch: str = "main") -> str:
        access_policy = validate_access_policy(
            assertion.access_policy,
            tenant_id=assertion.tenant_id,
            location="assertion.access_policy",
        )
        self.ensure_tenant_and_branch(assertion.tenant_id, branch)
        incoming = Assertion.from_dict(assertion.to_dict())
        incoming.access_policy = access_policy
        incoming.branch = branch
        requested_status = incoming.status
        incoming.status = "active" if incoming.status == "candidate" else incoming.status
        incoming.transaction_time = utc_now()
        db_tenant_id = _stable_uuid("tenant", incoming.tenant_id)
        db_user_id = _stable_uuid("user", incoming.user_id) if incoming.user_id else None
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                self._ensure_entity_registry_schema(cur)
                self._ensure_evidence_vector_schema(cur)
                self._set_tenant(cur, db_tenant_id)
                self._apply_projection_reality_monitoring(cur, incoming, db_tenant_id)
                self._apply_schema_fast_path_projection_status(
                    incoming,
                    requested_status=requested_status,
                    cur=cur,
                    db_tenant_id=db_tenant_id,
                )
                cur.execute(
                    """
                    SELECT * FROM assertions
                    WHERE tenant_id = %s AND branch = %s AND subject = %s
                      AND predicate = %s AND scope = %s
                      AND status IN ('active', 'contested')
                    ORDER BY trust_tier ASC, valid_from DESC
                    """,
                    (db_tenant_id, branch, incoming.subject, incoming.predicate, self._jsonb(incoming.scope)),
                )
                peers = list(cur.fetchall())
                same = [row for row in peers if row["object"] == incoming.object]
                if same:
                    winner = same[0]
                    merged_access_policy = merge_access_policies(
                        [dict(winner["access_policy"] or {}), incoming.access_policy],
                        tenant_id=incoming.tenant_id,
                    )
                    merged_confidence = max(float(winner["confidence"]), incoming.confidence)
                    merged_sources = sorted(set(_bytes_list_to_cids(winner["source_evidence_cids"]) + incoming.source_evidence_cids))
                    merged_calibration = dict(winner["calibration"] or {})
                    merged_monitoring = self._projection_reality_monitoring_for_sources(
                        cur,
                        tenant_id=incoming.tenant_id,
                        branch=branch,
                        db_tenant_id=db_tenant_id,
                        source_evidence_cids=merged_sources,
                    )
                    merged_calibration["reality_monitoring"] = merged_monitoring
                    merged_calibration["reality_class"] = merged_monitoring["reality_class"]
                    cur.execute(
                        """
                        UPDATE assertions
                        SET confidence = %s, calibration = %s, source_evidence_cids = %s, trust_tier = LEAST(trust_tier, %s),
                            access_policy = %s, last_accessed = now(), access_count = access_count + 1
                        WHERE id = %s
                        """,
                        (
                            merged_confidence,
                            self._jsonb(merged_calibration),
                            _cid_list_to_bytes(merged_sources),
                            incoming.trust_tier,
                            self._jsonb(merged_access_policy),
                            winner["id"],
                        ),
                    )
                    self._audit(
                        cur,
                        db_tenant_id,
                        "engine",
                        "upsert_assertion.reinforce",
                        str(winner["id"]),
                        {"source_evidence_cids": merged_sources},
                        source="assertion",
                        trust_tier=incoming.trust_tier,
                    )
                    return str(winner["id"])

                conflicts = [row for row in peers if row["object"] != incoming.object]
                if conflicts:
                    current = conflicts[0]
                    current_valid_from = parse_dt(current["valid_from"]) or utc_now()
                    current_trust_tier = int(current["trust_tier"])
                    if incoming.trust_tier < current_trust_tier:
                        incoming.version = int(current["version"]) + 1
                        incoming.status = "active"
                        current_valid_to = (
                            incoming.valid_from
                            if incoming.valid_from > current_valid_from
                            else current_valid_from + timedelta(microseconds=1)
                        )
                        cur.execute(
                            "UPDATE assertions SET valid_to = %s, status = 'superseded', superseded_by = %s WHERE id = %s",
                            (current_valid_to, incoming.id, current["id"]),
                        )
                    elif incoming.trust_tier > current_trust_tier:
                        incoming.status = "superseded"
                        incoming.superseded_by = str(current["id"])
                    elif incoming.valid_from > current_valid_from:
                        incoming.version = int(current["version"]) + 1
                        incoming.status = "active"
                        cur.execute(
                            "UPDATE assertions SET valid_to = %s, status = 'superseded', superseded_by = %s WHERE id = %s",
                            (incoming.valid_from, incoming.id, current["id"]),
                        )
                    elif incoming.valid_from == current_valid_from:
                        incoming.status = "contested"
                        cur.execute("UPDATE assertions SET status = 'contested' WHERE id = %s", (current["id"],))
                    else:
                        incoming.status = "superseded"
                        incoming.valid_to = current_valid_from

                embedding_partition = vector_partition_for_item(
                    sensitivity=int(incoming.sensitivity),
                    access_policy=incoming.access_policy,
                    status=incoming.status,
                )
                assertion_embedding = (
                    _vector_literal(self.adapters.embedding.embed(incoming.statement()))
                    if embedding_partition == "public"
                    else None
                )
                cur.execute(
                    """
                    INSERT INTO assertions (
                      id, tenant_id, user_id, branch, subject, predicate, object, scope,
                      confidence, calibration, valid_from, valid_to, transaction_time,
                      expired_at, justification_id, source_evidence_cids, status, version,
                      superseded_by, trust_tier, sensitivity, access_policy, embedding,
                      embedding_partition, lexeme, last_accessed, access_count
                    )
                    VALUES (
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s, %s, %s::vector, %s,
                      to_tsvector('english', %s), %s, %s
                    )
                    ON CONFLICT (id) DO UPDATE
                    SET confidence = EXCLUDED.confidence,
                        calibration = EXCLUDED.calibration,
                        source_evidence_cids = EXCLUDED.source_evidence_cids,
                        status = EXCLUDED.status,
                        trust_tier = EXCLUDED.trust_tier,
                        sensitivity = EXCLUDED.sensitivity,
                        access_policy = EXCLUDED.access_policy,
                        embedding = EXCLUDED.embedding,
                        embedding_partition = EXCLUDED.embedding_partition,
                        lexeme = EXCLUDED.lexeme
                    """,
                    (
                        incoming.id,
                        db_tenant_id,
                        db_user_id,
                        branch,
                        incoming.subject,
                        incoming.predicate,
                        incoming.object,
                        self._jsonb(incoming.scope),
                        incoming.confidence,
                        self._jsonb(incoming.calibration),
                        incoming.valid_from,
                        incoming.valid_to,
                        incoming.transaction_time,
                        incoming.expired_at,
                        incoming.justification_id,
                        _cid_list_to_bytes(incoming.source_evidence_cids),
                        incoming.status,
                        incoming.version,
                        incoming.superseded_by,
                        incoming.trust_tier,
                        incoming.sensitivity,
                        self._jsonb(incoming.access_policy),
                        assertion_embedding,
                        embedding_partition,
                        incoming.statement(),
                        incoming.last_accessed,
                        incoming.access_count,
                    ),
                )
                self._audit(
                    cur,
                    db_tenant_id,
                    "engine",
                    "upsert_assertion",
                    incoming.id,
                    {"branch": branch, "source_evidence_cids": incoming.source_evidence_cids},
                    source="assertion",
                    trust_tier=incoming.trust_tier,
                )
        return incoming.id

    def add_relation(self, relation: Relation, branch: str = "main") -> str:
        access_policy = validate_access_policy(
            relation.access_policy,
            tenant_id=relation.tenant_id,
            location="relation.access_policy",
        )
        self.ensure_tenant_and_branch(relation.tenant_id, branch)
        db_tenant_id = _stable_uuid("tenant", relation.tenant_id)
        with self.connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    INSERT INTO relations (
                      id, tenant_id, branch, source, predicate, target, confidence,
                      valid_from, valid_to, source_evidence_cids, access_policy
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                    SET confidence = EXCLUDED.confidence,
                        source_evidence_cids = EXCLUDED.source_evidence_cids,
                        access_policy = EXCLUDED.access_policy
                    """,
                    (
                        relation.id,
                        db_tenant_id,
                        branch,
                        relation.source,
                        relation.predicate,
                        relation.target,
                        relation.confidence,
                        relation.valid_from,
                        relation.valid_to,
                        _cid_list_to_bytes(relation.source_evidence_cids),
                        self._jsonb(access_policy),
                    ),
                )
                self._audit(
                    cur,
                    db_tenant_id,
                    "engine",
                    "add_relation",
                    relation.id,
                    {"branch": branch, "source_evidence_cids": relation.source_evidence_cids},
                    source="relation",
                )
        return relation.id

    def add_justification(self, justification: Justification) -> str:
        self.ensure_tenant_and_branch(justification.tenant_id)
        db_tenant_id = _stable_uuid("tenant", justification.tenant_id)
        with self.connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    INSERT INTO justifications (
                      id, tenant_id, assertion_id, evidence_cids, rule,
                      dependency_ids, kind, label, hypothesis_prob
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                    SET evidence_cids = EXCLUDED.evidence_cids,
                        rule = EXCLUDED.rule,
                        dependency_ids = EXCLUDED.dependency_ids,
                        kind = EXCLUDED.kind,
                        label = EXCLUDED.label,
                        hypothesis_prob = EXCLUDED.hypothesis_prob
                    """,
                    (
                        justification.id,
                        db_tenant_id,
                        justification.assertion_id,
                        _cid_list_to_bytes(justification.evidence_cids),
                        justification.rule,
                        list(justification.dependency_ids),
                        justification.kind,
                        self._jsonb(justification.label),
                        justification.hypothesis_prob,
                    ),
                )
                self._audit(
                    cur,
                    db_tenant_id,
                    "engine",
                    "add_justification",
                    justification.id,
                    {
                        "assertion_id": justification.assertion_id,
                        "evidence_cids": justification.evidence_cids,
                        "dependencies": justification.dependency_ids,
                    },
                    source="justification",
                )
        return justification.id

    def add_contradiction(self, contradiction: Contradiction) -> str:
        self.ensure_tenant_and_branch(contradiction.tenant_id)
        db_tenant_id = _stable_uuid("tenant", contradiction.tenant_id)
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                self._set_tenant(cur, db_tenant_id)
                self._ensure_preference_access_policy_schema(cur)
                cur.execute(
                    """
                    SELECT id
                    FROM contradictions
                    WHERE tenant_id = %s AND status = 'open'
                      AND ((a = %s AND b = %s) OR (a = %s AND b = %s))
                    LIMIT 1
                    """,
                    (db_tenant_id, contradiction.a, contradiction.b, contradiction.b, contradiction.a),
                )
                existing = cur.fetchone()
                if existing:
                    return str(existing["id"])
                cur.execute(
                    """
                    INSERT INTO contradictions(id, tenant_id, a, b, detected_at, status, resolution)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        contradiction.id,
                        db_tenant_id,
                        contradiction.a,
                        contradiction.b,
                        contradiction.detected_at,
                        contradiction.status,
                        contradiction.resolution,
                    ),
                )
                self._audit(
                    cur,
                    db_tenant_id,
                    "engine",
                    "add_contradiction",
                    contradiction.id,
                    {"a": contradiction.a, "b": contradiction.b},
                    source="contradiction",
                )
        return contradiction.id

    def add_preference(self, preference: Preference) -> str:
        access_policy = validate_access_policy(
            preference.access_policy,
            tenant_id=preference.tenant_id,
            location="preference.access_policy",
        )
        self.ensure_tenant_and_branch(preference.tenant_id)
        pref = Preference.from_dict(preference.to_dict())
        pref.access_policy = access_policy
        db_tenant_id = _stable_uuid("tenant", pref.tenant_id)
        db_user_id = _stable_uuid("user", pref.user_id)
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                self._set_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    SELECT id, statement, explicit
                    FROM preferences
                    WHERE tenant_id = %s AND user_id = %s AND category = %s
                      AND scope = %s AND status = 'active'
                    """,
                    (db_tenant_id, db_user_id, pref.category, self._jsonb(pref.scope)),
                )
                for row in cur.fetchall():
                    if row["statement"] == pref.statement:
                        continue
                    if pref.explicit or not row["explicit"]:
                        cur.execute(
                            "UPDATE preferences SET status = 'superseded', valid_to = %s WHERE id = %s",
                            (pref.valid_from, row["id"]),
                        )
                    else:
                        pref.status = "retracted"
                cur.execute(
                    """
                    INSERT INTO preferences (
                      id, tenant_id, user_id, category, statement, scope, confidence,
                      explicit, exceptions, source_evidence_cids, valid_from, valid_to,
                      status, access_policy
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                    SET statement = EXCLUDED.statement,
                        confidence = EXCLUDED.confidence,
                        explicit = EXCLUDED.explicit,
                        exceptions = EXCLUDED.exceptions,
                        source_evidence_cids = EXCLUDED.source_evidence_cids,
                        valid_to = EXCLUDED.valid_to,
                        status = EXCLUDED.status,
                        access_policy = EXCLUDED.access_policy
                    """,
                    (
                        pref.id,
                        db_tenant_id,
                        db_user_id,
                        pref.category,
                        pref.statement,
                        self._jsonb(pref.scope),
                        pref.confidence,
                        pref.explicit,
                        self._jsonb(pref.exceptions),
                        _cid_list_to_bytes(pref.source_evidence_cids),
                        pref.valid_from,
                        pref.valid_to,
                        pref.status,
                        self._jsonb(pref.access_policy),
                    ),
                )
                self._audit(
                    cur,
                    db_tenant_id,
                    "engine",
                    "add_preference",
                    pref.id,
                    {
                        "category": pref.category,
                        "explicit": pref.explicit,
                        "source_evidence_cids": pref.source_evidence_cids,
                        "access_policy": pref.access_policy,
                    },
                    source="preference",
                    trust_tier=0 if pref.explicit else None,
                )
        return pref.id

    def lexical_search(self, query: str, k: int, filt: dict[str, Any]) -> list[Hit]:
        tenant_id = str(filt["tenant_id"])
        branch = str(filt.get("branch", "main"))
        if self.adapters.lexical_retriever is not None:
            hits = self.adapters.lexical_retriever.search(
                query,
                tenant_id=tenant_id,
                branch=branch,
                k=k,
                filt=filt,
            )
            hits = validate_adapter_hit_scope(
                hits,
                tenant_id=tenant_id,
                branch=branch,
                k=k,
                adapter_name="lexical",
            )
            return self._mark_retrieved_text_as_data(hits)
        db_tenant_id = _stable_uuid("tenant", tenant_id)
        include_quarantined = bool(filt.get("include_quarantined", False))
        default_max_trust = int(TrustTier.UNTRUSTED_EXTERNAL) if include_quarantined else self.policy.max_trust_tier
        max_trust = int(filt.get("max_trust_tier", filt.get("min_trust_tier", default_max_trust)))
        max_sensitivity = effective_max_sensitivity(filt, self.policy.max_sensitivity)
        hits: list[Hit] = []
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                self._set_tenant(cur, db_tenant_id)
                self._ensure_evidence_vector_schema(cur)
                cur.execute(
                    """
                    WITH q AS (SELECT plainto_tsquery('english', %s) AS query)
                    SELECT e.cid, e.branch, e.content, e.metadata, e.trust_tier, e.sensitivity, e.access_policy,
                      e.actor, e.source_type,
                      ts_rank_cd(to_tsvector('english', coalesce(e.content, '')), q.query) AS score
                    FROM evidence e, q
                    WHERE e.tenant_id = %s AND e.branch = %s AND e.erased = false
                      AND e.trust_tier <= %s AND e.sensitivity <= %s
                      AND (%s OR NOT (e.metadata ? 'quarantine_reason'))
                      AND NOT (
                        e.metadata ? 'summary'
                        AND (
                          lower(coalesce(e.metadata->'summary'->>'status', '')) IN ('retired', 'superseded', 'stale')
                          OR COALESCE((e.metadata->'summary') ? 'retired_at', false)
                          OR COALESCE((e.metadata->'summary') ? 'superseded_by', false)
                        )
                      )
                      AND to_tsvector('english', coalesce(e.content, '')) @@ q.query
                    ORDER BY score DESC
                    LIMIT %s
                    """,
                    (query, db_tenant_id, branch, max_trust, max_sensitivity, include_quarantined, k),
                )
                for row in cur.fetchall():
                    cid = _bytes_to_cid(row["cid"])
                    metadata = dict(row["metadata"] or {})
                    if is_retired_summary_metadata(metadata):
                        continue
                    decision = may_read_item(
                        item_tenant_id=tenant_id,
                        sensitivity=int(row["sensitivity"]),
                        access_policy=dict(row["access_policy"] or {}),
                        context=filt,
                        policy_max_sensitivity=self.policy.max_sensitivity,
                    )
                    if not decision.allowed:
                        continue
                    text, privacy_metadata = apply_text_redactions(row["content"] or "", dict(row["access_policy"] or {}), decision)
                    hit_metadata = {
                        "source_type": row["source_type"],
                        "actor": row["actor"],
                        "backend": self.adapters.lexical_backend,
                        "reality_class": self._classify_evidence_row_reality(row, metadata),
                        "privacy": privacy_metadata,
                    }
                    if isinstance(metadata.get("summary"), dict):
                        hit_metadata["summary"] = metadata["summary"]
                    if isinstance(metadata.get("lifecycle"), dict):
                        hit_metadata["lifecycle"] = metadata["lifecycle"]
                    if "confidence" in metadata:
                        hit_metadata["confidence"] = metadata["confidence"]
                    if isinstance(metadata.get("earned_autonomy"), dict):
                        hit_metadata["earned_autonomy"] = metadata["earned_autonomy"]
                    if "birth_groundedness" in metadata:
                        hit_metadata["birth_groundedness"] = metadata["birth_groundedness"]
                    hits.append(
                        Hit(
                            id=cid,
                            kind="evidence",
                            tenant_id=tenant_id,
                            branch=row["branch"],
                            text=text,
                            score=float(row["score"] or 0.0),
                            channel="postgres_fts",
                            provenance=[cid],
                            trust_tier=row["trust_tier"],
                            sensitivity=row["sensitivity"],
                            metadata=hit_metadata,
                        )
                    )
                cur.execute(
                    """
                    WITH q AS (SELECT plainto_tsquery('english', %s) AS query)
                    SELECT a.id, a.branch, a.subject, a.predicate, a.object, a.confidence, a.calibration, a.status,
                      a.source_evidence_cids, a.trust_tier, a.sensitivity, a.access_policy, a.last_accessed, a.access_count,
                      ts_rank_cd(coalesce(a.lexeme, to_tsvector('english', concat_ws(' ', a.subject, a.predicate, a.object))), q.query) AS score
                    FROM assertions a, q
                    WHERE a.tenant_id = %s AND a.branch = %s AND a.status IN ('active', 'contested')
                      AND a.trust_tier <= %s AND a.sensitivity <= %s
                      AND coalesce(a.lexeme, to_tsvector('english', concat_ws(' ', a.subject, a.predicate, a.object))) @@ q.query
                    ORDER BY score DESC, a.confidence DESC
                    LIMIT %s
                    """,
                    (query, db_tenant_id, branch, max_trust, max_sensitivity, k),
                )
                for row in cur.fetchall():
                    decision = may_read_item(
                        item_tenant_id=tenant_id,
                        sensitivity=int(row["sensitivity"]),
                        access_policy=dict(row["access_policy"] or {}),
                        context=filt,
                        policy_max_sensitivity=self.policy.max_sensitivity,
                        status=str(row["status"]),
                    )
                    if not decision.allowed:
                        continue
                    text, privacy_metadata = apply_statement_redactions(
                        subject=str(row["subject"]),
                        predicate=str(row["predicate"]),
                        object_value=str(row["object"]),
                        access_policy=dict(row["access_policy"] or {}),
                        decision=decision,
                    )
                    reality_monitoring = self._projection_reality_monitoring_from_calibration(dict(row["calibration"] or {}))
                    hits.append(
                        Hit(
                            id=str(row["id"]),
                            kind="assertion",
                            tenant_id=tenant_id,
                            branch=row["branch"],
                            text=text,
                            score=float(row["score"] or 0.0) * float(row["confidence"]),
                            channel="postgres_fts",
                            provenance=_bytes_list_to_cids(row["source_evidence_cids"]),
                            trust_tier=row["trust_tier"],
                            sensitivity=row["sensitivity"],
                            metadata={
                                "confidence": float(row["confidence"]),
                                "reality_class": reality_monitoring["reality_class"],
                                "reality_monitoring": reality_monitoring,
                                "backend": self.adapters.lexical_backend,
                                "last_accessed": row["last_accessed"].isoformat() if row["last_accessed"] else None,
                                "access_count": row["access_count"],
                                "privacy": privacy_metadata,
                            },
                        )
                    )
        if not hits:
            return self._local_rank(query, k, filt, channel="postgres_lexical_fallback")
        return self._mark_retrieved_text_as_data(sorted(hits, key=lambda item: item.score, reverse=True)[:k])

    def vector_search(self, query: str, k: int, filt: dict[str, Any]) -> list[Hit]:
        tenant_id = filt["tenant_id"]
        db_tenant_id = _stable_uuid("tenant", tenant_id)
        branch = filt.get("branch", "main")
        include_quarantined = bool(filt.get("include_quarantined", False))
        default_max_trust = int(TrustTier.UNTRUSTED_EXTERNAL) if include_quarantined else self.policy.max_trust_tier
        max_trust = int(filt.get("max_trust_tier", filt.get("min_trust_tier", default_max_trust)))
        max_sensitivity = effective_max_sensitivity(filt, self.policy.max_sensitivity)
        query_vec = embed_query(self.adapters.embedding, query)
        query_literal = _vector_literal(query_vec)
        hits: list[Hit] = []
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                self._set_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    SELECT id, branch, subject, predicate, object, confidence, calibration, status,
                      source_evidence_cids, trust_tier, sensitivity, access_policy, last_accessed, access_count,
                      embedding_partition, 1.0 - (embedding <=> %s::vector) AS score
                    FROM assertions
                    WHERE tenant_id = %s AND branch = %s AND status IN ('active', 'contested')
                      AND trust_tier <= %s AND sensitivity <= %s
                      AND embedding IS NOT NULL
                      AND embedding_partition <> 'none'
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (query_literal, db_tenant_id, branch, max_trust, max_sensitivity, query_literal, k),
                )
                for row in cur.fetchall():
                    score = float(row["score"] or 0.0)
                    if score <= 0:
                        continue
                    decision = may_read_item(
                        item_tenant_id=tenant_id,
                        sensitivity=int(row["sensitivity"]),
                        access_policy=dict(row["access_policy"] or {}),
                        context=filt,
                        policy_max_sensitivity=self.policy.max_sensitivity,
                        status=str(row["status"]),
                    )
                    if not decision.allowed:
                        continue
                    if not may_use_stored_embedding(
                        decision=decision,
                        sensitivity=int(row["sensitivity"]),
                        access_policy=dict(row["access_policy"] or {}),
                        embedding_partition=str(row["embedding_partition"] or ""),
                    ):
                        continue
                    text, privacy_metadata = apply_statement_redactions(
                        subject=str(row["subject"]),
                        predicate=str(row["predicate"]),
                        object_value=str(row["object"]),
                        access_policy=dict(row["access_policy"] or {}),
                        decision=decision,
                    )
                    reality_monitoring = self._projection_reality_monitoring_from_calibration(dict(row["calibration"] or {}))
                    hits.append(
                        Hit(
                            id=str(row["id"]),
                            kind="assertion",
                            tenant_id=tenant_id,
                            branch=row["branch"],
                            text=text,
                            score=score * float(row["confidence"]),
                            channel="postgres_pgvector",
                            provenance=_bytes_list_to_cids(row["source_evidence_cids"]),
                            trust_tier=row["trust_tier"],
                            sensitivity=row["sensitivity"],
                            metadata={
                                "confidence": float(row["confidence"]),
                                "reality_class": reality_monitoring["reality_class"],
                                "reality_monitoring": reality_monitoring,
                                "backend": self.adapters.embedding.name,
                                "embedding_dims": self.adapters.embedding.dims,
                                "last_accessed": row["last_accessed"].isoformat() if row["last_accessed"] else None,
                                "access_count": row["access_count"],
                                "privacy": privacy_metadata,
                            },
                        )
                    )
                cur.execute(
                    """
                    SELECT cid, branch, content, content_pointer, modality, metadata,
                      trust_tier, sensitivity, access_policy, actor, source_type,
                      embedding_partition, 1.0 - (embedding <=> %s::vector) AS score
                    FROM evidence
                    WHERE tenant_id = %s AND branch = %s AND erased = false
                      AND trust_tier <= %s AND sensitivity <= %s
                      AND (%s OR NOT (metadata ? 'quarantine_reason'))
                      AND NOT (
                        metadata ? 'summary'
                        AND (
                          lower(coalesce(metadata->'summary'->>'status', '')) IN ('retired', 'superseded', 'stale')
                          OR COALESCE((metadata->'summary') ? 'retired_at', false)
                          OR COALESCE((metadata->'summary') ? 'superseded_by', false)
                        )
                      )
                      AND embedding IS NOT NULL
                      AND embedding_partition <> 'none'
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (
                        query_literal,
                        db_tenant_id,
                        branch,
                        max_trust,
                        max_sensitivity,
                        include_quarantined,
                        query_literal,
                        k,
                    ),
                )
                for row in cur.fetchall():
                    text = row["content"] or row["content_pointer"] or f"{row['modality']} evidence"
                    score = float(row["score"] or 0.0)
                    if score <= 0:
                        continue
                    cid = _bytes_to_cid(row["cid"])
                    metadata = dict(row["metadata"] or {})
                    if is_retired_summary_metadata(metadata):
                        continue
                    decision = may_read_item(
                        item_tenant_id=tenant_id,
                        sensitivity=int(row["sensitivity"]),
                        access_policy=dict(row["access_policy"] or {}),
                        context=filt,
                        policy_max_sensitivity=self.policy.max_sensitivity,
                    )
                    if not decision.allowed:
                        continue
                    if not may_use_stored_embedding(
                        decision=decision,
                        sensitivity=int(row["sensitivity"]),
                        access_policy=dict(row["access_policy"] or {}),
                        embedding_partition=str(row["embedding_partition"] or ""),
                    ):
                        continue
                    text, privacy_metadata = apply_text_redactions(text, dict(row["access_policy"] or {}), decision)
                    media_embedding = metadata.get("media_embedding")
                    hit_metadata = {
                        "source_type": row["source_type"],
                        "actor": row["actor"],
                        "backend": self.adapters.embedding.name,
                        "embedding_dims": self.adapters.embedding.dims,
                        "stored_embedding": True,
                        "embedding_partition": str(row["embedding_partition"] or ""),
                        "stored_media_embedding": bool(media_embedding and row["modality"] != "text"),
                        "source_table": "evidence",
                        "modality": row["modality"],
                        "content_pointer": row["content_pointer"],
                        "reality_class": self._classify_evidence_row_reality(row, metadata),
                        "privacy": privacy_metadata,
                    }
                    if isinstance(media_embedding, dict):
                        hit_metadata["media_embedding"] = media_embedding
                    if isinstance(metadata.get("summary"), dict):
                        hit_metadata["summary"] = metadata["summary"]
                    if isinstance(metadata.get("lifecycle"), dict):
                        hit_metadata["lifecycle"] = metadata["lifecycle"]
                    if "confidence" in metadata:
                        hit_metadata["confidence"] = metadata["confidence"]
                    if isinstance(metadata.get("earned_autonomy"), dict):
                        hit_metadata["earned_autonomy"] = metadata["earned_autonomy"]
                    if "birth_groundedness" in metadata:
                        hit_metadata["birth_groundedness"] = metadata["birth_groundedness"]
                    hits.append(
                        Hit(
                            id=cid,
                            kind="evidence",
                            tenant_id=tenant_id,
                            branch=row["branch"],
                            text=text,
                            score=score,
                            channel="postgres_pgvector",
                            provenance=[cid],
                            trust_tier=row["trust_tier"],
                            sensitivity=row["sensitivity"],
                            metadata=hit_metadata,
                        )
                    )
                cur.execute(
                    """
                    SELECT cid, branch, content, content_pointer, modality, metadata,
                      trust_tier, sensitivity, access_policy, actor, source_type, embedding_partition
                    FROM evidence
                    WHERE tenant_id = %s AND branch = %s AND erased = false
                      AND trust_tier <= %s AND sensitivity <= %s
                      AND (%s OR NOT (metadata ? 'quarantine_reason'))
                      AND NOT (
                        metadata ? 'summary'
                        AND (
                          lower(coalesce(metadata->'summary'->>'status', '')) IN ('retired', 'superseded', 'stale')
                          OR COALESCE((metadata->'summary') ? 'retired_at', false)
                          OR COALESCE((metadata->'summary') ? 'superseded_by', false)
                        )
                      )
                      AND embedding IS NULL
                    """,
                    (db_tenant_id, branch, max_trust, max_sensitivity, include_quarantined),
                )
                for row in cur.fetchall():
                    text = row["content"] or row["content_pointer"] or f"{row['modality']} evidence"
                    cid = _bytes_to_cid(row["cid"])
                    metadata = dict(row["metadata"] or {})
                    if is_retired_summary_metadata(metadata):
                        continue
                    decision = may_read_item(
                        item_tenant_id=tenant_id,
                        sensitivity=int(row["sensitivity"]),
                        access_policy=dict(row["access_policy"] or {}),
                        context=filt,
                        policy_max_sensitivity=self.policy.max_sensitivity,
                    )
                    if not decision.allowed:
                        continue
                    text, privacy_metadata = apply_text_redactions(text, dict(row["access_policy"] or {}), decision)
                    if not may_embed_item(
                        sensitivity=int(row["sensitivity"]),
                        access_policy=dict(row["access_policy"] or {}),
                    ):
                        continue
                    if str(row["embedding_partition"] or "") == "private" and not may_use_stored_embedding(
                        decision=decision,
                        sensitivity=int(row["sensitivity"]),
                        access_policy=dict(row["access_policy"] or {}),
                        embedding_partition=str(row["embedding_partition"] or ""),
                    ):
                        # Use the redacted projection for dense fallback; never
                        # the raw text loaded from the database.
                        fallback_text = text
                    else:
                        fallback_text = text
                    score = cosine(query_vec, self.adapters.embedding.embed(fallback_text))
                    if score <= 0:
                        continue
                    hit_metadata = {
                        "source_type": row["source_type"],
                        "actor": row["actor"],
                        "backend": self.adapters.embedding.name,
                        "embedding_dims": self.adapters.embedding.dims,
                        "stored_embedding": False,
                        "embedding_partition": str(row["embedding_partition"] or ""),
                        "source_table": "evidence",
                        "reality_class": self._classify_evidence_row_reality(row, metadata),
                        "privacy": privacy_metadata,
                    }
                    if isinstance(metadata.get("summary"), dict):
                        hit_metadata["summary"] = metadata["summary"]
                    if isinstance(metadata.get("lifecycle"), dict):
                        hit_metadata["lifecycle"] = metadata["lifecycle"]
                    if "confidence" in metadata:
                        hit_metadata["confidence"] = metadata["confidence"]
                    if isinstance(metadata.get("earned_autonomy"), dict):
                        hit_metadata["earned_autonomy"] = metadata["earned_autonomy"]
                    if "birth_groundedness" in metadata:
                        hit_metadata["birth_groundedness"] = metadata["birth_groundedness"]
                    hits.append(
                        Hit(
                            id=cid,
                            kind="evidence",
                            tenant_id=tenant_id,
                            branch=row["branch"],
                            text=text,
                            score=score,
                            channel="postgres_dense_fallback",
                            provenance=[cid],
                            trust_tier=row["trust_tier"],
                            sensitivity=row["sensitivity"],
                            metadata=hit_metadata,
                        )
                    )
        return self._mark_retrieved_text_as_data(sorted(hits, key=lambda item: item.score, reverse=True)[:k])

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
        seed_set = {seed.lower() for seed in seeds}
        if not seed_set or not tenant_id:
            return []
        def matches_seed(node: str) -> bool:
            node_lower = node.lower()
            return node_lower in seed_set or bool(set(tokenize(node_lower)) & seed_set)

        tenant_id = str(tenant_id or "")
        branch = str(branch or "main")
        moment = as_of or utc_now()
        moment = moment.astimezone(UTC) if moment.tzinfo else moment.replace(tzinfo=UTC)
        graph_filter = dict(filt or {})
        graph_filter.setdefault("tenant_id", tenant_id)
        graph_filter.setdefault("branch", branch)
        include_quarantined = bool(graph_filter.get("include_quarantined", False))
        default_max_trust = int(TrustTier.UNTRUSTED_EXTERNAL) if include_quarantined else self.policy.max_trust_tier
        max_trust = int(graph_filter.get("max_trust_tier", graph_filter.get("min_trust_tier", default_max_trust)))
        max_sensitivity = effective_max_sensitivity(graph_filter, self.policy.max_sensitivity)
        db_tenant_id = _stable_uuid("tenant", tenant_id)
        if self.adapters.graph_retriever is not None:
            hits = self.adapters.graph_retriever.search(
                seeds,
                tenant_id=tenant_id,
                branch=branch,
                k=k,
                as_of=moment,
                filt=graph_filter,
            )
            hits = validate_adapter_hit_scope(
                hits,
                tenant_id=tenant_id,
                branch=branch,
                k=k,
                adapter_name="graph",
            )
            hits = self._filter_graph_adapter_hits(
                hits,
                db_tenant_id=db_tenant_id,
                branch=branch,
                include_quarantined=include_quarantined,
                max_trust=max_trust,
                max_sensitivity=max_sensitivity,
                access_context=graph_filter,
            )
            return self._mark_retrieved_text_as_data(hits)
        if use_cache:
            cached_hits = self._read_graph_ppr_cache(
                seed_set=seed_set,
                k=k,
                db_tenant_id=db_tenant_id,
                tenant_id=tenant_id,
                branch=branch,
                moment=moment,
                as_of=as_of,
                include_quarantined=include_quarantined,
                max_trust=max_trust,
                max_sensitivity=max_sensitivity,
                access_context=graph_filter,
            )
            if cached_hits is not None:
                return self._mark_retrieved_text_as_data(cached_hits)
        adjacency: dict[str, set[str]] = defaultdict(set)
        relation_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                self._set_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    SELECT *
                    FROM relations
                    WHERE tenant_id = %s AND branch = %s
                      AND valid_from <= %s AND (valid_to IS NULL OR valid_to > %s)
                    """,
                    (db_tenant_id, branch, moment, moment),
                )
                relation_rows = [dict(row) for row in cur.fetchall()]
                relation_source_cids: set[bytes] = set()
                for row in relation_rows:
                    for cid_value in row.get("source_evidence_cids") or []:
                        raw = cid_value.tobytes() if isinstance(cid_value, memoryview) else cid_value
                        if raw:
                            relation_source_cids.add(bytes(raw))
                evidence_by_cid: dict[str, dict[str, Any]] = {}
                if relation_source_cids:
                    cur.execute(
                        """
                        SELECT cid, metadata, trust_tier, sensitivity, access_policy, erased, actor, source_type
                        FROM evidence
                        WHERE tenant_id = %s AND branch = %s AND cid = ANY(%s::bytea[])
                        """,
                        (db_tenant_id, branch, list(relation_source_cids)),
                    )
                    evidence_by_cid = {_bytes_to_cid(row["cid"]): dict(row) for row in cur.fetchall()}
                for row in relation_rows:
                    security = self._relation_hit_security_from_rows(
                        row,
                        evidence_by_cid,
                        include_quarantined=include_quarantined,
                        max_trust=max_trust,
                        max_sensitivity=max_sensitivity,
                        access_context=graph_filter,
                    )
                    if security is None:
                        continue
                    relation_policy = dict(row.get("access_policy") or {})
                    relation_decision = may_read_item(
                        item_tenant_id=tenant_id,
                        sensitivity=int(security["sensitivity"]),
                        access_policy=relation_policy,
                        context=graph_filter,
                        policy_max_sensitivity=self.policy.max_sensitivity,
                        status="active",
                    )
                    if not relation_decision.allowed:
                        continue
                    source = row["source"].lower()
                    target = row["target"].lower()
                    adjacency[source].add(target)
                    adjacency[target].add(source)
                    row["hit_security"] = security
                    row["hit_access_decision"] = relation_decision
                    row["hit_access_policy"] = relation_policy
                    relation_by_pair[(source, target)] = dict(row)
                    relation_by_pair[(target, source)] = dict(row)
        hits: list[Hit] = []
        seen_relation_ids: set[str] = set()
        for rel in {str(row["id"]): row for row in relation_by_pair.values()}.values():
            if not (matches_seed(str(rel["source"])) and matches_seed(str(rel["target"]))):
                continue
            relation_id = str(rel["id"])
            security = rel["hit_security"]
            relation_policy = dict(rel.get("hit_access_policy") or {})
            relation_decision = rel["hit_access_decision"]
            text, privacy_metadata = apply_relation_redactions(
                source=str(rel["source"]),
                predicate=str(rel["predicate"]),
                target=str(rel["target"]),
                access_policy=relation_policy,
                decision=relation_decision,
            )
            relation_fields = privacy_metadata.get("redacted_record")
            if not isinstance(relation_fields, dict):
                relation_fields = {
                    "source": str(rel["source"]),
                    "predicate": str(rel["predicate"]),
                    "target": str(rel["target"]),
                }
            seen_relation_ids.add(relation_id)
            hits.append(
                Hit(
                    id=relation_id,
                    kind="relation",
                    tenant_id=tenant_id,
                    branch=rel["branch"],
                    text=text,
                    score=float(rel["confidence"]),
                    channel="postgres_graph_ppr",
                    provenance=_bytes_list_to_cids(rel["source_evidence_cids"]),
                    trust_tier=security["trust_tier"],
                    sensitivity=security["sensitivity"],
                    metadata={
                        "source": relation_fields["source"],
                        "predicate": relation_fields["predicate"],
                        "target": relation_fields["target"],
                        "confidence": float(rel["confidence"]),
                        "source_evidence_cids": _bytes_list_to_cids(rel["source_evidence_cids"]),
                        "backend": self.adapters.graph_backend,
                        "reality_class": security["reality_class"],
                        "source_evidence_status": security["source_evidence_status"],
                        "source_evidence_security": security["source_evidence_security"],
                        "direct_seed_relation": True,
                        "privacy": privacy_metadata,
                    },
                )
            )
            if len(hits) >= k:
                return self._mark_retrieved_text_as_data(hits)
        for seed in seed_set:
            adjacency.setdefault(seed, [])
        ranks = ppr_power_iteration(adjacency, matches_seed)
        for node, score in sorted(ranks.items(), key=lambda item: item[1], reverse=True):
            if matches_seed(node) or score <= 0:
                continue
            rel = next((relation_by_pair[pair] for pair in relation_by_pair if pair[0] == node or pair[1] == node), None)
            if not rel:
                continue
            relation_id = str(rel["id"])
            if relation_id in seen_relation_ids:
                continue
            security = rel["hit_security"]
            relation_policy = dict(rel.get("hit_access_policy") or {})
            relation_decision = rel["hit_access_decision"]
            text, privacy_metadata = apply_relation_redactions(
                source=str(rel["source"]),
                predicate=str(rel["predicate"]),
                target=str(rel["target"]),
                access_policy=relation_policy,
                decision=relation_decision,
            )
            relation_fields = privacy_metadata.get("redacted_record")
            if not isinstance(relation_fields, dict):
                relation_fields = {
                    "source": str(rel["source"]),
                    "predicate": str(rel["predicate"]),
                    "target": str(rel["target"]),
                }
            seen_relation_ids.add(relation_id)
            hits.append(
                Hit(
                    id=relation_id,
                    kind="relation",
                    tenant_id=tenant_id,
                    branch=rel["branch"],
                    text=text,
                    score=float(score) * float(rel["confidence"]),
                    channel="postgres_graph_ppr",
                    provenance=_bytes_list_to_cids(rel["source_evidence_cids"]),
                    trust_tier=security["trust_tier"],
                    sensitivity=security["sensitivity"],
                    metadata={
                        "source": relation_fields["source"],
                        "predicate": relation_fields["predicate"],
                        "target": relation_fields["target"],
                        "confidence": float(rel["confidence"]),
                        "source_evidence_cids": _bytes_list_to_cids(rel["source_evidence_cids"]),
                        "backend": self.adapters.graph_backend,
                        "reality_class": security["reality_class"],
                        "source_evidence_status": security["source_evidence_status"],
                        "source_evidence_security": security["source_evidence_security"],
                        "privacy": privacy_metadata,
                    },
                )
            )
            if len(hits) >= k:
                break
        return self._mark_retrieved_text_as_data(hits)

    def refresh_graph_ppr_cache(
        self,
        seeds: list[str],
        k: int,
        as_of: datetime | None = None,
        tenant_id: str | None = None,
        branch: str = "main",
    ) -> dict[str, Any]:
        seed_set = {seed.lower() for seed in seeds}
        if not seed_set or not tenant_id:
            return {"refreshed": False, "reason": "missing_seed_or_tenant", "hit_count": 0}
        tenant_id = str(tenant_id)
        branch = str(branch or "main")
        db_tenant_id = _stable_uuid("tenant", tenant_id)
        moment = as_of or utc_now()
        moment = moment.astimezone(UTC) if moment.tzinfo else moment.replace(tzinfo=UTC)
        self.ensure_tenant_and_branch(tenant_id, branch)
        hits = self.graph_ppr(seeds, k, as_of=as_of, tenant_id=tenant_id, branch=branch, use_cache=False)
        relation_fingerprint = self._graph_ppr_relation_fingerprint(db_tenant_id, branch, moment)
        seed_hash = _graph_ppr_seed_hash(seed_set)
        as_of_key = _graph_ppr_as_of_key(as_of, moment)
        with self.connect() as conn:
            with conn.cursor() as cur:
                self._ensure_graph_ppr_cache_schema(cur)
                self._set_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    INSERT INTO graph_ppr_cache (
                      tenant_id, branch, seed_hash, as_of_key, as_of,
                      relation_fingerprint, cache_depth, hits, refreshed_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (tenant_id, branch, seed_hash, as_of_key)
                    DO UPDATE SET
                      as_of = EXCLUDED.as_of,
                      relation_fingerprint = EXCLUDED.relation_fingerprint,
                      cache_depth = EXCLUDED.cache_depth,
                      hits = EXCLUDED.hits,
                      refreshed_at = now()
                    """,
                    (
                        db_tenant_id,
                        branch,
                        seed_hash,
                        as_of_key,
                        moment if as_of is not None else None,
                        relation_fingerprint,
                        k,
                        self._jsonb([hit.to_dict() for hit in hits]),
                    ),
                )
        return {
            "refreshed": True,
            "hit_count": len(hits),
            "seed_hash": seed_hash,
            "as_of_key": as_of_key,
            "relation_fingerprint": relation_fingerprint,
        }

    def _read_graph_ppr_cache(
        self,
        *,
        seed_set: set[str],
        k: int,
        db_tenant_id: str,
        tenant_id: str,
        branch: str,
        moment: datetime,
        as_of: datetime | None,
        include_quarantined: bool,
        max_trust: int,
        max_sensitivity: int,
        access_context: dict[str, Any] | None = None,
    ) -> list[Hit] | None:
        cache_context = dict(access_context or {})
        role = str(cache_context.get("role") or cache_context.get("mnemosyne_role") or "reader").lower()
        extra_context = set(cache_context) - {"tenant_id", "tenant", "branch", "role", "mnemosyne_role"}
        default_reader_sensitivity = effective_max_sensitivity({"role": "reader"}, self.policy.max_sensitivity)
        if (
            include_quarantined
            or max_trust != int(self.policy.max_trust_tier)
            or max_sensitivity != default_reader_sensitivity
            or role != "reader"
            or extra_context
        ):
            return None
        relation_fingerprint = self._graph_ppr_relation_fingerprint(db_tenant_id, branch, moment)
        seed_hash = _graph_ppr_seed_hash(seed_set)
        as_of_key = _graph_ppr_as_of_key(as_of, moment)
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                self._ensure_graph_ppr_cache_schema(cur)
                self._set_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    SELECT relation_fingerprint, cache_depth, hits
                    FROM graph_ppr_cache
                    WHERE tenant_id = %s AND branch = %s AND seed_hash = %s AND as_of_key = %s
                    """,
                    (db_tenant_id, branch, seed_hash, as_of_key),
                )
                row = cur.fetchone()
        if row is None or row["relation_fingerprint"] != relation_fingerprint:
            return None
        if int(row["cache_depth"] or 0) < k or len(row["hits"] or []) < k:
            return None
        hits: list[Hit] = []
        for item in list(row["hits"] or [])[:k]:
            data = dict(item)
            data["tenant_id"] = tenant_id
            data["branch"] = branch
            hits.append(Hit(**data))
        return hits

    def _graph_ppr_relation_fingerprint(self, db_tenant_id: str, branch: str, moment: datetime) -> str:
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                self._set_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    SELECT id, source, predicate, target, confidence, weight,
                           valid_from, valid_to, source_evidence_cids, access_policy
                    FROM relations
                    WHERE tenant_id = %s AND branch = %s
                      AND valid_from <= %s AND (valid_to IS NULL OR valid_to > %s)
                    ORDER BY id
                    """,
                    (db_tenant_id, branch, moment, moment),
                )
                rows = cur.fetchall()
                source_cid_bytes: set[bytes] = set()
                for row in rows:
                    for cid_value in row.get("source_evidence_cids") or []:
                        raw = cid_value.tobytes() if isinstance(cid_value, memoryview) else cid_value
                        if raw:
                            source_cid_bytes.add(bytes(raw))
                evidence_by_cid: dict[str, dict[str, Any]] = {}
                if source_cid_bytes:
                    cur.execute(
                        """
                        SELECT cid, trust_tier, sensitivity, metadata, erased, source_type, actor, access_policy
                        FROM evidence
                        WHERE tenant_id = %s AND branch = %s AND cid = ANY(%s::bytea[])
                        ORDER BY cid
                        """,
                        (db_tenant_id, branch, sorted(source_cid_bytes)),
                    )
                    evidence_by_cid = {_bytes_to_cid(row["cid"]): dict(row) for row in cur.fetchall()}
        payload = [
            {
                "id": str(row["id"]),
                "source": row["source"],
                "predicate": row["predicate"],
                "target": row["target"],
                "confidence": float(row["confidence"]),
                "weight": float(row["weight"]),
                "valid_from": dt_to_json(row["valid_from"]),
                "valid_to": dt_to_json(row["valid_to"]),
                "source_evidence_cids": _bytes_list_to_cids(row["source_evidence_cids"]),
                "access_policy": dict(row.get("access_policy") or {}),
                "source_evidence_custody": [
                    {
                        "cid": cid,
                        "present": cid in evidence_by_cid,
                        "trust_tier": int(evidence_by_cid[cid].get("trust_tier") or 0) if cid in evidence_by_cid else None,
                        "sensitivity": int(evidence_by_cid[cid].get("sensitivity") or 0) if cid in evidence_by_cid else None,
                        "metadata": dict(evidence_by_cid[cid].get("metadata") or {}) if cid in evidence_by_cid else None,
                        "erased": bool(evidence_by_cid[cid].get("erased")) if cid in evidence_by_cid else None,
                        "source_type": str(evidence_by_cid[cid].get("source_type") or "")
                        if cid in evidence_by_cid
                        else None,
                        "actor": str(evidence_by_cid[cid].get("actor") or "") if cid in evidence_by_cid else None,
                        "access_policy": dict(evidence_by_cid[cid].get("access_policy") or {})
                        if cid in evidence_by_cid
                        else None,
                    }
                    for cid in _bytes_list_to_cids(row["source_evidence_cids"])
                ],
            }
            for row in rows
        ]
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return sha256(encoded).hexdigest()

    def as_of(self, subject: str, predicate: str, t: datetime, tenant_id: str | None = None, branch: str = "main") -> list[Assertion]:
        moment = t.astimezone(UTC) if t.tzinfo else t.replace(tzinfo=UTC)
        if not tenant_id:
            raise ValueError("PostgresEngine.as_of requires tenant_id")
        db_tenant_id = _stable_uuid("tenant", tenant_id)
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                self._set_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    SELECT a.*, t.name AS tenant_name
                    FROM assertions a
                    JOIN tenants t ON t.id = a.tenant_id
                    WHERE a.tenant_id = %s AND a.branch = %s AND a.subject = %s AND a.predicate = %s
                      AND a.valid_from <= %s AND (a.valid_to IS NULL OR a.valid_to > %s)
                      AND a.status IN ('active', 'superseded', 'contested')
                    ORDER BY a.valid_from ASC
                    """,
                    (db_tenant_id, branch, subject, predicate, moment, moment),
                )
                return [_row_to_assertion(row) for row in cur.fetchall()]

    #: explain["channels"] key names consumed by the shared pipeline.
    retrieval_explain_channel_keys: tuple[str, str, str] = (
        "postgres_dense",
        "postgres_lexical",
        "postgres_graph_ppr",
    )

    def retrieve(self, query: str, tenant_id: str, branch: str = "main", deep: bool = False, filt: dict[str, Any] | None = None) -> RetrievalResult:
        return run_retrieval_pipeline(
            self,
            query=query,
            tenant_id=tenant_id,
            branch=branch,
            deep=deep,
            filt=filt,
            policy=self.policy,
        )

    def set_calibration(self, calibration: CalibrationSet) -> None:
        db_tenant_id = _stable_uuid("tenant", calibration.tenant_id)
        self.ensure_tenant_and_branch(calibration.tenant_id, "main")
        with self.connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    INSERT INTO conformal_calibration(tenant_id, memory_type, scores, target_coverage, updated_at)
                    VALUES (%s, %s, %s, %s, now())
                    ON CONFLICT (tenant_id, memory_type)
                    DO UPDATE SET scores = EXCLUDED.scores,
                                  target_coverage = EXCLUDED.target_coverage,
                                  updated_at = now()
                    """,
                    (db_tenant_id, calibration.memory_type, list(calibration.scores), calibration.target_coverage),
                )
                self._audit(
                    cur,
                    db_tenant_id,
                    "engine",
                    "set_calibration",
                    None,
                    {"memory_type": calibration.memory_type, "scores": len(calibration.scores)},
                )

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
        canonical = canonical.strip() or "unknown-entity"
        incoming_access_policy = validate_access_policy(
            access_policy if access_policy is not None else {"tenant": tenant_id},
            tenant_id=tenant_id,
            location="entity.access_policy",
        )
        aliases = sorted({canonical, *([" ".join(alias.split())] if alias and alias.strip() else [])})
        db_tenant_id = _stable_uuid("tenant", tenant_id)
        self.ensure_tenant_and_branch(tenant_id, "main")
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                self._ensure_entity_registry_schema(cur)
                self._set_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    SELECT access_policy
                    FROM entities
                    WHERE tenant_id = %s AND canonical = %s
                    """,
                    (db_tenant_id, canonical),
                )
                existing = cur.fetchone()
                if existing is None:
                    effective_access_policy = incoming_access_policy
                else:
                    current_access_policy = validate_access_policy(
                        dict(existing["access_policy"] or {}),
                        tenant_id=tenant_id,
                        location="entity.access_policy",
                    )
                    effective_access_policy = (
                        merge_access_policies([current_access_policy, incoming_access_policy], tenant_id=tenant_id)
                        if access_policy is not None
                        else current_access_policy
                    )
                cur.execute(
                    """
                    INSERT INTO entities(
                      tenant_id, canonical, type, summary, source_evidence_cids,
                      access_policy, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (tenant_id, canonical)
                    DO UPDATE SET
                      type = COALESCE(NULLIF(entities.type, ''), EXCLUDED.type),
                      summary = COALESCE(EXCLUDED.summary, entities.summary),
                      source_evidence_cids = COALESCE((
                        SELECT array_agg(DISTINCT cid)
                        FROM unnest(entities.source_evidence_cids || EXCLUDED.source_evidence_cids) AS cid
                      ), '{}'::bytea[]),
                      access_policy = EXCLUDED.access_policy,
                      updated_at = now()
                    RETURNING id, canonical, type, summary, salience, source_evidence_cids, access_policy, updated_at
                    """,
                    (
                        db_tenant_id,
                        canonical,
                        entity_type,
                        summary,
                        _cid_list_to_bytes(source_evidence_cids or []),
                        self._jsonb(effective_access_policy),
                    ),
                )
                row = cur.fetchone()
                for alias_value in aliases:
                    cur.execute(
                        """
                        INSERT INTO entity_aliases(tenant_id, alias, entity_id)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (tenant_id, alias) DO UPDATE SET entity_id = EXCLUDED.entity_id
                        """,
                        (db_tenant_id, alias_value, row["id"]),
                    )
                self._audit(cur, db_tenant_id, "engine", "register_entity", str(row["id"]), {"canonical": canonical})
        return {
            "id": str(row["id"]),
            "tenant_id": tenant_id,
            "canonical": row["canonical"],
            "type": row["type"],
            "summary": row["summary"],
            "salience": float(row["salience"]),
            "aliases": aliases,
            "source_evidence_cids": _bytes_list_to_cids(row["source_evidence_cids"]),
            "access_policy": dict(row["access_policy"] or {}),
            "updated_at": dt_to_json(row["updated_at"]),
        }

    def _calibration_for(self, tenant_id: str, memory_type: str) -> CalibrationSet | None:
        db_tenant_id = _stable_uuid("tenant", tenant_id)
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                self._set_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    SELECT memory_type, scores, target_coverage
                    FROM conformal_calibration
                    WHERE tenant_id = %s AND memory_type = %s
                    """,
                    (db_tenant_id, memory_type),
                )
                row = cur.fetchone()
        if not row:
            return None
        return CalibrationSet(
            tenant_id=tenant_id,
            memory_type=str(row["memory_type"]),
            scores=[float(score) for score in row["scores"]],
            target_coverage=float(row["target_coverage"]),
        )

    @staticmethod
    def _calibration_explain(calibration: CalibrationSet | None, threshold: float) -> dict[str, Any]:
        if calibration is None:
            return {"source": "policy", "memory_type": "fact", "threshold": threshold}
        return {
            "source": "conformal",
            "memory_type": calibration.memory_type,
            "threshold": threshold,
            "target_coverage": calibration.target_coverage,
            "scores": len(calibration.scores),
        }

    def _record_retrieval_access(self, hits: list[Hit]) -> dict[str, int]:
        ids_by_scope: dict[tuple[str, str], list[UUID]] = defaultdict(list)
        evidence_by_scope: dict[tuple[str, str], set[bytes]] = defaultdict(set)
        for hit in hits:
            if hit.kind == "evidence" and hit.id:
                cid_bytes = _cid_bytes_or_none(hit.id)
                if cid_bytes is not None:
                    evidence_by_scope[(hit.tenant_id, hit.branch)].add(cid_bytes)
            for cid in hit.provenance:
                cid_bytes = _cid_bytes_or_none(str(cid)) if cid else None
                if cid_bytes is not None:
                    evidence_by_scope[(hit.tenant_id, hit.branch)].add(cid_bytes)
            if hit.kind == "assertion":
                assertion_id = _uuid_or_none(hit.id)
                if assertion_id:
                    ids_by_scope[(hit.tenant_id, hit.branch)].append(assertion_id)
        if not ids_by_scope and not evidence_by_scope:
            return {"assertions": 0, "evidence": 0}
        touched_assertions = 0
        touched_evidence = 0
        with self.connect() as conn:
            with conn.cursor() as cur:
                for (tenant_id, branch), assertion_ids in ids_by_scope.items():
                    db_tenant_id = _stable_uuid("tenant", tenant_id)
                    self._set_tenant(cur, db_tenant_id)
                    cur.execute(
                        """
                        UPDATE assertions
                        SET last_accessed = now(), access_count = access_count + 1
                        WHERE tenant_id = %s AND branch = %s AND id = ANY(%s::uuid[])
                        """,
                        (db_tenant_id, branch, [str(item) for item in assertion_ids]),
                    )
                    touched_assertions += max(cur.rowcount or 0, 0)
                for (tenant_id, branch), evidence_cids in evidence_by_scope.items():
                    if not evidence_cids:
                        continue
                    db_tenant_id = _stable_uuid("tenant", tenant_id)
                    self._set_tenant(cur, db_tenant_id)
                    cur.execute(
                        """
                        SELECT cid, metadata
                        FROM evidence
                        WHERE tenant_id = %s AND branch = %s AND cid = ANY(%s::bytea[])
                        """,
                        (db_tenant_id, branch, list(evidence_cids)),
                    )
                    rows = cur.fetchall()
                    for cid_bytes, metadata_raw in rows:
                        metadata = dict(metadata_raw or {})
                        lifecycle = metadata.get("lifecycle")
                        lifecycle = dict(lifecycle) if isinstance(lifecycle, dict) else {}
                        try:
                            access_count = int(lifecycle.get("access_count", 0))
                        except (TypeError, ValueError):
                            access_count = 0
                        lifecycle["access_count"] = access_count + 1
                        lifecycle["last_accessed"] = utc_now().isoformat()
                        try:
                            salience = float(lifecycle.get("salience", 0.5))
                        except (TypeError, ValueError):
                            salience = 0.5
                        lifecycle["salience"] = min(1.0, max(0.0, salience) + 0.05)
                        metadata["lifecycle"] = lifecycle
                        cur.execute(
                            """
                            UPDATE evidence
                            SET metadata = %s
                            WHERE tenant_id = %s AND branch = %s AND cid = %s
                            """,
                            (self._jsonb(metadata), db_tenant_id, branch, cid_bytes),
                        )
                        touched_evidence += max(cur.rowcount or 0, 0)
        return {"assertions": touched_assertions, "evidence": touched_evidence}

    @staticmethod
    def _normalise_reality_class(value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().lower().replace("-", "_")
        aliases = {
            "grounded": "grounded",
            "evidence_grounded": "grounded",
            "external": "externally_suggested",
            "external_grounded": "grounded",
            "observed": "grounded",
            "user_grounded": "grounded",
            "self_generated": "self_generated",
            "self": "self_generated",
            "generated": "self_generated",
            "assistant_generated": "self_generated",
            "simulation": "simulated",
            "simulated": "simulated",
            "externally_suggested": "externally_suggested",
            "suggested": "externally_suggested",
            "untrusted_suggestion": "externally_suggested",
        }
        return aliases.get(normalized)

    @classmethod
    def _classify_evidence_reality(cls, ev: Evidence) -> str:
        explicit = cls._normalise_reality_class(ev.metadata.get("reality_class"))
        source_type = ev.source_type.lower()
        actor = ev.actor.lower()
        if any(marker in source_type for marker in ("simulation", "synthetic", "generated", "hypothesis")):
            base_class = "simulated"
        elif any(marker in source_type for marker in ("summary", "trace", "analysis", "consolidation")):
            base_class = "self_generated"
        elif actor == "assistant":
            base_class = "self_generated"
        elif actor in {"system", "tool"} and any(
            marker in source_type for marker in ("scratchpad", "workspace", "thought", "reflection")
        ):
            base_class = "self_generated"
        elif actor == "external" or ev.trust_tier >= int(TrustTier.LOW):
            base_class = "externally_suggested"
        else:
            base_class = "grounded"
        if explicit == "grounded" and base_class != "grounded":
            return "unknown"
        return explicit or base_class

    @classmethod
    def _classify_evidence_row_reality(cls, row: dict[str, Any], metadata: dict[str, Any]) -> str:
        explicit = cls._normalise_reality_class(metadata.get("reality_class"))
        source_type = str(row.get("source_type") or "").lower()
        actor = str(row.get("actor") or "").lower()
        trust_tier = int(row.get("trust_tier") or 0)
        if any(marker in source_type for marker in ("simulation", "synthetic", "generated", "hypothesis")):
            base_class = "simulated"
        elif any(marker in source_type for marker in ("summary", "trace", "analysis", "consolidation")):
            base_class = "self_generated"
        elif actor == "assistant":
            base_class = "self_generated"
        elif actor in {"system", "tool"} and any(
            marker in source_type for marker in ("scratchpad", "workspace", "thought", "reflection")
        ):
            base_class = "self_generated"
        elif actor == "external" or trust_tier >= int(TrustTier.LOW):
            base_class = "externally_suggested"
        else:
            base_class = "grounded"
        if explicit == "grounded" and base_class != "grounded":
            return "unknown"
        return explicit or base_class

    @staticmethod
    def _hit_source_evidence_cids(hit: Hit) -> list[str]:
        raw = hit.metadata.get("source_evidence_cids")
        if isinstance(raw, list | tuple):
            return [str(cid) for cid in raw if str(cid)]
        if isinstance(raw, str) and raw:
            return [raw]
        return [str(cid) for cid in hit.provenance if str(cid)]

    def _filter_graph_adapter_hits(
        self,
        hits: list[Hit],
        *,
        db_tenant_id: str,
        branch: str,
        include_quarantined: bool,
        max_trust: int,
        max_sensitivity: int,
        access_context: dict[str, Any] | None,
    ) -> list[Hit]:
        relation_source_cids: set[str] = set()
        source_cids_by_hit: dict[str, list[str]] = {}
        for hit in hits:
            if hit.kind != "relation":
                continue
            source_cids = self._hit_source_evidence_cids(hit)
            source_cids_by_hit[hit.id] = source_cids
            relation_source_cids.update(source_cids)

        evidence_by_cid: dict[str, dict[str, Any]] = {}
        if relation_source_cids:
            source_cid_bytes = [
                cid_bytes
                for cid in sorted(relation_source_cids)
                if (cid_bytes := _cid_bytes_or_none(cid)) is not None
            ]
            try:
                with self.connect() as conn:
                    with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                        self._set_tenant(cur, db_tenant_id)
                        cur.execute(
                            """
                            SELECT cid, trust_tier, sensitivity, access_policy, metadata, erased, source_type, actor
                            FROM evidence
                            WHERE tenant_id = %s AND branch = %s AND cid = ANY(%s::bytea[])
                            """,
                            (db_tenant_id, branch, source_cid_bytes),
                        )
                        evidence_by_cid = {_bytes_to_cid(row["cid"]): dict(row) for row in cur.fetchall()}
            except PostgresUnavailableError:
                evidence_by_cid = {}
            except self._psycopg.Error:
                evidence_by_cid = {}

        filtered: list[Hit] = []
        for hit in hits:
            if hit.kind != "relation":
                continue
            source_cids = source_cids_by_hit.get(hit.id, [])
            source_cid_bytes = [
                cid_bytes for cid in source_cids if (cid_bytes := _cid_bytes_or_none(cid)) is not None
            ]
            security = self._relation_hit_security_from_rows(
                {"source_evidence_cids": source_cid_bytes},
                evidence_by_cid,
                include_quarantined=include_quarantined,
                max_trust=max_trust,
                max_sensitivity=max_sensitivity,
                access_context=access_context,
            )
            if security is None:
                continue
            hit.trust_tier = int(security["trust_tier"])
            hit.sensitivity = int(security["sensitivity"])
            hit.provenance = list(source_cids)
            hit.metadata = {
                **hit.metadata,
                "source_evidence_cids": list(source_cids),
                "source_evidence_status": security["source_evidence_status"],
                "source_evidence_security": security["source_evidence_security"],
                "independent_corroboration": security["independent_corroboration"],
                "reality_class": security["reality_class"],
            }
            filtered.append(hit)
        return filtered

    def _relation_hit_security_from_rows(
        self,
        relation: dict[str, Any],
        evidence_by_cid: dict[str, dict[str, Any]],
        *,
        include_quarantined: bool,
        max_trust: int,
        max_sensitivity: int,
        access_context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        source_cids = _bytes_list_to_cids(relation.get("source_evidence_cids"))
        if not source_cids:
            return None

        source_rows: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        for cid in source_cids:
            row = evidence_by_cid.get(cid)
            if row is None or bool(row.get("erased")):
                return None
            metadata = dict(row.get("metadata") or {})
            if not include_quarantined and metadata.get("quarantine_reason"):
                return None
            if is_retired_summary_metadata(metadata):
                return None
            decision = may_read_item(
                item_tenant_id=str(access_context.get("tenant_id") if access_context else ""),
                sensitivity=int(row.get("sensitivity") or 0),
                access_policy=dict(row.get("access_policy") or {}),
                context=access_context or {},
                policy_max_sensitivity=self.policy.max_sensitivity,
                erased=bool(row.get("erased")),
            )
            if not decision.allowed:
                return None
            source_rows.append((cid, row, metadata))

        trust_tier = max(int(row.get("trust_tier") or 0) for _, row, _ in source_rows)
        sensitivity = max(int(row.get("sensitivity") or 0) for _, row, _ in source_rows)
        if trust_tier > max_trust or sensitivity > max_sensitivity:
            return None

        reality_classes = [self._classify_evidence_row_reality(row, metadata) for _, row, metadata in source_rows]
        corroboration = self._independent_corroboration_report_from_rows(
            [row for _, row, _ in source_rows],
            missing_cids=[],
        )
        return {
            "trust_tier": trust_tier,
            "sensitivity": sensitivity,
            "reality_class": self._aggregate_reality_classes(reality_classes),
            "source_evidence_status": "source_evidence_visible",
            "independent_corroboration": corroboration,
            "source_evidence_security": [
                {
                    "cid": cid,
                    "trust_tier": int(row.get("trust_tier") or 0),
                    "sensitivity": int(row.get("sensitivity") or 0),
                    "reality_class": self._classify_evidence_row_reality(row, metadata),
                    "access_policy_enforced": True,
                }
                for cid, row, metadata in source_rows
            ],
        }

    def _standing_signals_for_hit(self, hit: Hit, reality_class: str) -> dict[str, Any]:
        activation = hit.metadata.get("activation") if isinstance(hit.metadata, dict) else {}
        lifecycle = hit.metadata.get("lifecycle") if isinstance(hit.metadata, dict) else {}
        lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
        earned_autonomy = hit.metadata.get("earned_autonomy") if isinstance(hit.metadata, dict) else {}
        earned_autonomy = earned_autonomy if isinstance(earned_autonomy, dict) else {}
        source_cids = self._hit_source_evidence_cids(hit)
        if hit.kind == "evidence" and hit.id:
            source_cids = sorted(set(source_cids + [hit.id]))
        corroboration = hit.metadata.get("independent_corroboration") if isinstance(hit.metadata, dict) else None
        if not isinstance(corroboration, dict):
            try:
                with self.connect() as conn:
                    with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                        db_tenant_id = _stable_uuid("tenant", hit.tenant_id)
                        self._set_tenant(cur, db_tenant_id)
                        corroboration = self._independent_corroboration_report(
                            cur,
                            tenant_id=hit.tenant_id,
                            branch=hit.branch,
                            db_tenant_id=db_tenant_id,
                            source_evidence_cids=source_cids,
                        )
            except Exception:
                corroboration = self._fallback_independent_corroboration_report(
                    hit,
                    reality_class=reality_class,
                    source_evidence_cids=source_cids,
                )
        return {
            "reality_class": reality_class,
            "trust_tier": hit.trust_tier,
            "calibrated_confidence": hit.metadata.get("confidence", 0.0),
            "corroboration_count": len(source_cids),
            "independent_corroboration_count": corroboration["independent_corroboration_count"],
            "independent_corroboration_weight": corroboration["independent_corroboration_weight"],
            "self_generated_corroboration_count": corroboration["self_generated_corroboration_count"],
            "rejected_corroboration_count": corroboration["rejected_corroboration_count"],
            "contradiction_pressure": 1.0 if hit.metadata.get("status") == "contested" else 0.0,
            "groundedness_decay": lifecycle.get("decay", lifecycle.get("groundedness_decay", 0.0)),
            "activation": activation.get("score") if isinstance(activation, dict) else 0.0,
            "lifecycle_salience": lifecycle.get("salience", 0.0),
            "birth_groundedness": earned_autonomy.get(
                "birth_groundedness",
                hit.metadata.get("birth_groundedness") if isinstance(hit.metadata, dict) else None,
            ),
        }

    @staticmethod
    def _fallback_independent_corroboration_report(
        hit: Hit,
        *,
        reality_class: str,
        source_evidence_cids: list[str],
    ) -> dict[str, Any]:
        source_cids = sorted({str(item) for item in source_evidence_cids if item})
        if reality_class == "grounded":
            weight = trust_weight(int(hit.trust_tier))
            accepted = [
                {
                    "cid": cid,
                    "root": cid,
                    "trust_tier": int(hit.trust_tier),
                    "weight": round(weight, 6),
                    "source": "metadata_fallback",
                }
                for cid in source_cids
            ]
            return {
                "independent_corroboration_count": len(accepted),
                "independent_corroboration_weight": round(min(weight * len(accepted), 5.0) / 5.0, 6),
                "self_generated_corroboration_count": 0,
                "rejected_corroboration_count": 0,
                "accepted_corroborators": accepted,
                "rejected_corroborators": [],
            }
        rejected = [
            {"cid": cid, "reason": f"not_grounded:{reality_class}", "reality_class": reality_class}
            for cid in source_cids
        ]
        return {
            "independent_corroboration_count": 0,
            "independent_corroboration_weight": 0.0,
            "self_generated_corroboration_count": len(source_cids) if reality_class in {"self_generated", "simulated"} else 0,
            "rejected_corroboration_count": len(rejected),
            "accepted_corroborators": [],
            "rejected_corroborators": rejected,
        }

    def _independent_corroboration_report(
        self,
        cur: Any,
        *,
        tenant_id: str,
        branch: str,
        db_tenant_id: str,
        source_evidence_cids: list[str],
    ) -> dict[str, Any]:
        _ = tenant_id
        source_cids = sorted({str(item) for item in source_evidence_cids if item})
        if source_cids:
            cur.execute(
                """
                SELECT cid, actor, source_type, source_identity, content_pointer,
                  metadata, trust_tier, erased, capability_tags
                FROM evidence
                WHERE tenant_id = %s AND branch = %s AND cid = ANY(%s)
                """,
                (db_tenant_id, branch, _cid_list_to_bytes(source_cids)),
            )
            rows = list(cur.fetchall())
        else:
            rows = []
        found = {_bytes_to_cid(row["cid"]) for row in rows}
        missing = [cid for cid in source_cids if cid not in found]
        return self._independent_corroboration_report_from_rows(rows, missing_cids=missing)

    def _independent_corroboration_report_from_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        missing_cids: list[str],
    ) -> dict[str, Any]:
        roots: set[str] = set()
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        self_generated_count = 0
        trust_sum = 0.0
        for row in rows:
            cid = _bytes_to_cid(row["cid"]) if row.get("cid") is not None else ""
            metadata = dict(row.get("metadata") or {})
            reason = None
            if bool(row.get("erased")):
                reason = "erased"
            elif metadata.get("quarantine_reason"):
                reason = "quarantined"
            elif is_retired_summary_metadata(metadata):
                reason = "retired"
            elif is_write_tainted(list(row.get("capability_tags") or [])):
                reason = "sanitized_data_only"
            reality_class = self._classify_evidence_row_reality(row, metadata)
            if reason is None and reality_class != "grounded":
                reason = f"not_grounded:{reality_class}"
                if reality_class in {"self_generated", "simulated"}:
                    self_generated_count += 1
            if reason is None and self._has_self_generated_ancestor(metadata):
                reason = "shares_self_generated_ancestor"
            root = self._independent_source_key(row, cid)
            if reason is None and root in roots:
                reason = "duplicate_source_root"
            if reason is not None:
                rejected.append({"cid": cid, "reason": reason, "reality_class": reality_class})
                continue
            roots.add(root)
            trust_tier = int(row.get("trust_tier") or 0)
            weight = trust_weight(trust_tier)
            trust_sum += weight
            accepted.append(
                {
                    "cid": cid,
                    "root": root,
                    "trust_tier": trust_tier,
                    "weight": round(weight, 6),
                }
            )
        for cid in missing_cids:
            rejected.append({"cid": cid, "reason": "missing", "reality_class": "unknown"})
        return {
            "independent_corroboration_count": len(accepted),
            "independent_corroboration_weight": round(min(trust_sum, 5.0) / 5.0, 6),
            "self_generated_corroboration_count": self_generated_count,
            "rejected_corroboration_count": len(rejected),
            "accepted_corroborators": accepted,
            "rejected_corroborators": rejected,
        }

    @staticmethod
    def _has_self_generated_ancestor(metadata: dict[str, Any]) -> bool:
        keys = (
            "self_generated_ancestor_cids",
            "self_generated_ancestors",
            "derived_from_self_cids",
            "source_self_cids",
        )
        for key in keys:
            value = metadata.get(key)
            if isinstance(value, list | tuple | set) and any(str(item) for item in value):
                return True
            if isinstance(value, str) and value.strip():
                return True
        provenance = metadata.get("provenance")
        if isinstance(provenance, dict):
            return bool(provenance.get("self_generated") or provenance.get("self_generated_ancestor"))
        return False

    @staticmethod
    def _independent_source_key(row: dict[str, Any], cid: str) -> str:
        identity = row.get("source_identity") or row.get("content_pointer") or cid
        return f"{row.get('source_type') or 'evidence'}:{identity}"

    def _apply_standing_scores(self, hits: list[Hit]) -> list[Hit]:
        weighted: list[Hit] = []
        for hit in hits:
            reality_class = self._normalise_reality_class(hit.metadata.get("reality_class")) or "unknown"
            score = standing(self._standing_signals_for_hit(hit, reality_class))
            multiplier = 0.75 + 0.20 * score.groundedness + 0.05 * score.salience
            source_cids = self._hit_source_evidence_cids(hit)
            if hit.kind == "evidence" and hit.id:
                source_cids = sorted(set(source_cids + [hit.id]))
            metadata = {
                **hit.metadata,
                "standing": score.to_dict(),
                "standing_rank_multiplier": round(multiplier, 6),
                "standing_observability": standing_observability_record(
                    target_id=hit.id,
                    kind=hit.kind,
                    tenant_id=hit.tenant_id,
                    branch=hit.branch,
                    source_evidence_cids=source_cids,
                    score=score,
                    surface="retrieval.rank",
                ),
            }
            weighted.append(
                Hit(
                    id=hit.id,
                    kind=hit.kind,
                    tenant_id=hit.tenant_id,
                    branch=hit.branch,
                    text=hit.text,
                    score=max(hit.score, 0.0) * multiplier,
                    channel=hit.channel,
                    provenance=list(hit.provenance),
                    trust_tier=hit.trust_tier,
                    sensitivity=hit.sensitivity,
                    metadata=metadata,
                )
            )
        return sorted(weighted, key=lambda item: item.score, reverse=True)

    @staticmethod
    def _aggregate_reality_classes(classes: list[str]) -> str:
        normalized = [item for item in classes if item]
        if not normalized:
            return "unknown"
        if all(item == "grounded" for item in normalized):
            return "grounded"
        if "self_generated" in normalized:
            return "self_generated"
        if "simulated" in normalized:
            return "simulated"
        if "externally_suggested" in normalized:
            return "externally_suggested"
        return "unknown"

    def _reality_monitoring_report(self, hits: list[Hit]) -> dict[str, Any]:
        risky = {"self_generated", "simulated", "externally_suggested"}
        ungrounded = risky | {"unknown"}
        counts: dict[str, int] = {}
        grounded_cids: set[str] = set()
        risky_hit_ids: list[str] = []
        shadow_tags: dict[str, dict[str, Any]] = {}
        standing_rows: list[dict[str, Any]] = []
        monitor = RealityMonitor()
        for index, hit in enumerate(hits):
            reality_class = self._normalise_reality_class(hit.metadata.get("reality_class")) or "unknown"
            counts[reality_class] = counts.get(reality_class, 0) + 1
            tag = self._shadow_reality_monitor_tag(monitor, hit)
            shadow_tags[hit.id or f"{hit.kind}:{index}"] = tag
            if reality_class == "grounded":
                grounded_cids.update(str(cid) for cid in hit.provenance if cid)
                if hit.kind == "evidence" and hit.id:
                    grounded_cids.add(hit.id)
            elif reality_class in ungrounded:
                risky_hit_ids.append(hit.id)
            score = standing(self._standing_signals_for_hit(hit, reality_class))
            standing_rows.append(
                {
                    "hit_id": hit.id or f"{hit.kind}:{index}",
                    "kind": hit.kind,
                    "authority": score.authority,
                    "groundedness": score.groundedness,
                    "salience": score.salience,
                    "standing_fn_version": score.standing_fn_version,
                    "reality_class": reality_class,
                    "explain": score.explain,
                }
            )
        hit_count = len(hits)
        grounded = counts.get("grounded", 0)
        ungrounded_only = hit_count > 0 and grounded == 0 and any(counts.get(item, 0) for item in ungrounded)
        standing_report = standing_abstention_report(standing_rows)
        standing_report["p1_mirror"] = {
            "boolean_ungrounded_only": ungrounded_only,
            "standing_ungrounded_only": standing_report["abstention_gate"]["active"],
            "zero_divergence": standing_report["abstention_gate"]["active"] is ungrounded_only,
        }
        standing_report["legacy_reality_monitoring"] = {
            "ungrounded_only": ungrounded_only,
            "explain_only": True,
        }
        return {
            "applied": True,
            "classes": counts,
            "grounded_hit_count": grounded,
            "grounded_source_count": len(grounded_cids),
            "risky_hit_ids": risky_hit_ids,
            "ungrounded_only": ungrounded_only,
            "shadow_only": False,
            "critical_path": True,
            "abstention_gate": {
                "critical_path": True,
                "shadow_only": False,
                "trigger": "ungrounded_only",
                "active": ungrounded_only,
            },
            "shadow_source": "RealityMonitor",
            "shadow_tags_shadow_only": True,
            "shadow_tags_critical_path": False,
            "shadow_tags": shadow_tags,
            "standing": standing_report,
        }

    @staticmethod
    def _shadow_reality_monitor_tag(monitor: RealityMonitor, hit: Hit) -> dict[str, Any]:
        metadata = hit.metadata if isinstance(hit.metadata, dict) else {}
        tag = monitor.tag(
            source_type=str(metadata.get("source_type") or hit.kind),
            actor=str(metadata.get("actor") or ""),
            trust_tier=int(hit.trust_tier),
            metadata={"reality_class": metadata.get("reality_class")},
            provenance_count=len(hit.provenance),
        )
        explicit_class = str(metadata.get("reality_class") or "").strip().lower().replace("-", "_")
        source_type = str(metadata.get("source_type") or hit.kind).strip().lower()
        preserve_simulated = explicit_class in {"simulated", "simulation"} and (
            hit.kind == "assertion"
            or any(marker in source_type for marker in ("simulation", "synthetic", "generated", "hypothesis"))
        )
        reality_class = "simulated" if preserve_simulated else tag.reality_class
        return {
            "reality_class": reality_class,
            "confidence": tag.confidence,
            "calibrated": tag.calibrated,
            "signals": tag.signals,
        }

    @staticmethod
    def _merge_schema_fast_path_reports(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
        boosted = sorted(set(first.get("boosted_hit_ids") or []) | set(second.get("boosted_hit_ids") or []))
        reasons: dict[str, Any] = {}
        if isinstance(first.get("reasons"), dict):
            reasons.update(first["reasons"])
        if isinstance(second.get("reasons"), dict):
            reasons.update(second["reasons"])
        return {
            "applied": bool(first.get("applied")) or bool(second.get("applied")),
            "boost": second.get("boost", first.get("boost")),
            "boosted_hit_ids": boosted,
            "reasons": reasons,
            "passes": [first, second],
        }

    def deep_search(self, query: str, tenant_id: str, branch: str = "main", filt: dict[str, Any] | None = None) -> RetrievalResult:
        return self.retrieve(query=query, tenant_id=tenant_id, branch=branch, deep=True, filt=filt)

    def explain(self, query: str, tenant_id: str, branch: str = "main") -> dict[str, Any]:
        return self.deep_search(query, tenant_id, branch=branch).to_dict()

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

    def forget(
        self,
        tenant_id: str,
        cid: str,
        branch: str = "main",
        requested_by: str = "user",
        erasure_mode: ErasureMode | str = ErasureMode.TOMBSTONE_RECOMPUTE,
    ) -> dict[str, Any]:
        mode = ErasureMode(erasure_mode)
        db_tenant_id = _stable_uuid("tenant", tenant_id)
        cid_bytes = _cid_to_bytes(cid)
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
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                self._set_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    SELECT cid, source_type, trust_tier, capability_tags, metadata, user_id
                    FROM evidence
                    WHERE tenant_id = %s AND branch = %s AND cid = %s
                    """,
                    (db_tenant_id, branch, cid_bytes),
                )
                evidence_row = cur.fetchone()
                if not evidence_row:
                    return {"erased": False, "reason": "evidence_not_found", "cid": cid, "erasure_mode": mode.value}
                cur.execute(
                    """
                    SELECT cid, metadata, source_type
                    FROM evidence
                    WHERE tenant_id = %s AND branch = %s
                      AND erased = false
                      AND cid <> %s
                    """,
                    (db_tenant_id, branch, cid_bytes),
                )
                candidate_rows = list(cur.fetchall())
                candidates = [(bytes(row["cid"]), dict(row["metadata"] or {})) for row in candidate_rows]
                cascade_metadata: dict[str, dict[str, Any]] = {
                    cid: {**dict(evidence_row.get("metadata") or {}), "source_type": evidence_row["source_type"]}
                }
                for row in candidate_rows:
                    row_cid = _bytes_to_cid(row["cid"])
                    cascade_metadata[row_cid] = {
                        **dict(row.get("metadata") or {}),
                        "source_type": row.get("source_type") or "",
                    }
                legal_blind = mode is ErasureMode.HARD_DELETE_LEGAL and requested_by == "legal"
                if legal_blind:
                    derived_cid_bytes, derived_cids, retained_metadata = _derived_evidence_forget_plan(
                        cid,
                        candidates,
                        legal_blind=True,
                    )
                else:
                    derived_cid_bytes, derived_cids, retained_metadata = _derived_evidence_forget_plan(cid, candidates)
                affected_cids = {cid, *derived_cids}
                affected_cid_bytes = [cid_bytes, *derived_cid_bytes]
                propagated["erased_derived_evidence"] = derived_cids
                propagated["retained_derived_evidence"] = sorted(
                    _bytes_to_cid(item) for item in retained_metadata
                )
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
                    cur.execute(
                        """
                        SELECT id, source_evidence_cids
                        FROM assertions
                        WHERE tenant_id = %s
                          AND branch = %s
                          AND status = 'active'
                          AND source_evidence_cids && %s
                        """,
                        (db_tenant_id, branch, affected_cid_bytes),
                    )
                    blocking: list[str] = []
                    for row in cur.fetchall():
                        sources = set(_bytes_list_to_cids(row["source_evidence_cids"]))
                        if sources and sources <= affected_cids and len(sources) < minimum:
                            blocking.append(str(row["id"]))
                    if blocking:
                        return {
                            "erased": False,
                            "reason": "min_corroboration_for_delete",
                            "cid": cid,
                            "erasure_mode": mode.value,
                            "min_corroboration_for_delete": minimum,
                            "blocking_assertions": blocking,
                        }
                if mode is ErasureMode.HARD_DELETE_LEGAL:
                    cur.execute(
                        """
                        DELETE FROM evidence
                        WHERE tenant_id = %s AND branch = %s AND cid = ANY(%s)
                        RETURNING cid
                        """,
                        (db_tenant_id, branch, affected_cid_bytes),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE evidence
                        SET content = '', erased = true
                        WHERE tenant_id = %s AND branch = %s AND cid = ANY(%s)
                        RETURNING cid
                        """,
                        (db_tenant_id, branch, affected_cid_bytes),
                    )
                for retained_bytes, metadata in retained_metadata.items():
                    cur.execute(
                        """
                        UPDATE evidence
                        SET metadata = %s
                        WHERE tenant_id = %s AND branch = %s AND cid = %s
                        """,
                        (self._jsonb(metadata), db_tenant_id, branch, retained_bytes),
                    )
                cur.execute(
                    """
                    SELECT id, source_evidence_cids
                    FROM assertions
                    WHERE tenant_id = %s AND branch = %s AND source_evidence_cids && %s
                    """,
                    (db_tenant_id, branch, affected_cid_bytes),
                )
                for row in cur.fetchall():
                    sources = [item for item in _bytes_list_to_cids(row["source_evidence_cids"]) if item not in affected_cids]
                    if sources:
                        cur.execute(
                            "UPDATE assertions SET source_evidence_cids = %s WHERE id = %s",
                            (_cid_list_to_bytes(sources), row["id"]),
                        )
                        propagated["trimmed_assertions"].append(str(row["id"]))
                    else:
                        cur.execute(
                            "UPDATE assertions SET status = 'retracted', expired_at = now(), source_evidence_cids = %s WHERE id = %s",
                            (_cid_list_to_bytes([]), row["id"]),
                        )
                        propagated["retracted_assertions"].append(str(row["id"]))
                cur.execute(
                    """
                    SELECT id, source_evidence_cids
                    FROM preferences
                    WHERE tenant_id = %s AND source_evidence_cids && %s
                    """,
                    (db_tenant_id, affected_cid_bytes),
                )
                for row in cur.fetchall():
                    sources = [item for item in _bytes_list_to_cids(row["source_evidence_cids"]) if item not in affected_cids]
                    if sources:
                        cur.execute(
                            "UPDATE preferences SET source_evidence_cids = %s WHERE id = %s",
                            (_cid_list_to_bytes(sources), row["id"]),
                        )
                        propagated["trimmed_preferences"].append(str(row["id"]))
                    else:
                        cur.execute(
                            "UPDATE preferences SET status = 'retracted', valid_to = now(), source_evidence_cids = %s WHERE id = %s",
                            (_cid_list_to_bytes([]), row["id"]),
                        )
                        propagated["retracted_preferences"].append(str(row["id"]))
                cur.execute(
                    """
                    SELECT id, source_evidence_cids
                    FROM relations
                    WHERE tenant_id = %s AND branch = %s AND source_evidence_cids && %s
                    """,
                    (db_tenant_id, branch, affected_cid_bytes),
                )
                for row in cur.fetchall():
                    sources = [item for item in _bytes_list_to_cids(row["source_evidence_cids"]) if item not in affected_cids]
                    if sources:
                        cur.execute(
                            "UPDATE relations SET source_evidence_cids = %s WHERE id = %s",
                            (_cid_list_to_bytes(sources), row["id"]),
                        )
                        propagated["trimmed_relations"].append(str(row["id"]))
                    else:
                        cur.execute(
                            """
                            UPDATE relations
                            SET valid_to = GREATEST(clock_timestamp(), valid_from + interval '1 microsecond'),
                                source_evidence_cids = %s
                            WHERE id = %s
                            """,
                            (_cid_list_to_bytes([]), row["id"]),
                        )
                        propagated["expired_relations"].append(str(row["id"]))
                self._ensure_entity_registry_schema(cur)
                cur.execute(
                    """
                    SELECT id, canonical, source_evidence_cids
                    FROM entities
                    WHERE tenant_id = %s AND source_evidence_cids && %s
                    """,
                    (db_tenant_id, affected_cid_bytes),
                )
                for row in cur.fetchall():
                    sources = [item for item in _bytes_list_to_cids(row["source_evidence_cids"]) if item not in affected_cids]
                    if sources:
                        cur.execute(
                            "UPDATE entities SET source_evidence_cids = %s, updated_at = now() WHERE id = %s",
                            (_cid_list_to_bytes(sources), row["id"]),
                        )
                        propagated["trimmed_entities"].append(row["canonical"])
                    else:
                        cur.execute("DELETE FROM entities WHERE id = %s", (row["id"],))
                        propagated["removed_entities"].append(row["canonical"])
                # Spec §7 privacy invariant 13: NO retained record for a hard delete
                # may carry the erased cid (a salted sha256 of the content, so
                # sha256(guess) could confirm it) — not the deletion_log evidence_cid,
                # not the provenance/standing-cascade refs inside `propagated`, and not
                # the audit target_id. Redact every retained copy with one per-erasure
                # placeholder map (stable within the record, non-recomputable). The
                # dict RETURNED to the caller keeps the real cids. tombstone_recompute
                # keeps the cid (the tombstone row lives in the ledger).
                if mode is ErasureMode.HARD_DELETE_LEGAL:
                    placeholder_map = build_erasure_placeholder_map({cid, *derived_cids}, tenant_id)
                    stored_propagated = redact_erased_cids(propagated, placeholder_map)
                    deletion_cid_value = bytes.fromhex(
                        erasure_deletion_record_id(cid, tenant_id, evidence_row.get("user_id") or "")
                    )
                    audit_target_id = placeholder_map[cid]
                else:
                    stored_propagated = propagated
                    deletion_cid_value = cid_bytes
                    audit_target_id = cid
                cur.execute(
                    """
                    INSERT INTO deletion_log(tenant_id, evidence_cid, requested_by, propagated)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        db_tenant_id,
                        deletion_cid_value,
                        requested_by,
                        self._jsonb({**stored_propagated, "erasure_mode": mode.value}),
                    ),
                )
                self._audit(
                    cur,
                    db_tenant_id,
                    requested_by,
                    "forget",
                    audit_target_id,
                    {**stored_propagated, "erasure_mode": mode.value, "source_type": evidence_row["source_type"]},
                    source=evidence_row["source_type"],
                    trust_tier=evidence_row["trust_tier"],
                    capability_tags=list(evidence_row["capability_tags"] or []),
                )
        return {"erased": True, "cid": cid, "erasure_mode": mode.value, "propagated": propagated}

    def export_tenant(self, tenant_id: str) -> dict[str, Any]:
        db_tenant_id = _stable_uuid("tenant", tenant_id)
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                self._set_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    SELECT e.*, t.name AS tenant_name
                    FROM evidence e
                    JOIN tenants t ON t.id = e.tenant_id
                    WHERE e.tenant_id = %s AND e.erased = false
                    """,
                    (db_tenant_id,),
                )
                evidence = [_row_to_evidence(row, _bytes_to_cid(row["cid"])).to_dict() for row in cur.fetchall()]
                cur.execute(
                    """
                    SELECT a.*, t.name AS tenant_name,
                           (
                             SELECT ev.metadata->>'_external_user_id'
                             FROM evidence ev
                             WHERE ev.tenant_id = a.tenant_id
                               AND ev.branch = a.branch
                               AND ev.cid = ANY(a.source_evidence_cids)
                             ORDER BY ev.created_at, ev.cid
                             LIMIT 1
                           ) AS external_user_id
                    FROM assertions a
                    JOIN tenants t ON t.id = a.tenant_id
                    WHERE a.tenant_id = %s
                    """,
                    (db_tenant_id,),
                )
                assertions = [_row_to_assertion(row).to_dict() for row in cur.fetchall()]
                cur.execute("SELECT * FROM relations WHERE tenant_id = %s", (db_tenant_id,))
                relations = [_row_to_relation(row, tenant_id).to_dict() for row in cur.fetchall()]
                cur.execute(
                    """
                    SELECT p.*, t.name AS tenant_name,
                           (
                             SELECT ev.metadata->>'_external_user_id'
                             FROM evidence ev
                             WHERE ev.tenant_id = p.tenant_id
                               AND ev.cid = ANY(p.source_evidence_cids)
                             ORDER BY ev.created_at, ev.cid
                             LIMIT 1
                           ) AS external_user_id
                    FROM preferences p
                    JOIN tenants t ON t.id = p.tenant_id
                    WHERE p.tenant_id = %s
                    """,
                    (db_tenant_id,),
                )
                preferences = [_row_to_preference(row, tenant_id).to_dict() for row in cur.fetchall()]
                cur.execute("SELECT * FROM justifications WHERE tenant_id = %s ORDER BY id", (db_tenant_id,))
                justifications = [
                    {
                        "tenant_id": tenant_id,
                        "assertion_id": str(row["assertion_id"]) if row["assertion_id"] else None,
                        "evidence_cids": _bytes_list_to_cids(row["evidence_cids"]),
                        "rule": row["rule"],
                        "dependency_ids": [str(item) for item in row["dependency_ids"]],
                        "kind": row["kind"],
                        "label": dict(row["label"] or {}),
                        "hypothesis_prob": row["hypothesis_prob"],
                        "id": str(row["id"]),
                    }
                    for row in cur.fetchall()
                ]
                cur.execute("SELECT * FROM contradictions WHERE tenant_id = %s ORDER BY detected_at, id", (db_tenant_id,))
                contradictions = [
                    {
                        "tenant_id": tenant_id,
                        "a": str(row["a"]),
                        "b": str(row["b"]),
                        "status": row["status"],
                        "resolution": row["resolution"],
                        "detected_at": dt_to_json(row["detected_at"]),
                        "id": str(row["id"]),
                    }
                    for row in cur.fetchall()
                ]
                cur.execute("SELECT * FROM audit_log WHERE tenant_id = %s", (db_tenant_id,))
                audit = [_row_to_audit_log(row) for row in cur.fetchall()]
                cur.execute("SELECT * FROM deletion_log WHERE tenant_id = %s", (db_tenant_id,))
                deletion = [_json_safe(dict(row)) for row in cur.fetchall()]
                cur.execute(
                    "SELECT frm, into_, report, at FROM merges WHERE tenant_id = %s ORDER BY at",
                    (db_tenant_id,),
                )
                merge_log = [
                    {
                        **dict(row["report"] or {}),
                        "from_branch": row["frm"],
                        "into_branch": row["into_"],
                        "merged_at": dt_to_json(row["at"]),
                    }
                    for row in cur.fetchall()
                ]
                cur.execute("SELECT * FROM conformal_calibration WHERE tenant_id = %s", (db_tenant_id,))
                calibrations = [
                    {
                        "tenant_id": tenant_id,
                        "memory_type": row["memory_type"],
                        "scores": [float(score) for score in row["scores"]],
                        "target_coverage": float(row["target_coverage"]),
                    }
                    for row in cur.fetchall()
                ]
                cur.execute(
                    """
                    SELECT e.*, COALESCE(array_agg(a.alias ORDER BY a.alias) FILTER (WHERE a.alias IS NOT NULL), '{}') AS aliases
                    FROM entities e
                    LEFT JOIN entity_aliases a ON a.tenant_id = e.tenant_id AND a.entity_id = e.id
                    WHERE e.tenant_id = %s
                    GROUP BY e.id
                    ORDER BY e.canonical
                    """,
                    (db_tenant_id,),
                )
                entities = [
                    {
                        "id": str(row["id"]),
                        "tenant_id": tenant_id,
                        "canonical": row["canonical"],
                        "type": row["type"],
                        "summary": row["summary"],
                        "salience": float(row["salience"]),
                        "aliases": sorted(row["aliases"]),
                        "source_evidence_cids": _bytes_list_to_cids(row["source_evidence_cids"]),
                        "access_policy": dict(row["access_policy"] or {}),
                        "updated_at": dt_to_json(row["updated_at"]),
                    }
                    for row in cur.fetchall()
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
            "audit_log": audit,
            "deletion_log": deletion,
            "merge_log": merge_log,
        }

    def export_tenant_filtered(self, tenant_id: str, access_context: dict[str, Any]) -> dict[str, Any]:
        return filter_export_for_context(
            self.export_tenant(tenant_id),
            {**dict(access_context or {}), "tenant_id": tenant_id},
            policy_max_sensitivity=self.policy.max_sensitivity,
        )

    def to_json(self) -> str:
        return json.dumps(self.export_all(), indent=2, sort_keys=True)

    def export_all(self) -> dict[str, Any]:
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                cur.execute("SELECT id, name FROM tenants ORDER BY name")
                tenant_rows = list(cur.fetchall())
                branches: list[dict[str, Any]] = []
                for tenant_row in tenant_rows:
                    self._set_tenant(cur, tenant_row["id"])
                    cur.execute(
                        """
                        SELECT name, from_branch, kind, head, created_at
                        FROM branches
                        WHERE tenant_id = %s
                        ORDER BY name
                        """,
                        (tenant_row["id"],),
                    )
                    branches.extend(
                        {
                            "tenant_id": tenant_row["name"],
                            "name": row["name"],
                            "from_branch": row["from_branch"],
                            "kind": row["kind"],
                            "head": _bytes_to_cid(row["head"]) if row["head"] else None,
                            "created_at": dt_to_json(row["created_at"]),
                        }
                        for row in cur.fetchall()
                    )
                merge_log: list[dict[str, Any]] = []
                for tenant_row in tenant_rows:
                    self._set_tenant(cur, tenant_row["id"])
                    cur.execute(
                        """
                        SELECT report
                        FROM merges
                        WHERE tenant_id = %s
                        ORDER BY id
                        """,
                        (tenant_row["id"],),
                    )
                    for row in cur.fetchall():
                        merge_log.append(dict(row["report"]))
        tenant_exports = [self.export_tenant(row["name"]) for row in tenant_rows]
        return {
            "policy": self.policy.to_dict(),
            "branches": branches,
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

    def branch(self, name: str, frm: str = "main", kind: str = "scratch", tenant_id: str | None = None) -> None:
        if name == frm:
            return
        if not tenant_id:
            raise ValueError("PostgresEngine.branch requires tenant_id")
        self.ensure_tenant_and_branch(tenant_id, frm)
        db_tenant_id = _stable_uuid("tenant", tenant_id)
        with self.connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur, db_tenant_id)
                self._ensure_evidence_vector_schema(cur)
                for db_tenant_id in [db_tenant_id]:
                    cur.execute(
                        """
                        INSERT INTO branches(tenant_id, name, from_branch, kind)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (tenant_id, name) DO NOTHING
                        RETURNING name
                        """,
                        (db_tenant_id, name, frm, kind),
                    )
                    if not cur.fetchone():
                        continue
                    cur.execute(
                        """
                        INSERT INTO evidence (
                          cid, branch, tenant_id, user_id, session_id, actor, source_type,
                          source_identity, content, content_pointer, modality, metadata,
                          trust_tier, capability_tags, sensitivity, signed_provenance,
                          access_policy, embedding, embedding_partition, erased, created_at
                        )
                        SELECT cid, %s, tenant_id, user_id, session_id, actor, source_type,
                          source_identity, content, content_pointer, modality, metadata,
                          trust_tier, capability_tags, sensitivity, signed_provenance,
                          access_policy, embedding, embedding_partition, erased, created_at
                        FROM evidence
                        WHERE tenant_id = %s AND branch = %s
                        ON CONFLICT (tenant_id, branch, cid) DO NOTHING
                        """,
                        (name, db_tenant_id, frm),
                    )
                    cur.execute(
                        """
                        INSERT INTO assertions (
                          id, tenant_id, user_id, branch, subject, predicate, object, scope,
                          confidence, calibration, valid_from, valid_to, transaction_time,
                          expired_at, justification_id, source_evidence_cids, status, version,
                          superseded_by, trust_tier, sensitivity, access_policy, embedding,
                          embedding_partition, lexeme, last_accessed, access_count
                        )
                        SELECT gen_random_uuid(), tenant_id, user_id, %s, subject, predicate,
                          object, scope, confidence, calibration, valid_from, valid_to,
                          transaction_time, expired_at, justification_id, source_evidence_cids,
                          status, version, superseded_by, trust_tier, sensitivity,
                          access_policy, embedding, embedding_partition, lexeme, last_accessed, access_count
                        FROM assertions
                        WHERE tenant_id = %s AND branch = %s
                        """,
                        (name, db_tenant_id, frm),
                    )
                    cur.execute(
                        """
                        INSERT INTO relations (
                          id, tenant_id, branch, source, predicate, target, confidence,
                          valid_from, valid_to, source_evidence_cids, access_policy
                        )
                        SELECT gen_random_uuid(), tenant_id, %s, source, predicate, target,
                          confidence, valid_from, valid_to, source_evidence_cids, access_policy
                        FROM relations
                        WHERE tenant_id = %s AND branch = %s
                        """,
                        (name, db_tenant_id, frm),
                    )

    def merge(self, frm: str, into: str = "main", tenant_id: str | None = None) -> MergeReport:
        if not tenant_id:
            raise ValueError("PostgresEngine.merge requires tenant_id")
        report = MergeReport(frm, into, 0, 0, 0, 0, [])
        db_tenant_id = _stable_uuid("tenant", tenant_id)
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                self._set_tenant(cur, db_tenant_id)
                for db_tenant_id in [db_tenant_id]:
                    cur.execute(
                        """
                        INSERT INTO branches(tenant_id, name, from_branch, kind)
                        VALUES (%s, %s, %s, 'protected')
                        ON CONFLICT (tenant_id, name) DO NOTHING
                        """,
                        (db_tenant_id, into, frm),
                    )
                    cur.execute(
                        """
                        INSERT INTO evidence (
                          cid, branch, tenant_id, user_id, session_id, actor, source_type,
                          source_identity, content, content_pointer, modality, metadata,
                          trust_tier, capability_tags, sensitivity, signed_provenance,
                          access_policy, embedding, embedding_partition, erased, created_at
                        )
                        SELECT cid, %s, tenant_id, user_id, session_id, actor, source_type,
                          source_identity, content, content_pointer, modality, metadata,
                          trust_tier, capability_tags, sensitivity, signed_provenance,
                          access_policy, embedding, embedding_partition, erased, created_at
                        FROM evidence
                        WHERE tenant_id = %s AND branch = %s
                        ON CONFLICT (tenant_id, branch, cid) DO NOTHING
                        """,
                        (into, db_tenant_id, frm),
                    )
                    report.evidence_added += cur.rowcount
                    cur.execute(
                        """
                        UPDATE assertions src
                        SET branch = %s, transaction_time = now()
                        WHERE tenant_id = %s AND branch = %s
                          AND NOT EXISTS (
                            SELECT 1 FROM assertions dst
                            WHERE dst.tenant_id = src.tenant_id AND dst.branch = %s
                              AND dst.subject = src.subject AND dst.predicate = src.predicate
                              AND dst.object = src.object AND dst.scope = src.scope
                              AND dst.status IN ('active', 'contested')
                          )
                        """,
                        (into, db_tenant_id, frm, into),
                    )
                    report.assertions_added += cur.rowcount
                    cur.execute(
                        """
                        UPDATE relations src
                        SET branch = %s
                        WHERE tenant_id = %s AND branch = %s
                          AND NOT EXISTS (
                            SELECT 1 FROM relations dst
                            WHERE dst.tenant_id = src.tenant_id AND dst.branch = %s
                              AND dst.source = src.source AND dst.predicate = src.predicate
                              AND dst.target = src.target
                          )
                        """,
                        (into, db_tenant_id, frm, into),
                    )
                    report.relations_added += cur.rowcount
                    cur.execute(
                        """
                        INSERT INTO merges(tenant_id, frm, into_, report)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (db_tenant_id, frm, into, self._jsonb(report.to_dict())),
                    )
        return report

    def discard(self, branch: str, tenant_id: str | None = None) -> None:
        if branch == "main":
            raise ValueError("main branch cannot be discarded")
        if not tenant_id:
            raise ValueError("PostgresEngine.discard requires tenant_id")
        db_tenant_id = _stable_uuid("tenant", tenant_id)
        with self.connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur, db_tenant_id)
                cur.execute("DELETE FROM relations WHERE tenant_id = %s AND branch = %s", (db_tenant_id, branch))
                cur.execute("DELETE FROM assertions WHERE tenant_id = %s AND branch = %s", (db_tenant_id, branch))
                cur.execute(
                    """
                    DELETE FROM justifications j
                    WHERE j.tenant_id = %s
                      AND (
                        NOT EXISTS (
                          SELECT 1 FROM assertions a
                          WHERE a.tenant_id = j.tenant_id AND a.id = j.assertion_id
                        )
                        OR EXISTS (
                          SELECT 1
                          FROM unnest(j.dependency_ids) AS dep(id)
                          WHERE NOT EXISTS (
                            SELECT 1 FROM assertions a
                            WHERE a.tenant_id = j.tenant_id AND a.id = dep.id
                          )
                        )
                      )
                    """,
                    (db_tenant_id,),
                )
                cur.execute(
                    """
                    DELETE FROM contradictions c
                    WHERE c.tenant_id = %s
                      AND (
                        NOT EXISTS (
                          SELECT 1 FROM assertions a
                          WHERE a.tenant_id = c.tenant_id AND a.id = c.a
                        )
                        OR NOT EXISTS (
                          SELECT 1 FROM assertions a
                          WHERE a.tenant_id = c.tenant_id AND a.id = c.b
                        )
                      )
                    """,
                    (db_tenant_id,),
                )
                cur.execute("DELETE FROM evidence WHERE tenant_id = %s AND branch = %s", (db_tenant_id, branch))
                cur.execute("DELETE FROM branches WHERE tenant_id = %s AND name = %s", (db_tenant_id, branch))

    def _local_rank(self, query: str, k: int, filt: dict[str, Any], channel: str) -> list[Hit]:
        tenant_id = filt["tenant_id"]
        db_tenant_id = _stable_uuid("tenant", tenant_id)
        branch = filt.get("branch", "main")
        include_quarantined = bool(filt.get("include_quarantined", False))
        default_max_trust = int(TrustTier.UNTRUSTED_EXTERNAL) if include_quarantined else self.policy.max_trust_tier
        max_trust = int(filt.get("max_trust_tier", filt.get("min_trust_tier", default_max_trust)))
        max_sensitivity = effective_max_sensitivity(filt, self.policy.max_sensitivity)
        candidates: list[Hit] = []
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                self._set_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    SELECT cid, tenant_id, branch, content, metadata, trust_tier, sensitivity, access_policy, actor, source_type
                    FROM evidence
                    WHERE tenant_id = %s AND branch = %s AND erased = false
                      AND trust_tier <= %s AND sensitivity <= %s
                      AND (%s OR NOT (metadata ? 'quarantine_reason'))
                      AND NOT (
                        metadata ? 'summary'
                        AND (
                          lower(coalesce(metadata->'summary'->>'status', '')) IN ('retired', 'superseded', 'stale')
                          OR COALESCE((metadata->'summary') ? 'retired_at', false)
                          OR COALESCE((metadata->'summary') ? 'superseded_by', false)
                        )
                      )
                    """,
                    (db_tenant_id, branch, max_trust, max_sensitivity, include_quarantined),
                )
                for row in cur.fetchall():
                    text = row["content"] or ""
                    score = lexical_score(query, text)
                    if score > 0:
                        cid = _bytes_to_cid(row["cid"])
                        metadata = dict(row["metadata"] or {})
                        if is_retired_summary_metadata(metadata):
                            continue
                        decision = may_read_item(
                            item_tenant_id=tenant_id,
                            sensitivity=int(row["sensitivity"]),
                            access_policy=dict(row["access_policy"] or {}),
                            context=filt,
                            policy_max_sensitivity=self.policy.max_sensitivity,
                        )
                        if not decision.allowed:
                            continue
                        text, privacy_metadata = apply_text_redactions(text, dict(row["access_policy"] or {}), decision)
                        hit_metadata = {
                            "source_type": row["source_type"],
                            "actor": row["actor"],
                            "reality_class": self._classify_evidence_row_reality(row, metadata),
                            "privacy": privacy_metadata,
                        }
                        if isinstance(metadata.get("summary"), dict):
                            hit_metadata["summary"] = metadata["summary"]
                        if isinstance(metadata.get("lifecycle"), dict):
                            hit_metadata["lifecycle"] = metadata["lifecycle"]
                        if "confidence" in metadata:
                            hit_metadata["confidence"] = metadata["confidence"]
                        if isinstance(metadata.get("earned_autonomy"), dict):
                            hit_metadata["earned_autonomy"] = metadata["earned_autonomy"]
                        if "birth_groundedness" in metadata:
                            hit_metadata["birth_groundedness"] = metadata["birth_groundedness"]
                        candidates.append(
                            Hit(
                                id=cid,
                                kind="evidence",
                                tenant_id=tenant_id,
                                branch=row["branch"],
                                text=text,
                                score=score,
                                channel=channel,
                                provenance=[cid],
                                trust_tier=row["trust_tier"],
                                sensitivity=row["sensitivity"],
                                metadata=hit_metadata,
                            )
                        )
                cur.execute(
                    """
                    SELECT id, tenant_id, branch, subject, predicate, object, confidence, calibration, status,
                      source_evidence_cids, trust_tier, sensitivity, access_policy, last_accessed, access_count
                    FROM assertions
                    WHERE tenant_id = %s AND branch = %s AND status IN ('active', 'contested')
                      AND trust_tier <= %s AND sensitivity <= %s
                    """,
                    (db_tenant_id, branch, max_trust, max_sensitivity),
                )
                for row in cur.fetchall():
                    raw_text = f"{row['subject']} {row['predicate']} {row['object']}"
                    score = lexical_score(query, raw_text) * float(row["confidence"])
                    if score > 0:
                        decision = may_read_item(
                            item_tenant_id=tenant_id,
                            sensitivity=int(row["sensitivity"]),
                            access_policy=dict(row["access_policy"] or {}),
                            context=filt,
                            policy_max_sensitivity=self.policy.max_sensitivity,
                            status=str(row["status"]),
                        )
                        if not decision.allowed:
                            continue
                        text, privacy_metadata = apply_statement_redactions(
                            subject=str(row["subject"]),
                            predicate=str(row["predicate"]),
                            object_value=str(row["object"]),
                            access_policy=dict(row["access_policy"] or {}),
                            decision=decision,
                        )
                        reality_monitoring = self._projection_reality_monitoring_from_calibration(dict(row["calibration"] or {}))
                        candidates.append(
                            Hit(
                                id=str(row["id"]),
                                kind="assertion",
                                tenant_id=tenant_id,
                                branch=row["branch"],
                                text=text,
                                score=score,
                                channel=channel,
                                provenance=_bytes_list_to_cids(row["source_evidence_cids"]),
                                trust_tier=row["trust_tier"],
                                sensitivity=row["sensitivity"],
                                metadata={
                                    "confidence": float(row["confidence"]),
                                    "reality_class": reality_monitoring["reality_class"],
                                    "reality_monitoring": reality_monitoring,
                                    "last_accessed": row["last_accessed"].isoformat() if row["last_accessed"] else None,
                                    "access_count": row["access_count"],
                                    "privacy": privacy_metadata,
                                },
                            )
                        )
        return self._mark_retrieved_text_as_data(sorted(candidates, key=lambda item: item.score, reverse=True)[:k])

    def _audit(
        self,
        cur: Any,
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
        target_uuid = _uuid_or_none(target_id)
        audit_diff = dict(diff)
        if target_id and not target_uuid:
            audit_diff.setdefault("target_id", target_id)
        normalized_tags = sorted(set(capability_tags or []))
        audit_diff.setdefault("source", source or actor)
        if trust_tier is not None:
            audit_diff.setdefault("trust_tier", trust_tier)
        if normalized_tags:
            audit_diff.setdefault("capability_tags", normalized_tags)
        cur.execute(
            """
            INSERT INTO audit_log(tenant_id, actor, op, target_id, trust_tier, capability_tags, diff)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (tenant_id, actor, op, target_uuid, trust_tier, normalized_tags, self._jsonb(audit_diff)),
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
        db_tenant_id = _stable_uuid("tenant", tenant_id) if tenant_id else None
        with self.connect() as conn:
            with conn.cursor() as cur:
                if db_tenant_id is not None:
                    self._set_tenant(cur, db_tenant_id)
                self._audit(
                    cur,
                    db_tenant_id,
                    actor,
                    op,
                    target_id,
                    diff,
                    source=source,
                    trust_tier=trust_tier,
                    capability_tags=capability_tags,
                )

    @staticmethod
    def _mark_retrieved_text_as_data(hits: list[Hit]) -> list[Hit]:
        for hit in hits:
            hit.metadata = {
                **hit.metadata,
                "retrieved_text": sanitize_retrieved_text(hit.text, hit.trust_tier),
            }
        return hits

    def _rrf(self, ranked_lists: list[list[Hit]], k: int) -> list[Hit]:
        return rrf_fuse(ranked_lists, k, rrf_k=self.policy.rrf_k, annotate_channel_scores=True)

    def _mmr(self, query: str, hits: list[Hit], k: int) -> list[Hit]:
        # Embedding sourcing stays hardcoded to hashing_embedding for BOTH
        # query and hits (deliberately divergent from LocalMemoryEngine's
        # security-gated path, spec §4.0). hashing_embedding never returns
        # None and is pure/memoized, so mmr_select's missing-vector guards
        # are no-ops here and per-candidate recomputation is byte-identical.
        return mmr_select(
            hits,
            k,
            query_vec=hashing_embedding(query),
            embed_hit=lambda hit: hashing_embedding(hit.text),
            mmr_lambda=self.policy.mmr_lambda,
        )

    @staticmethod
    def _u_curve_order(hits: list[Hit]) -> list[Hit]:
        return u_curve_order(hits)

    @staticmethod
    def _fit_budget(hits: list[Hit], budget: int) -> tuple[list[Hit], int]:
        return fit_budget(hits, budget)

    @staticmethod
    def _confidence(query: str, hits: list[Hit], *, support_score: float | None = None) -> float:
        if not hits:
            return 0.0
        weighted = 0.0
        total = 0.0
        for hit in hits:
            trust = trust_weight(hit.trust_tier)
            base = float(hit.metadata.get("confidence", 0.7))
            weighted += max(hit.score, 0.01) * trust * base
            total += max(hit.score, 0.01)
        evidence_quality = max(0.0, min(1.0, weighted / max(total, 0.01)))
        query_support_score = support_score if support_score is not None else query_support(query, hits)["score"]
        query_support_score = max(0.0, min(1.0, query_support_score))
        if query_support_score < QUERY_SUPPORT_THRESHOLD:
            return min(evidence_quality, 0.05 * (query_support_score / QUERY_SUPPORT_THRESHOLD))
        support_floor = 0.96 + 0.04 * (
            (query_support_score - QUERY_SUPPORT_THRESHOLD) / max(1.0 - QUERY_SUPPORT_THRESHOLD, 0.01)
        )
        return max(evidence_quality, min(1.0, support_floor))

    @staticmethod
    def _prediction_set_size(hits: list[Hit], threshold: float) -> int:
        if not hits:
            return 0
        max_score = max((max(hit.score, 0.0) for hit in hits), default=0.0)
        if max_score <= 0.0:
            return 0
        cutoff = max_score * max(0.05, min(0.95, threshold))
        return sum(1 for hit in hits if max(hit.score, 0.0) >= cutoff)


def _cid_to_bytes(cid: str) -> bytes:
    return bytes.fromhex(cid.removeprefix("cidv1:"))


def _cid_bytes_or_none(cid: str) -> bytes | None:
    value = cid.removeprefix("cidv1:")
    try:
        return bytes.fromhex(value)
    except ValueError:
        return None


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.8g}" for value in vector) + "]"


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return dt_to_json(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, memoryview):
        return value.tobytes().hex()
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return value


def _row_to_audit_log(row: Any) -> dict[str, Any]:
    data = _json_safe(dict(row))
    diff = data.get("diff")
    if isinstance(diff, dict):
        if not data.get("target_id") and diff.get("target_id"):
            data["target_id"] = diff["target_id"]
        data["diff"] = {key: value for key, value in diff.items() if key != "target_id"}
        if "source" in diff:
            data.setdefault("source", diff["source"])
    return data


def _bytes_to_cid(value: bytes | memoryview) -> str:
    raw = value.tobytes() if isinstance(value, memoryview) else value
    return raw.hex()


def _cid_list_to_bytes(cids: list[str]) -> list[bytes]:
    return [_cid_to_bytes(cid) for cid in cids]


def _bytes_list_to_cids(values: list[bytes] | None) -> list[str]:
    if not values:
        return []
    return [_bytes_to_cid(value) for value in values]


def _graph_ppr_seed_hash(seed_set: set[str]) -> str:
    payload = json.dumps(sorted(seed_set), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(payload).hexdigest()


def _graph_ppr_as_of_key(as_of: datetime | None, moment: datetime) -> str:
    if as_of is None:
        return "current"
    return moment.isoformat()


def _metadata_source_cids(metadata: dict[str, Any]) -> set[str]:
    sources: set[str] = set()
    single = metadata.get("source_evidence_cid")
    if single:
        sources.add(str(single))
    values = metadata.get("source_evidence_cids")
    if isinstance(values, list):
        sources.update(str(item) for item in values if item)
    summary = metadata.get("summary")
    if isinstance(summary, dict):
        summary_values = summary.get("source_evidence_cids")
        if isinstance(summary_values, list):
            sources.update(str(item) for item in summary_values if item)
    return sources


def _derived_evidence_forget_plan(
    cid: str,
    candidates: list[tuple[bytes, dict[str, Any]]],
    *,
    legal_blind: bool = False,
) -> tuple[list[bytes], list[str], dict[bytes, dict[str, Any]]]:
    affected = {cid}
    erased_bytes: list[bytes] = []
    erased_cids: list[str] = []
    retained: dict[bytes, dict[str, Any]] = {}
    changed = True
    while changed:
        changed = False
        for candidate_bytes, metadata in candidates:
            candidate_cid = _bytes_to_cid(candidate_bytes)
            if candidate_cid in affected:
                continue
            sources = _metadata_source_cids(metadata)
            if not affected.intersection(sources):
                continue
            surviving_sources = sources - affected
            if surviving_sources and not legal_blind:
                retained[candidate_bytes] = _trim_metadata_source_cids(metadata, affected)
                continue
            affected.add(candidate_cid)
            retained.pop(candidate_bytes, None)
            erased_bytes.append(candidate_bytes)
            erased_cids.append(candidate_cid)
            changed = True
    return erased_bytes, erased_cids, retained


def _trim_metadata_source_cids(metadata: dict[str, Any], affected_cids: set[str]) -> dict[str, Any]:
    trimmed = copy.deepcopy(metadata)
    if str(trimmed.get("source_evidence_cid") or "") in affected_cids:
        trimmed.pop("source_evidence_cid", None)
    values = trimmed.get("source_evidence_cids")
    if isinstance(values, list):
        trimmed["source_evidence_cids"] = [str(item) for item in values if str(item) not in affected_cids]
    summary = trimmed.get("summary")
    if isinstance(summary, dict):
        summary_values = summary.get("source_evidence_cids")
        if isinstance(summary_values, list):
            kept = [str(item) for item in summary_values if str(item) not in affected_cids]
            summary["source_evidence_cids"] = kept
            summary["source_count"] = len(kept)
            summary.pop("source_fingerprint", None)
    return trimmed


def _uuid_or_none(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(UUID(value))
    except ValueError:
        return None


def _stable_uuid(kind: str, value: str) -> str:
    if _uuid_or_none(value):
        return value
    return str(uuid5(NAMESPACE_URL, f"mnemosyne:{kind}:{value}"))


def _dedupe_hits(hits: list[Hit]) -> list[Hit]:
    by_id: dict[tuple[str, str], Hit] = {}
    for hit in hits:
        key = (hit.kind, hit.id)
        if key not in by_id or hit.score > by_id[key].score:
            by_id[key] = hit
    return list(by_id.values())


def _vector_from_db(value: Any) -> list[float] | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped == "[]":
            return None
        if stripped.startswith("[") and stripped.endswith("]"):
            stripped = stripped[1:-1]
        return [float(part) for part in stripped.split(",") if part]
    if isinstance(value, (list, tuple)):
        return [float(part) for part in value]
    return None


_INTERNAL_EVIDENCE_METADATA_KEYS = {
    "_external_tenant_id",
    "_external_user_id",
    "_external_session_id",
    "_mnemosyne_embedding_explicit",
}


def _public_evidence_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metadata.items()
        if key not in _INTERNAL_EVIDENCE_METADATA_KEYS
    }


def _row_to_evidence(row: dict[str, Any], cid: str) -> Evidence:
    metadata = dict(row["metadata"] or {})
    explicit_embedding = bool(metadata.get("_mnemosyne_embedding_explicit"))
    public_metadata = _public_evidence_metadata(metadata)
    return Evidence(
        tenant_id=str(row.get("tenant_name") or metadata.get("_external_tenant_id") or row["tenant_id"]),
        user_id=str(metadata.get("_external_user_id") or row["user_id"]),
        actor=row["actor"],
        source_type=row["source_type"],
        source_identity=row["source_identity"],
        session_id=str(metadata.get("_external_session_id") or row["session_id"]) if row["session_id"] else None,
        content=row["content"] or "",
        metadata=public_metadata,
        content_pointer=row["content_pointer"],
        modality=row["modality"],
        embedding=_vector_from_db(row.get("embedding")) if explicit_embedding else None,
        signed_provenance=dict(row["signed_provenance"]) if row["signed_provenance"] else None,
        trust_tier=row["trust_tier"],
        capability_tags=list(row["capability_tags"] or []),
        sensitivity=row["sensitivity"],
        access_policy=dict(row["access_policy"] or {}),
        branch=row["branch"],
        cid=cid,
        created_at=parse_dt(row["created_at"]) or utc_now(),
        erased=row["erased"],
    )


def _row_to_assertion(row: dict[str, Any]) -> Assertion:
    return Assertion(
        id=str(row["id"]),
        tenant_id=str(row.get("tenant_name") or row["tenant_id"]),
        user_id=str(row.get("external_user_id") or row["user_id"]) if row["user_id"] else None,
        branch=row["branch"],
        subject=row["subject"],
        predicate=row["predicate"],
        object=row["object"],
        scope=dict(row["scope"] or {}),
        confidence=float(row["confidence"]),
        calibration=dict(row["calibration"] or {}),
        valid_from=parse_dt(row["valid_from"]) or utc_now(),
        valid_to=parse_dt(row["valid_to"]),
        transaction_time=parse_dt(row["transaction_time"]) or utc_now(),
        expired_at=parse_dt(row["expired_at"]),
        justification_id=str(row["justification_id"]) if row["justification_id"] else None,
        source_evidence_cids=_bytes_list_to_cids(row["source_evidence_cids"]),
        status=row["status"],
        version=row["version"],
        superseded_by=str(row["superseded_by"]) if row["superseded_by"] else None,
        trust_tier=row["trust_tier"],
        sensitivity=row["sensitivity"],
        access_policy=dict(row["access_policy"] or {}),
        last_accessed=parse_dt(row["last_accessed"]),
        access_count=row["access_count"],
    )


def _row_to_relation(row: dict[str, Any], tenant_id: str) -> Relation:
    return Relation(
        id=str(row["id"]),
        tenant_id=tenant_id,
        branch=row["branch"],
        source=row["source"],
        predicate=row["predicate"],
        target=row["target"],
        confidence=float(row["confidence"]),
        valid_from=parse_dt(row["valid_from"]) or utc_now(),
        valid_to=parse_dt(row["valid_to"]),
        source_evidence_cids=_bytes_list_to_cids(row["source_evidence_cids"]),
        access_policy=dict(row["access_policy"] or {}),
    )


def _row_to_preference(row: dict[str, Any], tenant_id: str) -> Preference:
    return Preference(
        id=str(row["id"]),
        tenant_id=tenant_id,
        user_id=str(row.get("external_user_id") or row["user_id"]),
        category=row["category"],
        statement=row["statement"],
        scope=dict(row["scope"] or {}),
        confidence=float(row["confidence"]),
        explicit=bool(row["explicit"]),
        exceptions=row["exceptions"] if row["exceptions"] is not None else {},
        source_evidence_cids=_bytes_list_to_cids(row["source_evidence_cids"]),
        access_policy=dict(row.get("access_policy") or {}),
        valid_from=parse_dt(row["valid_from"]) or utc_now(),
        valid_to=parse_dt(row["valid_to"]),
        status=row["status"],
    )
