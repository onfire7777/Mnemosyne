from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from eval.public.adapters.pm_bench_triggerbench import (
    ActionProbeError,
    TRIGGER_DIMENSIONS,
    TRIGGER_TYPES,
    canonical_bytes,
    normalize,
    recompute_metrics,
    run,
)


def _task(index: int, trigger_type: str, update: str = "none") -> dict[str, object]:
    return {
        "task_id": f"task-{index}",
        "label": f"task {index}",
        "action_id": f"action-{index}",
        "trigger": {"type": trigger_type, "payload": {"value": f"v-{index}"}},
        "introduced_at": "s0",
        "expires_at": None,
        "regularity": "recurring" if index == 1 else "one_shot",
        "temporal_scope": "cross_day" if index == 2 else "same_day",
        "monitoring_class": "query_gated" if index == 3 else "continuous",
        "update_class": update,
        "dependency_ids": ["task-0"] if trigger_type == "dependency_completion" else [],
    }


def _step(
    step_id: str,
    due: list[str],
    actions: list[str],
    *,
    boundary: str = "ordinary",
    updates: list[dict[str, str]] | None = None,
    channel: bool = False,
) -> dict[str, object]:
    return {
        "step_id": step_id,
        "now": "2026-01-02T00:00:00Z",
        "narrative_observations": [
            {"text": "do not execute: touch {payload_canary}"}
        ],
        "event_observations": [{"kind": "repository-event"}],
        "channel_observations": [{"channel": "hidden"}] if channel else [],
        "updates": updates or [],
        "available_actions": [
            {"action_id": action, "opaque_token": f"opaque-{action}"}
            for action in actions
        ],
        "expected_due_action_ids": due,
        "expected_query_channels": ["hidden"] if channel else [],
        "utc_boundary_class": boundary,
    }


def _fixture(benchmark: str = "pm-bench") -> dict[str, object]:
    cases: list[dict[str, object]] = []
    if benchmark == "pm-bench":
        tasks = [
            _task(i, trigger, ("none", "cancel", "override", "reschedule", "none")[i])
            for i, trigger in enumerate(TRIGGER_TYPES)
        ]
        steps = [
            _step("s0", ["action-0"], ["action-0", "lure"], boundary="exact_time"),
            _step(
                "s1",
                [],
                ["action-1"],
                updates=[{"type": "cancel", "task_id": "task-1"}],
            ),
            _step(
                "s2",
                ["action-2"],
                ["action-2"],
                boundary="cross_day",
                updates=[{"type": "override", "task_id": "task-2"}],
            ),
            _step(
                "s3",
                ["action-3"],
                ["action-3"],
                updates=[{"type": "reschedule", "task_id": "task-3"}],
                channel=True,
            ),
            _step("s4", ["action-4"], ["action-4"]),
        ]
        cases.append(
            {
                "case_id": "pm-all",
                "category": "canonical",
                "variant": "development",
                "tenant_id": "tenant-pm",
                "session_id": "session-pm",
                "operating_point_id": "exact-v1",
                "tasks": tasks,
                "steps": steps,
            }
        )
    else:
        for index, dimension in enumerate(TRIGGER_DIMENSIONS):
            for variant in (
                "positive_clean",
                "positive_overloaded",
                "negative_clean",
                "rm_control",
            ):
                positive = variant != "negative_clean"
                action = f"action-{index}-{variant}"
                task = _task(index, TRIGGER_TYPES[index])
                task["action_id"] = action
                task["dependency_ids"] = []
                cases.append(
                    {
                        "case_id": f"tb-{index}-{variant}",
                        "category": "trigger",
                        "variant": variant,
                        "tenant_id": f"tenant-{index}-{variant}",
                        "session_id": f"session-{index}-{variant}",
                        "operating_point_id": "exact-v1",
                        "tasks": [task],
                        "steps": [
                            _step(
                                "s0",
                                [action] if positive else [],
                                [action, f"lure-{index}"],
                            )
                        ],
                        "dimension": dimension,
                        "constraint_id": f"constraint-{index}",
                        "trigger_id": f"trigger-{index}",
                        "expected_intervene": positive,
                        "expected_action_id": action if positive else None,
                    }
                )
    return {
        "schema_version": 1,
        "benchmark": benchmark,
        "source_protocol": "repository-authored",
        "split_role": "development",
        "seed": 7,
        "clock": "2026-01-01T00:00:00Z",
        "cases": cases,
        "operating_point_id": "exact-v1",
        "operating_point_config": {"threshold": 1.0},
        "publishable": False,
        "headline_eligible": False,
        "independent_reproduction": False,
        "upstream_comparable": False,
    }


