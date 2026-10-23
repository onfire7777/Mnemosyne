"""Atomic document manifests and current-read custody for Local storage."""

import copy
from datetime import UTC, datetime, timedelta

import pytest

from mnemosyne.document_storage import DocumentConflict
from mnemosyne.engine import Intention, LocalMemoryEngine, WorkingMemoryItem
from mnemosyne.models import Assertion, Evidence, Hit, Preference, Relation
from mnemosyne.retrieval import filter_derived_adapter_hits


NOW = datetime(2026, 10, 22, tzinfo=UTC)
WORDS = "The launch code is amber."


def evidence(segment="doc/first", text=WORDS, owner="owner"):
    return Evidence(tenant_id="tenant", user_id=owner, actor="user", source_type="document",
                    content=text, document_segment_id=segment)


def manifest(entries, *, current=None, document="doc", owner="owner", branch="main"):
    if current is None:
        row = {"schema_version": 1, "tenant_id": "tenant", "owner_id": owner,
               "document_id": document, "branch": branch, "revision": 1,
               "created_at": NOW.isoformat(), "updated_at": NOW.isoformat(),
               "deleted": False, "settings": {}, "segments": entries,
               "retired_segments": [], "receipts": []}
    else:
        row = copy.deepcopy(current)
        row["revision"] += 1
        row["updated_at"] = (NOW + timedelta(seconds=row["revision"])).isoformat()
        kept = {entry["cid"] for entry in entries}
        row["retired_segments"] += [entry for entry in current["segments"] if entry["cid"] not in kept]
        row["segments"] = entries
    row["receipts"].append({"operation_id": f"op/{row['revision']}", "revision": row["revision"],
                            "action": "replace" if current else "create", "request_hash": "a" * 64})
    return row


def create(engine, *, branch="main", document="doc", segment="doc/first", owner="owner"):
    with engine.source_transaction("tenant", branch):
        cid = engine.append_evidence(evidence(segment, owner=owner), branch)
        row = engine.save_document_record("tenant", owner, document,
            manifest([{"segment_id": segment, "cid": cid}], document=document, owner=owner, branch=branch), branch)
    return cid, row


def retire(engine, current, *, branch="main"):
    with engine.source_transaction("tenant", branch):
        return engine.save_document_record("tenant", "owner", "doc", manifest([], current=current), branch,
                                           expected_revision=current["revision"])


def test_manifest_replacement_preserves_history_and_survives_reopen(tmp_path):
    path = tmp_path / "memory.json"
    engine = LocalMemoryEngine(path)
    cid, original = create(engine)
    saved = retire(engine, original)
    assert saved["revision"] == 2 and saved["retired_segments"] == original["segments"]
    historical = engine.get_evidence("tenant", cid)
    assert historical.content == WORDS and historical.retired_at is not None and not historical.erased
    engine.close()
    reopened = LocalMemoryEngine(path)
    assert reopened.get_document_record("tenant", "owner", "doc") == saved
    assert reopened.get_evidence("tenant", cid).retired_at == historical.retired_at
    assert reopened.export_tenant("tenant")["documents"] == [saved]
    assert reopened.export_all()["documents"] == [saved]
    assert "documents" not in reopened.export_tenant_filtered("tenant", {"user_id": "owner"})
    reopened.close()


def test_manifest_write_requires_transaction_and_conflict_poisoning_rolls_back():
    engine = LocalMemoryEngine()
    cid, original = create(engine)
    changed = manifest([], current=original)
    with pytest.raises(RuntimeError, match="source_transaction"):
        engine.save_document_record("tenant", "owner", "doc", changed, expected_revision=1)
    with pytest.raises(RuntimeError, match="aborted"):
        with engine.source_transaction("tenant"):
            engine.save_document_record("tenant", "owner", "doc", changed, expected_revision=1)
            with pytest.raises(DocumentConflict):
                engine.save_document_record("tenant", "owner", "doc", changed, expected_revision=1)
    assert engine.get_document_record("tenant", "owner", "doc") == original
    assert engine.get_evidence("tenant", cid).retired_at is None


@pytest.mark.parametrize("failure", ["foreign_owner", "reused_segment", "retired_source"])
def test_document_custody_rejects_invalid_sources(failure):
    engine = LocalMemoryEngine()
    cid, original = create(engine)
    if failure == "retired_source":
        retire(engine, original)
    owner = "other" if failure == "foreign_owner" else "owner"
    record = manifest([{"segment_id": "doc/first", "cid": cid}], document="other", owner=owner)
    with pytest.raises(DocumentConflict):
        with engine.source_transaction("tenant"):
            engine.save_document_record("tenant", owner, "other", record)
    assert engine.get_document_record("tenant", owner, "other") is None


