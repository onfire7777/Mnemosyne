"""Document lifecycle integration against an explicitly supplied disposable DB."""

from __future__ import annotations

from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import os
from threading import Event
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from mnemosyne.answering import AnswerReadContext
from mnemosyne.document_storage import DocumentConflict
from mnemosyne.documents import DocumentService
from mnemosyne.engine import Intention
from mnemosyne.models import Assertion, Evidence, Relation
from mnemosyne.postgres_engine import PostgresEngine, _stable_uuid


@pytest.fixture(params=[True, False], ids=["pooled", "fresh"])
def storage(request):
    pytest.importorskip("psycopg")
    dsn = os.environ.get("MNEMOSYNE_POSTGRES_DSN")
    if not dsn:
        pytest.skip("MNEMOSYNE_POSTGRES_DSN is not set")
    engine, observer = PostgresEngine(dsn), PostgresEngine(dsn)
    engine._conn_reuse = observer._conn_reuse = request.param
    context = AnswerReadContext(f"documents-{uuid4().hex}", user_id="owner", role="agent")
    try:
        yield engine, observer, context, DocumentService(engine)
    finally:
        engine.close_connections()
        observer.close_connections()


def test_empty_create_initializes_tenant_and_branch(storage):
    engine, observer, context, service = storage
    context = replace(context, branch="draft")
    receipt = service.create(context, "empty", "", operation_id="create")
    assert receipt.revision == 1 and receipt.created == 0
    assert DocumentService(observer).get(context, "empty").content == ""
    assert engine.get_document_record(context.tenant_id, "owner", "empty", "draft")["segments"] == []


def test_append_replace_preserve_occurrences_and_retire_history(storage):
    engine, observer, context, service = storage
    service.create(context, "notes", "Amber launch.\n\nBlue sea.", operation_id="create")
    first = service.get(context, "notes")
    appended = service.append(context, "notes", "\n\nGreen field.", operation_id="append", expected_revision=1)
    assert appended.revision == 2 and appended.reused == 1
    assert service.get(context, "notes").segment_cids[0] == first.segment_cids[0]
    changed = service.replace(context, "notes", "Copper launch.\n\nBlue sea.\n\nGreen field.",
                              operation_id="replace", expected_revision=2)
    assert changed.retired == 1 and changed.reused == 2
    old = observer.get_evidence(context.tenant_id, first.segment_cids[0])
    assert old.content == "Amber launch.\n\n" and old.retired_at is not None and not old.erased
    assert engine.get_evidence_for_read(context.tenant_id, old.cid, access_context=context.to_filter()) is None
    assert old.cid not in {hit.id for hit in engine.lexical_search("Amber launch", 20, context.to_filter())}
    assert old.cid not in {hit.id for hit in engine.vector_search("Amber launch", 20, context.to_filter())}
    service.replace(context, "notes", "Amber launch.\n\n", operation_id="return", expected_revision=3)
    assert service.get(context, "notes").segment_cids[0] != old.cid


def test_document_owner_cannot_be_spoofed_with_source_identity(storage):
    engine, _, context, service = storage
    service.create(context, "notes", "Amber launch.", operation_id="create")
    cid = service.get(context, "notes").segment_cids[0]
    other = replace(context, user_id="other", source_identity="owner", role="operator")
    assert service.get(other, "notes") is None
    assert engine.get_evidence_for_read(context.tenant_id, cid, access_context=other.to_filter()) is None
    assert engine.lexical_search("Amber launch", 20, other.to_filter()) == []
    assert engine.vector_search("Amber launch", 20, other.to_filter()) == []
    assert engine.export_tenant_filtered(context.tenant_id, other.to_filter())["evidence"] == []
    assert "documents" not in engine.export_tenant_filtered(context.tenant_id, context.to_filter())
    assert engine.export_tenant(context.tenant_id)["documents"][0]["document_id"] == "notes"
    with pytest.raises(ValueError):
        engine.update_evidence_metadata(context.tenant_id, cid, {"_external_user_id": "other"})


