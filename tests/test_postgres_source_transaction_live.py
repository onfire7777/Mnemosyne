"""Source transaction contracts, plus optional disposable-PostgreSQL coverage."""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from mnemosyne.ids import evidence_cid, evidence_unscoped_cid
from mnemosyne.models import Assertion, Evidence
from mnemosyne.postgres_engine import PostgresEngine


class _Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.connection.statements.append((" ".join(sql.split()), params))

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class _Connection:
    def __init__(self):
        self.statements = []
        self.commits = self.rollbacks = 0
        self.closed = self.fail_commit = False

    def cursor(self, **kwargs):
        return _Cursor(self)

    def commit(self):
        if self.fail_commit:
            raise OSError("injected commit failure")
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *args):
        self.commit() if exc_type is None else self.rollback()
        self.close()
        return False


@pytest.fixture(params=[True, False], ids=["pooled", "fresh"])
def fake_engine(request, monkeypatch):
    engine = PostgresEngine("postgresql://unit-test-fake", require_safe_role=False)
    engine._conn_reuse = request.param
    engine._psycopg = SimpleNamespace(rows=SimpleNamespace(dict_row=None))
    engine._jsonb = lambda value: value
    connections = []

    def create_connection():
        conn = _Connection()
        connections.append(conn)
        return conn

    monkeypatch.setattr(engine, "_new_connection", create_connection)
    monkeypatch.setattr(engine, "_ensure_evidence_vector_schema", lambda cur: None)
    monkeypatch.setattr(engine, "_ensure_evidence_document_schema", lambda cur: None)
    yield engine, connections
    engine.close_connections()


def _evidence(tenant="t", text="Growing source", segment="doc-1/segment-1", user="owner", **kwargs):
    return Evidence(tenant_id=tenant, user_id=user, actor="user", source_type="document",
                    content=text, document_segment_id=segment, **kwargs)


def test_source_operations_share_noncommitting_lease_and_lock_first(fake_engine):
    engine, connections = fake_engine
    cache = object()
    engine._passage_bm25_index = cache
    with engine.source_transaction("t"):
        conn = connections[0]
        commits = conn.commits
        cid = engine.append_evidence(_evidence())
        with engine.source_transaction("t"):
            assert engine.get_evidence("t", cid) is None
            assert engine.update_evidence_metadata("t", cid, {"revision": 2}) is False
            assert engine.forget("t", cid)["erased"] is False
        assert conn.commits == commits
        assert engine._passage_bm25_index is cache
        assert len(connections) == 1
    assert conn.commits == commits + 1
    assert engine._passage_bm25_index is None
    assert engine._source_transaction_state() is None
    statements = [sql for sql, _ in conn.statements]
    first_lock = next(i for i, sql in enumerate(statements) if "pg_advisory_xact_lock" in sql)
    first_write = next(i for i, sql in enumerate(statements) if sql.startswith("INSERT"))
    assert first_lock < first_write
    insert, params = next((sql, params) for sql, params in conn.statements if sql.startswith("INSERT INTO evidence"))
    assert "document_segment_id" in insert and "doc-1/segment-1" in params
    assert insert.count("%s") == len(params)


@pytest.mark.parametrize("failure", ["nested", "scope", "metadata", "unsupported", "mental_model"])
def test_caught_nested_failure_aborts_outer_lease(fake_engine, failure):
    engine, connections = fake_engine
    with pytest.raises(RuntimeError, match="source transaction is aborted"):
        with engine.source_transaction("t"):
            conn = connections[0]
            commits, rollbacks = conn.commits, conn.rollbacks
            engine.append_evidence(_evidence())
            with pytest.raises((ValueError, RuntimeError)):
                if failure == "nested":
                    with engine.source_transaction("t"):
                        raise ValueError("nested failure")
                elif failure == "scope":
                    engine.append_evidence(_evidence(tenant="other"))
                elif failure == "metadata":
                    engine.update_evidence_metadata("t", "ab" * 32, {"access_policy": {}})
                elif failure == "unsupported":
                    engine.ensure_tenant_and_branch("other")
                else:
                    with engine.mental_model_guard("t"):
                        pytest.fail("guard must not open")
    assert conn.commits == commits and conn.rollbacks == rollbacks + 1
    assert engine._source_transaction_state() is None
    assert len(connections) == 1


def test_source_transaction_cannot_enter_mental_model_guard(fake_engine):
    engine, connections = fake_engine
    with engine.mental_model_guard("t"):
        with pytest.raises(RuntimeError, match="cannot join a mental model guard"):
            with engine.source_transaction("t"):
                pytest.fail("source transaction must not open")
    assert len(connections) == 1


def test_source_transaction_rejects_provider_before_call(fake_engine):
    engine, _ = fake_engine
    calls = []
    engine.adapters = replace(engine.adapters, embedding=SimpleNamespace(embed=lambda text: calls.append(text)))
    with pytest.raises(ValueError, match="prepare provider output"):
        with engine.source_transaction("t"):
            engine.append_evidence(_evidence())
    assert calls == []


