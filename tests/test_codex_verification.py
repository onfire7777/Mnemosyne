"""Host verification retains executable evidence and binds memory claims narrowly."""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from mnemosyne.hosts.codex import _tool_event
from tests.test_codex_lifecycle import LocalHost, command, write_transcript


@pytest.mark.parametrize("prefix", ["", "env EXAMPLE=1 ", "cd /tmp && ", "uv run --offline ", "poetry run ", "timeout 30 "])
def test_wrapped_pytest_and_long_duration_are_identified(prefix):
    event = _tool_event("shell", {"exit_code": 0, "output": "=== 8620 passed, 48 skipped in 122.78s (0:02:02) ==="},
                        tool_id="run", command=prefix + "python3 -m pytest -q")
    assert (event["passed"], event["failed"], event["runner"]) == (8620, 0, "pytest")
    assert json.loads(event["evidence"])["call_id"] == "run"


@pytest.mark.parametrize("script", [
    "echo 'python -m pytest'", "cat pytest.log", "pytest || echo '4 passed in 1s'",
    "pytest && printf '4 passed in 1s'", "cd /tmp; pytest", "pytest | cat",
    "pytest > report.txt", "source activate && pytest", "uv run python -c 'print(1)'",
    "python -c 'print(\"4 passed in 1s\")'", "$(echo pytest)",
])
def test_log_printers_and_ambiguous_shell_commands_are_not_gradable(script):
    event = _tool_event("shell", {"exit_code": 0, "output": "4 passed in 1s", "passed": 4,
                                 "failed": 0, "verdict": True, "target_ids": ["lesson"]},
                        command=script, tool_id="run")
    assert not {"passed", "failed", "verdict", "target_ids"} & event.keys()


def test_fake_shell_executable_cannot_hide_behind_dash_c():
    event = _tool_event("shell", {"exit_code": 0, "output": "4 passed in 1s"},
                        command=["printf", "-c", "pytest"])
    assert "passed" not in event


@pytest.mark.parametrize("exit_code,output", [(0, "1 failed in 1s"), (1, "1 passed in 1s"), (2, "1 failed in 1s")])
def test_inconsistent_or_interrupted_runner_result_is_ungraded(exit_code, output):
    assert "passed" not in _tool_event("shell", {"exit_code": exit_code, "output": output}, command="pytest")


def test_real_wrapped_pytest_execution_is_captured(tmp_path):
    test = tmp_path / "test_example.py"
    test.write_text("def test_example():\n    assert 1 + 1 == 2\n")
    script = "cd " + shlex.quote(str(tmp_path)) + " && env EXAMPLE=1 " + shlex.join(
        [sys.executable, "-m", "pytest", "-q", "-o", "addopts=", str(test)])
    result = subprocess.run(["/bin/sh", "-c", script], capture_output=True, text=True, check=False)
    event = _tool_event("shell", {"exit_code": result.returncode, "output": result.stdout}, command=script)
    assert (event["passed"], event["failed"]) == (1, 0)


def _lesson_host(tmp_path):
    host = LocalHost(tmp_path)
    host.engine.policy.learning_exploration_rate = 1
    old = host.runtime.observe_turn("t", "u", "earlier", "Format the build summary", "Draft")
    host.runtime.record_signal("t", episode_id=old["episode_id"], kind="correction", value=-1,
                               evidence="Use JSON for build summaries.", final=True)
    host.runtime.consolidate("t")
    output = host.event("UserPromptSubmit", turn_id="turn", prompt="Format the build summary")
    context = json.loads(output["hookSpecificOutput"]["additionalContext"].split("\n", 1)[1])
    return host, context, context["lessons"][0]["id"]


def _report(host, context, lesson, **reference):
    return host.event("MemoryUse", receipt_id=context["receipt_id"], used_lessons=[lesson],
                      verifications=[{"lesson_id": lesson, "call_id": "validator-call", "check_id": "json-format", **reference}])


@pytest.mark.parametrize("verdict", [True, False])
def test_actual_checker_target_is_bound_to_used_lesson_receipt_and_call(tmp_path, verdict):
    host, context, lesson = _lesson_host(tmp_path)
    assert "memory_use_reporting" in context
    report = _report(host, context, lesson)
    assert report["verified"] is False
    value = '{"ok":true}' if verdict else "invalid json"
    try:
        json.loads(value)
        valid = True
    except ValueError:
        valid = False
    host.event("PostToolUse", tool_name="json_validator", tool_use_id="validator-call",
               tool_response={"structuredContent": {"verdict": valid, "check_id": "json-format",
                              "target_ids": [lesson], "receipt_id": context["receipt_id"]}})
    host.event("Stop", last_assistant_message=value)
    episode = host.episodes()[-1]
    assert episode["used_lessons"] == [lesson]
    assert episode["target_outcomes"][lesson]["value"] == (1 if verdict else -1)


