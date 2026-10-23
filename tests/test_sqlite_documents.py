"""Atomic SQLite document manifests, nondestructive retirement and custody."""

from __future__ import annotations

import copy
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta

import pytest

from mnemosyne.document_storage import DocumentConflict
from mnemosyne.engine import Intention, WorkingMemoryItem
from mnemosyne.models import Evidence, Relation
from mnemosyne.privacy import ErasureMode
from mnemosyne.sqlite_engine import SqliteEngine, _evidence_from_row


TENANT = "document-tenant"
OWNER = "document-owner"
CREATED = datetime(2024, 1, 1, tzinfo=UTC)


@pytest.fixture
def engine(tmp_path):
    value = SqliteEngine(tmp_path / "store")
    yield value
    value.close()


def append(engine, segment_id, text="The observatory opens on Tuesday.", *, owner=OWNER, branch="main"):
    cid = engine.append_evidence(Evidence(
        tenant_id=TENANT, user_id=owner, actor="user", source_type="document",
        content=text, document_segment_id=segment_id, created_at=CREATED, session_id="document-session",
    ), branch=branch)
    return {"segment_id": segment_id, "cid": cid}


def manifest(segments, *, current=None, owner=OWNER, document_id="observatory", branch="main"):
    revision = current["revision"] + 1 if current else 1
    retired = copy.deepcopy(current["retired_segments"]) if current else []
    if current:
        current_ids = {row["segment_id"] for row in segments}
        retired.extend(row for row in current["segments"] if row["segment_id"] not in current_ids)
    return {
        "schema_version": 1, "tenant_id": TENANT, "branch": branch,
        "owner_id": owner, "document_id": document_id, "revision": revision,
        "created_at": CREATED.isoformat(), "updated_at": f"2024-01-{revision:02d}T00:00:00+00:00",
        "deleted": False, "settings": {}, "segments": copy.deepcopy(segments),
        "retired_segments": retired,
        "receipts": copy.deepcopy(current["receipts"] if current else []) + [{
            "operation_id": f"operation-{revision}", "action": "replace" if current else "create",
            "revision": revision, "request_hash": str(revision % 10) * 64,
        }],
    }


def save(engine, record, *, expected=None):
    return engine.save_document_record(
        TENANT, record["owner_id"], record["document_id"], record,
        branch=record["branch"], expected_revision=expected,
    )


def create(engine, *, owner=OWNER, document_id="observatory", branch="main", segment_id="doc/first"):
    with engine.source_transaction(TENANT, branch):
        first = append(engine, segment_id, owner=owner, branch=branch)
        record = save(engine, manifest([first], owner=owner, document_id=document_id, branch=branch))
    return first, record


def replace(engine, first, record, *, branch="main"):
    with engine.source_transaction(TENANT, branch):
        second = append(engine, "doc/second", "The observatory opens on Wednesday.", branch=branch)
        saved = save(engine, manifest([second], current=record, branch=branch), expected=record["revision"])
    return second, saved


def test_document_save_requires_source_transaction(engine):
    first = append(engine, "doc/first")
    with pytest.raises(RuntimeError, match="source transaction"):
        save(engine, manifest([first]))
    assert engine.list_document_records(TENANT) == []


def test_raw_export_preserves_document_manifest_but_filtered_export_withholds_it(engine):
    first, record = create(engine)
    assert engine.export_tenant(TENANT)["documents"] == [record]
    assert engine.export_all()["documents"] == [record]
    for context in ({"user_id": OWNER}, {"user_id": "other-owner"}, {"role": "operator"}):
        exported = engine.export_tenant_filtered(TENANT, context)
        assert "documents" not in exported
        assert "receipts" not in repr(exported)
    assert first["cid"] in {row["cid"] for row in engine.export_tenant_filtered(TENANT, {"user_id": OWNER})["evidence"]}


def test_document_replacement_preserves_history_and_reopens(engine):
    first, record = create(engine)
    engine.add_relation(Relation(
        tenant_id=TENANT, source="observatory", predicate="opens", target="Tuesday",
        source_evidence_cids=[first["cid"]],
    ))
    fingerprint = engine._relations_fingerprint(TENANT, "main")
    second, saved = replace(engine, first, record)
    assert engine._relations_fingerprint(TENANT, "main") != fingerprint
    old = engine.get_evidence(TENANT, first["cid"])
    assert old.content == "The observatory opens on Tuesday."
    assert old.retired_at == datetime(2024, 1, 2, tzinfo=UTC)
    assert old.created_at == CREATED and not old.erased
    assert engine.get_evidence(TENANT, second["cid"]).retired_at is None
    assert saved["segments"] == [second] and saved["retired_segments"] == [first]
    assert saved["receipts"][0]["request_hash"] is None
    assert [row.cid for row in engine.main_evidence(TENANT)] == [second["cid"]]
    engine.close()
    with closing(SqliteEngine(engine.root_dir)) as reopened:
        assert reopened.get_document_record(TENANT, OWNER, "observatory") == saved
        assert reopened.get_evidence(TENANT, first["cid"]).retired_at == old.retired_at


