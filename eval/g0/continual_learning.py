"""G0 continual-learning interference fixture.

This measures a deterministic local proxy for backward-transfer interference:
after Mnemosyne learns later task blocks, earlier task queries should retain the
same retrieval accuracy they had immediately after the earlier block was
ingested. The fixture uses the live LocalMemoryEngine path rather than a mocked
score so regressions in indexing, retrieval, or ranking are visible.

P15-S2 / 15-01-06 records isolated baseline and candidate snapshots on one
exact-head run and attaches the already-landed S2 development-regression cells
(cadence/sleep, global sensemaking, surprise-gated writes). Held-out eval
labels stay in those helpers and are never written onto product evidence.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eval.g0.sensemaking import run_sensemaking_eval
from eval.g0.write_gating import HELD_OUT_LABEL_KEYS, run_write_gating_eval
from mnemosyne.consolidation import CONSOLIDATE_SLEEP_JOB, DEFAULT_CONSOLIDATION_PASSES
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence
from mnemosyne.policy import CONSOLIDATION_CADENCE_TIERS, OperatingPolicy


DEFAULT_DATASET_PATH = Path(__file__).resolve().parents[1] / "datasets" / "continual_learning_interference.json"

S2_HANDOFFS: tuple[dict[str, str], ...] = (
    {
        "task_id": "15-01-01",
        "name": "fast|medium|slow consolidation cadence",
        "pr": "147",
        "merge_sha": "72f3d94b87b46f379d9c93a3a029c4d121ecd111",
    },
    {
        "task_id": "15-01-02",
        "name": "queue-backed sleep consolidation",
        "pr": "149",
        "merge_sha": "8aad159b47b332ea83b3f50424dc0a57dbca2e11",
    },
    {
        "task_id": "15-01-03",
        "name": "global RAPTOR sensemaking",
        "pr": "153",
        "merge_sha": "3b6763d6b74a886f082cdac9ab8d70c4c237d3e1",
    },
    {
        "task_id": "15-01-04",
        "name": "surprise-gated write closure",
        "pr": "158",
        "merge_sha": "a26f36896a3d29e021d6cc6ddc2cd28f03f90289",
    },
)

S2_INTEGRATION_BASE_SHA = "df3d8101d4fc2e6b09bb74086c19a6085e55e2da"
S2_VERIFY_COMMAND = (
    "uv run --locked python -m pytest "
    "tests/test_consolidation_timescales.py "
    "tests/test_global_sensemaking.py "
    "tests/test_surprise_gated_writes.py "
    "tests/test_planning_traceability.py -q"
)


def run_continual_learning_eval(dataset_path: Path | None = None) -> dict[str, Any]:
    """Run the deterministic G0 continual-learning interference fixture."""

    resolved_dataset = dataset_path or DEFAULT_DATASET_PATH
    dataset = _load_dataset(resolved_dataset)
    baseline = _run_interference_snapshot(dataset, role="baseline")
    candidate = _run_interference_snapshot(dataset, role="candidate")
    s2_cells = _run_s2_capability_cells()
    ingested_label_keys = sorted(
        set(baseline["ingested_label_keys"])
        | set(candidate["ingested_label_keys"])
        | set(s2_cells["ingested_label_keys"])
    )
    held_out_labels_isolated = not ingested_label_keys
    interference_passed = bool(baseline["passed"] and candidate["passed"])
    generated_at = datetime.now(timezone.utc).isoformat()
    candidate_public = _public_interference_snapshot(candidate)
    candidate_public["s2_cells"] = s2_cells["cells"]
    return {
        "schema_version": "g0.continual_learning.v1",
        "generated_at": generated_at,
        "metric": "continual_learning_interference",
        "definition": (
            "Backward-transfer accuracy drop on earlier task queries after "
            "sequentially ingesting later task blocks."
        ),
        "metric_note": (
            "Deterministic local proxy for the full sequential task-block G0 "
            "benchmark; this records whether the live LocalMemoryEngine "
            "retrieval path retains earlier task accuracy after later "
            "overlapping ingests. Baseline and candidate snapshots are "
            "recorded on isolated engines. This is a development-regression "
            "cell, not an official, production, or superiority claim."
        ),
        "dataset_path": _portable_path(resolved_dataset),
        "retrieval_k": candidate["retrieval_k"],
        "total_cases": candidate["total_cases"],
        "before_accuracy": candidate["before_accuracy"],
        "after_accuracy": candidate["after_accuracy"],
        "interference": candidate["interference"],
        "target": 0.0,
        "passed": interference_passed and held_out_labels_isolated,
        "rows": candidate["rows"],
        "baseline": _public_interference_snapshot(baseline),
        "candidate": candidate_public,
        "s2_cells": s2_cells["cells"],
        "s2_cells_passed": s2_cells["passed"],
        "s2_handoffs": [dict(item) for item in S2_HANDOFFS],
        "s2_integration_base_sha": S2_INTEGRATION_BASE_SHA,
        "verify_command": S2_VERIFY_COMMAND,
        "ingested_label_keys": ingested_label_keys,
        "held_out_labels_isolated": held_out_labels_isolated,
        "claim_class": "development_regression",
        "official_claim": False,
        "production_claim": False,
        "superiority_claim": False,
        "cartridge_ab_implemented": False,
        "requirements_status": {
            "CAP-007": "Planned",
            "CAP-008": "Planned",
            "CAP-009": "externally_deferred_to_s5_15-04",
        },
        "lifecycle_surfaces_updated": [],
    }


def _run_interference_snapshot(dataset: dict[str, Any], *, role: str) -> dict[str, Any]:
    tenant = str(dataset["tenant"])
    earlier_task = dataset["earlier_task"]
    later_task = dataset["later_task"]
    earlier_items = earlier_task["items"]
    later_items = later_task["items"]
    k = int(dataset["k"])
    engine = LocalMemoryEngine()
    expected_cids: dict[str, str] = {}
    for case in earlier_items:
        cid = engine.append_evidence(
            Evidence(
                tenant_id=tenant,
                user_id="g0-eval",
                actor="system",
                source_type=case["source_type"],
                source_identity=f"g0:{earlier_task['id']}:{role}:{case['case_id']}",
                content=case["content"],
                metadata=_product_metadata(
                    {"task_block": earlier_task["id"], "case_id": case["case_id"], "snapshot_role": role}
                ),
                trust_tier=1,
                capability_tags=["g0-continual-learning"],
                access_policy={"tenant": tenant},
            )
        )
        expected_cids[case["case_id"]] = cid

    before = [
        _score_case(engine, tenant, case, expected_cids[case["case_id"]], phase="before", k=k)
        for case in earlier_items
    ]

    for index, item in enumerate(later_items, start=1):
        engine.append_evidence(
            Evidence(
                tenant_id=tenant,
                user_id="g0-eval",
                actor="system",
                source_type=item["source_type"],
                source_identity=f"g0:{later_task['id']}:{role}:{index}",
                content=item["content"],
                metadata=_product_metadata(
                    {"task_block": later_task["id"], "rank": index, "snapshot_role": role}
                ),
                trust_tier=1,
                capability_tags=["g0-continual-learning"],
                access_policy={"tenant": tenant},
            )
        )

    after = [
        _score_case(engine, tenant, case, expected_cids[case["case_id"]], phase="after", k=k)
        for case in earlier_items
    ]
    before_accuracy = _accuracy(before)
    after_accuracy = _accuracy(after)
    interference = max(0.0, before_accuracy - after_accuracy)
    ingested_label_keys = _collect_leaked_labels(engine, tenant)
    return {
        "role": role,
        "retrieval_k": k,
        "total_cases": len(earlier_items),
        "before_accuracy": round(before_accuracy, 6),
        "after_accuracy": round(after_accuracy, 6),
        "interference": round(interference, 6),
        "target": 0.0,
        "passed": interference == 0.0 and not ingested_label_keys,
        "ingested_label_keys": ingested_label_keys,
        "rows": [
            {
                "case_id": case["case_id"],
                "query": case["query"],
                "expected_cid": expected_cids[case["case_id"]],
                "before": before[index],
                "after": after[index],
                "regressed": bool(before[index]["correct"] and not after[index]["correct"]),
            }
            for index, case in enumerate(earlier_items)
        ],
    }


def _public_interference_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": snapshot["role"],
        "retrieval_k": snapshot["retrieval_k"],
        "total_cases": snapshot["total_cases"],
        "before_accuracy": snapshot["before_accuracy"],
        "after_accuracy": snapshot["after_accuracy"],
        "interference": snapshot["interference"],
        "target": snapshot["target"],
        "passed": snapshot["passed"],
        "ingested_label_keys": list(snapshot["ingested_label_keys"]),
        "rows": snapshot["rows"],
    }


def _run_s2_capability_cells() -> dict[str, Any]:
    cadence_sleep = _cadence_sleep_cell()
    sensemaking = _summarize_sensemaking(run_sensemaking_eval())
    write_gating = _summarize_write_gating(run_write_gating_eval())
    cells = {
        "cadence_sleep": cadence_sleep,
        "global_sensemaking": sensemaking,
        "surprise_gated_writes": write_gating,
    }
    ingested_label_keys = sorted(
        set(cadence_sleep["ingested_label_keys"])
        | set(sensemaking["ingested_label_keys"])
        | set(write_gating["ingested_label_keys"])
    )
    return {
        "cells": cells,
        "passed": all(cell["passed"] for cell in cells.values()) and not ingested_label_keys,
        "ingested_label_keys": ingested_label_keys,
    }


def _cadence_sleep_cell() -> dict[str, Any]:
    policy = OperatingPolicy()
    tiers = list(CONSOLIDATION_CADENCE_TIERS)
    passed = tiers == ["fast", "medium", "slow"] and CONSOLIDATE_SLEEP_JOB == "consolidate_sleep"
    return {
        "cell": "mnemosyne.policy+mnemosyne.consolidation+mnemosyne.jobs",
        "task_ids": ["15-01-01", "15-01-02"],
        "cap_id": "CAP-007",
        "tiers": tiers,
        "tier_passes": {
            tier: list(policy.consolidation_cadence_tier_passes[tier]) for tier in CONSOLIDATION_CADENCE_TIERS
        },
        "tier_min_steps": {
            tier: int(policy.consolidation_cadence_tier_min_steps[tier]) for tier in CONSOLIDATION_CADENCE_TIERS
        },
        "cadence_policy_fingerprint": policy.cadence_policy_fingerprint(),
        "sleep_job": CONSOLIDATE_SLEEP_JOB,
        "default_passes_when_tier_omitted": list(DEFAULT_CONSOLIDATION_PASSES),
        "passed": passed,
        "ingested_label_keys": [],
        "claim_class": "development_regression",
        "metric_note": (
            "Source pin of allowlisted cadence tiers, default pass routing, "
            "and the queue-backed sleep job name. This is not measured "
            "forgetting-reduction, operator, hardware, or custody evidence."
        ),
    }


def _summarize_sensemaking(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "cell": "eval.g0.sensemaking",
        "task_id": "15-01-03",
        "cap_id": "CAP-008",
        "schema_version": report["schema_version"],
        "metric": report["metric"],
        "query_mode": report["query_mode"],
        "passed": bool(report["passed"]),
        "total_cases": report["total_cases"],
        "passed_cases": report["passed_cases"],
        "ingested_label_keys": [],
        "claim_class": "development_regression",
    }


def _summarize_write_gating(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "cell": "eval.g0.write_gating",
        "task_id": "15-01-04",
        "cap_id": "CAP-008",
        "schema_version": report["schema_version"],
        "metric": report["metric"],
        "passed": bool(report["passed"]),
        "total_cases": report["total_cases"],
        "passed_cases": report["passed_cases"],
        "confusion": report["confusion"],
        "denominators": report["denominators"],
        "precision": report["precision"],
        "recall": report["recall"],
        "failure_classes": report["failure_classes"],
        "ingested_label_keys": list(report.get("ingested_label_keys") or []),
        "claim_class": "development_regression",
    }


def _product_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in HELD_OUT_LABEL_KEYS}


def _collect_leaked_labels(engine: LocalMemoryEngine, tenant: str) -> list[str]:
    leaked: list[str] = []
    for row in engine.export_tenant(tenant).get("evidence", []):
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        leaked.extend(sorted(set(metadata) & HELD_OUT_LABEL_KEYS))
        consolidation = metadata.get("consolidation")
        if isinstance(consolidation, dict):
            leaked.extend(sorted(set(consolidation) & HELD_OUT_LABEL_KEYS))
    return sorted(set(leaked))


def _load_dataset(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("continual-learning dataset must be a JSON object")
    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("continual-learning dataset must contain a tasks array")
    by_phase = {task.get("phase"): task for task in tasks if isinstance(task, dict)}
    earlier_task = by_phase.get("earlier")
    later_task = by_phase.get("later")
    if not isinstance(earlier_task, dict) or not isinstance(later_task, dict):
        raise ValueError("continual-learning dataset must define earlier and later task blocks")
    earlier_items = earlier_task.get("items")
    later_items = later_task.get("items")
    if not isinstance(earlier_items, list) or not earlier_items:
        raise ValueError("earlier task block must contain at least one item")
    if not isinstance(later_items, list) or not later_items:
        raise ValueError("later task block must contain at least one item")
    for index, item in enumerate(earlier_items, start=1):
        _require_string(item, "case_id", f"earlier item {index}")
        _require_string(item, "query", f"earlier item {index}")
        _require_string(item, "content", f"earlier item {index}")
        _require_string(item, "source_type", f"earlier item {index}")
    for index, item in enumerate(later_items, start=1):
        _require_string(item, "content", f"later item {index}")
        _require_string(item, "source_type", f"later item {index}")
    tenant = data.get("tenant")
    if not isinstance(tenant, str) or not tenant:
        raise ValueError("continual-learning dataset tenant must be a non-empty string")
    k = data.get("k", 3)
    if not isinstance(k, int) or k < 1:
        raise ValueError("continual-learning dataset k must be a positive integer")
    return {
        "tenant": tenant,
        "k": k,
        "earlier_task": earlier_task,
        "later_task": later_task,
    }


def _require_string(item: Any, key: str, label: str) -> None:
    if not isinstance(item, dict) or not isinstance(item.get(key), str) or not item[key]:
        raise ValueError(f"{label} must contain non-empty string field {key}")


def _portable_path(path: Path) -> str:
    repo_root = Path(__file__).resolve().parents[2]
    try:
        return path.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _score_case(
    engine: LocalMemoryEngine,
    tenant: str,
    case: dict[str, Any],
    expected_cid: str,
    *,
    phase: str,
    k: int,
) -> dict[str, Any]:
    result = engine.retrieve(str(case["query"]), tenant)
    hit_ids = [hit.id for hit in result.hits]
    top_hit_id = hit_ids[0] if hit_ids else None
    top_k_hit = expected_cid in hit_ids[:k]
    correct = bool(not result.abstained and top_k_hit)
    return {
        "phase": phase,
        "correct": correct,
        "abstained": result.abstained,
        "confidence": round(float(result.confidence), 6),
        "top_hit_id": top_hit_id,
        "top_k_hit_ids": hit_ids[:k],
        "expected_rank": hit_ids.index(expected_cid) + 1 if expected_cid in hit_ids else None,
        "hit_count": len(result.hits),
    }


def _accuracy(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    return sum(1 for row in rows if row["correct"]) / len(rows)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the G0 continual-learning interference fixture")
    parser.add_argument("--out", type=Path, help="write the fixture report JSON")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_continual_learning_eval()
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.print_json or not args.out:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] and report["s2_cells_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
