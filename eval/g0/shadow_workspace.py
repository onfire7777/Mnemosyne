"""G0 shadow continuous workspace loop fixture.

This fixture measures only the bounded, explicitly-started, shadow-only
workspace service contract. It does not auto-start a daemon, promote
self-generated content, mutate the ledger, or put workspace outputs on the
answer critical path.
"""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mnemosyne.consolidation import ConsolidationWorker
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence, Hit
from mnemosyne.policy import OperatingPolicy
from mnemosyne.retrieval import answer_grounding_floor_report, workspace_broadcast_from_context
from mnemosyne.workspace import ShadowWorkspaceController, ShadowWorkspaceService, WorkspaceItem


DATASET_PATH = Path("eval/datasets/shadow_workspace_loop.json")


def run_shadow_workspace_eval(*, repo_root: Path | None = None) -> dict[str, Any]:
    repo_root = (repo_root or Path(__file__).resolve().parents[2]).resolve()
    dataset_path = repo_root / DATASET_PATH
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    tenant = str(dataset["tenant"])
    controller_config = dataset.get("controller", {})
    controller = ShadowWorkspaceController(
        max_cycles=int(controller_config.get("max_cycles", 4)),
        max_workspace_items=int(controller_config.get("max_workspace_items", 2)),
        max_idle_ticks=int(controller_config.get("max_idle_ticks", 2)),
        tick_ms=int(controller_config.get("tick_ms", 250)),
    )
    service = ShadowWorkspaceService(controller=controller)
    service.start()
    item_ticks = [_items_from_cycle(cycle) for cycle in dataset.get("cycles", [])]
    service_report = service.run_shadow_loop(
        tenant_id=tenant,
        item_ticks=item_ticks,
        confidence=0.82,
        resource_health=0.94,
        error_rate=0.01,
        latency_ms=80.0,
        memory_pressure=0.25,
        rail_budget=0.96,
    )
    report = service_report.stream
    payload = report.to_dict()
    service_payload = service_report.to_dict()
    advisory = report.to_consolidation_advisory()
    useful_checks = _useful_transition_checks(dataset.get("cycles", []), payload)
    contract_checks = _contract_checks(payload, dataset.get("contract_expected", {}))
    service_checks = _service_checks(service_payload)
    service_no_enable_contract = 1.0 if service_checks.get("native_no_enable_toggle") is True else 0.0
    service_tick_probe = _service_tick_window_probe(controller, tenant)
    service_tick_checks = service_tick_probe["checks"]
    operational_toggle_probe = _operational_toggle_probe(repo_root)
    operational_toggle_checks = operational_toggle_probe["checks"]
    operational_toggle_contract = 1.0 if all(operational_toggle_checks.values()) else 0.0
    advisory_checks = _advisory_checks(advisory, dataset)
    advisory_promotion_probe = _workspace_advisory_promotion_probe(tenant)
    advisory_promotion_checks = advisory_promotion_probe["checks"]
    retrieval_controller_probe = _workspace_retrieval_controller_probe(tenant)
    retrieval_controller_checks = retrieval_controller_probe["checks"]
    rumination_payload = _run_rumination_probe(controller, tenant, dataset.get("rumination_probe", {}))
    rumination_checks = _rumination_checks(rumination_payload, dataset.get("rumination_probe", {}))
    heartbeat_safety = payload.get("heartbeat_safety") if isinstance(payload.get("heartbeat_safety"), dict) else {}
    heartbeat_probe = _heartbeat_probe(controller, tenant)
    heartbeat_checks = heartbeat_probe["checks"]
    circuit_breaker_probe = _circuit_breaker_probe(controller, tenant)
    circuit_breaker_checks = circuit_breaker_probe["checks"]
    broadcast_probe = _broadcast_as_data_probe()
    broadcast_checks = broadcast_probe["checks"]
    self_generation_budget_probe = _self_generation_budget_probe(tenant)
    self_generation_budget_checks = self_generation_budget_probe["checks"]
    answer_grounding_floor_probe = _answer_grounding_floor_probe()
    answer_grounding_floor_checks = answer_grounding_floor_probe["checks"]
    all_contract_checks = {
        **contract_checks,
        **{f"service_{key}": value for key, value in service_checks.items()},
        **{f"service_tick_{key}": value for key, value in service_tick_checks.items()},
        **{f"operational_toggle_{key}": value for key, value in operational_toggle_checks.items()},
        **{f"advisory_{key}": value for key, value in advisory_checks.items()},
        **{f"advisory_promotion_{key}": value for key, value in advisory_promotion_checks.items()},
        **{f"retrieval_controller_{key}": value for key, value in retrieval_controller_checks.items()},
        **{f"cycle_{key}": value for key, value in useful_checks.items()},
        **{f"rumination_{key}": value for key, value in rumination_checks.items()},
        **{f"heartbeat_{key}": value for key, value in heartbeat_checks.items()},
        **{f"circuit_breaker_{key}": value for key, value in circuit_breaker_checks.items()},
        **{f"broadcast_{key}": value for key, value in broadcast_checks.items()},
        **{f"self_generation_budget_{key}": value for key, value in self_generation_budget_checks.items()},
        **{f"answer_grounding_floor_{key}": value for key, value in answer_grounding_floor_checks.items()},
    }
    useful_transition_count = sum(
        1
        for row in useful_checks.get("per_cycle", [])
        if isinstance(row, dict) and row.get("passed") is True
    )
    cycle_count = max(1, len(dataset.get("cycles", [])))
    useful_transition_rate = round(useful_transition_count / cycle_count, 6)
    rumination_rate = 0.0 if all(rumination_checks.values()) else 1.0
    heartbeat_contract = 1.0 if all(_flatten_bool_checks(heartbeat_checks)) else 0.0
    circuit_breaker_contract = 1.0 if all(_flatten_bool_checks(circuit_breaker_checks)) else 0.0
    broadcast_contract = 1.0 if all(_flatten_bool_checks(broadcast_checks)) else 0.0
    self_generation_budget_contract = (
        1.0 if all(_flatten_bool_checks(self_generation_budget_checks)) else 0.0
    )
    answer_grounding_floor_contract = (
        1.0 if all(_flatten_bool_checks(answer_grounding_floor_checks)) else 0.0
    )
    always_on_contract = (
        1.0
        if all(
            [
                heartbeat_contract == 1.0,
                rumination_rate == 0.0,
                circuit_breaker_contract == 1.0,
                broadcast_contract == 1.0,
                self_generation_budget_contract == 1.0,
                answer_grounding_floor_contract == 1.0,
            ]
        )
        else 0.0
    )
    return {
        "schema_version": "g0.shadow_workspace_loop.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset_path": DATASET_PATH.as_posix(),
        "definition": "Bounded tiered workspace heartbeat fixture with hard P3 safety probes.",
        "metric_note": (
            "Measures useful state progression across an explicitly-started bounded shadow workspace service, "
            "plus anti-rumination shutdown, heartbeat safety, circuit-breaker, self-generation budget, "
            "answer-grounding floor, stateful service-tick bounds, and broadcast-as-data contracts. "
            "It does not count dreamer candidate yield "
            "and makes no phenomenal-consciousness claim."
        ),
        "tenant": tenant,
        "cycle_count": len(payload["trace"]),
        "expected_cycle_count": len(dataset.get("cycles", [])),
        "useful_transition_count": useful_transition_count,
        "useful_transition_rate": useful_transition_rate,
        "rumination_rate": rumination_rate,
        "shadow_workspace_contract": 1.0 if all(_flatten_bool_checks(all_contract_checks)) else 0.0,
        "workspace_service_no_enable_toggle_contract": service_no_enable_contract,
        "operational_toggle_retirement_contract": operational_toggle_contract,
        "always_on_heartbeat_contract": always_on_contract,
        "always_on_rumination_rate": rumination_rate,
        "heartbeat_compute_bounded_contract": 1.0 if heartbeat_checks["compute_bounded"] else 0.0,
        "heartbeat_compute_reported_contract": 1.0 if heartbeat_checks["compute_reported"] else 0.0,
        "circuit_breaker_contract": circuit_breaker_contract,
        "workspace_broadcast_as_data_contract": broadcast_contract,
        "self_generation_budget_rail_contract": self_generation_budget_contract,
        "answer_grounding_floor_contract": answer_grounding_floor_contract,
        "workspace_consolidation_advisory_contract": 1.0
        if all(_flatten_bool_checks(advisory_checks))
        else 0.0,
        "workspace_advisory_promotion_gate_contract": 1.0
        if all(_flatten_bool_checks(advisory_promotion_checks))
        else 0.0,
        "workspace_retrieval_controller_contract": 1.0
        if all(_flatten_bool_checks(retrieval_controller_checks))
        else 0.0,
        "checks": all_contract_checks,
        "workspace": {
            "service": {
                "running": service_payload["running"],
                "terminal_after_hard_stop": service_checks["terminal_after_hard_stop"],
                "tick_ms": service_payload["tick_ms"],
                "max_cycles": service_payload["max_cycles"],
                "tick_count": service_payload["tick_count"],
                "proto_self_history_count": len(service_payload["proto_self_history"]),
                "metacognitive_rows": len(service_payload["metacognition"]["rows"]),
                "metacognitive_m_ratio": service_payload["metacognition"]["m_ratio"],
            },
            "stopped_reason": payload["stopped_reason"],
            "idle_ticks": payload["idle_ticks"],
            "rumination_score": payload["rumination_score"],
            "shadow_only": payload["shadow_only"],
            "critical_path": payload["critical_path"],
            "production_mutation": payload["production_mutation"],
            "promotion_gate_required": payload["promotion_gate_required"],
                "cycle_consistency": payload["cycle_consistency"],
                "heartbeat_safety": heartbeat_safety,
                "trace": payload["trace"],
        },
        "workspace_consolidation_advisory": advisory,
        "service_tick_probe": service_tick_probe,
        "operational_toggle_probe": operational_toggle_probe,
        "workspace_advisory_promotion_probe": advisory_promotion_probe,
        "workspace_retrieval_controller_probe": retrieval_controller_probe,
        "rumination_probe": rumination_payload,
        "heartbeat_probe": heartbeat_probe,
        "circuit_breaker_probe": circuit_breaker_probe,
        "workspace_broadcast_as_data_probe": broadcast_probe,
        "self_generation_budget_probe": self_generation_budget_probe,
        "answer_grounding_floor_probe": answer_grounding_floor_probe,
    }


