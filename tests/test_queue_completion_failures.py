"""Failed result persistence must not strand durable jobs in running state."""

import sqlite3

import pytest

from mnemosyne.queue import PostgresQueue, QueueJob, QueueWorker, SqliteQueue


@pytest.mark.parametrize("failure_source", ["result", "handler"])
def test_worker_records_type_errors_and_exhausts_attempts(tmp_path, failure_source):
    queue = SqliteQueue(tmp_path, "tenant")
    try:
        queued = queue.enqueue("result", {}, max_attempts=2)
        def handler(payload):
            if failure_source == "handler":
                raise TypeError("handler input is not serializable")
            return {"bad": object()}

        worker = QueueWorker(queue, {"result": handler})

        first = worker.run_once()
        assert first.id == queued.id
        assert first.status == "retry"
        assert queue.jobs[queued.id].status == "retry"
        assert queue.jobs[queued.id].attempts == 1
        assert "serializable" in queue.jobs[queued.id].last_error

        second = worker.run_once()
        assert second.status == "dead"
        assert queue.jobs[queued.id].status == "dead"
        assert queue.jobs[queued.id].attempts == 2
        assert worker.run_once() is None
    finally:
        queue.close()


@pytest.mark.parametrize("operation", ["complete", "fail"])
def test_postgres_failed_status_write_preserves_running_job(monkeypatch, operation):
    pytest.importorskip("psycopg")
    # No database is needed to test in-memory state at a failed connection
    # boundary; schema setup is outside this lifecycle test's scope.
    monkeypatch.setattr(PostgresQueue, "ensure_schema", lambda self: None)
    queue = PostgresQueue("unused", "tenant", require_safe_role=False)
    job = QueueJob(kind="result", payload={}, status="running", attempts=1, result={"answer": 42})
    queue._leased[job.id] = job
    before = job.to_dict()

    def unavailable():
        raise ConnectionError("database unavailable")

    monkeypatch.setattr(queue, "connect", unavailable)
    with pytest.raises(ConnectionError, match="database unavailable"):
        if operation == "complete":
            queue.complete(job.id)
        else:
            queue.fail(job.id, "handler failed")

    assert job.to_dict() == before
    persisted = []
    monkeypatch.setattr(queue, "_update_status", lambda job_id, **fields: persisted.append((job_id, fields)))
    queue.complete(job.id)
    assert job.status == "complete"
    assert persisted == [(job.id, {"status": "complete", "result": {"answer": 42}})]


def test_failed_completion_preserves_lease_result_for_retry(tmp_path):
    queue = SqliteQueue(tmp_path, "tenant")
    try:
        queued = queue.enqueue("result", {})
        leased = queue.lease()
        leased.result = object()
        with pytest.raises(TypeError):
            queue.complete(queued.id)

        assert leased.status == "running"
        assert queue.jobs[queued.id].status == "running"
        leased.result = {"answer": 42}
        queue.complete(queued.id)
        assert leased.status == "complete"
        assert queue.jobs[queued.id].status == "complete"
        assert queue.jobs[queued.id].result == {"answer": 42}
    finally:
        queue.close()


def test_sqlite_failed_failure_write_preserves_lease(tmp_path):
    queue = SqliteQueue(tmp_path, "tenant")
    try:
        queued = queue.enqueue("result", {})
        leased = queue.lease()
        leased.result = {"answer": 42}
        # Exercise a real aborted write, without replacing queue methods.
        queue._conn.execute(
            "CREATE TEMP TRIGGER fail_status_write BEFORE UPDATE ON runtime_jobs "
            "BEGIN SELECT RAISE(ABORT, 'write rejected'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="write rejected"):
            queue.fail(queued.id, "handler failed")
        assert leased.status == "running"
        assert queue.jobs[queued.id].status == "running"

        queue._conn.execute("DROP TRIGGER fail_status_write")
        queue.complete(queued.id)
        assert leased.status == "complete"
        assert queue.jobs[queued.id].result == {"answer": 42}
    finally:
        queue.close()


def test_worker_does_not_retry_after_ambiguous_completion_acknowledgment(tmp_path, monkeypatch):
    queue = SqliteQueue(tmp_path, "tenant")
    try:
        queued = queue.enqueue("result", {})
        complete = queue.complete

        def lost_acknowledgment(job_id):
            complete(job_id)
            raise ConnectionError("completion acknowledgment lost")

        monkeypatch.setattr(queue, "complete", lost_acknowledgment)
        worker = QueueWorker(queue, {"result": lambda payload: {"answer": 42}})
        with pytest.raises(ConnectionError, match="acknowledgment lost"):
            worker.run_once()
        assert queue.jobs[queued.id].status == "complete"
        assert queue.jobs[queued.id].result == {"answer": 42}
        assert queue.lease() is None
    finally:
        queue.close()
