"""Regression checks for batch provenance and ranked passage custody."""

import pytest

from eval.harness.metrics import resolve_retrieved_doc_ids
from mnemosyne.consolidation import (
    ConsolidationWorker,
    _extract_simple_fact,
    _normalize_candidate,
)
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence
from mnemosyne.policy import OperatingPolicy
from mnemosyne.sqlite_engine import SqliteEngine


def test_batch_membership_is_not_fact_provenance(monkeypatch):
    engine = LocalMemoryEngine()
    cids = [engine.append_evidence(Evidence(
        tenant_id="t", user_id="u", actor="user", source_type="note",
        content=text, trust_tier=0, access_policy={"tenant": "t"},
    )) for text in ["Mars is red.", "Venus is hot."]]
    worker = ConsolidationWorker(engine, [])
    jobs = []

    def capture_jobs(batch, **kwargs):
        jobs.extend(batch)
        return [], {}

    monkeypatch.setattr(worker, "run_jobs", capture_jobs)
    worker.run_queue_payload({"tenant_id": "t", "source_evidence_cids": cids})
    assert jobs
    by_subject = {job.candidate_subject: job.source_evidence_cids for job in jobs}
    assert by_subject == {"Mars": [cids[0]], "Venus": [cids[1]]}


def test_model_extractor_preserves_explicit_citations_and_rejects_ambiguous_batch():
    evidence = [Evidence(tenant_id="t", user_id="u", actor="user",
                         source_type="note", content="Mars is red.", cid=cid)
                for cid in ["a", "b"]]
    row = {"signature": "mars", "query": "Mars", "candidate_subject": "Mars",
           "candidate_predicate": "is", "candidate_object": "red",
           "source_evidence_cids": ["a"]}
    assert _normalize_candidate(row, evidence, {})["source_evidence_cids"] == ["a"]
    for sources in [None, [], ["outside"]]:
        with pytest.raises(ValueError, match="source_evidence_cids"):
            _normalize_candidate({**row, "source_evidence_cids": sources}, evidence, {})


def test_name_cooccurrence_does_not_assert_a_relation():
    assert _extract_simple_fact("Mara, Helios. Mara and Helios.") == []
    assert _extract_simple_fact("Mara owns Helios.") == [("Mara", "owns", "Helios")]


def test_ranked_passages_do_not_expand_provenance_into_corpus_order():
    mapping = {"a": "doc-a", "b": "doc-b", "c": "doc-c"}
    hits = [
        {"id": "b", "provenance": ["a", "b", "c"]},
        {"id": "fact", "provenance": ["a", "b", "c"]},
        {"id": "single-source-fact", "metadata": {"source_evidence_cids": ["c"]}},
        {"id": "a"},
    ]
    assert resolve_retrieved_doc_ids(hits, mapping) == ["doc-b", "doc-c", "doc-a"]


def test_passage_retrieval_uses_rare_terms_and_keeps_rank_two_second():
    engine = LocalMemoryEngine(policy=OperatingPolicy(top_k=3))
    texts = ["Quasar telescope discovers nebula.", "Quasar observation of distant stars."]
    texts += [f"Common telescope observation {i}." for i in range(8)]
    cids = [engine.append_evidence(Evidence(
        tenant_id="t", user_id="u", actor="user", source_type="document",
        content=text, trust_tier=0, access_policy={"tenant": "t"},
    )) for text in texts]
    filt = {"query_mode": "passages", "evaluated_at": "2026-10-07T00:00:00Z"}
    result = engine.retrieve("Quasar telescope", tenant_id="t", filt=filt, record_access=False)
    assert result.hits[0].id == cids[0]
    assert result.hits[1].id == cids[1]
    assert [hit.score for hit in result.hits] == sorted(
        [hit.score for hit in result.hits], reverse=True)
    assert result.explain["activation"]["applied"] is False
    again = engine.retrieve("Quasar telescope", tenant_id="t", filt=filt, record_access=False)
    assert [(hit.id, hit.score) for hit in result.hits] == [(hit.id, hit.score) for hit in again.hits]


@pytest.mark.parametrize("sqlite", [False, True])
def test_passage_index_rechecks_authorization_and_new_evidence(tmp_path, sqlite):
    engine = SqliteEngine(tmp_path / "db") if sqlite else LocalMemoryEngine()
    public = engine.append_evidence(Evidence(
        tenant_id="t", user_id="u", actor="user", source_type="document",
        content="Orbit telescope public notes", access_policy={"tenant": "t"},
    ))
    secret = engine.append_evidence(Evidence(
        tenant_id="t", user_id="u", actor="user", source_type="document",
        content="Orbit telescope restricted notes", sensitivity=3,
        access_policy={"tenant": "t", "allow_principals": ["owner"]},
    ))
    filt = {"tenant_id": "t", "branch": "main", "query_mode": "passages", "user_id": "guest"}
    assert [hit.id for hit in engine.lexical_search("Orbit", 10, filt)] == [public]
    added = engine.append_evidence(Evidence(
        tenant_id="t", user_id="u", actor="user", source_type="document",
        content="Orbit new public discovery", access_policy={"tenant": "t"},
    ))
    hits = engine.lexical_search("Orbit", 10, filt)
    assert {hit.id for hit in hits} == {public, added}
    assert secret not in {hit.id for hit in hits}
    engine.forget("t", public)
    assert engine._passage_bm25_index is None
    assert {hit.id for hit in engine.lexical_search("Orbit", 10, filt)} == {added}


@pytest.mark.parametrize("sqlite", [False, True])
def test_sourced_summaries_do_not_exhaust_autonomous_memory_budget(tmp_path, sqlite):
    policy = OperatingPolicy(self_generation_budget_max_events=1)
    engine = SqliteEngine(tmp_path / "db", policy=policy) if sqlite else LocalMemoryEngine(policy=policy)
    source = engine.append_evidence(Evidence(
        tenant_id="t", user_id="u", actor="user", source_type="note", content="Mars is red.",
    ))
    for number in range(3):
        cid = engine.append_evidence(Evidence(
            tenant_id="t", user_id="u", actor="system", source_type="consolidation-summary",
            content=f"Mars summary {number}", metadata={"source_evidence_cids": [source]},
        ))
        stored = engine.get_evidence("t", cid)
        assert stored is not None
        assert LocalMemoryEngine._classify_evidence_reality(stored) == "self_generated"
    first = engine.append_evidence(Evidence(
        tenant_id="t", user_id="u", actor="assistant", source_type="thought", content="Speculation one",
    ))
    second = engine.append_evidence(Evidence(
        tenant_id="t", user_id="u", actor="assistant", source_type="thought", content="Speculation two",
    ))
    assert engine.get_evidence("t", first) is not None
    assert engine.get_evidence("t", second) is None
    forged = engine.append_evidence(Evidence(
        tenant_id="t", user_id="u", actor="system", source_type="consolidation-summary",
        content="Unverifiable summary", metadata={"source_evidence_cids": ["missing-source"]},
    ))
    assert engine.get_evidence("t", forged) is None
