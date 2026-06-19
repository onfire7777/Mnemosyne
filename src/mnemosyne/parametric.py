"""Isolated parametric-tier promotion boundaries."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from mnemosyne.gate import GateResult, RegressionCase
from mnemosyne.ids import new_id
from mnemosyne.learning import Lesson, Procedure


@dataclass(slots=True)
class ParametricArtifact:
    tenant_id: str
    source_ids: list[str]
    adapter_kind: str
    status: str = "shadow"
    metrics: dict[str, float] = field(default_factory=dict)
    immutable_rails: list[str] = field(default_factory=list)
    id: str = field(default_factory=new_id)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ParametricPromotionDecision:
    promoted: bool
    reason: str
    artifact: ParametricArtifact
    gate_report: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["artifact"] = self.artifact.to_dict()
        return data


class ParametricTier:
    """Shadow-only boundary for validated lessons/procedures.

    Mnemosyne is not a foundation-model trainer. This class models the
    blueprint's parametric tier as an isolated artifact gate: only already
    validated lessons/procedures can become adapter candidates, and protected
    regressions keep them in shadow.
    """

    required_rails = (
        "tenant_isolation_required",
        "branch_promotion_requires_gate",
        "protected_regression_suite_required",
    )

    def propose_from_lessons(self, tenant_id: str, lessons: list[Lesson], procedures: list[Procedure]) -> ParametricArtifact:
        active_lessons = [lesson.id for lesson in lessons if lesson.tenant_id == tenant_id and lesson.status == "active"]
        active_procedures = [procedure.id for procedure in procedures if procedure.tenant_id == tenant_id and procedure.status in {"active", "validated"}]
        return ParametricArtifact(
            tenant_id=tenant_id,
            source_ids=active_lessons + active_procedures,
            adapter_kind="local-shadow-adapter",
            immutable_rails=list(self.required_rails),
        )

    def evaluate(
        self,
        artifact: ParametricArtifact,
        gate_result: GateResult,
        protected_cases: list[RegressionCase],
    ) -> ParametricPromotionDecision:
        if not artifact.source_ids:
            artifact.status = "rejected"
            return ParametricPromotionDecision(False, "no validated source lessons or procedures", artifact)
        if not protected_cases:
            artifact.status = "shadow"
            return ParametricPromotionDecision(False, "protected regression suite required", artifact)
        if not all(rail in artifact.immutable_rails for rail in self.required_rails):
            artifact.status = "rejected"
            return ParametricPromotionDecision(False, "immutable rails missing", artifact)
        if not gate_result.promoted or gate_result.protected_regressions:
            artifact.status = "shadow"
            return ParametricPromotionDecision(False, "promotion gate did not clear protected cases", artifact, gate_result.to_dict())
        artifact.status = "promoted"
        artifact.metrics["protected_cases"] = float(len(protected_cases))
        return ParametricPromotionDecision(True, "parametric artifact promoted in isolated tier", artifact, gate_result.to_dict())