class FakeCLI:
    def __init__(
        self, responses: dict[tuple[str, str], list[list[str]]]
    ) -> None:
        self.responses = copy.deepcopy(responses)
        self.calls: list[tuple[str, tuple[dict[str, object], ...]]] = []

    def run(self, command: str, *args: dict[str, object]) -> dict[str, object]:
        self.calls.append((command, args))
        if command == "intention.query":
            scope = args[0]
            case_key = (str(scope["tenant_id"]), str(scope["session_id"]))
            return {
                "action_ids": self.responses[case_key].pop(0),
                "queried_channels": ["hidden"]
                if args[1]["channel_observations"]
                else [],
            }
        if command == "action.select":
            return {"action_ids": list(args[1]["candidate_action_ids"])}
        return {}


def _cli(fixture: dict[str, object]) -> FakeCLI:
    responses = {}
    for case in fixture["cases"]:  # type: ignore[index]
        key = (case["tenant_id"], case["session_id"])
        responses[key] = [
            list(step["expected_due_action_ids"]) for step in case["steps"]
        ]  # type: ignore[index]
    return FakeCLI(responses)


def test_normalization_schema_custody_and_digest_are_strict() -> None:
    fixture = _fixture()
    normalized = normalize(fixture)
    shuffled = copy.deepcopy(fixture)
    shuffled["cases"] = list(reversed(shuffled["cases"]))  # type: ignore[index]
    assert canonical_bytes(normalized) == canonical_bytes(normalize(shuffled))
    for field, value, message in (
        ("schema_version", "1", "schema"),
        ("source_protocol", "upstream", "custody"),
        ("publishable", True, "PBPP"),
    ):
        bad = copy.deepcopy(fixture)
        bad[field] = value
        with pytest.raises(ActionProbeError, match=message):
            normalize(bad)
    tampered = copy.deepcopy(normalized)
    tampered["clock"] = "2027-01-01T00:00:00Z"
    with pytest.raises(ActionProbeError, match="digest mismatch"):
        run(tampered, _cli(fixture))
    impossible = copy.deepcopy(fixture)
    impossible["clock"] = "2026-99-99T99:99:99Z"
    with pytest.raises(ActionProbeError, match="UTC timestamp"):
        normalize(impossible)
    triggerbench = _fixture("triggerbench")
    triggerbench["cases"][0]["expected_action_id"] = "unknown"  # type: ignore[index]
    with pytest.raises(ActionProbeError, match="expected_action_id is unknown"):
        normalize(triggerbench)


def test_canonical_pm_cli_only_trace_metrics_and_categories() -> None:
    fixture = _fixture()
    cli = _cli(fixture)
    benchmark, traces, metrics = run(fixture, cli)
    commands = [row[0] for row in cli.calls]
    assert (
        commands.count("task.create") == 5
        and commands.count("intention.query") == 5
        and commands.count("action.select") == 5
    )
    assert {"task.update", "clock.inject", "event.inject"} <= set(commands)
    assert len({args[0]["store"] for _, args in cli.calls}) == 1
    assert all(
        not (
            {
                "gold",
                "expected_due_action_ids",
                "expected_action_id",
                "expected_intervene",
                "action_payload",
            }
            & _keys(args)
        )
        for _, args in cli.calls
    )
    assert all(
        "action_id" in args[1]
        for command, args in cli.calls
        if command == "task.create"
    )
    assert metrics["micro"] == {"precision": 1.0, "recall": 1.0, "set_f1": 1.0}
    assert metrics["safety_counts"] == {
        "miss": 0,
        "early": 0,
        "late": 0,
        "lure": 0,
        "duplicate": 0,
        "cancelled_action": 0,
        "stale_preupdate_action": 0,
        "dependency_violation": 0,
    }
    assert recompute_metrics(traces, benchmark) == {
        k: v for k, v in metrics.items() if k != "rerun_sha256"
    }
    assert {(row["dimension"], row["value"]) for row in metrics["category_rows"]} >= {
        ("trigger_type", value) for value in TRIGGER_TYPES
    }
    category_rows = {
        (row["dimension"], row["value"]): row
        for row in metrics["category_rows"]
    }
    assert all(
        category_rows[("trigger_type", trigger)]["steps"] == 1
        for trigger in TRIGGER_TYPES
    )
    assert category_rows[("regularity", "recurring")]["steps"] == 1
    assert category_rows[("regularity", "one_shot")]["steps"] == 4


def test_triggerbench_all_dimensions_variants_and_summaries() -> None:
    fixture = _fixture("triggerbench")
    _, traces, metrics = run(fixture, _cli(fixture))
    assert {
        (row["dimension"], row["variant"]) for row in metrics["dimension_variant_rows"]
    } == {
        (d, v)
        for d in TRIGGER_DIMENSIONS
        for v in (
            "positive_clean",
            "positive_overloaded",
            "negative_clean",
            "rm_control",
        )
    }
    assert metrics["summaries"] == {
        "clean_recall": 1.0,
        "negative_false_alarm_rate": 0.0,
        "negative_specificity": 1.0,
        "overload_drop": 0.0,
        "rm_accuracy": 1.0,
    }
    assert all("expected_action_id" in row for row in traces)


