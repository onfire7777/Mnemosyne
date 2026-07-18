from __future__ import annotations

import os
import types
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from mnemosyne.models import Evidence
from mnemosyne.postgres_engine import (
    PostgresEngine,
    PostgresUnavailableError,
    WorkingMemoryItem,
    _stable_uuid,
    _working_payload,
)


CREATED_AT = datetime(2026, 7, 18, 8, 0, tzinfo=UTC)


def _item(**overrides: object) -> WorkingMemoryItem:
    values: dict[str, object] = {
        "item_id": "working-1",
        "tenant_id": "tenant-a",
        "session_id": "session-a",
        "user_id": "user-a",
        "agent_id": "agent-a",
        "kind": "active_goal",
        "task_id": "task-a",
        "content": "transient task state",
        "created_at": CREATED_AT,
        "expires_at": CREATED_AT + timedelta(minutes=5),
        "evidence_ids": ["00" * 32],
    }
    values.update(overrides)
    return WorkingMemoryItem(**values)


class _RecordingCursor:
    def __init__(self, connection: "_RecordingConnection") -> None:
        self.connection = connection

    def __enter__(self) -> "_RecordingCursor":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def execute(self, sql: str, _params: object = None, **_kwargs: object) -> None:
        normalized = " ".join(sql.split())
        self.connection.statements.append(normalized)
        if normalized.startswith("INSERT INTO working_memory"):
            self.connection.pending_rows += 1


class _RecordingConnection:
    def __init__(self) -> None:
        self.pending_rows = 0
        self.persisted_rows = 0
        self.commits = 0
        self.rollbacks = 0
        self.statements: list[str] = []

    def __enter__(self) -> "_RecordingConnection":
        return self

    def __exit__(self, exc_type: object, _exc: object, _tb: object) -> bool:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False

    def cursor(self, **_kwargs: object) -> _RecordingCursor:
        return _RecordingCursor(self)

    def commit(self) -> None:
        self.persisted_rows += self.pending_rows
        self.pending_rows = 0
        self.commits += 1

    def rollback(self) -> None:
        self.pending_rows = 0
        self.rollbacks += 1


def _live_engine() -> PostgresEngine:
    pytest.importorskip("psycopg", reason="psycopg is required for live PostgreSQL coverage")
    dsn = os.environ.get("MNEMOSYNE_POSTGRES_DSN")
    if not dsn:
        pytest.skip("MNEMOSYNE_POSTGRES_DSN is not set")
    return PostgresEngine(dsn)


def _live_evidence(
    engine: PostgresEngine,
    *,
    tenant_id: str,
    session_id: str,
    user_id: str,
    marker: str,
    created_at: datetime,
    trust_tier: int = 0,
    capability_tags: list[str] | None = None,
    sensitivity: int = 0,
) -> str:
    return engine.append_evidence(
        Evidence(
            tenant_id=tenant_id,
            user_id=user_id,
            actor="user",
            source_type="working-memory-test",
            content=f"originating evidence {marker}",
            session_id=session_id,
            created_at=created_at,
            trust_tier=trust_tier,
            capability_tags=capability_tags or [],
            sensitivity=sensitivity,
            access_policy={"tenant": tenant_id},
        )
    )


def _live_item(
    engine: PostgresEngine,
    *,
    tenant_id: str,
    session_id: str,
    user_id: str,
    item_id: str,
    created_at: datetime,
    expires_at: datetime,
    marker: str | None = None,
    evidence_id: str | None = None,
    trust_tier: int = 0,
    capability_tags: list[str] | None = None,
    sensitivity: int = 0,
) -> WorkingMemoryItem:
    evidence_id = evidence_id or _live_evidence(
        engine,
        tenant_id=tenant_id,
        session_id=session_id,
        user_id=user_id,
        marker=marker or item_id,
        created_at=created_at,
        trust_tier=trust_tier,
        capability_tags=capability_tags,
        sensitivity=sensitivity,
    )
    return _item(
        item_id=item_id,
        tenant_id=tenant_id,
        session_id=session_id,
        user_id=user_id,
        task_id=f"task-{item_id}",
        content=f"working content {item_id}",
        created_at=created_at,
        expires_at=expires_at,
        evidence_ids=[evidence_id],
        trust_tier=0,
        capability_tags=["Caller-Tag"],
        sensitivity=0,
        metadata={"marker": marker or item_id, "nested": ["original"]},
    )


