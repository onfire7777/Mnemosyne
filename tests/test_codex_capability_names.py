"""Current tool names must match the host's recorded action names."""
import json

from mnemosyne.hosts.codex import _tool_manifest
from tests.test_codex_lifecycle import LocalHost


def test_native_capability_aliases_are_grounded_in_current_manifest():
    assert _tool_manifest({"available_tools": ["functions.exec_command", "mcp__checks__verify"]}) == [
        "checks.verify", "functions.exec_command", "mcp__checks__verify", "shell"]
    assert _tool_manifest({"available_tools": ["exec", "plugin.exec_command", "write_stdin"]}) == [
        "exec", "plugin.exec_command", "write_stdin"]
    assert _tool_manifest({"available_tools": []}) == []
    assert _tool_manifest({}) is None


def test_recorded_shell_action_is_usable_in_later_native_tool_manifest(tmp_path):
    host = LocalHost(tmp_path)
    first = host.adapter.handle({"hook_event_name": "UserPromptSubmit", "session_id": "first",
        "turn_id": "a", "prompt": "Run smoke tests", "available_tools": ["exec_command"]})
    initial = json.loads(first["hookSpecificOutput"]["additionalContext"].split("\n", 1)[1])
    host.adapter.handle({"hook_event_name": "PostToolUse", "session_id": "first", "turn_id": "a",
        "tool_name": "shell", "tool_use_id": "check", "tool_input": {"command": "pytest tests"},
        "tool_response": {"exit_code": 0, "output": "2 passed in 0.10s"}})
    host.adapter.handle({"hook_event_name": "Stop", "session_id": "first", "last_assistant_message": "Done"})
    later = host.adapter.handle({"hook_event_name": "UserPromptSubmit", "session_id": "second",
        "turn_id": "b", "prompt": "Execute smoke tests.", "available_tools": ["exec_command"]})
    recalled = json.loads(later["hookSpecificOutput"]["additionalContext"].split("\n", 1)[1])
    assert recalled["task_class"] == initial["task_class"]
    receipt = host.runtime.writer.read("t")["receipts"][recalled["receipt_id"]]
    assert "shell" in receipt["available_tools"]
    assert receipt["task_match"]["matched_episode_id"] == host.episodes()[0]["id"]
    unavailable = host.adapter.handle({"hook_event_name": "UserPromptSubmit", "session_id": "third",
        "turn_id": "c", "prompt": "Execute smoke tests.", "available_tools": ["browser"]})
    other = json.loads(unavailable["hookSpecificOutput"]["additionalContext"].split("\n", 1)[1])
    assert other["task_class"] != initial["task_class"]
