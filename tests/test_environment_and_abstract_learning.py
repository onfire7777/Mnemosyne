from copy import deepcopy

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.environment_experiments import run_environment_experiment, valid_alternative
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.experience.sleep import activation_supported
from mnemosyne.experience.strategies import propose_strategies, validated_strategy
from mnemosyne.experience.strategy_trials import strategy_trial_stats


def sqlite_environment():
    return {"version": 1, "kind": "sqlite", "setup": ["CREATE TABLE counts (value INTEGER)", "INSERT INTO counts VALUES (-3)"],
            "baseline": ["UPDATE counts SET value=value"],
            "checks": [{"query": "SELECT value FROM counts", "expected_rows": [[0]]}],
            "alternatives": [{"id": "clamp", "statements": ["UPDATE counts SET value=MAX(0,value)"]}]}


def test_real_sqlite_baseline_and_alternative_execute_in_separate_environments():
    environment = sqlite_environment()
    result = run_environment_experiment(environment, environment["alternatives"][0])
    assert result["status"] == "improved"
    assert result["baseline"]["failed"] == 1
    assert result["candidate"]["passed"] == 1
    assert result["live_task_outcome"] is False
    forbidden = {"id": "escape", "statements": ["ATTACH DATABASE '/tmp/forbidden.db' AS host"]}
    result = run_environment_experiment(environment, forbidden)
    assert result["status"] == "not_improved"
    assert "not authorized" in result["candidate"]["error"]
    assert not valid_alternative(environment, {**forbidden, "checks": []})


def test_real_python_alternative_preserves_external_tests():
    environment = {"version": 1, "kind": "python", "files": {
        "calculator.py": "def add(a,b): return a-b\n",
        "test_calculator.py": "import unittest\nfrom calculator import add\nclass Tests(unittest.TestCase):\n def test_sum(self): self.assertEqual(add(3,2),5)\n"}}
    alternative = {"id": "add", "files": {"calculator.py": "def add(a,b): return a+b\n"}}
    result = run_environment_experiment(environment, alternative)
    if result["status"] == "inconclusive":
        pytest.skip(str(result))
    assert result["status"] == "improved"
    assert not valid_alternative(environment, {"id": "cheat", "files": {"test_calculator.py": ""}})


def record(runtime, session, query, events, tools=("shell", "apply_patch")):
    receipt = runtime.prepare_context("t", "u", session, query, list(tools), workspace="/work")
    row = runtime.observe_turn("t", "u", session, query, "", receipt_ids=[receipt["receipt_id"]], tool_events=events)
    runtime.resolve("t", row["episode_id"])
    return row


def workflow(target):
    return [{"name": "shell", "source": "tool", "command": f"cat {target}.py", "output": "source", "cwd": "/work"},
            {"name": "apply_patch", "source": "tool", "arguments": {"patch": f"repair {target}.py"}, "output": "applied"},
            {"name": "shell", "source": "tool", "command": f"pytest test_{target}.py", "cwd": "/work", "verdict": True, "output": "1 passed"}]


def test_abstract_workflow_transfers_different_files_commands_and_extra_inspection():
    runtime = LearningRuntime(LocalMemoryEngine())
    record(runtime, "one", "fix the cache bug", workflow("cache"))
    other = workflow("authentication")
    other.insert(1, {"name": "shell", "source": "tool", "command": "rg token auth.py", "output": "matches", "cwd": "/work"})
    record(runtime, "two", "fix the authentication bug", other)
    state = runtime.writer.read("t")
    proposals = propose_strategies(state)
    abstract = [row for row in proposals if row["strategy_contract"]["kind"] == "observed_conditional_roles"]
    assert len(abstract) == 1
    assert validated_strategy(abstract[0], state["episodes"], state["receipts"])
    runtime.consolidate("t")
    stored = runtime.writer.read("t")["artifacts"][abstract[0]["id"]]
    assert stored["state"] == "probation"
    contexts = [runtime.prepare_context("t", "u", f"new-{i}", "fix the billing bug", ["shell", "apply_patch"], workspace="/new") for i in range(2)]
    assert any(context["procedures"] for context in contexts)
    assert not runtime.prepare_context("t", "u", "missing", "fix the billing bug", ["shell"])["procedures"]
    changed = deepcopy(stored)
    changed["steps"][0] = "invented command"
    assert not validated_strategy(changed, state["episodes"], state["receipts"])


def test_conditional_failure_inspection_repair_verification_is_grounded():
    runtime = LearningRuntime(LocalMemoryEngine())
    for target in ("cache", "authentication"):
        events = [{"name": "shell", "source": "tool", "command": f"pytest test_{target}.py", "cwd": "/work", "verdict": False, "output": "1 failed"}, *workflow(target)]
        events[-1].update(outcome_scope="task", final=True)
        record(runtime, target, f"fix the {target} bug", events)
    abstract = next(row for row in propose_strategies(runtime.writer.read("t"))
                    if row["strategy_contract"]["kind"] == "observed_conditional_roles")
    assert abstract["strategy_contract"]["roles"] == ["reproduce", "inspect", "modify", "verify"]
    assert '"when": "initial_check_failed"' in abstract["steps"][1]


