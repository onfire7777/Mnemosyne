"""Public capture and completed-turn entry points form source-bound memory."""

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.mcp_tools import MemoryTools
from mnemosyne.sqlite_engine import SqliteEngine


@pytest.fixture(params=["local", "sqlite"])
def memory(request, tmp_path):
    engine = SqliteEngine(tmp_path / "memory") if request.param == "sqlite" else LocalMemoryEngine()
    yield MemoryTools(engine)
    engine.close()


def test_public_capture_forms_owned_facts_and_retries_idempotently(memory):
    args = dict(tenant_id="t", user_id="u", actor="user", source_type="chat",
                content="I live in Portland.", trust_tier=1)
    first = memory.capture(**args)
    second = memory.capture(**args)
    assert first["memory_formation"]["assertion_ids"]
    assert second["memory_formation"]["assertion_ids"] == first["memory_formation"]["assertion_ids"]
    assert second["memory_formation"]["created_count"] == 0
    rows = memory.engine.export_tenant("t")["assertions"]
    assert len(rows) == 1
    assert rows[0]["source_evidence_cids"] == [first["cid"]]
    memory.engine.forget("t", first["cid"])
    assert not memory.capture(**args)["memory_formation"]


def test_completed_turn_forms_facts_and_one_profile_claim_per_clause(memory):
    args = dict(tenant_id="t", user_id="u", session_id="s",
                user_text="I live in Portland. I prefer concise answers.",
                assistant_text="Understood.", observation_id="codex:one")
    first = memory.observe_turn(**args)
    assert any(row["count"] for row in first["memory_formation"])
    assert memory.observe_turn(**args)["already_observed"]
    assert [row.statement for row in memory.user_model.entries.values()] == ["I prefer concise answers."]
    assert len(memory._learning_runtime().writer.read("t")["episodes"]) == 1


def test_quoted_user_preferences_never_create_profile_or_semantic_facts(memory):
    memory.observe_turn("t", "u", "s",
        'Review this example:\n"I prefer long answers."\n```\nI live in Portland.\n```',
        "The example is quoted.", observation_id="codex:quote")
    assert not memory.user_model.entries
    assert not memory.engine.export_tenant("t")["assertions"]


def test_identical_first_person_claims_keep_separate_owners(memory):
    captures = [memory.capture("t", user, "user", "chat", "I live in Portland.", trust_tier=1)
                for user in ("alice", "bob")]
    assert captures[0]["cid"] != captures[1]["cid"]
    for user, capture in zip(("alice", "bob"), captures):
        source = memory.engine.get_evidence("t", capture["cid"])
        assert source.user_id == user
    rows = memory.engine.export_tenant("t")["assertions"]
    assert {row["user_id"] for row in rows} == {"alice", "bob"}
    assert all(row["access_policy"]["allow_principals"] == [row["user_id"]] for row in rows)


def test_observation_retries_projection_failure_without_duplicate_episode(memory, monkeypatch):
    import mnemosyne.memory_formation as formation
    original = formation.project_direct_user_memory
    def unavailable(*args, **kwargs):
        raise RuntimeError("projection temporarily unavailable")
    monkeypatch.setattr(formation, "project_direct_user_memory", unavailable)
    args = dict(tenant_id="t", user_id="u", session_id="s", user_text="I live in Portland.",
                assistant_text="Understood.", observation_id="codex:retry")
    with pytest.raises(RuntimeError, match="temporarily unavailable"):
        memory.observe_turn(**args)
    monkeypatch.setattr(formation, "project_direct_user_memory", original)
    result = memory.observe_turn(**args)
    assert result["already_observed"]
    assert any(row["count"] for row in result["memory_formation"])
    assert len(memory._learning_runtime().writer.read("t")["episodes"]) == 1
