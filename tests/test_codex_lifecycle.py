import json
import os
import subprocess
import sys
import textwrap
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.experience.integration import observe_completed_turn
from mnemosyne.hosts.codex import CodexAdapter


class LocalHost:
    def __init__(self, tmp_path):
        self.engine = LocalMemoryEngine(store_path=tmp_path / "memory.json")
        self.runtime = LearningRuntime(self.engine)
        self.fail_after_observe = False
        self.adapter = CodexAdapter(
            state_dir=tmp_path / "state",
            tenant_id="t",
            user_id="u",
            open_facade=lambda: nullcontext(SimpleNamespace(engine=self.engine)),
            locked=nullcontext,
            invoke=self.invoke,
            transcript_root=tmp_path / "transcripts",
        )

    def invoke(self, facade, name, arguments, session_id):
        if name == "observe_turn" and self.fail_after_observe:
            self.fail_after_observe = False
            self.runtime.observe_turn("t", "u", **arguments)
            raise OSError("interrupted after the durable observation")
        if name == "observe_turn":
            result = observe_completed_turn(self.runtime, "t", "u", **arguments)
        elif name == "end_session":
            result = self.runtime.end_session("t", **arguments)
        else:
            result = getattr(self.runtime, name)("t", "u", **arguments)
        return result

    def event(self, kind, **values):
        return self.adapter.handle(
            {"hook_event_name": kind, "session_id": "session", **values}
        )

    def episodes(self):
        return list(self.runtime.writer.read("t")["episodes"].values())


def test_session_start_includes_configured_scope_without_claiming_learning_is_enabled(
    tmp_path,
):
    host = LocalHost(tmp_path)
    host.runtime.pause("t")
    output = host.event("SessionStart")["hookSpecificOutput"]["additionalContext"]
    assert "Tenant t, user u, agent codex." in output
    assert "Current session_id is session." in output
    assert "enabled" not in output


def write_transcript(tmp_path, turns, *, session="session"):
    path = tmp_path / "transcript.jsonl"
    rows = [{"type": "session_meta", "payload": {"id": session, "session_id": session}}]
    for turn, prompt, commands, final in turns:
        rows.append(
            {"type": "event_msg", "payload": {"type": "task_started", "turn_id": turn}}
        )
        items = [
            {
                "type": "UserMessage",
                "id": turn + "-user",
                "content": [{"type": "text", "text": prompt}],
            }
        ]
        items.extend(commands)
        if final is not None:
            items.append(
                {
                    "type": "AgentMessage",
                    "id": turn + "-final",
                    "phase": "final",
                    "content": [{"type": "text", "text": final}],
                }
            )
        rows.extend(
            {
                "type": "event_msg",
                "payload": {
                    "type": "item_completed",
                    "thread_id": session,
                    "turn_id": turn,
                    "item": item,
                },
            }
            for item in items
        )
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    return path


def command(
    output, *, exit_code=0, status="completed", command=None, identifier="command-1"
):
    return {
        "type": "CommandExecution",
        "id": identifier,
        "command": command or ["python", "-m", "pytest", "-q"],
        "cwd": "/tmp",
        "source": "unified_exec_startup",
        "status": status,
        "aggregated_output": output,
        "exit_code": exit_code,
    }


def test_stop_recovers_a_new_turn_when_prompt_hook_was_missed(tmp_path):
    host = LocalHost(tmp_path)
    host.event("UserPromptSubmit", turn_id="old", prompt="old request")
    host.event("Stop", last_assistant_message="old response")
    old_receipt = host.episodes()[0]["receipt_ids"][0]
    transcript = write_transcript(
        tmp_path,
        [
            ("old", "old request", [], "old response"),
            ("new", "fix cache", [command("2 passed in 0.10s")], "fixed"),
        ],
    )
    host.event(
        "Stop",
        transcript_path=str(transcript),
        last_assistant_message="wrong stale payload",
    )
    host.event("Stop", transcript_path=str(transcript))
    episodes = host.episodes()
    assert [row["user_text"] for row in episodes] == ["old request", "fix cache"]
    assert episodes[0]["receipt_ids"] == [old_receipt]
    assert episodes[1]["receipt_ids"] == []
    assert episodes[1]["tool_events"][0]["passed"] == 2
    assert (
        host.engine.get_evidence("t", episodes[1]["source_cids"][1]).content == "fixed"
    )


