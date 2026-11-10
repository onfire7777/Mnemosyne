"""Maintenance fairness, concurrent writers, and source-backed dense candidates."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Assertion, Evidence, Preference
from mnemosyne.retrieval import HashingEmbeddingProvider
from mnemosyne.retrieval_maintenance import maintain_retrieval_index
from mnemosyne.sqlite_engine import SqliteEngine


def _engine(tmp_path, backend):
    return LocalMemoryEngine() if backend == "local" else SqliteEngine(tmp_path / "db")


def _clear_vector(engine, cid):
    if isinstance(engine, LocalMemoryEngine):
        engine.evidence[engine._evidence_key("t", "main", cid)].embedding = None
    else:
        conn = engine._connect("t")
        with conn:
            conn.execute("UPDATE evidence SET embedding=NULL WHERE cid=?", (cid,))


@pytest.mark.parametrize("backend", ["local", "sqlite"])
def test_bad_newest_record_does_not_starve_older_records_even_with_batch_one(tmp_path, backend):
    engine = _engine(tmp_path, backend)
    good = engine.append_evidence(Evidence("t", "u", "user", "chat", "Good source.",
        created_at=datetime.now(UTC) - timedelta(seconds=10)))
    bad = engine.append_evidence(Evidence("t", "u", "user", "chat", "Oversized input."))
    for cid in (good, bad):
        _clear_vector(engine, cid)
    class Provider:
        def embed(self, text):
            if text.startswith("Oversized"):
                raise ValueError("Input is too large")
            return [1., 0.]
    engine.adapters = replace(engine.adapters, embedding=Provider())
    first = maintain_retrieval_index(engine, "t", "u", limit=1)
    second = maintain_retrieval_index(engine, "t", "u", limit=1)
    assert len(first["errors"]) == 1 and first["indexed"] == 0
    assert second["indexed"] == 1 and second["deferred"] == 1
    assert engine.get_evidence("t", good).embedding == [1., 0.]
    assert not engine.get_evidence("t", bad).embedding
    engine.close()


@pytest.mark.parametrize("backend", ["local", "sqlite"])
def test_maintenance_does_not_replace_vector_written_during_provider_io(tmp_path, backend):
    engine = _engine(tmp_path, backend)
    cid = engine.append_evidence(Evidence("t", "u", "user", "chat", "Concurrent source."))
    _clear_vector(engine, cid)
    other = engine if backend == "local" else SqliteEngine(tmp_path / "db")
    class Provider:
        def embed(self, text):
            assert other.set_evidence_embedding("t", cid, [0., 1.])
            return [1., 0.]
    engine.adapters = replace(engine.adapters, embedding=Provider())
    assert maintain_retrieval_index(engine, "t", "u")["indexed"] == 0
    assert engine.get_evidence("t", cid).embedding == [0., 1.]
    if other is not engine:
        other.close()
    engine.close()


@pytest.mark.parametrize("backend", ["local", "sqlite"])
def test_atomic_only_if_missing_allows_exactly_one_concurrent_writer(tmp_path, backend):
    engine = _engine(tmp_path, backend)
    cid = engine.append_evidence(Evidence("t", "u", "user", "chat", "Concurrent source."))
    _clear_vector(engine, cid)
    other = engine if backend == "local" else SqliteEngine(tmp_path / "db")
    other.get_evidence("t", cid)
    barrier = Barrier(2)
    def write(target, value):
        barrier.wait(timeout=5)
        return target.set_evidence_embedding("t", cid, value, only_if_missing=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(write, target, value) for target, value in
                   ((engine, [1., 0.]), (other, [0., 1.]))]
        assert sorted(future.result(timeout=10) for future in futures) == [False, True]
    assert engine.get_evidence("t", cid).embedding in ([1., 0.], [0., 1.])
    if other is not engine:
        other.close()
    engine.close()


@pytest.mark.parametrize("backend", ["local", "sqlite"])
def test_dense_projection_candidates_survive_without_embedding_them_on_read(tmp_path, backend):
    engine = _engine(tmp_path, backend)
    source = engine.append_evidence(Evidence("t", "u", "user", "chat", "Atlas hosts our services and runs Debian."))
    engine.set_evidence_embedding("t", source, HashingEmbeddingProvider().embed("Atlas hosts our services and runs Debian."))
    assertion = Assertion("t", "Atlas", "runs", "Debian", user_id="u", status="active", source_evidence_cids=[source])
    preference = Preference("t", "u", "tooling", "Use Atlas for deployment.", source_evidence_cids=[source])
    engine.upsert_assertion(assertion)
    engine.add_preference(preference)
    blocked = Assertion("t", "Atlas", "contains", "restricted data", user_id="u", status="active",
                        source_evidence_cids=[source], access_policy={"embed_ok": False})
    engine.upsert_assertion(blocked)
    calls = []
    class QueryOnly:
        def embed(self, text):
            calls.append(text)
            assert text == "Atlas"
            return HashingEmbeddingProvider().embed(text)
    engine.adapters = replace(engine.adapters, embedding=QueryOnly(), embed_missing_on_read=False)
    hits = engine.vector_search("Atlas", 8, {"tenant_id": "t", "user_id": "u", "principal": "u", "role": "reader"})
    assert calls == ["Atlas"]
    assert {source, assertion.id, preference.id} <= {hit.id for hit in hits}
    assert blocked.id not in {hit.id for hit in hits}
    assert all(hit.metadata["source_vector_proxy"] and hit.metadata["dense_source_cids"] == [source]
               for hit in hits if hit.kind != "evidence")
    engine.forget("t", source)
    assert not engine.vector_search("Atlas", 8, {"tenant_id": "t", "user_id": "u", "role": "reader"})
    engine.close()