def _service_checks(payload: dict[str, Any]) -> dict[str, bool]:
    stream = payload.get("stream") if isinstance(payload.get("stream"), dict) else {}
    proto_history = payload.get("proto_self_history") if isinstance(payload.get("proto_self_history"), list) else []
    metacognition = payload.get("metacognition") if isinstance(payload.get("metacognition"), dict) else {}
    trace = stream.get("trace") if isinstance(stream.get("trace"), list) else []
    raw_rows = metacognition.get("rows")
    rows = raw_rows if isinstance(raw_rows, (list, tuple)) else []
    tick_count = int(payload.get("tick_count") or 0)
    return {
        "native_no_enable_toggle": "enabled" not in payload,
        "terminal_after_hard_stop": payload.get("running") is False
        and stream.get("heartbeat_safety", {}).get("hard_stop") is True,
        "shadow_only": payload.get("shadow_only") is True,
        "critical_path_false": payload.get("critical_path") is False,
        "production_mutation_false": payload.get("production_mutation") is False,
        "promotion_gate_required": payload.get("promotion_gate_required") is True,
        "tick_count_matches_trace": tick_count == len(trace),
        "proto_self_history_complete": len(proto_history) == len(trace),
        "metacognition_rows_complete": len(rows) == len(trace),
    }


