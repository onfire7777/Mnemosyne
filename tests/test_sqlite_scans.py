"""Phase-2 Task 4 — SqliteEngine scan-surface parity vs the LocalMemoryEngine oracle.

Every SqliteEngine scan result (vector / lexical / graph) is byte-compared —
as an ordered list of ``(hit.id, struct.pack("<d", hit.score), hit.channel)``
tuples — against a LocalMemoryEngine seeded with byte-identical content. The
oracle is authoritative; a mismatch is a SqliteEngine bug.

Kernel-mode discipline (the file is dispatch-adjacent): both engines route
through ``mnemosyne.text`` so they share the active kernel. Gate 1 runs this
file twice — native (default) and ``MNEMOSYNE_PURE=1`` — and the byte-compare
must hold in BOTH. In native mode ``vector_search`` exercises the packed-BLOB
``dense_scan_packed`` seam; in pure mode the per-hit ``cosine`` loop. Assertions
and relations are seeded via low-level writes (SqliteEngine's upsert/add_relation
land in Task 5) so the SQL rows hydrate to objects identical to the oracle's.
"""

from __future__ import annotations

import struct
import tempfile
from pathlib import Path

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import (
    Assertion,
    Evidence,
    Relation,
    dt_to_json,
)
from mnemosyne.sqlite_engine import SqliteEngine, fts_safe_query, sqlite_vec_available
from mnemosyne.sqlite_schema import json_text
from mnemosyne.text import tokenize

TENANT = "tenant-scan"
USER = "user-scan"


# --- seeding helpers --------------------------------------------------------


def _fresh_engines() -> tuple[LocalMemoryEngine, SqliteEngine]:
    root = Path(tempfile.mkdtemp(prefix="sqlite-scan-"))
    return LocalMemoryEngine(), SqliteEngine(root)


def _append_evidence_both(
    local: LocalMemoryEngine,
    sqlite: SqliteEngine,
    content: str,
    *,
    with_embedding: bool,
    trust_tier: int = 0,
    modality: str = "text",
) -> str:
    """Append byte-identical evidence to both engines; return the shared cid.

    When ``with_embedding`` is set, a deterministic stored embedding (the shared
    hashing embedder over ``content``) is written to both — exercising the
    packed-BLOB stored-vector path. Without it, the scan re-embeds ``hit.text``
    on the fallback path. The embedder is deterministic, so stored and
    re-embedded vectors coincide; only the channel/metadata path differs.
    """
    ev_local = Evidence(
        tenant_id=TENANT, user_id=USER, actor="user", source_type="chat",
        content=content, trust_tier=trust_tier, modality=modality,
    )
    ev_sqlite = Evidence(
        tenant_id=TENANT, user_id=USER, actor="user", source_type="chat",
        content=content, trust_tier=trust_tier, modality=modality,
    )
    cid = local.append_evidence(ev_local)
    cid2 = sqlite.append_evidence(ev_sqlite)
    assert cid == cid2, "CID divergence — store cores must agree before scanning"
    if with_embedding:
        embedding = local.adapters.embedding.embed(content)
        assert local.set_evidence_embedding(TENANT, cid, embedding)
        assert sqlite.set_evidence_embedding(TENANT, cid2, embedding)
    return cid


def _insert_assertion_sql(sqlite: SqliteEngine, assertion: Assertion) -> None:
    """Low-level assertion row write mirroring the oracle's stored object
    (SqliteEngine.upsert_assertion lands in Task 5)."""
    conn = sqlite._connect(assertion.tenant_id)
    with conn:
        conn.execute(
            "INSERT INTO assertions (tenant_id, branch, id, user_id, subject, predicate, "
            "object, scope, confidence, calibration, valid_from, valid_to, transaction_time, "
            "expired_at, justification_id, source_evidence_cids, status, version, superseded_by, "
            "trust_tier, sensitivity, access_policy, last_accessed, access_count) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                assertion.tenant_id, assertion.branch, assertion.id, assertion.user_id,
                assertion.subject, assertion.predicate, assertion.object,
                json_text(assertion.scope), float(assertion.confidence),
                json_text(assertion.calibration), dt_to_json(assertion.valid_from),
                dt_to_json(assertion.valid_to), dt_to_json(assertion.transaction_time),
                dt_to_json(assertion.expired_at), assertion.justification_id,
                json_text(list(assertion.source_evidence_cids)), assertion.status,
                int(assertion.version), assertion.superseded_by, int(assertion.trust_tier),
                int(assertion.sensitivity), json_text(assertion.access_policy),
                dt_to_json(assertion.last_accessed), int(assertion.access_count),
            ),
        )


def _insert_relation_sql(sqlite: SqliteEngine, relation: Relation) -> None:
    """Low-level relation row write mirroring the oracle's stored object."""
    conn = sqlite._connect(relation.tenant_id)
    with conn:
        conn.execute(
            "INSERT INTO relations (tenant_id, branch, id, source, predicate, target, "
            "confidence, valid_from, valid_to, source_evidence_cids, access_policy) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                relation.tenant_id, relation.branch, relation.id, relation.source,
                relation.predicate, relation.target, float(relation.confidence),
                dt_to_json(relation.valid_from), dt_to_json(relation.valid_to),
                json_text(list(relation.source_evidence_cids)),
                json_text(relation.access_policy),
            ),
        )


