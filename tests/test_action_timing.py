import copy

import pytest

from eval.public.action_timing import score_exact_time


def expected(action="a", due="2030-01-01T00:00:00Z", cancelled=False):
    return {"action_id": action, "occurrence": 0, "due_at": due, "cancelled": cancelled}


def tick(actions=("a",), now="2030-01-01T00:00:10Z"):
    return {"action_ids": list(actions), "queried_channels": [], "evaluated_at": now,
            "evaluation_wall_ms": 12.5, "firing_observations": [
                {"action_id": action, "intention_id": "int-" + action, "occurrence": 0,
                 "trigger_type": "exact_time", "due_at": "2030-01-01T00:00:00Z", "evaluated_at": now,
                 "provider_evaluated_at": now}
                for action in actions]}


def test_timing_preserves_missing_early_late_cancelled_duplicate_and_unexpected():
    schedule = [expected(), expected("early", "2030-01-01T00:00:20Z"), expected("missing"),
                expected("future", "2030-01-02T00:00:00Z"), expected("cancel", cancelled=True)]
    observed = [tick(("a", "a", "early", "cancel", "unknown"))]
    before = copy.deepcopy((schedule, observed))
    report = score_exact_time(schedule, observed)
    assert report["status_counts"] == {"early": 1, "on-time": 0, "late": 1, "missed": 1,
                                       "pending": 1, "cancelled-fired": 1, "cancelled-unfired": 0}
    assert report["duplicate_observations"] == 1
    assert report["unexpected_observations"][0]["action_id"] == "unknown"
    assert report["lateness_observed_denominator"] == 2
    assert report["mean_lateness_seconds"] == 5
    assert report["max_lateness_seconds"] == 10
    assert report["reported_due_drift_observations"] == 1
    assert report["evaluation_command_wall_ms"] == 12.5
    assert (schedule, observed) == before


def test_missing_has_null_lateness_and_no_ticks_means_pending():
    report = score_exact_time([expected()], [tick(())])
    assert report["status_counts"]["missed"] == 1
    assert report["mean_lateness_seconds"] is report["max_lateness_seconds"] is None
    assert report["lateness_observed_denominator"] == 0
    assert score_exact_time([expected()], [])["status_counts"]["pending"] == 1


def test_duplicate_later_observation_does_not_shift_first_firing_time():
    report = score_exact_time([expected()], [tick(now="2030-01-01T00:00:00Z"), tick()])
    assert report["duplicate_observations"] == 1
    assert report["status_counts"]["on-time"] == 1
    assert report["max_lateness_seconds"] == 0


@pytest.mark.parametrize("mutation", ["clock", "provider-clock", "wall", "ids", "unknown", "type", "occurrence", "due"])
def test_timing_rejects_invalid_or_inconsistent_observations(mutation):
    row = tick()
    if mutation == "clock":
        row["firing_observations"][0]["evaluated_at"] = "2031-01-01T00:00:00Z"
    elif mutation == "provider-clock":
        row["firing_observations"][0]["provider_evaluated_at"] = "2031-01-01T00:00:00Z"
    elif mutation == "wall":
        row["evaluation_wall_ms"] = float("nan")
    elif mutation == "ids":
        row["action_ids"] = []
    elif mutation == "unknown":
        row["approved"] = True
    elif mutation == "type":
        row["firing_observations"][0]["trigger_type"] = "event"
    elif mutation == "occurrence":
        row["firing_observations"][0]["occurrence"] = True
    else:
        row["firing_observations"][0]["due_at"] = "2030-01-01T00:00:00"
    with pytest.raises(ValueError):
        score_exact_time([expected()], [row])


def test_timing_rejects_backwards_clock_and_duplicate_expectations():
    with pytest.raises(ValueError, match="backwards"):
        score_exact_time([expected()], [tick(), tick(now="2030-01-01T00:00:00Z")])
    with pytest.raises(ValueError, match="duplicate occurrence"):
        score_exact_time([expected(), expected()], [tick()])


def test_absent_provider_clock_stays_absent_in_diagnostic():
    row = tick()
    row["firing_observations"][0]["provider_evaluated_at"] = None
    report = score_exact_time([expected()], [row])
    assert report["rows"][0]["observations"][0]["provider_evaluated_at"] is None
    assert report["mean_lateness_seconds"] == 10