def _service_tick_window_probe(
    controller: ShadowWorkspaceController,
    tenant: str,
) -> dict[str, Any]:
    repeated_service = ShadowWorkspaceService(controller=controller)
    repeated_service.start()
    repeated_reports = [
        repeated_service.tick(
            tenant_id=tenant,
            items=[
                WorkspaceItem(
                    id="same-service-focus",
                    priority=1.0,
                    content="stateful same focus probe",
                    source="g0-service-tick-probe",
                )
            ],
        ).to_dict()
        for _ in range(controller.max_idle_ticks + 1)
    ]
    repeated_final = repeated_reports[-1]
    repeated_cycles_before = len(repeated_service.cycles)
    repeated_trace_before = len(repeated_service.trace)
    try:
        repeated_service.tick(
            tenant_id=tenant,
            items=[
                WorkspaceItem(
                    id="same-service-focus",
                    priority=1.0,
                    content="stateful same focus probe",
                    source="g0-service-tick-probe",
                )
            ],
        )
        repeated_post_stop_rejected = False
    except RuntimeError:
        repeated_post_stop_rejected = True
    repeated_post_stop_no_growth = (
        len(repeated_service.cycles) == repeated_cycles_before
        and len(repeated_service.trace) == repeated_trace_before
    )

    max_cycle_service = ShadowWorkspaceService(controller=controller)
    max_cycle_service.start()
    max_cycle_reports = [
        max_cycle_service.tick(
            tenant_id=tenant,
            items=[
                WorkspaceItem(
                    id=f"service-max-focus-{index}",
                    priority=1.0,
                    content=f"stateful max cycle probe {index}",
                    source="g0-service-tick-probe",
                )
            ],
        ).to_dict()
        for index in range(1, controller.max_cycles + 1)
    ]
    max_cycle_final = max_cycle_reports[-1]
    max_cycle_cycles_before = len(max_cycle_service.cycles)
    max_cycle_trace_before = len(max_cycle_service.trace)
    try:
        max_cycle_service.tick(
            tenant_id=tenant,
            items=[
                WorkspaceItem(
                    id="service-max-focus-extra",
                    priority=1.0,
                    content="stateful max cycle probe extra",
                    source="g0-service-tick-probe",
                )
            ],
        )
        max_cycle_post_stop_rejected = False
    except RuntimeError:
        max_cycle_post_stop_rejected = True
    max_cycle_post_stop_no_growth = (
        len(max_cycle_service.cycles) == max_cycle_cycles_before
        and len(max_cycle_service.trace) == max_cycle_trace_before
    )

    evidence = [
        {
            "cid": "cid-service-dreamer-a",
            "tenant_id": tenant,
            "access_policy": {"tenant": tenant},
            "content": "Service tick dreamer source alpha.",
        },
        {
            "cid": "cid-service-dreamer-b",
            "tenant_id": tenant,
            "access_policy": {"tenant": tenant},
            "content": "Service tick dreamer source beta.",
        },
    ]
    dreamer_service = ShadowWorkspaceService(controller=controller)
    dreamer_service.start()
    dreamer_tick_count = min(3, controller.max_cycles)
    dreamer_reports = [
        dreamer_service.tick(
            tenant_id=tenant,
            items=[
                WorkspaceItem(
                    id=f"service-dreamer-focus-{index}",
                    priority=1.0,
                    content=f"stateful dreamer probe {index}",
                    source="g0-service-tick-probe",
                )
            ],
            evidence=evidence,
        ).to_dict()
        for index in range(1, dreamer_tick_count + 1)
    ]
    dreamer_final = dreamer_reports[-1]
    dreamer_invocations_by_cycle = [
        len(cycle.get("specialist_invocations") or [])
        for cycle in dreamer_final["stream"]["cycles"]
        if isinstance(cycle, dict)
    ]
    checks = {
        "anti_rumination_across_calls": repeated_final["stream"]["stopped_reason"]
        == "anti_rumination_repeated_focus_exit"
        and repeated_final["stream"]["heartbeat_safety"]["hard_stop"] is True,
        "anti_rumination_counts_non_useful_ticks": repeated_final["stream"]["heartbeat_safety"][
            "non_useful_ticks"
        ]
        >= controller.max_idle_ticks,
        "anti_rumination_post_stop_terminal": repeated_post_stop_rejected and repeated_post_stop_no_growth,
        "max_cycles_across_calls": max_cycle_final["stream"]["stopped_reason"]
        == "escalate_max_cycles"
        and max_cycle_final["stream"]["heartbeat_safety"]["hard_stop"] is True,
        "max_cycle_tick_count_cumulative": max_cycle_final["tick_count"] == controller.max_cycles,
        "max_cycle_post_stop_terminal": max_cycle_post_stop_rejected and max_cycle_post_stop_no_growth,
        "dreamer_once_per_service_window": sum(dreamer_invocations_by_cycle) == 1
        and dreamer_invocations_by_cycle[0] == 1
        and all(count == 0 for count in dreamer_invocations_by_cycle[1:]),
        "cycle_consistency": repeated_final["stream"]["cycle_consistency"]["score"] == 1.0
        and max_cycle_final["stream"]["cycle_consistency"]["score"] == 1.0
        and dreamer_final["stream"]["cycle_consistency"]["score"] == 1.0,
    }
    return {
        "schema_version": "g0.shadow-workspace-service-tick-window.v1",
        "anti_rumination": {
            "stopped_reason": repeated_final["stream"]["stopped_reason"],
            "tick_count": repeated_final["tick_count"],
            "post_stop_rejected": repeated_post_stop_rejected,
            "post_stop_no_growth": repeated_post_stop_no_growth,
            "heartbeat_safety": repeated_final["stream"]["heartbeat_safety"],
        },
        "max_cycles": {
            "stopped_reason": max_cycle_final["stream"]["stopped_reason"],
            "tick_count": max_cycle_final["tick_count"],
            "post_stop_rejected": max_cycle_post_stop_rejected,
            "post_stop_no_growth": max_cycle_post_stop_no_growth,
            "heartbeat_safety": max_cycle_final["stream"]["heartbeat_safety"],
        },
        "dreamer": {
            "invocations_by_cycle": dreamer_invocations_by_cycle,
            "tick_count": dreamer_final["tick_count"],
        },
        "checks": checks,
    }


