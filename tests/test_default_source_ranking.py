"""Source-only local search keeps scoped BM25 relevance without changing other routes."""

from dataclasses import replace
from datetime import datetime

import pytest

from mnemosyne import pipeline
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Assertion, Evidence, Hit
from mnemosyne.policy import OperatingPolicy
from mnemosyne.retrieval import HashingEmbeddingProvider, LocalSimilarityReranker
from mnemosyne.sqlite_engine import SqliteEngine


AT = "2026-10-22T12:00:00Z"


def append(engine, text, *, tenant="t", **kwargs):
    return engine.append_evidence(Evidence(
        tenant_id=tenant, user_id="u", actor="user", source_type="document",
        content=text, trust_tier=0, access_policy=kwargs.pop("access_policy", {"tenant": tenant}),
        **kwargs,
    ))


@pytest.fixture(params=["local", "sqlite"])
def engine(request, tmp_path):
    policy = OperatingPolicy(top_k=3)
    value = (SqliteEngine(tmp_path / "db", policy=policy) if request.param == "sqlite"
             else LocalMemoryEngine(policy=policy))
    yield value
    if request.param == "sqlite":
        value.close()


def retrieve(engine, query="quasar observatory", **kwargs):
    filt = {"evaluated_at": AT, **kwargs.pop("filt", {})}
    return engine.retrieve(query, tenant_id="t", filt=filt, record_access=False, **kwargs)


def test_default_recovers_long_rare_term_sources_beyond_channel_cutoff(engine, monkeypatch):
    relevant = {
        append(engine, "The quasar observatory is in Cedar Valley. "
               + "Astronomy field notes discuss weather and equipment. " * 20),
        append(engine, "A quasar observatory visit is scheduled. "
               + "Visitors should wear sturdy boots. " * 20),
    }
    for number in range(120):
        append(engine, f"Where is the meeting? The meeting is in room {number}.")
    query = "Where is the quasar observatory?"
    old_candidates = engine.lexical_search(query, engine.policy.rerank_width, {"tenant_id": "t"})
    assert relevant.isdisjoint(hit.id for hit in old_candidates)

    widths = []
    lexical_search = engine.lexical_search

    def record_width(query, k, filt):
        if filt.get("query_mode") == "passages":
            widths.append(k)
        return lexical_search(query, k, filt)

    monkeypatch.setattr(engine, "lexical_search", record_width)
    result = retrieve(engine, query)
    assert {hit.id for hit in result.hits[:2]} == relevant
    assert len(result.hits) == engine.policy.top_k
    assert widths == [100]
    assert result.explain["source_only_local_fallback"] == {
        "applied": True, "ranker": "scoped_bm25", "score_scale": "bm25",
        "candidate_width": 100, "candidate_count": 100,
    }
    assert "query_mode" not in result.explain
    assert result.explain["activation"]["applied"] is False
    scores = [hit.score for hit in result.hits]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] > 1  # BM25 is deliberately not called a probability or cosine.
    assert all(hit.metadata["score_scale"] == "bm25" for hit in result.hits)
    threshold = result.explain["confidence"]["threshold"]
    assert result.explain["confidence"]["prediction_set_size"] == sum(
        score >= max(scores) * threshold for score in scores
    )
    assert 0 <= result.confidence <= 1


def test_default_bm25_reauthorizes_index_and_erasure(engine):
    public = append(engine, "Quasar observatory public notes")
    secret = append(engine, "Quasar observatory classified coordinates", sensitivity=1,
                    access_policy={"tenant": "t", "allow_principals": ["owner"]})
    append(engine, "Quasar observatory other tenant", tenant="other")
    owner = retrieve(engine, filt={"user_id": "owner", "max_sensitivity": 3})
    assert secret in {hit.id for hit in owner.hits}
    guest = retrieve(engine, filt={"user_id": "guest"})
    assert [hit.id for hit in guest.hits] == [public]
    assert engine._passage_bm25_index.texts == ("Quasar observatory public notes",)
    added = append(engine, "Quasar observatory new public measurements")
    assert {hit.id for hit in retrieve(engine, filt={"user_id": "guest"}).hits} == {public, added}
    engine.forget("t", public)
    assert engine._passage_bm25_index is None
    assert [hit.id for hit in retrieve(engine, filt={"user_id": "guest"}).hits] == [added]
    assert engine._passage_bm25_index.texts == ("Quasar observatory new public measurements",)


