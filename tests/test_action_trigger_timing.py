from datetime import UTC, datetime, timedelta

import pytest

from eval.harness.cli_driver import MnemoCLI
from eval.public.action_cli import ActionCLI
from eval.public.action_trigger_timing import score_trigger_windows


def stamp(second):
    return (datetime(2030, 1, 1, tzinfo=UTC) + timedelta(seconds=second)).isoformat()


def expected(kind="event", windows=((10, 20),), cancelled=None, action="action"):
    return {
        "action_id": action,
        "occurrence": 0,
        "trigger_type": kind,
        "due_at": stamp(0),
        "windows": [
            {
                "start": stamp(start),
                "end": stamp(end) if end is not None else None,
                "end_inclusive": kind != "time_window",
            }
            for start, end in windows
        ],
        "cancelled_at": stamp(cancelled) if cancelled is not None else None,
    }


def tick(second, actions=(), kind="event"):
    return {
        "action_ids": list(actions),
        "queried_channels": [],
        "evaluated_at": stamp(second),
        "evaluation_wall_ms": 1,
        "firing_observations": [
            {
                "action_id": action,
                "intention_id": action,
                "occurrence": 0,
                "trigger_type": kind,
                "due_at": stamp(0),
                "evaluated_at": stamp(second),
                "provider_evaluated_at": None,
            }
            for action in actions
        ],
    }


def test_eligibility_not_due_at_defines_event_lateness():
    result = score_trigger_windows([expected()], [tick(12, ["action"])])
    assert result["metrics"] == {
        "true_positives": 1,
        "false_positives": 0,
        "false_negatives": 0,
        "precision": 1,
        "recall": 1,
        "f1": 1,
    }
    assert result["mean_lateness_seconds"] == 2
    assert result["cost_usd"] is None and result["publishable"] is False
    assert result["workload_completeness_verified"] is False


def test_transient_windows_do_not_make_inactive_gap_eligible():
    result = score_trigger_windows(
        [expected(windows=((10, 10), (20, 20)))],
        [tick(10), tick(15, ["action"]), tick(20, ["action"])],
    )
    assert (
        result["metrics"]["true_positives"] == result["metrics"]["false_positives"] == 1
    )
    assert result["metrics"]["false_negatives"] == 0
    assert result["invalid_observations"][0]["reason"] == "inactive"
    assert result["mean_lateness_seconds"] == 10
    assert result["duplicate_observations"] == 1


@pytest.mark.parametrize(
    "at,reason", [(5, "early"), (21, "expired"), (30, "cancelled")]
)
def test_invalid_firing_does_not_hide_a_missed_opportunity(at, reason):
    result = score_trigger_windows(
        [expected(cancelled=30)],
        sorted([tick(10), tick(at, ["action"])], key=lambda row: row["evaluated_at"]),
    )
    assert (
        result["metrics"]["false_positives"]
        == result["metrics"]["false_negatives"]
        == 1
    )
    assert result["invalid_observations"][0]["reason"] == reason
    assert result["mean_lateness_seconds"] is None


def test_absent_tick_opportunity_is_disclosed_not_counted_as_a_miss():
    result = score_trigger_windows([expected()], [tick(5), tick(30)])
    assert result["no_observed_opportunity"] == 1
    assert result["metrics"]["recall"] is None
    assert result["metrics"]["false_negatives"] == 0


def test_cancellation_at_tick_boundary_wins_and_empty_windows_never_enable():
    result = score_trigger_windows(
        [expected(cancelled=10), expected(windows=(), action="never")],
        [tick(10, ["action", "never"])],
    )
    assert result["eligible_opportunities"] == 0
    assert result["metrics"]["false_positives"] == 2
    assert {row["reason"] for row in result["invalid_observations"]} == {
        "cancelled",
        "not-eligible",
    }


def test_duplicates_unknown_actions_and_wrong_types_all_count_as_false_positives():
    result = score_trigger_windows(
        [expected()],
        [
            tick(10, ["action", "action", "unknown"]),
            tick(11, ["action"], kind="condition"),
        ],
    )
    assert result["metrics"]["true_positives"] == 1
    assert result["metrics"]["false_positives"] == 3
    assert result["duplicate_observations"] == 2
    assert len(result["unexpected_observations"]) == 1


