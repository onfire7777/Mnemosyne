"""Explicit use and durable host evidence, without crediting retrieval alone."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mnemosyne.hosts.codex import _read_transcript, _tool_event, reparse_retained_events
from mnemosyne.mcp_tools import MemoryTools
from mnemosyne.models import Evidence
from mnemosyne.skills import SkillStore
from tests.test_codex_lifecycle import LocalHost, write_transcript


def test_memory_reads_do_not_claim_application(tmp_path):
    host = LocalHost(tmp_path)
    host.event("UserPromptSubmit", turn_id="turn", prompt="Read reference material")
    for tool, arguments in [("skill_get", {"skill_id": "skill"}),
                            ("knowledge_page_get", {"page_id": "page"}),
                            ("observation_get", {"observation_id": "observation"})]:
        host.event("PostToolUse", tool_name="mnemosyne." + tool,
                   tool_input=arguments, tool_response={})
    transcript = write_transcript(tmp_path, [("turn", "Read reference material", [{
        "type": "McpToolCall", "id": "read", "server": "mnemosyne", "tool": "skill_get",
        "arguments": {"skill_id": "skill"}, "status": "completed", "result": {},
    }], "I read it.")])
    assert _read_transcript(transcript, "session")[0]["used_skills"] == []
    host.event("Stop", transcript_path=str(transcript))
    episode = host.episodes()[-1]
    assert episode["used_skills"] == [] and episode["cited_cids"] == []
    assert not host.runtime.writer.read("t")["credit"]


def test_explicit_skill_use_is_receipt_bound_and_keeps_independent_check(tmp_path):
    host = LocalHost(tmp_path)
    host.engine.policy.learning_exploration_rate = 1
    host.engine.policy.token_budget = 16000
    cid = host.engine.append_evidence(Evidence(tenant_id="t", user_id="u", actor="user",
        source_type="import", content="Read the release checklist."))
    source = tmp_path / "release.md"
    source.write_text("---\nname: release-guide\n---\nRead the release checklist.")
    store = SkillStore(str(tmp_path / "skills.sqlite"))
    store.import_skill(str(source), "", memory={"tenant": "t", "user": "u", "cids": [cid]})
    tools = MemoryTools(host.engine, skill_store=store)
    host.runtime = tools._learning_runtime()
    output = host.event("UserPromptSubmit", turn_id="turn", prompt="release-guide")
    context = json.loads(output["hookSpecificOutput"]["additionalContext"].split("\n", 1)[1])
    skill = context["skills"][0]["id"]
    for fields in ({"used_skills": ["not-served"]},
                   {"used_skills": [skill], "verifications": [{"skill_id": skill, "verdict": True}]}):
        with pytest.raises(ValueError):
            host.event("MemoryUse", receipt_id=context["receipt_id"], **fields)
    result = host.event("MemoryUse", receipt_id=context["receipt_id"], used_skills=[skill],
        verifications=[{"skill_id": skill, "call_id": "check", "check_id": "release-check"}])
    assert result["used_skills"] == [skill] and result["verified"] is False
    host.event("PostToolUse", tool_name="release_checker", tool_use_id="check",
        tool_response={"structuredContent": {"verdict": True, "check_id": "release-check",
            "receipt_id": context["receipt_id"], "target_ids": [skill]}})
    host.event("Stop", last_assistant_message="Checked release checklist.")
    episode = host.episodes()[-1]
    assert episode["used_skills"] == [skill]
    assert episode["target_outcomes"][skill]["value"] == 1
    assert not host.runtime.writer.read("t")["credit"]


def test_spool_is_retained_until_durable_state_commit(tmp_path):
    host = LocalHost(tmp_path)
    host.event("UserPromptSubmit", turn_id="turn", prompt="Run checks")
    path = next((tmp_path / "state").glob("session-*.json"))
    event = _tool_event("shell", {"exit_code": 0, "output": "2 passed in 1s"},
                        tool_id="check", command="pytest")
    host.adapter._append_spool(path, {"turn_id": "turn", "tool_event": event})
    before = json.loads(path.read_text())
    host.adapter._drain_spool(path, before)
    assert path.with_suffix(".spool.jsonl").exists()
    # Simulate interruption before _save: recovery starts from durable state.
    recovered = json.loads(path.read_text())
    host.adapter._drain_spool(path, recovered)
    host.adapter._drain_spool(path, recovered)
    assert [row["call_id"] for row in recovered["tool_events"]] == ["check"]
    host.adapter._save(path, recovered)
    assert not path.with_suffix(".spool.jsonl").exists()
    host.event("Stop", last_assistant_message="Checks passed.")
    assert host.episodes()[-1]["reward"] == 1


@pytest.mark.parametrize("spooled", [False, True])
def test_late_tool_event_retains_original_turn_after_new_prompt(tmp_path, spooled):
    host = LocalHost(tmp_path)
    host.event("UserPromptSubmit", turn_id="first", prompt="Run checks")
    host.event("UserPromptSubmit", turn_id="second", prompt="Another request")
    event = _tool_event("checker", {"verdict": False}, tool_id="first-check")
    if spooled:
        path = next((tmp_path / "state").glob("session-*.json"))
        host.adapter._append_spool(path, {"turn_id": "first", "tool_event": event})
    else:
        host.event("PostToolUse", turn_id="first", tool_name="checker",
                   tool_use_id="first-check", tool_response={"verdict": False})
    transcript = write_transcript(tmp_path, [
        ("first", "Run checks", [], "Failed."), ("second", "Another request", [], "Done.")])
    host.event("Stop", transcript_path=str(transcript))
    episodes = host.episodes()
    assert episodes[0]["reward"] == -1
    assert [event["call_id"] for event in episodes[0]["tool_events"]] == ["first-check"]
    assert episodes[1]["tool_events"] == []
    host.event("Stop", transcript_path=str(transcript))
    assert len(host.episodes()) == 2


def test_superseded_context_is_not_returned_as_current(tmp_path):
    host = LocalHost(tmp_path)
    invoke = host.adapter.invoke
    newer = {}

    def interrupted(facade, name, arguments, session):
        if name == "prepare_context" and arguments["query"] == "First request":
            newer.update(host.event("UserPromptSubmit", turn_id="second", prompt="Second request"))
        return invoke(facade, name, arguments, session)

    host.adapter.invoke = interrupted
    assert host.event("UserPromptSubmit", turn_id="first", prompt="First request") == {}
    state = json.loads(next((tmp_path / "state").glob("session-*.json")).read_text())
    assert state["turn_id"] == "second"
    assert state["receipt_id"] == newer["_mnemosyne_delivery"]["receipt_id"]
    assert "first" not in state["prepared_turns"]


@pytest.mark.parametrize("spooled", [False, True])
def test_late_finalized_turn_evidence_reconciles_original_episode(tmp_path, spooled):
    host = LocalHost(tmp_path)
    host.event("UserPromptSubmit", turn_id="first", prompt="Run checks")
    host.event("PostToolUse", turn_id="first", tool_name="checker", tool_use_id="fast-check",
               tool_response={"verdict": True})
    host.event("Stop", last_assistant_message="Fast check passed.")
    original = host.episodes()[0]
    assert original["reward"] == 1
    host.event("UserPromptSubmit", turn_id="second", prompt="Another request")
    path = next((tmp_path / "state").glob("session-*.json"))
    event = _tool_event("checker", {"verdict": False}, tool_id="late-failed-check")
    if spooled:
        host.adapter._append_spool(path, {"turn_id": "first", "tool_event": event})
    else:
        host.event("PostToolUse", turn_id="first", tool_name="checker", tool_use_id="late-failed-check",
                   tool_response={"verdict": False})
    host.event("Stop", last_assistant_message="Current turn completed.")
    state = json.loads(path.read_text())
    assert state["late_tool_events"] == {}
    repaired = host.runtime.episode("t", original["id"])
    assert repaired["reward"] == -1
    assert [item["call_id"] for item in repaired["tool_events"]] == ["fast-check", "late-failed-check"]
    assert repaired["tool_events"][:1] == original["tool_events"]
    assert repaired["receipt_ids"] == original["receipt_ids"]
    assert repaired["prediction"] == original["prediction"]
    assert not path.with_suffix(".spool.jsonl").exists()
    assert host.episodes()[1]["tool_events"] == []
    host.event("Stop", last_assistant_message="Current turn completed.")
    assert host.runtime.episode("t", original["id"]) == repaired
    report = host.adapter.recover_completed()
    assert report["pending_late_event_sessions"] == 0
    assert report["pending_late_events"] == 0


def test_reparse_keeps_original_external_runner_kind():
    event = {"source": "tool", "command": "ruff check src", "exit_code": 0,
             "output": "All checks passed!", "call_id": "actual"}
    parsed = reparse_retained_events([event])[0]
    assert parsed["runner"] == "ruff" and parsed["passed"] == 1
    assert "_runner" not in parsed and parsed["call_id"] == "actual"
    assert "receipt_id" not in parsed and "target_ids" not in parsed


def test_timeout_diagnostics_are_stage_and_session_scoped_without_payload(tmp_path, monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "runtime", SimpleNamespace(
        STATE=tmp_path, TENANT="t", USER="u", invoke=None, locked=None, open_facade=None))
    source = Path(__file__).resolve().parents[1] / "integrations/codex/hook.py"
    spec = importlib.util.spec_from_file_location("isolated_codex_hook", source)
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)

    def timeout(command, payload, **kwargs):
        hook._write_stage(payload, "prepare_context", "session", "turn")
        return None, {"attempts": [{"mode": "local", "status": "timeout"}]}

    monkeypatch.setattr("mnemosyne.hosts.deadlines.run_bounded", timeout)
    hook.supervise({"hook_event_name": "UserPromptSubmit", "session_id": "session",
                    "turn_id": "turn", "prompt": "PRIVATE CONTENT MUST NOT BE LOGGED"})
    text = (tmp_path / "host-attempts.jsonl").read_text()
    row = json.loads(text)
    assert row["session_id"] == "session" and row["turn_id"] == "turn"
    assert row["last_stage"]["stage"] == "prepare_context"
    assert "PRIVATE CONTENT" not in text
    assert not list(tmp_path.glob("hook-stage-*.json"))


def test_unchanged_compatibility_migration_refreshes_without_a_write(tmp_path, monkeypatch):
    from mnemosyne.experience.writer import LearningWriter
    from mnemosyne.learning import LearningSystem
    from mnemosyne.runtime_state import migrate_legacy_learning

    host = LocalHost(tmp_path)
    system = LearningSystem(host.engine)
    system.load_native(["t"])
    observed = host.runtime.observe_turn("t", "u", "new-chat", "Later request", "Response")
    calls = []
    read = host.runtime.writer.read

    def counted_read(tenant):
        calls.append(tenant)
        return read(tenant)

    def forbidden_write(*args, **kwargs):
        raise AssertionError("unchanged migration must not make a guarded write")

    monkeypatch.setattr(host.runtime.writer, "read", counted_read)
    monkeypatch.setattr(LearningWriter, "apply", forbidden_write)
    assert migrate_legacy_learning(host.runtime, system, "t") == {"archived": 0}
    assert calls == ["t"]
    assert observed["episode_id"] in system.trajectories


def test_changed_compatibility_migration_still_persists_through_native_writer(tmp_path):
    from mnemosyne.learning import LearningSystem
    from mnemosyne.runtime_state import migrate_legacy_learning

    host = LocalHost(tmp_path)
    observed = host.runtime.observe_turn("t", "u", "chat", "Original request", "Response")
    system = LearningSystem(host.engine)
    system.load_native(["t"])
    system.trajectories[observed["episode_id"]].task = "Corrected request"
    migrate_legacy_learning(host.runtime, system, "t")
    assert host.runtime.episode("t", observed["episode_id"])["user_text"] == "Corrected request"
