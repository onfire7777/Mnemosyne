"""Bounded task reuse and source-grounded workspace parameter induction."""

import json
import subprocess
import sys
from copy import deepcopy

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.candidates import (
    action_occurrence, candidate_score, observed_steps, portable_observed_steps,
    validate_action_template,
)
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.experience.signals import reward, tool_signals, verified_target_outcome
from mnemosyne.experience.sleep import _candidate, common_sequence


def resolved(events):
    signals = tool_signals(events)
    return {"tool_events": events, "signals": signals, "reward": reward(signals)}


def shell(command="pytest tests", cwd="/work/alpha", call_id="routine"):
    return {"name": "shell", "source": "tool", "command": command,
            "cwd": cwd, "call_id": call_id}


def artifact(events):
    return {"id": "routine", "kind": "procedure", "steps": observed_steps(resolved(events))}


def test_task_tools_follow_observed_requirements_and_keep_provenance():
    runtime = LearningRuntime(LocalMemoryEngine())
    first = runtime.prepare_context("t", "u", "first", "Run the smoke tests", ["shell", "read"])
    recorded = runtime.observe_turn(
        "t", "u", "first", "Run the smoke tests", "", receipt_ids=[first["receipt_id"]],
        tool_events=[{**shell(), "verdict": True}],
    )
    second = runtime.prepare_context("t", "u", "second", "Execute smoke tests.", ["shell", "browser"])
    assert second["task_class"] == first["task_class"]
    receipt = runtime.writer.read("t")["receipts"][second["receipt_id"]]
    assert receipt["task_match"]["matched_episode_id"] == recorded["episode_id"]
    assert set(runtime.episode("t", recorded["episode_id"])["source_cids"]) <= set(receipt["source_cids"])
    no_shell = runtime.prepare_context("t", "u", "missing", "Execute smoke tests.", ["browser"])
    assert no_shell["task_class"] != first["task_class"]
    assert runtime.prepare_context("t", "other", "owner", "Execute smoke tests.", ["shell"])["task_class"] != first["task_class"]


@pytest.mark.parametrize("query", [
    "Run smoke tests without integration tests.", "Run smoke Tests.",
    "Run smoke tests version 2.", "Do not run smoke tests.",
    "Run `smoke tests.`", "Run smoke tests --force.",
])
def test_prose_equivalence_does_not_erase_constraints_or_literals(query):
    runtime = LearningRuntime(LocalMemoryEngine())
    context = runtime.prepare_context("t", "u", "first", "Run smoke tests", ["shell"])
    runtime.observe_turn("t", "u", "first", "Run smoke tests", "",
                         receipt_ids=[context["receipt_id"]], tool_events=[shell()])
    assert runtime.prepare_context("t", "u", "second", query, ["shell"])["task_class"] != context["task_class"]


def test_embedded_routine_needs_its_own_actual_checker():
    routine = artifact([shell()])
    events = [shell("git status", call_id="status"), shell(),
              {"name": "benchmark_verifier", "source": "tool", "verdict": True,
               "call_id": "check", "checked_call_ids": ["routine"]}]
    assert verified_target_outcome(routine, resolved(events)) == 1
    assert candidate_score(routine, resolved(events)) == 1
    for checked in (["status"], ["missing"], ["routine", "routine"], []):
        changed = deepcopy(events)
        changed[-1]["checked_call_ids"] = checked
        assert verified_target_outcome(routine, resolved(changed)) is None
        assert candidate_score(routine, resolved(changed)) is None
    untrusted = deepcopy(events)
    untrusted[-1]["source"] = "assistant"
    assert verified_target_outcome(routine, resolved(untrusted)) is None
    premature = [events[-1], *events[:-1]]
    assert verified_target_outcome(routine, resolved(premature)) is None


def test_multistep_occurrence_preserves_order_and_one_workspace():
    first = shell("ruff check src", call_id="lint")
    second = shell("pytest tests", call_id="test")
    steps, _ = portable_observed_steps(resolved([first, second]))
    routine = {"id": "routine", "kind": "procedure", "steps": steps}
    moved = [{**first, "cwd": "/work/beta"}, {**second, "cwd": "/work/beta"}]
    assert action_occurrence(routine, resolved(moved)) == [0, 1]
    assert action_occurrence(routine, resolved(list(reversed(moved)))) is None
    assert action_occurrence(routine, resolved([moved[0], second])) is None
    assert action_occurrence(routine, resolved([moved[0], {**moved[1], "command": "pytest other_tests"}])) is None


def test_literal_step_checker_and_operation_verdict_allow_embedded_verification():
    operation = shell()
    routine = artifact([operation])
    before = shell("git status", call_id="status")
    check = {"name": "benchmark_verifier", "source": "tool", "verdict": True,
             "tested_steps": routine["steps"]}
    assert verified_target_outcome(routine, resolved([before, operation, check])) == 1
    check["tested_steps"] = observed_steps(resolved([before]))
    assert verified_target_outcome(routine, resolved([before, operation, check])) is None
    assert verified_target_outcome(routine, resolved([before, {**operation, "passed": 3, "failed": 0}])) == 1