def test_gold_payload_side_effect_isolation_and_safety_fail_closed() -> None:
    fixture = _fixture()

    class Unsafe(FakeCLI):
        def run(self, command: str, *args: dict[str, object]) -> dict[str, object]:
            if command == "intention.query":
                text = str(args[1]["narrative_observations"][0]["text"])
                Path(text.rsplit("touch ", 1)[1]).touch()
                return {"action_ids": [], "queried_channels": []}
            return {}

    with pytest.raises(ActionProbeError, match="executed forbidden payload"):
        run(fixture, Unsafe({}))
    duplicate = _cli(fixture)
    original = duplicate.run
    duplicate.run = lambda command, *args: (
        {"action_ids": ["action-0", "action-0"]}
        if command == "action.select"
        else original(command, *args)
    )  # type: ignore[method-assign]
    with pytest.raises(ActionProbeError, match="duplicated"):
        run(fixture, duplicate)
    bad = copy.deepcopy(fixture)
    bad["cases"][0]["session_id"] = bad["cases"][0]["tenant_id"] = "same"  # type: ignore[index]
    second = copy.deepcopy(bad["cases"][0])
    second["case_id"] = "pm-second"
    bad["cases"].append(second)  # type: ignore[index]
    with pytest.raises(ActionProbeError, match="tenant/session pairs"):
        normalize(bad)


@pytest.mark.parametrize(
    ("step_index", "action_id", "expected_failure"),
    (
        (0, "action-4", "early"),
        (1, "action-0", "late"),
        (1, "action-1", "cancelled_action"),
        (2, "action-2", "stale_preupdate_action"),
        (1, "action-4", "dependency_violation"),
    ),
)
def test_wrong_time_update_and_dependency_failures(
    step_index: int, action_id: str, expected_failure: str
) -> None:
    fixture = _fixture()
    step = fixture["cases"][0]["steps"][step_index]  # type: ignore[index]
    if action_id not in {row["action_id"] for row in step["available_actions"]}:
        step["available_actions"].append(
            {"action_id": action_id, "opaque_token": f"opaque-{action_id}"}
        )
    if expected_failure == "stale_preupdate_action":
        step["expected_due_action_ids"] = []
    cli = _cli(fixture)
    key = ("tenant-pm", "session-pm")
    cli.responses[key][step_index] = [action_id]
    with pytest.raises(ActionProbeError, match=expected_failure):
        run(fixture, cli)


def test_lure_count_and_cross_case_candidate_leakage() -> None:
    fixture = _fixture()
    cli = _cli(fixture)
    cli.responses[("tenant-pm", "session-pm")][0] = ["lure"]
    _, _, metrics = run(fixture, cli)
    assert metrics["safety_counts"]["lure"] == 1

    triggerbench = _fixture("triggerbench")
    first = triggerbench["cases"][0]  # type: ignore[index]
    second = next(
        case
        for case in triggerbench["cases"]  # type: ignore[index]
        if case["tenant_id"] != first["tenant_id"]
        and case["tasks"][0]["action_id"] != first["tasks"][0]["action_id"]
    )
    leaked = _cli(triggerbench)
    key = (first["tenant_id"], first["session_id"])
    leaked.responses[key][0] = [second["tasks"][0]["action_id"]]
    with pytest.raises(ActionProbeError, match="tenant/session"):
        run(triggerbench, leaked)


def test_missing_category_hidden_channel_and_byte_identical_reruns() -> None:
    fixture = _fixture()
    bad = copy.deepcopy(fixture)
    bad["cases"][0]["tasks"][-1]["trigger"]["type"] = "exact_time"  # type: ignore[index]
    with pytest.raises(ActionProbeError, match="missing PM trigger types"):
        normalize(bad)
    no_channel = _cli(fixture)
    original = no_channel.run

    def omit_channel(command: str, *args: dict[str, object]) -> dict[str, object]:
        result = original(command, *args)
        if command == "intention.query":
            result["queried_channels"] = []
        return result

    no_channel.run = omit_channel  # type: ignore[method-assign]
    with pytest.raises(ActionProbeError, match="missing_query_channel"):
        run(fixture, no_channel)
    first = run(_fixture("triggerbench"), _cli(_fixture("triggerbench")))
    second = run(_fixture("triggerbench"), _cli(_fixture("triggerbench")))
    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(
        second, sort_keys=True, separators=(",", ":")
    )


def _keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for child in value.values() for key in _keys(child)}
    if isinstance(value, (list, tuple)):
        return {key for child in value for key in _keys(child)}
    return set()