@pytest.mark.parametrize("controls", [{"embedding": [0.0] * 1024}, {"sensitivity": 3}])
def test_prepared_or_private_source_never_calls_provider(fake_engine, controls):
    engine, _ = fake_engine
    calls = []
    engine.adapters = replace(engine.adapters, embedding=SimpleNamespace(embed=lambda text: calls.append(text)))
    with engine.source_transaction("t"):
        engine.append_evidence(_evidence(**controls))
    assert calls == []


def test_failed_commit_preserves_cache_and_clears_transaction_state(fake_engine):
    engine, connections = fake_engine
    cache = object()
    engine._passage_bm25_index = cache
    with pytest.raises(OSError, match="commit failure"):
        with engine.source_transaction("t"):
            engine.forget("t", "ab" * 32)
            connections[0].fail_commit = True
    assert engine._passage_bm25_index is cache
    assert engine._source_transaction_state() is None


def test_source_transaction_context_is_thread_local(fake_engine):
    engine, connections = fake_engine
    barrier = threading.Barrier(2)

    def append_for(tenant):
        with engine.source_transaction(tenant):
            barrier.wait(timeout=5)
            assert engine._source_transaction_state()["tenant_id"] == tenant
            return engine.append_evidence(_evidence(tenant))

    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(append_for, "one")
        two = pool.submit(append_for, "two")
        assert one.result(timeout=10) != two.result(timeout=10)
    assert len(connections) == 2
    assert engine._source_transaction_state() is None


@pytest.mark.parametrize("stored_segment,incoming_segment,stored_owner,incoming_owner,blocks", [
    (None, "new", "one", "two", True),
    ("same", "same", "one", "one", True),
    ("same", "different", "one", "one", False),
    ("same", None, "one", "one", False),
    ("same", "same", "one", "two", False),
])
def test_tombstones_respect_legacy_and_document_identity(
    stored_segment, incoming_segment, stored_owner, incoming_owner, blocks,
):
    engine = PostgresEngine("unused")
    stored = evidence_cid("bytes", tenant_id="t", user_id=stored_owner,
                          source_type="document", content_pointer=None, modality="text",
                          sensitivity=3, document_segment_id=stored_segment)
    row = (bytes.fromhex(stored), 3, {"_external_user_id": stored_owner}, stored_segment)
    cur = SimpleNamespace(execute=lambda *args: None, fetchall=lambda: [row])
    result = engine._erased_replay_cid(
        cur, external_tenant_id="t", tenant_id="unused", branch="main", content="bytes",
        source_type="document", content_pointer=None, modality="text",
        user_id=incoming_owner, document_segment_id=incoming_segment,
    )
    assert result == (stored if blocks else None)


def test_unscoped_legacy_tombstone_still_blocks_new_document_identity():
    engine = PostgresEngine("unused")
    stored = evidence_unscoped_cid("bytes", tenant_id="t", source_type="document",
                                   content_pointer=None, modality="text")
    cur = SimpleNamespace(execute=lambda *args: None,
                          fetchall=lambda: [(bytes.fromhex(stored), 0, {}, None)])
    assert engine._erased_replay_cid(
        cur, external_tenant_id="t", tenant_id="unused", branch="main", content="bytes",
        source_type="document", content_pointer=None, modality="text", user_id="owner",
        document_segment_id="new",
    ) == stored


@pytest.fixture(params=[True, False], ids=["pooled", "fresh"])
def live_engines(request):
    pytest.importorskip("psycopg")
    dsn = os.environ.get("MNEMOSYNE_POSTGRES_DSN")
    if not dsn:
        pytest.skip("MNEMOSYNE_POSTGRES_DSN is not set")
    first, observer = PostgresEngine(dsn), PostgresEngine(dsn)
    first._conn_reuse = observer._conn_reuse = request.param
    tenant = f"source-transaction-{uuid4().hex}"
    original = first.append_evidence(_evidence(tenant, "Original source", segment="original"))
    try:
        yield first, observer, tenant, original
    finally:
        first.close_connections()
        observer.close_connections()


def test_live_composed_sources_publish_together(live_engines):
    engine, observer, tenant, original = live_engines
    with engine.source_transaction(tenant):
        appended = engine.append_evidence(_evidence(tenant, "Appended source", segment="appended"))
        assert engine.update_evidence_metadata(tenant, appended, {"revision": 2})
        assert engine.forget(tenant, original)["erased"]
        assert engine.get_evidence(tenant, original) is None
        assert engine.get_evidence(tenant, appended).metadata["revision"] == 2
        assert observer.get_evidence(tenant, original) is not None
        assert observer.get_evidence(tenant, appended) is None
    assert observer.get_evidence(tenant, original) is None
    assert observer.get_evidence(tenant, appended).metadata["revision"] == 2