def test_abstract_verification_honors_targeted_failure_and_ignores_host_use_annotations():
    from mnemosyne.experience.signals import verified_target_outcome, tool_signals
    from mnemosyne.experience.strategy_roles import trace_roles
    events = workflow("cache") + [{"name": "memory_use", "source": "host", "claims": []}]
    assert trace_roles({"tool_events": events})
    targeted = {"name": "checker", "source": "tool", "verdict": False, "target_ids": ["strategy"], "output": "incorrect repair"}
    episode = {"tool_events": events, "signals": tool_signals([*events, targeted])}
    artifact = {"id": "strategy", "strategy_contract": {"kind": "observed_conditional_roles", "roles": ["inspect", "modify", "verify"]}}
    assert verified_target_outcome(artifact, episode) == -1


def test_actual_environment_experiment_is_automatically_planned_from_failed_retained_event():
    runtime = LearningRuntime(LocalMemoryEngine())
    environment = sqlite_environment()
    receipt = runtime.prepare_context("t", "u", "db", "fix the counter bug", ["database_checker"])
    captured = runtime.observe_turn("t", "u", "db", "fix the counter bug", "", receipt_ids=[receipt["receipt_id"]],
        tool_events=[{"name": "database_checker", "source": "tool", "verdict": False,
                                      "output": "negative count", "experiment_environment": environment}])
    runtime.resolve("t", captured["episode_id"])
    before = len(runtime.writer.read("t")["episodes"])
    runtime.consolidate("t")
    state = runtime.writer.read("t")
    review = next(row for row in state["policy"]["hypotheses"].values() if row.get("environment_result"))
    assert review["environment_result"]["status"] == "improved"
    assert review["review_complete"] and review["status"] == "inconclusive"
    assert len(state["episodes"]) == before and not state["credit"]


def test_complete_matched_pairs_from_different_tasks_jointly_support_activation():
    runtime = LearningRuntime(LocalMemoryEngine())
    for target in ("cache", "authentication"):
        record(runtime, target, f"fix the {target} bug", workflow(target))
    runtime.consolidate("t")
    artifact = next(row for row in runtime.writer.read("t")["artifacts"].values()
                    if row.get("strategy_contract", {}).get("kind") == "observed_conditional_roles")
    for name in ("alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa", "lambda", "mu"):
        for index in range(2):
            query = f"fix the billing {name} bug"
            context = runtime.prepare_context("t", "u", f"{name}-{index}", query, ["shell", "apply_patch"], workspace="/work")
            served = bool(context["procedures"])
            events = workflow("billing")
            events[-1]["verdict"] = served
            events[-1]["output"] = "1 passed" if served else "1 failed"
            row = runtime.observe_turn("t", "u", f"{name}-{index}", query, "", receipt_ids=[context["receipt_id"]], tool_events=events)
            runtime.resolve("t", row["episode_id"])
    state = runtime.writer.read("t")
    pooled = strategy_trial_stats(state, artifact)
    assert pooled["n"] == 12 and pooled["control_n"] == 12
    assert activation_supported(runtime, state, artifact)
    runtime.consolidate("t")
    assert runtime.writer.read("t")["artifacts"][artifact["id"]]["state"] == "active"
    forged = deepcopy(state)
    for row in forged["episodes"].values():
        if row["user_id"] == "u" and row["session_id"].startswith("alpha"):
            row["user_id"] = "someone-else"
    assert strategy_trial_stats(forged, artifact)["n"] == 11


def test_failed_pytest_snapshot_generates_actual_isolated_repair_experiment(tmp_path):
    import subprocess
    import sys
    from mnemosyne.experience.environment_capture import capture_failed_python_environment
    from mnemosyne.hosts.codex import _tool_event

    (tmp_path / "calculator.py").write_text("def add(a,b): return a-b\n")
    (tmp_path / "test_calculator.py").write_text("from calculator import add\ndef test_sum(): assert add(3,2)==5\n")
    process = subprocess.run([sys.executable, "-m", "pytest", "-q", "test_calculator.py"],
                             cwd=tmp_path, capture_output=True, text=True)
    event = _tool_event("exec_command", {"exit_code": process.returncode, "output": process.stdout},
                       tool_id="actual-failure", command=[sys.executable, "-m", "pytest", "-q", "test_calculator.py"], cwd=str(tmp_path))
    environment = capture_failed_python_environment(event)
    assert environment and set(environment["files"]) == {"calculator.py", "test_calculator.py"}
    assert environment["original_failed_tests"] == ["test_calculator.py::test_sum"]
    result = run_environment_experiment(environment, {"id": "repair", "files": {"calculator.py": "def add(a,b): return a+b\n"}})
    assert result["status"] == "improved", result
    assert result["baseline"]["failed_tests"] == ["test_calculator.py::test_sum"]
    assert result["candidate"]["passed"] == 1
    assert (tmp_path / "calculator.py").read_text() == "def add(a,b): return a-b\n"


def test_python_environment_cannot_read_host_files_or_open_network(tmp_path):
    from mnemosyne.experience.environment_experiments import _python_variant
    secret = tmp_path / "outside.txt"
    secret.write_text("must remain outside the sandbox")
    source = ("import unittest,socket\nclass Isolation(unittest.TestCase):\n"
              " def test_file(self):\n"
              "  with self.assertRaises(PermissionError): open(" + repr(str(secret)) + ").read()\n"
              " def test_network(self):\n"
              "  with socket.socket() as s:\n"
              "   with self.assertRaises(PermissionError): s.connect(('127.0.0.1',9))\n")
    result = _python_variant({"files": {"test_isolation.py": source}}, {})
    assert result["passed"] == 2 and result["failed"] == 0, result
