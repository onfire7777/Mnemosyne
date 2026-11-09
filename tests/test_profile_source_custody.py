"""Profile packets keep source authority even when cleanup must be retried."""
from __future__ import annotations

from mnemosyne.mcp_tools import MemoryTools
from mnemosyne.models import Evidence
from mnemosyne.user_model import LatentUserProfile, SupportStrategy, UserMistakeEvent, UserModel, UserModelEntry, UserMemoryKind
from tests.test_ingestion_acknowledgement import engine as engine, pipeline as pipeline, _request


def test_source_guard_is_batched_and_preserves_manual_entries(pipeline, monkeypatch):
    tools = MemoryTools(engine=pipeline.engine, ingestion=pipeline)
    request = _request()
    source = pipeline.ingest(request)
    sourced = tools.profile_record_explicit(request.tenant_id, request.user_id, "Verified preference.", source_evidence_cids=[source.cid])
    manual = tools.profile_record_explicit(request.tenant_id, request.user_id, "Manual preference.")
    monkeypatch.setattr(pipeline.engine, "export_tenant", lambda *_: (_ for _ in ()).throw(AssertionError("profile read scanned corpus")))
    reads = []
    original = pipeline.engine.get_evidence
    def get(*args, **kwargs):
        reads.append(args)
        return original(*args, **kwargs)
    monkeypatch.setattr(pipeline.engine, "get_evidence", get)
    packet = tools.user_model.context_packet(request.tenant_id, request.user_id, {})
    assert {row["id"] for row in packet["authoritative"]} == {sourced["id"], manual["id"]}
    assert len(reads) == 1
    monkeypatch.setattr(pipeline.engine, "list_branches", lambda *_: (_ for _ in ()).throw(RuntimeError("read unavailable")))
    packet = tools.profile_context(request.tenant_id, request.user_id)
    assert [row["id"] for row in packet["authoritative"]] == [manual["id"]]


def test_authorized_branch_copy_preserves_profile_until_it_is_denied(pipeline):
    tools = MemoryTools(engine=pipeline.engine, ingestion=pipeline)
    request = _request()
    source = pipeline.ingest(request)
    profile = tools.profile_record_explicit(request.tenant_id, request.user_id, "Branch-backed preference.", source_evidence_cids=[source.cid])
    pipeline.engine.branch("side", tenant_id=request.tenant_id)
    pipeline.engine.forget(request.tenant_id, source.cid)
    assert any(row["id"] == profile["id"] for row in tools.profile_context(request.tenant_id, request.user_id)["authoritative"])
    pipeline.engine.backfill_evidence_privacy(request.tenant_id, source.cid, ["secret"], branch="side")
    assert tools.profile_context(request.tenant_id, request.user_id)["authoritative"] == []


def test_summary_backed_profile_requires_live_transitive_sources(pipeline):
    tools = MemoryTools(engine=pipeline.engine, ingestion=pipeline)
    request = _request()
    source = pipeline.ingest(request)
    summary = pipeline.engine.append_evidence(Evidence(
        tenant_id=request.tenant_id, user_id=request.user_id, actor="system",
        source_type="consolidation-summary", content="Source-backed summary preference.",
        metadata={"source_evidence_cids": [source.cid], "summary": {"source_evidence_cids": [source.cid]}},
        access_policy={"tenant": request.tenant_id},
    ))
    tools.profile_record_explicit(request.tenant_id, request.user_id, "Summary preference.", source_evidence_cids=[summary])
    assert tools.profile_context(request.tenant_id, request.user_id)["authoritative"]
    pipeline.engine.backfill_evidence_privacy(request.tenant_id, source.cid, ["secret"])
    assert tools.profile_context(request.tenant_id, request.user_id)["authoritative"] == []


def test_independently_sourced_current_statement_survives_old_source_erasure(pipeline):
    tools = MemoryTools(engine=pipeline.engine, ingestion=pipeline)
    first_request = _request()
    first = pipeline.ingest(first_request)
    old = tools.profile_propose_inference(first_request.tenant_id, first_request.user_id, "Old inferred preference.", source_evidence_cids=[first.cid])
    second = pipeline.ingest(_request(tenant_id=first_request.tenant_id, content="A new, independently stated preference."))
    current = tools.profile_record_explicit(first_request.tenant_id, first_request.user_id, "Current preference.", source_evidence_cids=[second.cid])
    assert tools.user_model.entries[old["id"]].status != "active"
    pipeline.engine.forget(first_request.tenant_id, first.cid)
    packet = tools.profile_context(first_request.tenant_id, first_request.user_id)
    assert [row["id"] for row in packet["authoritative"]] == [current["id"]]


