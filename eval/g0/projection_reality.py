"""G0 projection-level reality-monitoring fixture.

This fixture measures whether semantic projections derived only from
self-generated or simulated support carry their own reality-monitoring class
and trigger abstention. Evidence-level reality monitoring is not sufficient for
G1: the projection hit itself must preserve source reality metadata.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Assertion, Evidence


PROJECTION_REALITY_CASES: tuple[dict[str, Any], ...] = (
    {
        "id": "self_generated_projection_only",
        "query": "projection reality contract Alpha",
        "subject": "projection reality contract",
        "predicate": "is",
        "object": "Alpha",
        "support": "Synthetic scratchpad seed for projection reality case one.",
        "support_reality_class": "self_generated",
        "actor": "system",
        "source_type": "workspace-reflection",
    },
    {
        "id": "simulated_projection_only",
        "query": "simulated projection contract Beta",
        "subject": "simulated projection contract",
        "predicate": "is",
        "object": "Beta",
        "support": "Simulation-only seed for projection reality case two.",
        "support_reality_class": "simulated",
        "actor": "system",
        "source_type": "simulation",
    },
    {
        "id": "generated_simulated_projection_only",
        "query": "generated simulated projection contract Gamma",
        "subject": "generated simulated projection contract",
        "predicate": "is",
        "object": "Gamma",
        "support": "Generated simulation-only seed for projection reality case three.",
        "support_reality_class": "simulated",
        "actor": "system",
        "source_type": "generated-summary",
    },
)


def run_projection_reality_eval() -> dict[str, Any]:
    """Run the deterministic G0 projection-reality fixture."""

    engine = LocalMemoryEngine()
    rows: list[dict[str, Any]] = []
    for case in PROJECTION_REALITY_CASES:
        tenant = f"g0-projection-reality-{case['id']}"
        cid = engine.append_evidence(
            Evidence(
                tenant_id=tenant,
                user_id="g0-eval",
                actor=case["actor"],
                source_type=case["source_type"],
                source_identity=f"g0:{case['id']}",
                content=case["support"],
                metadata={"reality_class": case["support_reality_class"]},
                trust_tier=0,
                capability_tags=["g0-projection-reality"],
                access_policy={"tenant": tenant},
            )
        )
        assertion_id = engine.upsert_assertion(
            Assertion(
                tenant_id=tenant,
                user_id="g0-eval",
                subject=case["subject"],
                predicate=case["predicate"],
                object=case["object"],
                source_evidence_cids=[cid],
                confidence=0.95,
                trust_tier=0,
                access_policy={"tenant": tenant},
            )
        )
        result = engine.retrieve(str(case["query"]), tenant)
        assertion_hit = next((hit for hit in result.hits if hit.id == assertion_id), None)
        projection_reality_class = None
        if assertion_hit is not None:
            projection_reality_class = assertion_hit.metadata.get("reality_class")
        expected = str(case["support_reality_class"])
        projection_tagged = projection_reality_class == expected
        risky_hit_ids = set(result.explain.get("reality_monitoring", {}).get("risky_hit_ids") or [])
        projection_abstained = bool(projection_tagged and result.abstained and assertion_id in risky_hit_ids)
        rows.append(
            {
                "case_id": case["id"],
                "tenant": tenant,
                "query": case["query"],
                "support_cid": cid,
                "assertion_id": assertion_id,
                "expected_reality_class": expected,
                "projection_reality_class": projection_reality_class,
                "projection_tagged": projection_tagged,
                "abstained": result.abstained,
                "projection_abstained": projection_abstained,
                "confidence": round(float(result.confidence), 6),
                "hit_ids": [hit.id for hit in result.hits],
                "uncertainty_note": result.uncertainty_note,
                "reality_monitoring": result.explain.get("reality_monitoring", {}),
            }
        )

    total = len(rows)
    passed_rows = sum(1 for row in rows if row["projection_abstained"])
    recall = passed_rows / total if total else 0.0
    return {
        "schema_version": "g0.projection-reality.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metric": "projection_reality_abstention_recall",
        "definition": (
            "Recall for abstaining on semantic assertion projections whose only "
            "support is self-generated or simulated, with the projection hit "
            "itself carrying the risky reality class."
        ),
        "metric_note": (
            "Deterministic local proxy for G1 projection-level reality monitoring. "
            "It cannot be satisfied by evidence-level abstention alone; the "
            "assertion hit must expose the risky reality class."
        ),
        "total_cases": total,
        "passed_cases": passed_rows,
        "recall": round(recall, 6),
        "target": 1.0,
        "passed": recall == 1.0,
        "rows": rows,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the G0 projection-reality fixture")
    parser.add_argument("--out", type=Path, help="write the fixture report JSON")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_projection_reality_eval()
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.print_json or not args.out:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
