"""Provider-free document service contracts across native storage backends."""

from dataclasses import replace
import json
import os
from uuid import uuid4

import pytest

from mnemosyne.answering import AnswerReadContext
from mnemosyne.documents import DocumentService, split_document_text
from mnemosyne.document_storage import DocumentConflict
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Assertion, Evidence, utc_now
from mnemosyne.postgres_engine import PostgresEngine
from mnemosyne.privacy import ErasureMode
from mnemosyne.sqlite_engine import SqliteEngine


@pytest.fixture(params=["local", "sqlite", "postgres"])
def store(request, tmp_path):
    if request.param == "local":
        engine = LocalMemoryEngine(tmp_path / "memory.json")
    elif request.param == "sqlite":
        engine = SqliteEngine(tmp_path / "sqlite")
    else:
        dsn = os.environ.get("MNEMOSYNE_POSTGRES_DSN")
        if not dsn:
            pytest.skip("disposable PostgreSQL DSN not configured")
        engine = PostgresEngine(dsn)
    context = AnswerReadContext(tenant_id=f"documents-{uuid4().hex}", user_id="owner", role="agent")
    yield engine, DocumentService(engine), context
    if isinstance(engine, PostgresEngine):
        engine.close_connections()
    else:
        engine.close()


@pytest.mark.parametrize("text", ["", "A", "\n\n", "a\n\nb\n\n", "a\r\n \r\nb\r\n", "🙂é" * 2300, "  x\n y  "])
def test_splitter_is_lossless_and_bounded(text):
    parts = split_document_text(text, chunk_chars=64)
    assert "".join(parts) == text
    assert all(0 < len(part) <= 64 for part in parts)
    assert split_document_text(text, chunk_chars=64) == parts


@pytest.mark.parametrize("invalid", [0, -1, 63, 16385, 64.0, True])
def test_splitter_rejects_invalid_size(invalid):
    with pytest.raises(ValueError):
        split_document_text("abc", chunk_chars=invalid)


def manifest(store, document_id="guide"):
    engine, _, ctx = store
    return engine.get_document_record(ctx.tenant_id, ctx.user_id, document_id, ctx.branch)


def test_replace_keeps_exact_occurrences_and_retires_changed_prose(store):
    engine, service, ctx = store
    first = service.create(ctx, "guide", "Always use amber.\n\nOld delivery is Friday.\n\n", operation_id="create")
    old = service.get(ctx, "guide")
    second = service.replace(ctx, "guide", "Always use amber.\n\nNew delivery is Monday.\n\n",
                             expected_revision=first.revision, operation_id="replace")
    new = service.get(ctx, "guide")
    assert (second.revision, second.created, second.reused, second.retired) == (2, 1, 1, 1)
    assert new.segment_cids[0] == old.segment_cids[0]
    assert new.segment_cids[1] != old.segment_cids[1]
    retired = engine.get_evidence(ctx.tenant_id, old.segment_cids[1])
    assert retired.content == "Old delivery is Friday.\n\n" and retired.retired_at is not None
    assert engine.get_evidence_for_read(ctx.tenant_id, retired.cid, access_context=ctx.to_filter()) is None
    assert manifest(store)["retired_segments"][0]["cid"] == retired.cid


def test_reordering_duplicates_reuses_each_occurrence_once(store):
    _, service, ctx = store
    service.create(ctx, "guide", "A\n\nB\n\nA\n\n", operation_id="create")
    old = service.get(ctx, "guide")
    receipt = service.replace(ctx, "guide", "A\n\nA\n\nB\n\n", expected_revision=1, operation_id="reorder")
    new = service.get(ctx, "guide")
    assert new.segment_cids == (old.segment_cids[0], old.segment_cids[2], old.segment_cids[1])
    assert (receipt.created, receipt.reused, receipt.retired) == (0, 3, 0)


def test_append_is_exact_and_only_new_or_changed_tail_is_admitted(store):
    _, service, ctx = store
    service.create(ctx, "guide", "A\n\nB", operation_id="create")
    before = service.get(ctx, "guide")
    receipt = service.append(ctx, "guide", "eta\n\nGamma", expected_revision=1, operation_id="append")
    after = service.get(ctx, "guide")
    assert after.content == "A\n\nBeta\n\nGamma"
    assert after.segment_cids[0] == before.segment_cids[0]
    assert (receipt.created, receipt.reused, receipt.retired) == (2, 1, 1)


def test_returning_to_old_text_creates_a_new_occurrence(store):
    engine, service, ctx = store
    service.create(ctx, "guide", "A", operation_id="create")
    old_cid = service.get(ctx, "guide").segment_cids[0]
    service.replace(ctx, "guide", "B", operation_id="b", expected_revision=1)
    service.replace(ctx, "guide", "A", operation_id="a", expected_revision=2)
    current = service.get(ctx, "guide")
    assert current.revision == 3 and current.content == "A"
    assert current.segment_cids[0] != old_cid
    assert engine.get_evidence(ctx.tenant_id, old_cid).retired_at is not None


