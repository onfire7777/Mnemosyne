"""Fault injection drops successful public CLI responses, never fakes a write."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from eval.harness.cli_driver import CLIError, MnemoCLI
from eval.public.action_cli import ActionCLI, ActionCLIError


@pytest.mark.parametrize("seed", [7, 19, 41, 73, 101])
@pytest.mark.parametrize("cancel_before_due", [False, True])
def test_lost_operation_responses_recover_through_public_cli(
    tmp_path, monkeypatch, seed, cancel_before_due
):
    driver = MnemoCLI(store=str(tmp_path / "unused.json"), timeout_s=30)
    scope = {
        "store": str(tmp_path / "case.json"),
        "tenant_id": "tenant",
        "session_id": "session",
    }
    due = (datetime(2030, 1, 1, tzinfo=UTC) + timedelta(weeks=seed)).isoformat()
    task = {
        "task_id": "reminder",
        "action_id": "original",
        "idempotency_key": "create-1",
        "trigger": {"type": "exact_time", "payload": {"at": due}},
    }
    original = MnemoCLI.run
    dropped = []

    def lose_first_response(self, command, *args, **kwargs):
        result = original(self, command, *args, **kwargs)
        if (
            command in {"intention-schedule", "intention-update", "intention-cancel"}
            and command not in dropped
        ):
            assert result.ok
            dropped.append(command)
            raise TimeoutError(
                "injected response loss after successful subprocess exit"
            )
        return result

    monkeypatch.setattr(MnemoCLI, "run", lose_first_response)
    adapter = ActionCLI(driver)
    with pytest.raises(TimeoutError):
        adapter.run("task.create", scope, task)
    # Rebuild all adapter state. The production process is fresh on every call.
    adapter = ActionCLI(driver)
    assert adapter.run("task.create", scope, task) == {}
    before = adapter.run("task.inspect", scope, {"task_id": "reminder"})
    update = {
        "type": "override",
        "task_id": "reminder",
        "action_id": "revised",
        "idempotency_key": "update-1",
        "expected_revision": before["revision"],
    }
    with pytest.raises(TimeoutError):
        adapter.run("task.update", scope, update)
    adapter = ActionCLI(driver)
    adapter.run("task.create", scope, task)
    assert adapter.run("task.update", scope, update) == {}
    after = adapter.run("task.inspect", scope, {"task_id": "reminder"})
    assert after["intention_id"] == before["intention_id"]
    assert after["revision"] != before["revision"]
    assert after["action_id"] == "revised"
    with pytest.raises(CLIError, match="idempotency conflict"):
        adapter.run("task.update", scope, {**update, "action_id": "conflicting"})
    with pytest.raises(CLIError, match="revision conflict"):
        adapter.run(
            "task.update", scope, {**update, "idempotency_key": "fresh-stale-request"}
        )
    assert adapter.run("task.inspect", scope, {"task_id": "reminder"}) == after
    if cancel_before_due:
        cancel = {
            "type": "cancel",
            "task_id": "reminder",
            "idempotency_key": "cancel-1",
            "expected_revision": after["revision"],
        }
        with pytest.raises(TimeoutError):
            adapter.run("task.update", scope, cancel)
        adapter = ActionCLI(driver)
        adapter.run("task.create", scope, task)
        adapter.run("task.update", scope, update)
        assert adapter.run("task.update", scope, cancel) == {}
        with pytest.raises(CLIError, match="revision conflict"):
            adapter.run(
                "task.update", scope, {**cancel, "idempotency_key": "cancel-stale"}
            )
    adapter.run("clock.inject", scope, {"now": due})
    assert adapter.run("intention.observe", scope, {})["action_ids"] == (
        [] if cancel_before_due else ["revised"]
    )
    assert adapter.run("intention.observe", scope, {})["action_ids"] == []
    adapter.run("task.update", scope, update)
    assert adapter.run("task.inspect", scope, {"task_id": "reminder"})["status"] == (
        "cancelled" if cancel_before_due else "fired"
    )
    assert dropped == ["intention-schedule", "intention-update"] + (
        ["intention-cancel"] if cancel_before_due else []
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", "other"),
        ("session_id", "other"),
        ("user_id", "other"),
        ("agent_id", "other"),
        ("revision", "invalid"),
        ("status", "unknown"),
    ],
)
def test_inspection_rejects_misbound_provider_state(
    tmp_path, monkeypatch, field, value
):
    def run(self, command, *args, **kwargs):
        if command == "capture":
            return SimpleNamespace(json={"cid": "origin"})
        if command == "intention-schedule":
            return SimpleNamespace(json={"intention_id": "known"})
        assert command == "intention-list"
        assert "--include-revision" in args
        row = {
            "intention_id": "known",
            "tenant_id": "tenant",
            "session_id": "session",
            "user_id": "mnemosyne-public-eval-user",
            "agent_id": "mnemosyne-public-eval-agent",
            "revision": "a" * 64,
            "status": "scheduled",
            "action": {"ref": "action"},
        }
        row[field] = value
        return SimpleNamespace(json={"intentions": [row]})

    monkeypatch.setattr(MnemoCLI, "run", run)
    adapter = ActionCLI(MnemoCLI(store=str(tmp_path / "unused.json")))
    scope = {
        "store": str(tmp_path / "case.json"),
        "tenant_id": "tenant",
        "session_id": "session",
    }
    adapter.run(
        "task.create",
        scope,
        {
            "task_id": "task",
            "action_id": "action",
            "trigger": {
                "type": "exact_time",
                "payload": {"at": "2030-01-01T00:00:00Z"},
            },
        },
    )
    with pytest.raises(ActionCLIError):
        adapter.run("task.inspect", scope, {"task_id": "task"})


def test_keyed_task_binding_and_cancel_preconditions_fail_before_writes(
    tmp_path, monkeypatch
):
    calls = []

    def run(self, command, *args, **kwargs):
        calls.append(command)
        if command == "capture":
            return SimpleNamespace(json={"cid": "origin"})
        assert command == "intention-schedule"
        return SimpleNamespace(json={"intention_id": "known"})

    monkeypatch.setattr(MnemoCLI, "run", run)
    adapter = ActionCLI(MnemoCLI(store=str(tmp_path / "unused.json")))
    scope = {
        "store": str(tmp_path / "case.json"),
        "tenant_id": "tenant",
        "session_id": "session",
    }
    task = {
        "task_id": "task",
        "action_id": "action",
        "idempotency_key": "create-1",
        "trigger": {"type": "exact_time", "payload": {"at": "2030-01-01T00:00:00Z"}},
    }
    adapter.run("task.create", scope, task)
    for changed in ({**task, "idempotency_key": "other"}, {**task, "task_id": "other"}):
        with pytest.raises(ActionCLIError):
            adapter.run("task.create", scope, changed)
    with pytest.raises(ActionCLIError, match="expected_revision"):
        adapter.run(
            "task.update",
            scope,
            {
                "type": "cancel",
                "task_id": "task",
                "idempotency_key": "cancel-1",
            },
        )
    assert calls == ["capture", "intention-schedule"]
