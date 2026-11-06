from __future__ import annotations

import json
import sys

import pytest

from eval.learning.families import REQUIRED, generate, verify_family
from eval.learning.faults import run_injected_fault
from eval.learning.model_agent import CommandModelAgent, ModelConfiguration, PROMPT
from eval.learning.probes import run_specialized_probe
from eval.learning.runner import build_report
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.guards import GUARD_CLASSES
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.experience.writer import LearningWriter


@pytest.mark.parametrize("family", range(1, 27))
def test_each_specialized_fixture_executes_and_reports_real_missing_prerequisites(
    family,
):
    runtime = LearningRuntime(LocalMemoryEngine())
    result = run_specialized_probe(runtime, family, 13, budget=4)
    assert result["probe"] == "specialized-v1"
    assert result["operations"]  # No empty status-only implementation.
    assert not result["verification_reason"].startswith(
        ("TypeError:", "KeyError:", "AttributeError:")
    )
    if result["supported"]:
        assert set(REQUIRED[family]) <= result["evidence"].keys()
        assert result["verified"] == verify_family(family, result["evidence"]).passed
    else:
        assert result["verification_reason"]
        assert not result["verified"]


def test_holdout_failures_do_not_reveal_corrective_actions_to_learning():
    runtime = LearningRuntime(LocalMemoryEngine())
    result = run_specialized_probe(runtime, 2, 13, budget=8)
    state = runtime.writer.read("probe-f2-13-learning_on")
    heldout = [row for row in result["rows"] if row["phase"] == "test"]
    assert heldout
    for row in heldout:
        episode = state["episodes"][row["episode_id"]]
        assert not any(
            "expected_steps" in event or "corrective_steps" in event
            for event in episode["tool_events"]
        )
        performed = [
            event["name"]
            for event in episode["tool_events"]
            if event["name"] != "benchmark_verifier"
        ]
        assert performed == row["action"].split(" -> ")
    expected = sum(row["success"] for row in result["rows"][4:]) / 4
    assert result["evidence"]["ordered_steps_verified"] == expected


def test_real_read_strengthening_fault_is_detected_by_f23(monkeypatch):
    engine = LocalMemoryEngine()
    original = engine._record_retrieval_access

    def corrupt(hits):
        value = original(hits)
        for hit in hits:
            evidence = engine.get_evidence(hit.tenant_id, hit.id)
            if evidence is not None:
                evidence.metadata.setdefault("lifecycle", {})["salience"] = 0.9
                engine.update_evidence_metadata(
                    hit.tenant_id, hit.id, evidence.metadata
                )
        return value

    monkeypatch.setattr(engine, "_record_retrieval_access", corrupt)
    result = run_specialized_probe(LearningRuntime(engine), 23, 13, budget=4)
    assert result["supported"]
    assert result["evidence"]["salience_delta"] != 0
    assert not result["verified"]


@pytest.mark.parametrize("code", GUARD_CLASSES)
def test_test_only_fault_fixture_reaches_writer_and_independent_family(
    code, monkeypatch
):
    from tests.fault_injection.learning import baseline, corrupt, source_lookup

    before = baseline()
    after = corrupt(code, before)
    engine = LocalMemoryEngine()
    engine._learning_data = {"t": before}  # Deliberately isolated fault fixture only.
    monkeypatch.setattr(engine, "get_evidence", lambda tenant, cid: source_lookup(cid))

    def mutate(state):
        state.clear()
        state.update(after)

    result = run_injected_fault(
        LearningWriter(engine),
        "t",
        mutate,
        family=23,
        clean_evidence={key: 0 for key in REQUIRED[23]},
    )
    assert result["caught_guard"] == code
    assert result["recorded_guards"] == [code]
    assert result["contained"] and result["family_rejected"]


def test_model_track_uses_existing_transport_without_sending_oracle(tmp_path):
    request = tmp_path / "request.json"
    script = (
        "import json,sys,pathlib; p=json.load(sys.stdin); "
        f"pathlib.Path({str(request)!r}).write_text(json.dumps(p)); "
        "print(json.dumps({'action':p['request']['choices'][0]}))"
    )
    config = ModelConfiguration(
        (sys.executable, "-c", script), "fixed-test-model", 0.0, 29
    )
    agent = CommandModelAgent(config)
    task = generate(2, 17)[0]
    action, skills, lessons = agent.act(task, {"hits": []})
    payload = json.loads(request.read_text())
    assert set(payload["request"]) == {"query", "choices", "task_class"}
    assert (
        payload["model"] == "fixed-test-model"
        and payload["temperature"] == 0
        and payload["seed"] == 29
    )
    assert payload["system"] == PROMPT
    assert action in task.choices and skills == lessons == []
    assert agent.calls[0]["track"] == "model"


