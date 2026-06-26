"""G0 deep-path latency fixture.

This measures the local deep-search path over a small graph-backed corpus. It is
reported-only G0 evidence: useful for comparing future deep-path changes, but
not a production latency claim.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Relation


DEFAULT_DATASET_PATH = Path(__file__).resolve().parents[1] / "datasets" / "deep_latency.json"


def run_deep_latency_eval(dataset_path: Path | None = None) -> dict[str, Any]:
    """Run the versioned corpus through the live local deep-search path."""

    dataset_file = dataset_path or DEFAULT_DATASET_PATH
    dataset = _load_dataset(dataset_file)
    tenant = dataset["tenant"]
    engine = LocalMemoryEngine()
    for relation in dataset["relations"]:
        engine.add_relation(
            Relation(
                tenant_id=tenant,
                source=relation["source"],
                predicate=relation["predicate"],
                target=relation["target"],
                source_evidence_cids=[],
                access_policy={"tenant": tenant},
            )
        )

    queries = list(dataset["queries"])
    rounds = int(dataset["rounds"])
    rows: list[dict[str, Any]] = []
    durations: list[float] = []
    for round_index in range(1, rounds + 1):
        for query_index, query in enumerate(queries, start=1):
            started = time.perf_counter()
            result = engine.deep_search(query, tenant)
            duration_ms = (time.perf_counter() - started) * 1000.0
            durations.append(duration_ms)
            rows.append(
                {
                    "round": round_index,
                    "query_index": query_index,
                    "query": query,
                    "duration_ms": round(duration_ms, 6),
                    "hit_count": len(result.hits),
                    "graph_hits": result.explain["channels"]["graph_ppr"],
                    "abstained": result.abstained,
                }
            )

    p50 = _percentile(durations, 0.50)
    p95 = _percentile(durations, 0.95)
    return {
        "schema_version": "g0.deep_latency.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metric": "deep_path_p95_ms",
        "definition": "95th-percentile latency for local graph-backed deep-search queries.",
        "metric_note": (
            "Local reported-only deep-search timing fixture. It measures the "
            "live LocalMemoryEngine deep path over a versioned graph corpus; "
            "it is not production infrastructure evidence."
        ),
        "dataset_path": str(dataset_file.resolve()),
        "query_count": len(rows),
        "unique_queries": len(queries),
        "rounds": rounds,
        "p50_ms": round(p50, 6),
        "p95_ms": round(p95, 6),
        "max_ms": round(max(durations), 6) if durations else 0.0,
        "rows": rows,
    }


def _load_dataset(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("deep-latency dataset must be a JSON object")
    tenant = data.get("tenant")
    if not isinstance(tenant, str) or not tenant:
        raise ValueError("deep-latency dataset tenant must be a non-empty string")
    rounds = data.get("rounds", 1)
    if not isinstance(rounds, int) or rounds < 1:
        raise ValueError("deep-latency dataset rounds must be a positive integer")
    queries = data.get("queries")
    if not isinstance(queries, list) or not queries or not all(isinstance(q, str) and q for q in queries):
        raise ValueError("deep-latency dataset queries must be a non-empty string array")
    relations = data.get("relations")
    if not isinstance(relations, list) or not relations:
        raise ValueError("deep-latency dataset relations must be a non-empty array")
    for index, relation in enumerate(relations, start=1):
        _require_string(relation, "source", f"relations[{index}]")
        _require_string(relation, "predicate", f"relations[{index}]")
        _require_string(relation, "target", f"relations[{index}]")
    return {"tenant": tenant, "rounds": rounds, "queries": queries, "relations": relations}


def _require_string(item: Any, key: str, label: str) -> None:
    if not isinstance(item, dict) or not isinstance(item.get(key), str) or not item[key]:
        raise ValueError(f"{label} must contain non-empty string field {key}")


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * percentile))
    return ordered[index]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the G0 deep-path latency fixture")
    parser.add_argument("--out", type=Path, help="write the fixture report JSON")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_deep_latency_eval()
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.print_json or not args.out:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