def test_branch_copy_retirement_isolation_and_merge_preflight():
    engine = LocalMemoryEngine()
    cid, original = create(engine)
    engine.branch("draft", tenant_id="tenant", kind="canary")
    draft = engine.get_document_record("tenant", "owner", "doc", "draft")
    assert draft == {**original, "branch": "draft"}
    retire(engine, draft, branch="draft")
    assert engine.get_evidence("tenant", cid).retired_at is None
    assert engine.get_evidence("tenant", cid, "draft").retired_at is not None
    before = engine.export_all()
    with pytest.raises(DocumentConflict, match="divergent"):
        engine.merge("draft", tenant_id="tenant")
    assert engine.export_all() == before
    assert engine.get_document_record("tenant", "owner", "doc") == original
    engine.discard("draft", tenant_id="tenant")
    assert engine.get_document_record("tenant", "owner", "doc", "draft") is None


def test_document_merge_to_absent_target_and_identical_merge():
    engine = LocalMemoryEngine()
    engine.branch("draft", tenant_id="tenant")
    cid, original = create(engine, branch="draft")
    engine.merge("draft", tenant_id="tenant")
    assert engine.get_document_record("tenant", "owner", "doc") == {**original, "branch": "main"}
    assert engine.get_evidence("tenant", cid) is not None
    engine.merge("draft", tenant_id="tenant")


def test_forget_scrubs_retired_manifest_refs_and_rollback_restores_them():
    engine = LocalMemoryEngine()
    cid, original = create(engine)
    saved = retire(engine, original)
    with pytest.raises(ValueError, match="abort"):
        with engine.source_transaction("tenant"):
            engine.forget("tenant", cid)
            raise ValueError("abort")
    assert engine.get_document_record("tenant", "owner", "doc") == saved
    engine.forget("tenant", cid)
    scrubbed = engine.get_document_record("tenant", "owner", "doc")
    assert scrubbed["retired_segments"] == []
    assert all(receipt["request_hash"] is None for receipt in scrubbed["receipts"])


def test_manifest_and_retirement_rollback_on_persistence_failure(tmp_path, monkeypatch):
    engine = LocalMemoryEngine(tmp_path / "memory.json")
    cid, original = create(engine)
    before = engine.store_path.read_bytes()
    real_persist = engine._persist

    def fail_commit():
        if engine._source_transaction_state is None:
            raise OSError("publication failed")
        return real_persist()

    monkeypatch.setattr(engine, "_persist", fail_commit)
    with pytest.raises(OSError, match="publication failed"):
        retire(engine, original)
    assert engine.get_document_record("tenant", "owner", "doc") == original
    assert engine.get_evidence("tenant", cid).retired_at is None
    assert engine.store_path.read_bytes() == before
    engine.close()


@pytest.mark.parametrize("identity", [{}, {"user_id": "other"}, {"source_identity": "owner"},
                                      {"user_id": "other", "role": "operator"}])
def test_segment_reads_require_owner_on_native_export_raw_and_adapter_paths(identity):
    engine = LocalMemoryEngine()
    cid, _ = create(engine)
    filt = {"tenant_id": "tenant", **identity}
    assert engine.get_evidence("tenant", cid) is not None  # administrative storage read
    assert engine.get_evidence_for_read("tenant", cid, access_context=filt) is None
    assert engine.lexical_search("launch code amber", 20, filt) == []
    assert engine.vector_search("launch code amber", 20, filt) == []
    assert engine.export_tenant_filtered("tenant", filt)["evidence"] == []
    forged = Hit(id=cid, kind="evidence", tenant_id="tenant", branch="main", text=WORDS,
                 score=1, channel="lexical", provenance=[cid])
    assert filter_derived_adapter_hits(engine, [forged], filt) == []


