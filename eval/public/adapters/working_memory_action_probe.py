"""Deterministic development probe for action choices from working memory.

The probe deliberately drives only ``MnemoCLI.run``.  It never imports a memory
engine and never exposes fixture gold labels to the deterministic policy.
"""

from __future__ import annotations

import json
import random
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from eval.harness.cli_driver import MnemoCLI

SCHEMA_VERSION = 1
SUITE = "working-memory-action-v1"
SCORING_PROFILE = "working-memory-action-v1"
ITEM_CATEGORIES = (
    "active_goal",
    "current_plan_step",
    "active_constraint",
    "unresolved_question",
    "recent_tool_result",
    "intermediate_conclusion",
)
OPERATIONS = frozenset({"put", "replace", "resolve", "expire", "observe"})
OPERATING_POINT = {
    "policy": "highest-task-relevance-then-item-id",
    "positive_threshold": 0.75,
}
_TOP_KEYS = {
    "schema_version", "suite", "split_role", "seed", "operating_point", "cases"
}
_CASE_KEYS = {
    "case_id", "tenant_id", "session_id", "now", "category", "action_choices",
    "expected_action_id", "expected_abstain", "events",
}
_EVENT_REQUIRED = {
    "event_id", "at", "operation", "item_id", "item_type", "content",
    "task_relevance", "tenant_id", "session_id", "user_id", "agent_id",
    "task_id", "branch",
}
_EVENT_OPTIONAL = {"expires_at", "supersedes"}
_CHOICE_KEYS = {"action_id", "item_id"}