@pytest.mark.parametrize("mode", ["lexical", "vector", "passages", "default", "as_of"])
def test_retired_sources_are_not_current_retrieval_even_from_warmed_cache(engine, mode):
    first, record = create(engine)
    filt = {"tenant_id": TENANT, "user_id": OWNER, "branch": "main"}

    def ids():
        if mode == "lexical":
            hits = engine.lexical_search("observatory", 10, filt)
        elif mode == "vector":
            hits = engine.vector_search("observatory", 10, filt)
        elif mode == "passages":
            hits = engine.passage_candidates(filt)
        else:
            hits = engine.retrieve("observatory", TENANT, filt=filt).hits
        return {hit.id for hit in hits}

    assert first["cid"] in ids()
    second, _ = replace(engine, first, record)
    if mode == "as_of":
        filt["as_of"] = "2024-01-01T12:00:00Z"
    assert first["cid"] not in ids()
    if mode != "as_of":
        assert second["cid"] in ids()
    assert engine.get_evidence_for_read(TENANT, first["cid"], access_context=filt) is None


def test_replacement_failure_restores_manifest_sources_and_models(engine):
    first, record = create(engine)
    model = {
        "tenant_id": TENANT, "branch": "main", "model_id": "saved-answer", "owner_id": OWNER,
        "name": "Opening day", "question": "When does the observatory open?",
        "created_at": CREATED.isoformat(), "updated_at": CREATED.isoformat(),
        "status": "ready", "scope": {}, "revisions": [], "answer": {"text": "Tuesday"},
        "corpus_fingerprint": "before", "source_evidence_cids": [first["cid"]],
    }
    model = engine.save_mental_model_record(TENANT, "saved-answer", model)
    before = engine.export_tenant(TENANT)
    with pytest.raises(ValueError, match="abort publication"):
        with engine.source_transaction(TENANT):
            second = append(engine, "doc/second", "The observatory opens on Wednesday.")
            save(engine, manifest([second], current=record), expected=1)
            raise ValueError("abort publication")
    assert engine.get_document_record(TENANT, OWNER, "observatory") == record
    assert engine.get_evidence(TENANT, first["cid"]).retired_at is None
    assert engine.get_evidence(TENANT, second["cid"]) is None
    assert engine.export_tenant(TENANT) == before
    replace(engine, first, record)
    changed = engine.get_mental_model_record(TENANT, "saved-answer")
    assert changed["answer"] is None and changed["status"] == "stale"
    assert changed["version"] == model["version"] + 1


def test_caught_cas_error_aborts_all_source_writes(engine):
    first, record = create(engine)
    with pytest.raises(RuntimeError, match="aborted"):
        with engine.source_transaction(TENANT):
            second = append(engine, "doc/second")
            with pytest.raises(DocumentConflict, match="revision"):
                save(engine, manifest([second], current=record), expected=9)
    assert engine.get_evidence(TENANT, second["cid"]) is None
    assert engine.get_evidence(TENANT, first["cid"]).retired_at is None
    assert engine.get_document_record(TENANT, OWNER, "observatory") == record


def test_other_connection_sees_atomic_publication_and_rejects_stale_revision(engine):
    first, record = create(engine)
    with closing(SqliteEngine(engine.root_dir)) as reader:
        assert reader.get_document_record(TENANT, OWNER, "observatory") == record
        with engine.source_transaction(TENANT):
            second = append(engine, "doc/second")
            changed = save(engine, manifest([second], current=record), expected=1)
            assert reader.get_document_record(TENANT, OWNER, "observatory") == record
            assert reader.get_evidence(TENANT, first["cid"]).retired_at is None
            assert reader.get_evidence(TENANT, second["cid"]) is None
        assert reader.get_document_record(TENANT, OWNER, "observatory") == changed
        assert reader.get_evidence(TENANT, first["cid"]).retired_at is not None
        with pytest.raises(DocumentConflict, match="revision"):
            with reader.source_transaction(TENANT):
                save(reader, manifest([first], current=record), expected=1)


