"""Shadow workspace controller over typed specialist modules.

The workspace controller is advisory by construction. It can recruit specialists
registered in :mod:`mnemosyne.providers`, but it cannot place shadow-only
specialists on the answer critical path or mutate production memory.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
from itertools import islice
from typing import Any, Iterable, Mapping, Sequence

from .consciousness import BoundedCognitiveCycle, InteroceptiveProtoSelf, ProtoSelfSnapshot, workspace_bottleneck
from .dreamer import DreamReport, SandboxedDreamer
from .models import Evidence
from .providers import SpecialistModuleRegistry, default_registry

WORKSPACE_CONSOLIDATION_ADVISORY_VERSION = "workspace-consolidation-advisory.v1"
SPECIALIST_PROMOTION_EVIDENCE_VERSION = "specialist-promotion-evidence.v1"


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
    shadow_only: bool = True
    critical_path: bool = False
    production_mutation: bool = False
    promotion_gate_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["cycles"] = [cycle.to_dict() for cycle in self.cycles]
        data["trace"] = [entry.to_dict() for entry in self.trace]
        return data

    def to_consolidation_advisory(self, *, max_items: int = 8) -> dict[str, Any]:
        """Return bounded shadow-only consolidation advice.

        The advisory is evidence for a future promotion gate. It intentionally
        does not authorize production mutation or live consolidation steering.
        """

        return workspace_consolidation_advisory(self, max_items=max_items)


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
        return WorkspaceStreamReport(
            tenant_id=tenant_id,
            cycles=tuple(cycles),
            trace=tuple(trace),
            cycle_consistency=_cycle_consistency(cycles, trace),
            stopped_reason=stopped_reason,
            idle_ticks=idle_ticks,
            rumination_score=round(non_useful_ticks / total_ticks, 6),
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
        if evidence and cycle_guard.cycle_index == 1:
            spec = self.registry.specialist(self.dreamer_name)
            if str(spec.role) != "dreamer":
                raise ValueError(f"{self.dreamer_name} must have dreamer role")
            if not spec.budget.shadow_only:
                raise ValueError(f"{self.dreamer_name} must remain shadow-only")
            if spec.budget.critical_path_allowed:
                raise ValueError(f"{self.dreamer_name} must remain off the critical path")
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
    if isinstance(access_policy, Mapping):
        policy_tenant = access_policy.get("tenant")
        if policy_tenant is not None and str(policy_tenant) != tenant_id:
            raise ValueError("workspace item access policy does not match stream tenant")


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
