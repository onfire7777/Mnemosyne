import json
import os
import subprocess
import sys
import textwrap
from datetime import UTC, datetime, timedelta
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
    for row in rows:
        row["timestamp"] = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
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
    assert any(
        source.actor == "assistant" and source.content == "fixed"
        for cid in episodes[1]["source_cids"]
        if (source := host.engine.get_evidence("t", cid)) is not None
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


def test_host_observation_identity_retries_without_recapturing_sources(tmp_path):
    host = LocalHost(tmp_path)
    context = host.runtime.prepare_context("t", "u", "session", "request")
    arguments = dict(
        session_id="session", user_text="request", assistant_text="response",
        receipt_ids=[context["receipt_id"]], observation_id="codex:turn-one",
    )
    first = host.runtime.observe_turn("t", "u", **arguments)
    source_count = len(host.engine.export_tenant("t")["evidence"])
    second = host.runtime.observe_turn("t", "u", **arguments)
    assert first["episode_id"] == second["episode_id"]
    assert second["already_observed"] is True
    assert len(host.episodes()) == 1
    assert len(host.engine.export_tenant("t")["evidence"]) == source_count


def test_erased_host_observation_identity_blocks_transcript_resurrection(tmp_path):
    host = LocalHost(tmp_path)
    arguments = dict(session_id="session", user_text="erase this request",
                     assistant_text="erase this response", observation_id="codex:erased")
    first = host.runtime.observe_turn("t", "u", **arguments)
    cid = host.episodes()[0]["source_cids"][0]
    host.runtime.erase("t", cid)
    count = len(host.engine.export_tenant("t")["evidence"])
    replay = host.runtime.observe_turn("t", "u", **arguments)
    assert replay["episode_id"] == first["episode_id"]
    assert replay["erased"] is True
    assert len(host.episodes()) == 1
    assert host.episodes()[0]["status"] == "erased"
    assert len(host.engine.export_tenant("t")["evidence"]) == count


def test_host_observation_identity_includes_user_and_session(tmp_path):
    host = LocalHost(tmp_path)
    results = [host.runtime.observe_turn("t", user, session, "request", "response",
                                       observation_id="codex:shared")
               for user, session in (("u", "first"), ("u", "second"), ("other", "first"))]
    assert len({row["episode_id"] for row in results}) == 3


def test_stop_drains_all_missed_completed_turns_in_order(tmp_path):
    host = LocalHost(tmp_path)
    transcript = write_transcript(tmp_path, [
        ("one", "first request", [], "first answer"),
        ("two", "second request", [], "second answer"),
        ("three", "still running", [], None),
    ])
    host.event("Stop", transcript_path=str(transcript))
    host.event("Stop", transcript_path=str(transcript))
    assert [row["user_text"] for row in host.episodes()] == ["first request", "second request"]
    assert all(not row["receipt_ids"] for row in host.episodes())


def test_failed_completion_survives_next_prompt_and_recovers_once(tmp_path):
    host = LocalHost(tmp_path)
    transcript = write_transcript(tmp_path, [("one", "first request", [], "first answer")])
    host.event("UserPromptSubmit", turn_id="one", prompt="first request")
    host.fail_after_observe = True
    with pytest.raises(OSError):
        host.event("Stop", transcript_path=str(transcript))
    host.event("UserPromptSubmit", turn_id="two", prompt="second request")
    write_transcript(tmp_path, [
        ("one", "first request", [], "first answer"),
        ("two", "second request", [], "second answer"),
    ])
    host.event("Stop", transcript_path=str(transcript))
    assert [row["user_text"] for row in host.episodes()] == ["first request", "second request"]
    assert all(len(row["receipt_ids"]) == 1 for row in host.episodes())


def test_worker_recovery_drains_more_than_one_batch_without_recapturing(tmp_path):
    host = LocalHost(tmp_path)
    transcript = write_transcript(tmp_path, [(str(i), f"request {i}", [], f"answer {i}") for i in range(11)])
    host.event("UserPromptSubmit", turn_id="10", prompt="request 10", transcript_path=str(transcript))
    first = host.adapter.recover_completed()
    second = host.adapter.recover_completed()
    third = host.adapter.recover_completed()
    assert [first["captured_turns"], second["captured_turns"], third["captured_turns"]] == [8, 3, 0]
    assert len(host.episodes()) == 11


def test_verified_command_metadata_preserves_check_and_execution_identity(tmp_path):
    from mnemosyne.hosts.codex import _tool_event

    first = _tool_event("shell", {"exit_code": 0, "output": "2 passed in 0.1s"},
                        command=["python", "-m", "pytest", "-q"], cwd="/work",
                        tool_id="first", arguments={"command": "python -m pytest -q"})
    second = _tool_event("shell", {"exit_code": 0, "output": "2 passed in 0.1s"},
                         command=["python", "-m", "pytest", "-q"], cwd="/work", tool_id="second")
    assert first["check_id"] == second["check_id"]
    assert first["call_id"] != second["call_id"]
    assert first["cwd"] == "/work"
    assert first["arguments"] == {"command": "python -m pytest -q"}
    assert first["passed"] == 2


def test_explicit_verifier_target_scope_is_preserved_without_inference():
    from mnemosyne.hosts.codex import _tool_event

    scoped = _tool_event("validator", {"verdict": True, "target_ids": ["artifact"],
                                       "outcome_scope": "task", "final": True}, tool_id="call")
    assert scoped["target_ids"] == ["artifact"]
    assert scoped["outcome_scope"] == "task" and scoped["final"] is True
    unscoped = _tool_event("validator", {"verdict": True}, tool_id="other")
    assert "target_ids" not in unscoped
    assert "outcome_scope" not in unscoped


def test_legacy_erased_turn_is_not_recreated_by_transcript_backfill(tmp_path):
    host = LocalHost(tmp_path)
    original = host.runtime.observe_turn("t", "u", "session", "erased request", "erased answer")
    host.runtime.erase("t", host.episodes()[0]["source_cids"][0])
    transcript = write_transcript(tmp_path, [("old", "erased request", [], "erased answer")])
    rows = [json.loads(line) for line in transcript.read_text().splitlines()]
    for row in rows:
        row["timestamp"] = "2000-01-01T00:00:00Z"
    transcript.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    host.event("Stop", transcript_path=str(transcript))
    assert [row["id"] for row in host.episodes()] == [original["episode_id"]]
    assert host.episodes()[0]["status"] == "erased"
    state = json.loads(next((tmp_path / "state").glob("session-*.json")).read_text())
    assert state["skipped_legacy_turns"] == {"old": "unidentifiable_before_capture_boundary"}


def test_profile_feedback_retries_failure_and_marks_only_success(tmp_path):
    host = LocalHost(tmp_path)
    calls = []
    def feedback(episode_id):
        calls.append(episode_id)
        if len(calls) == 1:
            raise OSError("profile persistence failed")
    arguments = dict(session_id="s", user_text="request", assistant_text="answer",
                     observation_id="codex:profile-retry", feedback=feedback)
    with pytest.raises(OSError, match="profile persistence"):
        observe_completed_turn(host.runtime, "t", "u", **arguments)
    assert not host.runtime.writer.read("t")["policy"].get("host_feedback_done")
    result = observe_completed_turn(host.runtime, "t", "u", **arguments)
    observe_completed_turn(host.runtime, "t", "u", **arguments)
    assert calls == [result["episode_id"], result["episode_id"]]
    assert host.runtime.writer.read("t")["policy"]["host_feedback_done"] == {result["episode_id"]: True}
    assert len(host.episodes()) == 1


def test_session_end_is_preserved_until_all_recovery_batches_finish(tmp_path):
    host = LocalHost(tmp_path)
    transcript = write_transcript(tmp_path, [(str(i), f"request {i}", [], f"answer {i}") for i in range(11)])
    host.event("SessionEnd", transcript_path=str(transcript))
    host.adapter.recover_completed()
    assert len(host.episodes()) == 11
    assert {row["status"] for row in host.episodes()} == {"unknown"}


def test_worker_ignores_unprepared_history_before_capture_started(tmp_path):
    host = LocalHost(tmp_path)
    host.event("UserPromptSubmit", turn_id="new", prompt="new request")
    transcript = write_transcript(tmp_path, [
        ("old", "unprepared historical request", [], "historical answer"),
        ("new", "new request", [], "new answer"),
    ])
    rows = [json.loads(line) for line in transcript.read_text().splitlines()]
    for row in rows:
        if row.get("payload", {}).get("turn_id") == "old":
            row["timestamp"] = "2000-01-01T00:00:00Z"
    transcript.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    host.event("Stop", transcript_path=str(transcript))
    assert [row["user_text"] for row in host.episodes()] == ["new request"]


def test_tool_event_redacts_structured_secrets_without_breaking_quoted_commands():
    from mnemosyne.hosts.codex import _tool_event

    command = 'echo "API_KEY=abcdefgh12345678"'
    event = _tool_event("shell", {"exit_code": 0, "output": "ok"}, command=command,
                        arguments={"command": command, "password": "hunter2hunter2hunter2",
                                   "sk-abcdefghijklmnop": 1})
    assert event["arguments"] == {"command": 'echo "API_KEY=[REDACTED]"', "password": "[REDACTED]",
                                  "[REDACTED]": 1}