def test_owner_isolation_and_cross_document_adoption_denied(engine):
    first, record = create(engine)
    assert engine.get_document_record(TENANT, "other-owner", "observatory") is None
    assert engine.get_evidence_for_read(TENANT, first["cid"], access_context={"user_id": "other-owner"}) is None
    with pytest.raises(DocumentConflict, match="custody"):
        with engine.source_transaction(TENANT):
            save(engine, manifest([first], owner="other-owner"))
    with pytest.raises(DocumentConflict, match="another document"):
        with engine.source_transaction(TENANT):
            save(engine, manifest([first], document_id="another"))
    _, other = create(engine, owner="other-owner")
    assert other["segments"][0]["cid"] != first["cid"]
    assert len(engine.list_document_records(TENANT)) == 2
    record["settings"]["tamper"] = True
    assert engine.get_document_record(TENANT, OWNER, "observatory")["settings"] == {}


def test_retired_occurrence_cannot_reactivate_and_append_cannot_set_retirement(engine):
    first, record = create(engine)
    second, changed = replace(engine, first, record)
    with pytest.raises((ValueError, DocumentConflict)):
        with engine.source_transaction(TENANT):
            save(engine, manifest([first], current=changed), expected=2)
    with pytest.raises(ValueError, match="cannot set retired_at"):
        engine.append_evidence(Evidence(
            tenant_id=TENANT, user_id=OWNER, actor="user", source_type="document", content="forged",
            document_segment_id="forged", retired_at=CREATED,
        ))
    with engine.source_transaction(TENANT):
        fresh = append(engine, "doc/third", "The observatory opens on Tuesday.")
        final = save(engine, manifest([fresh], current=changed), expected=2)
    assert fresh["cid"] != first["cid"]
    assert final["retired_segments"] == [first, second]


@pytest.mark.parametrize("kind", ["working", "intention"])
def test_retired_source_no_longer_authorizes_working_or_intention_records(engine, kind):
    first, record = create(engine)
    if kind == "working":
        item = WorkingMemoryItem(
            item_id="goal", tenant_id=TENANT, session_id="document-session", user_id=OWNER,
            agent_id="document-agent", task_id="visit", kind="active_goal", content="Visit the observatory",
            created_at=CREATED, expires_at=CREATED + timedelta(minutes=30),
            evidence_ids=[first["cid"]],
        )
        engine.put_working(item)
        assert engine.get_working(TENANT, "document-session", "goal", as_of=CREATED)
        replace(engine, first, record)
        with pytest.raises(ValueError, match="retired"):
            engine.get_working(TENANT, "document-session", "goal", as_of=CREATED)
    else:
        due_at = CREATED + timedelta(days=30)
        item = Intention(
            intention_id="visit", tenant_id=TENANT, user_id=OWNER, agent_id="document-agent",
            trigger_type="exact_time", trigger_expression={"at": due_at.isoformat()},
            action={"type": "remind", "message": "Visit the observatory"}, due_at=due_at,
            evidence_ids=[first["cid"]],
        )
        engine.schedule_intention(item)
        replace(engine, first, record)
        item.intention_id = "visit-again"
        with pytest.raises(ValueError, match="missing"):
            engine.schedule_intention(item)


def test_branch_copy_merge_preflight_and_discard(engine):
    first, record = create(engine)
    engine.branch("candidate", tenant_id=TENANT)
    copied = engine.get_document_record(TENANT, OWNER, "observatory", "candidate")
    assert copied == {**record, "branch": "candidate"}
    engine.merge("candidate", tenant_id=TENANT)
    _, changed = replace(engine, first, copied, branch="candidate")
    unrelated = append(engine, "unrelated", "An unrelated source", branch="candidate")
    before = engine.export_tenant(TENANT)
    with pytest.raises(DocumentConflict, match="divergent"):
        engine.merge("candidate", tenant_id=TENANT)
    assert engine.export_tenant(TENANT) == before
    assert engine.get_evidence(TENANT, unrelated["cid"]) is None
    assert engine.get_document_record(TENANT, OWNER, "observatory") == record
    assert engine.get_document_record(TENANT, OWNER, "observatory", "candidate") == changed
    engine.discard("candidate", tenant_id=TENANT)
    assert engine.list_document_records(TENANT, "candidate") == []
    assert engine.get_evidence(TENANT, first["cid"]).retired_at is None


