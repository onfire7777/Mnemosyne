"""Publication transaction/SQL contracts against fakes; no live PostgreSQL."""

from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any

import pytest

from mnemosyne.mental_model_storage import MentalModelConflict
from mnemosyne.postgres_engine import PostgresEngine, _stable_uuid


def _record() -> dict[str, Any]:
    return {"tenant_id": "t", "branch": "main", "model_id": "m", "owner_id": "u",
            "name": "Launch", "question": "When is launch?", "scope": {},
            "created_at": "2026-10-22T00:00:00+00:00", "updated_at": "2026-10-22T00:00:00+00:00",
            "status": "pending", "answer": None, "corpus_fingerprint": None,
            "source_evidence_cids": [], "revisions": [], "version": 1}


class Cursor:
    def __init__(self, conn):
        self.conn = conn
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        sql = " ".join(sql.split())
        if sql.startswith("SET TRANSACTION") and self.conn.transaction_started:
            raise RuntimeError("isolation change after first query")
        self.conn.statements.append((sql, params))
        if sql.startswith("SELECT"):
            self.conn.transaction_started = True
        self.rows = []
        if sql.startswith("LOCK TABLE") and self.conn.lock_error:
            raise RuntimeError("lock timeout")
        if sql.startswith("SELECT record FROM mental_models"):
            self.rows = [{"record": copy.deepcopy(self.conn.model)}] if self.conn.model else []
        elif sql.startswith("SELECT version FROM mental_models"):
            self.rows = [{"version": self.conn.model["version"]}] if self.conn.model else []
        elif sql.startswith("UPDATE mental_models"):
            self.conn.model = copy.deepcopy(params[1])
            self.rows = [{"version": self.conn.model["version"]}]
        elif sql.startswith("DELETE FROM mental_models"):
            self.conn.model = None

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self):
        self.statements = []
        self.commits = self.rollbacks = 0
        self.closed = self.lock_error = False
        self.transaction_started = False
        self.model = _record()
        self.committed = copy.deepcopy(self.model)

    def cursor(self, **kwargs):
        return Cursor(self)

    def commit(self):
        self.commits += 1
        self.transaction_started = False
        self.committed = copy.deepcopy(self.model)

    def rollback(self):
        self.rollbacks += 1
        self.transaction_started = False
        self.model = copy.deepcopy(self.committed)

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *args):
        self.commit() if exc_type is None else self.rollback()
        self.close()
        return False


@pytest.fixture(params=[True, False], ids=["pooled", "fresh"])
def backend(request):
    engine = PostgresEngine("postgresql://unit-test-fake", require_safe_role=False)
    engine._conn_reuse = request.param
    engine._psycopg = SimpleNamespace(rows=SimpleNamespace(dict_row=None))
    engine._jsonb = lambda value: value
    connections = []

    def connect():
        connection = Connection()
        connections.append(connection)
        return connection

    engine._new_connection = connect
    yield engine, connections
    engine.close_connections()