@pytest.mark.parametrize("passed", [True, False])
def test_real_pytest_output_produces_verified_test_counts(tmp_path, passed):
    test_file = tmp_path / "test_example.py"
    test_file.write_text("def test_example():\n    assert " + str(passed) + "\n")
    args = [sys.executable, "-m", "pytest", "-q", "-o", "addopts=", str(test_file)]
    completed = subprocess.run(
        args, cwd=tmp_path, capture_output=True, text=True, check=False
    )
    host = LocalHost(tmp_path)
    transcript = write_transcript(
        tmp_path,
        [
            (
                "turn",
                "run the tests",
                [
                    command(
                        completed.stdout, exit_code=completed.returncode, command=args
                    )
                ],
                "done",
            )
        ],
    )
    host.event("Stop", transcript_path=str(transcript))
    episode = host.episodes()[0]
    event = episode["tool_events"][0]
    assert (event["passed"], event["failed"]) == ((1, 0) if passed else (0, 1))
    assert episode["reward"] == (1 if passed else -1)


def test_non_pytest_output_and_assistant_claims_do_not_prove_success(tmp_path):
    host = LocalHost(tmp_path)
    transcript = write_transcript(
        tmp_path,
        [
            (
                "turn",
                "check something",
                [
                    command(
                        "99 passed in 0.01s", command=["printf", "99 passed in 0.01s"]
                    )
                ],
                "All tests passed successfully",
            )
        ],
    )
    host.event("Stop", transcript_path=str(transcript))
    episode = host.episodes()[0]
    assert "passed" not in episode["tool_events"][0]
    assert episode["reward"] is None


def test_recovered_turn_does_not_credit_retrospectively_prepared_memory(tmp_path):
    host = LocalHost(tmp_path)
    transcript = write_transcript(
        tmp_path, [("turn", "run tests", [command("2 passed in 0.10s")], "done")]
    )
    host.event("Stop", transcript_path=str(transcript))
    assert host.episodes()[0]["receipt_ids"] == []
    assert host.runtime.writer.read("t")["receipts"] == {}


@pytest.mark.parametrize(
    "script",
    [
        "pytest failing_tests; echo '100 passed in 1s'",
        "pytest failing_tests || echo '100 passed in 1s'",
        "pytest failing_tests\necho '100 passed in 1s'",
    ],
)
def test_compound_shell_output_cannot_supply_a_pytest_grade(tmp_path, script):
    host = LocalHost(tmp_path)
    transcript = write_transcript(
        tmp_path,
        [
            (
                "turn",
                "check tests",
                [
                    command(
                        "1 failed in 0.1s\n100 passed in 1s",
                        command=["/bin/zsh", "-lc", script],
                    )
                ],
                "done",
            )
        ],
    )
    host.event("Stop", transcript_path=str(transcript))
    episode = host.episodes()[0]
    assert "passed" not in episode["tool_events"][0]
    assert episode["reward"] is None


@pytest.mark.parametrize("verdict", [True, False])
def test_structured_boolean_verdict_reaches_native_outcome_interpretation(
    tmp_path, verdict
):
    host = LocalHost(tmp_path)
    host.event("UserPromptSubmit", turn_id="turn", prompt="verify output")
    host.event(
        "PostToolUse",
        tool_name="external_validator",
        tool_response={"verdict": verdict, "output": "verified by validator"},
    )
    host.event("Stop", last_assistant_message="done")
    assert host.episodes()[0]["reward"] == (1 if verdict else -1)


def test_unfinished_command_does_not_record_a_failure(tmp_path):
    host = LocalHost(tmp_path)
    transcript = write_transcript(
        tmp_path,
        [
            (
                "turn",
                "start tests",
                [command("1 failed in 0.01s", exit_code=1, status="inProgress")],
                "still running",
            )
        ],
    )
    host.event("Stop", transcript_path=str(transcript))
    episode = host.episodes()[0]
    assert "exit_code" not in episode["tool_events"][0]
    assert "failed" not in episode["tool_events"][0]
    assert episode["reward"] is None


