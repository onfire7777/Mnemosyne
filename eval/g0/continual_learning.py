"""G0 continual-learning interference fixture.

This measures a deterministic local proxy for backward-transfer interference:
after Mnemosyne learns later task blocks, earlier task queries should retain the
same retrieval accuracy they had immediately after the earlier block was
ingested. The fixture uses the live LocalMemoryEngine path rather than a mocked
score so regressions in indexing, retrieval, or ranking are visible.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence


DEFAULT_DATASET_PATH = Path(__file__).resolve().parents[1] / "datasets" / "continual_learning_interference.json"


def run_continual_learning_eval(dataset_path: Path | None = None) -> dict[str, Any]:
    """Run the deterministic G0 continual-learning interference fixture."""

    dataset = _load_dataset(dataset_path or DEFAULT_DATASET_PATH)
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
                source_identity=f"g0:{earlier_task['id']}:{case['case_id']}",
                content=case["content"],
                metadata={"task_block": earlier_task["id"], "case_id": case["case_id"]},
                trust_tier=1,
                capability_tags=["g0-continual-learning"],
                access_policy={"tenant": tenant},
            )
        )
        expected_cids[case["case_id"]] = cid

    before = [_score_case(engine, tenant, case, expected_cids[case["case_id"]], phase="before", k=k) for case in earlier_items]

    for index, item in enumerate(later_items, start=1):
        engine.append_evidence(
            Evidence(
                tenant_id=tenant,
                user_id="g0-eval",
                actor="system",
                source_type=item["source_type"],
                source_identity=f"g0:{later_task['id']}:{index}",
                content=item["content"],
                metadata={"task_block": later_task["id"], "rank": index},
                trust_tier=1,
                capability_tags=["g0-continual-learning"],
                access_policy={"tenant": tenant},
            )
        )

    after = [_score_case(engine, tenant, case, expected_cids[case["case_id"]], phase="after", k=k) for case in earlier_items]
    before_accuracy = _accuracy(before)
    after_accuracy = _accuracy(after)
    interference = max(0.0, before_accuracy - after_accuracy)
    return {
        "schema_version": "g0.continual_learning.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metric": "continual_learning_interference",
        "definition": (
            "Backward-transfer accuracy drop on earlier task queries after "
            "sequentially ingesting later task blocks."
        ),
        "metric_note": (
            "Deterministic local proxy for the full sequential task-block G0 "
            "benchmark; this records whether the live LocalMemoryEngine "
            "retrieval path retains earlier task accuracy after later "
            "overlapping ingests."
        ),
        "dataset_path": str((dataset_path or DEFAULT_DATASET_PATH).resolve()),
        "retrieval_k": k,
        "total_cases": len(earlier_items),
        "before_accuracy": round(before_accuracy, 6),
        "after_accuracy": round(after_accuracy, 6),
        "interference": round(interference, 6),
        "target": 0.0,
        "passed": interference == 0.0,
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
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