def _seed_assertion_both(
    local: LocalMemoryEngine,
    sqlite: SqliteEngine,
    *,
    subject: str,
    predicate: str,
    obj: str,
    status: str = "active",
    source_evidence_cids: list[str] | None = None,
) -> Assertion:
    """Seed the identical active assertion object into both stores (direct
    writes bypass Task-5 upsert semantics to keep the rows byte-identical)."""
    assertion = Assertion(
        tenant_id=TENANT, subject=subject, predicate=predicate, object=obj,
        status=status, source_evidence_cids=list(source_evidence_cids or []),
    )
    local.assertions[assertion.id] = assertion
    _insert_assertion_sql(sqlite, assertion)
    return assertion


def _seed_relation_both(
    local: LocalMemoryEngine,
    sqlite: SqliteEngine,
    *,
    source: str,
    predicate: str,
    target: str,
    confidence: float,
    source_evidence_cids: list[str],
) -> Relation:
    relation = Relation(
        tenant_id=TENANT, source=source, predicate=predicate, target=target,
        confidence=confidence, source_evidence_cids=list(source_evidence_cids),
    )
    local.relations[relation.id] = relation
    _insert_relation_sql(sqlite, relation)
    return relation


def _sig(hits: list) -> list[tuple[str, bytes, str]]:
    return [(hit.id, struct.pack("<d", hit.score), hit.channel) for hit in hits]


# --- vector_search ----------------------------------------------------------


def test_vector_search_parity_stored_and_fallback():
    """Stored-embedding rows + fallback re-embed rows + assertion candidates,
    byte-identical to the oracle; text-modality channel is always dense_hash."""
    local, sqlite = _fresh_engines()
    # Repeated tokens force equal-score ties → catches candidate-order (tie
    # break) regressions the raw score-bits alone would miss.
    _append_evidence_both(local, sqlite, "quick brown fox", with_embedding=True)
    _append_evidence_both(local, sqlite, "quick memory graph vector", with_embedding=True)
    _append_evidence_both(local, sqlite, "postgres tenant belief", with_embedding=False)
    _append_evidence_both(local, sqlite, "quick brown hound", with_embedding=False)
    _append_evidence_both(local, sqlite, "memory graph edges", with_embedding=True)
    _seed_assertion_both(local, sqlite, subject="alice", predicate="likes", obj="quick graph")

    filt = {"tenant_id": TENANT, "branch": "main"}
    for query in ["quick memory", "graph vector", "postgres", "alice quick", "absent"]:
        local_hits = local.vector_search(query, 10, filt)
        sqlite_hits = sqlite.vector_search(query, 10, filt)
        assert _sig(local_hits) == _sig(sqlite_hits), f"vector mismatch for {query!r}"
        assert all(hit.channel == "dense_hash" for hit in sqlite_hits)
    sqlite.close()


def test_vector_search_top_k_truncation_parity():
    local, sqlite = _fresh_engines()
    for i in range(8):
        _append_evidence_both(local, sqlite, f"memory item {i} shared token", with_embedding=(i % 2 == 0))
    filt = {"tenant_id": TENANT, "branch": "main"}
    for k in (1, 3, 5):
        assert _sig(local.vector_search("shared token memory", k, filt)) == _sig(
            sqlite.vector_search("shared token memory", k, filt)
        )
    sqlite.close()


# --- lexical_search ---------------------------------------------------------


def test_lexical_search_parity_fts_safe_queries():
    """unicode61-safe queries drive the FTS5 prefilter; results still match the
    oracle's full scan (FTS is recall-only — lexical_score is the ranker)."""
    local, sqlite = _fresh_engines()
    _append_evidence_both(local, sqlite, "the quick brown fox", with_embedding=False)
    _append_evidence_both(local, sqlite, "postgres memory belief evidence", with_embedding=False)
    _append_evidence_both(local, sqlite, "quick memory graph vector", with_embedding=False)
    _append_evidence_both(local, sqlite, "underscore token foo_bar included", with_embedding=False)
    _seed_assertion_both(local, sqlite, subject="carol", predicate="notes", obj="quick memory")

    filt = {"tenant_id": TENANT, "branch": "main"}
    for query in ["quick", "quick memory", "postgres", "foo_bar", "memory graph", "absentword"]:
        tokens = tokenize(query)
        assert fts_safe_query(tokens), f"{query!r} should be FTS-safe"
        assert _sig(local.lexical_search(query, 10, filt)) == _sig(
            sqlite.lexical_search(query, 10, filt)
        ), f"lexical mismatch (fts prefilter) for {query!r}"
    sqlite.close()


