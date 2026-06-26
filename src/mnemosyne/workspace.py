"""Shadow workspace controller over typed specialist modules.

The workspace controller is advisory by construction. It can recruit specialists
registered in :mod:`mnemosyne.providers`, but it cannot place shadow-only
specialists on the answer critical path or mutate production memory.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

from .consciousness import BoundedCognitiveCycle, InteroceptiveProtoSelf, ProtoSelfSnapshot, workspace_bottleneck
from .dreamer import DreamReport, SandboxedDreamer
from .models import Evidence
from .providers import SpecialistModuleRegistry, default_registry


@dataclass(frozen=True, slots=True)
class WorkspaceItem:
    """A low-bandwidth item competing for workspace attention."""

    id: str
    priority: float
    content: str
    source: str = "runtime"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_bottleneck_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "priority": float(self.priority),
            "content": self.content,
            "source": self.source,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class SpecialistInvocation:
    """Specialist invocation record emitted by the shadow controller."""

    name: str
    role: str
    shadow_only: bool
    critical_path: bool
    critical_path_allowed: bool
    output_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class WorkspaceCycleReport:
    """Bounded shadow workspace cycle report."""

    tenant_id: str
    cycle: dict[str, Any]
    selected_items: tuple[dict[str, Any], ...]
    proto_self: ProtoSelfSnapshot
    specialist_invocations: tuple[SpecialistInvocation, ...]
    shadow_only: bool = True
    critical_path: bool = False
    production_mutation: bool = False
    escalation_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["proto_self"] = asdict(self.proto_self)
        data["specialist_invocations"] = [item.to_dict() for item in self.specialist_invocations]
        return data


@dataclass(slots=True)
class ShadowWorkspaceController:
    """Bounded controller that recruits typed specialists in shadow mode."""

    registry: SpecialistModuleRegistry = field(default_factory=default_registry)
    max_workspace_items: int = 4
    max_cycles: int = 4
    tick_ms: int = 250
    dreamer_name: str = "dreamer.shadow"

    def run_shadow_cycle(
        self,
        *,
        tenant_id: str,
        items: Sequence[WorkspaceItem | Mapping[str, Any]],
        evidence: Sequence[Evidence | Mapping[str, Any]] = (),
        confidence: float = 0.75,
        resource_health: float = 0.9,
        error_rate: float = 0.0,
        latency_ms: float = 0.0,
        memory_pressure: float = 0.0,
        rail_budget: float = 1.0,
    ) -> WorkspaceCycleReport:
        """Run one bounded advisory cycle and return a machine-checkable report."""

        selected = workspace_bottleneck(
            [_item_to_row(item) for item in items],
            limit=self.max_workspace_items,
        )
        cycle_guard = BoundedCognitiveCycle(max_cycles=self.max_cycles, tick_ms=self.tick_ms)
        cycle = cycle_guard.tick(coherent=True, progressed=bool(selected or evidence))
        proto_self = InteroceptiveProtoSelf().snapshot(
            resource_health=resource_health,
            error_rate=error_rate,
            latency_ms=latency_ms,
            memory_pressure=memory_pressure,
            confidence=confidence,
            rail_budget=rail_budget,
            cycle_index=cycle["cycle_index"],
            max_cycles=cycle["max_cycles"],
        )
        invocations: list[SpecialistInvocation] = []
        if evidence:
            spec = self.registry.specialist(self.dreamer_name)
            if spec.budget.critical_path_allowed:
                raise ValueError(f"{self.dreamer_name} must remain off the critical path")
            dreamer = self.registry.build_specialist(self.dreamer_name, critical_path=False)
            if not isinstance(dreamer, SandboxedDreamer):
                raise TypeError(f"{self.dreamer_name} must build a SandboxedDreamer")
            dream_report = dreamer.dream(evidence, tenant_id=tenant_id)
            invocations.append(_dreamer_invocation(spec, dream_report))

        escalation_required = bool(proto_self.escalation_required or cycle["state"].startswith("escalate"))
        return WorkspaceCycleReport(
            tenant_id=tenant_id,
            cycle=cycle,
            selected_items=tuple(selected),
            proto_self=proto_self,
            specialist_invocations=tuple(invocations),
            escalation_required=escalation_required,
        )


def _item_to_row(item: WorkspaceItem | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(item, WorkspaceItem):
        return item.to_bottleneck_row()
    return {
        "id": str(item.get("id") or ""),
        "priority": float(item.get("priority", 0.0)),
        "content": str(item.get("content") or ""),
        "source": str(item.get("source") or "runtime"),
        "metadata": dict(item.get("metadata") or {}),
    }


def _dreamer_invocation(spec: Any, report: DreamReport) -> SpecialistInvocation:
    return SpecialistInvocation(
        name=spec.name,
        role=str(spec.role),
        shadow_only=spec.budget.shadow_only and report.shadow_only,
        critical_path=bool(report.critical_path),
        critical_path_allowed=bool(spec.budget.critical_path_allowed),
        output_summary={
            "candidate_count": len(report.candidates),
            "source_count": report.source_count,
            "production_mutation": report.production_mutation,
            "promotion_gate_required": report.promotion_gate_required,
            "candidate_reality_classes": sorted({candidate.reality_class for candidate in report.candidates}),
            "candidate_trust_tiers": sorted({candidate.trust_tier for candidate in report.candidates}),
        },
    )