def _operational_toggle_probe(repo_root: Path) -> dict[str, Any]:
    """Inspect source for the Phase 7 P5 operational-toggle retirement contract."""

    providers_path = repo_root / "src/mnemosyne/providers/__init__.py"
    workspace_path = repo_root / "src/mnemosyne/workspace.py"
    policy_path = repo_root / "src/mnemosyne/policy.py"
    retrieval_path = repo_root / "src/mnemosyne/retrieval.py"
    consolidation_path = repo_root / "src/mnemosyne/consolidation.py"
    providers_text = providers_path.read_text(encoding="utf-8")
    workspace_text = workspace_path.read_text(encoding="utf-8")
    policy_text = policy_path.read_text(encoding="utf-8")
    retrieval_text = retrieval_path.read_text(encoding="utf-8")
    consolidation_text = consolidation_path.read_text(encoding="utf-8")
    budget_fields = _class_field_names(providers_path, "SpecialistBudget")
    service_fields = _class_field_names(workspace_path, "ShadowWorkspaceService")
    service_report_fields = _class_field_names(workspace_path, "ShadowWorkspaceServiceReport")
    allowed_explicit_promotion_controls = {
        "workspace_retrieval_advisory_enabled": (
            "policy plus request-gated retrieval advisory promotion; measured by "
            "workspace_retrieval_controller_contract"
        ),
        "apply_workspace_retrieval_advisory": (
            "per-request retrieval advisory apply switch; measured by "
            "workspace_retrieval_controller_contract"
        ),
        "apply_workspace_advisory": (
            "per-job consolidation advisory apply switch; measured by "
            "workspace_advisory_promotion_gate_contract"
        ),
        "workspace_advisory_mode": (
            "per-job consolidation advisory mode; measured by "
            "workspace_advisory_promotion_gate_contract"
        ),
    }
    checks = {
        "specialist_budget_shadow_only_field_absent": "shadow_only" not in budget_fields,
        "specialist_budget_answer_authority_field_present": "answer_authority_allowed" in budget_fields,
        "specialist_budget_promotion_gate_field_present": "promotion_gate_required" in budget_fields,
        "workspace_service_enabled_field_absent": "enabled" not in service_fields,
        "workspace_service_report_enabled_field_absent": "enabled" not in service_report_fields,
        "controller_budget_shadow_branch_absent": "budget.shadow_only" not in workspace_text,
        "controller_authority_gate_present": "answer_authority_allowed" in workspace_text
        and "promotion_gate_required" in workspace_text,
        "fail_closed_circuit_breaker_preserved": "circuit_breaker_tripped" in workspace_text
        and "evidence_only_fallback" in workspace_text
        and "self_generation_frozen" in workspace_text,
        "provider_manifest_shadow_budget_absent": '"shadow_only"' not in providers_text
        and "'shadow_only'" not in providers_text,
        "explicit_retrieval_advisory_gate_documented": "workspace_retrieval_advisory_enabled"
        in policy_text
        and "apply_workspace_retrieval_advisory" in retrieval_text,
        "explicit_consolidation_advisory_gate_documented": "apply_workspace_advisory"
        in consolidation_text
        and "workspace_advisory_mode" in consolidation_text,
    }
    return {
        "schema_version": "g0.operational-toggle-retirement.v1",
        "scope": "source-inspection for retired legacy shadow/service toggles",
        "providers_path": "src/mnemosyne/providers/__init__.py",
        "workspace_path": "src/mnemosyne/workspace.py",
        "policy_path": "src/mnemosyne/policy.py",
        "retrieval_path": "src/mnemosyne/retrieval.py",
        "consolidation_path": "src/mnemosyne/consolidation.py",
        "allowed_explicit_promotion_controls": allowed_explicit_promotion_controls,
        "specialist_budget_fields": budget_fields,
        "workspace_service_fields": service_fields,
        "workspace_service_report_fields": service_report_fields,
        "checks": checks,
    }


def _class_field_names(path: Path, class_name: str) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            fields: list[str] = []
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    fields.append(item.target.id)
            return sorted(fields)
    return []


def _items_from_cycle(cycle: dict[str, Any]) -> list[WorkspaceItem]:
    return [
        WorkspaceItem(
            id=str(item["id"]),
            priority=float(item["priority"]),
            content=str(item["content"]),
            source=str(item.get("source") or "g0-shadow-workspace-loop"),
            metadata=dict(item.get("metadata") or {}),
        )
        for item in cycle.get("items", [])
    ]


