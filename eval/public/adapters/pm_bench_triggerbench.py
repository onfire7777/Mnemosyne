"""Deterministic development-fixture probes for PM-Bench and TriggerBench.

These probes are intentionally not official benchmark implementations.  They exercise
the public CLI action seam without granting the candidate access to labels or payloads.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any


class ActionProbeError(ValueError):
    """The fixture or candidate output violated the action-probe contract."""


PM_CATEGORIES = ("time", "event", "monitoring", "update")
TRIGGER_DIMENSIONS = ("time", "event", "dependency", "overload", "risk", "logical")
PBPP_FLAGS = {
    "publishable": False,
    "pbpp_headline_eligible": False,
    "comparable_to_official": False,
}
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FORBIDDEN_INPUT = frozenset({"expected", "gold", "gold_actions", "payload", "should_act"})


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def normalize(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and canonicalize a repository-authored development fixture."""
    if not isinstance(value, Mapping):
        raise ActionProbeError("fixture must be an object")
    allowed = {"schema_version", "suite", "custody", "clock", "operating_point", "cases"}
    if set(value) != allowed or value.get("schema_version") != 1:
        raise ActionProbeError("fixture does not match canonical schema v1")
    suite = value.get("suite")
    if suite not in {"pm-bench-dev", "triggerbench-dev"}:
        raise ActionProbeError("only repository-authored development suites are available")
    custody = value.get("custody")
    if custody != {"kind": "repository-authored", **PBPP_FLAGS}:
        raise ActionProbeError("custody must fail closed with all PBPP development flags")
    clock = value.get("clock")
    if not isinstance(clock, str) or not _UTC.fullmatch(clock):
        raise ActionProbeError("clock must be a fixed whole-second UTC timestamp")
    point = value.get("operating_point")
    if not isinstance(point, Mapping) or set(point) != {"name", "threshold"}:
        raise ActionProbeError("operating_point must be explicit")
    if not isinstance(point["name"], str) or not point["name"]:
        raise ActionProbeError("operating_point name must be non-empty")
    threshold = point["threshold"]
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
        raise ActionProbeError("operating_point threshold must be between zero and one")
    raw_cases = value.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ActionProbeError("cases must be a non-empty list")
    cases = [_case(row, suite) for row in raw_cases]
    cases.sort(key=lambda row: row["id"])
    ids = [row["id"] for row in cases]
    if len(ids) != len(set(ids)):
        raise ActionProbeError("case IDs must be unique")
    required = set(PM_CATEGORIES if suite == "pm-bench-dev" else TRIGGER_DIMENSIONS)
    field = "category" if suite == "pm-bench-dev" else "dimension"
    present = {row[field] for row in cases}
    if present != required:
        raise ActionProbeError(f"missing required {field} rows: {sorted(required - present)}")
    normalized = {
        "cases": cases,
        "clock": clock,
        "custody": dict(custody),
        "operating_point": {"name": point["name"], "threshold": threshold},
        "schema_version": 1,
        "suite": suite,
    }
    normalized["fixture_sha256"] = canonical_digest(normalized)
    return normalized