def test_portability_requires_distinct_observed_bindings_and_exact_literals():
    rows = [{**resolved([shell(cwd=root)]), "id": str(index), "created_at": "2026-11-09",
             "tenant_id": "t", "user_id": "u", "source_cids": [str(index)]}
            for index, root in enumerate(["/work/alpha", "/work/beta"])]
    steps = common_sequence([portable_observed_steps(row)[0] for row in rows])
    candidate = _candidate("task", steps, rows)
    assert validate_action_template(candidate, rows)
    changed = deepcopy(rows)
    changed[1]["tool_events"][0]["cwd"] = "/work/alpha"
    assert not validate_action_template(candidate, changed)
    changed = deepcopy(rows)
    changed[1]["tool_events"][0]["command"] += " --force"
    assert not validate_action_template(candidate, changed)
    tied = resolved([shell("cat /work/alpha/private", cwd="/work/alpha")])
    assert portable_observed_steps(tied)[0] == observed_steps(tied)


def test_host_argument_copy_binds_only_the_explicit_working_directory():
    original = {**shell(), "arguments": {"cmd": "pytest tests", "workdir": "/work/alpha"}}
    moved = {**shell(cwd="/work/beta"), "arguments": {"cmd": "pytest tests", "workdir": "/work/beta"}}
    assert portable_observed_steps(resolved([original]))[0] == portable_observed_steps(resolved([moved]))[0]
    changed = deepcopy(moved)
    changed["arguments"]["cmd"] = "pytest tests --force"
    assert portable_observed_steps(resolved([original]))[0] != portable_observed_steps(resolved([changed]))[0]


def test_portable_procedure_reuses_real_actions_in_broader_workflow_and_erases(tmp_path):
    engine = LocalMemoryEngine(store_path=tmp_path / "memory.json")
    runtime = LearningRuntime(engine)
    command = [sys.executable, "-c", "from pathlib import Path; print(Path('value.txt').read_text().strip())"]

    def run(root, call_id="routine"):
        root.mkdir(exist_ok=True)
        (root / "value.txt").write_text("42")
        result = subprocess.run(command, cwd=root, capture_output=True, text=True)
        event = {**shell(command, str(root), call_id), "output": result.stdout}
        check = {"name": "benchmark_verifier", "source": "tool", "call_id": "check-" + call_id,
                 "checked_call_ids": [call_id], "verdict": result.returncode == 0 and result.stdout.strip() == "42"}
        return event, check

    for index, query in enumerate(["Run the arithmetic smoke check", "Execute arithmetic smoke check."]):
        context = runtime.prepare_context("t", "u", str(index), query, ["shell", "read"])
        captured = runtime.observe_turn("t", "u", str(index), query, "",
                                        receipt_ids=[context["receipt_id"]],
                                        tool_events=list(run(tmp_path / str(index))))
        runtime.resolve("t", captured["episode_id"])
    runtime.consolidate("t")
    procedures = [item for item in runtime.writer.read("t")["artifacts"].values() if item.get("action_template")]
    assert len(procedures) == 1
    procedure = procedures[0]
    assert procedure["state"] == "probation" and procedure["gate_passed"]
    assert procedure["needs"] == ["shell"]
    assert json.loads(procedure["steps"][0])["cwd"] == {"variable": "workspace"}
    assert len(procedure["source_quotes"]) == 2
    for quote in procedure["source_quotes"]:
        assert quote["quote"] in engine.get_evidence("t", quote["cid"]).content
    from mnemosyne.experience.guards import LearningGuardError, validate
    before = runtime.writer.read("t")
    forged = deepcopy(before)
    forged["artifacts"][procedure["id"]]["action_template"]["bindings"][0]["value"] = "/invented"
    with pytest.raises(LearningGuardError, match="servable steps"):
        validate(before, forged, "capture", source_lookup=lambda cid: engine.get_evidence("t", cid))
    engine.close()

    engine = LocalMemoryEngine(store_path=tmp_path / "memory.json")
    runtime = LearningRuntime(engine)
    query = "Please run arithmetic smoke check!"
    offered = None
    for index in range(6):
        context = runtime.prepare_context("t", "u", "reuse-" + str(index), query, ["shell", "browser"])
        if any(item["id"] == procedure["id"] for item in context["procedures"]):
            offered = context
            break
    assert offered is not None
    event, check = run(tmp_path / "new")
    setup_command = [sys.executable, "-c", "print('setup')"]
    setup = subprocess.run(setup_command, cwd=tmp_path / "new", capture_output=True, text=True)
    assert setup.returncode == 0
    captured = runtime.observe_turn(
        "t", "u", "reuse-" + str(index), query, "", receipt_ids=[offered["receipt_id"]],
        tool_events=[{**shell(setup_command, str(tmp_path / "new"), "setup"), "output": setup.stdout}, event, check],
        used_skills=[procedure["id"]],
    )
    runtime.resolve("t", captured["episode_id"])
    episode = runtime.episode("t", captured["episode_id"])
    assert episode["target_outcomes"][procedure["id"]]["value"] == 1
    other = runtime.prepare_context("t", "other", "other", query, ["shell"])
    assert not other["procedures"]
    runtime.erase("t", procedure["source_cids"][0])
    assert all(item["id"] != procedure["id"] for i in range(3)
               for item in runtime.prepare_context("t", "u", "erased-" + str(i), query, ["shell"])["procedures"])
    engine.close()