def test_retirement_withholds_warmed_reads_and_jointly_dependent_projections():
    engine = LocalMemoryEngine()
    cid, original = create(engine)
    independent = engine.append_evidence(evidence(None, "An independent launch witness."))
    summary = engine.append_evidence(Evidence(tenant_id="tenant", user_id="owner", actor="system",
        source_type="consolidation-summary", content=WORDS,
        metadata={"summary": {"source_evidence_cids": [cid, independent], "status": "active"}}))
    fact = engine.upsert_assertion(Assertion(tenant_id="tenant", subject="launch code", predicate="is",
        object="amber", source_evidence_cids=[cid, independent], status="active"))
    preference = engine.add_preference(Preference(tenant_id="tenant", user_id="owner", category="workflow",
        statement=WORDS, source_evidence_cids=[summary]))
    relation = engine.add_relation(Relation(tenant_id="tenant", source="launch", predicate="code", target="amber",
        source_evidence_cids=[cid, independent]))
    relation_row = engine.relations[engine._branch_key("tenant", "main", relation)]
    filt = {"tenant_id": "tenant", "user_id": "owner", "max_trust_tier": 5}
    assert cid in {hit.id for hit in engine.lexical_search("launch code amber", 20, filt)}
    assert engine._relation_hit_security(relation_row, branch="main", include_quarantined=False,
                                         max_trust=5, max_sensitivity=3, access_context=filt) is not None
    retire(engine, original)
    hidden = {cid, summary, fact, preference}
    assert engine.get_evidence_for_read("tenant", summary, access_context=filt) is None
    assert not hidden.intersection(hit.id for hit in engine.lexical_search("launch code amber", 20, filt))
    assert not hidden.intersection(hit.id for hit in engine.vector_search("launch code amber", 20, filt))
    assert engine._relation_hit_security(relation_row, branch="main", include_quarantined=False,
                                         max_trust=5, max_sensitivity=3, access_context=filt) is None
    assert engine.assertions[engine._branch_key("tenant", "main", fact)].source_evidence_cids == [cid, independent]
    assert engine.get_evidence("tenant", summary).content == WORDS
    assert engine.get_evidence_for_read("tenant", independent, access_context=filt) is not None


def test_append_cannot_supply_retirement_marker():
    engine = LocalMemoryEngine()
    row = evidence()
    row.retired_at = NOW
    with pytest.raises(ValueError, match="retired_at"):
        engine.append_evidence(row)


def test_retirement_invalidates_models_and_hides_working_and_intentions_without_deleting():
    engine = LocalMemoryEngine()
    source = evidence()
    source.session_id = "session"
    with engine.source_transaction("tenant"):
        cid = engine.append_evidence(source)
        original = engine.save_document_record("tenant", "owner", "doc",
            manifest([{"segment_id": source.document_segment_id, "cid": cid}]))
    engine.mental_models[("tenant", "main", "model")] = {
        "version": 1, "answer": {"text": WORDS}, "source_evidence_cids": [cid], "status": "ready",
    }
    working = WorkingMemoryItem(item_id="work", tenant_id="tenant", user_id="owner", session_id="session",
        agent_id="agent", kind="active_goal", task_id="task", content=WORDS,
        created_at=NOW, expires_at=NOW + timedelta(minutes=5), evidence_ids=[cid])
    engine.put_working(working)
    intention = Intention(intention_id="reminder", tenant_id="tenant", user_id="owner", agent_id="agent",
        trigger_type="exact_time", trigger_expression={"at": (NOW + timedelta(minutes=1)).isoformat()},
        action={"type": "remind", "message": WORDS}, due_at=NOW + timedelta(minutes=1),
        evidence_ids=[cid], session_id="session")
    engine.schedule_intention(intention)
    assert engine.get_working("tenant", "session", "work", as_of=NOW) is not None
    assert len(engine.list_intentions("tenant")) == 1
    retire(engine, original)
    model = engine.mental_models[("tenant", "main", "model")]
    assert model["status"] == "stale" and model["answer"] is None
    assert engine.get_working("tenant", "session", "work", as_of=NOW) is None
    assert engine.list_working("tenant", "session", as_of=NOW) == []
    assert engine.list_intentions("tenant") == []
    assert len(engine.working_memory) == len(engine.intentions) == 1


@pytest.mark.parametrize("branch_filter", [{"branch": "main"}, {}])
def test_live_copy_in_another_branch_cannot_authorize_retired_source_export(branch_filter):
    engine = LocalMemoryEngine()
    cid, original = create(engine)
    fact = engine.upsert_assertion(Assertion(tenant_id="tenant", subject="launch code", predicate="is",
        object="amber", source_evidence_cids=[cid], status="active"))
    preference = engine.add_preference(Preference(tenant_id="tenant", user_id="owner", category="workflow",
        statement=WORDS, source_evidence_cids=[cid]))
    engine.branch("draft", tenant_id="tenant")
    retire(engine, original)
    exported = engine.export_tenant_filtered("tenant", {**branch_filter, "user_id": "owner"})
    assert {row["branch"] for row in exported["evidence"]} == (set() if branch_filter else {"draft"})
    assert not any(row["id"] == fact and row["branch"] == "main" for row in exported["assertions"])
    assert preference not in {row["id"] for row in exported["preferences"]}
    if not branch_filter:
        assert any(row["id"] == fact and row["branch"] == "draft" for row in exported["assertions"])
    assert engine.get_evidence_for_read("tenant", cid, "draft", access_context={"user_id": "owner"}) is not None
