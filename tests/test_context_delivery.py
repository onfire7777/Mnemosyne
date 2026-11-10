"""Focused host delivery, budget and authenticated scope acceptance."""

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace

import pytest

from mnemosyne.context_composer import compose_context, token_bound
from mnemosyne.engine import Intention, LocalMemoryEngine
from mnemosyne.hosts.codex import CodexAdapter
from mnemosyne.mcp_tools import MemoryTools
from mnemosyne.models import Evidence
from mnemosyne.security import SessionIdentity


def test_hundred_large_profile_claims_share_total_budget_with_host_envelope():
    packet = {"receipt_id": "receipt", "user_model": {"authoritative": [
        {"id": str(i), "kind": "hard_instruction", "statement": "Preserve the full claim: " + "scope " * 1000,
         "source_evidence_cids": ["source-" + str(i)]} for i in range(100)]}}
    envelope = {"memory_use_reporting": {"command": ["python", "/local/host/report.py"],
                "session_id": "session", "turn_id": "turn"}, "correlation_id": "correlation"}
    result = compose_context("scope", packet, 2048, envelope=envelope)
    assert token_bound(result["text"]) <= 2048
    assert result["used_tokens_upper_bound"] == len(result["text"].encode())
    assert result["packet"]["memory_use_reporting"] == envelope["memory_use_reporting"]
    assert result["required_overflow"] == 100
    assert result["omitted"] == 100


def test_irrelevant_profile_is_omitted_but_hard_instruction_is_retained():
    result = compose_context("debug PostgreSQL connection", {"user_model": {"authoritative": [
        {"id": "food", "kind": "preference", "statement": "I prefer strawberry ice cream."},
        {"id": "hard", "kind": "hard_instruction", "statement": "Preserve original source provenance."},
    ]}}, 2048)
    assert [row["id"] for row in result["packet"]["user_model"]] == ["hard"]


@pytest.mark.parametrize("budget", [100, 350, 2048])
def test_negation_and_qualifiers_are_never_cut_to_fit(budget):
    claim = "The Paris deployment " + "requires review " * 20 + "and must not run in Berlin until Friday."
    result = compose_context("Paris deployment", {"hits": [
        {"id": "claim", "kind": "assertion", "text": claim, "provenance": ["source"]},
    ]}, budget)
    assert token_bound(result["text"]) <= budget
    delivered = result["packet"].get("hits", [])
    assert not delivered or delivered[0]["text"] == claim
    assert claim in result["text"] or "The Paris deployment" not in result["text"]


def _identity(session="session"):
    return SessionIdentity("t", "u", "agent", 1, agent_id="codex", session_id=session)


def test_authenticated_facade_delivers_working_and_prospective_sources_and_honors_erasure():
    engine = LocalMemoryEngine()
    engine.policy.token_budget = 16000
    tools = MemoryTools(engine)
    now = datetime.now(UTC)
    source = engine.append_evidence(Evidence(tenant_id="t", user_id="u", actor="user", source_type="chat",
        content="The deployment needs a smoke check.", session_id="session", trust_tier=1,
        access_policy={"tenant": "t", "allow_principals": ["u"]}))
    tools.working_seed("t", "session", "u", "codex", "deployment", "main", "active_goal",
        "Deployment smoke check must preserve the database.", [source], 300, now,
        item_id="working-deployment", session_identity=_identity())
    due = now - timedelta(seconds=1)
    engine.schedule_intention(Intention("intention-deployment", "t", "u", "codex", "exact_time",
        {"at": due.isoformat()}, {"text": "Perform the deployment smoke check."}, due, evidence_ids=[source]))
    result = tools.prepare_context("t", "u", "session", "deployment smoke check", session_identity=_identity())
    assert {"working", "intention"} <= {row["kind"] for row in result["hits"]}
    assert {"working-deployment", "intention-deployment"} <= {row["id"] for row in result["hits"]}
    assert source in result["_context_text"]
    other = tools.prepare_context("t", "u", "other", "deployment smoke check", session_identity=_identity("other"))
    assert "working-deployment" not in {row["id"] for row in other["hits"]}
    engine.forget("t", source)
    erased = tools.prepare_context("t", "u", "session", "deployment smoke check", session_identity=_identity())
    assert not {"working-deployment", "intention-deployment"} & {row["id"] for row in erased["hits"]}
    assert source not in erased["_context_text"]
    engine.close()


