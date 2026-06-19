"""Procedural and corrective learning primitives."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.gate import Candidate, GateResult, PromotionGate, RegressionCase
from mnemosyne.ids import new_id
from mnemosyne.models import Assertion


@dataclass(slots=True)
class Trajectory:
    tenant_id: str
    user_id: str
    session_id: str
    task: str
    steps: list[dict[str, Any]]
    outcome: Literal["success", "failure"]
    reward: float
    memory_version: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: str = field(default_factory=new_id)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["created_at"] = self.created_at.astimezone(UTC).isoformat()
        return data


@dataclass(slots=True)
class FailureAttribution:
    trajectory_id: str
    signature: str
    cause: str
    evidence: list[str]
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Lesson:
    tenant_id: str
    lesson_type: str
    failure_signature: str
    content: str
    votes: int = 2
    status: str = "candidate"
    id: str = field(default_factory=new_id)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Procedure:
    tenant_id: str
    kind: str
    name: str
    body: str
    signature: dict[str, Any]
    status: str = "candidate"
    success_rate: float | None = None
    n_trials: int = 0
    id: str = field(default_factory=new_id)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LearningSystem:
    def __init__(self, engine: LocalMemoryEngine):
        self.engine = engine
        self.trajectories: dict[str, Trajectory] = {}
        self.attributions: dict[str, FailureAttribution] = {}
        self.lessons: dict[str, Lesson] = {}
        self.procedures: dict[str, Procedure] = {}

    def log_trajectory(self, trajectory: Trajectory) -> str:
        self.trajectories[trajectory.id] = trajectory
        self.engine._audit(trajectory.tenant_id, "learning", "log_trajectory", trajectory.id, {"task": trajectory.task, "outcome": trajectory.outcome})
        return trajectory.id

    def attribute_failure(self, trajectory_id: str) -> FailureAttribution:
        trajectory = self.trajectories[trajectory_id]
        failing_steps = [step for step in trajectory.steps if step.get("status") == "failed"]
        if failing_steps:
            first = failing_steps[0]
            cause = str(first.get("error") or first.get("description") or "failed step")
        else:
            cause = "outcome marked failure without failed step"
        signature = f"{trajectory.task}:{cause}".lower().replace(" ", "-")
        attribution = FailureAttribution(
            trajectory_id=trajectory_id,
            signature=signature,
            cause=cause,
            evidence=[str(step) for step in failing_steps],
            confidence=0.75 if failing_steps else 0.45,
        )
        self.attributions[trajectory_id] = attribution
        return attribution

    def induce_lesson(self, attribution: FailureAttribution) -> Lesson:
        lesson = Lesson(
            tenant_id=self.trajectories[attribution.trajectory_id].tenant_id,
            lesson_type="corrective",
            failure_signature=attribution.signature,
            content=f"When encountering {attribution.cause}, verify with tools before writing durable memory.",
        )
        self.lessons[lesson.id] = lesson
        return lesson

    def induce_procedure(self, lesson: Lesson) -> Procedure:
        procedure = Procedure(
            tenant_id=lesson.tenant_id,
            kind="checklist",
            name=f"Procedure for {lesson.failure_signature}",
            body=f"1. Detect {lesson.failure_signature}\n2. Run a verification check\n3. Apply the smallest correction\n4. Re-run protected regression cases",
            signature={"failure_signature": lesson.failure_signature},
        )
        self.procedures[procedure.id] = procedure
        return procedure

    def promote_lesson(self, lesson: Lesson, cases: list[RegressionCase]) -> GateResult:
        gate = PromotionGate(self.engine, cases)
        candidate = Candidate(
            id=lesson.id,
            kind="lesson",
            signature=lesson.failure_signature,
            description=lesson.content,
            branch=f"canary-lesson-{lesson.id}",
            source_evidence_cids=[],
        )

        def apply(engine: LocalMemoryEngine, branch: str) -> None:
            engine.upsert_assertion(
                Assertion(
                    tenant_id=lesson.tenant_id,
                    subject="lesson",
                    predicate="says",
                    object=lesson.content,
                    confidence=0.8,
                    status="active",
                    trust_tier=3,
                    access_policy={"tenant": lesson.tenant_id},
                ),
                branch=branch,
            )

        result = gate.evaluate(lesson.tenant_id, candidate, apply)
        if result.promoted:
            lesson.status = "active"
        return result


def counterfactual_replay_score(before_successes: int, after_successes: int, total_cases: int) -> float:
    if total_cases <= 0:
        return 0.0
    return (after_successes - before_successes) / total_cases