def test_retry_returns_same_receipt_and_old_operation_never_reapplies(store):
    _, service, ctx = store
    original = service.create(ctx, "guide", "A", operation_id="create")
    before = manifest(store)
    assert service.create(ctx, "guide", "A", operation_id="create") == original
    assert manifest(store) == before
    changed = service.append(ctx, "guide", "B", operation_id="append", expected_revision=1)
    assert service.append(ctx, "guide", "B", operation_id="append", expected_revision=1) == changed
    with pytest.raises(DocumentConflict):
        service.append(ctx, "guide", "C", operation_id="append", expected_revision=1)
    with pytest.raises(DocumentConflict):
        service.create(ctx, "guide", "A", operation_id="create")
    assert service.get(ctx, "guide").content == "AB"
    assert manifest(store)["receipts"][0]["request_hash"] is None


def test_cas_rejects_stale_writer_without_source_or_receipt_changes(store):
    engine, service, ctx = store
    service.create(ctx, "guide", "A", operation_id="create")
    service.replace(ctx, "guide", "B", operation_id="winner", expected_revision=1)
    before = engine.export_tenant(ctx.tenant_id)
    before_manifest = manifest(store)
    with pytest.raises(DocumentConflict):
        service.replace(ctx, "guide", "C", operation_id="loser", expected_revision=1)
    assert manifest(store) == before_manifest
    assert engine.export_tenant(ctx.tenant_id)["evidence"] == before["evidence"]


def test_document_transaction_rolls_back_new_sources_and_retirement(store, monkeypatch):
    engine, service, ctx = store
    service.create(ctx, "guide", "A", operation_id="create")
    before = manifest(store)
    before_sources = engine.export_tenant(ctx.tenant_id)["evidence"]
    save = engine.save_document_record

    def fail_after_save(*args, **kwargs):
        save(*args, **kwargs)
        raise RuntimeError("injected after manifest publication")

    monkeypatch.setattr(engine, "save_document_record", fail_after_save)
    with pytest.raises(RuntimeError, match="injected"):
        service.replace(ctx, "guide", "B", expected_revision=1, operation_id="replace")
    assert manifest(store) == before
    assert engine.export_tenant(ctx.tenant_id)["evidence"] == before_sources
    assert service.get(ctx, "guide").content == "A"


def test_owners_are_independent_and_source_identity_cannot_impersonate_owner(store):
    engine, service, ctx = store
    service.create(ctx, "guide", "Secret amber", operation_id="create")
    own = service.get(ctx, "guide")
    other = replace(ctx, user_id="other", source_identity="owner")
    assert service.get(other, "guide") is None
    assert engine.get_evidence_for_read(ctx.tenant_id, own.segment_cids[0], access_context=other.to_filter()) is None
    service.create(other, "guide", "Other blue", operation_id="create")
    assert service.get(other, "guide").content == "Other blue"
    assert service.get(ctx, "guide").content == "Secret amber"


@pytest.mark.parametrize("mode", [ErasureMode.TOMBSTONE_RECOMPUTE, ErasureMode.HARD_DELETE_LEGAL])
def test_erasing_sources_scrubs_registry_and_leaves_non_recreatable_document(store, mode):
    engine, service, ctx = store
    service.create(ctx, "guide", "A", operation_id="create")
    old = service.get(ctx, "guide").segment_cids[0]
    service.replace(ctx, "guide", "B", operation_id="replace", expected_revision=1)
    current = service.get(ctx, "guide").segment_cids[0]
    result = engine.forget(ctx.tenant_id, old, erasure_mode=mode)
    assert result["erased"]
    assert old not in json.dumps(manifest(store))
    assert service.get(ctx, "guide").content == "B"
    assert engine.forget(ctx.tenant_id, current, erasure_mode=mode)["erased"]
    record = manifest(store)
    assert record["deleted"] and not record["segments"] and not record["retired_segments"]
    assert all(receipt["request_hash"] is None for receipt in record["receipts"])
    assert service.get(ctx, "guide") is None
    with pytest.raises(DocumentConflict, match="deleted"):
        service.create(ctx, "guide", "A", operation_id="new-identity")


def test_empty_document_and_exact_noop_have_durable_revisions(store):
    _, service, ctx = store
    created = service.create(ctx, "guide", "", operation_id="create")
    assert (created.revision, created.created) == (1, 0)
    updated = service.replace(ctx, "guide", "", operation_id="empty", expected_revision=1)
    assert (updated.revision, updated.created, updated.reused, updated.retired) == (2, 0, 0, 0)
    assert service.get(ctx, "guide").content == ""