def test_host_uses_current_manifest_and_resets_to_unknown_when_absent(tmp_path):
    calls = []
    def invoke(facade, name, arguments, session_id):
        assert name == "prepare_context"
        calls.append(arguments)
        return {"receipt_id": "receipt-" + str(len(calls)), "_context_text": "bounded context"}
    adapter = CodexAdapter(state_dir=tmp_path / "state", tenant_id="t", user_id="u",
        open_facade=lambda: nullcontext(SimpleNamespace()), locked=nullcontext, invoke=invoke,
        transcript_root=tmp_path / "transcripts", report_command=["python", "report.py"])
    first = adapter.handle({"hook_event_name": "UserPromptSubmit", "session_id": "session",
        "turn_id": "one", "prompt": "inspect deployment", "available_tools": ["read", "exec", "read"]})
    assert first["hookSpecificOutput"]["additionalContext"] == "bounded context"
    assert calls[0]["available_tools"] == ["exec", "read"]
    assert calls[0]["delivery_envelope"]["capabilities_status"] == "current_host_manifest"
    adapter.handle({"hook_event_name": "UserPromptSubmit", "session_id": "session",
                    "turn_id": "two", "prompt": "inspect another deployment"})
    assert calls[1]["available_tools"] == []
    assert calls[1]["delivery_envelope"]["capabilities_status"] == "unknown"
    retained = [json.loads(path.read_text()) for path in (tmp_path / "state").glob("session-*.json")]
    assert retained
    assert all(state.get("available_tools", []) == [] for state in retained)


def test_expired_source_cannot_deliver_a_due_intention():
    engine = LocalMemoryEngine()
    engine.policy.token_budget = 16000
    tools = MemoryTools(engine)
    due = datetime.now(UTC) - timedelta(seconds=1)
    source = engine.append_evidence(Evidence(tenant_id="t", user_id="u", actor="user", source_type="chat",
        content="Remember the expired deployment instruction.", trust_tier=1,
        metadata={"expires_at": "2000-01-01T00:00:00Z"},
        access_policy={"tenant": "t", "allow_principals": ["u"]}))
    engine.schedule_intention(Intention("expired-intention", "t", "u", "codex", "exact_time",
        {"at": due.isoformat()}, {"text": "Expired deployment instruction."}, due, evidence_ids=[source]))
    result = tools.prepare_context("t", "u", "session", "deployment instruction", session_identity=_identity())
    assert "expired-intention" not in {row["id"] for row in result["hits"]}
    assert "Expired deployment instruction." not in result["_context_text"]
    engine.close()


def test_unreturned_context_never_enters_completed_episode(tmp_path):
    from tests.test_codex_lifecycle import LocalHost
    host = LocalHost(tmp_path)
    host.adapter.require_delivery_confirmation = True
    host.event("UserPromptSubmit", turn_id="undelivered", prompt="Summarize the build report")
    host.event("Stop", last_assistant_message="The build report is ready.")
    assert host.episodes()[-1]["receipt_ids"] == []


def test_confirmed_return_can_enter_completed_episode(tmp_path):
    from tests.test_codex_lifecycle import LocalHost
    from mnemosyne.experience.receipts import digest
    host = LocalHost(tmp_path)
    host.adapter.require_delivery_confirmation = True
    prepared = host.event("UserPromptSubmit", turn_id="returned", prompt="Summarize the build report")
    row = prepared["_mnemosyne_delivery"]
    directory = host.adapter.state_dir / "deliveries"
    directory.mkdir()
    (directory / (digest(row["receipt_id"]) + ".json")).write_text(json.dumps({**row, "status": "returned"}))
    host.event("Stop", last_assistant_message="The build report is ready.")
    assert host.episodes()[-1]["receipt_ids"] == [row["receipt_id"]]


def test_completed_authenticated_turn_feeds_working_memory_once():
    engine = LocalMemoryEngine()
    tools = MemoryTools(engine)
    identity = SessionIdentity('t', 'u', 'operator', 1, agent_id='codex', session_id='s')
    args = dict(tenant_id='t', user_id='u', session_id='s', user_text='Please finish the Atlas deployment plan.',
                assistant_text='The first step is prepared.', observation_id='working:one', session_identity=identity)
    result = tools.observe_turn(**args)
    assert result['working_item_ids']
    repeated = tools.observe_turn(**args)
    assert repeated['working_item_ids'] == result['working_item_ids']
    rows = engine.list_working('t', 's', as_of=datetime.now(UTC))
    assert len(rows) == 1
    assert rows[0].content == args['user_text']
    engine.forget('t', rows[0].evidence_ids[0])
    assert tools.observe_turn(**args)['working_item_ids'] == []