def run(
    fixture: Mapping[str, Any], cli: MnemoCLI
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Validate, execute, and score a frozen working-memory action fixture."""
    normalized = normalize(fixture)
    traces: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="mneme-working-action-") as temp:
        for index, case in enumerate(normalized["cases"]):
            case_cli = (
                replace(cli, store=str(Path(temp) / f"{index}.store.json"))
                if isinstance(cli, MnemoCLI)
                else cli
            )
            visible, command_log = _execute_case(case, case_cli)
            decision = choose_action(
                visible,
                case["action_choices"],
                threshold=normalized["operating_point"]["positive_threshold"],
            )
            traces.append(
                {
                    "case_id": case["case_id"],
                    "category": case["category"],
                    "status": "abstain" if decision is None else "action",
                    "predicted_action_id": decision,
                    "visible_item_ids": sorted(
                        item["item_id"] for item in visible if _valid_visible_item(item)
                    ),
                    "command_log": command_log,
                    "scoring_family": "deterministic-action",
                }
            )
    labels = [
        {
            "case_id": case["case_id"],
            "expected_action_id": case["expected_action_id"],
            "expected_abstain": case["expected_abstain"],
        }
        for case in normalized["cases"]
    ]
    return normalized, traces, score(labels, traces, seed=normalized["seed"])


def normalize(value: Mapping[str, Any]) -> dict[str, Any]:
    """Strictly validate and return a canonical, detached JSON value."""
    if not isinstance(value, Mapping) or set(value) != _TOP_KEYS:
        raise ValueError("working-action fixture has invalid top-level fields")
    if value.get("schema_version") != SCHEMA_VERSION or isinstance(
        value.get("schema_version"), bool
    ):
        raise ValueError("working-action schema_version must be 1")
    if value.get("suite") != SUITE or value.get("split_role") != "development":
        raise ValueError("working-action fixture has invalid suite custody")
    seed = value.get("seed")
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise ValueError("working-action seed must be a non-negative integer")
    if value.get("operating_point") != OPERATING_POINT:
        raise ValueError("working-action operating_point is not frozen")
    cases = value.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("working-action cases must be a non-empty array")
    if [case.get("case_id") for case in cases if isinstance(case, Mapping)] != sorted(
        case.get("case_id") for case in cases if isinstance(case, Mapping)
    ):
        raise ValueError("working-action cases must be sorted by case_id")

    seen_cases: set[str] = set()
    seen_scopes: set[tuple[str, str]] = set()
    categories: set[str] = set()
    normalized_cases: list[dict[str, Any]] = []
    for raw_case in cases:
        case = _validate_case(raw_case)
        case_id = case["case_id"]
        if case_id in seen_cases:
            raise ValueError(f"duplicate working-action case_id: {case_id}")
        seen_cases.add(case_id)
        scope = (case["tenant_id"], case["session_id"])
        if scope in seen_scopes:
            raise ValueError("working-action cases must use fresh tenant/session scopes")
        seen_scopes.add(scope)
        categories.add(case["category"])
        normalized_cases.append(case)
    if categories != set(ITEM_CATEGORIES):
        raise ValueError("working-action fixture must cover all six item categories")
    return json.loads(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "suite": SUITE,
                "split_role": "development",
                "seed": seed,
                "operating_point": OPERATING_POINT,
                "cases": normalized_cases,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def choose_action(
    visible_items: list[dict[str, Any]],
    action_choices: list[dict[str, str]],
    *,
    threshold: float,
) -> str | None:
    """Choose from visible state only; expected labels are intentionally absent."""
    action_by_item = {choice["item_id"]: choice["action_id"] for choice in action_choices}
    candidates = [
        item for item in visible_items
        if _valid_visible_item(item)
        and item["item_id"] in action_by_item
        and float(item.get("task_relevance", 0.0)) >= threshold
    ]
    if not candidates:
        return None
    chosen = min(candidates, key=lambda item: (-float(item["task_relevance"]), item["item_id"]))
    return action_by_item[chosen["item_id"]]


def score(
    labels: list[dict[str, Any]], traces: list[dict[str, Any]], *, seed: int
) -> dict[str, Any]:
    """Recompute deterministic action metrics from scoring-side gold custody."""
    if [row.get("case_id") for row in labels] != [row.get("case_id") for row in traces]:
        raise ValueError("working-action labels and traces are misaligned")
    rows: list[dict[str, Any]] = []
    for label, trace in zip(labels, traces, strict=True):
        expected = label.get("expected_action_id")
        abstain = label.get("expected_abstain")
        predicted = trace.get("predicted_action_id")
        if not isinstance(abstain, bool) or (abstain != (expected is None)):
            raise ValueError("working-action gold is internally inconsistent")
        rows.append(
            {
                "case_id": label["case_id"],
                "category": trace["category"],
                "status": trace["status"],
                "correct": predicted == expected,
                "positive": not abstain,
                "predicted_positive": predicted is not None,
            }
        )
    total = len(rows)
    tp = sum(row["positive"] and row["correct"] for row in rows)
    fp = sum(row["predicted_positive"] and not row["correct"] for row in rows)
    positives = sum(row["positive"] for row in rows)
    negatives = total - positives
    tn = sum(not row["positive"] and not row["predicted_positive"] for row in rows)
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, positives)
    per_category = _group_accuracy(rows, "category", ITEM_CATEGORIES)
    per_status = _group_accuracy(rows, "status", ("action", "abstain"))
    return {
        "profile": SCORING_PROFILE,
        "trace_count": total,
        "decision_accuracy": _ratio(sum(row["correct"] for row in rows), total),
        "positive_precision": precision,
        "positive_recall": recall,
        "positive_f1": _ratio(2 * precision * recall, precision + recall),
        "abstention_specificity": _ratio(tn, negatives),
        "false_action_rate": _ratio(negatives - tn, negatives),
        "bootstrap_macro_accuracy": _bootstrap_macro(rows, seed),
        "category_rows": per_category,
        "status_rows": per_status,
        "isolation_rows": [
            {
                "isolation": "tenant_session",
                "cases": total,
                "accuracy": _ratio(sum(row["correct"] for row in rows), total),
            }
        ],
        "hard_gate_violations": {
            "fixture_gold_exposed_to_policy": 0,
            "foreign_scope_visible": 0,
            "payload_executed": 0,
            "automatic_durable_promotion": 0,
        },
    }


def _validate_case(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _CASE_KEYS:
        raise ValueError("working-action case has invalid fields")
    case = dict(value)
    for name in ("case_id", "tenant_id", "session_id"):
        _string(case.get(name), name)
    _timestamp(case.get("now"), "now")
    if case.get("category") not in ITEM_CATEGORIES:
        raise ValueError("working-action case has unknown category")
    choices = case.get("action_choices")
    if not isinstance(choices, list) or any(
        not isinstance(choice, Mapping) or set(choice) != _CHOICE_KEYS for choice in choices
    ):
        raise ValueError("working-action action_choices are invalid")
    for choice in choices:
        _string(choice.get("action_id"), "action_id")
        _string(choice.get("item_id"), "choice item_id")
    if [choice["action_id"] for choice in choices] != sorted(
        choice["action_id"] for choice in choices
    ) or len({choice["action_id"] for choice in choices}) != len(choices):
        raise ValueError("working-action choices must have sorted unique opaque IDs")
    expected = case.get("expected_action_id")
    abstain = case.get("expected_abstain")
    if not isinstance(abstain, bool) or (expected is None) != abstain:
        raise ValueError("working-action expected label is inconsistent")
    if expected is not None and expected not in {choice["action_id"] for choice in choices}:
        raise ValueError("working-action expected action is not a choice")
    events = case.get("events")
    if not isinstance(events, list) or not events:
        raise ValueError("working-action events must be non-empty")
    if [event.get("event_id") for event in events if isinstance(event, Mapping)] != sorted(
        event.get("event_id") for event in events if isinstance(event, Mapping)
    ):
        raise ValueError("working-action events must be sorted by event_id")
    seen_events: set[str] = set()
    for event in events:
        _validate_event(event, case, seen_events)
    return json.loads(json.dumps(case, sort_keys=True, separators=(",", ":")))


def _validate_event(event: Any, case: dict[str, Any], seen: set[str]) -> None:
    if not isinstance(event, Mapping) or not _EVENT_REQUIRED <= set(event) or not set(event) <= (
        _EVENT_REQUIRED | _EVENT_OPTIONAL
    ):
        raise ValueError("working-action event has invalid fields")
    event_id = _string(event.get("event_id"), "event_id")
    if event_id in seen:
        raise ValueError(f"duplicate working-action event_id: {event_id}")
    seen.add(event_id)
    _timestamp(event.get("at"), "event at")
    if event.get("operation") not in OPERATIONS:
        raise ValueError("working-action event has unknown operation")
    for name in ("item_id", "item_type", "user_id", "agent_id", "task_id", "branch"):
        _string(event.get(name), name)
    if event.get("item_type") not in ITEM_CATEGORIES:
        raise ValueError("working-action event has unknown item_type")
    if not isinstance(event.get("content"), str):
        raise ValueError("working-action event content must be a string")
    relevance = event.get("task_relevance")
    if isinstance(relevance, bool) or not isinstance(relevance, (int, float)) or not 0 <= relevance <= 1:
        raise ValueError("working-action task_relevance must be between zero and one")
    if event.get("tenant_id") != case["tenant_id"] or event.get("session_id") != case["session_id"]:
        raise ValueError("working-action event crosses its case scope")
    for name in _EVENT_OPTIONAL & set(event):
        if name == "expires_at":
            _timestamp(event[name], name)
        elif event[name] is not None:
            _string(event[name], name)


def _execute_case(case: dict[str, Any], cli: Any) -> tuple[list[dict[str, Any]], list[str]]:
    command_log: list[str] = []
    for event in case["events"]:
        operation = event["operation"]
        if operation in {"put", "replace"}:
            captured = cli.run(
                "capture", "--tenant", event["tenant_id"], "--user", event["user_id"],
                "--actor", "user", "--source-type", "working-action-probe",
                "--session-id", event["session_id"], "--content", event["content"],
            ).json
            cid = captured.get("cid") if isinstance(captured, Mapping) else None
            if not isinstance(cid, str) or not cid:
                raise ValueError("working-action capture omitted evidence CID")
            ttl = _ttl_seconds(event["at"], event.get("expires_at"))
            cli.run(
                "working-seed", *_scope_args(event), "--kind", event["item_type"],
                "--content", event["content"], "--evidence-cid", cid,
                "--ttl-seconds", str(ttl), "--created-at", event["at"],
                "--item-id", event["item_id"], "--source-trust-tier", "1",
            )
            command_log.extend(["capture", "working-seed"])
        elif operation in {"resolve", "expire"}:
            cli.run(
                "working-expire", *_scope_args(event), "--expired-at", event["at"],
                "--role", "operator", "--source-trust-tier", "0",
            )
            command_log.append("working-expire")
        else:
            command_log.append("observe")
    query = cli.run("working-query", *_scope_args(case["events"][-1]), "--as-of", case["now"]).json
    command_log.append("working-query")
    items = query.get("items") if isinstance(query, Mapping) else None
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ValueError("working-action query returned invalid items")
    return items, command_log


def _scope_args(event: Mapping[str, Any]) -> list[str]:
    return [
        "--tenant", event["tenant_id"], "--session-id", event["session_id"],
        "--user", event["user_id"], "--agent-id", event["agent_id"],
        "--task-id", event["task_id"], "--branch", event["branch"],
    ]


def _ttl_seconds(created: str, expires: Any) -> int:
    start = _timestamp(created, "created_at")
    if expires is None:
        return 86_400
    seconds = int((_timestamp(expires, "expires_at") - start).total_seconds())
    if seconds < 1 or seconds > 86_400:
        raise ValueError("working-action TTL must be within one day")
    return seconds


def _valid_visible_item(item: Mapping[str, Any]) -> bool:
    return isinstance(item.get("item_id"), str) and isinstance(
        item.get("task_relevance"), (int, float)
    ) and not isinstance(item.get("task_relevance"), bool)


def _timestamp(value: Any, name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"working-action {name} must be RFC3339 UTC with Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError(f"working-action {name} is invalid") from error
    if parsed.tzinfo != UTC or parsed.microsecond:
        raise ValueError(f"working-action {name} must be fixed whole-second UTC")
    return parsed


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"working-action {name} must be a non-empty canonical string")
    return value


def _ratio(numerator: float, denominator: float) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def _group_accuracy(
    rows: list[dict[str, Any]], key: str, required: tuple[str, ...]
) -> list[dict[str, Any]]:
    result = []
    for value in required:
        selected = [row for row in rows if row[key] == value]
        result.append(
            {key: value, "cases": len(selected), "accuracy": _ratio(sum(row["correct"] for row in selected), len(selected))}
        )
    return result


def _bootstrap_macro(rows: list[dict[str, Any]], seed: int) -> dict[str, Any]:
    by_category = {category: [row for row in rows if row["category"] == category] for category in ITEM_CATEGORIES}
    generator = random.Random(seed)
    samples: list[float] = []
    for _ in range(1_000):
        category_scores = []
        for category in ITEM_CATEGORIES:
            group = by_category[category]
            drawn = [generator.choice(group) for _ in group]
            category_scores.append(_ratio(sum(row["correct"] for row in drawn), len(drawn)))
        samples.append(sum(category_scores) / len(category_scores))
    samples.sort()
    return {"seed": seed, "samples": 1_000, "mean": sum(samples) / len(samples), "ci95": [samples[24], samples[974]]}