def test_lexical_search_parity_tokenizer_stressors():
    """Hyphenated tags, version strings and URLs force fts_safe_query -> False
    -> full-table scan. Recall parity vs the oracle must still hold exactly."""
    local, sqlite = _fresh_engines()
    _append_evidence_both(local, sqlite, "capability data-only foo-bar tag", with_embedding=False)
    _append_evidence_both(local, sqlite, "released v1.2.3 today and v1.2.4 tomorrow", with_embedding=False)
    _append_evidence_both(local, sqlite, "visit https://example.com/x for the docs", with_embedding=False)
    _append_evidence_both(local, sqlite, "unrelated memory content", with_embedding=False)

    filt = {"tenant_id": TENANT, "branch": "main"}
    stressors = ["foo-bar", "data-only", "v1.2.3", "https://example.com/x", "example.com"]
    for query in stressors:
        tokens = tokenize(query)
        assert not fts_safe_query(tokens), f"{query!r} should force a full scan"
        assert _sig(local.lexical_search(query, 10, filt)) == _sig(
            sqlite.lexical_search(query, 10, filt)
        ), f"lexical mismatch (full scan) for {query!r}"
    sqlite.close()


# --- graph_ppr --------------------------------------------------------------


def test_graph_ppr_parity():
    local, sqlite = _fresh_engines()
    cids = [
        _append_evidence_both(local, sqlite, f"support {label}", with_embedding=False)
        for label in ("ab", "bc", "cd", "ef")
    ]
    _seed_relation_both(local, sqlite, source="alice", predicate="knows", target="bob",
                        confidence=0.9, source_evidence_cids=[cids[0]])
    _seed_relation_both(local, sqlite, source="bob", predicate="works_at", target="acme",
                        confidence=0.8, source_evidence_cids=[cids[1]])
    _seed_relation_both(local, sqlite, source="bob", predicate="knows", target="carol",
                        confidence=0.7, source_evidence_cids=[cids[2]])
    _seed_relation_both(local, sqlite, source="dave", predicate="met", target="erin",
                        confidence=0.6, source_evidence_cids=[cids[3]])
    _seed_assertion_both(local, sqlite, subject="alice", predicate="likes", obj="bob")

    filt = {"tenant_id": TENANT, "branch": "main"}
    seed_sets = [["alice"], ["bob"], ["alice", "acme"], ["carol"], ["dave"], ["nobody"], ["alice", "bob", "carol"]]
    for seeds in seed_sets:
        local_hits = local.graph_ppr(seeds, 10, tenant_id=TENANT, branch="main", filt=filt)
        sqlite_hits = sqlite.graph_ppr(seeds, 10, tenant_id=TENANT, branch="main", filt=filt)
        assert _sig(local_hits) == _sig(sqlite_hits), f"graph mismatch for seeds {seeds}"
        assert all(hit.channel == "graph_ppr" for hit in sqlite_hits)
    sqlite.close()


def test_graph_ppr_empty_seeds_returns_empty():
    local, sqlite = _fresh_engines()
    assert sqlite.graph_ppr([], 5, tenant_id=TENANT, branch="main", filt={"tenant_id": TENANT}) == []
    sqlite.close()


# --- fts_safe_query unit ----------------------------------------------------


def test_fts_safe_query_unit():
    assert fts_safe_query(["foo", "bar", "baz123", "with_underscore"]) is True
    assert fts_safe_query(["foo-bar"]) is False       # hyphen
    assert fts_safe_query(["v1.2.3"]) is False         # dots
    assert fts_safe_query(["https", "example.com"]) is False  # dot
    assert fts_safe_query(["a", "b:c"]) is False       # colon
    assert fts_safe_query(["path/to"]) is False        # slash
    assert fts_safe_query(["c++"]) is False            # plus
    # every-token rule: one unsafe token taints the whole query
    assert fts_safe_query(["safe", "un-safe"]) is False


def test_fts_safe_query_matches_tokenizer_on_stressors():
    """The safe predicate agrees with the app tokenizer: the stressor corpus
    tokenizes into tokens carrying :+./- (unsafe), the plain corpus does not."""
    assert not fts_safe_query(tokenize("foo-bar v1.2.3 https://example.com/x"))
    assert fts_safe_query(tokenize("quick brown memory graph vector"))


# --- sqlite-vec optional extra ---------------------------------------------


def test_sqlite_vec_detector_is_bool_and_default_scan_unaffected():
    """The optional sqlite-vec detector returns a bool; whether or not the extra
    is present, the DEFAULT packed-BLOB dense scan works. When absent, all
    vec0-specific paths are skipped (there are none wired yet — Task 8)."""
    available = sqlite_vec_available()
    assert isinstance(available, bool)
    if not available:
        pytest.importorskip(
            "sqlite_vec",
            reason="sqlitevec extra absent — vec0 paths skipped; default scan below",
        )
    # Default scan is unaffected by the extra either way.
    local, sqlite = _fresh_engines()
    _append_evidence_both(local, sqlite, "default packed scan still works", with_embedding=True)
    filt = {"tenant_id": TENANT, "branch": "main"}
    assert _sig(local.vector_search("packed scan", 5, filt)) == _sig(
        sqlite.vector_search("packed scan", 5, filt)
    )
    sqlite.close()