@pytest.mark.parametrize(
    "windows", [((20, 10),), ((10, 20), (20, 30)), ((10, None), (20, 30))]
)
def test_invalid_windows_fail_closed(windows):
    with pytest.raises(ValueError):
        score_trigger_windows([expected(windows=windows)], [])


def test_all_five_explicit_triggers_cross_real_public_cli(tmp_path):
    adapter = ActionCLI(MnemoCLI(store=str(tmp_path / "unused.json"), timeout_s=30))
    scope = {
        "store": str(tmp_path / "case.json"),
        "tenant_id": "tenant",
        "session_id": "session",
    }
    triggers = {
        "exact_time": {"at": stamp(0)},
        "time_window": {"start": stamp(1), "end": stamp(4)},
        "event": {
            "event_type": "arrived",
            "match": {"code": "yes"},
            "due_at": stamp(0),
        },
        "condition": {
            "condition_id": "ready",
            "operator": "eq",
            "value": True,
            "due_at": stamp(0),
        },
        "dependency_completion": {"due_at": stamp(2)},
    }
    for kind, payload in triggers.items():
        adapter.run(
            "task.create",
            scope,
            {
                "task_id": kind,
                "action_id": kind,
                "trigger": {"type": kind, "payload": payload},
                "dependency_ids": ["exact_time"]
                if kind == "dependency_completion"
                else [],
            },
        )
    observations = []
    for second in range(3):
        adapter.run("clock.inject", scope, {"now": stamp(second)})
        if second == 1:
            adapter.run(
                "event.inject",
                scope,
                {
                    "kind": "event",
                    "event_id": "event-1",
                    "event_type": "arrived",
                    "occurred_at": stamp(1),
                    "payload": {"code": "yes"},
                },
            )
            adapter.run(
                "event.inject",
                scope,
                {
                    "kind": "condition",
                    "condition_id": "ready",
                    "value": True,
                    "observed_at": stamp(1),
                },
            )
        observations.append(adapter.run("intention.observe", scope, {}))
    gold = [
        expected(kind, windows=windows, action=kind)
        for kind, windows in (
            ("exact_time", ((0, None),)),
            ("time_window", ((1, 4),)),
            ("event", ((1, 1),)),
            ("condition", ((1, 1),)),
            ("dependency_completion", ((2, None),)),
        )
    ]
    gold[1]["due_at"] = stamp(1)
    gold[4]["due_at"] = stamp(2)
    result = score_trigger_windows(gold, observations)
    assert result["metrics"]["true_positives"] == 5
    assert (
        result["metrics"]["false_positives"]
        == result["metrics"]["false_negatives"]
        == 0
    )
    assert (
        result["reported_due_drift_observations"]
        == result["duplicate_observations"]
        == 0
    )
    assert all(row["recall"] == 1 for row in result["by_trigger"].values())


def test_time_window_end_matches_public_cli_exclusive_boundary(tmp_path):
    adapter = ActionCLI(MnemoCLI(store=str(tmp_path / "unused.json")))
    scope = {
        "store": str(tmp_path / "case.json"),
        "tenant_id": "tenant",
        "session_id": "session",
    }
    gold = []
    for action, end in (("expired", 1), ("live", 2)):
        adapter.run(
            "task.create",
            scope,
            {
                "task_id": action,
                "action_id": action,
                "trigger": {
                    "type": "time_window",
                    "payload": {"start": stamp(0), "end": stamp(end)},
                },
            },
        )
        gold.append(expected("time_window", windows=((0, end),), action=action))
    adapter.run("clock.inject", scope, {"now": stamp(1)})
    observation = adapter.run("intention.observe", scope, {})
    assert observation["action_ids"] == ["live"]
    result = score_trigger_windows(gold, [observation])
    assert result["metrics"]["true_positives"] == 1
    assert (
        result["metrics"]["false_positives"]
        == result["metrics"]["false_negatives"]
        == 0
    )
    assert result["no_observed_opportunity"] == 1
    rejected = score_trigger_windows(
        [gold[0]], [tick(1, ["expired"], kind="time_window")]
    )
    assert rejected["invalid_observations"][0]["reason"] == "expired"