def test_cycle_and_missing_support_events_are_not_treated_as_manual():
    model = UserModel()
    for item_id, sources in (("a", ["b"]), ("b", ["c"]), ("c", ["b"])):
        model.entries[item_id] = UserModelEntry("t", "u", UserMemoryKind.EXPLICIT_PREFERENCE, item_id, source_evidence_cids=sources, id=item_id)
    manual = UserModelEntry("t", "u", UserMemoryKind.EXPLICIT_PREFERENCE, "Manual", id="manual")
    model.entries[manual.id] = manual
    strategy = SupportStrategy("t", "u", "dates", "Check dates", supporting_event_ids=["missing"], id="strategy")
    model.support_strategies[strategy.id] = strategy
    model.bind_source_custody(lambda *_: set())
    packet = model.context_packet("t", "u", {})
    assert [row["id"] for row in packet["authoritative"]] == [manual.id]
    assert packet["support_strategies"] == []


def test_support_and_latent_sources_are_checked_with_entry_sources():
    model = UserModel()
    event = UserMistakeEvent("t", "u", "dates", "Date slip", scope={"_learning_source_cids": ["source"]})
    model.mistake_events.append(event)
    strategy = SupportStrategy("t", "u", "dates", "Check dates", supporting_event_ids=[event.id])
    model.support_strategies[strategy.id] = strategy
    model.set_latent_profile(LatentUserProfile("t", "u", [], "Consolidated 1 prioritized evidence item(s) | source_cids=source | evidence=private"))
    calls = []
    def resolver(tenant, user, cids):
        calls.append(cids)
        return set()
    model.bind_source_custody(resolver)
    packet = model.context_packet("t", "u", {})
    assert calls == [["source"]]
    assert packet["support_strategies"] == [] and packet["latent_advisory"] is None


def test_reloaded_and_shared_profile_objects_recheck_source_custody(pipeline, tmp_path, monkeypatch):
    import pytest
    from mnemosyne.postgres_engine import PostgresEngine
    from mnemosyne.postgres_runtime_state import PostgresRuntimeState
    from mnemosyne.runtime_state import RuntimeState

    request = _request()
    def state():
        return (PostgresRuntimeState(pipeline.engine.dsn, tenant_id=request.tenant_id)
                if isinstance(pipeline.engine, PostgresEngine) else RuntimeState(tmp_path / "profile-state.json"))
    tools = MemoryTools(engine=pipeline.engine, ingestion=pipeline, runtime_state=state())
    source = pipeline.ingest(request)
    profile = tools.profile_record_explicit(request.tenant_id, request.user_id, "Sourced preference.", source_evidence_cids=[source.cid])
    manual = tools.profile_record_explicit(request.tenant_id, request.user_id, "Manual preference.")
    def fail_cleanup(*_):
        raise RuntimeError("profile cleanup unavailable")
    monkeypatch.setattr(pipeline.engine, "_learning_profile_erasure", fail_cleanup)
    with pytest.raises(RuntimeError, match="profile cleanup unavailable"):
        pipeline.engine.forget(request.tenant_id, source.cid)
    reloaded = MemoryTools(engine=pipeline.engine, ingestion=pipeline, runtime_state=state())
    for reader in (tools, reloaded):
        packet = reader.user_model.context_packet(request.tenant_id, request.user_id, {})
        assert profile["id"] not in {row["id"] for row in packet["authoritative"]}
        assert manual["id"] in {row["id"] for row in packet["authoritative"]}


def test_public_packet_omits_drift_history_without_hiding_current_statement():
    model = UserModel()
    entry = UserModelEntry("t", "u", UserMemoryKind.EXPLICIT_PREFERENCE, "Current supported preference.",
                           source_evidence_cids=["live"], scope={"drift_history": [{
                               "new_statement": "erased private drift text", "new_evidence_cid": "erased",
                           }]})
    model.entries[entry.id] = entry
    model.bind_source_custody(lambda *_: {"live"})
    packet = model.context_packet("t", "u", {})
    assert packet["authoritative"][0]["statement"] == entry.statement
    assert "drift_history" not in packet["authoritative"][0]["scope"]
    assert "erased private drift text" not in str(packet)