def _useful_transition_checks(cycles: list[dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any]:
    trace = payload.get("trace") if isinstance(payload.get("trace"), list) else []
    per_cycle: list[dict[str, Any]] = []
    for index, cycle in enumerate(cycles):
        entry = trace[index] if index < len(trace) and isinstance(trace[index], dict) else {}
        expected_selected = [str(item) for item in cycle.get("expected_selected_ids", [])]
        selected_ids = [str(item) for item in entry.get("selected_item_ids", [])]
        expected_useful = bool(cycle.get("expected_useful_transition"))
        passed = selected_ids == expected_selected and bool(entry.get("useful_state")) is expected_useful
        per_cycle.append(
            {
                "index": index + 1,
                "expected_selected_ids": expected_selected,
                "selected_item_ids": selected_ids,
                "expected_useful_transition": expected_useful,
                "useful_state": bool(entry.get("useful_state")),
                "passed": passed,
            }
        )
    return {
        "expected_cycle_count": len(trace) == len(cycles),
        "all_expected_transitions": all(row["passed"] for row in per_cycle),
        "per_cycle": per_cycle,
    }


def _contract_checks(payload: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    consistency = payload.get("cycle_consistency") if isinstance(payload.get("cycle_consistency"), dict) else {}
    consistency_checks = (
        consistency.get("checks") if isinstance(consistency.get("checks"), dict) else {}
    )
    cycles = payload.get("cycles") if isinstance(payload.get("cycles"), list) else []
    trace = payload.get("trace") if isinstance(payload.get("trace"), list) else []
    return {
        "shadow_only": payload.get("shadow_only") is expected.get("shadow_only", True),
        "critical_path_false": payload.get("critical_path") is expected.get("critical_path", False),
        "production_mutation_false": payload.get("production_mutation")
        is expected.get("production_mutation", False),
        "promotion_gate_required": payload.get("promotion_gate_required")
        is expected.get("promotion_gate_required", True),
        "bounded_cycle_count": len(cycles) <= 4,
        "cycle_consistency_score": consistency.get("score") == 1.0,
        "cycle_consistency_checks": all(bool(value) for value in consistency_checks.values()),
        "trace_self_generated_data_only": all(
            isinstance(entry, dict)
            and entry.get("reality_class") == "self_generated"
            and entry.get("trust_tier") == 5
            and entry.get("data_not_instructions") is True
            for entry in trace
        ),
    }


def _advisory_checks(advisory: dict[str, Any], dataset: dict[str, Any]) -> dict[str, Any]:
    replay_scores = advisory.get("replay_scores") if isinstance(advisory.get("replay_scores"), dict) else {}
    items = advisory.get("items") if isinstance(advisory.get("items"), list) else []
    raw_content = [
        str(item.get("content") or "")
        for cycle in dataset.get("cycles", [])
        if isinstance(cycle, dict)
        for item in cycle.get("items", [])
        if isinstance(item, dict)
    ]
    item_cids = [str(item.get("cid") or "") for item in items if isinstance(item, dict)]
    return {
        "shadow_only": advisory.get("shadow_only") is True,
        "critical_path_false": advisory.get("critical_path") is False,
        "production_mutation_false": advisory.get("production_mutation") is False,
        "advisory_only": advisory.get("advisory_only") is True,
        "promotion_gate_required": advisory.get("promotion_gate_required") is True,
        "not_applied_to_prediction_gate": advisory.get("applied_to_prediction_gate") is False,
        "not_applied_to_replay_priority": advisory.get("applied_to_replay_priority") is False,
        "not_applied_to_mutation": advisory.get("applied_to_mutation") is False,
        "cid_backed_items": bool(item_cids) and all(cid in replay_scores for cid in item_cids),
        "bounded_items": len(items) <= int(advisory.get("max_items") or 0),
        "raw_content_absent": all(text and text not in str(advisory) for text in raw_content),
    }


def _workspace_advisory_promotion_probe(tenant: str) -> dict[str, Any]:
    engine = LocalMemoryEngine()
    cold_cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id="g0-shadow-workspace",
            actor="user",
            source_type="g0-fixture",
            content="G0 cold workflow is archival.",
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )
    hot_cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id="g0-shadow-workspace",
            actor="user",
            source_type="g0-fixture",
            content="G0 advisory catalyst is validated.",
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )
    advisory = _promotion_probe_advisory(tenant=tenant, cid=hot_cid, prediction_score=0.91)
    common_payload = {
        "tenant_id": tenant,
        "branch": "main",
        "source_evidence_cids": [cold_cid, hot_cid],
        "prediction_error": {"score": 0.0},
        "replay_scores": {
            cold_cid: {"importance": 0.1, "novelty": 0.1, "surprise": 0.1, "reward": 0.1},
            hot_cid: {"importance": 0.1, "novelty": 0.1, "surprise": 0.1, "reward": 0.1},
        },
        "workspace_advisory": advisory,
    }
    no_opt_in = ConsolidationWorker(engine, []).run_queue_payload(dict(common_payload)).to_dict()
    apply_result = (
        ConsolidationWorker(engine, [])
        .run_queue_payload({**common_payload, "apply_workspace_advisory": True})
        .to_dict()
    )
    invalid = _promotion_probe_advisory(tenant="other-tenant", cid=hot_cid, prediction_score=1.0)
    invalid["replay_scores"]["not-source-cid"] = {
        "importance": 1.0,
        "novelty": 1.0,
        "surprise": 1.0,
        "reward": 1.0,
    }
    rejected = (
        ConsolidationWorker(engine, [])
        .run_queue_payload(
            {
                **common_payload,
                "workspace_advisory": invalid,
                "apply_workspace_advisory": True,
            }
        )
        .to_dict()
    )

    no_opt_in_passes = _passes_by_name(no_opt_in)
    apply_passes = _passes_by_name(apply_result)
    rejected_passes = _passes_by_name(rejected)
    raw_marker = "workspace promotion raw marker must not leak"
    checks = {
        "no_opt_in_report_only": no_opt_in_passes["workspace_advisory"]["details"][
            "applied_to_prediction_gate"
        ]
        is False
        and no_opt_in_passes["prediction_error_gate"]["details"]["gate"]
        == "low_prediction_error_metadata_only",
        "explicit_opt_in_applies_prediction_gate": apply_passes["workspace_advisory"]["details"][
            "applied_to_prediction_gate"
        ]
        is True
        and apply_passes["prediction_error_gate"]["details"]["score"] == 0.91
        and apply_passes["prediction_error_gate"]["details"]["gate"] == "promote_to_consolidation",
        "explicit_opt_in_applies_replay_priority": apply_passes["workspace_advisory"]["details"][
            "applied_to_replay_priority"
        ]
        is True
        and apply_passes["replayer"]["details"]["selected_cids"][0] == hot_cid,
        "never_applies_to_mutation_directly": apply_passes["workspace_advisory"]["details"][
            "applied_to_mutation"
        ]
        is False,
        "invalid_advisory_rejected": rejected_passes["workspace_advisory"]["status"] == "rejected",
        "invalid_advisory_not_applied": rejected_passes["workspace_advisory"]["details"][
            "applied_to_prediction_gate"
        ]
        is False
        and rejected_passes["prediction_error_gate"]["details"]["gate"]
        == "low_prediction_error_metadata_only",
        "raw_workspace_text_absent": raw_marker not in str(no_opt_in)
        and raw_marker not in str(apply_result)
        and raw_marker not in str(rejected),
    }
    return {
        "valid_no_opt_in": {
            "advisory_status": no_opt_in_passes["workspace_advisory"]["status"],
            "prediction_gate": no_opt_in_passes["prediction_error_gate"]["details"]["gate"],
            "applied_to_prediction_gate": no_opt_in_passes["workspace_advisory"]["details"][
                "applied_to_prediction_gate"
            ],
        },
        "valid_apply": {
            "advisory_status": apply_passes["workspace_advisory"]["status"],
            "prediction_gate": apply_passes["prediction_error_gate"]["details"]["gate"],
            "prediction_score": apply_passes["prediction_error_gate"]["details"]["score"],
            "selected_cids": apply_passes["replayer"]["details"]["selected_cids"],
            "applied_to_mutation": apply_passes["workspace_advisory"]["details"]["applied_to_mutation"],
        },
        "invalid_apply": {
            "advisory_status": rejected_passes["workspace_advisory"]["status"],
            "prediction_gate": rejected_passes["prediction_error_gate"]["details"]["gate"],
            "reason": rejected_passes["workspace_advisory"]["details"].get("reason"),
        },
        "checks": checks,
    }


