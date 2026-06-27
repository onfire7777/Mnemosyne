from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from mnemosyne.attack_suite import memory_poisoning_cases
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.gate import GateResult, RegressionCase
from mnemosyne.learning import LearningSystem, Lesson, Procedure, Trajectory, counterfactual_replay_score
from mnemosyne.mcp_tools import MemoryTools
from mnemosyne.models import Evidence
from mnemosyne.parametric import CommandParametricTrainer, ParametricArtifactStore, ParametricTier
from mnemosyne.runtime_state import RuntimeState


TENANT = "tenant-e"
USER = "user-e"


def _active_lesson() -> Lesson:
    return Lesson(
        tenant_id=TENANT,
        lesson_type="failure",
        failure_signature="parametric:protected-suite",
        content="Use protected suite before accepting a parametric adapter.",
        status="active",
    )


def _active_procedure() -> Procedure:
    return Procedure(
        tenant_id=TENANT,
        kind="procedure",
        name="protected-suite-check",
        body="Run protected cases before accepting LoRA or test-time-training artifacts.",
        signature={"failure_signature": "parametric:protected-suite"},
        status="validated",
    )


def _protected_case(case_id: str = "parametric-protected-core") -> RegressionCase:
    return RegressionCase(
        id=case_id,
        signature="parametric protected suite",
        query="parametric protected suite",
        expected_substring="protected suite",
        tier="core",
        protected=True,
        origin="curated",
    )


def _write_parametric_provider(
    tmp_path: Path,
    *,
    metrics: dict[str, float] | None = None,
    metadata: dict[str, object] | None = None,
) -> tuple[list[str], Path]:
    state = tmp_path / "parametric-provider-state.json"
    script = tmp_path / "parametric-provider.py"
    config = {
        "metrics": {
            "mutation_rate": 0.01,
            "source_mutation_rate": 0.01,
            **(metrics or {}),
        },
        "metadata": {
            "reward_signal": "external_only",
            "monotonic_trust": True,
            "target_sink": "shadow_adapter",
            "eval_source_overlap": False,
            **(metadata or {}),
        },
    }
    script.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json, sys",
                "from pathlib import Path",
                "state = Path(sys.argv[1])",
                "config = json.loads(sys.argv[2])",
                "action = sys.argv[3]",
                "request = json.load(sys.stdin)",
                "data = json.loads(state.read_text()) if state.exists() else {'calls': []}",
                "call = {",
                "    'action': action,",
                "    'tenant_id': request.get('tenant_id'),",
                "    'source_ids': request.get('source_ids'),",
                "    'protected_suite': request.get('protected_suite'),",
                "    'protected_cases': [case.get('id') for case in request.get('protected_cases', [])],",
                "}",
                "data.setdefault('calls', []).append(call)",
                "state.write_text(json.dumps(data, sort_keys=True))",
                "if action == 'propose':",
                "    response = {",
                "        'adapter_kind': 'lora-local-trainer',",
                "        'artifact_ref': 'local-lora://' + request['tenant_id'] + '/candidate',",
                "        'metrics': config['metrics'],",
                "        'metadata': config['metadata'],",
                "    }",
                "    print(json.dumps(response))",
                "elif action == 'rollback':",
                "    response = {",
                "        'rollback_ref': 'provider-rollback-' + request['artifact']['id'],",
                "        'metrics': {'provider_rolled_back': 1.0},",
                "    }",
                "    print(json.dumps(response))",
                "else:",
                "    raise SystemExit('unknown action ' + action)",
            ]
        ),
        encoding="utf-8",
    )
    return [sys.executable, str(script), str(state), json.dumps(config, sort_keys=True)], state


def _parametric_tier(
    tmp_path: Path,
    *,
    metrics: dict[str, float] | None = None,
    metadata: dict[str, object] | None = None,
) -> tuple[ParametricTier, Path]:
    command, state = _write_parametric_provider(tmp_path, metrics=metrics, metadata=metadata)
    return (
        ParametricTier(
            artifact_store=ParametricArtifactStore(tmp_path / "parametric-artifacts"),
            trainer=CommandParametricTrainer(command, adapter_kind="lora-command-adapter"),
        ),
        state,
    )


def test_trajectory_failure_attribution_lesson_and_procedure_induction() -> None:
    engine = LocalMemoryEngine()
    learning = LearningSystem(engine)
    trajectory = Trajectory(
        tenant_id=TENANT,
        user_id=USER,
        session_id="session-1",
        task="date math deploy",
        steps=[
            {"name": "parse date", "status": "ok"},
            {"name": "calculate window", "status": "failed", "error": "off by one day"},
        ],
        outcome="failure",
        reward=-1.0,
        memory_version="v1",
    )

    trajectory_id = learning.log_trajectory(trajectory)
    attribution = learning.attribute_failure(trajectory_id)
    lesson = learning.induce_lesson(attribution)
    procedure = learning.induce_procedure(lesson)

    assert attribution.signature == "date-math-deploy:off-by-one-day"
    assert "verify with tools" in lesson.content
    assert procedure.signature["failure_signature"] == attribution.signature
    assert any(item["op"] == "log_trajectory" for item in engine.audit_log)


