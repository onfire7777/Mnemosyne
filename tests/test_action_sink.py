from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from eval.public.action_sink import ActionSink


def sink(path, **scope):
    return ActionSink(path, **{"run_id": "run", "case_id": "case", "tenant_id": "tenant", "session_id": "session", **scope})


def test_delivery_survives_reopen_preserves_retries_and_rejects_conflicts(tmp_path):
    path = tmp_path / "sink.sqlite3"
    first = sink(path).deliver(intention_id="i", occurrence=0, action_id="a")
    again = sink(path).deliver(intention_id="i", occurrence=0, action_id="a", origin="harness-retry")
    conflict = sink(path).deliver(intention_id="i", occurrence=0, action_id="changed")
    snapshot = sink(path).snapshot()
    assert first["outcome"] == "accepted"
    assert again["outcome"] == "duplicate"
    assert conflict["outcome"] == "conflict"
    assert first["receipt_id"] == again["receipt_id"] == conflict["receipt_id"]
    assert len(snapshot["receipts"]) == 1 and snapshot["receipts"][0]["action_id"] == "a"
    assert [row["outcome"] for row in snapshot["attempts"]] == ["accepted", "duplicate", "conflict"]
    assert snapshot["attempts"][1]["origin"] == "harness-retry"


def test_concurrent_delivery_commits_one_receipt_and_retains_every_attempt(tmp_path):
    current = sink(tmp_path / "sink.sqlite3")
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(lambda _: current.deliver(intention_id="i", occurrence=0, action_id="a"), range(16)))
    assert sum(row["outcome"] == "accepted" for row in rows) == 1
    assert sum(row["outcome"] == "duplicate" for row in rows) == 15
    assert len(current.snapshot()["receipts"]) == 1
    assert len(current.snapshot()["attempts"]) == 16


@pytest.mark.parametrize("field", ["run_id", "case_id", "tenant_id", "session_id"])
def test_scope_is_part_of_identity_and_snapshot_is_scoped(tmp_path, field):
    path = tmp_path / "sink.sqlite3"
    first = sink(path)
    other = sink(path, **{field: "other"})
    one = first.deliver(intention_id="i", occurrence=0, action_id="a")
    two = other.deliver(intention_id="i", occurrence=0, action_id="a")
    assert one["receipt_id"] != two["receipt_id"]
    assert len(first.snapshot()["receipts"]) == len(other.snapshot()["receipts"]) == 1
    assert len(first.snapshot()["attempts"]) == len(other.snapshot()["attempts"]) == 1


def test_occurrences_are_distinct_and_data_is_never_executed(tmp_path):
    current = sink(tmp_path / "sink.sqlite3")
    canary = tmp_path / "must-not-exist"
    data = f"$(touch {canary})"
    rows = [current.deliver(intention_id="i", occurrence=i, action_id=data) for i in (0, 1)]
    assert all(row["outcome"] == "accepted" for row in rows)
    assert not canary.exists()


def test_foreign_database_is_not_modified(tmp_path):
    path = tmp_path / "foreign.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT)")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="not a supported"):
        sink(path)
    assert path.read_bytes() == before


def test_receipt_and_attempt_commit_atomically(tmp_path):
    path = tmp_path / "sink.sqlite3"
    current = sink(path)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TRIGGER injected_failure BEFORE INSERT ON attempts BEGIN SELECT RAISE(ABORT, 'injected'); END")
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        current.deliver(intention_id="i", occurrence=0, action_id="a")
    assert current.snapshot()["receipts"] == current.snapshot()["attempts"] == []


@pytest.mark.parametrize("occurrence", [-1, True, 9223372036854775808])
def test_invalid_occurrence_does_not_write(tmp_path, occurrence):
    current = sink(tmp_path / "sink.sqlite3")
    with pytest.raises(ValueError):
        current.deliver(intention_id="i", occurrence=occurrence, action_id="a")
    assert current.snapshot()["attempts"] == []
