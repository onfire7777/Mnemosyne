from pathlib import Path
from datetime import UTC, datetime, timedelta
import random

import pytest

from eval.harness.cli_driver import CLIError, MnemoCLI
from eval.public.action_cli import ActionCLI


@pytest.mark.parametrize("set_on_update", [False, True])
def test_explicit_recurrence_fires_each_occurrence_once_through_public_cli(
    tmp_path: Path, set_on_update: bool
) -> None:
    cli = ActionCLI(MnemoCLI(store=str(tmp_path / "unused.json")))
    scope = {"store": str(tmp_path / "memory.json"), "tenant_id": "tenant", "session_id": "session"}
    policy = {"type": "interval", "interval_seconds": 60, "max_occurrences": 2}
    task = {
        "task_id": "reminder", "action_id": "action",
        "trigger": {"type": "exact_time", "payload": {"at": "2026-01-01T12:00:00Z"}},
    }
    if not set_on_update:
        task["recurrence_policy"] = policy
    cli.run("task.create", scope, task)
    if set_on_update:
        cli.run("task.update", scope, {
            "type": "override", "task_id": "reminder", "action_id": "action",
            "recurrence_policy": policy,
        })
    actual = []
    for now in ["12:00:00", "12:00:00", "12:00:30", "12:01:00", "12:02:00"]:
        cli.run("clock.inject", scope, {"now": f"2026-01-01T{now}Z"})
        actual.append(cli.run("intention.query", scope, {})["action_ids"])
    assert actual == [["action"], [], [], ["action"], []]


def test_invalid_explicit_recurrence_rejected_by_public_cli(tmp_path: Path) -> None:
    cli = ActionCLI(MnemoCLI(store=str(tmp_path / "unused.json")))
    scope = {"store": str(tmp_path / "memory.json"), "tenant_id": "tenant", "session_id": "session"}
    with pytest.raises(CLIError, match="interval_seconds must be a positive integer"):
        cli.run("task.create", scope, {
            "task_id": "reminder", "action_id": "action",
            "trigger": {"type": "exact_time", "payload": {"at": "2026-01-01T12:00:00Z"}},
            "recurrence_policy": {"type": "interval", "interval_seconds": 0},
        })


@pytest.mark.parametrize("seed", [7, 19, 41, 73, 101])
def test_weekly_recurrence_survives_delayed_polls_and_midstream_cancellation(tmp_path, seed):
    """Real public subprocesses; seeded timing controls, not a full M12 corpus.

    Poll delays are harness inputs, not measured scheduler latency. This checks
    that delayed observations do not shift the next occurrence, duplicate a
    firing, or revive a cancelled recurring intention.
    """
    rng = random.Random(seed)
    start = datetime(2030, 1, 1, tzinfo=UTC) + timedelta(
        days=rng.randrange(730), seconds=rng.randrange(86400),
    )
    cli = ActionCLI(MnemoCLI(store=str(tmp_path / "unused.json"), timeout_s=30))
    scope = {"store": str(tmp_path / "memory.json"), "tenant_id": "tenant", "session_id": "session"}

    def stamp(now):
        return now.isoformat().replace("+00:00", "Z")

    def poll(now):
        cli.run("clock.inject", scope, {"now": stamp(now)})
        return cli.run("intention.query", scope, {})["action_ids"]

    for name in ("keep", "cancel"):
        cli.run("task.create", scope, {
            "task_id": name, "action_id": name,
            "trigger": {"type": "exact_time", "payload": {"at": stamp(start)}},
            "recurrence_policy": {"type": "interval", "interval_seconds": 604800, "max_occurrences": 4},
        })
    delays = [0, 60, 300, 86400]
    rng.shuffle(delays)
    for index, delay in enumerate(delays):
        due = start + timedelta(weeks=index)
        assert poll(due - timedelta(seconds=1)) == []
        observed_at = due + timedelta(seconds=delay)
        assert poll(observed_at) == (["cancel", "keep"] if index < 2 else ["keep"])
        assert poll(observed_at) == []
        if index == 1:
            cli.run("task.update", scope, {"type": "cancel", "task_id": "cancel"})
    assert poll(start + timedelta(weeks=4)) == []
