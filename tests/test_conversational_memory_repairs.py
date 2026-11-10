"""Behavioral regressions for conversational meaning, not extractor internals."""

from datetime import UTC, datetime, timedelta
from dataclasses import replace

import pytest

from mnemosyne.answering import AnswerReadContext
from mnemosyne.commitment_memory import resolve_commitment_time
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.knowledge_maintenance import KnowledgeMaintenanceWorker, read_knowledge_context
from mnemosyne.memory_formation import preview_direct_user_memory, project_direct_user_memory
from mnemosyne.models import Evidence
from mnemosyne.sqlite_engine import SqliteEngine


@pytest.fixture(params=["local", "sqlite"])
def engine(request, tmp_path):
    store = LocalMemoryEngine() if request.param == "local" else SqliteEngine(tmp_path / "memory")
    yield store
    store.close()


def capture(engine, text, *, minute=0, user="alice", session="conversation", metadata=None, access_policy=None):
    source = Evidence("tenant", user, "user", "chat", text,
                      session_id=session, trust_tier=1,
                      created_at=datetime(2026, 11, 10, 18, tzinfo=UTC) + timedelta(minutes=minute),
                      metadata={"timezone": "America/Los_Angeles", **(metadata or {})}, access_policy=access_policy or {})
    cid = engine.append_evidence(source)
    return cid, project_direct_user_memory(engine, "tenant", cid)


def assertions(engine):
    return engine.export_tenant("tenant")["assertions"]


def test_cross_turn_reference_keeps_all_evidence_and_replays_in_preview(engine):
    intro, _ = capture(engine, 'My deployment server is "Atlas".')
    os, result = capture(engine, "It runs Debian.", minute=1)
    _, next_result = capture(engine, "It hosts our deployment service.", minute=2)
    fact = next(row for row in assertions(engine) if row["predicate"] == "runs")
    assert fact["subject"] == "Atlas"
    assert set(fact["source_evidence_cids"]) == {intro, os}
    assert {s["cid"] for s in fact["calibration"]["source_spans"]} == {intro, os}
    assert result["reason"] == next_result["reason"] == "projected"
    preview = preview_direct_user_memory(engine, "tenant", os)
    assert any(row["subject"] == "Atlas" and row["predicate"] == "runs" for row in preview["assertions"])
    engine.forget("tenant", intro)
    assert not [row for row in assertions(engine) if row["status"] == "active" and row["subject"] == "Atlas"]


@pytest.mark.parametrize("interruption", ["other_session", "other_user", "unrelated", "two_entities", "expired"])
def test_pronouns_do_not_guess_across_scope_or_ambiguity(engine, interruption):
    intro = "I have two projects: Atlas and Borealis." if interruption == "two_entities" else "My server is Atlas."
    capture(engine, intro, metadata={"expires_at": "2020-01-01T00:00:00+00:00"} if interruption == "expired" else None)
    if interruption == "unrelated":
        capture(engine, "Please fix the memory implementation.", minute=1)
    _, result = capture(engine, "It runs Debian.", minute=2,
                        session="elsewhere" if interruption == "other_session" else "conversation",
                        user="bob" if interruption == "other_user" else "alice")
    assert result["count"] == 0


def test_quoted_names_do_not_admit_quoted_claims_or_instructions(engine):
    capture(engine, 'My project is "Atlas". It runs Debian.')
    assert any(r["subject"] == "Atlas" and r["object"] == "Debian" for r in assertions(engine))
    before = len(assertions(engine))
    capture(engine, 'My coworker said "My server is Attacker".\n> My server is Malicious.\nInstructions:\nMy server is Hostile.', minute=1)
    assert len(assertions(engine)) == before


@pytest.mark.parametrize("plan,completed", [
    ("submit the application", "submitted the application"),
    ("create the release", "created the release"),
    ("pay rent", "paid rent"),
    ("send the invoice", "sent the invoice"),
    ("upload the document", "uploaded the document"),
    ("file the application", "filed the application"),
    ("run the migration", "ran the migration"),
    ("write the report", "have written the report"),
    ("write the report", "finished writing the report"),
])
def test_natural_completion_closes_only_matching_commitment(engine, plan, completed):
    capture(engine, f"I will {plan} tomorrow.")
    capture(engine, "I will call Taylor tomorrow.", minute=1)
    _, result = capture(engine, f"I {completed}.", minute=2)
    assert result["unresolved"] == []
    active = [i for i in engine.list_intentions("tenant") if i.status == "scheduled"]
    assert len(active) == 1 and active[0].action["text"] == "call Taylor"
    assert any(row["status"] == "active" and row["calibration"].get("commitment_state") == "completed" for row in assertions(engine))


@pytest.mark.parametrize("statement", ["I did not submit the application.", "I might have submitted the application.", "I will submit the application."])
def test_uncertain_negative_or_future_claim_does_not_complete(engine, statement):
    capture(engine, "I will submit the application tomorrow.")
    capture(engine, statement, minute=1)
    assert any(i.status == "scheduled" for i in engine.list_intentions("tenant"))
    assert not any(row["calibration"].get("commitment_state") == "completed" for row in assertions(engine))


