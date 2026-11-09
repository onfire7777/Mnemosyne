"""Ingestion side effects require evidence that the engine actually accepted."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from mnemosyne.consolidation import CONSOLIDATE_EVIDENCE_JOB
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.ingestion import IngestionPipeline, IngestRequest
from mnemosyne.mcp_tools import MemoryTools
from mnemosyne.policy import OperatingPolicy
from mnemosyne.postgres_engine import PostgresEngine
from mnemosyne.queue import InProcessQueue
from mnemosyne.sqlite_engine import SqliteEngine
from mnemosyne.storage import LocalObjectStore


@pytest.fixture(params=["local", "sqlite", "postgres"])
def engine(request, tmp_path):
    policy = OperatingPolicy(self_generation_budget_max_events=0)
    if request.param == "local":
        value = LocalMemoryEngine(policy=policy)
    elif request.param == "sqlite":
        value = SqliteEngine(tmp_path / "db", policy=policy)
    else:
        dsn = os.environ.get("MNEMOSYNE_POSTGRES_DSN")
        if not dsn:
            pytest.skip("live PostgreSQL DSN not configured")
        value = PostgresEngine(dsn, policy=policy)
    yield value
    if isinstance(value, PostgresEngine):
        value.close_connections()
    else:
        value.close()


@pytest.fixture
def pipeline(engine, tmp_path):
    return IngestionPipeline(
        engine, LocalObjectStore(tmp_path / "objects"), queue=InProcessQueue(),
    )


def _request(**changes):
    return IngestRequest(**{
        "tenant_id": f"ingest-ack-{uuid4()}", "user_id": "owner", "actor": "user",
        "source_type": "chat", "content": "The observatory opens on Tuesday.",
        **changes,
    })


def test_created_and_duplicate_ingestion_have_explicit_acknowledgements(pipeline):
    request = _request()
    created = pipeline.ingest(request)
    assert created.stored and created.created and not created.idempotent
    assert [job["kind"] for job in created.queued_jobs] == [CONSOLIDATE_EVIDENCE_JOB]
    duplicate = pipeline.ingest(request)
    assert duplicate.cid == created.cid
    assert duplicate.stored and not duplicate.created and duplicate.idempotent
    assert duplicate.queued_jobs == []
    assert len(pipeline.queue.jobs) == 1


@pytest.mark.parametrize("media", [False, True])
def test_erased_replay_cannot_queue_work_or_reapply_correction(pipeline, media):
    changes = {"data": b"test-image", "modality": "image", "media_type": "image/png"} if media else {}
    request = _request(**changes)
    first = pipeline.ingest(request)
    pipeline.engine.forget(request.tenant_id, first.cid)
    before = set(pipeline.queue.jobs)
    request.correction = {"subject": "observatory", "predicate": "opens", "object": "Tuesday"}
    replay = pipeline.ingest(request)
    assert replay.queued_jobs == []
    assert set(pipeline.queue.jobs) == before
    assert not replay.correction_applied
    assert replay.correction_assertion_id is None
    assert not replay.stored and not replay.created and not replay.idempotent
    assert pipeline.engine.get_evidence(request.tenant_id, replay.cid) is None


def test_budget_deferral_is_not_a_successful_ingestion(pipeline):
    request = _request(actor="assistant", source_type="thought")
    result = pipeline.ingest(request)
    assert pipeline.engine.get_evidence(request.tenant_id, result.cid) is None
    assert result.queued_jobs == []
    assert pipeline.queue.jobs == {}
    assert not result.stored and not result.created and not result.idempotent


def test_accepted_correction_still_applies_once(pipeline):
    request = _request(correction={"subject": "observatory", "predicate": "opens", "object": "Tuesday"})
    created = pipeline.ingest(request)
    assert created.stored and created.correction_applied and created.correction_assertion_id
    duplicate = pipeline.ingest(request)
    assert duplicate.idempotent and not duplicate.correction_applied


def test_mcp_only_requests_indexing_for_created_evidence(pipeline, monkeypatch):
    tools = MemoryTools(engine=pipeline.engine, ingestion=pipeline)
    indexed = []
    monkeypatch.setattr(tools, "_index_later", lambda *args: indexed.append(args))
    request = _request()
    kwargs = {
        "tenant_id": request.tenant_id, "user_id": request.user_id, "actor": request.actor,
        "source_type": request.source_type, "content": request.content,
    }
    created = tools.ingest(**kwargs)
    duplicate = tools.ingest(**kwargs)
    pipeline.engine.forget(request.tenant_id, created["cid"])
    rejected = tools.ingest(**kwargs)
    assert indexed == [(request.tenant_id, "main")]
    assert created["created"] and duplicate["idempotent"] and not rejected["stored"]


@pytest.mark.parametrize("rollback", [False, True])
def test_bound_profile_cleanup_follows_outer_source_commit(pipeline, rollback):
    from contextvars import ContextVar

    tools = MemoryTools(engine=pipeline.engine, ingestion=pipeline)
    request = _request()
    source = pipeline.ingest(request)
    profile = tools.profile_record_explicit(
        request.tenant_id, request.user_id, "Prefers observatory updates.",
        source_evidence_cids=[source.cid],
    )
    entry = tools.user_model.entries[profile["id"]]
    original_statement = entry.statement
    marker = ContextVar("profile-cleanup-test", default="outside")
    cleanup_observations = []
    cleanup = pipeline.engine._learning_profile_erasure

    def observe_cleanup(tenant, cid):
        transaction = pipeline.engine._source_transaction_state
        if callable(transaction):
            transaction = transaction()
        cleanup_observations.append((marker.get(), transaction))
        return cleanup(tenant, cid)

    pipeline.engine._learning_profile_erasure = observe_cleanup

    class Abort(Exception):
        pass

    try:
        with pipeline.engine.source_transaction(request.tenant_id):
            token = marker.set("scheduled")
            try:
                pipeline.engine.forget(request.tenant_id, source.cid)
            finally:
                marker.reset(token)
            assert entry.status == "active" and entry.statement == original_statement
            if rollback:
                raise Abort
    except Abort:
        pass

    if rollback:
        assert cleanup_observations == []
        assert pipeline.engine.get_evidence(request.tenant_id, source.cid) is not None
        assert entry.status == "active" and entry.statement == original_statement
    else:
        assert cleanup_observations == [("scheduled", None)]
        assert pipeline.engine.get_evidence(request.tenant_id, source.cid) is None
        assert entry.status != "active" and entry.statement != original_statement
        # Tombstone replay keeps the completed cleanup idempotent.
        pipeline.engine.forget(request.tenant_id, source.cid)
        assert entry.status != "active" and entry.statement != original_statement


def test_bound_profile_cleanup_failure_keeps_erasure_and_can_retry(pipeline, monkeypatch, tmp_path):
    if isinstance(pipeline.engine, (LocalMemoryEngine, SqliteEngine)):
        pipeline.engine._journal_dir = tmp_path / "source-journal"
    tools = MemoryTools(engine=pipeline.engine, ingestion=pipeline)
    request = _request()
    source = pipeline.ingest(request)
    profile = tools.profile_record_explicit(
        request.tenant_id, request.user_id, "Prefers observatory updates.",
        source_evidence_cids=[source.cid],
    )
    from mnemosyne.answering import AnswerReadContext
    from mnemosyne.mental_models import MentalModelService
    service = MentalModelService(pipeline.engine)
    service._snapshot(AnswerReadContext(tenant_id=request.tenant_id, user_id=request.user_id, role="agent"))
    cached = list(pipeline.engine._mental_model_source_cache.values())
    callback = pipeline.engine._learning_profile_erasure
    calls = []

    def fail_once(tenant, cid):
        calls.append(cid)
        if len(calls) == 1:
            raise RuntimeError("profile store temporarily unavailable")
        return callback(tenant, cid)

    monkeypatch.setattr(pipeline.engine, "_learning_profile_erasure", fail_once)
    with pytest.raises(RuntimeError, match="profile store temporarily unavailable"):
        pipeline.engine.forget(request.tenant_id, source.cid)
    assert pipeline.engine.get_evidence(request.tenant_id, source.cid) is None
    assert all(not state.raw and not state.evidence for state in cached)
    context = tools.profile_context(request.tenant_id, request.user_id)
    relevant = tools.profile_get_relevant(request.tenant_id, request.user_id)
    assert all(row["id"] != profile["id"] for row in context["authoritative"])
    assert all(row["id"] != profile["id"] for row in relevant["authoritative"])
    packet = tools.user_model.context_packet(request.tenant_id, request.user_id, {})
    assert all(row["id"] != profile["id"] for row in packet["authoritative"])
    prepared = tools.prepare_context(request.tenant_id, request.user_id, "profile-read", "observatory")
    assert all(row["id"] != profile["id"] for row in prepared["user_model"]["authoritative"])
    from mnemosyne.frameworks import AutoMemorySession
    with AutoMemorySession(pipeline.engine, request.tenant_id, request.user_id,
                           session_id="sdk-profile-read", auto_consolidate=False) as session:
        assert "Prefers observatory updates." not in session.pre_turn_retrieve("observatory")["context_text"]
    if isinstance(pipeline.engine, (LocalMemoryEngine, SqliteEngine)):
        from mnemosyne.journal import journal_filename
        journal = pipeline.engine._journal_dir / journal_filename(request.tenant_id)
        assert request.content not in journal.read_text()
    pipeline.engine.forget(request.tenant_id, source.cid)
    assert tools.user_model.entries[profile["id"]].status != "active"
    assert calls == [source.cid, source.cid]