def test_working_payload_canonicalizes_utc_and_preserves_security_fields() -> None:
    item = _item(
        created_at=datetime(2026, 7, 18, 1, 0, tzinfo=UTC),
        expires_at=datetime(2026, 7, 18, 1, 5, tzinfo=UTC),
        capability_tags=["Data-Only"],
        metadata={"nested": ["value"]},
    )

    values = _working_payload(item)

    assert values["created_at"].tzinfo is UTC
    assert values["expires_at"].tzinfo is UTC
    assert values["capability_tags"] == ["Data-Only"]
    assert values["metadata"] == {"nested": ["value"]}


@pytest.mark.parametrize(
    "overrides",
    [
        {"created_at": datetime(2026, 7, 18, 8, 0), "expires_at": CREATED_AT + timedelta(minutes=5)},
        {"expires_at": CREATED_AT + timedelta(hours=24, seconds=1)},
    ],
)
def test_working_payload_rejects_unsafe_ttl_boundaries(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _working_payload(_item(**overrides))


def test_schema_declares_working_memory_identity_indexes_rls_and_audit_idempotency() -> None:
    schema = Path(__file__).parents[1].joinpath("sql", "schema.sql").read_text()

    assert "PRIMARY KEY (tenant_id, session_id, item_id)" in schema
    assert "CREATE INDEX IF NOT EXISTS working_memory_scope_created_idx" in schema
    assert "CREATE INDEX IF NOT EXISTS working_memory_expiry_idx" in schema
    assert "ALTER TABLE working_memory FORCE ROW LEVEL SECURITY" in schema
    assert "CREATE POLICY working_memory_tenant_isolation" in schema
    assert "audit_log_tenant_event_unique" in schema


def test_postgres_unavailable_does_not_fall_back_to_local(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = PostgresEngine("postgresql://unavailable/mnemosyne", require_safe_role=False)
    monkeypatch.setattr(engine, "ensure_tenant_and_branch", lambda *_args, **_kwargs: None)

    def unavailable() -> object:
        raise PostgresUnavailableError("postgres unavailable")

    monkeypatch.setattr(engine, "connect", unavailable)

    with pytest.raises(PostgresUnavailableError, match="postgres unavailable"):
        engine.put_working(_item())
    assert not hasattr(engine, "working_memory")


@pytest.mark.parametrize("operation", ["get", "list", "expire"])
def test_postgres_unavailable_operations_fail_closed_without_local_fallback(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    engine = PostgresEngine("postgresql://unavailable/mnemosyne", require_safe_role=False)

    def unavailable() -> object:
        raise PostgresUnavailableError("postgres unavailable")

    monkeypatch.setattr(engine, "connect", unavailable)

    def call() -> object:
        if operation == "get":
            return engine.get_working("tenant-a", "session-a", "working-1", as_of=CREATED_AT)
        if operation == "list":
            return engine.list_working("tenant-a", "session-a", as_of=CREATED_AT)
        return engine.expire_working("tenant-a", expired_at=CREATED_AT)

    with pytest.raises(PostgresUnavailableError, match="postgres unavailable"):
        call()
    assert not hasattr(engine, "working_memory")


def test_postgres_put_rolls_back_working_mutation_when_audit_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = PostgresEngine("postgresql://unit-test-fake", require_safe_role=False)
    connection = _RecordingConnection()
    engine._psycopg = types.SimpleNamespace(rows=types.SimpleNamespace(dict_row=object()))
    engine._jsonb = lambda value: value
    monkeypatch.setattr(engine, "connect", lambda: connection)
    monkeypatch.setattr(engine, "ensure_tenant_and_branch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        engine,
        "_working_provenance",
        lambda _cur, values: (values["trust_tier"], values["capability_tags"], values["sensitivity"], values["access_policy"]),
    )

    def fail_audit(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(engine, "_audit", fail_audit)

    with pytest.raises(RuntimeError, match="audit write failed"):
        engine.put_working(_item())

    assert connection.persisted_rows == 0
    assert connection.pending_rows == 0
    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert any(statement.startswith("INSERT INTO working_memory") for statement in connection.statements)
    assert not any(statement.startswith("INSERT INTO audit_log") for statement in connection.statements)


def test_postgres_working_memory_live_round_trip_boundaries_isolation_and_ordering() -> None:
    engine = _live_engine()
    tenant = f"working-roundtrip-{uuid4()}"
    user = f"user-{uuid4()}"
    session = f"session-{uuid4()}"
    other_session = f"session-other-{uuid4()}"
    now = datetime.now(UTC)
    created_at = now - timedelta(minutes=2)
    expires_at = now + timedelta(minutes=10)
    evidence_id = _live_evidence(
        engine,
        tenant_id=tenant,
        session_id=session,
        user_id=user,
        marker="shared-source",
        created_at=created_at,
        trust_tier=1,
        capability_tags=["Source-Tag"],
        sensitivity=2,
    )
    first = _live_item(
        engine,
        tenant_id=tenant,
        session_id=session,
        user_id=user,
        item_id="working-z",
        created_at=created_at,
        expires_at=expires_at,
        evidence_id=evidence_id,
        marker="first",
    )
    second = _live_item(
        engine,
        tenant_id=tenant,
        session_id=session,
        user_id=user,
        item_id="working-a",
        created_at=created_at,
        expires_at=expires_at,
        evidence_id=evidence_id,
        marker="second",
    )
    engine.put_working(first)
    engine.put_working(second)

    other = _live_item(
        engine,
        tenant_id=tenant,
        session_id=other_session,
        user_id=user,
        item_id="working-other-session",
        created_at=created_at,
        expires_at=expires_at,
        marker="other-session",
    )
    engine.put_working(other)

    assert first.trust_tier == 1
    assert first.capability_tags == ["caller-tag", "source-tag"]
    assert first.sensitivity == 2
    listed = engine.list_working(tenant, session, as_of=now)
    assert [item.item_id for item in listed] == ["working-a", "working-z"]
    assert listed[0] is not first
    listed[0].metadata["nested"].append("caller-mutation")
    first.content = "caller mutation must not rewrite PostgreSQL"

    fetched = engine.get_working(tenant, session, first.item_id, as_of=first.created_at)
    assert fetched is not None
    assert fetched.content == "working content working-z"
    assert fetched.metadata == {"marker": "first", "nested": ["original"]}
    assert fetched.created_at.tzinfo is UTC
    assert fetched.expires_at.tzinfo is UTC
    assert engine.get_working(tenant, session, first.item_id, as_of=first.expires_at) is None
    assert engine.list_working(tenant, other_session, as_of=now)[0].item_id == "working-other-session"
    assert engine.list_working(f"tenant-missing-{uuid4()}", session, as_of=now) == []


def test_postgres_working_memory_duplicate_item_ids_are_session_scoped() -> None:
    engine = _live_engine()
    tenant = f"working-identity-{uuid4()}"
    user = f"user-{uuid4()}"
    session_a = f"session-a-{uuid4()}"
    session_b = f"session-b-{uuid4()}"
    now = datetime.now(UTC)
    created_at = now - timedelta(minutes=1)
    expires_at = now + timedelta(minutes=10)
    item_a = _live_item(
        engine,
        tenant_id=tenant,
        session_id=session_a,
        user_id=user,
        item_id="same-item-id",
        created_at=created_at,
        expires_at=expires_at,
    )
    item_b = _live_item(
        engine,
        tenant_id=tenant,
        session_id=session_b,
        user_id=user,
        item_id="same-item-id",
        created_at=created_at,
        expires_at=expires_at,
    )
    engine.put_working(item_a)
    engine.put_working(item_b)

    duplicate = _live_item(
        engine,
        tenant_id=tenant,
        session_id=session_a,
        user_id=user,
        item_id="same-item-id",
        created_at=created_at,
        expires_at=expires_at,
        marker="duplicate",
    )
    with pytest.raises(ValueError, match="already exists"):
        engine.put_working(duplicate)

    assert engine.get_working(tenant, session_a, "same-item-id", as_of=now) is not None
    assert engine.get_working(tenant, session_b, "same-item-id", as_of=now) is not None
    with engine.connect() as conn:
        with conn.cursor() as cur:
            engine._set_tenant(cur, _stable_uuid("tenant", tenant))
            cur.execute(
                "SELECT count(*) FROM audit_log WHERE op = 'put_working' AND diff->>'item_id' = %s",
                ("same-item-id",),
            )
            assert cur.fetchone() == (2,)


def test_postgres_working_memory_rls_blocks_direct_cross_tenant_dml() -> None:
    engine = _live_engine()
    tenant_a = f"working-rls-a-{uuid4()}"
    tenant_b = f"working-rls-b-{uuid4()}"
    user = f"user-{uuid4()}"
    session = f"session-{uuid4()}"
    now = datetime.now(UTC)
    item = _live_item(
        engine,
        tenant_id=tenant_a,
        session_id=session,
        user_id=user,
        item_id="rls-direct-dml",
        created_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=10),
    )
    engine.put_working(item)
    db_tenant_a = _stable_uuid("tenant", tenant_a)
    db_tenant_b = _stable_uuid("tenant", tenant_b)
    db_session = _stable_uuid("session", session)
    db_user = _stable_uuid("user", user)

    with engine.connect() as conn:
        with conn.cursor() as cur:
            engine._set_tenant(cur, db_tenant_b)
            cur.execute(
                "SELECT count(*) FROM working_memory WHERE tenant_id = %s AND item_id = %s",
                (db_tenant_a, item.item_id),
            )
            assert cur.fetchone() == (0,)
            cur.execute(
                "UPDATE working_memory SET content = %s WHERE tenant_id = %s AND item_id = %s",
                ("cross-tenant tamper", db_tenant_a, item.item_id),
            )
            assert cur.rowcount == 0
            cur.execute(
                "DELETE FROM working_memory WHERE tenant_id = %s AND item_id = %s",
                (db_tenant_a, item.item_id),
            )
            assert cur.rowcount == 0
            with pytest.raises(Exception) as exc_info:
                cur.execute(
                    """
                    INSERT INTO working_memory(
                      tenant_id, session_id, external_session_id, item_id,
                      user_id, external_user_id, agent_id, kind, task_id, content,
                      created_at, expires_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        db_tenant_a,
                        db_session,
                        session,
                        "rls-cross-tenant-insert",
                        db_user,
                        user,
                        "agent-a",
                        "active_goal",
                        "task-a",
                        "cross-tenant insert",
                        now,
                        now + timedelta(minutes=5),
                    ),
                )
            assert getattr(exc_info.value, "sqlstate", None) == "42501"


def test_postgres_working_memory_put_and_expiry_roll_back_with_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _live_engine()
    tenant = f"working-rollback-{uuid4()}"
    user = f"user-{uuid4()}"
    session = f"session-{uuid4()}"
    now = datetime.now(UTC)
    source_created_at = now - timedelta(minutes=10)
    source_id = _live_evidence(
        engine,
        tenant_id=tenant,
        session_id=session,
        user_id=user,
        marker="rollback-source",
        created_at=source_created_at,
    )
    put_item = _item(
        item_id="rollback-put",
        tenant_id=tenant,
        session_id=session,
        user_id=user,
        created_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=10),
        evidence_ids=[source_id],
    )

    def fail_audit(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(engine, "_audit", fail_audit)
    with pytest.raises(RuntimeError, match="audit write failed"):
        engine.put_working(put_item)
    assert engine.get_working(tenant, session, put_item.item_id, as_of=now) is None

    expired = _live_item(
        engine,
        tenant_id=tenant,
        session_id=session,
        user_id=user,
        item_id="rollback-expiry",
        created_at=source_created_at,
        expires_at=now - timedelta(minutes=5),
        evidence_id=source_id,
    )
    monkeypatch.undo()
    engine.put_working(expired)
    monkeypatch.setattr(engine, "_audit", fail_audit)
    with pytest.raises(RuntimeError, match="audit write failed"):
        engine.expire_working(tenant, expired_at=now)

    still_active = engine.get_working(tenant, session, expired.item_id, as_of=expired.expires_at - timedelta(microseconds=1))
    assert still_active is not None
    with engine.connect() as conn:
        with conn.cursor() as cur:
            engine._set_tenant(cur, _stable_uuid("tenant", tenant))
            cur.execute(
                "SELECT status, count(*) FROM working_memory WHERE item_id = %s GROUP BY status",
                (expired.item_id,),
            )
            assert cur.fetchone() == ("active", 1)


def test_postgres_working_memory_expiry_is_exactly_once_under_concurrency() -> None:
    engine = _live_engine()
    dsn = os.environ["MNEMOSYNE_POSTGRES_DSN"]
    tenant = f"working-expiry-race-{uuid4()}"
    user = f"user-{uuid4()}"
    now = datetime.now(UTC)
    expired_at = now - timedelta(minutes=5)
    items = [
        _live_item(
            engine,
            tenant_id=tenant,
            session_id=f"session-{index}",
            user_id=user,
            item_id=f"expiry-{index}",
            created_at=now - timedelta(minutes=10),
            expires_at=expired_at,
        )
        for index in range(6)
    ]
    for item in items:
        engine.put_working(item)

    def sweep() -> list[WorkingMemoryItem]:
        return PostgresEngine(dsn).expire_working(tenant, expired_at=now)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _index: sweep(), range(4)))
    expired_items = [item for result in results for item in result]
    expected_ids = {item.item_id for item in items}
    observed_ids = [item.item_id for item in expired_items]
    assert set(observed_ids) == expected_ids
    assert len(observed_ids) == len(set(observed_ids)) == len(expected_ids)

    with engine.connect() as conn:
        with conn.cursor() as cur:
            engine._set_tenant(cur, _stable_uuid("tenant", tenant))
            cur.execute("SELECT count(*) FROM working_memory WHERE status = 'expired'")
            assert cur.fetchone() == (len(expected_ids),)
            cur.execute("SELECT count(*) FROM audit_log WHERE op = 'expire_working'")
            assert cur.fetchone() == (len(expected_ids),)


def test_postgres_pool_clears_tenant_after_aborted_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _live_engine()
    tenant = f"working-pool-reset-{uuid4()}"
    user = f"user-{uuid4()}"
    session = f"session-{uuid4()}"
    now = datetime.now(UTC)
    item = _live_item(
        engine,
        tenant_id=tenant,
        session_id=session,
        user_id=user,
        item_id="pool-reset",
        created_at=now - timedelta(minutes=10),
        expires_at=now - timedelta(minutes=5),
    )
    engine.put_working(item)

    def fail_audit(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(engine, "_audit", fail_audit)
    with pytest.raises(RuntimeError, match="audit write failed"):
        engine.expire_working(tenant, expired_at=now)

    with engine.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_setting('mnemosyne.tenant_id', true)")
            assert cur.fetchone() == ("",)