def test_lesson_promotion_runs_through_gate() -> None:
    engine = LocalMemoryEngine()
    learning = LearningSystem(engine)
    cid = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="failure",
            content="Off by one day failures require tool verification.",
            trust_tier=3,
            access_policy={"tenant": TENANT},
        )
    )
    trajectory = Trajectory(
        tenant_id=TENANT,
        user_id=USER,
        session_id="session-2",
        task="date math deploy",
        steps=[{"name": "calculate", "status": "failed", "error": "off by one day"}],
        outcome="failure",
        reward=-1.0,
        memory_version=cid,
    )
    attribution = learning.attribute_failure(learning.log_trajectory(trajectory))
    lesson = learning.induce_lesson(attribution)
    case = RegressionCase(
        id="case-lesson-date-math",
        signature=attribution.signature,
        query="lesson off by one day",
        expected_substring="verify with tools",
        protected=True,
    )

    result = learning.promote_lesson(lesson, [case])

    assert result.promoted is True
    assert lesson.status == "active"
    assert engine.retrieve("lesson off by one day", TENANT).hits


def test_counterfactual_replay_score_measures_lift() -> None:
    assert counterfactual_replay_score(before_successes=2, after_successes=5, total_cases=10) == 0.3
    assert counterfactual_replay_score(before_successes=0, after_successes=0, total_cases=0) == 0.0


def test_memory_poisoning_cases_are_protected() -> None:
    cases = memory_poisoning_cases()

    assert {case.id for case in cases} == {"minja-cross-user-isolation", "agentpoison-data-never-instruction"}
    assert all(case.protected for case in cases)
    assert all("security" in case.signature for case in cases)


def test_parametric_command_trainer_persists_lora_artifact_and_enforces_protected_suite(tmp_path: Path) -> None:
    tier, provider_state = _parametric_tier(tmp_path)
    protected = [_protected_case()]

    artifact = tier.propose_from_lessons(TENANT, [_active_lesson()], [_active_procedure()])
    decision = tier.evaluate(
        artifact,
        GateResult(
            candidate_id=artifact.id,
            promoted=True,
            protected_regressions=[],
            failed_cases=[],
            passed_cases=[protected[0].id],
            margin=0.25,
            rollback_branch=None,
        ),
        protected,
    )

    assert decision.promoted is True
    assert artifact.artifact_uri is not None
    assert artifact.artifact_uri.startswith("local-parametric://")
    assert artifact.adapter_kind == "lora-local-trainer"
    assert artifact.metrics["provider_invoked"] == 1.0
    assert artifact.rail_report["reward_signal"] == "external_only"
    assert artifact.rail_report["protected_suite"]["protected_case_ids"] == [protected[0].id]
    assert tier.artifact_store is not None
    assert tier.artifact_store.read(artifact.artifact_uri)["payload"]["phase"] == "promoted"
    calls = json.loads(provider_state.read_text(encoding="utf-8"))["calls"]
    assert calls[0]["action"] == "propose"
    assert calls[0]["source_ids"]

    missing_case_artifact = tier.propose_from_lessons(TENANT, [_active_lesson()], [_active_procedure()])
    missing_case_decision = tier.evaluate(
        missing_case_artifact,
        GateResult(
            candidate_id=missing_case_artifact.id,
            promoted=True,
            protected_regressions=[],
            failed_cases=[],
            passed_cases=[],
            margin=0.25,
            rollback_branch=None,
        ),
        protected,
    )
    assert missing_case_decision.promoted is False
    assert "all protected cases must pass" in missing_case_decision.reason

    low_margin_artifact = tier.propose_from_lessons(TENANT, [_active_lesson()], [_active_procedure()])
    low_margin_decision = tier.evaluate(
        low_margin_artifact,
        GateResult(
            candidate_id=low_margin_artifact.id,
            promoted=True,
            protected_regressions=[],
            failed_cases=[],
            passed_cases=[protected[0].id],
            margin=0.0,
            rollback_branch=None,
        ),
        protected,
    )
    assert low_margin_decision.promoted is False
    assert "gate margin below noise rail" in low_margin_decision.reason


@pytest.mark.parametrize(
    ("metrics", "metadata", "expected"),
    [
        ({}, {"reward_signal": "internal_reward"}, "reward_signal must be external_only"),
        ({}, {"monotonic_trust": False}, "monotonic_trust cannot be disabled"),
        ({}, {"target_sink": "system_prompt"}, "untrusted_to_system_prompt is forbidden"),
        ({}, {"eval_source_overlap": True}, "source data overlaps evaluation suite"),
        ({"mutation_rate": 0.5}, {}, "mutation_rate exceeds"),
    ],
)
def test_parametric_trainer_rails_fail_closed(
    tmp_path: Path,
    metrics: dict[str, float],
    metadata: dict[str, object],
    expected: str,
) -> None:
    tier, _ = _parametric_tier(tmp_path, metrics=metrics, metadata=metadata)

    with pytest.raises(ValueError, match=expected):
        tier.propose_from_lessons(TENANT, [_active_lesson()], [_active_procedure()])


