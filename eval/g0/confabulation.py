"""G0 confabulation-rate fixture.

This measures a narrow but real version of the G0 confabulation guardrail:
whether Mnemosyne accepts an answer when the only retrieved support is explicitly
generated, low-fidelity, or marked as confabulation-risk. A false accept here is
an unsupported answer claim escaping the provenance/reality-monitoring rail.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence


CONFABULATION_CASES: tuple[dict[str, Any], ...] = (
    {
        "id": "statistical_trace_only",
        "query": "statistical trace contract alpha",
        "content": "Statistical trace contract alpha support requires source inspection.",
        "source_type": "statistical-trace",
        "metadata": {
            "lifecycle": {"tier": "statistical_trace", "confabulation_risk": True},
            "reality_class": "self_generated",
        },
        "capability_tags": ["statistical-trace"],
    },
    {
        "id": "summary_confabulation_risk",
        "query": "confabulation risk contract beta",
        "content": "Confabulation risk contract beta support requires source inspection.",
        "source_type": "analysis-summary",
        "metadata": {
            "summary": {"kind": "extractive_summary", "confabulation_risk": True},
            "reality_class": "self_generated",
        },
        "capability_tags": ["derived-summary"],
    },
    {
        "id": "simulated_origin_only",
        "query": "simulated origin contract gamma",
        "content": "Simulated origin contract gamma support requires source inspection.",
        "source_type": "simulation",
        "metadata": {
            "summary": {"kind": "abstractive_gist"},
            "reality_class": "simulated",
        },
        "capability_tags": ["simulated-memory"],
    },
)


def run_confabulation_eval() -> dict[str, Any]:
    """Run the deterministic G0 confabulation fixture against the engine."""

    engine = LocalMemoryEngine()
    rows: list[dict[str, Any]] = []
    for index, case in enumerate(CONFABULATION_CASES, start=1):
        tenant = f"g0-confab-{case['id']}"
        cid = engine.append_evidence(
            Evidence(
                tenant_id=tenant,
                user_id="g0-eval",
                actor="system",
                source_type=case["source_type"],
                source_identity=f"g0:{case['id']}",
                content=case["content"],
                metadata=dict(case["metadata"]),
                trust_tier=2,
                capability_tags=list(case["capability_tags"]),
                access_policy={"tenant": tenant},
            )
        )
        result = engine.retrieve(str(case["query"]), tenant)
        accepted = not result.abstained
        gist_support = result.explain.get("gist_support", {})
        rows.append(
            {
                "case_id": case["id"],
                "tenant": tenant,
                "query": case["query"],
                "evidence_cid": cid,
                "accepted": accepted,
                "abstained": result.abstained,
                "confidence": round(float(result.confidence), 6),
                "uncertainty_note": result.uncertainty_note,
                "gist_support_applied": bool(gist_support.get("applied")),
                "gist_hit_ids": list(gist_support.get("gist_hit_ids") or []),
                "hit_count": len(result.hits),
                "rank": index,
                "source_type": case["source_type"],
                "reality_class": case["metadata"].get("reality_class"),
            }
        )

    false_accepts = sum(1 for row in rows if row["accepted"])
    total = len(rows)
    rate = false_accepts / total if total else 1.0
    return {
        "schema_version": "g0.confabulation.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metric": "confabulation_rate",
        "definition": (
            "False-accept rate on cases where the only support is generated, "
            "low-fidelity, or explicitly confabulation-risk provenance."
        ),
        "metric_note": (
            "Deterministic local proxy for the full G0 provenance-entailment "
            "and sampled-audit confabulation metric; this proves the live "
            "retrieval/abstention rail fails closed on generated or risky "
            "support without introducing a network or LLM evaluator."
        ),
        "total_cases": total,
        "false_accepts": false_accepts,
        "rate": round(rate, 6),
        "target": 0.0,
        "passed": rate == 0.0,
        "rows": rows,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the G0 confabulation-rate fixture")
    parser.add_argument("--out", type=Path, help="write the fixture report JSON")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_confabulation_eval()
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.print_json or not args.out:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