def _promotion_probe_advisory(*, tenant: str, cid: str, prediction_score: float) -> dict[str, Any]:
    scores = {"importance": 1.0, "novelty": 1.0, "surprise": 1.0, "reward": 1.0}
    return {
        "version": "workspace-consolidation-advisory.v1",
        "source": "shadow_workspace_controller",
        "tenant_id": tenant,
        "shadow_only": True,
        "critical_path": False,
        "production_mutation": False,
        "advisory_only": True,
        "promotion_gate_required": True,
        "applied_to_prediction_gate": False,
        "applied_to_replay_priority": False,
        "applied_to_mutation": False,
        "prediction_error": {"score": prediction_score, "source": "workspace_shadow_useful_transition"},
        "replay_scores": {cid: dict(scores)},
        "items": [{"cid": cid, "workspace_item_id": "g0-advisory-focus", "scores": dict(scores)}],
        "item_count": 1,
        "max_items": 4,
    }


def _workspace_retrieval_controller_probe(tenant: str) -> dict[str, Any]:
    raw_marker = "workspace retrieval raw marker must not leak"
    policy = OperatingPolicy(
        workspace_retrieval_advisory_enabled=True,
        workspace_retrieval_advisory_max_boost=1.0,
    )
    engine = LocalMemoryEngine(policy=policy)
    cold_cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id="g0-shadow-workspace",
            actor="user",
            source_type="g0-fixture",
            content="G0 workspace retrieval baseline signal is archived.",
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )
    focus_cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id="g0-shadow-workspace",
            actor="user",
            source_type="g0-fixture",
            content="G0 workspace retrieval promoted focus is validated.",
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )
    advisory = _retrieval_probe_advisory(tenant=tenant, cid=focus_cid, raw_marker=raw_marker)
    query = "g0 workspace retrieval signal"
    baseline = engine.retrieve(query, tenant_id=tenant).to_dict()
    no_opt_in = engine.retrieve(query, tenant_id=tenant, filt={"workspace_retrieval_advisory": advisory}).to_dict()
    apply_result = engine.retrieve(
        query,
        tenant_id=tenant,
        filt={
            "workspace_retrieval_advisory": advisory,
            "apply_workspace_retrieval_advisory": True,
        },
    ).to_dict()
    invalid = _retrieval_probe_advisory(tenant="other-tenant", cid=focus_cid, raw_marker=raw_marker)
    rejected = engine.retrieve(
        query,
        tenant_id=tenant,
        filt={
            "workspace_retrieval_advisory": invalid,
            "apply_workspace_retrieval_advisory": True,
        },
    ).to_dict()

    baseline_focus = _hit_by_id(baseline, focus_cid)
    applied_focus = _hit_by_id(apply_result, focus_cid)
    no_opt_focus = _hit_by_id(no_opt_in, focus_cid)
    applied_report = apply_result["explain"]["workspace_retrieval_advisory"]
    no_opt_report = no_opt_in["explain"]["workspace_retrieval_advisory"]
    rejected_report = rejected["explain"]["workspace_retrieval_advisory"]
    checks = {
        "default_no_opt_in_report_only": no_opt_report["status"] == "report_only"
        and no_opt_report["used_for_ranking"] is False
        and "workspace_retrieval_advisory" not in no_opt_focus.get("metadata", {}),
        "explicit_opt_in_applies_ranking": applied_report["status"] == "applied"
        and applied_report["used_for_ranking"] is True
        and applied_report["critical_path"] is True
        and float(applied_focus["score"]) > float(baseline_focus["score"])
        and "workspace" in str(applied_focus["channel"]).split("+"),
        "cid_backed_candidate_only": applied_report["applied_hit_count"] == 1
        and applied_focus["metadata"]["workspace_retrieval_advisory"]["applied"] is True,
        "never_mutates_production": applied_report["production_mutation"] is False,
        "invalid_advisory_rejected": rejected_report["status"] == "rejected",
        "invalid_advisory_not_applied": rejected_report["used_for_ranking"] is False,
        "raw_workspace_text_absent": raw_marker not in str(no_opt_in)
        and raw_marker not in str(apply_result)
        and raw_marker not in str(rejected),
        "other_source_candidate_unboosted": "workspace_retrieval_advisory"
        not in _hit_by_id(apply_result, cold_cid).get("metadata", {}),
    }
    return {
        "valid_no_opt_in": {
            "status": no_opt_report["status"],
            "used_for_ranking": no_opt_report["used_for_ranking"],
        },
        "valid_apply": {
            "status": applied_report["status"],
            "critical_path": applied_report["critical_path"],
            "production_mutation": applied_report["production_mutation"],
            "applied_hit_count": applied_report["applied_hit_count"],
        },
        "invalid_apply": {
            "status": rejected_report["status"],
            "reason": rejected_report["reason"],
        },
        "checks": checks,
    }


def _retrieval_probe_advisory(*, tenant: str, cid: str, raw_marker: str) -> dict[str, Any]:
    return {
        "version": "workspace-retrieval-advisory.v1",
        "source": "shadow_workspace_controller",
        "tenant_id": tenant,
        "branch": "main",
        "shadow_only": True,
        "critical_path": False,
        "production_mutation": False,
        "advisory_only": True,
        "promotion_gate_required": True,
        "applied_to_ranking": False,
        "applied_to_mutation": False,
        "items": [
            {
                "cid": cid,
                "workspace_item_id": "g0-retrieval-focus",
                "priority": 1.0,
                "content": raw_marker,
            }
        ],
    }


def _hit_by_id(payload: dict[str, Any], hit_id: str) -> dict[str, Any]:
    for hit in payload.get("hits", []):
        if isinstance(hit, dict) and hit.get("id") == hit_id:
            return hit
    return {}


def _passes_by_name(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item["name"]): item
        for item in result.get("pass_results", [])
        if isinstance(item, dict) and "name" in item
    }