def test_retired_sources_withhold_derived_memory_and_graph(storage):
    engine, _, context, service = storage
    service.create(context, "notes", "Amber launch.", operation_id="create")
    cid = service.get(context, "notes").segment_cids[0]
    assertion = engine.upsert_assertion(Assertion(
        tenant_id=context.tenant_id, user_id="owner", subject="launch", predicate="color", object="amber",
        source_evidence_cids=[cid], status="active",
    ))
    relation = engine.add_relation(Relation(
        tenant_id=context.tenant_id, source="launch", predicate="color", target="amber",
        source_evidence_cids=[cid],
    ))
    owner_filter = context.to_filter()
    other_filter = replace(context, user_id="other").to_filter()
    assert relation in {hit.id for hit in engine.graph_ppr(["launch"], 10, tenant_id=context.tenant_id,
                                                          filt=owner_filter)}
    assert engine.graph_ppr(["launch"], 10, tenant_id=context.tenant_id, filt=other_filter) == []
    assert assertion in {hit.id for hit in engine.lexical_search("launch amber", 20, owner_filter)}
    service.replace(context, "notes", "Copper launch.", operation_id="replace", expected_revision=1)
    assert engine.graph_ppr(["launch"], 10, tenant_id=context.tenant_id, filt=owner_filter) == []
    assert not {cid, assertion}.intersection(hit.id for hit in engine.lexical_search("launch amber", 20, owner_filter))
    raw = engine.export_tenant(context.tenant_id)
    assert cid in {item["cid"] for item in raw["evidence"]}
    assert assertion in {item["id"] for item in raw["assertions"]}


def test_revision_conflict_poisoning_rolls_back_publication_and_audit(storage):
    engine, observer, context, service = storage
    service.create(context, "notes", "Amber launch.", operation_id="create")
    before = observer.export_tenant(context.tenant_id)
    with pytest.raises(RuntimeError, match="aborted"):
        with engine.source_transaction(context.tenant_id):
            service.replace(context, "notes", "Copper launch.", operation_id="replace", expected_revision=1)
            with pytest.raises(DocumentConflict):
                service.replace(context, "notes", "Wrong revision.", operation_id="stale", expected_revision=1)
    assert observer.export_tenant(context.tenant_id) == before


def test_sql_failure_after_retirement_rolls_back_everything(storage, monkeypatch):
    engine, observer, context, service = storage
    service.create(context, "notes", "Amber launch.", operation_id="create")
    before = observer.export_tenant(context.tenant_id)
    audit = engine._audit

    def fail_save(cur, *args, **kwargs):
        if args[2] == "save_document":
            cur.execute("SELECT 1 / 0")
        return audit(cur, *args, **kwargs)

    monkeypatch.setattr(engine, "_audit", fail_save)
    with pytest.raises(engine._psycopg.errors.DivisionByZero):
        service.replace(context, "notes", "Copper launch.", operation_id="replace", expected_revision=1)
    assert observer.export_tenant(context.tenant_id) == before


def test_branch_copy_merge_divergence_and_discard(storage):
    engine, observer, context, service = storage
    service.create(context, "notes", "Amber launch.", operation_id="create")
    service.replace(context, "notes", "Copper launch.", operation_id="replace", expected_revision=1)
    engine.branch("draft", tenant_id=context.tenant_id)
    draft = replace(context, branch="draft")
    copied = observer.get_document_record(context.tenant_id, "owner", "notes", "draft")
    source = engine.get_document_record(context.tenant_id, "owner", "notes")
    assert copied == {**source, "branch": "draft"}
    historical = copied["retired_segments"][0]["cid"]
    assert observer.get_evidence(context.tenant_id, historical, "draft").retired_at is not None
    engine.merge("draft", tenant_id=context.tenant_id)
    service.append(draft, "notes", " More.", operation_id="draft-append", expected_revision=2)
    before = observer.export_tenant(context.tenant_id)
    with pytest.raises(DocumentConflict, match="divergent"):
        engine.merge("draft", tenant_id=context.tenant_id)
    assert observer.export_tenant(context.tenant_id) == before
    engine.discard("draft", tenant_id=context.tenant_id)
    assert observer.get_document_record(context.tenant_id, "owner", "notes", "draft") is None
    assert observer.get_document_record(context.tenant_id, "owner", "notes") == source