@pytest.mark.parametrize("route", ["lexical", "vector", "retrieve"])
def test_retired_sources_and_dependent_prose_leave_warm_recall(store, route):
    engine, service, ctx = store
    service.create(ctx, "guide", "The secret launch code is amber.", operation_id="create")
    cid = service.get(ctx, "guide").segment_cids[0]
    summary = engine.append_evidence(Evidence(
        tenant_id=ctx.tenant_id, user_id=ctx.user_id, actor="system", source_type="consolidation-summary",
        content="The secret launch code is amber.", metadata={"summary": {"source_evidence_cids": [cid], "status": "active"}},
    ))
    fact = engine.upsert_assertion(Assertion(
        tenant_id=ctx.tenant_id, user_id=ctx.user_id, subject="secret launch code", predicate="is", object="amber",
        source_evidence_cids=[cid], confidence=0.95, status="active",
    ))

    def search():
        if route == "retrieve":
            return engine.retrieve("secret launch code amber", tenant_id=ctx.tenant_id, filt=ctx.to_filter(), record_access=False).hits
        return getattr(engine, f"{route}_search")("secret launch code amber", 20, ctx.to_filter())

    assert {cid, fact} & {hit.id for hit in search()}
    service.replace(ctx, "guide", "The launch is cancelled.", operation_id="replace", expected_revision=1)
    assert not {cid, fact, summary} & {hit.id for hit in search()}
    assert engine.get_evidence_for_read(ctx.tenant_id, summary, access_context=ctx.to_filter()) is None


@pytest.mark.parametrize("change", [{"role": "reader"}, {"user_id": None}, {"break_glass": True}, {"as_of": "2020-01-01T00:00:00Z"}])
def test_mutation_requires_current_authenticated_writer_context(store, change):
    _, service, ctx = store
    with pytest.raises((ValueError, PermissionError)):
        service.create(replace(ctx, **change), "guide", "A", operation_id="create")


def test_append_limit_rejects_without_committing(store):
    engine, _, ctx = store
    service = DocumentService(engine, max_content_chars=4)
    service.create(ctx, "guide", "ABC", operation_id="create")
    with pytest.raises(ValueError, match="limit"):
        service.append(ctx, "guide", "DE", expected_revision=1, operation_id="too-long")
    assert service.get(ctx, "guide").content == "ABC" and manifest(store)["revision"] == 1


def test_historical_graph_query_keeps_current_owner_and_retirement_checks(store):
    from mnemosyne.mcp_tools import MemoryTools

    engine, service, ctx = store
    service.create(ctx, "guide", "The archive code is amber.", operation_id="create")
    cid = service.get(ctx, "guide").segment_cids[0]
    engine.upsert_assertion(Assertion(
        tenant_id=ctx.tenant_id, user_id=ctx.user_id, subject="archive code", predicate="is", object="amber",
        source_evidence_cids=[cid], confidence=0.95, status="active",
    ))
    tools = MemoryTools(engine)
    moment = utc_now().isoformat()
    assert tools.graph_as_of(ctx.tenant_id, "archive code", "is", moment, user_id=ctx.user_id)["assertions"]
    assert not tools.graph_as_of(ctx.tenant_id, "archive code", "is", moment, user_id="other")["assertions"]
    assert not tools.graph_as_of(ctx.tenant_id, "archive code", "is", moment)["assertions"]
    service.replace(ctx, "guide", "The archive is closed.", expected_revision=1, operation_id="replace")
    assert not tools.graph_as_of(ctx.tenant_id, "archive code", "is", moment, user_id=ctx.user_id)["assertions"]


def test_summary_snapshot_cannot_publish_or_capture_retired_inputs(store):
    from mnemosyne.consolidation import _SourceCustody

    engine, service, ctx = store
    service.create(ctx, "guide", "Original source.", operation_id="create")
    cid = service.get(ctx, "guide").segment_cids[0]
    original = engine.get_evidence(ctx.tenant_id, cid)
    custody = _SourceCustody(engine)
    snapshot = custody.capture(ctx.tenant_id, ctx.branch, [original])
    assert snapshot is not None
    service.replace(ctx, "guide", "Changed source.", operation_id="replace", expected_revision=1)
    assert not custody.unchanged(ctx.tenant_id, ctx.branch, snapshot, [original])
    assert custody.capture(ctx.tenant_id, ctx.branch, [engine.get_evidence(ctx.tenant_id, cid)]) is None


# Regression contracts for the independent document-service review findings.