def test_final_reads_and_model_cas_use_one_source_locked_transaction(backend):
    engine, connections = backend
    with engine.mental_model_guard("t"):
        conn = connections[0]
        commits = conn.commits
        model = engine.get_mental_model_record("t", "m")
        assert engine.get_evidence("t", "ab" * 32) is None
        assert engine.export_tenant_filtered("t", {"tenant_id": "t", "user_id": "u"})["evidence"] == []
        updated = engine.save_mental_model_record("t", "m", model, expected_version=1)
        assert updated["version"] == 2
        assert engine.get_mental_model_record("t", "m") == updated
        assert engine.list_mental_model_records("t") == [updated]
        engine.export_tenant("t")
        assert len(connections) == 1 and conn.commits == commits
        statements = [sql for sql, _ in conn.statements]
        lock = "LOCK TABLE tenants, branches, evidence, assertions, relations, preferences IN SHARE MODE"
        assert statements.count(lock) == 1
        first_select = next(i for i, sql in enumerate(statements) if sql.startswith("SELECT record"))
        assert statements.index("SET TRANSACTION ISOLATION LEVEL READ COMMITTED") < statements.index(lock) < first_select
        assert "SET LOCAL lock_timeout = '5s'" in statements
        assert not any(sql.startswith(("ALTER TABLE", "CREATE", "INSERT INTO tenants", "INSERT INTO branches")) for sql in statements)
        bindings = [params for sql, params in conn.statements if "set_config('mnemosyne.tenant_id', %s, true)" in sql]
        assert bindings and all(params == (str(_stable_uuid("tenant", "t")),) for params in bindings)
    assert conn.commits == commits + 1
    assert conn.committed["version"] == 2
    assert engine._active_mental_model_connection("t") is None


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_final_validation_error_rolls_back_write_and_clears_pin(backend, operation):
    engine, connections = backend
    with pytest.raises(RuntimeError, match="source invalid"):
        with engine.mental_model_guard("t"):
            if operation == "update":
                engine.save_mental_model_record("t", "m", _record(), expected_version=1)
            else:
                assert engine.delete_mental_model_record("t", "m", expected_version=1)
            raise RuntimeError("source invalid")
    assert connections[0].committed == _record()
    assert connections[0].model == _record()
    assert connections[0].rollbacks == 2  # clean leased transaction, then failed publication
    assert engine._active_mental_model_connection("t") is None


def test_conflict_rolls_back_outer_transaction(backend):
    engine, connections = backend
    with pytest.raises(MentalModelConflict):
        with engine.mental_model_guard("t"):
            engine.save_mental_model_record("t", "m", _record(), expected_version=2)
    assert connections[0].rollbacks == 2
    assert not any(sql.startswith("UPDATE mental_models") for sql, _ in connections[0].statements)


def test_nested_same_tenant_guard_never_commits_inner_scope(backend):
    engine, connections = backend
    with engine.mental_model_guard("t"):
        commits = connections[0].commits
        with engine.mental_model_guard("t"):
            assert engine.get_mental_model_record("t", "m")["version"] == 1
        assert connections[0].commits == commits
        assert len(connections) == 1


def test_cross_tenant_calls_rejected_before_query(backend):
    engine, connections = backend
    with engine.mental_model_guard("t"):
        count = len(connections[0].statements)
        for call in (lambda: engine.get_mental_model_record("other", "m"),
                     lambda: engine.get_evidence("other", "ab" * 32),
                     lambda: engine.export_tenant("other")):
            with pytest.raises(ValueError, match="tenant scope"):
                call()
        with pytest.raises(ValueError, match="tenant scope"):
            with engine.mental_model_guard("other"):
                pytest.fail("cross-tenant guard entered")
        assert len(connections[0].statements) == count


def test_connection_pin_is_not_shared_with_another_thread(backend):
    engine, connections = backend
    with engine.mental_model_guard("t"):
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(engine._active_mental_model_connection, "other").result() is None
            assert pool.submit(engine.get_mental_model_record, "other", "m").result()["version"] == 1
        assert len(connections) == 2


def test_lock_failure_does_not_enter_body_or_leave_pinned_connection(backend):
    engine, connections = backend
    original = engine._new_connection

    def locked():
        conn = original()
        conn.lock_error = True
        return conn

    engine._new_connection = locked
    with pytest.raises(RuntimeError, match="lock timeout"):
        with engine.mental_model_guard("t"):
            pytest.fail("body entered without source locks")
    assert connections[0].rollbacks == 2
    assert engine._active_mental_model_connection("t") is None


def test_startup_safe_role_probe_does_not_pin_old_snapshot(backend):
    engine, connections = backend
    original = engine._new_connection

    def checked():
        conn = original()
        conn.transaction_started = True  # The fresh-connection role probe queried pg_roles.
        return conn

    engine._new_connection = checked
    with engine.mental_model_guard("t"):
        assert engine.get_mental_model_record("t", "m")["version"] == 1
    assert connections[0].rollbacks >= 1
