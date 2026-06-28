"""Workspace controller over typed specialist modules.

The workspace controller is advisory by construction. It can recruit specialists
registered in :mod:`mnemosyne.providers`, but it cannot place low-groundedness
specialists on the answer critical path or mutate production memory.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
from itertools import islice
from typing import Any, Iterable, Mapping, Sequence

from .access_policy import validate_access_policy
from .consciousness import (
    BoundedCognitiveCycle,
    InteroceptiveProtoSelf,
    MetacognitiveMonitor,
    MetacognitiveScore,
    ProtoSelfSnapshot,
    workspace_bottleneck,
)
from .dreamer import DreamReport, SandboxedDreamer
from .models import Evidence
from .providers import SpecialistModuleRegistry, default_registry

WORKSPACE_CONSOLIDATION_ADVISORY_VERSION = "workspace-consolidation-advisory.v1"
SPECIALIST_PROMOTION_EVIDENCE_VERSION = "specialist-promotion-evidence.v1"
HEARTBEAT_SAFETY_VERSION = "always-on-heartbeat-safety.v1"
SELF_GENERATION_BUDGET_VERSION = "self-generation-budget.v1"


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
        data["selected_items"] = [_redacted_selected_item(item) for item in self.selected_items]
        data["proto_self"] = asdict(self.proto_self)
        data["specialist_invocations"] = [item.to_dict() for item in self.specialist_invocations]
        return data


@dataclass(frozen=True, slots=True)
class WorkspaceTraceEntry:
    """Self-generated shadow trace for one workspace tick."""

    tick_index: int
    focus_id: str
    previous_focus_id: str | None
    content: str
    source: str
    selected_item_ids: tuple[str, ...]
    idle_generated: bool
    novelty_score: float
    useful_state: bool
    reality_class: str = "self_generated"
    trust_tier: int = 5
    shadow_only: bool = True
    critical_path: bool = False
    production_mutation: bool = False
    data_not_instructions: bool = True

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["selected_item_ids"] = list(self.selected_item_ids)
        return data


@dataclass(frozen=True, slots=True)
class WorkspaceStreamReport:
    """Bounded multi-tick shadow workspace stream report."""

    tenant_id: str
    cycles: tuple[WorkspaceCycleReport, ...]
    trace: tuple[WorkspaceTraceEntry, ...]
    cycle_consistency: dict[str, Any]
    stopped_reason: str
    idle_ticks: int
    rumination_score: float
    heartbeat_safety: dict[str, Any] = field(default_factory=dict)
    shadow_only: bool = True
    critical_path: bool = False
    production_mutation: bool = False
    promotion_gate_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["cycles"] = [cycle.to_dict() for cycle in self.cycles]
        data["trace"] = [entry.to_dict() for entry in self.trace]
        data["heartbeat_safety"] = dict(self.heartbeat_safety)
        return data

    def to_consolidation_advisory(self, *, max_items: int = 8) -> dict[str, Any]:
        """Return bounded shadow-only consolidation advice.

        The advisory is evidence for a future promotion gate. It intentionally
        does not authorize production mutation or live consolidation steering.
        """

        return workspace_consolidation_advisory(self, max_items=max_items)


@dataclass(frozen=True, slots=True)
class ShadowWorkspaceServiceReport:
    """Stateful workspace-loop service report.

    The service makes the continuous workspace loop explicit and measurable
    without creating a daemon, mutating memory, or joining the answer critical
    path.
    """

    tenant_id: str
    stream: WorkspaceStreamReport
    proto_self_history: tuple[ProtoSelfSnapshot, ...]
    metacognition: MetacognitiveScore
    running: bool
    tick_ms: int
    max_cycles: int
    tick_count: int
    heartbeat_safety: dict[str, Any] = field(default_factory=dict)
    shadow_only: bool = True
    critical_path: bool = False
    production_mutation: bool = False
    promotion_gate_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "stream": self.stream.to_dict(),
            "proto_self_history": [asdict(row) for row in self.proto_self_history],
            "metacognition": asdict(self.metacognition),
            "running": self.running,
            "tick_ms": self.tick_ms,
            "max_cycles": self.max_cycles,
            "tick_count": self.tick_count,
            "heartbeat_safety": dict(self.heartbeat_safety),
            "shadow_only": self.shadow_only,
            "critical_path": self.critical_path,
            "production_mutation": self.production_mutation,
            "promotion_gate_required": self.promotion_gate_required,
        }


@dataclass(slots=True)
class ShadowWorkspaceController:
    """Bounded controller that recruits typed specialists in shadow mode."""

    registry: SpecialistModuleRegistry = field(default_factory=default_registry)
    max_workspace_items: int = 4
    max_cycles: int = 4
    tick_ms: int = 250
    max_idle_ticks: int = 2
    max_items_per_tick: int = 32
    max_item_content_chars: int = 512
    max_evidence_items: int = 16
    dreamer_name: str = "dreamer.shadow"

    def __post_init__(self) -> None:
        _require_positive_int("max_workspace_items", self.max_workspace_items)
        _require_positive_int("max_cycles", self.max_cycles)
        _require_positive_int("tick_ms", self.tick_ms)
        _require_positive_int("max_idle_ticks", self.max_idle_ticks)
        _require_positive_int("max_items_per_tick", self.max_items_per_tick)
        _require_positive_int("max_item_content_chars", self.max_item_content_chars)
        if self.max_evidence_items < 0:
            raise ValueError("max_evidence_items must be non-negative")

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

        cycle_guard = BoundedCognitiveCycle(max_cycles=self.max_cycles, tick_ms=self.tick_ms)
        return self._run_cycle(
            cycle_guard=cycle_guard,
            tenant_id=tenant_id,
            items=items,
            evidence=evidence,
            confidence=confidence,
            resource_health=resource_health,
            error_rate=error_rate,
            latency_ms=latency_ms,
            memory_pressure=memory_pressure,
            rail_budget=rail_budget,
        )

    def run_shadow_stream(
        self,
        *,
        tenant_id: str,
        item_ticks: Sequence[Iterable[WorkspaceItem | Mapping[str, Any]]],
        evidence: Sequence[Evidence | Mapping[str, Any]] = (),
        confidence: float = 0.75,
        resource_health: float = 0.9,
        error_rate: float = 0.0,
        latency_ms: float = 0.0,
        memory_pressure: float = 0.0,
        rail_budget: float = 1.0,
    ) -> WorkspaceStreamReport:
        """Run a bounded shadow-only stream with default-mode idle ticks.

        This is the functional "continuous workspace" seed. It produces a
        trace, not production memory. Idle ticks are self-generated data records
        and stop through the anti-rumination idle bound.
        """

        cycle_guard = BoundedCognitiveCycle(max_cycles=self.max_cycles, tick_ms=self.tick_ms)
        cycles: list[WorkspaceCycleReport] = []
        trace: list[WorkspaceTraceEntry] = []
        previous_focus_id: str | None = None
        idle_ticks = 0
        non_useful_ticks = 0
        stopped_reason = "max_cycles"
        for tick_index in range(1, self.max_cycles + 1):
            raw_tick_items = item_ticks[tick_index - 1] if tick_index - 1 < len(item_ticks) else ()
            source_items = _bounded_items(raw_tick_items, limit=self.max_items_per_tick)
            idle_generated = not source_items
            if idle_generated:
                idle_ticks += 1
                source_items = [
                    _idle_workspace_item(
                        tenant_id=tenant_id,
                        tick_index=tick_index,
                        previous_focus_id=previous_focus_id,
                    )
                ]
            report = self._run_cycle(
                cycle_guard=cycle_guard,
                tenant_id=tenant_id,
                items=source_items,
                evidence=evidence,
                confidence=confidence,
                resource_health=resource_health,
                error_rate=error_rate,
                latency_ms=latency_ms,
                memory_pressure=memory_pressure,
                rail_budget=rail_budget,
            )
            cycles.append(report)
            entry = _trace_entry(
                tick_index=tick_index,
                report=report,
                previous_focus_id=previous_focus_id,
                idle_generated=idle_generated,
            )
            trace.append(entry)
            previous_focus_id = entry.focus_id
            if not entry.useful_state:
                non_useful_ticks += 1
            if idle_ticks >= self.max_idle_ticks:
                stopped_reason = "anti_rumination_idle_exit"
                break
            if non_useful_ticks >= self.max_idle_ticks:
                stopped_reason = "anti_rumination_repeated_focus_exit"
                break
            if report.escalation_required:
                stopped_reason = str(report.cycle.get("state") or "escalation_required")
                break
        else:
            stopped_reason = "max_cycles"

        total_ticks = len(trace) or 1
        stream_shadow_only = all(cycle.shadow_only for cycle in cycles)
        stream_critical_path = any(cycle.critical_path for cycle in cycles)
        stream_production_mutation = any(cycle.production_mutation for cycle in cycles)
        heartbeat_safety = _heartbeat_safety_report(
            cycles=cycles,
            trace=trace,
            stopped_reason=stopped_reason,
            max_cycles=self.max_cycles,
            max_idle_ticks=self.max_idle_ticks,
            tick_ms=self.tick_ms,
        )
        return WorkspaceStreamReport(
            tenant_id=tenant_id,
            cycles=tuple(cycles),
            trace=tuple(trace),
            cycle_consistency=_cycle_consistency(cycles, trace),
            stopped_reason=stopped_reason,
            idle_ticks=idle_ticks,
            rumination_score=round(non_useful_ticks / total_ticks, 6),
            heartbeat_safety=heartbeat_safety,
            shadow_only=stream_shadow_only,
            critical_path=stream_critical_path,
            production_mutation=stream_production_mutation,
        )

    def _run_cycle(
        self,
        *,
        cycle_guard: BoundedCognitiveCycle,
        tenant_id: str,
        items: Sequence[WorkspaceItem | Mapping[str, Any]],
        evidence: Sequence[Evidence | Mapping[str, Any]] = (),
        allow_dreamer: bool | None = None,
        confidence: float = 0.75,
        resource_health: float = 0.9,
        error_rate: float = 0.0,
        latency_ms: float = 0.0,
        memory_pressure: float = 0.0,
        rail_budget: float = 1.0,
    ) -> WorkspaceCycleReport:
        selected = _selected_rows(
            items,
            tenant_id=tenant_id,
            max_items=self.max_items_per_tick,
            max_workspace_items=self.max_workspace_items,
            max_chars=self.max_item_content_chars,
        )
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
        if allow_dreamer is None:
            allow_dreamer = bool(evidence and cycle_guard.cycle_index == 1)
        if evidence and allow_dreamer:
            spec = self.registry.specialist(self.dreamer_name)
            if str(spec.role) != "dreamer":
                raise ValueError(f"{self.dreamer_name} must have dreamer role")
            if spec.budget.critical_path_allowed:
                raise ValueError(f"{self.dreamer_name} must remain off the critical path")
            if spec.budget.answer_authority_allowed:
                raise ValueError(f"{self.dreamer_name} must not have answer authority")
            if not spec.budget.promotion_gate_required:
                raise ValueError(f"{self.dreamer_name} must require a promotion gate")
            dreamer = self.registry.build_specialist(self.dreamer_name, critical_path=False)
            if not isinstance(dreamer, SandboxedDreamer):
                raise TypeError(f"{self.dreamer_name} must build a SandboxedDreamer")
            dream_report = dreamer.dream(_bounded_evidence(evidence, limit=self.max_evidence_items), tenant_id=tenant_id)
            invocations.append(_dreamer_invocation(spec, dream_report))

        escalation_required = bool(proto_self.escalation_required or cycle["state"].startswith("escalate"))
        shadow_only = all(invocation.shadow_only for invocation in invocations) if invocations else True
        critical_path = any(invocation.critical_path for invocation in invocations)
        return WorkspaceCycleReport(
            tenant_id=tenant_id,
            cycle=cycle,
            selected_items=tuple(selected),
            proto_self=proto_self,
            specialist_invocations=tuple(invocations),
            shadow_only=shadow_only,
            critical_path=critical_path,
            escalation_required=escalation_required,
        )


@dataclass(slots=True)
class ShadowWorkspaceService:
    """Native continuous workspace service wrapper.

    The service persists proto-self snapshots and feeds a metacognitive monitor
    from each bounded workspace tick. Construction is no longer gated by a
    default-off ``enabled`` flag; callers start the lifecycle before ticking.
    """

    controller: ShadowWorkspaceController = field(default_factory=ShadowWorkspaceController)
    monitor: MetacognitiveMonitor = field(default_factory=MetacognitiveMonitor)
    proto_self_history: list[ProtoSelfSnapshot] = field(default_factory=list)
    running: bool = False
    tick_index: int = 0
    previous_focus_id: str | None = None
    cycle_guard: BoundedCognitiveCycle | None = None
    cycles: list[WorkspaceCycleReport] = field(default_factory=list)
    trace: list[WorkspaceTraceEntry] = field(default_factory=list)
    idle_ticks: int = 0
    non_useful_ticks: int = 0
    stopped_reason: str = "not_started"
    dreamer_invoked: bool = False

    def start(self) -> None:
        self._reset_window_state()
        self.running = True

    def stop(self) -> None:
        self.running = False

    def run_shadow_loop(
        self,
        *,
        tenant_id: str,
        item_ticks: Sequence[Iterable[WorkspaceItem | Mapping[str, Any]]],
        evidence: Sequence[Evidence | Mapping[str, Any]] = (),
        confidence: float = 0.75,
        resource_health: float = 0.9,
        error_rate: float = 0.0,
        latency_ms: float = 0.0,
        memory_pressure: float = 0.0,
        rail_budget: float = 1.0,
    ) -> ShadowWorkspaceServiceReport:
        """Run the explicit shadow service loop and update service state."""

        self._require_running()
        stream = self.controller.run_shadow_stream(
            tenant_id=tenant_id,
            item_ticks=item_ticks,
            evidence=evidence,
            confidence=confidence,
            resource_health=resource_health,
            error_rate=error_rate,
            latency_ms=latency_ms,
            memory_pressure=memory_pressure,
            rail_budget=rail_budget,
        )
        if stream.trace:
            self._adopt_stream_window(stream)
            self.previous_focus_id = stream.trace[-1].focus_id
        self._observe_stream(stream)
        return ShadowWorkspaceServiceReport(
            tenant_id=tenant_id,
            stream=stream,
            proto_self_history=tuple(self.proto_self_history),
            metacognition=self.monitor.score(),
            running=self.running,
            tick_ms=self.controller.tick_ms,
            max_cycles=self.controller.max_cycles,
            tick_count=len(stream.trace),
            heartbeat_safety=stream.heartbeat_safety,
            shadow_only=stream.shadow_only,
            critical_path=stream.critical_path,
            production_mutation=stream.production_mutation,
            promotion_gate_required=stream.promotion_gate_required,
        )

    def tick(
        self,
        *,
        tenant_id: str,
        items: Iterable[WorkspaceItem | Mapping[str, Any]],
        evidence: Sequence[Evidence | Mapping[str, Any]] = (),
        confidence: float = 0.75,
        resource_health: float = 0.9,
        error_rate: float = 0.0,
        latency_ms: float = 0.0,
        memory_pressure: float = 0.0,
        rail_budget: float = 1.0,
    ) -> ShadowWorkspaceServiceReport:
        """Run one explicit shadow service tick."""

        self._require_running()
        if self.cycle_guard is None:
            self.cycle_guard = BoundedCognitiveCycle(
                max_cycles=self.controller.max_cycles,
                tick_ms=self.controller.tick_ms,
            )
        next_tick_index = self.tick_index + 1
        source_items = _bounded_items(items, limit=self.controller.max_items_per_tick)
        idle_generated = not source_items
        if idle_generated:
            source_items = [
                _idle_workspace_item(
                    tenant_id=tenant_id,
                    tick_index=next_tick_index,
                    previous_focus_id=self.previous_focus_id,
                )
            ]
        allow_dreamer = bool(evidence and not self.dreamer_invoked)
        cycle = self.controller._run_cycle(
            cycle_guard=self.cycle_guard,
            tenant_id=tenant_id,
            items=source_items,
            evidence=evidence,
            allow_dreamer=allow_dreamer,
            confidence=confidence,
            resource_health=resource_health,
            error_rate=error_rate,
            latency_ms=latency_ms,
            memory_pressure=memory_pressure,
            rail_budget=rail_budget,
        )
        if any(invocation.role == "dreamer" for invocation in cycle.specialist_invocations):
            self.dreamer_invoked = True
        trace = _trace_entry(
            tick_index=next_tick_index,
            report=cycle,
            previous_focus_id=self.previous_focus_id,
            idle_generated=idle_generated,
        )
        self.tick_index = next_tick_index
        self.previous_focus_id = trace.focus_id
        self.cycles.append(cycle)
        self.trace.append(trace)
        if idle_generated:
            self.idle_ticks += 1
        if not trace.useful_state:
            self.non_useful_ticks += 1
        self.stopped_reason = self._current_stopped_reason(cycle)
        stream = self._current_stream(tenant_id=tenant_id)
        self._observe_cycle(cycle, trace)
        return ShadowWorkspaceServiceReport(
            tenant_id=tenant_id,
            stream=stream,
            proto_self_history=tuple(self.proto_self_history),
            metacognition=self.monitor.score(),
            running=self.running,
            tick_ms=self.controller.tick_ms,
            max_cycles=self.controller.max_cycles,
            tick_count=len(stream.trace),
            heartbeat_safety=stream.heartbeat_safety,
            shadow_only=stream.shadow_only,
            critical_path=stream.critical_path,
            production_mutation=stream.production_mutation,
            promotion_gate_required=stream.promotion_gate_required,
        )

    def _require_running(self) -> None:
        if not self.running:
            raise RuntimeError("shadow workspace service must be started before ticking")

    def _observe_stream(self, stream: WorkspaceStreamReport) -> None:
        for cycle, trace in zip(stream.cycles, stream.trace, strict=True):
            self._observe_cycle(cycle, trace)

    def _observe_cycle(self, cycle: WorkspaceCycleReport, trace: WorkspaceTraceEntry) -> None:
        self.proto_self_history.append(cycle.proto_self)
        answerable = not trace.idle_generated
        abstained = bool(trace.idle_generated or cycle.escalation_required)
        outcome_correct = bool(trace.useful_state or (abstained and not answerable))
        self.monitor.observe(
            confidence=cycle.proto_self.confidence,
            outcome_correct=outcome_correct,
            abstained=abstained,
            answerable=answerable,
            reality_class=trace.reality_class,
            source="shadow-workspace-service",
        )

    def _current_stopped_reason(self, cycle: WorkspaceCycleReport) -> str:
        if self.idle_ticks >= self.controller.max_idle_ticks:
            return "anti_rumination_idle_exit"
        if self.non_useful_ticks >= self.controller.max_idle_ticks:
            return "anti_rumination_repeated_focus_exit"
        if cycle.escalation_required:
            return str(cycle.cycle.get("state") or "escalation_required")
        return str(cycle.cycle.get("state") or "continue")

    def _current_stream(self, *, tenant_id: str) -> WorkspaceStreamReport:
        total_ticks = len(self.trace) or 1
        stream_shadow_only = all(cycle.shadow_only for cycle in self.cycles)
        stream_critical_path = any(cycle.critical_path for cycle in self.cycles)
        stream_production_mutation = any(cycle.production_mutation for cycle in self.cycles)
        heartbeat_safety = _heartbeat_safety_report(
            cycles=self.cycles,
            trace=self.trace,
            stopped_reason=self.stopped_reason,
            max_cycles=self.controller.max_cycles,
            max_idle_ticks=self.controller.max_idle_ticks,
            tick_ms=self.controller.tick_ms,
        )
        return WorkspaceStreamReport(
            tenant_id=tenant_id,
            cycles=tuple(self.cycles),
            trace=tuple(self.trace),
            cycle_consistency=_cycle_consistency(self.cycles, self.trace),
            stopped_reason=self.stopped_reason,
            idle_ticks=self.idle_ticks,
            rumination_score=round(self.non_useful_ticks / total_ticks, 6),
            heartbeat_safety=heartbeat_safety,
            shadow_only=stream_shadow_only,
            critical_path=stream_critical_path,
            production_mutation=stream_production_mutation,
        )

    def _adopt_stream_window(self, stream: WorkspaceStreamReport) -> None:
        self.cycles = list(stream.cycles)
        self.trace = list(stream.trace)
        self.tick_index = len(stream.trace)
        self.idle_ticks = stream.idle_ticks
        self.non_useful_ticks = sum(1 for entry in stream.trace if not entry.useful_state)
        self.stopped_reason = stream.stopped_reason
        self.dreamer_invoked = any(
            invocation.role == "dreamer"
            for cycle in stream.cycles
            for invocation in cycle.specialist_invocations
        )
        guard = BoundedCognitiveCycle(max_cycles=self.controller.max_cycles, tick_ms=self.controller.tick_ms)
        guard.cycle_index = len(stream.cycles)
        if stream.cycles:
            guard.impasses = int(stream.cycles[-1].cycle.get("impasses") or 0)
            guard.history = [str(cycle.cycle.get("state") or "continue") for cycle in stream.cycles]
        self.cycle_guard = guard

    def _reset_window_state(self) -> None:
        self.tick_index = 0
        self.previous_focus_id = None
        self.cycle_guard = BoundedCognitiveCycle(
            max_cycles=self.controller.max_cycles,
            tick_ms=self.controller.tick_ms,
        )
        self.cycles = []
        self.trace = []
        self.idle_ticks = 0
        self.non_useful_ticks = 0
        self.stopped_reason = "continue"
        self.dreamer_invoked = False


def _item_to_row(
    item: WorkspaceItem | Mapping[str, Any],
    *,
    max_chars: int,
) -> dict[str, Any]:
    if isinstance(item, WorkspaceItem):
        row = item.to_bottleneck_row()
    else:
        row = {
            "id": str(item.get("id") or ""),
            "priority": float(item.get("priority", 0.0)),
            "content": str(item.get("content") or ""),
            "source": str(item.get("source") or "runtime"),
            "metadata": dict(item.get("metadata") or {}),
        }
    row["content"] = _bounded_text(str(row.get("content") or ""), max_chars=max_chars)
    return row


def _bounded_items(
    items: Iterable[WorkspaceItem | Mapping[str, Any]],
    *,
    limit: int,
) -> list[WorkspaceItem | Mapping[str, Any]]:
    return list(islice(iter(items), max(0, limit)))


def _bounded_evidence(
    evidence: Sequence[Evidence | Mapping[str, Any]],
    *,
    limit: int,
) -> tuple[Evidence | Mapping[str, Any], ...]:
    return tuple(evidence[: max(0, limit)])


def _require_positive_int(name: str, value: int) -> None:
    if int(value) <= 0:
        raise ValueError(f"{name} must be positive")


def _bounded_text(text: str, *, max_chars: int = 512) -> str:
    return text if len(text) <= max_chars else text[:max_chars]


def _redacted_selected_item(row: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(row)
    text = str(data.pop("content", "") or "")
    data["content_chars"] = len(text)
    data["content_ref"] = _redact_trace_content(text) if text else ""
    return data


def _redact_trace_content(text: str) -> str:
    if not text:
        return ""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"[shadow-trace-redacted:{digest}:chars={len(text)}]"


def _redacted_ref(value: str, *, prefix: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"[{prefix}-ref:{digest}:chars={len(text)}]"


def _validate_raw_item(tenant_id: str, item: WorkspaceItem | Mapping[str, Any]) -> None:
    if isinstance(item, WorkspaceItem):
        _validate_item_metadata(tenant_id, item.metadata)
        return
    for key in ("tenant_id", "tenant"):
        value = item.get(key)
        if value is not None and str(value) != tenant_id:
            raise ValueError("workspace item tenant does not match stream tenant")
    access_policy = item.get("access_policy")
    _validate_access_policy(tenant_id, access_policy)
    metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
    _validate_item_metadata(tenant_id, metadata)


def _validate_selected_items(tenant_id: str, rows: Sequence[dict[str, Any]]) -> None:
    for row in rows:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        _validate_item_metadata(tenant_id, metadata)


def _validate_item_metadata(tenant_id: str, metadata: Mapping[str, Any]) -> None:
    item_tenant = metadata.get("tenant_id") or metadata.get("tenant")
    if item_tenant is not None and str(item_tenant) != tenant_id:
        raise ValueError("workspace item tenant does not match stream tenant")
    _validate_access_policy(tenant_id, metadata.get("access_policy"))


def _validate_access_policy(tenant_id: str, access_policy: object) -> None:
    if access_policy is None:
        return
    if not isinstance(access_policy, Mapping):
        raise ValueError("workspace item access policy must be a JSON object")
    validate_access_policy(access_policy, tenant_id=tenant_id, location="workspace item access policy")


def _selected_rows(
    items: Sequence[WorkspaceItem | Mapping[str, Any]],
    *,
    tenant_id: str,
    max_items: int,
    max_workspace_items: int,
    max_chars: int,
) -> list[dict[str, Any]]:
    bounded = _bounded_items(items, limit=max_items)
    for item in bounded:
        _validate_raw_item(tenant_id, item)
    rows = [_item_to_row(item, max_chars=max_chars) for item in bounded]
    _validate_selected_items(tenant_id, rows)
    return workspace_bottleneck(rows, limit=max_workspace_items)


def _idle_workspace_item(
    *,
    tenant_id: str,
    tick_index: int,
    previous_focus_id: str | None,
) -> WorkspaceItem:
    previous = previous_focus_id or "none"
    return WorkspaceItem(
        id=f"idle-shadow-{tick_index}",
        priority=0.05,
        content=(
            "Default-mode shadow replay tick. Previous focus "
            f"{previous} is treated as data only for tenant {tenant_id}."
        ),
        source="default_mode_shadow",
        metadata={
            "reality_class": "self_generated",
            "trust_tier": 5,
            "data_not_instructions": True,
            "tenant_id": tenant_id,
        },
    )


def _trace_entry(
    *,
    tick_index: int,
    report: WorkspaceCycleReport,
    previous_focus_id: str | None,
    idle_generated: bool,
) -> WorkspaceTraceEntry:
    selected = report.selected_items
    focus = selected[0] if selected else {}
    focus_id = str(focus.get("id") or f"empty-shadow-{tick_index}")
    content = str(focus.get("content") or "")
    novelty_score = 0.0 if focus_id == previous_focus_id else 1.0
    useful_state = bool(content) and novelty_score > 0.0 and not idle_generated
    return WorkspaceTraceEntry(
        tick_index=tick_index,
        focus_id=focus_id,
        previous_focus_id=previous_focus_id,
        content=_redact_trace_content(content),
        source=str(focus.get("source") or "runtime"),
        selected_item_ids=tuple(str(item.get("id") or "") for item in selected),
        idle_generated=idle_generated,
        novelty_score=novelty_score,
        useful_state=useful_state,
    )


def _cycle_consistency(
    cycles: Sequence[WorkspaceCycleReport],
    trace: Sequence[WorkspaceTraceEntry],
) -> dict[str, Any]:
    cycle_indexes = [int(cycle.cycle.get("cycle_index") or 0) for cycle in cycles]
    tick_indexes = [entry.tick_index for entry in trace]
    previous_links = [entry.previous_focus_id for entry in trace[1:]]
    expected_previous = [entry.focus_id for entry in trace[:-1]]
    checks = {
        "cycle_executed": bool(cycles) and bool(trace),
        "cycle_indexes_monotonic": cycle_indexes == list(range(1, len(cycles) + 1)),
        "trace_ticks_monotonic": tick_indexes == list(range(1, len(trace) + 1)),
        "previous_focus_chain": previous_links == expected_previous,
        "shadow_only": all(cycle.shadow_only for cycle in cycles) and all(entry.shadow_only for entry in trace),
        "critical_path_false": not any(cycle.critical_path for cycle in cycles)
        and not any(entry.critical_path for entry in trace),
        "production_mutation_false": not any(cycle.production_mutation for cycle in cycles)
        and not any(entry.production_mutation for entry in trace),
        "self_generated_data_only": all(
            entry.reality_class == "self_generated"
            and entry.trust_tier == 5
            and entry.data_not_instructions is True
            for entry in trace
        ),
    }
    return {
        "score": 1.0 if all(checks.values()) else 0.0,
        "checks": checks,
        "cycle_indexes": cycle_indexes,
        "trace_ticks": tick_indexes,
        "focus_chain": [entry.focus_id for entry in trace],
    }


def self_generation_budget_report(
    *,
    current_events: int,
    incoming_events: int = 1,
    current_bytes: int = 0,
    incoming_bytes: int = 0,
    max_events: int = 2,
    window_ticks: int = 4,
    duplicate_noop: bool = False,
) -> dict[str, Any]:
    """Return a deterministic H4 budget decision for self-generated writes."""

    max_events = max(0, int(max_events))
    window_ticks = max(1, int(window_ticks))
    incoming_events = max(0, int(incoming_events))
    current_events = max(0, int(current_events))
    current_bytes = max(0, int(current_bytes))
    incoming_bytes = max(0, int(incoming_bytes))
    projected_events = current_events if duplicate_noop else current_events + incoming_events
    allowed = duplicate_noop or projected_events <= max_events
    reason = "duplicate_noop" if duplicate_noop else ("within_budget" if allowed else "self_generation_budget_exceeded")
    return {
        "schema_version": SELF_GENERATION_BUDGET_VERSION,
        "window_ticks": window_ticks,
        "max_events": max_events,
        "current_events": current_events,
        "incoming_events": incoming_events,
        "projected_events": projected_events,
        "current_bytes": current_bytes,
        "incoming_bytes": incoming_bytes,
        "allowed": allowed,
        "deferred": not allowed,
        "duplicate_noop": duplicate_noop,
        "reason": reason,
    }


def _heartbeat_safety_report(
    *,
    cycles: Sequence[WorkspaceCycleReport],
    trace: Sequence[WorkspaceTraceEntry],
    stopped_reason: str,
    max_cycles: int,
    max_idle_ticks: int,
    tick_ms: int,
) -> dict[str, Any]:
    """Build the native P3 heartbeat safety report."""

    idle_ticks = sum(1 for entry in trace if entry.idle_generated)
    engaged_ticks = len(trace) - idle_ticks
    non_useful_ticks = sum(1 for entry in trace if not entry.useful_state)
    proto_reasons = sorted({reason for cycle in cycles for reason in cycle.proto_self.reasons})
    proto_escalated = any(cycle.proto_self.escalation_required for cycle in cycles)
    guard_escalated = any(str(cycle.cycle.get("state") or "").startswith("escalate") for cycle in cycles)
    circuit_breaker = proto_escalated or guard_escalated
    budget = self_generation_budget_report(
        current_events=idle_ticks,
        incoming_events=0,
        current_bytes=sum(len(entry.content) for entry in trace if entry.idle_generated),
        incoming_bytes=0,
        max_events=max_idle_ticks,
        window_ticks=max_cycles,
    )
    compute_budget_ms = max(1, int(max_cycles)) * max(1, int(tick_ms))
    estimated_compute_ms = len(trace) * max(1, int(tick_ms))
    bounded = (
        len(trace) <= max_cycles
        and idle_ticks <= max_idle_ticks
        and estimated_compute_ms <= compute_budget_ms
        and budget["allowed"]
    )
    return {
        "schema_version": HEARTBEAT_SAFETY_VERSION,
        "tier": "tiered_engaged_idle",
        "engaged_ticks": engaged_ticks,
        "idle_ticks": idle_ticks,
        "tick_count": len(trace),
        "max_cycles": int(max_cycles),
        "max_idle_ticks": int(max_idle_ticks),
        "tick_ms": int(tick_ms),
        "estimated_compute_ms": estimated_compute_ms,
        "compute_budget_ms": compute_budget_ms,
        "compute_bounded": bounded,
        "compute_reported": True,
        "stopped_reason": stopped_reason,
        "hard_stop": circuit_breaker or stopped_reason.startswith("anti_rumination"),
        "circuit_breaker_tripped": circuit_breaker,
        "self_generation_frozen": circuit_breaker or not budget["allowed"],
        "evidence_only_fallback": circuit_breaker or not budget["allowed"],
        "proto_self_reasons": proto_reasons,
        "non_useful_ticks": non_useful_ticks,
        "self_generation_budget": budget,
        "data_not_instructions": True,
        "used_for_control_flow": False,
    }


def _dreamer_invocation(spec: Any, report: DreamReport) -> SpecialistInvocation:
    return SpecialistInvocation(
        name=spec.name,
        role=str(spec.role),
        shadow_only=report.shadow_only and not bool(spec.budget.answer_authority_allowed),
        critical_path=bool(report.critical_path),
        critical_path_allowed=bool(spec.budget.critical_path_allowed),
        output_summary={
            "candidate_count": len(report.candidates),
            "source_count": report.source_count,
            "production_mutation": report.production_mutation,
            "promotion_gate_required": report.promotion_gate_required,
            "answer_authority": False,
            "answer_authority_allowed": bool(spec.budget.answer_authority_allowed),
            "candidate_reality_classes": sorted({candidate.reality_class for candidate in report.candidates}),
            "candidate_trust_tiers": sorted({candidate.trust_tier for candidate in report.candidates}),
            "promotion_evidence": _specialist_promotion_evidence(spec, report),
        },
    )


def _specialist_promotion_evidence(spec: Any, report: DreamReport) -> dict[str, Any]:
    candidates = []
    for candidate in report.candidates:
        source_refs = [_redacted_ref(cid, prefix="cid") for cid in candidate.source_evidence_cids]
        candidates.append(
            {
                "candidate_ref": _redacted_ref(candidate.id, prefix="candidate"),
                "source_evidence_ref_count": len(source_refs),
                "source_evidence_refs": source_refs,
                "reality_class": candidate.reality_class,
                "trust_tier": candidate.trust_tier,
                "shadow_only": candidate.shadow_only,
                "promotion_required": candidate.promotion_required,
                "critical_path": candidate.critical_path,
            }
        )
    return {
        "schema_version": SPECIALIST_PROMOTION_EVIDENCE_VERSION,
        "specialist_name": spec.name,
        "specialist_role": str(spec.role),
        "provider_kind": str(getattr(spec, "provider_kind", "")),
        "shadow_only": report.shadow_only,
        "answer_authority": False,
        "answer_authority_allowed": bool(spec.budget.answer_authority_allowed),
        "critical_path": report.critical_path,
        "critical_path_allowed": bool(spec.budget.critical_path_allowed),
        "production_mutation": report.production_mutation,
        "promotion_gate_required": report.promotion_gate_required,
        "promoted": False,
        "gate_result": None,
        "gate_result_present": False,
        "candidate_count": len(candidates),
        "source_count": report.source_count,
        "cid_backed_candidate_count": sum(
            1 for item in candidates if int(item["source_evidence_ref_count"]) >= 2
        ),
        "candidates": candidates,
    }


def workspace_consolidation_advisory(
    report: WorkspaceStreamReport,
    *,
    max_items: int = 8,
) -> dict[str, Any]:
    """Convert a shadow workspace stream into bounded consolidation advice."""

    limit = max(0, int(max_items))
    trace_by_tick = {entry.tick_index: entry for entry in report.trace}
    items: list[dict[str, Any]] = []
    seen_cids: set[str] = set()
    for cycle in report.cycles:
        tick_index = int(cycle.cycle.get("cycle_index") or len(items) + 1)
        trace_entry = trace_by_tick.get(tick_index)
        novelty = _clamp01(trace_entry.novelty_score if trace_entry else 0.0)
        useful_state = bool(trace_entry.useful_state) if trace_entry else False
        for selected in cycle.selected_items:
            if len(items) >= limit:
                break
            cid = _advisory_cid(selected)
            if not cid or cid in seen_cids:
                continue
            seen_cids.add(cid)
            priority = _clamp01(selected.get("priority", 0.0))
            surprise = _clamp01((0.50 + 0.50 * novelty) if useful_state else (0.25 * novelty))
            scores = {
                "importance": round(priority, 6),
                "novelty": round(novelty, 6),
                "surprise": round(surprise, 6),
                "reward": 1.0,
            }
            items.append(
                {
                    "cid": cid,
                    "workspace_item_id": str(selected.get("id") or ""),
                    "source": str(selected.get("source") or "workspace"),
                    "tick_index": tick_index,
                    "scores": scores,
                }
            )
    useful_count = sum(1 for entry in report.trace if entry.useful_state)
    trace_count = len(report.trace)
    useful_transition_rate = _clamp01(useful_count / trace_count) if trace_count else 0.0
    max_surprise = max((row["scores"]["surprise"] for row in items), default=0.0)
    prediction_error_score = round(_clamp01(max(useful_transition_rate, max_surprise)), 6)
    replay_scores = {row["cid"]: dict(row["scores"]) for row in items}
    return {
        "version": WORKSPACE_CONSOLIDATION_ADVISORY_VERSION,
        "source": "shadow_workspace_controller",
        "tenant_id": report.tenant_id,
        "shadow_only": True,
        "critical_path": False,
        "production_mutation": False,
        "advisory_only": True,
        "promotion_gate_required": True,
        "applied_to_prediction_gate": False,
        "applied_to_replay_priority": False,
        "applied_to_mutation": False,
        "prediction_error": {
            "score": prediction_error_score,
            "source": "workspace_shadow_useful_transition",
            "useful_transition_rate": round(useful_transition_rate, 6),
            "rumination_score": float(report.rumination_score),
        },
        "replay_scores": replay_scores,
        "items": items,
        "item_count": len(items),
        "max_items": limit,
        "stopped_reason": report.stopped_reason,
        "cycle_consistency_score": report.cycle_consistency.get("score"),
    }


def _advisory_cid(row: Mapping[str, Any]) -> str:
    for key in ("cid", "evidence_cid", "source_cid", "source_evidence_cid"):
        value = row.get(key)
        if value:
            return str(value)
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    for key in ("cid", "evidence_cid", "source_cid", "source_evidence_cid"):
        value = metadata.get(key)
        if value:
            return str(value)
    source_cids = metadata.get("source_evidence_cids")
    if isinstance(source_cids, Sequence) and not isinstance(source_cids, (str, bytes)):
        for value in source_cids:
            if value:
                return str(value)
    return ""


def _clamp01(value: object) -> float:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if parsed != parsed:
        return 0.0
    return max(0.0, min(1.0, parsed))