def test_default_bm25_indexes_only_redacted_content(engine):
    append(engine, "Quasar observatory; secret: hidden-coordinate",
           access_policy={"tenant": "t", "redact_fields": ["secret"],
                          "min_role_for_raw": "operator"})
    result = retrieve(engine)
    assert len(result.hits) == 1
    assert "hidden-coordinate" not in result.hits[0].text
    assert result.hits[0].metadata["privacy"]["redacted"]
    assert engine._passage_bm25_index.texts == (result.hits[0].text,)
    assert "hidden-coordinate" not in engine._passage_bm25_index.postings


def forbid_passage_scan(monkeypatch, engine):
    def forbidden(*args, **kwargs):
        pytest.fail("source-only fallback must not replace this retrieval route")
    monkeypatch.setattr(engine, "passage_candidates", forbidden)


def test_mixed_assertion_route_keeps_existing_reranker(engine, monkeypatch):
    source = append(engine, "Quasar observatory is in Cedar Valley.")
    assertion = engine.upsert_assertion(Assertion(
        tenant_id="t", user_id="u", subject="Quasar observatory", predicate="is in",
        object="Cedar Valley", status="active", source_evidence_cids=[source],
        access_policy={"tenant": "t"},
    ))
    forbid_passage_scan(monkeypatch, engine)
    result = retrieve(engine)
    assert assertion in {hit.id for hit in result.hits}
    assert "source_only_local_fallback" not in result.explain
    assert all("rerank" in hit.channel for hit in result.hits)


@pytest.mark.parametrize("route", ["graph", "working", "prospective"])
def test_nonempty_additional_routes_are_not_replaced(engine, monkeypatch, route):
    append(engine, "Quasar observatory notes")
    extra = Hit(id="extra", kind="relation", tenant_id="t", branch="main",
                text="Quasar observatory directions", score=1, channel=route,
                provenance=[], trust_tier=0, sensitivity=0)
    if route == "graph":
        monkeypatch.setattr(engine, "graph_ppr", lambda *a, **kw: [extra])
    elif route == "working":
        monkeypatch.setattr(pipeline, "_working_memory_route", lambda *a, **kw: ([extra], {}))
    else:
        monkeypatch.setattr(pipeline, "prospective_memory_hits", lambda *a, **kw: [extra])
    forbid_passage_scan(monkeypatch, engine)
    result = retrieve(engine)
    assert "extra" in {hit.id for hit in result.hits}
    assert "source_only_local_fallback" not in result.explain


@pytest.mark.parametrize("provider", ["embedding", "reranker", "lexical", "graph"])
def test_custom_provider_routes_are_not_replaced(engine, monkeypatch, provider):
    append(engine, "Quasar observatory notes")

    # Keep familiar names to ensure provider identity, not a display string, controls bypass.
    class OtherEmbedding(HashingEmbeddingProvider):
        pass

    class OtherReranker(LocalSimilarityReranker):
        pass

    class EmptyRetriever:
        def search(self, *args, **kwargs):
            return []

    if provider == "embedding":
        engine.adapters = replace(engine.adapters, embedding=OtherEmbedding())
    elif provider == "reranker":
        engine.adapters = replace(engine.adapters, reranker=OtherReranker())
    elif provider == "lexical":
        engine.adapters = replace(engine.adapters, lexical_retriever=EmptyRetriever())
    else:
        engine.adapters = replace(engine.adapters, graph_retriever=EmptyRetriever())
    forbid_passage_scan(monkeypatch, engine)
    assert "source_only_local_fallback" not in retrieve(engine).explain


