"""Focused regression coverage for useful, authorized foreground memory."""

from mnemosyne.answering import AnswerReadContext
from mnemosyne.context_composer import compose_context
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.knowledge_maintenance import KnowledgeMaintenanceWorker, read_knowledge_context
from mnemosyne.mcp_tools import MemoryTools
from mnemosyne.models import Assertion, Evidence
from mnemosyne.mcp_server import MnemosyneMcpServer
from mnemosyne.security import SessionIdentity, SessionTokenVerifier


def _fact(engine, text, predicate, value, *, trust=1, user="u"):
    cid = engine.append_evidence(Evidence("t", user, "user", "chat", text, trust_tier=trust,
        access_policy={"tenant": "t", "allow_principals": [user]}))
    row = Assertion("t", "Atlas", predicate, value, user_id=user, status="active", trust_tier=trust,
        source_evidence_cids=[cid], calibration={"epistemic_class": "observed_tool" if trust > 1 else "direct_user",
            "projection_kind": "project_observation" if trust > 1 else "direct_user",
            "source_spans": [{"cid": cid, "start": 0, "end": len(text), "quote": text}]})
    engine.upsert_assertion(row)
    return row


def test_operator_provenance_does_not_narrow_foreground_source_read_policy():
    engine = LocalMemoryEngine()
    engine.policy.max_trust_tier = 3
    engine.policy.learning_modes["exploration"] = "off"
    engine.policy.token_budget = 16000
    _fact(engine, "Atlas uses SQLite.", "uses", "SQLite", trust=3)
    _fact(engine, "Atlas stores durable records.", "stores", "durable records", trust=3)
    context = AnswerReadContext("t", user_id="u", role="agent", max_trust_tier=3)
    assert KnowledgeMaintenanceWorker(engine, context).run_once()["created"] == 1
    tools = MemoryTools(engine)
    packet = tools.prepare_context("t", "u", "s", "Atlas durable storage", source_trust_tier=0)
    assert len(packet["knowledge_pages"]) == 1
    assert not tools.prepare_context("t", "other", "s2", "Atlas durable storage", source_trust_tier=0).get("knowledge_pages")
    engine.policy.max_trust_tier = 0
    assert not tools.prepare_context("t", "u", "s", "Atlas durable storage", source_trust_tier=0).get("knowledge_pages")


def test_signed_reflect_reads_eligible_sources_without_laundering_authority(tmp_path):
    from tests.test_reflect import FixtureProvider, call_reflect, seed
    secret = "test-memory-read-provenance"
    server = MnemosyneMcpServer(store_path=tmp_path / "memory.json", session_secret=secret,
        require_session=True, object_store=str(tmp_path / "objects"))
    try:
        seed(server.engine, "Project Zephyr launches Friday.", trust=3)
        server.engine.policy.max_trust_tier = 3
        server.tools = MemoryTools(server.engine, grounded_provider_factory=FixtureProvider)
        token = SessionTokenVerifier(secret).sign(SessionIdentity(
            "tenant-a", "user-a", "reader", 0, session_id="s"))
        args = {"session_token": token, "question": "When does Project Zephyr launch?"}
        result = call_reflect(server, args)
        assert result["structuredContent"]["answer"] == "Friday"
        restricted = call_reflect(server, {**args, "max_trust_tier": 0})
        assert restricted["structuredContent"]["abstained"] is True
    finally:
        server.close()


def test_saved_model_keeps_legacy_read_ceiling_without_disappearing():
    engine = LocalMemoryEngine()
    tools = MemoryTools(engine)
    saved = tools.mental_model_create("t", "u", "Atlas", "What does Atlas use?",
                                      source_trust_tier=0, max_trust_tier=0)
    loaded = tools.mental_model_get("t", "u", saved["model_id"], source_trust_tier=0)
    assert loaded["model_id"] == saved["model_id"]
    assert engine.get_mental_model_record("t", saved["model_id"])["scope"]["max_trust_tier"] == 0
    assert saved["model_id"] in {row["model_id"] for row in tools.mental_model_list("t", "u", source_trust_tier=0)}


def test_repeated_current_questions_do_not_crowd_grounded_answers():
    packet = {"hits": [
        {"id": "echo1", "kind": "evidence", "text": "What are the biggest remaining issues with Atlas memory?"},
        {"id": "echo2", "kind": "evidence", "text": "What are the issues with Atlas memory now?"},
        {"id": "fact", "kind": "assertion", "text": "Atlas memory requires explicit source provenance."},
    ]}
    result = compose_context("What are the biggest remaining issues with Atlas memory now?", packet, 1600)
    assert [row["id"] for row in result["packet"]["hits"]] == ["fact"]


def test_historical_questions_and_contradictory_facts_remain_distinct():
    packet = {"hits": [
        {"id": "request", "kind": "evidence", "text": "What are the Atlas storage requirements?"},
        {"id": "positive", "kind": "assertion", "text": "Atlas requires replication."},
        {"id": "negative", "kind": "assertion", "text": "Atlas does not require replication."},
    ]}
    result = compose_context("What did I ask about Atlas storage requirements?", packet, 2400)
    assert {row["id"] for row in result["packet"]["hits"]} == {"request", "positive", "negative"}


def test_native_grounded_utility_survives_final_context_composition():
    packet = {"hits": [
        {"id": "low", "kind": "assertion", "text": "Atlas uses SQLite.", "learning_utility": .8},
        {"id": "high", "kind": "assertion", "text": "Atlas requires backups.", "learning_utility": 1.2},
    ]}
    result = compose_context("Atlas", packet, 1600)
    assert [row["id"] for row in result["packet"]["hits"]] == ["high", "low"]


def test_durable_decision_and_commitment_survive_recent_fact_flood():
    engine = LocalMemoryEngine()
    _fact(engine, "Atlas chose SQLite to support offline work.", "chose", "SQLite to support offline work")
    _fact(engine, "Atlas plans a restore drill on Friday.", "plans", "a restore drill on Friday")
    for n in range(30):
        _fact(engine, f"Atlas component {n} has a recent observation.", f"component_{n}", "recent observation")
    context = AnswerReadContext("t", user_id="u", role="agent", max_trust_tier=3)
    assert KnowledgeMaintenanceWorker(engine, context, max_claims=2).run_once()["created"] == 1
    [page] = read_knowledge_context(engine, context, "Atlas")
    assert {claim["section"] for claim in page["claims"]} == {"Decisions", "Pending commitments"}
    assert "offline" in page["text"] and "Friday" in page["text"]


def test_actual_question_demand_changes_page_selection_without_becoming_fact():
    engine = LocalMemoryEngine()
    _fact(engine, "Atlas backup retention is seven days.", "backup_retention", "seven days")
    for n in range(12):
        _fact(engine, f"Atlas component {n} has a recent observation.", f"component_{n}", "recent observation")
    engine.append_evidence(Evidence("t", "u", "user", "chat", "What is Atlas backup retention?", trust_tier=1))
    context = AnswerReadContext("t", user_id="u", role="agent", max_trust_tier=3)
    assert KnowledgeMaintenanceWorker(engine, context, max_claims=2).run_once()["created"] == 1
    [page] = read_knowledge_context(engine, context, "Atlas backup retention")
    assert any(claim["predicate"] == "backup_retention" for claim in page["claims"])
    assert "What is" not in page["text"]
