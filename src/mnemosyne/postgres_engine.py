"""PostgreSQL-backed Mnemosyne engine adapter."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from mnemosyne.ids import content_cid
from mnemosyne.models import Assertion, Evidence, Hit, MergeReport, Preference, Relation, RetrievalResult, dt_to_json, parse_dt, utc_now
from mnemosyne.policy import OperatingPolicy
from mnemosyne.privacy import ErasureMode
from mnemosyne.retrieval import HashingEmbeddingProvider, LocalSimilarityReranker, RetrievalAdapters
from mnemosyne.security import TrustTier, trust_weight
from mnemosyne.text import approx_tokens, cosine, hashing_embedding, lexical_score, tokenize


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
    sql/schema.sql. It writes deterministic assertion embeddings and lexemes so
    fresh local deployments exercise the same Postgres full-text, pgvector, and
    graph contracts that production model providers can later replace.
    """

    def __init__(self, dsn: str, policy: OperatingPolicy | None = None, adapters: RetrievalAdapters | None = None):
        self.dsn = dsn
        self.policy = policy or OperatingPolicy()
        if adapters is None:
            embedding = HashingEmbeddingProvider(dims=1024)
            adapters = RetrievalAdapters(
                embedding=embedding,
                reranker=LocalSimilarityReranker(embedding_provider=embedding),
                lexical_backend="postgres-fts",
                graph_backend="postgres-recursive-ppr",
            )
        self.adapters = adapters
        self._psycopg, self._jsonb = _require_psycopg()

    def connect(self) -> Any:
        return self._psycopg.connect(self.dsn)

    @staticmethod
    def _set_tenant(cur: Any, db_tenant_id: str) -> None:
        cur.execute("SELECT set_config('mnemosyne.tenant_id', %s, true)", (str(db_tenant_id),))

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
        self.ensure_tenant_and_branch(ev.tenant_id, branch)
        db_tenant_id = _stable_uuid("tenant", ev.tenant_id)
        db_user_id = _stable_uuid("user", ev.user_id)
        db_session_id = _stable_uuid("session", ev.session_id) if ev.session_id else None
        metadata = {**ev.metadata, "_external_tenant_id": ev.tenant_id, "_external_user_id": ev.user_id}
        cid = content_cid(
            ev.content,
            {
                "tenant_id": ev.tenant_id,
                "source_type": ev.source_type,
                "content_pointer": ev.content_pointer,
                "modality": ev.modality,
            },
        )
        cid_bytes = _cid_to_bytes(cid)
        with self.connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    INSERT INTO evidence (
                      cid, branch, tenant_id, user_id, session_id, actor, source_type,
                      source_identity, content, content_pointer, modality, metadata,
                      trust_tier, capability_tags, sensitivity, signed_provenance,
                      access_policy, erased, created_at
                    )
                    VALUES (
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, false, %s
                    )
                    ON CONFLICT (tenant_id, branch, cid)
                    DO UPDATE SET
                      user_id = EXCLUDED.user_id,
                      session_id = EXCLUDED.session_id,
                      actor = EXCLUDED.actor,
                      source_type = EXCLUDED.source_type,
                      source_identity = EXCLUDED.source_identity,
                      content = EXCLUDED.content,
                      content_pointer = EXCLUDED.content_pointer,
                      modality = EXCLUDED.modality,
                      metadata = EXCLUDED.metadata,
                      trust_tier = EXCLUDED.trust_tier,
                      capability_tags = EXCLUDED.capability_tags,
                      sensitivity = EXCLUDED.sensitivity,
                      signed_provenance = EXCLUDED.signed_provenance,
                      access_policy = EXCLUDED.access_policy,
                      erased = false
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
                        self._jsonb(ev.access_policy),
                        ev.created_at,
                    ),
                )
                self._audit(cur, db_tenant_id, ev.actor, "append_evidence", cid, {"branch": branch})
        return cid

    def get_evidence(self, tenant_id: str, cid: str, branch: str = "main") -> Evidence | None:
        db_tenant_id = _stable_uuid("tenant", tenant_id)
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
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

    def upsert_assertion(self, assertion: Assertion, branch: str = "main") -> str:
        self.ensure_tenant_and_branch(assertion.tenant_id, branch)
        incoming = Assertion.from_dict(assertion.to_dict())
        incoming.branch = branch
        incoming.status = "active" if incoming.status == "candidate" else incoming.status
        incoming.transaction_time = utc_now()
        db_tenant_id = _stable_uuid("tenant", incoming.tenant_id)
        db_user_id = _stable_uuid("user", incoming.user_id) if incoming.user_id else None
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                self._set_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    SELECT * FROM assertions
                    WHERE tenant_id = %s AND branch = %s AND subject = %s
                      AND predicate = %s AND scope = %s
                      AND status IN ('active', 'contested')
                    ORDER BY valid_from DESC
                    """,
                    (db_tenant_id, branch, incoming.subject, incoming.predicate, self._jsonb(incoming.scope)),
                )
                peers = list(cur.fetchall())
                same = [row for row in peers if row["object"] == incoming.object]
                if same:
                    winner = same[0]
                    merged_confidence = max(float(winner["confidence"]), incoming.confidence)
                    merged_sources = sorted(set(_bytes_list_to_cids(winner["source_evidence_cids"]) + incoming.source_evidence_cids))
                    cur.execute(
                        """
                        UPDATE assertions
                        SET confidence = %s, source_evidence_cids = %s, trust_tier = LEAST(trust_tier, %s),
                            last_accessed = now(), access_count = access_count + 1
                        WHERE id = %s
                        """,
                        (merged_confidence, _cid_list_to_bytes(merged_sources), incoming.trust_tier, winner["id"]),
                    )
                    self._audit(cur, db_tenant_id, "engine", "upsert_assertion.reinforce", str(winner["id"]), {})
                    return str(winner["id"])

                conflicts = [row for row in peers if row["object"] != incoming.object]
                if conflicts:
                    current = conflicts[0]
                    current_valid_from = parse_dt(current["valid_from"]) or utc_now()
                    if incoming.valid_from > current_valid_from:
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

                cur.execute(
                    """
                    INSERT INTO assertions (
                      id, tenant_id, user_id, branch, subject, predicate, object, scope,
                      confidence, calibration, valid_from, valid_to, transaction_time,
                      expired_at, justification_id, source_evidence_cids, status, version,
                      superseded_by, trust_tier, sensitivity, access_policy, embedding,
                      lexeme, last_accessed, access_count
                    )
                    VALUES (
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s, %s, %s::vector,
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
                        _vector_literal(self.adapters.embedding.embed(incoming.statement())),
                        incoming.statement(),
                        incoming.last_accessed,
                        incoming.access_count,
                    ),
                )
                self._audit(cur, db_tenant_id, "engine", "upsert_assertion", incoming.id, {"branch": branch})
        return incoming.id

    def add_relation(self, relation: Relation, branch: str = "main") -> str:
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
                        self._jsonb(relation.access_policy),
                    ),
                )
                self._audit(cur, db_tenant_id, "engine", "add_relation", relation.id, {"branch": branch})
        return relation.id

    def add_preference(self, preference: Preference) -> str:
        self.ensure_tenant_and_branch(preference.tenant_id)
        pref = Preference.from_dict(preference.to_dict())
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
                      status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                    SET statement = EXCLUDED.statement,
                        confidence = EXCLUDED.confidence,
                        explicit = EXCLUDED.explicit,
                        exceptions = EXCLUDED.exceptions,
                        source_evidence_cids = EXCLUDED.source_evidence_cids,
                        valid_to = EXCLUDED.valid_to,
                        status = EXCLUDED.status
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
                    ),
                )
                self._audit(cur, db_tenant_id, "engine", "add_preference", pref.id, {"category": pref.category, "explicit": pref.explicit})
        return pref.id

    def lexical_search(self, query: str, k: int, filt: dict[str, Any]) -> list[Hit]:
        tenant_id = filt["tenant_id"]
        db_tenant_id = _stable_uuid("tenant", tenant_id)
        branch = filt.get("branch", "main")
        include_quarantined = bool(filt.get("include_quarantined", False))
        default_max_trust = int(TrustTier.UNTRUSTED_EXTERNAL) if include_quarantined else self.policy.max_trust_tier
        max_trust = int(filt.get("max_trust_tier", filt.get("min_trust_tier", default_max_trust)))
        max_sensitivity = int(filt.get("max_sensitivity", self.policy.max_sensitivity))
        hits: list[Hit] = []
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                self._set_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    WITH q AS (SELECT plainto_tsquery('english', %s) AS query)
                    SELECT e.cid, e.branch, e.content, e.trust_tier, e.sensitivity,
                      e.source_type, ts_rank_cd(to_tsvector('english', coalesce(e.content, '')), q.query) AS score
                    FROM evidence e, q
                    WHERE e.tenant_id = %s AND e.branch = %s AND e.erased = false
                      AND e.trust_tier <= %s AND e.sensitivity <= %s
                      AND (%s OR NOT (e.metadata ? 'quarantine_reason'))
                      AND to_tsvector('english', coalesce(e.content, '')) @@ q.query
                    ORDER BY score DESC
                    LIMIT %s
                    """,
                    (query, db_tenant_id, branch, max_trust, max_sensitivity, include_quarantined, k),
                )
                for row in cur.fetchall():
                    cid = _bytes_to_cid(row["cid"])
                    hits.append(
                        Hit(
                            id=cid,
                            kind="evidence",
                            tenant_id=tenant_id,
                            branch=row["branch"],
                            text=row["content"] or "",
                            score=float(row["score"] or 0.0),
                            channel="postgres_fts",
                            provenance=[cid],
                            trust_tier=row["trust_tier"],
                            sensitivity=row["sensitivity"],
                            metadata={"source_type": row["source_type"], "backend": self.adapters.lexical_backend},
                        )
                    )
                cur.execute(
                    """
                    WITH q AS (SELECT plainto_tsquery('english', %s) AS query)
                    SELECT a.id, a.branch, a.subject, a.predicate, a.object, a.confidence,
                      a.source_evidence_cids, a.trust_tier, a.sensitivity,
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
                    text = f"{row['subject']} {row['predicate']} {row['object']}"
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
                            metadata={"confidence": float(row["confidence"]), "backend": self.adapters.lexical_backend},
                        )
                    )
        if not hits:
            return self._local_rank(query, k, filt, channel="postgres_lexical_fallback")
        return sorted(hits, key=lambda item: item.score, reverse=True)[:k]

    def vector_search(self, query: str, k: int, filt: dict[str, Any]) -> list[Hit]:
        tenant_id = filt["tenant_id"]
        db_tenant_id = _stable_uuid("tenant", tenant_id)
        branch = filt.get("branch", "main")
        include_quarantined = bool(filt.get("include_quarantined", False))
        default_max_trust = int(TrustTier.UNTRUSTED_EXTERNAL) if include_quarantined else self.policy.max_trust_tier
        max_trust = int(filt.get("max_trust_tier", filt.get("min_trust_tier", default_max_trust)))
        max_sensitivity = int(filt.get("max_sensitivity", self.policy.max_sensitivity))
        query_vec = self.adapters.embedding.embed(query)
        query_literal = _vector_literal(query_vec)
        hits: list[Hit] = []
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                self._set_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    SELECT id, branch, subject, predicate, object, confidence,
                      source_evidence_cids, trust_tier, sensitivity,
                      1.0 - (embedding <=> %s::vector) AS score
                    FROM assertions
                    WHERE tenant_id = %s AND branch = %s AND status IN ('active', 'contested')
                      AND trust_tier <= %s AND sensitivity <= %s
                      AND embedding IS NOT NULL
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (query_literal, db_tenant_id, branch, max_trust, max_sensitivity, query_literal, k),
                )
                for row in cur.fetchall():
                    score = float(row["score"] or 0.0)
                    if score <= 0:
                        continue
                    text = f"{row['subject']} {row['predicate']} {row['object']}"
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
                                "backend": self.adapters.embedding.name,
                                "embedding_dims": self.adapters.embedding.dims,
                            },
                        )
                    )
                cur.execute(
                    """
                    SELECT cid, branch, content, trust_tier, sensitivity, source_type
                    FROM evidence
                    WHERE tenant_id = %s AND branch = %s AND erased = false
                      AND trust_tier <= %s AND sensitivity <= %s
                      AND (%s OR NOT (metadata ? 'quarantine_reason'))
                    """,
                    (db_tenant_id, branch, max_trust, max_sensitivity, include_quarantined),
                )
                for row in cur.fetchall():
                    text = row["content"] or ""
                    score = cosine(query_vec, self.adapters.embedding.embed(text))
                    if score <= 0:
                        continue
                    cid = _bytes_to_cid(row["cid"])
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
                            metadata={
                                "source_type": row["source_type"],
                                "backend": self.adapters.embedding.name,
                                "embedding_dims": self.adapters.embedding.dims,
                                "stored_embedding": False,
                            },
                        )
                    )
        return sorted(hits, key=lambda item: item.score, reverse=True)[:k]

    def graph_ppr(
        self,
        seeds: list[str],
        k: int,
        as_of: datetime | None = None,
        tenant_id: str | None = None,
        branch: str | None = None,
    ) -> list[Hit]:
        seed_set = {seed.lower() for seed in seeds}
        if not seed_set or not tenant_id:
            return []
        def matches_seed(node: str) -> bool:
            node_lower = node.lower()
            return node_lower in seed_set or bool(set(tokenize(node_lower)) & seed_set)

        db_tenant_id = _stable_uuid("tenant", tenant_id)
        branch = branch or "main"
        moment = None
        if as_of:
            moment = as_of.astimezone(UTC) if as_of.tzinfo else as_of.replace(tzinfo=UTC)
        adjacency: dict[str, set[str]] = defaultdict(set)
        relation_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                self._set_tenant(cur, db_tenant_id)
                if moment:
                    cur.execute(
                        """
                        SELECT *
                        FROM relations
                        WHERE tenant_id = %s AND branch = %s
                          AND valid_from <= %s AND (valid_to IS NULL OR valid_to > %s)
                        """,
                        (db_tenant_id, branch, moment, moment),
                    )
                else:
                    cur.execute(
                        """
                        SELECT *
                        FROM relations
                        WHERE tenant_id = %s AND branch = %s
                        """,
                        (db_tenant_id, branch),
                    )
                for row in cur.fetchall():
                    source = row["source"].lower()
                    target = row["target"].lower()
                    adjacency[source].add(target)
                    adjacency[target].add(source)
                    relation_by_pair[(source, target)] = dict(row)
                    relation_by_pair[(target, source)] = dict(row)
        ranks = {node: (1.0 if matches_seed(node) else 0.0) for node in adjacency}
        for seed in seed_set:
            ranks.setdefault(seed, 1.0)
        for _ in range(12):
            next_ranks = {node: 0.15 * (1.0 if matches_seed(node) else 0.0) for node in ranks}
            for node, neighbors in adjacency.items():
                if not neighbors:
                    continue
                share = 0.85 * ranks.get(node, 0.0) / len(neighbors)
                for neighbor in neighbors:
                    next_ranks[neighbor] = next_ranks.get(neighbor, 0.0) + share
            ranks = next_ranks
        hits: list[Hit] = []
        for node, score in sorted(ranks.items(), key=lambda item: item[1], reverse=True):
            if matches_seed(node) or score <= 0:
                continue
            rel = next((relation_by_pair[pair] for pair in relation_by_pair if pair[0] == node or pair[1] == node), None)
            if not rel:
                continue
            hits.append(
                Hit(
                    id=str(rel["id"]),
                    kind="relation",
                    tenant_id=tenant_id,
                    branch=rel["branch"],
                    text=f"{rel['source']} {rel['predicate']} {rel['target']}",
                    score=float(score) * float(rel["confidence"]),
                    channel="postgres_graph_ppr",
                    provenance=_bytes_list_to_cids(rel["source_evidence_cids"]),
                    metadata={
                        "confidence": float(rel["confidence"]),
                        "backend": self.adapters.graph_backend,
                    },
                )
            )
            if len(hits) >= k:
                break
        return hits

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

    def retrieve(self, query: str, tenant_id: str, branch: str = "main", deep: bool = False, filt: dict[str, Any] | None = None) -> RetrievalResult:
        effective_filter = dict(filt or {})
        effective_filter.update({"tenant_id": tenant_id, "branch": branch})
        k = self.policy.deep_top_k if deep else self.policy.top_k
        dense = self.vector_search(query, self.policy.rerank_width, effective_filter)
        lexical = self.lexical_search(query, self.policy.rerank_width, effective_filter)
        graph = self.graph_ppr(tokenize(query), max(4, k // 2), tenant_id=tenant_id, branch=branch) if deep else []
        fused = self._rrf([dense, lexical, graph], k=max(k * 2, self.policy.rerank_width))
        reranked = self.adapters.reranker.rerank(query, fused, k=max(k * 2, k))
        diversified = self._mmr(query, reranked, k=max(k, 1))
        ordered = self._u_curve_order(diversified)
        budgeted, used_tokens = self._fit_budget(ordered, self.policy.token_budget)
        confidence = self._confidence(budgeted)
        abstained = confidence < self.policy.abstention_threshold
        return RetrievalResult(
            query=query,
            hits=budgeted,
            confidence=confidence,
            abstained=abstained,
            uncertainty_note="Evidence is too thin, low-trust, or conflicting for a confident answer." if abstained else None,
            token_budget=self.policy.token_budget,
            used_tokens=used_tokens,
            explain={
                "channels": {
                    "postgres_dense": len(dense),
                    "postgres_lexical": len(lexical),
                    "postgres_graph_ppr": len(graph),
                },
                "rrf_k": self.policy.rrf_k,
                "mmr_lambda": self.policy.mmr_lambda,
                "adapters": {
                    "embedding": self.adapters.embedding.name,
                    "embedding_dims": self.adapters.embedding.dims,
                    "reranker": self.adapters.reranker.name,
                    "lexical_backend": self.adapters.lexical_backend,
                    "graph_backend": self.adapters.graph_backend,
                },
                "rails": self.policy.immutable_rails,
            },
        )

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
            "erased_derived_evidence": [],
        }
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                self._set_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    SELECT cid
                    FROM evidence
                    WHERE tenant_id = %s AND branch = %s AND cid = %s
                    """,
                    (db_tenant_id, branch, cid_bytes),
                )
                if not cur.fetchone():
                    return {"erased": False, "reason": "evidence_not_found", "cid": cid, "erasure_mode": mode.value}
                cur.execute(
                    """
                    SELECT cid
                    FROM evidence
                    WHERE tenant_id = %s AND branch = %s
                      AND erased = false
                      AND metadata->>'source_evidence_cid' = %s
                      AND cid <> %s
                    """,
                    (db_tenant_id, branch, cid, cid_bytes),
                )
                derived_cid_bytes = [bytes(row["cid"]) for row in cur.fetchall()]
                derived_cids = [_bytes_to_cid(item) for item in derived_cid_bytes]
                affected_cid_bytes = [cid_bytes, *derived_cid_bytes]
                affected_cids = {cid, *derived_cids}
                propagated["erased_derived_evidence"] = derived_cids
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
                            "UPDATE relations SET valid_to = now(), source_evidence_cids = %s WHERE id = %s",
                            (_cid_list_to_bytes([]), row["id"]),
                        )
                        propagated["expired_relations"].append(str(row["id"]))
                cur.execute(
                    """
                    INSERT INTO deletion_log(tenant_id, evidence_cid, requested_by, propagated)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (db_tenant_id, cid_bytes, requested_by, self._jsonb({**propagated, "erasure_mode": mode.value})),
                )
                self._audit(cur, db_tenant_id, requested_by, "forget", cid, {**propagated, "erasure_mode": mode.value})
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
                    SELECT a.*, t.name AS tenant_name
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
                    SELECT p.*, t.name AS tenant_name
                    FROM preferences p
                    JOIN tenants t ON t.id = p.tenant_id
                    WHERE p.tenant_id = %s
                    """,
                    (db_tenant_id,),
                )
                preferences = [_row_to_preference(row, tenant_id).to_dict() for row in cur.fetchall()]
                cur.execute("SELECT * FROM audit_log WHERE tenant_id = %s", (db_tenant_id,))
                audit = [_row_to_audit_log(row) for row in cur.fetchall()]
                cur.execute("SELECT * FROM deletion_log WHERE tenant_id = %s", (db_tenant_id,))
                deletion = [_json_safe(dict(row)) for row in cur.fetchall()]
        return {
            "tenant_id": tenant_id,
            "evidence": evidence,
            "assertions": assertions,
            "relations": relations,
            "preferences": preferences,
            "justifications": [],
            "contradictions": [],
            "audit_log": audit,
            "deletion_log": deletion,
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
                          access_policy, erased, created_at
                        )
                        SELECT cid, %s, tenant_id, user_id, session_id, actor, source_type,
                          source_identity, content, content_pointer, modality, metadata,
                          trust_tier, capability_tags, sensitivity, signed_provenance,
                          access_policy, erased, created_at
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
                          lexeme, last_accessed, access_count
                        )
                        SELECT gen_random_uuid(), tenant_id, user_id, %s, subject, predicate,
                          object, scope, confidence, calibration, valid_from, valid_to,
                          transaction_time, expired_at, justification_id, source_evidence_cids,
                          status, version, superseded_by, trust_tier, sensitivity,
                          access_policy, embedding, lexeme, last_accessed, access_count
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
                          access_policy, erased, created_at
                        )
                        SELECT cid, %s, tenant_id, user_id, session_id, actor, source_type,
                          source_identity, content, content_pointer, modality, metadata,
                          trust_tier, capability_tags, sensitivity, signed_provenance,
                          access_policy, erased, created_at
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
                cur.execute("DELETE FROM evidence WHERE tenant_id = %s AND branch = %s", (db_tenant_id, branch))
                cur.execute("DELETE FROM branches WHERE tenant_id = %s AND name = %s", (db_tenant_id, branch))

    def _local_rank(self, query: str, k: int, filt: dict[str, Any], channel: str) -> list[Hit]:
        tenant_id = filt["tenant_id"]
        db_tenant_id = _stable_uuid("tenant", tenant_id)
        branch = filt.get("branch", "main")
        include_quarantined = bool(filt.get("include_quarantined", False))
        default_max_trust = int(TrustTier.UNTRUSTED_EXTERNAL) if include_quarantined else self.policy.max_trust_tier
        max_trust = int(filt.get("max_trust_tier", filt.get("min_trust_tier", default_max_trust)))
        max_sensitivity = int(filt.get("max_sensitivity", 10))
        candidates: list[Hit] = []
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                self._set_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    SELECT cid, tenant_id, branch, content, trust_tier, sensitivity, source_type
                    FROM evidence
                    WHERE tenant_id = %s AND branch = %s AND erased = false
                      AND trust_tier <= %s AND sensitivity <= %s
                      AND (%s OR NOT (metadata ? 'quarantine_reason'))
                    """,
                    (db_tenant_id, branch, max_trust, max_sensitivity, include_quarantined),
                )
                for row in cur.fetchall():
                    text = row["content"] or ""
                    score = lexical_score(query, text)
                    if score > 0:
                        cid = _bytes_to_cid(row["cid"])
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
                                metadata={"source_type": row["source_type"]},
                            )
                        )
                cur.execute(
                    """
                    SELECT id, tenant_id, branch, subject, predicate, object, confidence,
                      source_evidence_cids, trust_tier, sensitivity
                    FROM assertions
                    WHERE tenant_id = %s AND branch = %s AND status IN ('active', 'contested')
                      AND trust_tier <= %s AND sensitivity <= %s
                    """,
                    (db_tenant_id, branch, max_trust, max_sensitivity),
                )
                for row in cur.fetchall():
                    text = f"{row['subject']} {row['predicate']} {row['object']}"
                    score = lexical_score(query, text) * float(row["confidence"])
                    if score > 0:
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
                            )
                        )
        return sorted(candidates, key=lambda item: item.score, reverse=True)[:k]

    def _audit(self, cur: Any, tenant_id: str, actor: str, op: str, target_id: str | None, diff: dict[str, Any]) -> None:
        target_uuid = _uuid_or_none(target_id)
        audit_diff = dict(diff)
        if target_id and not target_uuid:
            audit_diff.setdefault("target_id", target_id)
        cur.execute(
            """
            INSERT INTO audit_log(tenant_id, actor, op, target_id, diff)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (tenant_id, actor, op, target_uuid, self._jsonb(audit_diff)),
        )

    def _rrf(self, ranked_lists: list[list[Hit]], k: int) -> list[Hit]:
        by_id: dict[tuple[str, str], Hit] = {}
        scores: dict[tuple[str, str], float] = defaultdict(float)
        channels: dict[tuple[str, str], list[str]] = defaultdict(list)
        channel_scores: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
        for ranked in ranked_lists:
            for rank, hit in enumerate(ranked, start=1):
                key = (hit.kind, hit.id)
                by_id[key] = hit
                scores[key] += 1.0 / (self.policy.rrf_k + rank)
                channels[key].append(hit.channel)
                channel_scores[key][hit.channel] = max(channel_scores[key].get(hit.channel, 0.0), hit.score)
        fused = []
        for key, hit in by_id.items():
            item = Hit(
                id=hit.id,
                kind=hit.kind,
                tenant_id=hit.tenant_id,
                branch=hit.branch,
                text=hit.text,
                score=scores[key],
                channel="+".join(sorted(set(channels[key]))),
                provenance=list(hit.provenance),
                trust_tier=hit.trust_tier,
                sensitivity=hit.sensitivity,
                metadata={
                    **hit.metadata,
                    "channels": sorted(set(channels[key])),
                    "channel_scores": dict(sorted(channel_scores[key].items())),
                },
            )
            fused.append(item)
        return sorted(fused, key=lambda item: item.score, reverse=True)[:k]

    def _mmr(self, query: str, hits: list[Hit], k: int) -> list[Hit]:
        selected: list[Hit] = []
        remaining = list(hits)
        query_vec = hashing_embedding(query)
        while remaining and len(selected) < k:
            best: Hit | None = None
            best_score = float("-inf")
            for hit in remaining:
                relevance = cosine(query_vec, hashing_embedding(hit.text))
                diversity_penalty = 0.0
                if selected:
                    diversity_penalty = max(cosine(hashing_embedding(hit.text), hashing_embedding(item.text)) for item in selected)
                score = self.policy.mmr_lambda * relevance - (1.0 - self.policy.mmr_lambda) * diversity_penalty
                score += hit.score
                if score > best_score:
                    best = hit
                    best_score = score
            if best is None:
                break
            selected.append(best)
            remaining.remove(best)
        return selected

    @staticmethod
    def _u_curve_order(hits: list[Hit]) -> list[Hit]:
        front: list[Hit] = []
        back: list[Hit] = []
        for idx, hit in enumerate(hits):
            if idx % 2 == 0:
                front.append(hit)
            else:
                back.insert(0, hit)
        return front + back

    @staticmethod
    def _fit_budget(hits: list[Hit], budget: int) -> tuple[list[Hit], int]:
        kept: list[Hit] = []
        used = 0
        for hit in hits:
            cost = approx_tokens(hit.text)
            if used + cost > budget:
                continue
            kept.append(hit)
            used += cost
        return kept, used

    @staticmethod
    def _confidence(hits: list[Hit]) -> float:
        if not hits:
            return 0.0
        weighted = 0.0
        total = 0.0
        for hit in hits:
            trust = trust_weight(hit.trust_tier)
            base = float(hit.metadata.get("confidence", 0.7))
            weighted += max(hit.score, 0.01) * trust * base
            total += max(hit.score, 0.01)
        return max(0.0, min(1.0, weighted / max(total, 0.01)))


def _cid_to_bytes(cid: str) -> bytes:
    return bytes.fromhex(cid.removeprefix("cidv1:"))


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
    if not data.get("target_id") and isinstance(diff, dict) and diff.get("target_id"):
        data["target_id"] = diff["target_id"]
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


def _row_to_evidence(row: dict[str, Any], cid: str) -> Evidence:
    metadata = dict(row["metadata"] or {})
    return Evidence(
        tenant_id=str(row.get("tenant_name") or metadata.get("_external_tenant_id") or row["tenant_id"]),
        user_id=str(metadata.get("_external_user_id") or row["user_id"]),
        actor=row["actor"],
        source_type=row["source_type"],
        source_identity=row["source_identity"],
        session_id=str(row["session_id"]) if row["session_id"] else None,
        content=row["content"] or "",
        metadata=metadata,
        content_pointer=row["content_pointer"],
        modality=row["modality"],
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
        user_id=str(row["user_id"]) if row["user_id"] else None,
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
        user_id=str(row["user_id"]),
        category=row["category"],
        statement=row["statement"],
        scope=dict(row["scope"] or {}),
        confidence=float(row["confidence"]),
        explicit=bool(row["explicit"]),
        exceptions=dict(row["exceptions"] or {}),
        source_evidence_cids=_bytes_list_to_cids(row["source_evidence_cids"]),
        valid_from=parse_dt(row["valid_from"]) or utc_now(),
        valid_to=parse_dt(row["valid_to"]),
        status=row["status"],
    )