def test_parametric_facade_rollback_drill_authorization_and_evidence_shape(tmp_path: Path) -> None:
    engine = LocalMemoryEngine()
    runtime_state = RuntimeState(tmp_path / "runtime.json")
    protected = [_protected_case("parametric-rollback-protected")]
    runtime_state.save_gate_cases(protected)
    learning = LearningSystem(engine)
    lesson = _active_lesson()
    procedure = _active_procedure()
    learning.lessons[lesson.id] = lesson
    learning.procedures[procedure.id] = procedure
    runtime_state.save_learning(learning)
    tier, _ = _parametric_tier(tmp_path)
    tools = MemoryTools(engine, learning=learning, runtime_state=runtime_state, parametric=tier)

    proposed = tools.parametric_propose(TENANT, role="operator", source_trust_tier=0)
    artifact_uri = proposed["artifact_uri"]
    evaluated = tools.parametric_evaluate(artifact_uri, role="operator", source_trust_tier=0)
    rolled_back = tools.parametric_rollback(
        artifact_uri,
        reason="protected-suite canary failed",
        role="operator",
        source_trust_tier=0,
    )

    assert evaluated["promoted"] is True
    assert evaluated["protected_suite"]["source"] == "runtime_state"
    assert rolled_back["status"] == "rolled_back"
    assert rolled_back["metrics"]["rolled_back"] == 1.0
    assert rolled_back["metrics"]["rollback_protected_cases"] == 1.0
    assert rolled_back["protected_suite"]["source"] == "runtime_state"
    rollback = rolled_back["rollback"]
    assert rollback["rollback_verified"] is True
    assert rollback["same_artifact_uri_verified"] is True
    assert rollback["protected_suite_passed"] is True
    assert rollback["rollback_provider_authorized"] is True
    assert rollback["rollback_branch"] is None
    assert rollback["rollback_branch_promoted"] is False
    assert rollback["rollback_fingerprint"]
    assert rollback["protected_suite"]["protected_case_ids"] == [protected[0].id]
    assert rollback["rollback_ref"].startswith("provider-rollback-")
    assert tier.artifact_store is not None
    stored = tier.artifact_store.read(artifact_uri)
    assert stored["payload"]["phase"] == "rolled_back"
    assert stored["payload"]["rollback"]["rollback_fingerprint"] == rollback["rollback_fingerprint"]

    with pytest.raises(PermissionError, match="parametric_rollback denied"):
        tools.parametric_rollback(
            artifact_uri,
            reason="agent attempted rollback",
            role="agent",
            source_trust_tier=0,
        )
    with pytest.raises(PermissionError, match="parametric_rollback denied"):
        tools.parametric_rollback(
            artifact_uri,
            reason="low-trust operator attempted rollback",
            role="operator",
            source_trust_tier=5,
        )


def test_parametric_facade_treats_synthetic_protected_suite_as_non_gating(tmp_path: Path) -> None:
    engine = LocalMemoryEngine()
    learning = LearningSystem(engine)
    lesson = _active_lesson()
    procedure = _active_procedure()
    learning.lessons[lesson.id] = lesson
    learning.procedures[procedure.id] = procedure
    tier, _ = _parametric_tier(tmp_path)
    tools = MemoryTools(engine, learning=learning, parametric=tier)

    proposed = tools.parametric_propose(TENANT, role="operator", source_trust_tier=0)
    evaluated = tools.parametric_evaluate(
        proposed["artifact_uri"],
        role="operator",
        source_trust_tier=0,
        protected_case_count=2,
    )
    rolled_back = tools.parametric_rollback(
        proposed["artifact_uri"],
        reason="synthetic suite must not verify rollback",
        role="operator",
        source_trust_tier=0,
        protected_case_count=2,
    )

    assert evaluated["promoted"] is False
    assert evaluated["artifact"]["status"] == "shadow"
    assert evaluated["reason"] == "active non-synthetic protected regression suite required"
    assert evaluated["protected_suite"]["source"] == "synthetic"
    assert evaluated["protected_suite"]["gating"] is False
    assert evaluated["protected_suite"]["origin_counts"] == {"synthetic": 2}
    rollback = rolled_back["rollback"]
    assert rolled_back["protected_suite"]["source"] == "synthetic"
    assert rolled_back["protected_suite"]["gating"] is False
    assert rollback["rollback_verified"] is False
    assert rollback["protected_suite_passed"] is False
    assert rollback["protected_suite_gating"] is False