def test_model_cannot_claim_unserved_artifact_usage():
    script = (
        "import json; print(json.dumps({'action':'a','used_skills':['not-served']}))"
    )
    agent = CommandModelAgent(
        ModelConfiguration((sys.executable, "-c", script), "fixed", seed=1)
    )
    with pytest.raises(ValueError, match="actually served"):
        agent.act(generate(1, 3)[0], {"hits": []})


def test_specialized_subset_never_claims_complete_official_success():
    report = build_report(
        lambda path: LocalMemoryEngine(),
        family_ids=[23],
        arms=["learning_on"],
        episodes=4,
    )
    assert report["classification"] == "diagnostic"
    assert not report["complete"] and not report["passed"]
    assert all(row["probe"] == "specialized-v1" for row in report["results"])


def test_sealed_programmatic_run_reserves_before_engine_and_failed_run_consumes_sha(
    tmp_path, monkeypatch
):
    from eval.learning import runner

    monkeypatch.setattr(
        runner.subprocess,
        "check_output",
        lambda argv, **kwargs: "a" * 40 if "rev-parse" in argv else "",
    )
    calls = []

    def failed_engine(path):
        calls.append(path)
        raise RuntimeError("injected backend failure")

    with pytest.raises(RuntimeError, match="backend failure"):
        build_report(
            failed_engine,
            split="sealed",
            family_ids=[23],
            arms=["learning_on"],
            episodes=4,
            sealed_registry=tmp_path,
        )
    assert len(calls) == 1
    with pytest.raises(FileExistsError):
        build_report(
            failed_engine,
            split="sealed",
            family_ids=[23],
            arms=["learning_on"],
            episodes=4,
            sealed_registry=tmp_path,
        )
    assert len(calls) == 1


def test_sealed_programmatic_run_rejects_dirty_checkout_before_engine(
    tmp_path, monkeypatch
):
    from eval.learning import runner

    monkeypatch.setattr(
        runner.subprocess,
        "check_output",
        lambda argv, **kwargs: "a" * 40 if "rev-parse" in argv else " M changed.py",
    )
    with pytest.raises(ValueError, match="clean committed"):
        build_report(
            lambda _: pytest.fail("must reject before opening engine"),
            split="sealed",
            family_ids=[23],
            arms=["learning_on"],
            episodes=4,
            sealed_registry=tmp_path,
        )
    assert not list(tmp_path.iterdir())


def test_ordered_procedure_probe_rejects_executed_wrong_order():
    class WrongOrderAgent:
        def act(self, task, context):
            return "verify -> normalize -> inspect", [], []

    runtime = LearningRuntime(LocalMemoryEngine())
    result = run_specialized_probe(runtime, 2, 13, budget=4, agent=WrongOrderAgent())
    assert result["supported"] and not result["verified"]
    assert result["evidence"]["ordered_steps_verified"] == 0
    assert all(
        row["action"] == "verify -> normalize -> inspect" for row in result["rows"]
    )


def test_pattern_separation_records_real_isolated_reference_runs():
    result = run_specialized_probe(
        LearningRuntime(LocalMemoryEngine()), 9, 13, budget=8
    )
    references = [
        op
        for op in result["operations"]
        if op["operation"] == "isolated_task_reference"
    ]
    assert {op["feature"] for op in references} == {"hot", "cold"}
    assert all(
        any(row["phase"] == "test" and row["episode_id"] for row in op["rows"])
        for op in references
    )


def test_scripted_policy_can_apply_served_chunk_prefix_without_gold_lookup():
    from eval.learning.families import Task
    from eval.learning.simulator import ScriptedAgent

    task = Task(
        22,
        1,
        "Process the new record",
        "transfer",
        ("inspect -> normalize -> check", "check -> normalize -> inspect"),
        "private-unseen-oracle",
    )
    action, used, _ = ScriptedAgent(5).act(
        task, {"chunks": [{"id": "chunk", "steps": ["inspect", "normalize"]}]}
    )
    assert action == "inspect -> normalize -> check" and used == ["chunk"]


def test_import_probe_does_not_pass_from_two_empty_posteriors():
    result = run_specialized_probe(
        LearningRuntime(LocalMemoryEngine()), 25, 13, budget=4
    )
    assert not result["supported"] and not result["verified"]
    assert "twenty real selections" in result["verification_reason"]


def test_safety_ablation_uses_real_calibration_endpoint_instead_of_task_aulc():
    report = build_report(
        lambda _: LocalMemoryEngine(),
        family_ids=[14],
        arms=["learning_on", "without_calibrated_confidence_metacognition"],
        episodes=4,
    )
    assert len(report["comparisons"]) == 1
    comparison = report["comparisons"][0]
    assert comparison["metric"] == "calibration_error"
    assert comparison["direction"] == "lower"
    assert "aulc_lift" not in comparison
    assert not report["passed"]
