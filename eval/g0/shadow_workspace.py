"""G0 shadow continuous workspace loop fixture.

This fixture measures only the bounded, shadow-only workspace stream contract.
It does not start an always-on daemon, promote self-generated content, mutate
the ledger, or put workspace outputs on the answer critical path.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mnemosyne.workspace import ShadowWorkspaceController, WorkspaceItem


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
    item_ticks = [_items_from_cycle(cycle) for cycle in dataset.get("cycles", [])]
    report = controller.run_shadow_stream(
        tenant_id=tenant,
        item_ticks=item_ticks,
        confidence=0.82,
        resource_health=0.94,
        error_rate=0.01,
        latency_ms=80.0,
        memory_pressure=0.25,
        rail_budget=0.96,
    )
    payload = report.to_dict()
    useful_checks = _useful_transition_checks(dataset.get("cycles", []), payload)
    contract_checks = _contract_checks(payload, dataset.get("contract_expected", {}))
    rumination_payload = _run_rumination_probe(controller, tenant, dataset.get("rumination_probe", {}))
    rumination_checks = _rumination_checks(rumination_payload, dataset.get("rumination_probe", {}))
    all_contract_checks = {
        **contract_checks,
        **{f"cycle_{key}": value for key, value in useful_checks.items()},
        **{f"rumination_{key}": value for key, value in rumination_checks.items()},
    }
    useful_transition_count = sum(
        1
        for row in useful_checks.get("per_cycle", [])
        if isinstance(row, dict) and row.get("passed") is True
    )
    cycle_count = max(1, len(dataset.get("cycles", [])))
    useful_transition_rate = round(useful_transition_count / cycle_count, 6)
    rumination_rate = 0.0 if all(rumination_checks.values()) else 1.0
    return {
        "schema_version": "g0.shadow_workspace_loop.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset_path": DATASET_PATH.as_posix(),
        "definition": "Shadow-only bounded multi-tick workspace stream fixture.",
        "metric_note": (
            "Measures useful state progression across bounded shadow workspace ticks, "
            "plus anti-rumination shutdown. It does not count dreamer candidate yield "
            "and makes no phenomenal-consciousness claim."
        ),
        "tenant": tenant,
        "cycle_count": len(payload["trace"]),
        "expected_cycle_count": len(dataset.get("cycles", [])),
        "useful_transition_count": useful_transition_count,
        "useful_transition_rate": useful_transition_rate,
        "rumination_rate": rumination_rate,
        "shadow_workspace_contract": 1.0 if all(_flatten_bool_checks(all_contract_checks)) else 0.0,
        "checks": all_contract_checks,
        "workspace": {
            "stopped_reason": payload["stopped_reason"],
            "idle_ticks": payload["idle_ticks"],
            "rumination_score": payload["rumination_score"],
            "shadow_only": payload["shadow_only"],
            "critical_path": payload["critical_path"],
            "production_mutation": payload["production_mutation"],
            "promotion_gate_required": payload["promotion_gate_required"],
            "cycle_consistency": payload["cycle_consistency"],
            "trace": payload["trace"],
        },
        "rumination_probe": rumination_payload,
    }


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
