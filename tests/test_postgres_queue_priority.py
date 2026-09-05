"""Live queue-only PostgreSQL parity; no pgvector or memory-engine schema required."""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from mnemosyne.queue import InProcessQueue, PostgresQueue, QueueWorker


@pytest.fixture(scope="module")
def queue_dsn():
    dsn = os.environ.get("MNEMOSYNE_QUEUE_TEST_DSN")
    if not dsn:
        pytest.skip("MNEMOSYNE_QUEUE_TEST_DSN is not set")
    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    schema = "queue_review_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    scoped_dsn = make_conninfo(dsn, options=f"-c search_path={schema}")
    try:
        with psycopg.connect(scoped_dsn) as conn:
            conn.execute("CREATE TABLE tenants(id UUID PRIMARY KEY, name TEXT NOT NULL)")
            conn.execute(
                "CREATE FUNCTION mnemosyne_current_tenant() RETURNS UUID LANGUAGE SQL STABLE "
                "AS $$ SELECT nullif(current_setting('mnemosyne.tenant_id', true), '')::uuid $$"
            )
        yield scoped_dsn
    finally:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.mark.parametrize("kind_filter", [None, "work"])
@pytest.mark.parametrize(
    "first,second,expected",
    [
        ({"score": 1}, {"score": 2}, ["first", "second"]),
        ({"score": 0.5}, {"effective_score": "bad", "score": 0.9}, ["first", "second"]),
        ({"score": 0.5}, {"effective_score": None, "score": 0.9}, ["first", "second"]),
        ({"score": 0.5}, {"effective_score": -1, "score": 0.9}, ["first", "second"]),
        ({"score": 0.5}, {"effective_score": "9e-1"}, ["second", "first"]),
        ({"score": 0.5}, {"effective_score": "+.9"}, ["second", "first"]),
        ({"score": 0.5}, {"effective_score": True}, ["second", "first"]),
        ({"score": 0.5}, {"effective_score": "NaN", "score": 0.9}, ["first", "second"]),
        ({"score": 0.5}, {"effective_score": "Infinity"}, ["second", "first"]),
        ({"score": 0.5}, {"effective_score": "-Infinity"}, ["first", "second"]),
        ({"score": 0.5}, {"effective_score": "1e9999"}, ["second", "first"]),
        ({"score": 0.5}, {"effective_score": "1e-9999"}, ["first", "second"]),
        ({"score": 0.5}, {"effective_score": "1_000"}, ["second", "first"]),
        ({"score": 0.5}, {"effective_score": "0.9_0"}, ["second", "first"]),
        ({"score": 0.5}, {"effective_score": "0x10"}, ["first", "second"]),
        ({"score": 0.5}, {"effective_score": "0b11"}, ["first", "second"]),
        ({"score": 0.5}, {"effective_score": 10**400}, ["second", "first"]),
        ({"score": 0.5}, {"effective_score": -(10**400)}, ["first", "second"]),
    ],
)
def test_postgres_priority_matches_local(queue_dsn, kind_filter, first, second, expected):
    for queue in (InProcessQueue(), PostgresQueue(queue_dsn, uuid4().hex, require_safe_role=False)):
        for index, (label, priority) in enumerate((("first", first), ("second", second))):
            job = queue.enqueue("work", {"label": label, "write_priority": priority})
            created_at = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index)
            if isinstance(queue, InProcessQueue):
                job.created_at = created_at
            else:
                with queue.connect() as conn:
                    conn.execute("UPDATE runtime_jobs SET created_at = %s WHERE id = %s", (created_at, job.id))
        leased = [queue.lease(kind_filter), queue.lease(kind_filter)]
        assert [job.payload["label"] for job in leased] == expected
        assert queue.lease(kind_filter) is None


def test_postgres_lease_skips_locked_job_and_respects_kind(queue_dsn):
    queue = PostgresQueue(queue_dsn, uuid4().hex, require_safe_role=False)
    high = queue.enqueue("work", {"write_priority": {"score": 1}})
    low = queue.enqueue("work", {"write_priority": {"score": 0.2}})
    other = queue.enqueue("other", {"write_priority": {"score": 1}})
    with queue.connect() as conn:
        conn.execute("SELECT id FROM runtime_jobs WHERE id = %s FOR UPDATE", (high.id,))
        assert queue.lease("work").id == low.id
        assert queue.lease("work") is None
    assert queue.lease("work").id == high.id
    assert queue.lease().id == other.id


def test_postgres_result_serialization_failure_preserves_lease_live(queue_dsn):
    queue = PostgresQueue(queue_dsn, uuid4().hex, require_safe_role=False)
    queue.enqueue("work", {})
    leased = queue.lease()
    leased.result = object()
    with pytest.raises(TypeError):
        queue.complete(leased.id)
    assert leased.status == "running"
    assert queue.jobs[leased.id].status == "running"
    leased.result = {"answer": 42}
    queue.complete(leased.id)
    assert queue.jobs[leased.id].result == {"answer": 42}
    assert leased.status == "complete"


def test_postgres_worker_result_serialization_failure_reaches_dead_live(queue_dsn):
    queue = PostgresQueue(queue_dsn, uuid4().hex, require_safe_role=False)
    queued = queue.enqueue("work", {}, max_attempts=2)
    worker = QueueWorker(queue, {"work": lambda payload: object()})
    assert worker.run_once().status == "retry"
    assert worker.run_once().status == "dead"
    assert queue.jobs[queued.id].status == "dead"
    assert worker.run_once() is None