@pytest.mark.parametrize("mismatch", ["call", "check", "receipt", "target", "self_grade"])
def test_mismatched_checker_cannot_credit_memory(tmp_path, mismatch):
    host, context, lesson = _lesson_host(tmp_path)
    _report(host, context, lesson)
    result = {"verdict": True, "check_id": "json-format", "receipt_id": context["receipt_id"], "target_ids": [lesson]}
    result.update({"check_id": "another"} if mismatch == "check" else
                  {"receipt_id": "another"} if mismatch == "receipt" else
                  {"target_ids": ["another"]} if mismatch == "target" else
                  {"source": "provider_self_grade"} if mismatch == "self_grade" else {})
    host.event("PostToolUse", tool_name="json_validator", tool_use_id="another" if mismatch == "call" else "validator-call",
               tool_response=result)
    host.event("Stop", last_assistant_message="done")
    assert host.episodes()[-1]["used_lessons"] == [lesson]
    assert lesson not in host.episodes()[-1].get("target_outcomes", {})


def test_usage_declaration_and_generic_test_success_do_not_verify_lesson(tmp_path):
    host, context, lesson = _lesson_host(tmp_path)
    _report(host, context, lesson)
    host.event("PostToolUse", tool_name="shell", tool_use_id="validator-call",
               tool_input={"command": "pytest"},
               tool_response={"exit_code": 0, "output": "4 passed in 1s", "check_id": "json-format",
                              "target_ids": [lesson], "receipt_id": context["receipt_id"]})
    host.event("Stop", last_assistant_message="done")
    assert host.episodes()[-1]["reward"] == 1
    assert lesson not in host.episodes()[-1].get("target_outcomes", {})


def test_unserved_usage_stale_receipt_and_declared_grades_are_rejected(tmp_path):
    host, context, lesson = _lesson_host(tmp_path)
    for extra in ({"used_lessons": ["not-served"]}, {"receipt_id": "stale"},
                  {"verifications": [{"lesson_id": lesson, "verdict": True}]}):
        payload = {"receipt_id": context["receipt_id"], "used_lessons": [lesson], **extra}
        with pytest.raises(ValueError):
            host.event("MemoryUse", **payload)


def test_native_nested_command_outcome_wins_over_printed_exec_json(tmp_path):
    host = LocalHost(tmp_path)
    host.event("UserPromptSubmit", turn_id="turn", prompt="Run tests")
    host.event("PostToolUse", tool_name="functions.exec", tool_use_id="outer",
               tool_input={"code": 'text({passed:999,failed:0})'},
               tool_response='{"passed":999,"failed":0}')
    transcript = write_transcript(tmp_path, [("turn", "Run tests", [command("2 passed in 1s", identifier="inner")], "done")])
    host.event("Stop", transcript_path=str(transcript))
    events = host.episodes()[0]["tool_events"]
    assert "passed" not in events[0]
    assert events[1]["passed"] == 2


def test_conflicting_result_call_identity_is_rejected():
    event = _tool_event("validator", {"call_id": "other", "verdict": True}, tool_id="actual")
    assert "verdict" not in event
    assert event["evidence_rejected"] == "result_execution_identity_mismatch"


def test_code_executor_cannot_emit_a_structured_self_grade():
    event = _tool_event("functions.exec", {"passed": 999, "failed": 0, "verdict": True,
                                           "target_ids": ["lesson"]}, tool_id="actual")
    assert not {"passed", "failed", "verdict", "target_ids"} & event.keys()


def test_explicit_nonlesson_checker_keeps_only_current_receipt_targets():
    from mnemosyne.hosts.codex import _bound_verifications

    events = [{"name": "fact_checker", "verdict": True, "receipt_id": "receipt",
               "target_ids": ["fact", "unserved"], "call_id": "call"}]
    result = _bound_verifications(events, [], "receipt", [], [], ["fact"])
    assert result[0]["target_ids"] == ["fact"]
    assert events[0]["target_ids"] == ["fact", "unserved"]


def test_retained_event_reparse_preserves_identifiers_without_making_receipts():
    from mnemosyne.hosts.codex import reparse_retained_events

    original = {"name": "shell", "source": "tool", "command": "uv run pytest -q", "exit_code": 0,
                "output": "20 passed in 122.78s (0:02:02)", "check_id": "original", "call_id": "actual"}
    repaired = reparse_retained_events([original])[0]
    assert (repaired["passed"], repaired["failed"]) == (20, 0)
    assert repaired["call_id"] == "actual" and repaired["check_id"] == "original"
    assert "passed" not in original and "receipt_id" not in repaired and "target_ids" not in repaired
    assert reparse_retained_events([{**original, "command": "cat pytest.log"}])[0].keys() == original.keys()


