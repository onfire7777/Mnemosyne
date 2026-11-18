"""Live transaction-lifetime regressions for tenant source/publication guards.

Only participating engine writes are serialized; arbitrary SQL is not covered.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
from threading import Event
import time
from uuid import uuid4

import pytest

from mnemosyne.models import Assertion, Evidence, Preference, Relation
from mnemosyne.postgres_engine import PostgresEngine


@pytest.fixture(params=[True, False], ids=["pooled", "fresh"])
def engines(request):
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ.get("MNEMOSYNE_POSTGRES_DSN")
    if not dsn:
        pytest.skip("MNEMOSYNE_POSTGRES_DSN is not set")
    publisher, writer, unrelated = [PostgresEngine(dsn) for _ in range(3)]
    for engine in (publisher, writer, unrelated):
        engine._conn_reuse = request.param
    tenant = f"publication-lifetime-{uuid4().hex}"
    publisher.ensure_tenant_and_branch(tenant)
    unrelated.ensure_tenant_and_branch(tenant + "-other")
    try:
        with psycopg.connect(dsn, autocommit=True) as observer:
            yield publisher, writer, unrelated, tenant, observer
    finally:
        for engine in (publisher, writer, unrelated):
            engine.close_connections()


def _evidence(tenant):
    return Evidence(
        tenant_id=tenant, user_id="owner", actor="user", source_type="chat",
        content="Synthetic publication-lock lifetime source.",
        access_policy={"tenant": tenant},
    )


def _pid(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT pg_backend_pid()")
        return cur.fetchone()[0]


def _write_source(engine, tenant, collection):
    if collection == "evidence":
        return engine.append_evidence(_evidence(tenant))
    if collection == "assertions":
        return engine.upsert_assertion(Assertion(
            tenant_id=tenant, user_id="owner", subject="Launch", predicate="uses",
            object="a source guard", access_policy={"tenant": tenant},
        ))
    if collection == "relations":
        return engine.add_relation(Relation(
            tenant_id=tenant, source="Launch", predicate="uses", target="a source guard",
            access_policy={"tenant": tenant},
        ))
    assert collection == "preferences"
    return engine.add_preference(Preference(
        tenant_id=tenant, user_id="owner", category="workflow", statement="Use source guards.",
        access_policy={"tenant": tenant},
    ))


def _capture_connections(monkeypatch, engine, pids):
    connect = engine.connect

    @contextmanager
    def connect_with_pid():
        with connect() as conn:
            pids.append(_pid(conn))
            yield conn

    monkeypatch.setattr(engine, "connect", connect_with_pid)


def _wait_for_advisory_block(observer, pids, blocker, future):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        if pids and observer.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid = %s "
            "AND locktype = 'advisory' AND NOT granted) "
            "AND %s = ANY(pg_blocking_pids(%s))",
            (pids[-1], blocker, pids[-1]),
        ).fetchone()[0]:
            assert not future.done()
            return
        if future.done():
            future.result()  # Report a writer exception rather than misdiagnosing it.
            pytest.fail("source mutation committed while publication guard was held")
        time.sleep(0.01)
    pytest.fail("expected transaction did not wait on the publication advisory lock")


@pytest.mark.parametrize("collection", ["evidence", "assertions", "relations", "preferences"])
def test_live_source_reacquires_guard_after_setup_commit(engines, monkeypatch, collection):
    publisher, writer, unrelated, tenant, observer = engines
    setup_done, resume = Event(), Event()
    ensure = writer.ensure_tenant_and_branch
    pids = []
    _capture_connections(monkeypatch, writer, pids)

    def pause_after_setup(*args, **kwargs):
        ensure(*args, **kwargs)
        setup_done.set()
        assert resume.wait(10), "append was not resumed after tenant setup"

    monkeypatch.setattr(writer, "ensure_tenant_and_branch", pause_after_setup)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_write_source, writer, tenant, collection)
        try:
            assert setup_done.wait(5)
            with publisher.mental_model_guard(tenant):
                blocker = _pid(publisher._active_mental_model_connection(tenant))
                before = publisher.mental_model_source_revision(tenant)
                assert before == 0
                pids.clear()  # Observe the insertion lease, not the committed setup.
                resume.set()
                _wait_for_advisory_block(observer, pids, blocker, future)
                other_id = _write_source(unrelated, tenant + "-other", collection)
                key = "cid" if collection == "evidence" else "id"
                assert other_id in {
                    row[key] for row in unrelated.export_tenant(tenant + "-other")[collection]
                }
                assert publisher.mental_model_source_revision(tenant) == before
                assert publisher.export_tenant(tenant)[collection] == []
            source_id = future.result(timeout=10)
            assert source_id in {row[key] for row in publisher.export_tenant(tenant)[collection]}
            assert publisher.mental_model_source_revision(tenant) == before + 1
        finally:
            resume.set()
