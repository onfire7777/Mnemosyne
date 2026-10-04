from pathlib import Path

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
