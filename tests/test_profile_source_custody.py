"""Profile packets keep source authority even when cleanup must be retried."""
from __future__ import annotations

import pytest

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


@pytest.mark.parametrize("residue", ["drift", "latent", "both", "transitive"])
def test_erasure_scrubs_persisted_residue_without_retracting_live_entry(pipeline, tmp_path, residue):
    from mnemosyne.postgres_engine import PostgresEngine
    from mnemosyne.postgres_runtime_state import PostgresRuntimeState
    from mnemosyne.runtime_state import RuntimeState

    request = _request()
    runtime_state = (PostgresRuntimeState(pipeline.engine.dsn, tenant_id=request.tenant_id)
                     if isinstance(pipeline.engine, PostgresEngine) else RuntimeState(tmp_path / "residue.json"))
    tools = MemoryTools(engine=pipeline.engine, ingestion=pipeline, runtime_state=runtime_state)
    live = pipeline.ingest(request)
    secret = "private drift and latent residue"
    erased = pipeline.ingest(_request(tenant_id=request.tenant_id, content=secret))
    residue_cid = erased.cid
    if residue == "transitive":
        residue_cid = pipeline.engine.append_evidence(Evidence(
            tenant_id=request.tenant_id, user_id=request.user_id, actor="system",
            source_type="consolidation-summary", content=secret + " summary",
            metadata={"source_evidence_cids": [erased.cid]}, access_policy={"tenant": request.tenant_id},
        ))
    profile = tools.profile_record_explicit(request.tenant_id, request.user_id, "Live independent preference.",
                                            source_evidence_cids=[live.cid])
    entry = tools.user_model.entries[profile["id"]]
    if residue != "latent":
        entry.scope["drift_history"] = [{"entry_id": entry.id, "new_evidence_cid": residue_cid,
                                          "new_statement": secret}]
    if residue != "drift":
        tools.user_model.set_latent_profile(LatentUserProfile(request.tenant_id, request.user_id, [0.5],
            f"Consolidated 1 prioritized evidence item(s) | source_cids={residue_cid} | evidence={secret}"))
    manual = LatentUserProfile(request.tenant_id, "other-user", [0.2], "Manual independent summary.")
    tools.user_model.set_latent_profile(manual)
    foreign = LatentUserProfile("other-tenant", request.user_id, [0.3], f"source_cids={erased.cid} | foreign summary")
    tools.user_model.set_latent_profile(foreign)
    runtime_state.save_user_model(tools.user_model)
    result = tools.forget(request.tenant_id, erased.cid)
    assert profile["id"] not in result.get("retracted_profile_entries", [])
    assert entry.status == "active" and entry.statement == "Live independent preference."
    assert "drift_history" not in entry.scope
    assert (request.tenant_id, request.user_id) not in tools.user_model.latent_profiles
    assert tools.user_model.latent_profiles[(request.tenant_id, "other-user")].summary == manual.summary
    assert tools.user_model.latent_profiles[(foreign.tenant_id, foreign.user_id)].summary == foreign.summary
    reopened = (PostgresRuntimeState(pipeline.engine.dsn, tenant_id=request.tenant_id)
                if isinstance(pipeline.engine, PostgresEngine) else RuntimeState(runtime_state.path))
    reloaded = reopened.load_user_model()
    assert reloaded.entries[entry.id].statement == entry.statement
    assert "drift_history" not in reloaded.entries[entry.id].scope
    assert (request.tenant_id, request.user_id) not in reloaded.latent_profiles
    assert secret not in str(reloaded.entries[entry.id].to_dict())
    if isinstance(pipeline.engine, PostgresEngine):
        with reopened.connect() as conn:
            with conn.cursor() as cur:
                reopened._set_tenant(cur)
                cur.execute("SELECT scope::text FROM preferences WHERE tenant_id = %s", (reopened.db_tenant_id,))
                assert secret not in str(cur.fetchall())
                cur.execute("SELECT summary FROM user_latent WHERE tenant_id = %s", (reopened.db_tenant_id,))
                assert secret not in str(cur.fetchall())


def test_profile_residue_retains_a_live_branch_copy_until_final_erasure(pipeline):
    tools = MemoryTools(engine=pipeline.engine, ingestion=pipeline)
    request = _request()
    live = pipeline.ingest(request)
    original = pipeline.ingest(_request(tenant_id=request.tenant_id, content="Branch-supported source."))
    profile = tools.profile_record_explicit(request.tenant_id, request.user_id, "Live preference.", source_evidence_cids=[live.cid])
    entry = tools.user_model.entries[profile["id"]]
    entry.scope["drift_history"] = [{"entry_id": entry.id, "new_evidence_cid": original.cid, "new_statement": "Branch-supported source."}]
    latent = LatentUserProfile(request.tenant_id, request.user_id, [0.5], f"source_cids={original.cid} | Branch-supported source.")
    tools.user_model.set_latent_profile(latent)
    pipeline.engine.branch("side", tenant_id=request.tenant_id)
    tools.forget(request.tenant_id, original.cid, all_branches=False)
    assert entry.scope["drift_history"]
    assert tools.user_model.latent_profiles[(request.tenant_id, request.user_id)] is latent
    tools.forget(request.tenant_id, original.cid)
    assert "drift_history" not in entry.scope
    assert (request.tenant_id, request.user_id) not in tools.user_model.latent_profiles
    assert entry.status == "active"