def test_new_branch_document_merges_to_absent_target(storage):
    engine, observer, context, service = storage
    engine.branch("draft", tenant_id=context.tenant_id)
    draft = replace(context, branch="draft")
    service.create(draft, "notes", "Amber launch.", operation_id="create")
    engine.merge("draft", tenant_id=context.tenant_id)
    assert DocumentService(observer).get(context, "notes").content == "Amber launch."


def test_merge_rejects_target_tombstone_before_copying_manifest(storage):
    engine, observer, context, service = storage
    engine.branch("draft", tenant_id=context.tenant_id)
    draft = replace(context, branch="draft")
    service.create(draft, "notes", "Amber launch.", operation_id="create")
    cid = service.get(draft, "notes").segment_cids[0]
    row = engine.get_evidence(context.tenant_id, cid, "draft")
    engine.append_evidence(row)
    engine.forget(context.tenant_id, cid)
    before = observer.export_tenant(context.tenant_id)
    with pytest.raises(DocumentConflict, match="custody"):
        engine.merge("draft", tenant_id=context.tenant_id)
    assert observer.export_tenant(context.tenant_id) == before


@pytest.mark.parametrize("erasure_mode", ["tombstone_recompute", "hard_delete_legal"])
def test_forget_scrubs_current_and_historical_registry_refs(storage, erasure_mode):
    engine, observer, context, service = storage
    service.create(context, "notes", "Amber launch.", operation_id="create")
    old = service.get(context, "notes").segment_cids[0]
    service.replace(context, "notes", "Copper launch.", operation_id="replace", expected_revision=1)
    current = service.get(context, "notes").segment_cids[0]
    engine.forget(context.tenant_id, old, erasure_mode=erasure_mode, requested_by="legal")
    record = observer.get_document_record(context.tenant_id, "owner", "notes")
    assert record["revision"] == 3 and record["retired_segments"] == []
    assert all(item["request_hash"] is None for item in record["receipts"])
    engine.forget(context.tenant_id, current, erasure_mode=erasure_mode, requested_by="legal")
    record = observer.get_document_record(context.tenant_id, "owner", "notes")
    assert record["revision"] == 4 and record["segments"] == [] and record["deleted"]
    assert service.get(context, "notes") is None


def test_embedding_purge_waits_for_commit_and_is_dropped_on_rollback(storage):
    engine, observer, context, service = storage
    service.create(context, "notes", "Amber launch.", operation_id="create")
    cid = service.get(context, "notes").segment_cids[0]
    calls = []

    def purge():
        calls.append(observer.get_evidence(context.tenant_id, cid))

    engine.adapters = replace(engine.adapters, embedding=SimpleNamespace(purge_cache=purge))
    with pytest.raises(ValueError, match="rollback"):
        with engine.source_transaction(context.tenant_id):
            engine.forget(context.tenant_id, cid)
            assert calls == []
            raise ValueError("rollback")
    assert calls == []
    with engine.source_transaction(context.tenant_id):
        engine.forget(context.tenant_id, cid)
        assert calls == []
    assert calls == [None]


def test_document_save_rejects_outside_transaction_and_foreign_custody(storage):
    engine, observer, context, service = storage
    service.create(context, "notes", "Amber launch.", operation_id="create")
    record = engine.get_document_record(context.tenant_id, "owner", "notes")
    with pytest.raises(RuntimeError, match="source_transaction"):
        engine.save_document_record(context.tenant_id, "owner", "notes", record, expected_revision=1)
    forged = {**record, "document_id": "foreign", "owner_id": "other"}
    with pytest.raises(DocumentConflict):
        with engine.source_transaction(context.tenant_id):
            engine.save_document_record(context.tenant_id, "other", "foreign", forged)
    assert observer.get_document_record(context.tenant_id, "other", "foreign") is None