def test_transcript_cannot_supply_another_sessions_turn(tmp_path):
    host = LocalHost(tmp_path)
    transcript = write_transcript(
        tmp_path,
        [("turn", "private prompt", [], "private answer")],
        session="another-session",
    )
    with pytest.raises(ValueError, match="session"):
        host.event("Stop", transcript_path=str(transcript))
    assert host.episodes() == []


def test_subagent_transcript_cannot_supply_a_human_turn(tmp_path):
    host = LocalHost(tmp_path)
    transcript = write_transcript(
        tmp_path,
        [("turn", "assistant-authored subtask", [command("2 passed in 0.1s")], "done")],
    )
    rows = [json.loads(line) for line in transcript.read_text().splitlines()]
    rows[0]["payload"]["source"] = {
        "subagent": {"thread_spawn": {"parent_thread_id": "parent"}}
    }
    transcript.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    host.event(
        "UserPromptSubmit",
        turn_id="turn",
        prompt="assistant-authored subtask",
        transcript_path=str(transcript),
    )
    host.event("Stop", transcript_path=str(transcript))
    assert host.episodes() == []
    assert host.runtime.writer.read("t")["receipts"] == {}
    assert not host.engine.export_tenant("t")["evidence"]


@pytest.mark.parametrize(
    "event", ["SessionStart", "UserPromptSubmit", "PostToolUse", "Stop", "SessionEnd"]
)
def test_subagent_hook_origin_is_ignored(tmp_path, event):
    host = LocalHost(tmp_path)
    host.event(
        event,
        source={"subagent": {"thread_spawn": {"parent_thread_id": "parent"}}},
        prompt="assistant subtask",
        last_assistant_message="done",
        turn_id="turn",
    )
    assert host.episodes() == []
    assert host.runtime.writer.read("t")["receipts"] == {}


def test_transcript_outcomes_replace_duplicate_plain_hook_output(tmp_path):
    host = LocalHost(tmp_path)
    host.event("UserPromptSubmit", turn_id="turn", prompt="run the tests")
    for _ in range(2):
        host.event(
            "PostToolUse",
            tool_name="Bash",
            tool_input={"command": "python -m pytest -q"},
            tool_response="2 passed in 0.10s",
            tool_use_id="command-1",
        )
    transcript = write_transcript(
        tmp_path, [("turn", "run the tests", [command("2 passed in 0.10s")], "done")]
    )
    host.event("Stop", transcript_path=str(transcript))
    events = host.episodes()[0]["tool_events"]
    assert len(events) == 1
    assert events[0]["passed"] == 2
    assert len(host.episodes()[0]["receipt_ids"]) == 1


def test_stop_retry_after_durable_observation_does_not_duplicate_episode(tmp_path):
    host = LocalHost(tmp_path)
    transcript = write_transcript(
        tmp_path, [("turn", "run tests", [command("2 passed in 0.10s")], "done")]
    )
    host.fail_after_observe = True
    with pytest.raises(OSError):
        host.event("Stop", transcript_path=str(transcript))
    host.event("Stop", transcript_path=str(transcript))
    assert len(host.episodes()) == 1
    assert host.episodes()[0]["reward"] == 1


def test_partial_transcript_does_not_relabel_a_completed_older_turn(tmp_path):
    host = LocalHost(tmp_path)
    transcript = write_transcript(
        tmp_path, [("old", "completed", [], "done"), ("new", "in progress", [], None)]
    )
    host.event("Stop", transcript_path=str(transcript))
    assert [row["user_text"] for row in host.episodes()] == ["completed"]


def test_distinct_command_runs_with_identical_output_are_preserved(tmp_path):
    host = LocalHost(tmp_path)
    transcript = write_transcript(
        tmp_path,
        [
            (
                "turn",
                "repeat tests",
                [
                    command("2 passed in 0.10s", identifier="first"),
                    command("2 passed in 0.10s", identifier="second"),
                ],
                "done",
            )
        ],
    )
    host.event("Stop", transcript_path=str(transcript))
    assert len(host.episodes()[0]["tool_events"]) == 2


def test_session_end_closes_existing_episodes_when_latest_turn_is_incomplete(tmp_path):
    host = LocalHost(tmp_path)
    host.event("UserPromptSubmit", turn_id="old", prompt="old request")
    host.event("Stop", last_assistant_message="unverified response")
    transcript = write_transcript(tmp_path, [("new", "unfinished request", [], None)])
    host.event("SessionEnd", transcript_path=str(transcript))
    assert host.episodes()[0]["status"] == "unknown"


