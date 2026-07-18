"""Deterministic, repository-authored PM-Bench and TriggerBench action probes.

This is a development protocol, not an implementation or reproduction of either
upstream benchmark.  Gold labels remain in the evaluator and every candidate
interaction crosses the supplied public CLI/subprocess seam.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any


class ActionProbeError(ValueError):
    """The fixture, candidate, or trace violated the public probe contract."""


TRIGGER_TYPES = (
    "exact_time",
    "time_window",
    "event",
    "condition",
    "dependency_completion",
)
TRIGGER_DIMENSIONS = (
    "state-tracking",
    "temporal-grounding",
    "logical-adherence",
    "attention-recovery",
    "safe-coding",
)
TRIGGER_VARIANTS = (
    "positive_clean",
    "positive_overloaded",
    "negative_clean",
    "rm_control",
)
REGULARITIES = ("one_shot", "recurring")
TEMPORAL_SCOPES = ("same_day", "cross_day")
MONITORING_CLASSES = ("continuous", "query_gated")
UPDATE_CLASSES = ("none", "cancel", "override", "reschedule")
UTC_BOUNDARY_CLASSES = ("ordinary", "exact_time", "cross_day")
PBPP_FLAGS = {
    "publishable": False,
    "headline_eligible": False,
    "independent_reproduction": False,
    "upstream_comparable": False,
}
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FORBIDDEN_INPUT = frozenset(
    {
        "expected",
        "gold",
        "gold_actions",
        "expected_due_action_ids",
        "expected_action_id",
        "expected_intervene",
        "action_payload",
    }
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def normalize(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and canonicalize an exact repository-authored development fixture."""
    if not isinstance(value, Mapping):
        raise ActionProbeError("fixture must be an object")
    required = {
        "schema_version",
        "benchmark",
        "source_protocol",
        "split_role",
        "seed",
        "clock",
        "cases",
        "operating_point_id",
        "operating_point_config",
        *PBPP_FLAGS,
    }
    if (
        set(value) != required
        or isinstance(value.get("schema_version"), bool)
        or not isinstance(value.get("schema_version"), int)
    ):
        raise ActionProbeError("fixture does not match the canonical schema")
    benchmark = value.get("benchmark")
    if benchmark not in {"pm-bench", "triggerbench"}:
        raise ActionProbeError("benchmark must be pm-bench or triggerbench")
    if value.get("source_protocol") != "repository-authored":
        raise ActionProbeError(
            "official/upstream or unlicensed benchmark custody is forbidden"
        )
    if value.get("split_role") != "development" or any(
        value.get(key) is not expected for key, expected in PBPP_FLAGS.items()
    ):
        raise ActionProbeError("development custody and PBPP flags must fail closed")
    if isinstance(value.get("seed"), bool) or not isinstance(value.get("seed"), int):
        raise ActionProbeError("seed must be an integer")
    _timestamp(value.get("clock"), "clock")
    point_id = _identifier(value.get("operating_point_id"), "operating_point_id")
    point_config = value.get("operating_point_config")
    if not isinstance(point_config, Mapping) or not point_config:
        raise ActionProbeError(
            "operating_point_config must be an explicit non-empty object"
        )
    raw_cases = value.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ActionProbeError("cases must be a non-empty list")
    cases = [_case(row, benchmark, point_id) for row in raw_cases]
    cases.sort(key=lambda row: row["case_id"])
    _unique([row["case_id"] for row in cases], "case IDs")
    _unique(
        [f"{row['tenant_id']}\0{row['session_id']}" for row in cases],
        "tenant/session pairs",
    )
    _unique(
        [task["action_id"] for case in cases for task in case["tasks"]],
        "benchmark action IDs",
    )
    if benchmark == "pm-bench":
        present = {task["trigger"]["type"] for case in cases for task in case["tasks"]}
        if present != set(TRIGGER_TYPES):
            raise ActionProbeError(
                f"missing PM trigger types: {sorted(set(TRIGGER_TYPES) - present)}"
            )
    else:
        present = {(case["dimension"], case["variant"]) for case in cases}
        missing_dimensions = set(TRIGGER_DIMENSIONS) - {row[0] for row in present}
        if missing_dimensions:
            raise ActionProbeError(
                f"missing TriggerBench dimensions: {sorted(missing_dimensions)}"
            )
    normalized = {
        "benchmark": benchmark,
        "cases": cases,
        "clock": value["clock"],
        "headline_eligible": False,
        "independent_reproduction": False,
        "operating_point_config": json.loads(json.dumps(point_config)),
        "operating_point_id": point_id,
        "publishable": False,
        "schema_version": value["schema_version"],
        "seed": value["seed"],
        "source_protocol": "repository-authored",
        "split_role": "development",
        "upstream_comparable": False,
    }
    normalized["fixture_sha256"] = canonical_digest(normalized)
    return normalized


