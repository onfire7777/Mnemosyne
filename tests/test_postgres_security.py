from __future__ import annotations

import pytest

import mnemosyne.mcp_server as mcp_server
from mnemosyne.postgres_engine import PostgresEngine
from mnemosyne.mcp_server import MnemosyneMcpServer
from mnemosyne.postgres_security import (
    assert_postgres_safe_role,
    inspect_postgres_role,
    postgres_safe_role_required,
)


class FakeCursor:
    def __init__(self, row: tuple[str, bool, bool] | None):
        self.row = row
        self.sql: str | None = None

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def execute(self, sql: str) -> None:
        self.sql = sql

    def fetchone(self) -> tuple[str, bool, bool] | None:
        return self.row


class FakeConnection:
    def __init__(self, row: tuple[str, bool, bool] | None):
        self.row = row
        self.cursor_calls = 0

    def cursor(self) -> FakeCursor:
        self.cursor_calls += 1
        return FakeCursor(self.row)


class FakePsycopg:
    def __init__(self, conn: FakeConnection):
        self.conn = conn
        self.dsn: str | None = None

    def connect(self, dsn: str) -> FakeConnection:
        self.dsn = dsn
        return self.conn


def test_postgres_safe_role_required_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MNEMOSYNE_POSTGRES_REQUIRE_SAFE_ROLE", raising=False)
    assert postgres_safe_role_required() is False

    monkeypatch.setenv("MNEMOSYNE_POSTGRES_REQUIRE_SAFE_ROLE", "1")
    assert postgres_safe_role_required() is True

    monkeypatch.setenv("MNEMOSYNE_POSTGRES_REQUIRE_SAFE_ROLE", "false")
    assert postgres_safe_role_required() is False


def test_inspect_postgres_role_reports_current_privileges() -> None:
    conn = FakeConnection(("mnemosyne_app", False, False))

    report = inspect_postgres_role(conn)

    assert report.current_user == "mnemosyne_app"
    assert report.rolsuper is False
    assert report.rolbypassrls is False
    assert conn.cursor_calls == 1


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (("postgres", True, False), "rolsuper=True"),
        (("mnemosyne_owner", False, True), "rolbypassrls=True"),
    ],
)
def test_assert_postgres_safe_role_refuses_privileged_roles(
    row: tuple[str, bool, bool],
    expected: str,
) -> None:
    conn = FakeConnection(row)

    with pytest.raises(RuntimeError, match=expected):
        assert_postgres_safe_role(conn, surface="test-surface")


def test_assert_postgres_safe_role_refuses_missing_role_row() -> None:
    conn = FakeConnection(None)

    with pytest.raises(RuntimeError, match="current_user is absent"):
        assert_postgres_safe_role(conn)


def test_postgres_engine_connect_runs_safe_role_guard() -> None:
    conn = FakeConnection(("postgres", True, False))
    engine = PostgresEngine("postgresql://unused", require_safe_role=True)
    engine._psycopg = FakePsycopg(conn)
    engine._jsonb = object()

    with pytest.raises(RuntimeError, match="PostgresEngine production role"):
        engine.connect()


def test_mcp_production_profile_passes_safe_role_to_postgres_surfaces(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []

    class FakePostgresEngine:
        def __init__(self, dsn: str, **kwargs: object):
            calls.append(("engine", dsn, dict(kwargs)))

    class FakePostgresRuntimeState:
        def __init__(self, dsn: str, **kwargs: object):
            calls.append(("runtime", dsn, dict(kwargs)))

    class FakePostgresQueue:
        def __init__(self, dsn: str, **kwargs: object):
            calls.append(("queue", dsn, dict(kwargs)))

    class FakeMemoryTools:
        def __init__(self, *args: object, **kwargs: object):
            self.args = args
            self.kwargs = kwargs

    import mnemosyne.postgres_engine as postgres_engine_module

    monkeypatch.setattr(postgres_engine_module, "PostgresEngine", FakePostgresEngine)
    monkeypatch.setattr(mcp_server, "PostgresRuntimeState", FakePostgresRuntimeState)
    monkeypatch.setattr(mcp_server, "PostgresQueue", FakePostgresQueue)
    monkeypatch.setattr(mcp_server, "MemoryTools", FakeMemoryTools)

    server = MnemosyneMcpServer(
        store_path=tmp_path / "store.json",
        backend="postgres",
        queue_backend="postgres",
        postgres_dsn="postgresql://mnemosyne_app@example.test/mnemosyne",
        production_profile=True,
        require_session=True,
        session_secret="mnemosyne-mcp-session-secret",
        object_store=tmp_path / "objects",
        object_store_encryption="aesgcm",
        object_key_provider="command",
        object_key_command="/usr/bin/true",
        queue_tenant="tenant-a",
    )

    assert server.production_profile is True
    assert [(name, kwargs["require_safe_role"]) for name, _, kwargs in calls] == [
        ("engine", True),
        ("runtime", True),
        ("queue", True),
    ]
    assert calls[1][2]["tenant_id"] == "tenant-a"
    assert calls[2][2]["tenant_id"] == "tenant-a"