def test_retired_main_source_hides_intention_despite_live_branch_copy(storage):
    engine, _, context, service = storage
    service.create(context, "notes", "Amber launch.", operation_id="create")
    cid = service.get(context, "notes").segment_cids[0]
    due = datetime.now(UTC) + timedelta(minutes=5)
    intention = Intention(
        intention_id="reminder", tenant_id=context.tenant_id, user_id="owner", agent_id="agent",
        trigger_type="exact_time", trigger_expression={"at": due.isoformat()},
        action={"type": "remind", "message": "Amber launch."}, due_at=due,
        evidence_ids=[cid], session_id="session",
    )
    engine.schedule_intention(intention)
    assert len(engine.list_intentions(context.tenant_id)) == 1
    engine.branch("draft", tenant_id=context.tenant_id)
    service.replace(context, "notes", "Copper launch.", operation_id="replace", expected_revision=1)
    assert engine.get_evidence(context.tenant_id, cid, "draft").retired_at is None
    assert engine.list_intentions(context.tenant_id) == []
    with engine.connect() as conn:
        with conn.cursor() as cur:
            engine._set_tenant(cur, _stable_uuid("tenant", context.tenant_id))
            cur.execute("SELECT count(*) FROM intentions WHERE tenant_id = %s",
                        (_stable_uuid("tenant", context.tenant_id),))
            assert cur.fetchone()[0] == 1


def test_source_reads_lock_privacy_until_document_append_commits(storage, monkeypatch):
    engine, writer, context, service = storage
    service.create(context, "notes", "Amber launch.", operation_id="create")
    cid = service.get(context, "notes").segment_cids[0]
    entered = Event()
    writer_pid = []
    set_tenant = writer._set_tenant

    def identify_writer(cur, tenant):
        set_tenant(cur, tenant)
        cur.execute("SELECT pg_backend_pid()")
        row = cur.fetchone()
        writer_pid.append(row["pg_backend_pid"] if isinstance(row, dict) else row[0])
        entered.set()

    monkeypatch.setattr(writer, "_set_tenant", identify_writer)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with engine.source_transaction(context.tenant_id):
            engine.get_evidence(context.tenant_id, cid)
            future = pool.submit(writer.backfill_evidence_privacy, context.tenant_id, cid, ["email"])
            assert entered.wait(5)
            deadline = time.monotonic() + 5
            with engine._psycopg.connect(engine.dsn) as probe:
                while not probe.execute("SELECT cardinality(pg_blocking_pids(%s)) > 0",
                                        (writer_pid[0],)).fetchone()[0]:
                    assert not future.done()
                    assert time.monotonic() < deadline, "privacy writer was not blocked by the source read"
                    time.sleep(0.01)
            service.append(context, "notes", " Added.", operation_id="append", expected_revision=1)
            assert not future.done()
        assert future.result(timeout=10)
    assert engine.get_evidence(context.tenant_id, cid).sensitivity == 3
    assert service.get(context, "notes").content == "Amber launch. Added."


def test_retirement_marker_cannot_be_supplied_to_append(storage):
    engine, _, context, _ = storage
    row = Evidence(tenant_id=context.tenant_id, user_id="owner", actor="user", source_type="document",
                   content="Amber launch", document_segment_id="segment", retired_at=datetime.now(UTC))
    with pytest.raises(ValueError, match="retired_at"):
        engine.append_evidence(row)


def test_documents_table_rls_isolates_other_tenant(storage):
    engine, _, context, service = storage
    service.create(context, "notes", "Amber launch.", operation_id="create")
    with engine.connect() as conn:
        with conn.cursor() as cur:
            engine._set_tenant(cur, _stable_uuid("tenant", f"other-{uuid4().hex}"))
            cur.execute("SELECT record FROM documents")
            assert cur.fetchall() == []


def test_app_role_can_create_replace_and_read_documents():
    pytest.importorskip("psycopg")
    dsn = os.environ.get("MNEMOSYNE_POSTGRES_APP_DSN")
    if not dsn:
        pytest.skip("MNEMOSYNE_POSTGRES_APP_DSN is not set")
    engine = PostgresEngine(dsn)
    context = AnswerReadContext(f"documents-app-{uuid4().hex}", user_id="owner", role="agent")
    try:
        service = DocumentService(engine)
        service.create(context, "notes", "Amber launch.", operation_id="create")
        service.replace(context, "notes", "Copper launch.", operation_id="replace", expected_revision=1)
        assert service.get(context, "notes").content == "Copper launch."
    finally:
        engine.close_connections()
