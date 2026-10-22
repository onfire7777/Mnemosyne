import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from eval import codex_reader


def _mock(monkeypatch, *, events=None, answer=None, returncode=0, timeout=False):
    calls = []
    events = events if events is not None else [
        {"type": "thread.started", "thread_id": "synthetic-thread", "model": "reported-model"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": '{"answer":"blue"}'}},
        {"type": "turn.completed", "usage": {"input_tokens": 11, "output_tokens": 5}},
    ]

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command[1] == "--version":
            return SimpleNamespace(returncode=0, stdout="codex-cli synthetic\n", stderr="")
        if timeout:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        work = Path(command[command.index("-C") + 1])
        assert work.exists() and not list(work.iterdir())
        schema = json.loads(Path(command[command.index("--output-schema") + 1]).read_text())
        assert schema["required"] == ["answer"] and schema["additionalProperties"] is False
        Path(command[command.index("-o") + 1]).write_text(answer if answer is not None else '{"answer":"blue"}')
        return SimpleNamespace(returncode=returncode, stdout="\n".join(json.dumps(event) for event in events), stderr="")

    monkeypatch.setattr(codex_reader.subprocess, "run", run)
    return calls


@pytest.mark.parametrize("model", [None, "selected-model"])
def test_isolated_codex_command_and_metadata(monkeypatch, model):
    calls = _mock(monkeypatch)
    result = codex_reader.read_with_codex("Context: The door is blue. Question: What color?", model=model)
    assert result["answer"] == "blue"
    assert result["resolved_model"] == "reported-model" and result["requested_model"] == model
    assert result["codex_version"] == "codex-cli synthetic"
    assert result["usage"] == {"input_tokens": 11, "output_tokens": 5}
    command, kwargs = calls[1]
    assert len(calls) == 2
    for flag in ("--ignore-user-config", "--ephemeral", "--skip-git-repo-check", "--json"):
        assert flag in command
    assert "--ignore-rules" not in command
    assert command[command.index("-s") + 1] == "read-only"
    assert "mcp_servers={}" in command and "project_doc_max_bytes=0" in command
    assert "suppress_unstable_features_warning=true" in command
    assert "code_mode_host" not in command
    assert ('-m' in command) is (model is not None)
    for feature in ("hooks", "shell_tool", "unified_exec", "view_image", "memories", "plugins"):
        assert command[command.index(feature) - 1] == "--disable"
    assert command[-1] == "-" and "Context: The door" in kwargs["input"]
    assert not Path(command[command.index("-C") + 1]).exists()


@pytest.mark.parametrize("item_type", ["command_execution", "mcp_tool_call", "web_search", "file_change", "function_call"])
def test_tool_use_rejected_even_with_valid_answer(monkeypatch, item_type):
    _mock(monkeypatch, events=[
        {"type": "item.started", "item": {"type": item_type}}, {"type": "turn.completed"},
    ])
    with pytest.raises(codex_reader.CodexReaderError) as exc:
        codex_reader.read_with_codex("question")
    assert exc.value.kind == "tool_use"


@pytest.mark.parametrize("answer", ["", "no json", "[]", '{}', '{"answer":""}', '{"answer":12}', '{"answer":"a","extra":1}'])
def test_invalid_answers_rejected(monkeypatch, answer):
    _mock(monkeypatch, answer=answer)
    with pytest.raises(codex_reader.CodexReaderError) as exc:
        codex_reader.read_with_codex("question")
    assert exc.value.kind == "invalid_answer"


@pytest.mark.parametrize("events,kind", [
    ([], "incomplete_turn"), ([{"type": "turn.failed"}], "failed_turn"),
    ([{"type": "unknown"}], "invalid_events"),
    ([{"type": "turn.completed"}, {"type": "turn.completed"}], "incomplete_turn"),
])
def test_incomplete_or_failed_stream_rejected(monkeypatch, events, kind):
    _mock(monkeypatch, events=events)
    with pytest.raises(codex_reader.CodexReaderError) as exc:
        codex_reader.read_with_codex("question")
    assert exc.value.kind == kind


@pytest.mark.parametrize("timeout,returncode,kind", [(True, 0, "timeout"), (False, 1, "nonzero_exit")])
def test_failed_attempt_not_retried(monkeypatch, timeout, returncode, kind):
    calls = _mock(monkeypatch, timeout=timeout, returncode=returncode)
    with pytest.raises(codex_reader.CodexReaderError) as exc:
        codex_reader.read_with_codex("question")
    assert exc.value.kind == kind and len(calls) == 2


def test_missing_model_metadata_is_not_invented(monkeypatch):
    _mock(monkeypatch, events=[{"type": "turn.completed"}])
    assert codex_reader.read_with_codex("question", model="requested")["resolved_model"] is None


def test_explicit_reasoning_effort_is_forwarded_and_recorded(monkeypatch):
    calls = _mock(monkeypatch)
    result = codex_reader.read_with_codex("question", reasoning_effort="low")
    assert result["requested_reasoning_effort"] == "low"
    assert 'model_reasoning_effort="low"' in calls[1][0]


@pytest.mark.parametrize("stdout", ["not JSON", "[]", '{"type":{}}', '{"type":null}'])
def test_malformed_event_stream_fails_closed(stdout):
    with pytest.raises(codex_reader.CodexReaderError) as exc:
        codex_reader._events_metadata(stdout)
    assert exc.value.kind == "invalid_events"


def test_error_item_is_reported_as_failure_not_tool_use(monkeypatch):
    _mock(monkeypatch, events=[
        {"type": "item.completed", "item": {"type": "error", "message": "synthetic failure"}},
        {"type": "turn.completed"},
    ])
    with pytest.raises(codex_reader.CodexReaderError) as exc:
        codex_reader.read_with_codex("question")
    assert exc.value.kind == "failed_turn"


def test_unsupported_item_type_named_in_error(monkeypatch):
    _mock(monkeypatch, events=[
        {"type": "item.completed", "item": {"type": "mcp_tool_call"}},
        {"type": "turn.completed"},
    ])
    with pytest.raises(codex_reader.CodexReaderError, match="mcp_tool_call"):
        codex_reader.read_with_codex("question")
