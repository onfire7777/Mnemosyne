"""G0 resource-usage fixture.

The G0 spec asks the harness to report cost as tokens/query and USD per 1k
queries, plus controller watts/$ for the later always-on controller loop. The
default local path has no paid provider calls, so its provider cost is measured
as zero. Watts/$ is only emitted when an explicit telemetry artifact supplies a
positive controller watt draw and dollar denominator; this module does not
invent power data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence


DEFAULT_DATASET_PATH = Path(__file__).resolve().parents[1] / "datasets" / "resource_usage.json"


def run_resource_usage_eval(
    dataset_path: Path | None = None,
    *,
    telemetry_path: Path | None = None,
) -> dict[str, Any]:
    """Run the local G0 path and compute reported resource metrics."""

    dataset_file = dataset_path or DEFAULT_DATASET_PATH
    dataset = _load_dataset(dataset_file)
    telemetry = _load_telemetry(telemetry_path) if telemetry_path else None
    tenant = dataset["tenant"]
    engine = LocalMemoryEngine()
    for item in dataset["corpus"]:
        engine.append_evidence(
            Evidence(
                tenant_id=tenant,
                user_id="g0-eval",
                actor="system",
                source_type=item["source_type"],
                source_identity=f"g0:resource:{item['case_id']}",
                content=item["content"],
                metadata={"case_id": item["case_id"], "fixture": "g0-resource-usage"},
                trust_tier=1,
                capability_tags=["g0-resource-usage"],
                access_policy={"tenant": tenant},
            )
        )

    rows: list[dict[str, Any]] = []
    input_tokens = 0
    output_tokens = 0
    durations_ms: list[float] = []
    for round_index in range(1, dataset["rounds"] + 1):
        for query_index, query in enumerate(dataset["queries"], start=1):
            started = time.perf_counter()
            result = engine.retrieve(query, tenant)
            duration_ms = (time.perf_counter() - started) * 1000.0
            query_input_tokens = _token_count(query)
            query_output_tokens = 0
            input_tokens += query_input_tokens
            output_tokens += query_output_tokens
            durations_ms.append(duration_ms)
            rows.append(
                {
                    "round": round_index,
                    "query_index": query_index,
                    "query": query,
                    "duration_ms": round(duration_ms, 6),
                    "hit_count": len(result.hits),
                    "billable_input_tokens": query_input_tokens,
                    "billable_output_tokens": query_output_tokens,
                    "external_provider_calls": 0,
                }
            )

    query_count = len(rows)
    cost_model = dataset["cost_model"]
    input_cost = (input_tokens / 1000.0) * cost_model["billable_input_usd_per_1k_tokens"]
    output_cost = (output_tokens / 1000.0) * cost_model["billable_output_usd_per_1k_tokens"]
    fixed_cost = query_count * cost_model["fixed_usd_per_query"]
    total_usd = input_cost + output_cost + fixed_cost
    cost_per_1k = (total_usd / query_count) * 1000.0 if query_count else None
    watts_per_dollar = _controller_watts_per_dollar(telemetry)
    return {
        "schema_version": "g0.resource_usage.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metrics": ["cost_usd_per_1k_queries", "controller_watts_per_dollar"],
        "definition": (
            "Provider spend per 1k local G0 queries and optional controller "
            "watts per dollar from explicit telemetry."
        ),
        "metric_note": (
            "The default fixture instruments the live LocalMemoryEngine path and "
            "records zero paid-provider spend because no external embedding, "
            "reranker, or LLM provider is invoked. controller_watts_per_dollar "
            "is emitted only when a telemetry artifact supplies positive "
            "controller_avg_watts and controller_cost_usd_per_hour values. "
            "The cost denominator is normalized to the supplied measurement "
            "window, defaulting to one hour."
        ),
        "dataset_path": _portable_path(dataset_file),
        "telemetry_sha256": _sha256_path(telemetry_path) if telemetry_path else None,
        "telemetry_path": telemetry_path.name if telemetry_path else None,
        "measurement_scope": dataset["measurement_scope"],
        "provider": cost_model["provider"],
        "currency": cost_model["currency"],
        "query_count": query_count,
        "external_provider_calls": 0,
        "billable_input_tokens": input_tokens,
        "billable_output_tokens": output_tokens,
        "billable_tokens_per_query": round((input_tokens + output_tokens) / query_count, 6)
        if query_count
        else None,
        "total_usd": round(total_usd, 12),
        "cost_usd_per_1k_queries": round(cost_per_1k, 12) if cost_per_1k is not None else None,
        "controller_watts_per_dollar": watts_per_dollar,
        "controller_telemetry_present": telemetry is not None,
        "controller_cost_window_hours": telemetry["controller_cost_window_hours"] if telemetry else None,
        "controller_cost_usd_for_window": telemetry["controller_cost_usd_for_window"] if telemetry else None,
        "controller_telemetry_required_fields": [
            "controller_avg_watts",
            "controller_cost_usd_per_hour",
        ],
        "p95_ms": round(_percentile(durations_ms, 0.95), 6),
        "rows": rows,
    }


def _load_dataset(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("resource-usage dataset must be a JSON object")
    tenant = _require_string(data, "tenant", "dataset")
    measurement_scope = _require_string(data, "measurement_scope", "dataset")
    rounds = data.get("rounds", 1)
    if not isinstance(rounds, int) or rounds < 1:
        raise ValueError("resource-usage dataset rounds must be a positive integer")
    corpus = data.get("corpus")
    if not isinstance(corpus, list) or not corpus:
        raise ValueError("resource-usage dataset corpus must be a non-empty array")
    queries = data.get("queries")
    if not isinstance(queries, list) or not queries or not all(isinstance(q, str) and q for q in queries):
        raise ValueError("resource-usage dataset queries must be a non-empty string array")
    for index, item in enumerate(corpus, start=1):
        _require_string(item, "case_id", f"corpus[{index}]")
        _require_string(item, "content", f"corpus[{index}]")
        _require_string(item, "source_type", f"corpus[{index}]")
    cost_model = data.get("cost_model")
    if not isinstance(cost_model, dict):
        raise ValueError("resource-usage dataset must include a cost_model object")
    provider = _require_string(cost_model, "provider", "cost_model")
    currency = _require_string(cost_model, "currency", "cost_model")
    return {
        "tenant": tenant,
        "measurement_scope": measurement_scope,
        "rounds": rounds,
        "corpus": corpus,
        "queries": queries,
        "cost_model": {
            "provider": provider,
            "currency": currency,
            "billable_input_usd_per_1k_tokens": _require_non_negative_number(
                cost_model,
                "billable_input_usd_per_1k_tokens",
                "cost_model",
            ),
            "billable_output_usd_per_1k_tokens": _require_non_negative_number(
                cost_model,
                "billable_output_usd_per_1k_tokens",
                "cost_model",
            ),
            "fixed_usd_per_query": _require_non_negative_number(
                cost_model,
                "fixed_usd_per_query",
                "cost_model",
            ),
        },
    }


def _load_telemetry(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("controller telemetry must be a JSON object")
    window_hours = _require_positive_number(data, "controller_cost_window_hours", "telemetry") if "controller_cost_window_hours" in data else 1.0
    cost_per_hour = _require_positive_number(
        data,
        "controller_cost_usd_per_hour",
        "telemetry",
    )
    return {
        "controller_avg_watts": _require_positive_number(data, "controller_avg_watts", "telemetry"),
        "controller_cost_usd_per_hour": cost_per_hour,
        "controller_cost_window_hours": window_hours,
        "controller_cost_usd_for_window": cost_per_hour * window_hours,
    }


def _controller_watts_per_dollar(telemetry: dict[str, Any] | None) -> float | None:
    if telemetry is None:
        return None
    return round(telemetry["controller_avg_watts"] / telemetry["controller_cost_usd_for_window"], 6)


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _portable_path(path: Path) -> str:
    repo_root = Path(__file__).resolve().parents[2]
    try:
        return path.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _require_string(item: Any, key: str, label: str) -> str:
    if not isinstance(item, dict) or not isinstance(item.get(key), str) or not item[key]:
        raise ValueError(f"{label} must contain non-empty string field {key}")
    return item[key]


def _require_non_negative_number(item: dict[str, Any], key: str, label: str) -> float:
    value = item.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise ValueError(f"{label} must contain non-negative numeric field {key}")
    return float(value)


def _require_positive_number(item: dict[str, Any], key: str, label: str) -> float:
    value = item.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise ValueError(f"{label} must contain positive numeric field {key}")
    return float(value)


def _token_count(text: str) -> int:
    return len([part for part in text.replace("-", " ").split() if part])


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * percentile))
    return ordered[index]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the G0 resource-usage fixture")
    parser.add_argument("--telemetry", type=Path, help="optional controller power/cost telemetry JSON")
    parser.add_argument("--out", type=Path, help="write the fixture report JSON")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_resource_usage_eval(telemetry_path=args.telemetry)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.print_json or not args.out:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