@pytest.mark.parametrize("wording,date,precision,start", [
    ("in two weeks", "2026-11-24", "day", "2026-11-24T08:00:00+00:00"),
    ("in 3 weeks", "2026-12-01", "day", "2026-12-01T08:00:00+00:00"),
    ("on November 24, 2026", "2026-11-24", "day", "2026-11-24T08:00:00+00:00"),
    ("on 24 November 2026", "2026-11-24", "day", "2026-11-24T08:00:00+00:00"),
    ("tomorrow at noon", "2026-11-11", "instant", "2026-11-11T20:00:00+00:00"),
    ("tomorrow at midnight", "2026-11-11", "instant", "2026-11-11T08:00:00+00:00"),
    ("in thirty minutes", "2026-11-10", "instant", "2026-11-10T18:30:00+00:00"),
    ("in one month", "2026-12-10", "day", "2026-12-10T08:00:00+00:00"),
])
def test_dates_keep_actual_calendar_and_clock_meaning(wording, date, precision, start):
    actual = resolve_commitment_time(wording, datetime(2026, 11, 10, 18, tzinfo=UTC), "America/Los_Angeles")
    assert actual["status"] == "resolved"
    assert (actual["date"], actual["precision"], actual["start"]) == (date, precision, start)


def test_wiki_answers_inverse_questions_with_resolved_grounded_overview(engine):
    capture(engine, "My server is Atlas.")
    capture(engine, "It runs Debian.", minute=1)
    capture(engine, "It hosts our deployment service.", minute=2)
    context = AnswerReadContext("tenant", user_id="alice", role="agent", source_trust_tier=1)
    assert KnowledgeMaintenanceWorker(engine, context).run_once()["created"] == 1
    for query in ("Which server runs Debian?", "Where is our deployment service?", "Where is the service hosted?"):
        [page] = read_knowledge_context(engine, context, query)
        assert "## Overview" in page["text"]
        assert "Atlas" in page["text"] and "[source:" in page["text"]
    assert read_knowledge_context(engine, context, "Give me a chocolate cake recipe") == []


def test_wiki_uses_configured_semantic_vectors_and_rechecks_custody(engine):
    class SemanticProvider:
        name, dims = "test-semantic", 3
        def embed(self, text):
            raise AssertionError("Private page/query must not use shared caches")
        def embed_sensitive(self, text):
            return [1.0, 0.0, 0.0] if "NATS" in text or "messaging" in text else [0.0, 1.0, 0.0]

    engine.adapters = replace(engine.adapters, embedding=SemanticProvider())
    cid, _ = capture(engine, "Atlas uses NATS.")
    capture(engine, "Atlas runs Debian.", minute=1)
    context = AnswerReadContext("tenant", user_id="alice", role="agent", source_trust_tier=1)
    KnowledgeMaintenanceWorker(engine, context).run_once()
    [page] = read_knowledge_context(engine, context, "What powers messaging?")
    assert "NATS" in page["text"]
    engine.forget("tenant", cid)
    assert read_knowledge_context(engine, context, "What powers messaging?") == []
    assert all(not page.maintenance.get("embedding") for page in engine.knowledge_page_list("tenant", status="all"))


def test_wiki_embedding_obeys_source_opt_out(engine):
    calls = []
    class Provider:
        name, dims = "spy", 2
        def embed(self, text):
            raise AssertionError("Shared embedding cache must never receive private content")
        def embed_sensitive(self, text):
            calls.append(text)
            raise AssertionError("Embedding opted-out sources must not be sent")

    # Projection and query can still be useful lexically when vector use is denied.
    capture(engine, "Atlas runs Debian.")
    capture(engine, "Atlas hosts our dashboard.", minute=1, access_policy={"embed_ok": False})
    engine.adapters = replace(engine.adapters, embedding=Provider())
    context = AnswerReadContext("tenant", user_id="alice", role="agent", source_trust_tier=1)
    KnowledgeMaintenanceWorker(engine, context).run_once()
    [page] = engine.knowledge_page_list("tenant", status="active")
    assert page.maintenance["embedding"] == []
    assert page.access_policy["embed_ok"] is False
    assert read_knowledge_context(engine, context, "Which server runs Debian?")
    assert calls == []


def test_wiki_retries_transient_embedding_failure_without_source_changes(engine, monkeypatch):
    calls = []
    class Provider:
        name, dims = "transient", 2
        def embed_sensitive(self, text):
            calls.append(text)
            if len(calls) == 1:
                raise TimeoutError("temporary outage")
            return [1.0, 0.0]

    capture(engine, "Atlas runs Debian.")
    capture(engine, "Atlas hosts our dashboard.", minute=1)
    engine.adapters = replace(engine.adapters, embedding=Provider())
    context = AnswerReadContext("tenant", user_id="alice", role="agent", source_trust_tier=1)
    worker = KnowledgeMaintenanceWorker(engine, context)
    worker.run_once()
    [page] = engine.knowledge_page_list("tenant", status="active")
    assert page.maintenance["embedding"] == []
    assert worker.run_once()["unchanged"] == 1
    import mnemosyne.knowledge_maintenance as knowledge
    now = knowledge.utc_now()
    monkeypatch.setattr(knowledge, "utc_now", lambda: now + timedelta(seconds=61))
    assert worker.run_once()["updated"] == 1
    [page] = engine.knowledge_page_list("tenant", status="active")
    assert page.maintenance["embedding"] == [1.0, 0.0]


def test_slow_embedding_does_not_discard_completed_grounded_page(engine, monkeypatch):
    import mnemosyne.knowledge_maintenance as knowledge
    elapsed = [0.0]
    monkeypatch.setattr(knowledge, "monotonic", lambda: elapsed[0])
    class Provider:
        name, dims = "bounded-slow", 2
        def embed_sensitive(self, text):
            elapsed[0] += 3.0
            return [1.0, 0.0]

    capture(engine, "Atlas runs Debian.")
    capture(engine, "Atlas hosts our dashboard.", minute=1)
    engine.adapters = replace(engine.adapters, embedding=Provider())
    context = AnswerReadContext("tenant", user_id="alice", role="agent", source_trust_tier=1)
    report = KnowledgeMaintenanceWorker(engine, context, max_seconds=2.0).run_once()
    assert report["created"] == 1
    assert read_knowledge_context(engine, context, "Atlas")