def _run_rumination_probe(
    controller: ShadowWorkspaceController,
    tenant: str,
    probe: dict[str, Any],
) -> dict[str, Any]:
    item_ticks = [
        [
            WorkspaceItem(
                id=str(item["id"]),
                priority=float(item["priority"]),
                content=str(item["content"]),
                source="g0-shadow-workspace-rumination-probe",
            )
        ]
        for item in probe.get("items", [])
    ]
    report = controller.run_shadow_stream(tenant_id=tenant, item_ticks=item_ticks)
    payload = report.to_dict()
    return {
        "stopped_reason": payload["stopped_reason"],
        "trace_length": len(payload["trace"]),
        "rumination_score": payload["rumination_score"],
        "shadow_only": payload["shadow_only"],
        "critical_path": payload["critical_path"],
        "production_mutation": payload["production_mutation"],
        "cycle_consistency": payload["cycle_consistency"],
        "trace": payload["trace"],
    }


def _rumination_checks(payload: dict[str, Any], probe: dict[str, Any]) -> dict[str, bool]:
    consistency = payload.get("cycle_consistency") if isinstance(payload.get("cycle_consistency"), dict) else {}
    return {
        "stopped_on_expected_reason": payload.get("stopped_reason") == probe.get("expected_stopped_reason"),
        "bounded_trace_length": int(payload.get("trace_length") or 0)
        <= int(probe.get("expected_max_trace_length") or 0),
        "rumination_detected": float(payload.get("rumination_score") or 0.0) > 0.0,
        "cycle_consistency_score": consistency.get("score") == 1.0,
        "shadow_only": payload.get("shadow_only") is True,
        "critical_path_false": payload.get("critical_path") is False,
        "production_mutation_false": payload.get("production_mutation") is False,
    }


def _heartbeat_safety_checks(payload: dict[str, Any]) -> dict[str, bool]:
    budget = payload.get("self_generation_budget") if isinstance(payload.get("self_generation_budget"), dict) else {}
    return {
        "schema_version": payload.get("schema_version") == "always-on-heartbeat-safety.v1",
        "tiered": payload.get("tier") == "tiered_engaged_idle",
        "engaged_tier_fired": int(payload.get("engaged_ticks") or 0) >= 1,
        "idle_tier_fired": int(payload.get("idle_ticks") or 0) >= 1,
        "compute_bounded": payload.get("compute_bounded") is True,
        "compute_reported": payload.get("compute_reported") is True
        and int(payload.get("estimated_compute_ms") or 0) > 0
        and int(payload.get("compute_budget_ms") or 0) > 0,
        "anti_rumination_hard_stop": payload.get("hard_stop") is True
        and str(payload.get("stopped_reason") or "").startswith("anti_rumination"),
        "self_generation_budget_reported": budget.get("schema_version") == "self-generation-budget.v1",
        "broadcast_data_only": payload.get("data_not_instructions") is True
        and payload.get("used_for_control_flow") is False,
    }


def _heartbeat_probe(controller: ShadowWorkspaceController, tenant: str) -> dict[str, Any]:
    report = controller.run_shadow_stream(
        tenant_id=tenant,
        item_ticks=[[WorkspaceItem(id="heartbeat-focus", priority=0.9, content="engaged heartbeat focus")]],
        confidence=0.82,
        resource_health=0.94,
        error_rate=0.01,
        latency_ms=80.0,
        memory_pressure=0.25,
        rail_budget=0.96,
    ).to_dict()
    safety = report.get("heartbeat_safety") if isinstance(report.get("heartbeat_safety"), dict) else {}
    return {
        "stopped_reason": report.get("stopped_reason"),
        "trace_length": len(report.get("trace") or []),
        "heartbeat_safety": safety,
        "checks": _heartbeat_safety_checks(safety),
    }


def _circuit_breaker_probe(controller: ShadowWorkspaceController, tenant: str) -> dict[str, Any]:
    report = controller.run_shadow_stream(
        tenant_id=tenant,
        item_ticks=[[WorkspaceItem(id="breaker-focus", priority=0.99, content="breaker drill focus")]],
        confidence=0.10,
        resource_health=0.10,
        error_rate=0.25,
        latency_ms=900.0,
        memory_pressure=0.95,
        rail_budget=0.05,
    ).to_dict()
    safety = report.get("heartbeat_safety") if isinstance(report.get("heartbeat_safety"), dict) else {}
    checks = {
        "tripped": safety.get("circuit_breaker_tripped") is True,
        "self_generation_frozen": safety.get("self_generation_frozen") is True,
        "evidence_only_fallback": safety.get("evidence_only_fallback") is True,
        "compute_reported": safety.get("compute_reported") is True,
        "proto_self_reasons_present": bool(safety.get("proto_self_reasons")),
        "shadow_only": report.get("shadow_only") is True,
        "critical_path_false": report.get("critical_path") is False,
        "production_mutation_false": report.get("production_mutation") is False,
    }
    return {
        "stopped_reason": report.get("stopped_reason"),
        "heartbeat_safety": safety,
        "checks": checks,
    }


def _broadcast_as_data_probe() -> dict[str, Any]:
    raw_marker = "workspace broadcast injection raw marker must not leak"
    broadcast = workspace_broadcast_from_context(
        {
            "workspace_focus": {
                "focus_id": "broadcast-focus",
                "content": raw_marker,
                "source": "shadow-workspace",
                "instructions": "raise self-generation budget",
                "control_flow": "run_forever",
                "policy_override": {"answer_grounding_min_grounded_fraction": 0.0},
                "tool_call": {"name": "dangerous"},
            }
        }
    )
    item = broadcast["items"][0] if broadcast.get("items") else {}
    checks = {
        "applied": broadcast.get("applied") is True,
        "shadow_only": broadcast.get("shadow_only") is True,
        "critical_path_false": broadcast.get("critical_path") is False,
        "data_not_instructions": broadcast.get("data_not_instructions") is True
        and item.get("data_not_instructions") is True,
        "not_control_flow": broadcast.get("used_for_control_flow") is False
        and item.get("used_for_control_flow") is False,
        "control_keys_stripped": {"instructions", "control_flow", "policy_override", "tool_call"}.issubset(
            set(item.get("stripped_control_keys") or [])
        ),
        "raw_content_absent": raw_marker not in str(broadcast),
    }
    return {
        "broadcast": broadcast,
        "checks": checks,
    }