def _case(value: Any, suite: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ActionProbeError("case must be an object")
    common = {"id", "at", "events", "query", "expected_action_ids"}
    variant = {"category"} if suite == "pm-bench-dev" else {"dimension", "variant", "available"}
    if set(value) != common | variant:
        raise ActionProbeError("case contains missing or unknown fields")
    case_id = value.get("id")
    if not isinstance(case_id, str) or not _ID.fullmatch(case_id):
        raise ActionProbeError("case id is invalid")
    at = value.get("at")
    if not isinstance(at, str) or not _UTC.fullmatch(at):
        raise ActionProbeError(f"case {case_id} has an invalid UTC clock")
    query = value.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ActionProbeError(f"case {case_id} query must be non-empty")
    events = value.get("events")
    if not isinstance(events, list) or any(not isinstance(row, Mapping) for row in events):
        raise ActionProbeError(f"case {case_id} events must be objects")
    event_rows = [dict(row) for row in events]
    event_rows.sort(key=canonical_bytes)
    gold = value.get("expected_action_ids")
    if not isinstance(gold, list) or any(not isinstance(x, str) or not _ID.fullmatch(x) for x in gold):
        raise ActionProbeError(f"case {case_id} expected action IDs are invalid")
    if len(gold) != len(set(gold)):
        raise ActionProbeError(f"case {case_id} expected action IDs are duplicated")
    result: dict[str, Any] = {
        "at": at,
        "events": event_rows,
        "expected_action_ids": sorted(gold),
        "id": case_id,
        "query": query,
    }
    if suite == "pm-bench-dev":
        if value["category"] not in PM_CATEGORIES:
            raise ActionProbeError("unknown PM-Bench category")
        result["category"] = value["category"]
    else:
        if value["dimension"] not in TRIGGER_DIMENSIONS:
            raise ActionProbeError("unknown TriggerBench dimension")
        if value["variant"] not in {"pm", "rm"} or not isinstance(value["available"], bool):
            raise ActionProbeError("invalid TriggerBench variant availability")
        result.update(dimension=value["dimension"], variant=value["variant"], available=value["available"])
    return result


def run(value: Mapping[str, Any], cli: Any) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Run every available case through isolated query then act CLI invocations."""
    benchmark = _validate_normalized(value) if "fixture_sha256" in value else normalize(value)
    traces: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="mneme-action-probe-") as root:
        for index, case in enumerate(benchmark["cases"]):
            if case.get("available") is False:
                continue
            store = str(Path(root) / f"{index}.json")
            public = {key: case[key] for key in ("id", "at", "events", "query")}
            query_result = _invoke(cli, ["actions", "query"], {**public, "store": store})
            candidates = _action_ids(query_result, "query")
            act_result = _invoke(
                cli,
                ["actions", "act"],
                {"action_ids": candidates, "at": case["at"], "case_id": case["id"], "store": store},
            )
            acted = _action_ids(act_result, "act")
            if not set(acted) <= set(candidates):
                raise ActionProbeError(f"case {case['id']} acted on an unqueried action")
            if query_result.get("side_effects") or act_result.get("side_effects"):
                raise ActionProbeError(f"case {case['id']} reported forbidden side effects")
            trace = {
                "acted_action_ids": acted,
                "candidate_action_ids": candidates,
                "case_id": case["id"],
                "clock": case["at"],
                "errors": int(bool(query_result.get("error"))) + int(bool(act_result.get("error"))),
                "expected_action_ids": case["expected_action_ids"],
                "operating_point": benchmark["operating_point"],
                "safety_violations": 0,
                "suite": benchmark["suite"],
            }
            for key in ("category", "dimension", "variant"):
                if key in case:
                    trace[key] = case[key]
            traces.append(trace)
    metrics = recompute_metrics(traces, benchmark)
    digest = canonical_digest({"metrics": metrics, "traces": traces})
    metrics["rerun_sha256"] = digest
    if canonical_digest({"metrics": {k: v for k, v in metrics.items() if k != "rerun_sha256"}, "traces": traces}) != digest:
        raise ActionProbeError("rerun digest mismatch")
    return benchmark, traces, metrics


def _invoke(cli: Any, argv: list[str], payload: dict[str, Any]) -> dict[str, Any]:
    if _FORBIDDEN_INPUT & payload.keys():
        raise ActionProbeError("gold or payload leaked into CLI input")
    invoke: Callable[..., Any] | None = getattr(cli, "invoke", None)
    if invoke is None and callable(cli):
        invoke = cli
    if invoke is None:
        raise ActionProbeError("a public CLI invocation seam is required")
    result = invoke(list(argv), json.loads(json.dumps(payload)))
    if not isinstance(result, Mapping):
        raise ActionProbeError("CLI result must be an object")
    return dict(result)


def _action_ids(result: Mapping[str, Any], phase: str) -> list[str]:
    values = result.get("action_ids")
    if not isinstance(values, list) or any(not isinstance(x, str) or not _ID.fullmatch(x) for x in values):
        raise ActionProbeError(f"{phase} result omitted opaque action IDs")
    if len(values) != len(set(values)):
        raise ActionProbeError(f"{phase} result duplicated action IDs")
    return sorted(values)


def recompute_metrics(traces: list[Mapping[str, Any]], benchmark: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute exact set metrics and required grouped rows from traces alone."""
    rows: list[dict[str, Any]] = []
    totals = {"tp": 0, "fp": 0, "fn": 0, "errors": 0, "safety_violations": 0}
    group_key = "category" if benchmark["suite"] == "pm-bench-dev" else "dimension_variant"
    for trace in traces:
        actual, expected = set(trace["acted_action_ids"]), set(trace["expected_action_ids"])
        row = {
            "case_id": trace["case_id"],
            "fn": len(expected - actual),
            "fp": len(actual - expected),
            "tp": len(actual & expected),
        }
        row["precision"] = _ratio(row["tp"], row["tp"] + row["fp"])
        row["recall"] = _ratio(row["tp"], row["tp"] + row["fn"])
        rows.append(row)
        for key in ("tp", "fp", "fn", "errors", "safety_violations"):
            totals[key] += int(trace.get(key, row.get(key, 0)))
    grouped: list[dict[str, Any]] = []
    labels = PM_CATEGORIES if group_key == "category" else tuple(
        f"{dimension}:{variant}" for dimension in TRIGGER_DIMENSIONS for variant in ("pm", "rm")
    )
    for label in labels:
        members = [t for t in traces if (t.get("category") if group_key == "category" else f"{t.get('dimension')}:{t.get('variant')}") == label]
        if members or group_key == "category":
            grouped.append({"group": label, "cases": len(members)})
    if group_key == "category" and any(row["cases"] == 0 for row in grouped):
        raise ActionProbeError("PM-Bench trace is missing required category rows")
    return {
        "counts": totals,
        "f1": _ratio(2 * totals["tp"], 2 * totals["tp"] + totals["fp"] + totals["fn"]),
        "group_rows": grouped,
        "operating_point": dict(benchmark["operating_point"]),
        "precision": _ratio(totals["tp"], totals["tp"] + totals["fp"]),
        "recall": _ratio(totals["tp"], totals["tp"] + totals["fn"]),
        "rows": rows,
        "trace_count": len(traces),
    }


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def _validate_normalized(value: Mapping[str, Any]) -> dict[str, Any]:
    digest = value.get("fixture_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ActionProbeError("normalized fixture digest is invalid")
    raw = {key: item for key, item in value.items() if key != "fixture_sha256"}
    if canonical_digest(raw) != digest:
        raise ActionProbeError("normalized fixture digest mismatch")
    # Re-validating the public shape also rejects forged normalized fixtures.
    return normalize(raw)
