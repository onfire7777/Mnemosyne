"""Focused acceptance for source-backed entities and changing commitments."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from mnemosyne.commitment_memory import commitment_display_status, resolve_commitment_time
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.memory_formation import project_direct_user_memory, preview_direct_user_memory
from mnemosyne.models import Evidence
from mnemosyne.sqlite_engine import SqliteEngine


@pytest.fixture(params=["local", "sqlite"])
def engine(request, tmp_path):
    store = LocalMemoryEngine() if request.param == "local" else SqliteEngine(tmp_path / "memory")
    yield store
    store.close()


def capture(engine, text, *, user="alice", hour=0, proposer=None, timezone="America/Los_Angeles"):
    evidence = Evidence(tenant_id="t", user_id=user, actor="user", source_type="chat", content=text,
                        created_at=datetime(2026, 11, 11, 1, tzinfo=UTC) + timedelta(hours=hour),
                        trust_tier=1, metadata={"timezone": timezone},
                        access_policy={"tenant": "t", "allow_principals": [user]})
    cid = engine.append_evidence(evidence)
    return cid, project_direct_user_memory(engine, "t", cid, semantic_proposer=proposer)


def rows(engine):
    return engine.export_tenant("t")["assertions"]


def test_linked_assets_keep_separate_exact_quotes_and_owner(engine):
    text = "My deployment server is Atlas. It runs Debian."
    cid, result = capture(engine, text)
    facts = rows(engine)
    assert {(r["subject"], r["predicate"], r["object"]) for r in facts} == {
        ("user", "deployment_server", "Atlas"), ("Atlas", "runs", "Debian")}
    for fact in facts:
        span = fact["calibration"]["source_spans"][0]
        assert text[span["start"]:span["end"]] == span["quote"]
        assert span["cid"] == cid
        assert fact["user_id"] == "alice"
        assert fact["calibration"]["epistemic_class"] == "direct_user"
    os_fact = next(row for row in facts if row["predicate"] == "runs")
    assert os_fact["calibration"]["source_quote"] == "It runs Debian."
    assert os_fact["calibration"]["antecedent_spans"][0]["quote"] == "My deployment server is Atlas."
    assert len(result["relation_ids"]) == 2
    _, other = capture(engine, "My deployment server is Atlas. It runs Fedora.", user="bob")
    assert all(row["status"] == "active" for row in rows(engine))
    assert len(other["assertion_ids"]) == 2


def test_named_project_members_are_additive_and_ambiguous_pronoun_is_not_resolved(engine):
    capture(engine, "I have two projects: Mnemosyne and BurnOS. It runs Debian.")
    facts = rows(engine)
    assert {(r["predicate"], r["object"]) for r in facts} == {
        ("count", "2 projects"), ("has_project", "Mnemosyne"), ("has_project", "BurnOS")}
    assert all(r["status"] == "active" for r in facts)


def test_reported_belief_is_not_promoted_to_world_fact(engine):
    capture(engine, "My coworker thinks Atlas runs Debian.")
    [fact] = rows(engine)
    assert fact["subject"] == "My coworker"
    assert fact["predicate"] == "believes"
    assert fact["calibration"]["epistemic_class"] == "reported_belief"
    assert not engine.export_tenant("t")["relations"]


def test_relative_date_uses_local_observation_date_without_invented_time(engine):
    cid, result = capture(engine, "I plan to meet Alex tomorrow.")
    [intention] = engine.list_intentions("t")
    assert intention.intention_id in result["intention_ids"]
    assert intention.trigger_type == "time_window"
    assert intention.action["event_time"]["date"] == "2026-11-11"
    assert intention.action["event_time"]["precision"] == "day"
    assert intention.due_at == datetime(2026, 11, 11, 8, tzinfo=UTC)
    assert intention.evidence_ids == [cid]
    assert intention.action["notifications"] is False
    assert next(r for r in rows(engine) if r["predicate"] == "plan_to")["status"] == "superseded"
    before = deepcopy(engine.export_tenant("t"))
    assert project_direct_user_memory(engine, "t", cid)["created_count"] == 0
    assert engine.export_tenant("t") == before


@pytest.mark.parametrize("wording,reason", [("next Friday", "weekday_reference_ambiguous"), ("Friday", "weekday_reference_ambiguous")])
def test_ambiguous_dates_are_retained_without_schedule(engine, wording, reason):
    _, result = capture(engine, f"I plan to meet Alex {wording}.")
    assert result["unresolved"][0]["reason"] == reason
    assert engine.list_intentions("t") == []
    pending = next(r for r in rows(engine) if r["predicate"] == "commitment_state")
    assert pending["calibration"]["event_time"]["candidate_dates"] == ["2026-11-13", "2026-11-20"]


def test_reschedule_and_completion_remove_pending_and_keep_each_source(engine):
    original, _ = capture(engine, "I plan to meet Alex tomorrow.")
    revised, _ = capture(engine, "I rescheduled my meeting with Alex to 2026-11-15.", hour=1)
    intentions = engine.list_intentions("t")
    assert len(intentions) == 2
    assert next(i for i in intentions if i.evidence_ids == [original]).status == "cancelled"
    assert next(i for i in intentions if i.evidence_ids == [revised]).status == "scheduled"
    final, result = capture(engine, "I completed my meeting with Alex.", hour=2)
    assert all(i.status == "cancelled" for i in engine.list_intentions("t"))
    active = [r for r in rows(engine) if r["status"] == "active"]
    assert len(active) == 1
    assert active[0]["calibration"]["commitment_state"] == "completed"
    assert active[0]["source_evidence_cids"] == [final]
    assert project_direct_user_memory(engine, "t", final)["created_count"] == 0
    assert result["assertion_ids"] == [active[0]["id"]]


def test_cancellation_does_not_guess_between_multiple_matching_plans(engine):
    capture(engine, "I plan to meet Alex tomorrow.")
    capture(engine, "I plan to meet Alex on 2026-11-17.", hour=1)
    _, result = capture(engine, "I cancelled my meeting with Alex.", hour=2)
    assert result["unresolved"][0]["reason"] == "ambiguous_commitment_target"
    assert all(i.status == "scheduled" for i in engine.list_intentions("t"))


def test_overdue_does_not_mean_completed_and_erasure_does_not_resurrect(engine):
    cid, _ = capture(engine, "I plan to meet Alex tomorrow.")
    [intention] = engine.list_intentions("t")
    assert commitment_display_status(intention, now=datetime(2026, 11, 20, tzinfo=UTC)) == "overdue"
    assert next(r for r in rows(engine) if r["predicate"] == "commitment_state")["calibration"]["commitment_state"] == "pending"
    engine.forget("t", cid)
    assert not engine.list_intentions("t")
    assert project_direct_user_memory(engine, "t", cid)["count"] == 0
    assert not [r for r in rows(engine) if r["status"] == "active"]


def test_interrupted_cancellation_is_completed_by_replay(engine, monkeypatch):
    capture(engine, "I plan to meet Alex tomorrow.")
    cancel = engine.cancel_intention
    def fail(*args, **kwargs):
        raise RuntimeError("interrupted cancellation")
    monkeypatch.setattr(engine, "cancel_intention", fail)
    with pytest.raises(RuntimeError, match="interrupted"):
        capture(engine, "I cancelled my meeting with Alex.", hour=1)
    cid = next(r["source_evidence_cids"][0] for r in rows(engine) if r["calibration"].get("commitment_state") == "cancelled")
    monkeypatch.setattr(engine, "cancel_intention", cancel)
    project_direct_user_memory(engine, "t", cid)
    assert all(i.status == "cancelled" for i in engine.list_intentions("t"))


def test_semantic_provider_literal_structure_is_checked_not_just_quote_presence(engine):
    def proposer(payload):
        span = payload["clauses"][0]
        return {"claims": [
            {"span": span, "subject": "API", "predicate": "authenticates", "object": "requests",
             "subject_quote": "Our API", "predicate_quote": "authenticates", "object_quote": "requests", "epistemic_class": "direct_user"},
            {"span": span, "subject": "API", "predicate": "leaks", "object": "secrets", "epistemic_class": "direct_user"},
            {"span": {**span, "quote": "Fake evidence"}, "subject": "API", "predicate": "stores", "object": "secrets", "epistemic_class": "direct_user"},
        ]}
    _, result = capture(engine, "Our API authenticates requests.", proposer=proposer)
    active = [r for r in rows(engine) if r["status"] == "active"]
    assert [(r["subject"], r["predicate"], r["object"]) for r in active] == [("API", "authenticates", "requests")]
    proposed = [r for r in rows(engine) if r["status"] == "quarantined"]
    assert len(proposed) == 1
    assert proposed[0]["calibration"]["epistemic_class"] == "inferred_proposal"
    assert result["rejected_proposals"] == [{"reason": "ungrounded_span"}]
    assert len(engine.export_tenant("t")["relations"]) == 1
    hits = engine.retrieve("API leaks secrets", "t", filt={"user_id": "alice", "principal": "alice"}).hits
    assert proposed[0]["id"] not in {h.id for h in hits}


def test_preview_has_versioned_intentions_without_side_effects(engine):
    cid, _ = capture(engine, "I plan to meet Alex tomorrow.")
    before = deepcopy(engine.export_tenant("t"))
    preview = preview_direct_user_memory(engine, "t", cid)
    assert preview["intentions"][0]["action"]["event_time"]["precision"] == "day"
    assert all(r["calibration"]["projection_version"] == 3 for r in preview["assertions"])
    assert preview == preview_direct_user_memory(engine, "t", cid)
    assert before == engine.export_tenant("t")


def test_temporal_parser_rejects_timezone_and_dst_ambiguity():
    observed = datetime(2026, 10, 31, 20, tzinfo=UTC)
    assert resolve_commitment_time("tomorrow", observed)["reason"] == "timezone_required"
    assert resolve_commitment_time("2026-11-01 at 1:30am", observed, "America/Los_Angeles")["reason"] == "daylight_saving_transition"
    assert resolve_commitment_time("2026-03-08 at 2:30am", observed, "America/Los_Angeles")["reason"] == "daylight_saving_transition"
    assert resolve_commitment_time("tomorrow at 3", observed, "America/Los_Angeles")["reason"] == "meridiem_required"


def test_date_specific_cancellation_and_from_to_reschedule(engine):
    capture(engine, "I plan to meet Alex tomorrow.")
    capture(engine, "I plan to meet Alex on 2026-11-17.", hour=1)
    _, result = capture(engine, "I rescheduled my meeting with Alex from 2026-11-17 to 2026-11-20.", hour=2)
    assert result["unresolved"] == []
    active = [item for item in engine.list_intentions("t") if item.status == "scheduled"]
    assert {item.action["event_time"]["date"] for item in active} == {"2026-11-11", "2026-11-20"}
    cid, result = capture(engine, "I cancelled my meeting with Alex on 2026-11-20.", hour=3)
    assert result["unresolved"] == []
    assert [item.action["event_time"]["date"] for item in engine.list_intentions("t") if item.status == "scheduled"] == ["2026-11-11"]
    preview = preview_direct_user_memory(engine, "t", cid)
    assert preview["assertions"][0]["calibration"]["commitment_state"] == "cancelled"
    assert len(preview["cancelled_intention_ids"]) == 1


def test_backfill_is_bounded_private_and_preserves_manual_corrections(engine):
    import importlib.util
    import json
    from pathlib import Path
    from types import SimpleNamespace
    from uuid import NAMESPACE_URL, uuid5
    from mnemosyne.models import Assertion

    path = Path(__file__).parents[1] / "integrations" / "codex" / "backfill.py"
    spec = importlib.util.spec_from_file_location("semantic_backfill_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = Evidence(tenant_id="t", user_id="alice", actor="user", source_type="chat", content="I live in Paris.", trust_tier=1)
    cid = engine.append_evidence(source)
    legacy_id = str(uuid5(NAMESPACE_URL, json.dumps(["direct-user-assertion", "t", "alice", "main", cid, "user", "residence", "Paris", {}], sort_keys=True)))
    engine.upsert_assertion(Assertion(tenant_id="t", user_id="alice", subject="user", predicate="residence", object="Paris",
                                    id=legacy_id, status="active", source_evidence_cids=[cid], trust_tier=1,
                                    calibration={"source_quote": source.content, "projection_kind": "direct_user", "projection_version": 2}))
    engine.append_evidence(Evidence(tenant_id="t", user_id="alice", actor="user", source_type="chat", content="My server is SecretImported.", trust_tier=1, metadata={"imported": True}))
    raw_before = engine.get_evidence("t", cid).to_dict()
    snapshot = deepcopy(engine.export_tenant("t"))
    dry = module.run_backfill(SimpleNamespace(engine=engine), "t", "alice", limit=1)
    assert dry["mode"] == "dry_run"
    assert dry["processed"] == 1
    assert "Paris" not in json.dumps(dry)
    assert "SecretImported" not in json.dumps(dry)
    assert engine.export_tenant("t") == snapshot
    apply = module.run_backfill(SimpleNamespace(engine=engine), "t", "alice", limit=1, apply=True)
    assert apply["sources"][0]["retired_assertion_ids"] == [legacy_id]
    fact = next(r for r in rows(engine) if r["id"] == legacy_id)
    assert fact["status"] == "active"
    assert fact["calibration"]["projection_version"] == 3
    assert engine.get_evidence("t", cid).to_dict() == raw_before
    exhausted = module.run_backfill(SimpleNamespace(engine=engine), "t", "alice", cursor=apply["next_cursor"])
    assert exhausted["processed"] == 0


def test_proposer_skips_operational_chatter_and_has_a_whole_clause_budget(engine):
    import json
    calls = []
    def propose(payload):
        calls.append(payload)
        return {"claims": []}
    capture(engine, "Please fully implement the memory changes. " + "Run the complete implementation carefully. " * 1000, proposer=propose)
    assert calls == []
    capture(engine, " ".join(f"Our API authenticates request{i}." for i in range(100)), proposer=propose)
    assert len(calls) == 1
    assert len(calls[0]["clauses"]) <= 16
    assert len(json.dumps(calls[0], ensure_ascii=False).encode()) <= 16384
    assert all(span["quote"].endswith(".") for span in calls[0]["clauses"])


def test_terse_future_commitment_preserves_day_precision(engine):
    capture(engine, "Meet Alex tomorrow.")
    [intention] = engine.list_intentions("t")
    assert intention.action["event_time"]["date"] == "2026-11-11"
    assert intention.action["event_time"]["precision"] == "day"