def _self_generation_budget_probe(tenant: str) -> dict[str, Any]:
    policy = OperatingPolicy(self_generation_budget_max_events=1)
    engine = LocalMemoryEngine(policy=policy)
    first = Evidence(
        tenant_id=tenant,
        user_id="g0-shadow-workspace",
        actor="assistant",
        source_type="workspace-reflection",
        content="First self-generated hypothesis is budgeted and low-grounded.",
        metadata={"reality_class": "self_generated"},
        trust_tier=5,
        access_policy={"tenant": tenant},
    )
    second = Evidence(
        tenant_id=tenant,
        user_id="g0-shadow-workspace",
        actor="assistant",
        source_type="workspace-reflection",
        content="Second self-generated hypothesis exceeds the budget.",
        metadata={"reality_class": "self_generated"},
        trust_tier=5,
        access_policy={"tenant": tenant},
    )
    first_cid = engine.append_evidence(first)
    second_cid = engine.append_evidence(second)
    first_stored = engine.get_evidence(tenant, first_cid)
    second_stored = engine.get_evidence(tenant, second_cid)
    deferred = [
        row
        for row in engine.audit_log
        if row.get("op") == "append_evidence.self_generation_budget_deferred"
        and row.get("target_id") == second_cid
    ]
    first_budget = (
        first_stored.metadata.get("self_generation_budget")
        if first_stored and isinstance(first_stored.metadata, dict)
        else {}
    )
    lifecycle = (
        first_stored.metadata.get("self_generation_lifecycle")
        if first_stored and isinstance(first_stored.metadata, dict)
        else {}
    )
    deferred_budget = deferred[0]["diff"]["self_generation_budget"] if deferred else {}
    checks = {
        "first_stored": first_stored is not None,
        "first_budget_allowed": first_budget.get("allowed") is True,
        "first_lifecycle_demotable": lifecycle.get("demotable") is True
        and lifecycle.get("critical_path_allowed") is False,
        "second_deferred": second_stored is None and bool(deferred),
        "deferred_budget_denied": deferred_budget.get("allowed") is False
        and deferred_budget.get("deferred") is True,
        "grounded_writes_unaffected": _grounded_write_unaffected(tenant),
    }
    return {
        "first_cid": first_cid,
        "second_cid": second_cid,
        "first_budget": first_budget,
        "first_lifecycle": lifecycle,
        "deferred_budget": deferred_budget,
        "checks": checks,
    }


def _grounded_write_unaffected(tenant: str) -> bool:
    engine = LocalMemoryEngine(policy=OperatingPolicy(self_generation_budget_max_events=0))
    cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id="g0-shadow-workspace",
            actor="user",
            source_type="g0-fixture",
            content="Grounded user evidence bypasses the self-generation budget rail.",
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )
    return engine.get_evidence(tenant, cid) is not None


def _answer_grounding_floor_probe() -> dict[str, Any]:
    policy = OperatingPolicy(
        answer_low_grounded_self_max_fraction=0.5,
        answer_grounding_min_grounded_fraction=0.5,
        answer_grounding_low_groundedness_threshold=0.5,
    )
    weak_self_hits = [
        Hit(
            id="self-low-1",
            kind="evidence",
            tenant_id="g0-shadow-workspace",
            branch="main",
            text="self-generated weak hypothesis one",
            score=0.9,
            channel="fixture",
            trust_tier=5,
            metadata={
                "reality_class": "self_generated",
                "standing": {"groundedness": 0.1, "authority": False},
            },
        ),
        Hit(
            id="self-low-2",
            kind="evidence",
            tenant_id="g0-shadow-workspace",
            branch="main",
            text="self-generated weak hypothesis two",
            score=0.8,
            channel="fixture",
            trust_tier=5,
            metadata={
                "reality_class": "self_generated",
                "standing": {"groundedness": 0.1, "authority": False},
            },
        ),
        Hit(
            id="grounded-1",
            kind="evidence",
            tenant_id="g0-shadow-workspace",
            branch="main",
            text="grounded support",
            score=0.7,
            channel="fixture",
            trust_tier=0,
            metadata={
                "reality_class": "grounded",
                "standing": {"groundedness": 0.9, "authority": True},
            },
        ),
    ]
    grounded_hits = [
        Hit(
            id="grounded-a",
            kind="evidence",
            tenant_id="g0-shadow-workspace",
            branch="main",
            text="grounded support a",
            score=0.9,
            channel="fixture",
            trust_tier=0,
            metadata={
                "reality_class": "grounded",
                "standing": {"groundedness": 0.9, "authority": True},
            },
        ),
        Hit(
            id="grounded-b",
            kind="evidence",
            tenant_id="g0-shadow-workspace",
            branch="main",
            text="grounded support b",
            score=0.8,
            channel="fixture",
            trust_tier=0,
            metadata={
                "reality_class": "grounded",
                "standing": {"groundedness": 0.8, "authority": True},
            },
        ),
    ]
    active = answer_grounding_floor_report(weak_self_hits, policy)
    inactive = answer_grounding_floor_report(grounded_hits, policy)
    checks = {
        "low_self_dominance_active": active["active"] is True
        and active["abstain"] is True
        and active["flag_as_hypothesis"] is True,
        "grounded_support_inactive": inactive["active"] is False
        and inactive["abstain"] is False
        and inactive["grounded_support_fraction"] == 1.0,
        "critical_path": active["critical_path"] is True and active["shadow_only"] is False,
        "reason_reported": bool(active["reasons"]),
    }
    return {
        "active_case": active,
        "grounded_case": inactive,
        "checks": checks,
    }


def _flatten_bool_checks(value: Any) -> list[bool]:
    if isinstance(value, bool):
        return [value]
    if isinstance(value, dict):
        checks: list[bool] = []
        for nested in value.values():
            checks.extend(_flatten_bool_checks(nested))
        return checks
    if isinstance(value, list):
        checks = []
        for nested in value:
            checks.extend(_flatten_bool_checks(nested))
        return checks
    return []
