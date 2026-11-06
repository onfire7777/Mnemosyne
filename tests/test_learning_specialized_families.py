from __future__ import annotations

import json
import sys
from copy import deepcopy
from contextlib import nullcontext
from functools import partial
from types import SimpleNamespace

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
        "import json,sys; p=json.load(sys.stdin); "
        "print(json.dumps({'action':p['request']['choices'][0],"
        "'used_skills':['not-served']}))"
    )
    agent = CommandModelAgent(
        ModelConfiguration((sys.executable, "-c", script), "fixed", seed=1)
    )
    with pytest.raises(ValueError, match="actually served"):
        agent.act(generate(1, 3)[0], {"hits": []})


def test_model_rejects_action_outside_permitted_choices():
    agent = CommandModelAgent(
        ModelConfiguration(
            (sys.executable, "-c", 'print(\'{"action":"unpermitted"}\')'),
            "fixed",
            seed=1,
        )
    )
    with pytest.raises(ValueError, match="permitted choices"):
        agent.act(generate(1, 3)[0], {})


def test_model_cannot_attribute_a_lesson_as_a_used_skill():
    script = (
        "import json,sys; p=json.load(sys.stdin); "
        "print(json.dumps({'action':p['request']['choices'][0],"
        "'used_skills':['lesson']}))"
    )
    agent = CommandModelAgent(
        ModelConfiguration((sys.executable, "-c", script), "fixed")
    )
    with pytest.raises(ValueError, match="actually served"):
        agent.act(generate(1, 3)[0], {"lessons": [{"id": "lesson"}]})


def test_private_gold_position_is_permuted_and_paired_between_arms():
    from eval.learning.probes import Environment

    class FirstChoiceAgent:
        def __init__(self):
            self.tasks = []

        def act(self, task, context):
            self.tasks.append(task)
            return task.choices[0], [], []

    agents = [FirstChoiceAgent(), FirstChoiceAgent()]
    for agent, arm in zip(agents, ("learning_on", "no_memory"), strict=True):
        runtime = LearningRuntime(LocalMemoryEngine())
        e = Environment(runtime, 2, 11, budget=32, agent=agent, arm=arm)
        with e.clock:
            for index in range(32):
                e.turn(
                    f"Process new record {index}", ["inspect", "normalize", "verify"]
                )
    assert [t.choices for t in agents[0].tasks] == [t.choices for t in agents[1].tasks]
    positions = {t.choices.index(t.expected) for t in agents[0].tasks}
    assert positions == {0, 1, 2, 3}
    assert sum(t.choices[0] == t.expected for t in agents[0].tasks) < 16


def test_forced_demonstrations_do_not_call_model():
    from eval.learning.probes import Environment

    class UnavailableAgent:
        def act(self, task, context):
            pytest.fail("a fixture with an explicit action must not invoke the model")

    e = Environment(
        LearningRuntime(LocalMemoryEngine()), 2, 11, agent=UnavailableAgent()
    )
    with e.clock:
        e.demonstrate(["inspect", "verify"])
    assert len(e.operations) == 3


def test_local_adapter_constrains_usage_to_served_ids(monkeypatch):
    import io
    from eval.learning import ollama_adapter

    requests = []

    def respond(request, timeout):
        requests.append(json.loads(request.data))
        return io.BytesIO(
            json.dumps(
                {
                    "done": True,
                    "done_reason": "stop",
                    "model": "local-test",
                    "message": {
                        "content": json.dumps(
                            {
                                "action": "a",
                                "used_skill_index": 0,
                                "used_lesson_index": -1,
                            }
                        )
                    },
                }
            ).encode()
        )

    monkeypatch.setattr(ollama_adapter, "urlopen", respond)
    answer = ollama_adapter.respond(
        {
            "schema": "mnemosyne.learning-agent.v1",
            "model": "local-test",
            "system": PROMPT,
            "temperature": 0,
            "seed": 11,
            "request": {"choices": ["a", "b"]},
            "memory": {"procedures": [{"id": "served"}]},
        }
    )
    properties = requests[0]["format"]["properties"]
    assert properties["used_skill_index"]["enum"] == [-1, 0]
    assert properties["used_lesson_index"]["enum"] == [-1]
    assert answer["used_skills"] == ["served"] and answer["used_lessons"] == []
    assert answer["provider_metadata"]["model"] == "local-test"


def test_common_pretraining_is_matched_and_excluded_from_evaluation_rows():
    from eval.learning.probes import Environment

    environments = []
    for arm in ("learning_on", "memory_frozen", "no_memory"):
        runtime = LearningRuntime(LocalMemoryEngine())
        e = Environment(
            runtime, 11, 11, budget=8, arm=arm, protocol="common-pretraining-v2"
        )
        if arm != "learning_on":
            runtime.pause(e.tenant)
        with e.clock:
            e.train(["inspect", "verify"], count=8)
            assert not e.rows
            assert len(e.setup_rows) == 10
            assert runtime.status(e.tenant)["enabled"] is (arm == "learning_on")
            e.turn("heldout record", ["inspect", "verify"], phase="test")
        assert len(e.rows) == 1
        assert e.rows[0]["decision_policy"] == "heldout_competence"
        environments.append(e)
    workloads = [
        [(r["query"], r["action"], r["expected"]) for r in e.setup_rows]
        for e in environments
    ]
    assert workloads[0] == workloads[1] == workloads[2]