def test_merge_copies_absent_document_and_its_retired_history(engine):
    engine.branch("candidate", tenant_id=TENANT)
    first, record = create(engine, branch="candidate")
    second, changed = replace(engine, first, record, branch="candidate")
    engine.merge("candidate", tenant_id=TENANT)
    assert engine.get_document_record(TENANT, OWNER, "observatory") == {**changed, "branch": "main"}
    assert engine.get_evidence(TENANT, first["cid"]).retired_at is not None
    assert engine.get_evidence(TENANT, second["cid"]).retired_at is None


def test_merge_cannot_attach_document_to_destination_tombstone(engine):
    engine.branch("candidate", tenant_id=TENANT)
    first, _ = create(engine, branch="candidate")
    assert append(engine, "doc/first") == first
    engine.forget(TENANT, first["cid"])
    before = engine.export_tenant(TENANT)
    with pytest.raises(DocumentConflict, match="destination"):
        engine.merge("candidate", tenant_id=TENANT)
    assert engine.export_tenant(TENANT) == before
    assert engine.get_document_record(TENANT, OWNER, "observatory") is None


def test_merge_cannot_claim_another_documents_segment(engine):
    engine.branch("candidate", tenant_id=TENANT)
    create(engine, document_id="first-document")
    create(engine, document_id="second-document", branch="candidate")
    before = engine.export_tenant(TENANT)
    with pytest.raises(DocumentConflict, match="another document"):
        engine.merge("candidate", tenant_id=TENANT)
    assert engine.export_tenant(TENANT) == before
    assert engine.get_document_record(TENANT, OWNER, "second-document") is None


@pytest.mark.parametrize("mode", [ErasureMode.TOMBSTONE_RECOMPUTE, ErasureMode.HARD_DELETE_LEGAL])
def test_erasure_scrubs_current_and_retired_refs_and_deletion_marker_blocks_recreation(engine, mode):
    first, record = create(engine)
    second, changed = replace(engine, first, record)
    engine.branch("retained", tenant_id=TENANT)
    engine.forget(TENANT, first["cid"], requested_by="legal", erasure_mode=mode)
    scrubbed = engine.get_document_record(TENANT, OWNER, "observatory")
    assert scrubbed["retired_segments"] == [] and scrubbed["segments"] == [second]
    assert not scrubbed["deleted"] and scrubbed["revision"] == changed["revision"] + 1
    assert all(receipt["request_hash"] is None for receipt in scrubbed["receipts"])
    assert engine.get_document_record(TENANT, OWNER, "observatory", "retained") == {**changed, "branch": "retained"}
    engine.forget(TENANT, second["cid"], requested_by="legal", erasure_mode=mode)
    deleted = engine.get_document_record(TENANT, OWNER, "observatory")
    assert deleted["deleted"] and deleted["segments"] == []
    with pytest.raises(DocumentConflict, match="deleted"):
        with engine.source_transaction(TENANT):
            fresh = append(engine, "doc/reborn", "New private content")
            save(engine, manifest([fresh], current=deleted), expected=deleted["revision"])
    assert engine.get_evidence(TENANT, fresh["cid"]) is None


def test_erasure_manifest_scrub_rolls_back_with_source(engine):
    first, record = create(engine)
    with pytest.raises(ValueError, match="abort erasure"):
        with engine.source_transaction(TENANT):
            engine.forget(TENANT, first["cid"])
            assert engine.get_document_record(TENANT, OWNER, "observatory")["deleted"]
            raise ValueError("abort erasure")
    assert engine.get_document_record(TENANT, OWNER, "observatory") == record
    assert engine.get_evidence(TENANT, first["cid"]) is not None


def test_old_database_additive_migration_and_legacy_decoder(tmp_path):
    path = tmp_path / "legacy"
    with closing(SqliteEngine(path)) as original:
        cid = original.append_evidence(Evidence(
            tenant_id=TENANT, user_id=OWNER, actor="user", source_type="chat", content="Legacy source",
        ))
        database = original._tenant_db_path(TENANT)
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("DROP TABLE documents")
        conn.execute("ALTER TABLE evidence DROP COLUMN retired_at")
        assert _evidence_from_row(conn.execute("SELECT * FROM evidence").fetchone()).retired_at is None
    with closing(SqliteEngine(path)) as reopened:
        assert reopened.get_evidence(TENANT, cid).retired_at is None
        assert reopened.list_document_records(TENANT) == []
        assert "retired_at" in {row[1] for row in reopened._connect(TENANT).execute("PRAGMA table_info(evidence)")}
