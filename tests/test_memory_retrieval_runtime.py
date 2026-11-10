"""Focused checks for useful bounded recall and deferred indexing."""
from dataclasses import replace
import json
import subprocess
from types import SimpleNamespace

import pytest

from mnemosyne.context_composer import compose_context
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.hosts.deadlines import run_bounded
from mnemosyne.hosts.query_embedding import ScopedQueryEmbeddingProvider
from mnemosyne.models import Evidence
from mnemosyne.retrieval import HashingEmbeddingProvider
from mnemosyne.retrieval_maintenance import maintain_retrieval_index
from mnemosyne.sqlite_engine import SqliteEngine


def test_prompt_wrappers_do_not_make_another_project_relevant():
    packet = {"hits": [
        {"id": "game", "kind": "evidence", "text": "Please fully improve all those issues. Make the pixelated game character jump higher."},
        {"id": "memory", "kind": "assertion", "text": "Mnemosyne requires source-linked feedback to learn from recalled memories."},
    ]}
    result = compose_context("What are the biggest remaining issues with Mnemosyne memory and learning?", packet, 5000)
    assert [row["id"] for row in result["packet"]["hits"]] == ["memory"]
    assert result["omitted"] == 1


def test_semantic_reranking_survives_without_literal_overlap_and_rejects_noise():
    packet = {"hits": [
        {"id": "semantic", "text": "The host runs Debian.", "metadata": {"reranker": "http-reranker", "rerank_score": 3, "rerank_score_kind": "logit"}},
        {"id": "noise", "text": "operating system operating system", "metadata": {"reranker": "http-reranker", "rerank_score": -8, "rerank_score_kind": "logit"}},
        {"id": "probability_noise", "text": "cake", "metadata": {"reranker": "http-reranker", "rerank_score": 0.0001}},
    ]}
    result = compose_context("Which operating system?", packet, 5000)
    assert [row["id"] for row in result["packet"]["hits"]] == ["semantic"]


def test_large_irrelevant_set_still_fits_total_delivery_budget():
    packet = {"hits": [{"id": str(i), "text": "chocolate cake"} for i in range(1000)] +
              [{"id": "atlas", "text": "Atlas"}]}
    for budget in (132, 200, 300):
        result = compose_context("Atlas", packet, budget)
        assert result["used_tokens_upper_bound"] <= budget


@pytest.mark.parametrize("backend", ["local", "sqlite"])
def test_read_never_embeds_missing_documents_and_maintenance_repairs_them(tmp_path, backend):
    engine = LocalMemoryEngine() if backend == "local" else SqliteEngine(tmp_path / "db")
    cid = engine.append_evidence(Evidence("t", "u", "user", "chat", "Atlas runs Debian.", trust_tier=1))
    # Explicitly remove the append-time vector to simulate recovered old rows.
    if backend == "local":
        engine.evidence[engine._evidence_key("t", "main", cid)].embedding = None
    else:
        conn = engine._connect("t")
        with conn:
            conn.execute("UPDATE evidence SET embedding=NULL WHERE cid=?", (cid,))
    calls = []
    hashing = HashingEmbeddingProvider()
    class Provider:
        dims = hashing.dims
        def embed(self, text):
            calls.append(text)
            return hashing.embed(text)
    engine.adapters = replace(engine.adapters, embedding=Provider(), embed_missing_on_read=False)
    filt = {"tenant_id": "t", "user_id": "u", "role": "reader"}
    assert engine.vector_search("Atlas", 5, filt) == []
    assert calls == ["Atlas"]
    report = maintain_retrieval_index(engine, "t", "u")
    assert report["indexed"] == 1 and not report["errors"]
    assert calls[-1] == "Atlas runs Debian."
    assert any(hit.id == cid for hit in engine.vector_search("Atlas", 5, filt))
    engine.close()


def test_maintenance_does_not_embed_other_owner_expired_or_forbidden_sources():
    engine = LocalMemoryEngine()
    for user, policy, metadata in [
        ("other", {}, {}), ("u", {"embed_ok": False}, {}),
        ("u", {}, {"expires_at": "2000-01-01T00:00:00Z"}),
    ]:
        engine.append_evidence(Evidence("t", user, "user", "chat", "Private project fact.",
            trust_tier=1, access_policy=policy, metadata=metadata))
    for source in engine.evidence.values():
        source.embedding = None
    engine.adapters = replace(engine.adapters, embedding=SimpleNamespace(embed=lambda text: pytest.fail("forbidden embedding")))
    assert maintain_retrieval_index(engine, "t", "u")["indexed"] == 0
    engine.close()


def test_provider_timeout_and_local_delivery_have_distinct_observable_outcomes(monkeypatch):
    attempts = []
    def run(command, **kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return SimpleNamespace(stdout=json.dumps({"hits": []}))
    monkeypatch.setattr(subprocess, "run", run)
    response, report = run_bounded(["host"], {"query": "private text"})
    assert response == {"hits": []}
    assert report["degraded"]
    assert [row["status"] for row in report["attempts"]] == ["timeout", "returned"]
    assert "private text" not in json.dumps(report)
    assert attempts[1]["env"]["MNEMOSYNE_LOCAL_RECALL"] == "1"


def test_wiki_and_retrieval_share_only_the_request_owned_query_vector():
    calls = []
    provider = SimpleNamespace(query_prefix="query: ", embed=lambda text: pytest.fail("shared cache"),
                               embed_sensitive=lambda text: calls.append(text) or [1., 0.])
    scoped = ScopedQueryEmbeddingProvider(provider)
    assert scoped.embed_query_sensitive("current project") == scoped.embed_query("current project")
    assert calls == ["query: current project"]
    scoped.embed_sensitive("Private page contents")
    scoped.embed_sensitive("Private page contents")
    assert calls.count("Private page contents") == 2
    ScopedQueryEmbeddingProvider(provider).embed_query("current project")
    assert calls.count("query: current project") == 2