@pytest.mark.parametrize("history", [None, 42, {"unexpected": "object"}])
def test_malformed_drift_history_does_not_block_cleanup(history):
    model = UserModel()
    entry = UserModelEntry("t", "u", UserMemoryKind.EXPLICIT_PREFERENCE, "Live preference.",
                           source_evidence_cids=["live"], scope={"drift_history": history})
    model.entries[entry.id] = entry
    result = MemoryTools._erase_profile_model(model, None, "t", "unrelated")
    assert result["retracted_profile_entries"] == []
    assert entry.status == "active" and "drift_history" not in entry.scope


def test_hard_delete_retry_persists_cleanup_after_storage_failure(pipeline, tmp_path, monkeypatch):
    from mnemosyne.postgres_engine import PostgresEngine
    from mnemosyne.postgres_runtime_state import PostgresRuntimeState
    from mnemosyne.runtime_state import RuntimeState

    request = _request()
    is_postgres = isinstance(pipeline.engine, PostgresEngine)
    runtime_state = (PostgresRuntimeState(pipeline.engine.dsn, tenant_id=request.tenant_id)
                     if is_postgres else RuntimeState(tmp_path / "retry-profile.json"))
    tools = MemoryTools(engine=pipeline.engine, ingestion=pipeline, runtime_state=runtime_state)
    live = pipeline.ingest(request)
    secret = "erased profile storage residue"
    erased = pipeline.ingest(_request(tenant_id=request.tenant_id, content=secret))
    keep = tools.profile_record_explicit(request.tenant_id, request.user_id, "Keep current preference.", source_evidence_cids=[live.cid])
    remove = tools.profile_record_explicit(request.tenant_id, request.user_id, "Remove old preference.", source_evidence_cids=[erased.cid])
    tools.user_model.entries[keep["id"]].scope["drift_history"] = [{"new_evidence_cid": erased.cid, "new_statement": secret}]
    tools.user_model.set_latent_profile(LatentUserProfile(request.tenant_id, request.user_id, [0.4], f"source_cids={erased.cid} | {secret}"))
    runtime_state.save_user_model(tools.user_model)
    original = runtime_state.save_user_model
    saves = []
    def save(model):
        saves.append(1)
        assert "drift_history" not in model.entries[keep["id"]].scope
        assert (request.tenant_id, request.user_id) not in model.latent_profiles
        if len(saves) == 1:
            def fail(*_args, **_kwargs):
                raise OSError("profile persistence interrupted")
            # Fail after RuntimeState has replaced its in-memory payload, or
            # inside the PG transaction (payload rolls back with its profile mirror).
            with monkeypatch.context() as patch:
                patch.setattr(runtime_state, "_mirror_user_model" if is_postgres else "save", fail)
                return original(model)
        return original(model)
    monkeypatch.setattr(runtime_state, "save_user_model", save)
    options = {"requested_by": "legal", "erasure_mode": "hard_delete_legal"}
    with pytest.raises(OSError, match="profile persistence interrupted"):
        tools.forget(request.tenant_id, erased.cid, **options)
    assert pipeline.engine.get_evidence(request.tenant_id, erased.cid) is None
    assert "drift_history" in tools.user_model.entries[keep["id"]].scope
    packet = tools.profile_context(request.tenant_id, request.user_id)
    assert {row["id"] for row in packet["authoritative"]} == {keep["id"]}
    assert packet["latent_advisory"] is None
    retried = tools.forget(request.tenant_id, erased.cid, **options)
    assert retried["retracted_profile_entries"] == [remove["id"]]
    tools.forget(request.tenant_id, erased.cid, **options)
    tools.forget(request.tenant_id, "f" * 64)
    assert len(saves) == 2
    assert tools.user_model.entries[keep["id"]].status == "active"
    reopened = (PostgresRuntimeState(pipeline.engine.dsn, tenant_id=request.tenant_id)
                if is_postgres else RuntimeState(runtime_state.path))
    restored = reopened.load_user_model()
    assert "drift_history" not in restored.entries[keep["id"]].scope
    assert (request.tenant_id, request.user_id) not in restored.latent_profiles
    assert restored.entries[remove["id"]].status != "active"


def test_profile_probe_failure_restores_mutations_for_retry(pipeline, monkeypatch):
    tools = MemoryTools(engine=pipeline.engine, ingestion=pipeline)
    request = _request()
    erased = pipeline.ingest(request)
    live = pipeline.ingest(_request(tenant_id=request.tenant_id, content="Live independent source."))
    remove = tools.profile_record_explicit(request.tenant_id, request.user_id, "Old preference.", source_evidence_cids=[erased.cid])
    keep = tools.profile_record_explicit(request.tenant_id, request.user_id, "Live preference.", source_evidence_cids=[live.cid])
    tools.user_model.entries[keep["id"]].scope["drift_history"] = [{"entry_id": keep["id"], "new_evidence_cid": live.cid, "new_statement": "Still supported."}]
    original = MemoryTools._readable_profile_sources
    calls = []
    def probe(*args):
        calls.append(1)
        if len(calls) == 1:
            # The erased entry has already been retracted when this live
            # history row asks to validate its independent source.
            assert tools.user_model.entries[remove["id"]].status != "active"
            raise RuntimeError("source probe interrupted")
        return original(*args)
    monkeypatch.setattr(MemoryTools, "_readable_profile_sources", staticmethod(probe))
    options = {"requested_by": "legal", "erasure_mode": "hard_delete_legal"}
    with pytest.raises(RuntimeError, match="source probe interrupted"):
        tools.forget(request.tenant_id, erased.cid, **options)
    assert pipeline.engine.get_evidence(request.tenant_id, erased.cid) is None
    assert tools.user_model.entries[remove["id"]].status == "active"
    retried = tools.forget(request.tenant_id, erased.cid, **options)
    assert retried["retracted_profile_entries"] == [remove["id"]]
    assert tools.user_model.entries[keep["id"]].status == "active"