@pytest.mark.parametrize("kwargs", [{"deep": True}, {"filt": {"as_of": datetime.fromisoformat(AT)}}])
def test_deep_and_historical_search_keep_existing_routes(engine, monkeypatch, kwargs):
    append(engine, "Quasar observatory notes")
    forbid_passage_scan(monkeypatch, engine)
    assert "source_only_local_fallback" not in retrieve(engine, **kwargs).explain


def test_empty_search_does_not_build_an_index(engine, monkeypatch):
    forbid_passage_scan(monkeypatch, engine)
    result = retrieve(engine)
    assert result.hits == []
    assert result.abstained


def test_unattested_evidence_hit_does_not_trigger_source_fallback(engine, monkeypatch):
    hit = Hit(id="external-result", kind="evidence", tenant_id="t", branch="main",
              text="Quasar observatory", score=1, channel="dense_hash")
    monkeypatch.setattr(engine, "vector_search", lambda *a, **kw: [hit])
    forbid_passage_scan(monkeypatch, engine)
    result = retrieve(engine)
    assert [selected.id for selected in result.hits] == [hit.id]
    assert "source_only_local_fallback" not in result.explain


def test_multimodal_source_keeps_existing_retrieval(engine, monkeypatch):
    source = append(engine, "Quasar observatory photograph", modality="image")
    forbid_passage_scan(monkeypatch, engine)
    result = retrieve(engine)
    assert source in {hit.id for hit in result.hits}
    assert "source_only_local_fallback" not in result.explain


def test_stored_text_embeddings_keep_existing_retrieval(engine, monkeypatch):
    source = append(engine, "A remote mountain research site.",
                    embedding=engine.adapters.embedding.embed("quasar observatory"))
    forbid_passage_scan(monkeypatch, engine)
    result = retrieve(engine)
    assert source in {hit.id for hit in result.hits}
    assert "source_only_local_fallback" not in result.explain


def test_explicit_confidence_keeps_existing_probability_semantics(engine, monkeypatch):
    append(engine, "Quasar observatory location is Cedar Valley. " + "Research notes. " * 30)
    append(engine, "Quasar observatory opening dates are uncertain. " + "Research notes. " * 30,
           metadata={"confidence": 0.1})
    for number in range(12):
        append(engine, f"Common meeting {number} room notes.")
    forbid_passage_scan(monkeypatch, engine)
    result = retrieve(engine)
    assert len(result.hits) == 2
    assert all("rerank" in hit.channel for hit in result.hits)
    assert result.explain["confidence"]["prediction_set_size"] == 0
    assert result.abstained
    assert "source_only_local_fallback" not in result.explain


def test_explicit_confidence_discovered_beyond_channel_cutoff_keeps_old_route(engine):
    source = append(engine, "The quasar observatory is in Cedar Valley. "
                    + "Astronomy field notes discuss weather and equipment. " * 20,
                    metadata={"confidence": 0.1})
    for number in range(120):
        append(engine, f"Where is the meeting? The meeting is in room {number}.")
    query = "Where is the quasar observatory?"
    filt = {"tenant_id": "t", "branch": "main"}
    for channel in [engine.vector_search, engine.lexical_search]:
        assert source not in {hit.id for hit in channel(query, engine.policy.rerank_width, filt)}
    # This source is newly found by BM25. Its explicit confidence must not make
    # uncalibrated BM25 scores on sibling candidates look like probabilities.
    assert source == engine.lexical_search(query, 100, {**filt, "query_mode": "passages"})[0].id
    result = retrieve(engine, query)
    assert source not in {hit.id for hit in result.hits}
    assert all("rerank" in hit.channel for hit in result.hits)
    assert "source_only_local_fallback" not in result.explain


def test_parallel_and_sequential_source_ranking_match(engine, monkeypatch):
    append(engine, "Quasar observatory is in Cedar Valley.")
    append(engine, "Quasar observation notes.")
    results = []
    for parallel in ["0", "1"]:
        monkeypatch.setenv("MNEMOSYNE_PARALLEL_CHANNELS", parallel)
        results.append(retrieve(engine).to_dict())
    assert results[0] == results[1]