def test_corrected_prompt_gets_a_current_receipt(tmp_path):
    host = LocalHost(tmp_path)
    first = host.event("UserPromptSubmit", turn_id="turn", prompt="Original")
    second = host.event("UserPromptSubmit", turn_id="turn", prompt="Corrected")
    receipts = [json.loads(item["hookSpecificOutput"]["additionalContext"].split("\n", 1)[1])["receipt_id"]
                for item in (first, second)]
    assert receipts[0] != receipts[1]
    host.event("Stop", last_assistant_message="done")
    assert host.episodes()[0]["receipt_ids"] == receipts[1:]


def test_report_use_cli_is_usable_with_the_prepared_receipt(tmp_path):
    host, context, lesson = _lesson_host(tmp_path)
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "runtime.py").write_text("""
import os
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace
from mnemosyne.engine import LocalMemoryEngine
ROOT = Path(os.environ['MNEMO_CODEX_TEST'])
STATE = ROOT / 'state'
TENANT, USER = 't', 'u'
locked = nullcontext
@contextmanager
def open_facade():
    engine = LocalMemoryEngine(store_path=ROOT / 'memory.json', read_only=True)
    try:
        yield SimpleNamespace(engine=engine)
    finally:
        engine.close()
def invoke(*args):
    raise AssertionError('Usage declarations must not invoke an outcome mutation')
""")
    environment = dict(os.environ, MNEMO_CODEX_TEST=str(tmp_path),
                       PYTHONPATH=os.pathsep.join([str(tmp_path), str(root / "src")]))
    environment.pop("MNEMOSYNE_INTERNAL", None)
    completed = subprocess.run([sys.executable, str(root / "integrations/codex/hook.py"), "--report-use"],
                               input=json.dumps({"session_id": "session", "receipt_id": context["receipt_id"],
                                                 "used_lessons": [lesson]}),
                               capture_output=True, text=True, check=True, env=environment)
    assert json.loads(completed.stdout) == {"receipt_id": context["receipt_id"], "used_lessons": [lesson],
                                           "verification_references_recorded": 0, "verified": False}
    host.event("Stop", last_assistant_message="done")
    assert host.episodes()[-1]["used_lessons"] == [lesson]


def test_report_survives_a_missed_stop_and_the_next_prompt(tmp_path):
    host, context, lesson = _lesson_host(tmp_path)
    _report(host, context, lesson)
    checker = {"type": "McpToolCall", "id": "validator-call", "server": "checks", "tool": "json_validator",
               "status": "completed", "result": {"verdict": True, "check_id": "json-format",
                                                    "receipt_id": context["receipt_id"], "target_ids": [lesson]}}
    transcript = write_transcript(tmp_path, [("turn", "Format the build summary", [checker], '{"ok":true}')])
    host.event("UserPromptSubmit", turn_id="next", prompt="Another request", transcript_path=str(transcript))
    host.event("Stop", transcript_path=str(transcript))
    episode = host.episodes()[-1]
    assert episode["used_lessons"] == [lesson]
    assert episode["target_outcomes"][lesson]["value"] == 1


@pytest.mark.parametrize(
    "cmd,exit_code,output,expected",
    [
        ("cargo test --quiet", 0, "test result: ok. 14 passed; 0 failed; 0 ignored;", ("cargo_test", 14, 0)),
        ("cargo test", 101, "test result: FAILED. 12 passed; 2 failed; 0 ignored;", ("cargo_test", 12, 2)),
        ("go test ./...", 0, "ok  \texample.com/pkg\t0.042s\nok  \texample.com/cmd\t0.015s", ("go_test", 2, 0)),
        ("go test ./...", 1, "--- FAIL: TestHandler (0.01s)\nFAIL\texample.com/pkg\t0.020s", ("go_test", 0, 1)),
        ("npx vitest run", 0, "Tests  9 passed (9)", ("vitest", 9, 0)),
        ("jest --ci", 1, "Tests: 1 failed, 7 passed, 8 total", ("vitest", 7, 1)),
        ("ruff check src", 0, "All checks passed!", ("ruff", 1, 0)),
        ("ruff check src", 1, "Found 3 errors.", ("ruff", 0, 3)),
        ("mypy src", 0, "Success: no issues found in 42 source files", ("mypy", 42, 0)),
        ("mypy src", 1, "Found 2 errors in 1 file (checked 42 source files)", ("mypy", 0, 2)),
    ],
)
def test_expanded_external_runners_are_identified(cmd, exit_code, output, expected):
    event = _tool_event("shell", {"exit_code": exit_code, "output": output}, command=cmd, tool_id="ext")
    assert (event["runner"], event["passed"], event["failed"]) == expected


