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

from mnemosyne.consolidation import ConsolidationWorker
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence
from mnemosyne.policy import OperatingPolicy
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
    advisory = report.to_consolidation_advisory()
    useful_checks = _useful_transition_checks(dataset.get("cycles", []), payload)
    contract_checks = _contract_checks(payload, dataset.get("contract_expected", {}))
    advisory_checks = _advisory_checks(advisory, dataset)
    advisory_promotion_probe = _workspace_advisory_promotion_probe(tenant)
    advisory_promotion_checks = advisory_promotion_probe["checks"]
    retrieval_controller_probe = _workspace_retrieval_controller_probe(tenant)
    retrieval_controller_checks = retrieval_controller_probe["checks"]
    rumination_payload = _run_rumination_probe(controller, tenant, dataset.get("rumination_probe", {}))
    rumination_checks = _rumination_checks(rumination_payload, dataset.get("rumination_probe", {}))
    all_contract_checks = {
        **contract_checks,
        **{f"advisory_{key}": value for key, value in advisory_checks.items()},
        **{f"advisory_promotion_{key}": value for key, value in advisory_promotion_checks.items()},
        **{f"retrieval_controller_{key}": value for key, value in retrieval_controller_checks.items()},
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
        "workspace_consolidation_advisory": advisory,
        "workspace_advisory_promotion_probe": advisory_promotion_probe,
        "workspace_retrieval_controller_probe": retrieval_controller_probe,
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