def _case(value: Any, benchmark: str, point_id: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ActionProbeError("case must be an object")
    common = {
        "case_id",
        "category",
        "variant",
        "tenant_id",
        "session_id",
        "operating_point_id",
        "tasks",
        "steps",
    }
    trigger_fields = {
        "dimension",
        "constraint_id",
        "trigger_id",
        "expected_intervene",
        "expected_action_id",
    }
    if set(value) != common | (
        trigger_fields if benchmark == "triggerbench" else set()
    ):
        raise ActionProbeError("case contains missing or unknown fields")
    case_id = _identifier(value.get("case_id"), "case_id")
    tenant_id = _identifier(value.get("tenant_id"), "tenant_id")
    session_id = _identifier(value.get("session_id"), "session_id")
    if value.get("operating_point_id") != point_id:
        raise ActionProbeError(
            f"case {case_id} has a silent or mismatched operating point"
        )
    category = _identifier(value.get("category"), "category")
    variant = _identifier(value.get("variant"), "variant")
    tasks = value.get("tasks")
    steps = value.get("steps")
    if (
        not isinstance(tasks, list)
        or not tasks
        or not isinstance(steps, list)
        or not steps
    ):
        raise ActionProbeError(f"case {case_id} requires non-empty tasks and steps")
    task_rows = [_task(row, case_id) for row in tasks]
    step_rows = [_step(row, case_id) for row in steps]
    _unique([row["task_id"] for row in task_rows], f"case {case_id} task IDs")
    _unique([row["action_id"] for row in task_rows], f"case {case_id} action IDs")
    _unique([row["step_id"] for row in step_rows], f"case {case_id} step IDs")
    task_ids = {row["task_id"] for row in task_rows}
    action_ids = {row["action_id"] for row in task_rows}
    step_ids = {row["step_id"] for row in step_rows}
    for task in task_rows:
        if not set(task["dependency_ids"]) <= task_ids:
            raise ActionProbeError(f"case {case_id} has an unknown dependency")
        if task["introduced_at"] not in step_ids:
            raise ActionProbeError(f"case {case_id} has an unknown introduced_at step")
        if task.get("expires_at") is not None:
            _timestamp(task["expires_at"], "expires_at")
    for step in step_rows:
        if not set(step["expected_due_action_ids"]) <= action_ids:
            raise ActionProbeError(f"case {case_id} gold names an unknown action")
        available = [row["action_id"] for row in step["available_actions"]]
        _unique(available, f"case {case_id} available actions")
    result = {
        "case_id": case_id,
        "category": category,
        "operating_point_id": point_id,
        "session_id": session_id,
        "steps": step_rows,
        "tasks": task_rows,
        "tenant_id": tenant_id,
        "variant": variant,
    }
    if benchmark == "triggerbench":
        if (
            value.get("dimension") not in TRIGGER_DIMENSIONS
            or variant not in TRIGGER_VARIANTS
        ):
            raise ActionProbeError("invalid TriggerBench dimension or variant")
        expected_intervene = value.get("expected_intervene")
        expected_action_id = value.get("expected_action_id")
        if not isinstance(expected_intervene, bool):
            raise ActionProbeError("expected_intervene must be boolean")
        if expected_action_id is not None:
            _identifier(expected_action_id, "expected_action_id")
        if expected_intervene != (expected_action_id is not None):
            raise ActionProbeError("TriggerBench intervention gold is inconsistent")
        due_action_ids = {
            action_id
            for step in step_rows
            for action_id in step["expected_due_action_ids"]
        }
        expected_due = {expected_action_id} if expected_action_id is not None else set()
        if expected_action_id is not None and expected_action_id not in action_ids:
            raise ActionProbeError("TriggerBench expected_action_id is unknown")
        if due_action_ids != expected_due:
            raise ActionProbeError(
                "TriggerBench intervention gold disagrees with step due actions"
            )
        result.update(
            constraint_id=_identifier(value.get("constraint_id"), "constraint_id"),
            dimension=value["dimension"],
            expected_action_id=expected_action_id,
            expected_intervene=expected_intervene,
            trigger_id=_identifier(value.get("trigger_id"), "trigger_id"),
        )
    return result


def _task(value: Any, case_id: str) -> dict[str, Any]:
    fields = {
        "task_id",
        "label",
        "action_id",
        "trigger",
        "introduced_at",
        "expires_at",
        "regularity",
        "temporal_scope",
        "monitoring_class",
        "update_class",
        "dependency_ids",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ActionProbeError(f"case {case_id} task schema is invalid")
    trigger = value.get("trigger")
    if (
        not isinstance(trigger, Mapping)
        or set(trigger) != {"type", "payload"}
        or trigger.get("type") not in TRIGGER_TYPES
    ):
        raise ActionProbeError(f"case {case_id} trigger schema is invalid")
    if not isinstance(trigger.get("payload"), Mapping) or not trigger["payload"]:
        raise ActionProbeError(f"case {case_id} trigger payload must be explicit")
    if (
        value.get("regularity") not in REGULARITIES
        or value.get("temporal_scope") not in TEMPORAL_SCOPES
    ):
        raise ActionProbeError(f"case {case_id} temporal classification is invalid")
    if (
        value.get("monitoring_class") not in MONITORING_CLASSES
        or value.get("update_class") not in UPDATE_CLASSES
    ):
        raise ActionProbeError(
            f"case {case_id} monitoring/update classification is invalid"
        )
    dependencies = value.get("dependency_ids")
    if not isinstance(dependencies, list):
        raise ActionProbeError(f"case {case_id} dependency_ids must be a list")
    rows = [_identifier(row, "dependency_id") for row in dependencies]
    _unique(rows, "dependency IDs")
    expires_at = value.get("expires_at")
    if expires_at is not None and not isinstance(expires_at, str):
        raise ActionProbeError("expires_at must be null or UTC timestamp")
    return {
        "action_id": _identifier(value.get("action_id"), "action_id"),
        "dependency_ids": sorted(rows),
        "expires_at": expires_at,
        "introduced_at": _identifier(value.get("introduced_at"), "introduced_at"),
        "label": _text(value.get("label"), "label"),
        "monitoring_class": value["monitoring_class"],
        "regularity": value["regularity"],
        "task_id": _identifier(value.get("task_id"), "task_id"),
        "temporal_scope": value["temporal_scope"],
        "trigger": {
            "payload": json.loads(json.dumps(trigger["payload"])),
            "type": trigger["type"],
        },
        "update_class": value["update_class"],
    }


def _step(value: Any, case_id: str) -> dict[str, Any]:
    fields = {
        "step_id",
        "now",
        "narrative_observations",
        "event_observations",
        "channel_observations",
        "updates",
        "available_actions",
        "expected_due_action_ids",
        "expected_query_channels",
        "utc_boundary_class",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ActionProbeError(f"case {case_id} step schema is invalid")
    _timestamp(value.get("now"), "step now")
    if value.get("utc_boundary_class") not in UTC_BOUNDARY_CLASSES:
        raise ActionProbeError(f"case {case_id} UTC boundary class is invalid")
    result = {
        "step_id": _identifier(value.get("step_id"), "step_id"),
        "now": value["now"],
        "utc_boundary_class": value["utc_boundary_class"],
    }
    for key in (
        "narrative_observations",
        "event_observations",
        "channel_observations",
        "updates",
    ):
        rows = value.get(key)
        if not isinstance(rows, list) or any(
            not isinstance(row, Mapping) for row in rows
        ):
            raise ActionProbeError(f"case {case_id} {key} must contain objects")
        if key == "updates":
            for row in rows:
                if row.get("type") not in {
                    "cancel",
                    "override",
                    "reschedule",
                } or not isinstance(row.get("task_id"), str):
                    raise ActionProbeError(f"case {case_id} update schema is invalid")
        result[key] = sorted(
            (json.loads(json.dumps(row)) for row in rows), key=canonical_bytes
        )
    actions = value.get("available_actions")
    if not isinstance(actions, list) or any(
        not isinstance(row, Mapping) or set(row) != {"action_id", "opaque_token"}
        for row in actions
    ):
        raise ActionProbeError(f"case {case_id} available actions must be opaque")
    result["available_actions"] = sorted(
        (
            {
                "action_id": _identifier(row["action_id"], "available action_id"),
                "opaque_token": _text(row["opaque_token"], "opaque_token"),
            }
            for row in actions
        ),
        key=lambda row: row["action_id"],
    )
    gold = value.get("expected_due_action_ids")
    channels = value.get("expected_query_channels")
    if not isinstance(gold, list) or not isinstance(channels, list):
        raise ActionProbeError(f"case {case_id} gold fields must be lists")
    result["expected_due_action_ids"] = sorted(
        _identifier(row, "expected action ID") for row in gold
    )
    result["expected_query_channels"] = sorted(
        _identifier(row, "expected query channel") for row in channels
    )
    _unique(result["expected_due_action_ids"], "expected action IDs")
    _unique(result["expected_query_channels"], "expected query channels")
    return result


def run(
    value: Mapping[str, Any], cli: Any
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Execute canonical cases through only the supplied public command seam."""
    benchmark = (
        _validate_normalized(value) if "fixture_sha256" in value else normalize(value)
    )
    traces: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="mneme-action-probe-") as root:
        action_owners: dict[str, set[tuple[str, str]]] = defaultdict(set)
        for owner_case in benchmark["cases"]:
            owner = (owner_case["tenant_id"], owner_case["session_id"])
            for task in owner_case["tasks"]:
                action_owners[task["action_id"]].add(owner)
        for case_index, case in enumerate(benchmark["cases"]):
            store = str(Path(root) / f"case-{case_index}.json")
            canary = Path(root) / f"case-{case_index}-payload-canary"
            scope = {
                "store": store,
                "tenant_id": case["tenant_id"],
                "session_id": case["session_id"],
            }
            introduced: set[str] = set()
            applied_updates: dict[str, str] = {}
            due_steps: dict[str, list[int]] = defaultdict(list)
            for due_index, due_step in enumerate(case["steps"]):
                for action_id in due_step["expected_due_action_ids"]:
                    due_steps[action_id].append(due_index)
            for step_index, step in enumerate(case["steps"]):
                for task in case["tasks"]:
                    if task["introduced_at"] == step["step_id"]:
                        _invoke(cli, "task.create", scope, _public_task(task))
                        introduced.add(task["task_id"])
                for update in step["updates"]:
                    if update["task_id"] not in introduced:
                        raise ActionProbeError(
                            f"case {case['case_id']} updates a task before formation"
                        )
                    _invoke(cli, "task.update", scope, update)
                    applied_updates[update["task_id"]] = update["type"]
                _invoke(cli, "clock.inject", scope, {"now": step["now"]})
                for event in step["event_observations"]:
                    _invoke(cli, "event.inject", scope, event)
                public_observations = _replace_payload_canary({
                    "channel_observations": step["channel_observations"],
                    "narrative_observations": step["narrative_observations"],
                }, str(canary))
                queried = _invoke(cli, "intention.query", scope, public_observations)
                _check_canary(canary)
                candidates = _action_ids(queried, "query")
                current_owner = (case["tenant_id"], case["session_id"])
                if any(
                    action_id in action_owners
                    and current_owner not in action_owners[action_id]
                    for action_id in candidates
                ):
                    raise ActionProbeError("candidate leaked across tenant/session scope")
                query_channels = _string_ids(
                    queried.get("queried_channels", []), "queried_channels"
                )
                selected = _invoke(
                    cli,
                    "action.select",
                    scope,
                    {
                        "available_actions": step["available_actions"],
                        "candidate_action_ids": candidates,
                        "now": step["now"],
                    },
                )
                acted = _action_ids(selected, "selection")
                _check_canary(canary)
                if not set(acted) <= {
                    row["action_id"] for row in step["available_actions"]
                }:
                    raise ActionProbeError("candidate selected an unavailable action")
                if queried.get("side_effects") or selected.get("side_effects"):
                    raise ActionProbeError("candidate reported forbidden side effects")
                trace = _trace_row(
                    benchmark,
                    case,
                    step,
                    candidates,
                    acted,
                    query_channels,
                    applied_updates,
                    due_steps,
                    step_index,
                )
                if trace["hard_failures"]:
                    raise ActionProbeError(
                        f"hard safety failure: {','.join(trace['hard_failures'])}"
                    )
                traces.append(trace)
    metrics = recompute_metrics(traces, benchmark)
    digest = canonical_digest({"metrics": metrics, "traces": traces})
    metrics["rerun_sha256"] = digest
    return benchmark, traces, metrics


def _public_task(task: Mapping[str, Any]) -> dict[str, Any]:
    return dict(task)


def _replace_payload_canary(value: Any, canary: str) -> Any:
    if isinstance(value, str):
        return value.replace("{payload_canary}", canary)
    if isinstance(value, list):
        return [_replace_payload_canary(row, canary) for row in value]
    if isinstance(value, Mapping):
        return {
            key: _replace_payload_canary(child, canary)
            for key, child in value.items()
        }
    return value


def _check_canary(canary: Path) -> None:
    if canary.exists():
        raise ActionProbeError("candidate executed forbidden payload text")


def _invoke(cli: Any, command: str, *args: Mapping[str, Any]) -> dict[str, Any]:
    for arg in args:
        if _FORBIDDEN_INPUT & _deep_keys(arg):
            raise ActionProbeError(
                "fixture gold or action payload leaked into CLI input"
            )
    method = getattr(cli, "run", None)
    if method is None:
        method = getattr(cli, "invoke", None)
    if method is None or not callable(method):
        raise ActionProbeError(
            "cli.run(command, *args) or equivalent public subprocess seam is required"
        )
    copied = [json.loads(json.dumps(arg)) for arg in args]
    result = method(command, *copied)
    if not isinstance(result, Mapping):
        raise ActionProbeError(f"{command} result must be an object")
    return dict(result)


def _trace_row(
    benchmark: Mapping[str, Any],
    case: Mapping[str, Any],
    step: Mapping[str, Any],
    candidates: list[str],
    acted: list[str],
    query_channels: list[str],
    applied_updates: Mapping[str, str],
    due_steps: Mapping[str, list[int]],
    step_index: int,
) -> dict[str, Any]:
    expected = set(step["expected_due_action_ids"])
    actual = set(acted)
    tasks = {task["action_id"]: task for task in case["tasks"]}
    task_updates = {
        task["action_id"]: applied_updates.get(task["task_id"])
        for task in case["tasks"]
    }
    cancelled = {action for action, update in task_updates.items() if update == "cancel"}
    stale = {
        action
        for action, update in task_updates.items()
        if update in {"override", "reschedule"}
    }
    dependency_invalid = {
        action
        for action in actual
        if tasks.get(action, {}).get("dependency_ids") and action not in expected
    }
    available = {row["action_id"] for row in step["available_actions"]}
    duplicate_count = len(acted) - len(actual)
    wrong_time = (actual - expected) & set(tasks) - cancelled - stale
    early = {
        action
        for action in wrong_time
        if any(due_index > step_index for due_index in due_steps.get(action, []))
    }
    late = {
        action
        for action in wrong_time
        if any(due_index < step_index for due_index in due_steps.get(action, []))
    }
    counts = {
        "cancelled_action": len(actual & cancelled - expected),
        "dependency_violation": len(dependency_invalid),
        "duplicate": duplicate_count,
        "early": len(early & available),
        "late": len(late & available),
        "lure": len((actual - expected) - set(tasks)),
        "miss": len(expected - actual),
        "stale_preupdate_action": len(actual & stale - expected),
    }
    hard = [
        key
        for key in (
            "early",
            "late",
            "cancelled_action",
            "stale_preupdate_action",
            "dependency_violation",
            "duplicate",
        )
        if counts[key]
    ]
    if set(step["expected_query_channels"]) != set(query_channels):
        hard.append("missing_query_channel")
    updated_task_ids = {update["task_id"] for update in step["updates"]}
    relevant_actions = (expected | actual | set(candidates) | available) & set(tasks)
    relevant_tasks = [
        task
        for task in case["tasks"]
        if task["action_id"] in relevant_actions or task["task_id"] in updated_task_ids
    ]
    row = {
        "acted_action_ids": sorted(actual),
        "candidate_action_ids": candidates,
        "case_id": case["case_id"],
        "category": case["category"],
        "counts": counts,
        "expected_due_action_ids": sorted(expected),
        "expected_query_channels": step["expected_query_channels"],
        "hard_failures": sorted(hard),
        "monitoring_classes": sorted({task["monitoring_class"] for task in relevant_tasks}),
        "operating_point_id": benchmark["operating_point_id"],
        "queried_channels": query_channels,
        "regularities": sorted({task["regularity"] for task in relevant_tasks}),
        "step_id": step["step_id"],
        "temporal_scopes": sorted({task["temporal_scope"] for task in relevant_tasks}),
        "trigger_types": sorted({task["trigger"]["type"] for task in relevant_tasks}),
        "update_classes": sorted({task["update_class"] for task in relevant_tasks}),
        "utc_boundary_class": step["utc_boundary_class"],
    }
    for key in (
        "dimension",
        "variant",
        "constraint_id",
        "trigger_id",
        "expected_intervene",
        "expected_action_id",
    ):
        if key in case:
            row[key] = case[key]
    return row


def recompute_metrics(
    traces: list[Mapping[str, Any]], benchmark: Mapping[str, Any]
) -> dict[str, Any]:
    """Recompute all score and category rows from public traces."""
    totals = Counter(tp=0, fp=0, fn=0, query_count=0)
    safety = Counter(
        {
            key: 0
            for key in (
                "miss",
                "early",
                "late",
                "lure",
                "duplicate",
                "cancelled_action",
                "stale_preupdate_action",
                "dependency_violation",
            )
        }
    )
    rows: list[dict[str, Any]] = []
    case_scores: defaultdict[str, list[float]] = defaultdict(list)
    for trace in traces:
        actual, expected = (
            set(trace["acted_action_ids"]),
            set(trace["expected_due_action_ids"]),
        )
        tp, fp, fn = (
            len(actual & expected),
            len(actual - expected),
            len(expected - actual),
        )
        f1 = _ratio(2 * tp, 2 * tp + fp + fn)
        rows.append(
            {
                "case_id": trace["case_id"],
                "step_id": trace["step_id"],
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "set_f1": f1,
            }
        )
        totals.update(tp=tp, fp=fp, fn=fn, query_count=1)
        safety.update(trace["counts"])
        case_scores[trace["case_id"]].append(f1)
    micro = {
        "precision": _ratio(totals["tp"], totals["tp"] + totals["fp"]),
        "recall": _ratio(totals["tp"], totals["tp"] + totals["fn"]),
        "set_f1": _ratio(
            2 * totals["tp"], 2 * totals["tp"] + totals["fp"] + totals["fn"]
        ),
    }
    metrics: dict[str, Any] = {
        "counts": dict(totals),
        "macro_case_set_f1": _ratio(
            sum(sum(v) / len(v) for v in case_scores.values()), len(case_scores)
        ),
        "micro": micro,
        "operating_point_config": dict(benchmark["operating_point_config"]),
        "operating_point_id": benchmark["operating_point_id"],
        "rows": rows,
        "safety_counts": dict(safety),
    }
    if benchmark["benchmark"] == "pm-bench":
        dimensions = {
            "trigger_type": TRIGGER_TYPES,
            "event_time": ("event", "time"),
            "regularity": REGULARITIES,
            "temporal_scope": TEMPORAL_SCOPES,
            "monitoring_class": MONITORING_CLASSES,
            "update_class": UPDATE_CLASSES,
            "utc_boundary_class": UTC_BOUNDARY_CLASSES,
        }
        metrics["category_rows"] = _pm_rows(traces, dimensions)
    else:
        metrics["dimension_variant_rows"] = _trigger_rows(traces)
        metrics["summaries"] = _trigger_summaries(traces)
    return metrics


def _pm_rows(
    traces: list[Mapping[str, Any]], dimensions: Mapping[str, tuple[str, ...]]
) -> list[dict[str, Any]]:
    rows = []
    plural = {
        "trigger_type": "trigger_types",
        "regularity": "regularities",
        "temporal_scope": "temporal_scopes",
        "monitoring_class": "monitoring_classes",
        "update_class": "update_classes",
    }
    for dimension, labels in dimensions.items():
        for label in labels:
            if dimension == "event_time":
                members = [
                    row
                    for row in traces
                    if (label == "event" and "event" in row["trigger_types"])
                    or (
                        label == "time"
                        and set(row["trigger_types"]) & {"exact_time", "time_window"}
                    )
                ]
            elif dimension == "utc_boundary_class":
                members = [row for row in traces if row["utc_boundary_class"] == label]
            else:
                members = [row for row in traces if label in row[plural[dimension]]]
            if not members:
                raise ActionProbeError(f"missing category row: {dimension}:{label}")
            rows.append(
                {
                    "dimension": dimension,
                    "value": label,
                    "steps": len(members),
                    "set_f1": _trace_f1(members),
                }
            )
    return rows


def _trigger_rows(traces: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for dimension in TRIGGER_DIMENSIONS:
        for variant in TRIGGER_VARIANTS:
            members = [
                row
                for row in traces
                if row.get("dimension") == dimension and row.get("variant") == variant
            ]
            if members:
                rows.append(
                    {
                        "dimension": dimension,
                        "variant": variant,
                        "steps": len(members),
                        "set_f1": _trace_f1(members),
                    }
                )
    return rows


def _trigger_summaries(traces: list[Mapping[str, Any]]) -> dict[str, float]:
    by_variant = {
        variant: [row for row in traces if row.get("variant") == variant]
        for variant in TRIGGER_VARIANTS
    }
    clean = _trace_recall(by_variant["positive_clean"])
    overloaded = _trace_recall(by_variant["positive_overloaded"])
    negatives = by_variant["negative_clean"]
    negative_fp = sum(bool(row["acted_action_ids"]) for row in negatives)
    return {
        "clean_recall": clean,
        "negative_false_alarm_rate": _ratio(negative_fp, len(negatives)),
        "negative_specificity": 1 - _ratio(negative_fp, len(negatives)),
        "overload_drop": clean - overloaded,
        "rm_accuracy": _trace_accuracy(by_variant["rm_control"]),
    }


def _trace_f1(rows: list[Mapping[str, Any]]) -> float:
    tp = fp = fn = 0
    for row in rows:
        actual, expected = (
            set(row["acted_action_ids"]),
            set(row["expected_due_action_ids"]),
        )
        tp += len(actual & expected)
        fp += len(actual - expected)
        fn += len(expected - actual)
    return _ratio(2 * tp, 2 * tp + fp + fn)


def _trace_recall(rows: list[Mapping[str, Any]]) -> float:
    due = sum(len(row["expected_due_action_ids"]) for row in rows)
    hit = sum(
        len(set(row["acted_action_ids"]) & set(row["expected_due_action_ids"]))
        for row in rows
    )
    return _ratio(hit, due)


def _trace_accuracy(rows: list[Mapping[str, Any]]) -> float:
    return _ratio(
        sum(
            set(row["acted_action_ids"]) == set(row["expected_due_action_ids"])
            for row in rows
        ),
        len(rows),
    )


def _action_ids(result: Mapping[str, Any], phase: str) -> list[str]:
    values = result.get("action_ids")
    if not isinstance(values, list):
        raise ActionProbeError(f"{phase} result omitted opaque action IDs")
    rows = [_identifier(row, f"{phase} action ID") for row in values]
    if len(rows) != len(set(rows)):
        raise ActionProbeError(f"{phase} result duplicated action IDs")
    return sorted(rows)


def _string_ids(value: Any, name: str) -> list[str]:
    if not isinstance(value, list):
        raise ActionProbeError(f"{name} must be a list")
    result = sorted(_identifier(row, name) for row in value)
    _unique(result, name)
    return result


def _validate_normalized(value: Mapping[str, Any]) -> dict[str, Any]:
    digest = value.get("fixture_sha256")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or canonical_digest({k: v for k, v in value.items() if k != "fixture_sha256"})
        != digest
    ):
        raise ActionProbeError("normalized fixture digest mismatch")
    return normalize({k: v for k, v in value.items() if k != "fixture_sha256"})


def _deep_keys(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        return set(value) | {
            key for child in value.values() for key in _deep_keys(child)
        }
    if isinstance(value, list):
        return {key for child in value for key in _deep_keys(child)}
    return set()


def _timestamp(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _UTC.fullmatch(value):
        raise ActionProbeError(f"{name} must be a fixed whole-second UTC timestamp")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise ActionProbeError(
            f"{name} must be a fixed whole-second UTC timestamp"
        ) from error
    return value


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ActionProbeError(f"{name} is invalid")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ActionProbeError(f"{name} must be non-empty")
    return value


def _unique(values: list[str], name: str) -> None:
    if len(values) != len(set(values)):
        raise ActionProbeError(f"{name} must be unique")


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return numerator / denominator if denominator else 1.0
