from copy import deepcopy
import subprocess
import sys

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.environment_capture import capture_failed_python_environment
from mnemosyne.experience.environment_experiments import (
    MAX_MISSES, environment_retry_at, environment_retry_pending, run_environment_experiment,
)
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.experience.signals import reprocessed_episode, reward, tool_signals
from mnemosyne.experience.strategy_roles import abstract_score, trace_roles
from mnemosyne.hosts.codex import _tool_event


def test_partial_failure_is_failure_but_retains_progress_and_overrides_success_envelope():
    for event in ({"passed": 9, "failed": 1}, {"passed": 9, "failed": 1, "verdict": True}):
        signals = tool_signals([event])
        assert signals[0]["value"] == -1
        assert signals[0]["pass_fraction"] == .9
        assert signals[0]["progress"] == .8
        assert reward(signals) == -1
    assert reward(tool_signals([
        {"check_id": "unit", "passed": 100, "failed": 0},
        {"check_id": "integration", "passed": 9, "failed": 1},
    ])) == -1
    assert reward(tool_signals([
        {"check_id": "unit", "passed": 9, "failed": 1},
        {"check_id": "unit", "passed": 10, "failed": 0},
    ])) == 1


def test_legacy_partial_success_is_replaced_not_retained_as_manual_feedback():
    event = _tool_event("exec_command", {"exit_code": 1, "output": "9 passed, 1 failed in 1s"},
                        command="pytest test_example.py", tool_id="old")
    old_signal = {**tool_signals([event])[0], "value": .8}
    for field in ("progress", "pass_fraction", "passed", "failed"):
        old_signal.pop(field)
    before = {"status": "resolved", "outcome_version": 2, "event_parser_version": 2,
              "tool_events": [event], "signals": [old_signal], "prediction": .5,
              "reward": .8, "receipt_ids": []}
    after = reprocessed_episode(before, {}, {})
    assert after["outcome_version"] == 3 and after["reward"] == -1
    assert len(after["signals"]) == 1
    assert after["signals"][0]["progress"] == .8
    assert before["reward"] == .8
    assert reprocessed_episode(after, {}, {}) == after


def _workflow():
    return [{"name": "read_file", "source": "tool", "arguments": {"path": "a.py"}, "output": "source"},
            {"name": "apply_patch", "source": "tool", "arguments": {"patch": "repair a.py"}, "output": "applied"},
            {"name": "shell", "source": "tool", "command": "pytest test_a.py", "output": "9 passed, 1 failed", "passed": 9, "failed": 1}]


def test_workflow_ignores_only_safe_context_and_keeps_repair_cycles():
    events = _workflow()
    events.insert(1, {"name": "shell", "source": "tool", "command": "pwd", "output": "/work", "exit_code": 0})
    stages = trace_roles({"tool_events": events})
    assert [stage["role"] for stage in stages] == ["inspect", "modify", "verify"]
    assert abstract_score({"strategy_contract": {"roles": ["inspect", "modify", "verify"]}}, {"tool_events": events}) == 0
    events += deepcopy(_workflow())
    events[-1].update(passed=10, failed=0)
    assert [stage["role"] for stage in trace_roles({"tool_events": events})] == ["inspect", "modify", "verify"] * 2
    unsafe = _workflow()
    unsafe.insert(1, {"name": "shell", "source": "tool", "command": "pwd;rm secret", "output": "/work"})
    assert trace_roles({"tool_events": unsafe}) is None
    research = [_workflow()[0], {"name": "checker", "source": "tool", "verdict": True, "output": "claim matches source"}]
    assert [stage["role"] for stage in trace_roles({"tool_events": research})] == ["inspect", "verify"]