@pytest.mark.parametrize("caught", [False, True])
def test_live_failure_rolls_back_source_metadata_deletion_and_audit(live_engines, caught):
    engine, observer, tenant, original = live_engines
    engine.upsert_assertion(Assertion(
        tenant_id=tenant, user_id="owner", subject="source", predicate="has",
        object="custody", source_evidence_cids=[original], status="active",
    ))
    before = observer.export_tenant(tenant)
    with pytest.raises((ValueError, RuntimeError)):
        with engine.source_transaction(tenant):
            appended = engine.append_evidence(_evidence(tenant, "Uncommitted source", segment="appended"))
            assert engine.update_evidence_metadata(tenant, original, {"revision": 99})
            assert engine.forget(tenant, original)["erased"]
            try:
                with engine.source_transaction(tenant):
                    raise ValueError("abort update")
            except ValueError:
                if not caught:
                    raise
    assert observer.get_evidence(tenant, appended) is None
    assert observer.export_tenant(tenant) == before


def test_live_sql_failure_rolls_back_and_releases_locks(live_engines, monkeypatch):
    engine, observer, tenant, original = live_engines
    before = observer.export_tenant(tenant)
    original_audit = engine._audit

    def fail_metadata_audit(cur, *args, **kwargs):
        if args[2] == "update_evidence_metadata":
            cur.execute("SELECT 1 / 0")
        original_audit(cur, *args, **kwargs)

    monkeypatch.setattr(engine, "_audit", fail_metadata_audit)
    with pytest.raises(engine._psycopg.errors.DivisionByZero):
        with engine.source_transaction(tenant):
            engine.append_evidence(_evidence(tenant, "SQL rollback", segment="new"))
            engine.update_evidence_metadata(tenant, original, {"revision": 3})
    assert observer.export_tenant(tenant) == before
    assert observer.update_evidence_metadata(tenant, original, {"after_rollback": True})


def test_live_segment_identity_survives_restart_branch_merge_and_erasure(live_engines):
    engine, observer, tenant, _ = live_engines
    first = engine.append_evidence(_evidence(tenant, segment="one"))
    second = engine.append_evidence(_evidence(tenant, segment="two"))
    assert first != second
    assert observer.get_evidence(tenant, first).document_segment_id == "one"
    engine.branch("review", tenant_id=tenant)
    third = engine.append_evidence(_evidence(tenant, segment="three"), branch="review")
    engine.merge("review", tenant_id=tenant)
    assert observer.get_evidence(tenant, first, "review").document_segment_id == "one"
    assert observer.get_evidence(tenant, third).document_segment_id == "three"
    assert engine.forget(tenant, first)["erased"]
    assert engine.append_evidence(_evidence(tenant, segment="one")) == first
    assert observer.get_evidence(tenant, first) is None
    assert observer.get_evidence(tenant, second) is not None
    other_owner = engine.append_evidence(_evidence(tenant, segment="one", user="other"))
    assert other_owner != first and observer.get_evidence(tenant, other_owner) is not None


def test_live_legacy_tombstone_blocks_replay_with_segment_identity(live_engines):
    engine, observer, tenant, _ = live_engines
    legacy = engine.append_evidence(_evidence(tenant, "Legacy erased bytes", segment=None))
    engine.forget(tenant, legacy)
    assert engine.append_evidence(_evidence(tenant, "Legacy erased bytes", segment="new")) == legacy
    assert observer.get_evidence(tenant, legacy) is None


def test_live_source_transactions_serialize_before_read_modify_write(live_engines, monkeypatch):
    first, second, tenant, original = live_engines
    second_attempted_lock = threading.Event()
    second_pid = []
    lock = second._lock_working_tenant

    def identify_then_lock(cur, tenant_id):
        cur.execute("SELECT pg_backend_pid()")
        second_pid.append(cur.fetchone()[0])
        second_attempted_lock.set()
        lock(cur, tenant_id)

    monkeypatch.setattr(second, "_lock_working_tenant", identify_then_lock)

    def second_revision():
        with second.source_transaction(tenant):
            revision = second.get_evidence(tenant, original).metadata["revision"]
            second.update_evidence_metadata(tenant, original, {"revision": revision + 1})

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = None
        with first.source_transaction(tenant):
            first.update_evidence_metadata(tenant, original, {"revision": 1})
            future = pool.submit(second_revision)
            assert second_attempted_lock.wait(5)
            deadline = time.monotonic() + 5
            # Observe actual lock contention, without assuming thread timing.
            with first._psycopg.connect(first.dsn) as observer:
                while True:
                    blocked = observer.execute(
                        "SELECT cardinality(pg_blocking_pids(%s)) > 0", (second_pid[0],),
                    ).fetchone()[0]
                    if blocked:
                        break
                    assert not future.done()
                    assert time.monotonic() < deadline, "second source transaction did not wait"
                    time.sleep(0.01)
        future.result(timeout=10)
    assert first.get_evidence(tenant, original).metadata["revision"] == 2


def test_live_failed_initial_append_rolls_back_tenant_and_branch(live_engines):
    engine, observer, _, _ = live_engines
    tenant = f"rollback-initial-source-{uuid4().hex}"
    with pytest.raises(ValueError, match="abort initial append"):
        with engine.source_transaction(tenant, "draft"):
            engine.append_evidence(_evidence(tenant), branch="draft")
            raise ValueError("abort initial append")
    with observer.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM tenants WHERE name = %s", (tenant,))
            assert cur.fetchone() is None