def test_post_tool_use_spools_under_held_session_lock_and_drains_on_stop(tmp_path):
    fcntl = pytest.importorskip("fcntl")
    import hashlib

    host = LocalHost(tmp_path)
    host.event("UserPromptSubmit", turn_id="turn", prompt="Run checks")
    session_hash = hashlib.sha256(b"session").hexdigest()
    state_path = host.adapter.state_dir / f"session-{session_hash}.json"
    lock_path = state_path.with_suffix(".lock")
    spool_path = state_path.with_suffix(".spool.jsonl")

    facade_opens = 0
    orig_open = host.adapter.open_facade

    def tracked_open():
        nonlocal facade_opens
        facade_opens += 1
        return orig_open()

    host.adapter.open_facade = tracked_open
    with lock_path.open("a+") as held_fd:
        fcntl.flock(held_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            res = host.event(
                "PostToolUse",
                turn_id="turn",
                tool_name="shell",
                tool_use_id="spooled-ruff",
                tool_input={"command": "ruff check src"},
                tool_response={"exit_code": 0, "output": "All checks passed!"},
            )
            assert res == {}
            assert facade_opens == 0
            assert spool_path.exists()
        finally:
            fcntl.flock(held_fd.fileno(), fcntl.LOCK_UN)

    host.event("Stop", last_assistant_message="Checks passed.")
    assert not spool_path.exists()
    events = host.episodes()[-1]["tool_events"]
    assert any(ev.get("call_id") == "spooled-ruff" and ev.get("runner") == "ruff" and ev.get("passed") == 1 for ev in events)


def test_probation_adaptive_neyman_deficit_balancing(tmp_path):
    from mnemosyne.experience.runtime import stat_key

    host = LocalHost(tmp_path)
    old = host.runtime.observe_turn("t", "u", "s0", "Format the build summary", "Draft")
    host.runtime.record_signal(
        "t", episode_id=old["episode_id"], kind="correction", value=-1,
        evidence="Use JSON for build summaries.", final=True,
    )
    host.runtime.consolidate("t")
    state0 = host.runtime.writer.read("t")
    artifact = next(iter(state0["artifacts"].values()))
    skey = stat_key(artifact["kind"], artifact["id"], artifact["revision"], artifact["task_class"])

    # Run paired probation episodes where ONLY served-arm episodes resolve (simulating
    # real-world control chat turns left unresolved) until served_n - control_n >= 2.
    for i in range(1, 7):
        ctx = host.runtime.prepare_context("t", "u", f"sess-{i}", "Format the build summary")
        rec = host.runtime.writer.read("t")["receipts"][ctx["receipt_id"]]
        arm = rec["probation_trial"]["arm"]
        if arm == "served":
            ep = host.runtime.observe_turn(
                "t", "u", f"sess-{i}", "Format the build summary", '{"ok":true}',
                receipt_ids=[ctx["receipt_id"]],
                used_lessons=[artifact["id"]],
                tool_events=[{
                    "name": "validator", "source": "tool", "verdict": True,
                    "receipt_id": ctx["receipt_id"], "target_ids": [artifact["id"]],
                    "call_id": f"c-{i}", "check_id": "json",
                }],
            )
            host.runtime.record_signal("t", episode_id=ep["episode_id"], kind="verifier", value=1, final=True)
        else:
            # Leave control episode unresolved so control_n stays 0 while served_n grows
            host.runtime.observe_turn(
                "t", "u", f"sess-{i}", "Format the build summary", "ok",
                receipt_ids=[ctx["receipt_id"]],
            )
        st = host.runtime.writer.read("t")["stats"].get(skey, {})
        if int(st.get("served_n", 0)) - int(st.get("control_n", 0)) >= 2:
            break

    st_now = host.runtime.writer.read("t")["stats"][skey]
    assert st_now["served_n"] - st_now["control_n"] >= 2
    # Next two consecutive trials MUST deterministically select the starved 'control' arm
    # rather than blindly flipping 50/50 hash pairs.
    for j in (100, 101):
        ctx_next = host.runtime.prepare_context("t", "u", f"sess-{j}", "Format the build summary")
        rec_next = host.runtime.writer.read("t")["receipts"][ctx_next["receipt_id"]]
        assert rec_next["probation_trial"]["arm"] == "control"