def test_lower_trust_writer_cannot_launder_text_into_trusted_document(store):
    engine, service, ctx = store
    service.create(ctx, "guide", "Trusted text.", operation_id="create")
    before = manifest(store)
    before_sources = engine.export_tenant(ctx.tenant_id)["evidence"]
    tainted = replace(ctx, source_trust_tier=5, capability_tags=("data-only",))
    with pytest.raises(PermissionError):
        service.replace(tainted, "guide", "Injected text.", expected_revision=1, operation_id="launder")
    with pytest.raises(PermissionError):
        service.append(tainted, "guide", " Injected.", expected_revision=1, operation_id="launder-append")
    assert manifest(store) == before
    assert engine.export_tenant(ctx.tenant_id)["evidence"] == before_sources
    assert service.get(ctx, "guide").content == "Trusted text."


def test_pii_beyond_writer_ceiling_is_refused_before_any_source_write(store):
    engine, service, ctx = store  # "agent" reads at most S2; PII is S3.
    service.create(ctx, "guide", "Plain intro.\n\n", operation_id="create")
    before = manifest(store)
    before_sources = engine.export_tenant(ctx.tenant_id)["evidence"]
    with pytest.raises(PermissionError, match="sensitivity"):
        service.append(ctx, "guide", "Reach me at synthetic.person@example.com", expected_revision=1, operation_id="pii")
    with pytest.raises(PermissionError, match="sensitivity"):
        service.create(ctx, "other", "synthetic.person@example.com", operation_id="pii-create")
    assert manifest(store) == before
    assert engine.export_tenant(ctx.tenant_id)["evidence"] == before_sources


def test_pii_raises_document_and_segment_sensitivity_monotonically(store):
    engine, service, ctx = store
    ctx = replace(ctx, role="consolidator")
    service.create(ctx, "guide", "Plain intro.\n\n", operation_id="create")
    assert manifest(store)["settings"]["sensitivity"] == 0
    service.append(ctx, "guide", "Reach me at synthetic.person@example.com", expected_revision=1, operation_id="pii")
    record = manifest(store)
    assert record["settings"]["sensitivity"] == 3
    new_cid = record["segments"][-1]["cid"]
    row = engine.get_evidence(ctx.tenant_id, new_cid)
    assert row.sensitivity == 3 and any(tag.startswith("pii:") for tag in row.capability_tags)
    # Removing the PII never lowers the document's sensitivity again.
    service.replace(ctx, "guide", "Plain intro.\n\n", expected_revision=2, operation_id="scrub")
    assert engine.get_document_record(ctx.tenant_id, ctx.user_id, "guide", ctx.branch)["settings"]["sensitivity"] == 3
    low = replace(ctx, max_sensitivity=1)
    with pytest.raises(PermissionError):
        service.get(low, "guide")


def test_source_revoked_during_read_is_never_returned(store):
    engine, service, ctx = store
    service.create(ctx, "guide", "Text later quarantined", operation_id="create")
    cid = service.get(ctx, "guide").segment_cids[0]
    original = engine.get_document_record
    calls = [0]

    def concurrent_read(*args, **kwargs):
        calls[0] += 1
        if calls[0] == 2:
            engine.update_evidence_metadata(ctx.tenant_id, cid, {"quarantine_reason": "revoked during document read"})
        return original(*args, **kwargs)

    engine.get_document_record = concurrent_read
    try:
        with pytest.raises(DocumentConflict):
            service.get(ctx, "guide")
    finally:
        engine.get_document_record = original
    assert engine.get_evidence_for_read(ctx.tenant_id, cid, access_context=ctx.to_filter()) is None


@pytest.mark.parametrize("field,value", [
    ("chunk_chars", 0), ("trust_tier", -99), ("sensitivity", "invalid"),
    ("capability_tags", {"unsupported": "object"}), ("splitter_version", 2), ("chunk_chars", True),
])
def test_invalid_document_settings_are_rejected_before_storage(store, field, value):
    engine, service, ctx = store
    service.create(ctx, "guide", "A", operation_id="create")
    before = manifest(store)
    record = json.loads(json.dumps(before))
    record["settings"][field] = value
    record["receipts"].append({"operation_id": "bad", "action": "replace", "revision": 2,
                               "request_hash": "a" * 64, "created": 0, "reused": 1, "retired": 0})
    with pytest.raises(ValueError):
        with engine.source_transaction(ctx.tenant_id, ctx.branch):
            engine.save_document_record(ctx.tenant_id, ctx.user_id, "guide", record, ctx.branch, expected_revision=1)
    assert manifest(store) == before
    assert service.get(ctx, "guide").content == "A"


def test_segment_count_limit_rejects_before_any_source_write(store, monkeypatch):
    engine, service, ctx = store
    calls = []

    def trap(*args, **kwargs):
        calls.append(1)
        raise AssertionError("no source may be admitted for an over-limit document")

    monkeypatch.setattr(engine, "append_evidence", trap)
    with pytest.raises(ValueError, match="segment count limit"):
        service.create(ctx, "guide", "a\n\n" * 100_001, operation_id="oversized")
    assert calls == []
    assert manifest(store) is None