def test_competence_policy_follows_memory_and_does_not_get_an_oracle_fallback():
    from eval.learning.simulator import ScriptedAgent

    task = generate(2, 17)[0]
    context = {"procedures": [{"id": "p", "steps": [task.expected]}]}
    agent = ScriptedAgent(31)
    assert all(
        agent.act(task, context, explore=False)[0] == task.expected for _ in range(100)
    )
    no_memory = {agent.act(task, {}, explore=False)[0] for _ in range(40)}
    assert len(no_memory) > 1


def test_common_pretraining_cannot_consume_a_sealed_reservation(tmp_path):
    with pytest.raises(ValueError, match="development-only"):
        build_report(
            lambda _: pytest.fail("must reject before constructing engine"),
            split="sealed",
            protocol="common-pretraining-v2",
            sealed_registry=tmp_path,
        )
    assert not list(tmp_path.iterdir())


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


def test_parallel_report_preserves_seed_pairing_and_checkpoints(tmp_path):
    from eval.learning.runner import _make_engine, load_manifest

    report = build_report(
        partial(_make_engine, backend="local", in_memory=True),
        family_ids=[23],
        arms=["learning_on"],
        episodes=4,
        workers=2,
        checkpoint_dir=tmp_path,
    )
    expected_seeds = load_manifest()["splits"]["dev"]["seeds"]
    assert [r["seed"] for r in report["results"]] == expected_seeds
    assert len(list(tmp_path.glob("*.json"))) == len(expected_seeds)
    assert all(
        json.loads(path.read_text())["verified"] for path in tmp_path.glob("*.json")
    )
    assert report["configuration"]["workers"] == 2
    assert report["classification"] == "diagnostic" and not report["passed"]


@pytest.mark.parametrize(
    "option", [{"arms": []}, {"family_ids": []}, {"family_ids": [23, 23]}]
)
def test_report_rejects_empty_or_duplicate_workloads(option):
    with pytest.raises(ValueError):
        build_report(
            lambda _: pytest.fail("invalid workload must not create an engine"),
            **option,
        )


@pytest.mark.parametrize("corrupt", [False, True])
def test_extinction_probe_independently_rejects_resurrection(corrupt):
    from eval.learning.probes import _renewal

    class RenewalEnvironment:
        budget = 4
        evidence = {}

        def train(self, *args, **kwargs):
            return [{"id": "retired-procedure"}]

        def turn(self, *args, **kwargs):
            return None

        def sleep(self):
            return None

        def state(self):
            return {"artifacts": {"retired-procedure": {"state": "retired"}}}

        def context(self, *args):
            return {"procedures": [{"id": "retired-procedure"}] if corrupt else []}

        def require(self, condition, reason):
            assert condition, reason

    environment = RenewalEnvironment()
    _renewal(environment)
    environment.evidence["guard_detections"] = 0
    assert verify_family(19, environment.evidence).passed is not corrupt


@pytest.mark.parametrize("mutation", [None, "prediction", "demotion", "ranking"])
def test_hindsight_probe_checks_independent_semantic_corruptions(mutation):
    from eval.learning.probes import _hindsight

    before = {
        "receipts": {"earlier": {"prediction": 0.9}},
        "artifacts": {"proven": {"state": "active"}},
    }
    after = deepcopy(before)
    if mutation == "prediction":
        after["receipts"]["earlier"]["prediction"] = 0.1
    if mutation == "demotion":
        after["artifacts"]["proven"]["state"] = "retired"
    good, bad = (0.1, 0.9) if mutation == "ranking" else (0.9, 0.1)
    observations = [
        {"episode_id": "success", "prediction": good, "success": True},
        {"episode_id": "failure", "prediction": bad, "success": False},
    ]
    snapshots = iter((before, after))
    environment = SimpleNamespace(
        train=lambda *args, **kwargs: [{"id": "proven"}],
        state=lambda: next(snapshots),
        turn=lambda *args, **kwargs: {"episode_id": "unlucky"},
        runtime=SimpleNamespace(record_signal=lambda *args, **kwargs: None),
        sleep=lambda: None,
        tenant="test",
        rows=observations,
        evidence={},
        require=lambda condition, reason: None if condition else pytest.fail(reason),
    )
    _hindsight(environment)
    environment.evidence["guard_detections"] = 0
    assert verify_family(24, environment.evidence).passed is (mutation is None)