def test_changed_prompt_cannot_inherit_an_unrelated_prepared_receipt(tmp_path):
    host = LocalHost(tmp_path)
    host.event("UserPromptSubmit", turn_id="turn", prompt="original request")
    before = host.runtime.writer.read("t")["receipts"]
    transcript = write_transcript(tmp_path, [("turn", "changed request", [], "done")])
    host.event("Stop", transcript_path=str(transcript))
    assert host.episodes()[0]["receipt_ids"] == []
    assert host.runtime.writer.read("t")["receipts"] == before


def test_session_bound_transcript_is_discovered_when_hook_path_is_absent(tmp_path):
    host = LocalHost(tmp_path)
    path = write_transcript(tmp_path, [("turn", "discovered request", [], "done")])
    directory = tmp_path / "transcripts" / "2026" / "11" / "06"
    directory.mkdir(parents=True)
    path.rename(directory / "rollout-2026-11-06T01-00-00-session.jsonl")
    host.event("Stop")
    assert host.episodes()[0]["user_text"] == "discovered request"


def test_legacy_observed_marker_survives_a_new_turn_and_delayed_stop(tmp_path):
    host = LocalHost(tmp_path)
    host.event("UserPromptSubmit", turn_id="old", prompt="old request")
    host.event("Stop", last_assistant_message="old answer")
    state_path = next((tmp_path / "state").glob("session-*.json"))
    state = json.loads(state_path.read_text())
    state.pop("observed_turns")
    state_path.write_text(json.dumps(state))
    host.event("UserPromptSubmit", turn_id="new", prompt="new request")
    transcript = write_transcript(
        tmp_path,
        [
            ("old", "old request", [], "old answer"),
            ("new", "new request", [], "new answer"),
        ],
    )
    host.event("Stop", transcript_path=str(transcript))
    host.event("Stop", transcript_path=str(transcript), turn_id="old")
    assert [row["user_text"] for row in host.episodes()] == [
        "old request",
        "new request",
    ]


def test_hook_process_accepts_json_and_retries_across_processes(tmp_path):
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "runtime.py").write_text(
        textwrap.dedent("""
        import os
        from contextlib import contextmanager, nullcontext
        from pathlib import Path
        from types import SimpleNamespace
        from mnemosyne.engine import LocalMemoryEngine
        from mnemosyne.experience.runtime import LearningRuntime
        from mnemosyne.experience.integration import observe_completed_turn
        ROOT = Path(os.environ["CODEX_HOOK_TEST_ROOT"])
        STATE = ROOT / "state"
        TENANT, USER = "t", "u"
        locked = nullcontext
        @contextmanager
        def open_facade():
            engine = LocalMemoryEngine(store_path=ROOT / "memory.json")
            try:
                yield SimpleNamespace(engine=engine, runtime=LearningRuntime(engine))
            finally:
                engine.close()
        def invoke(facade, name, arguments, session_id):
            if name == "observe_turn":
                return observe_completed_turn(facade.runtime, TENANT, USER, **arguments)
            return getattr(facade.runtime, name)(TENANT, USER, **arguments)
    """)
    )
    transcript = write_transcript(
        tmp_path, [("turn", "test command", [command("2 passed in 0.10s")], "done")]
    )
    environment = dict(
        os.environ,
        CODEX_HOOK_TEST_ROOT=str(tmp_path),
        PYTHONPATH=os.pathsep.join([str(tmp_path), str(root / "src")]),
    )
    environment.pop("MNEMOSYNE_INTERNAL", None)
    payload = {
        "hook_event_name": "Stop",
        "session_id": "session",
        "transcript_path": str(transcript),
    }
    for _ in range(2):
        completed = subprocess.run(
            [sys.executable, str(root / "integrations/codex/hook.py")],
            input=json.dumps(payload),
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )
        assert json.loads(completed.stdout) == {}
    engine = LocalMemoryEngine(store_path=tmp_path / "memory.json")
    episodes = list(LearningRuntime(engine).writer.read("t")["episodes"].values())
    assert len(episodes) == 1
    assert episodes[0]["reward"] == 1
    assert episodes[0]["receipt_ids"] == []
    engine.close()
