from __future__ import annotations

from mnemosyne.attack_suite import memory_poisoning_cases
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.gate import RegressionCase
from mnemosyne.learning import LearningSystem, Trajectory, counterfactual_replay_score
from mnemosyne.models import Evidence


TENANT = "tenant-e"
USER = "user-e"


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