@pytest.mark.parametrize("mutation", [None, "still_live", "served_after_revert"])
def test_revision_probe_rejects_incomplete_semantic_reversion(mutation):
    from eval.learning.probes import ProbeUnavailable, _revision

    candidate = {
        "id": "challenger",
        "parent_revision": "incumbent",
        "state": "probation" if mutation == "still_live" else "retired",
        "ab_trial": {"status": "revert"},
    }
    rows = []
    environment = SimpleNamespace(
        budget=4,
        protocol="specialized-v1",
        rows=rows,
        operations=[],
        evidence={},
        tenant="test",
        runtime=SimpleNamespace(record_signal=lambda *args, **kwargs: None),
        train=lambda *args, **kwargs: [{"id": "incumbent"}],
        demonstrate=lambda *args, **kwargs: None,
        turn=lambda *args, **kwargs: rows.append({}) or {"episode_id": "observed"},
        sleep=lambda: None,
        state=lambda: {"artifacts": {"incumbent": {}, "challenger": candidate}},
        context=lambda *args: {
            "procedures": [candidate] if mutation == "served_after_revert" else []
        },
        require=lambda condition, reason: (
            None if condition else (_ for _ in ()).throw(ProbeUnavailable(reason))
        ),
    )
    if mutation:
        with pytest.raises(ProbeUnavailable):
            _revision(environment)
    else:
        _revision(environment)
        environment.evidence["guard_detections"] = 0
        assert verify_family(4, environment.evidence).passed


@pytest.mark.parametrize("mutation", [None, "slower_schema", "unrelated_promotion"])
def test_schema_probe_measures_matching_schema_promotions(monkeypatch, mutation):
    from eval.learning.probes import ProbeUnavailable, _schema

    monkeypatch.setattr(
        "mnemosyne.experience.candidates.register_import", lambda *args: None
    )
    rows = []

    def state():
        artifacts = {
            "base": {
                "id": "base",
                "state": "active",
                "created_at": "0",
                "framework": {"nodes": ["quoted"]},
            }
        }
        consistent_at, inconsistent_at = (
            (8, 6) if mutation == "slower_schema" else (6, 8)
        )
        if len(rows) >= consistent_at:
            artifacts["consistent"] = {
                "id": "consistent",
                "state": "active",
                "created_at": "1",
                "task_class": "unrelated"
                if mutation == "unrelated_promotion"
                else "schema",
                "schema_ref": {"id": "base"},
            }
        if len(rows) >= inconsistent_at:
            artifacts["inconsistent"] = {
                "id": "inconsistent",
                "state": "active",
                "created_at": "1",
                "task_class": "inconsistent",
            }
        return {"artifacts": artifacts}

    environment = SimpleNamespace(
        budget=4,
        rows=rows,
        evidence={},
        runtime=None,
        pretraining=nullcontext,
        tenant="test",
        source=lambda *args: "source",
        turn=lambda *args, **kwargs: rows.append({}),
        sleep=lambda: None,
        state=state,
        require=lambda condition, reason: (
            None if condition else (_ for _ in ()).throw(ProbeUnavailable(reason))
        ),
    )
    if mutation == "unrelated_promotion":
        with pytest.raises(ProbeUnavailable):
            _schema(environment)
    else:
        _schema(environment)
        environment.evidence["guard_detections"] = 0
        assert verify_family(10, environment.evidence).passed is (mutation is None)


@pytest.mark.parametrize("corrupt", [False, True])
def test_chunk_probe_rejects_reversed_transfer_advantage(monkeypatch, corrupt):
    from eval.learning import probes
    from eval.learning.simulator import ScriptedAgent

    class TransferEnvironment:
        def __init__(
            self,
            runtime,
            family,
            seed,
            *,
            budget,
            agent=None,
            arm,
            protocol="specialized-v1",
        ):
            self.runtime, self.family, self.seed = runtime, family, seed
            self.budget, self.arm, self.tenant = budget, arm, arm
            self.protocol = protocol
            self.agent, self.clock = ScriptedAgent(seed), None
            self.rows, self.evidence, self.operations = [], {}, []

        def train(self, *args, **kwargs):
            return None

        def sleep(self):
            return None

        def state(self):
            return {
                "policy": {"modes": {}},
                "artifacts": {"chunk": {"id": "chunk", "kind": "chunk"}},
            }

        def turn(self, *args, **kwargs):
            fast = self.arm.endswith("unchunked") == corrupt
            row = {"success": fast or len(self.rows) >= 4, "served_ids": ["chunk"]}
            self.rows.append(row)
            return row

        def require(self, condition, reason):
            assert condition, reason

    monkeypatch.setattr(probes, "Environment", TransferEnvironment)
    runtime = SimpleNamespace(mode=lambda *args: None)
    environment = TransferEnvironment(runtime, 22, 11, budget=16, arm="learning_on")
    probes._chunks(environment)
    environment.evidence["guard_detections"] = 0
    assert verify_family(22, environment.evidence).passed is not corrupt