@pytest.mark.parametrize("runner", ["pytest", "unittest"])
def test_real_directory_failure_snapshot_and_repair(tmp_path, runner):
    (tmp_path / "calculator.py").write_text("def add(a,b): return a-b\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("")
    (tests / "test_calculator.py").write_text(
        "import unittest\nfrom calculator import add\nclass Tests(unittest.TestCase):\n"
        " def test_sum(self): self.assertEqual(add(3,2),5)\n")
    args = [sys.executable, "-m", runner]
    args += ["-q", "tests/"] if runner == "pytest" else ["discover", "-s", "tests", "-t", "."]
    process = subprocess.run(args, cwd=tmp_path, capture_output=True, text=True)
    event = _tool_event("exec_command", {"exit_code": process.returncode, "output": process.stdout + process.stderr},
                        command=args, tool_id="failure", cwd=str(tmp_path))
    assert event["runner"] == runner and event["failed"] == 1
    environment = capture_failed_python_environment(event)
    assert environment and environment["tests"] == ["tests/test_calculator.py"]
    assert environment["original_failed_tests"]
    result = run_environment_experiment(environment, {"id": "fix", "files": {"calculator.py": "def add(a,b): return a+b\n"}})
    assert result["status"] == "improved", result
    assert result["live_task_outcome"] is False


def test_recovered_episode_still_generates_experiment_and_retries_failed_alternative():
    env = {"version": 1, "kind": "sqlite", "setup": ["CREATE TABLE counters (n INTEGER)", "INSERT INTO counters VALUES (-1)"],
           "baseline": ["UPDATE counters SET n=n"], "checks": [{"query": "SELECT n FROM counters", "expected_rows": [[0]]}],
           "alternatives": [{"id": "unsuccessful", "statements": ["UPDATE counters SET n=-2"]}]}
    engine = LocalMemoryEngine()
    received = []
    def propose(**payload):
        received.append(payload)
        return {"alternatives": [{"id": "fixed", "statements": ["UPDATE counters SET n=MAX(0,n)"]}]}
    engine._learning_configuration = {"environment_experiment_proposer": propose}
    runtime = LearningRuntime(engine)
    receipt = runtime.prepare_context("t", "u", "s", "fix counter", ["checker"])
    episode = runtime.observe_turn("t", "u", "s", "fix counter", "", receipt_ids=[receipt["receipt_id"]],
        tool_events=[{"name": "checker", "source": "tool", "verdict": False, "output": "negative counter",
                      "check_id": "counter", "experiment_environment": env},
                     {"name": "checker", "source": "tool", "verdict": True, "output": "fixed", "check_id": "counter"}])
    assert runtime.resolve("t", episode["episode_id"])["reward"] == 1
    assert environment_retry_pending(runtime.writer.read("t"))
    runtime.consolidate("t")
    state = runtime.writer.read("t")
    attempted = [row for row in state["policy"]["hypotheses"].values() if row.get("environment_result")]
    assert len(attempted) == 1 and attempted[0]["environment_result"]["status"] == "not_improved"
    assert environment_retry_pending(state)
    runtime.consolidate("t")
    state = runtime.writer.read("t")
    assert received and received[-1]["previous_attempts"][0]["result"]["status"] == "not_improved"
    assert any(row.get("environment_result", {}).get("status") == "improved" for row in state["policy"]["hypotheses"].values())
    assert not environment_retry_pending(state)
    assert len(state["episodes"]) == 1 and not state["credit"]


def test_open_episode_from_an_older_runtime_is_repaired_before_it_earns_credit():
    runtime = LearningRuntime(LocalMemoryEngine())
    receipt = runtime.prepare_context("t", "u", "s", "run the suite")
    key = runtime.observe_turn("t", "u", "s", "run the suite", "", receipt_ids=[receipt["receipt_id"]],
        tool_events=[{"name": "shell", "source": "tool", "command": "pytest", "passed": 9, "failed": 1}])["episode_id"]
    def older(state):
        row = state["episodes"][key]
        row["outcome_version"] = 2
        row["signals"] = [{**row["signals"][0], "value": 0.8}]
    runtime.writer.apply("t", "capture", older)
    resolved = runtime.resolve("t", key)
    assert resolved["reward"] == -1 and resolved["outcome_version"] == 3
    assert [item["value"] for item in resolved["signals"]] == [-1]


def test_failure_without_any_proposal_backs_off_and_stops_asking(monkeypatch):
    from mnemosyne.experience import environment_experiments
    env = {"version": 1, "kind": "sqlite", "setup": ["CREATE TABLE counters (n INTEGER)", "INSERT INTO counters VALUES (-1)"],
           "baseline": ["UPDATE counters SET n=n"], "checks": [{"query": "SELECT n FROM counters", "expected_rows": [[0]]}]}
    engine = LocalMemoryEngine()
    calls = []
    def propose(**payload):
        calls.append(payload)
        return {"alternatives": []}
    engine._learning_configuration = {"environment_experiment_proposer": propose}
    runtime = LearningRuntime(engine)
    clock = [1000.0]
    monkeypatch.setattr(environment_experiments.time, "time", lambda: clock[0])
    receipt = runtime.prepare_context("t", "u", "s", "fix counter", ["checker"])
    runtime.observe_turn("t", "u", "s", "fix counter", "", receipt_ids=[receipt["receipt_id"]],
        tool_events=[{"name": "checker", "source": "tool", "verdict": False, "output": "negative counter",
                      "check_id": "counter", "experiment_environment": env}])
    assert environment_retry_at(runtime.writer.read("t")) == 0
    runtime.consolidate("t")
    assert len(calls) == 1 and environment_retry_at(runtime.writer.read("t")) == 1300
    runtime.consolidate("t")  # not due yet: the provider is not asked again
    assert len(calls) == 1
    for _ in range(MAX_MISSES + 2):
        clock[0] = (environment_retry_at(runtime.writer.read("t")) or clock[0]) + 1
        runtime.consolidate("t")
    state = runtime.writer.read("t")
    assert len(calls) == MAX_MISSES and not environment_retry_pending(state)
    assert not state["policy"].get("hypotheses") and not state["credit"]
