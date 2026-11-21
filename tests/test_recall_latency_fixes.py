"""Regression tests for recall & retrieval latency optimizations and parity invariants."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from mnemosyne.access_policy import may_read_item
from mnemosyne.cid_lists import CidList
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.writer import LearningWriter
from mnemosyne.hosts.query_embedding import ScopedQueryEmbeddingProvider
from mnemosyne.models import Evidence, Hit, Relation
from mnemosyne.passages import PassageGraph, PassageIndex
from mnemosyne.policy import OperatingPolicy
from mnemosyne.retrieval import _evidence_sources_readable
from mnemosyne.sqlite_engine import SqliteEngine
from mnemosyne.text import (
    _hashing_embedding_pure,
    _lexical_score_pure,
    _tokenize_pure,
    hashing_embedding,
    lexical_scan,
    lexical_score,
    tokenize,
)


def test_separator_only_non_ascii_exact_parity():
    cases = [
        "hello — world … “smart quotes” ‘single’ • bullet\u00a0nbsp",
        "path/to/file.py → line 42 – fixed\u200bzero-width",
        "café naïve résumé 日本語 🚀 emoji — mixed",
        "plain ascii 12345_test",
        "— – … • ★ ☆ → ←",
    ]
    queries = [
        "hello world smart quotes",
        "path line fixed",
        "café résumé — mixed",
        "ascii 12345",
    ]
    for text in cases:
        assert tokenize(text) == _tokenize_pure(text)
        assert hashing_embedding(text, 256) == list(_hashing_embedding_pure(text, 256))
    for query in queries:
        expected = [_lexical_score_pure(query, text) for text in cases]
        assert [lexical_score(query, text) for text in cases] == expected
        assert lexical_scan(query, cases) == expected


def test_fts_trigger_skips_metadata_only_record_access(tmp_path):
    eng = SqliteEngine(tmp_path / "store")
    try:
        cid = eng.append_evidence(
            Evidence(
                tenant_id="t1",
                user_id="u1",
                actor="user",
                source_type="note",
                content="quantum memory latency optimization benchmark",
            )
        )
        conn = eng._connect("t1")
        changes_before = conn.total_changes
        hit = Hit(
            id=cid,
            kind="evidence",
            tenant_id="t1",
            branch="main",
            text="quantum memory latency optimization benchmark",
            score=1.0,
            channel="lexical",
            provenance=[cid],
        )
        eng._record_retrieval_access([hit])
        changes_after = conn.total_changes
        # Metadata-only UPDATE updates evidence + memory_source_revisions +
        # memory_source_changes without firing FTS5 delete+insert shadow table writes.
        assert changes_after - changes_before <= 5
        hits = eng.lexical_search("quantum latency", 5, {"tenant_id": "t1"})
        assert [h.id for h in hits] == [cid]
    finally:
        eng.close()


def test_graph_oracle_reuses_on_lifecycle_update_and_invalidates_on_custody_change(tmp_path):
    eng = SqliteEngine(tmp_path / "store")
    try:
        cid = eng.append_evidence(
            Evidence(
                tenant_id="t1",
                user_id="u1",
                actor="user",
                source_type="note",
                content="apollo connects to artemis",
            )
        )
        eng.add_relation(
            Relation(
                tenant_id="t1",
                source="apollo",
                predicate="connects_to",
                target="artemis",
                source_evidence_cids=[cid],
            )
        )
        oracle_1 = eng._graph_oracle("t1", "main", {"tenant_id": "t1"})
        rel = next(iter(oracle_1.relations.values()))
        assert type(rel.source_evidence_cids) is CidList

        # Lifecycle-only metadata write (_record_retrieval_access) keeps memoized graph oracle.
        hit = Hit(
            id=cid,
            kind="evidence",
            tenant_id="t1",
            branch="main",
            text="apollo connects to artemis",
            score=1.0,
            channel="lexical",
            provenance=[cid],
        )
        eng._record_retrieval_access([hit])
        oracle_2 = eng._graph_oracle("t1", "main", {"tenant_id": "t1"})
        assert oracle_2 is oracle_1

        # Custody-relevant write (forget) immediately invalidates the graph oracle.
        eng.forget("t1", cid)
        oracle_3 = eng._graph_oracle("t1", "main", {"tenant_id": "t1"})
        assert oracle_3 is not oracle_1
        assert not eng.graph_ppr(["apollo"], 5, tenant_id="t1", branch="main", filt={"tenant_id": "t1"})
    finally:
        eng.close()


def test_learning_store_cow_isolation_and_rollback_safety(tmp_path):
    eng = SqliteEngine(tmp_path / "store")
    try:
        writer = LearningWriter(eng)
        store = writer.store
        writer.apply(
            "t1",
            "test_seed",
            lambda state: state["episodes"].__setitem__(
                "ep-1", {"episode_id": "ep-1", "status": "open", "tool_events": [{"k": 1}]}
            ),
        )
        snap = store.read("t1")
        assert snap["episodes"]["ep-1"]["status"] == "open"
        # Mutating returned snapshot must not leak into subsequent reads.
        snap["episodes"]["ep-1"]["status"] = "mutated-locally"
        snap["episodes"]["ep-1"]["tool_events"].append({"k": 2})

        fresh = store.read("t1")
        assert fresh["episodes"]["ep-1"]["status"] == "open"
        assert fresh["episodes"]["ep-1"]["tool_events"] == [{"k": 1}]

        # Failed mutation inside apply must roll back cleanly and not poison cache.
        try:
            def failing(state):
                state["episodes"]["ep-1"]["status"] = "corrupted"
                raise RuntimeError("boom")

            writer.apply("t1", "test_fail", failing)
        except RuntimeError:
            pass
        after_fail = store.read("t1")
        assert after_fail["episodes"]["ep-1"]["status"] == "open"
    finally:
        eng.close()


def test_scoped_query_embedding_inflight_dedup_and_prefetch():
    calls = 0
    started = threading.Event()
    release = threading.Event()

    @dataclass
    class SlowEmbedder:
        dims: int = 4
        name: str = "slow-test"
        query_prefix: str = "q: "

        def embed_query(self, text: str) -> list[float]:
            nonlocal calls
            calls += 1
            started.set()
            release.wait(timeout=2.0)
            return [1.0, 0.0, 0.0, 0.0]

        def embed(self, text: str) -> list[float]:
            return self.embed_query(text)

        def embed_sensitive(self, text: str) -> list[float]:
            return self.embed_query(text)

    provider = ScopedQueryEmbeddingProvider(SlowEmbedder())
    results: list[list[float]] = []

    def worker():
        results.append(provider.embed_query("shared query"))

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    assert started.wait(timeout=1.0)
    t2.start()
    time.sleep(0.05)
    release.set()
    t1.join(timeout=2.0)
    t2.join(timeout=2.0)

    assert calls == 1
    assert len(results) == 2
    assert results[0] == [1.0, 0.0, 0.0, 0.0]
    assert results[1] == [1.0, 0.0, 0.0, 0.0]

    # Prefetch populates cache asynchronously for subsequent foreground lookup.
    provider.prefetch_query("prefetched query")
    vec = provider.embed_query("prefetched query")
    assert vec == [1.0, 0.0, 0.0, 0.0]
    assert calls == 2


def test_passage_graph_lazy_stats_materializes_on_demand():
    texts = [
        "alpha beta gamma delta epsilon",
        "alpha beta zeta eta theta",
    ]
    index = PassageIndex(texts)
    graph = index.passage_graph
    assert len(graph._pending_stats) == 2
    assert graph._total_passages == 2
    # Calling statistical methods lazily materializes identical IDF and co-occurrences.
    eager = PassageGraph(lazy_stats=False)
    for rec in graph._passage_records.values():
        eager.add_passage(rec)
    assert graph.get_live_idf("alpha") == eager.get_live_idf("alpha")
    assert not graph._pending_stats
    assert graph.get_corpus_cooccurrences("alpha") == eager.get_corpus_cooccurrences("alpha")


def test_readonly_custody_honors_monkeypatched_get_evidence_and_empty_policy():
    eng = LocalMemoryEngine()
    cid = eng.append_evidence(
        Evidence(
            tenant_id="t1",
            user_id="u1",
            actor="user",
            source_type="note",
            content="visible note",
        )
    )
    called = 0
    orig = eng.get_evidence

    def spy(tenant_id, item_cid, branch="main"):
        nonlocal called
        called += 1
        return orig(tenant_id, item_cid, branch)

    eng.get_evidence = spy
    assert _evidence_sources_readable(
        eng,
        [(cid, None, False)],
        tenant_id="t1",
        branch="main",
        filt={"tenant_id": "t1"},
        policy=OperatingPolicy(),
    )
    assert called == 1

    # Verify empty-policy fast path in may_read_item matches security rules.
    assert may_read_item(
        item_tenant_id="t1", sensitivity=1, access_policy={}, context={"tenant_id": "t1"}, policy_max_sensitivity=2
    ).allowed
    assert not may_read_item(
        item_tenant_id="t1", sensitivity=2, access_policy={}, context={"tenant_id": "t1", "role": "operator"}, policy_max_sensitivity=3
    ).allowed
    assert not may_read_item(
        item_tenant_id="t1", sensitivity=0, access_policy={}, context={"tenant_id": "other"}, policy_max_sensitivity=2
    ).allowed
