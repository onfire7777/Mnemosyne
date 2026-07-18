from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import sqlite3

import pytest

from mnemosyne.models import Evidence
from mnemosyne.sqlite_engine import SqliteEngine, _SQLiteWorkingMemoryItem


CREATED_AT = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
EXPIRES_AT = CREATED_AT + timedelta(seconds=30)
TENANT = "tenant-working"
USER = "user-working"
SESSION = "session-working"
AGENT = "agent-working"


def _evidence(engine: SqliteEngine, *, tenant_id: str = TENANT, session_id: str = SESSION) -> str:
    return engine.append_evidence(
        Evidence(
            tenant_id=tenant_id,
            user_id=USER,
            actor=AGENT,
            source_type="episode",
            source_identity="sqlite-working-test",
            session_id=session_id,
            content=f"evidence-{tenant_id}-{session_id}",
            capability_tags=["working-memory"],
            access_policy={"tenant": tenant_id},
        )
    )


def _item(
    evidence_id: str,
    *,
    item_id: str = "item-a",
    tenant_id: str = TENANT,
    session_id: str = SESSION,
    user_id: str = USER,
    created_at: datetime = CREATED_AT,
    expires_at: datetime = EXPIRES_AT,
) -> _SQLiteWorkingMemoryItem:
    return _SQLiteWorkingMemoryItem(
        item_id=item_id,
        tenant_id=tenant_id,
        session_id=session_id,
        user_id=user_id,
        agent_id=AGENT,
        kind="active_goal",
        task_id="task-1",
        content=f"content-{item_id}",
        created_at=created_at,
        expires_at=expires_at,
        evidence_ids=[evidence_id],
        access_policy={"tenant": tenant_id},
        metadata={"priority": "high"},
    )


def test_sqlite_schema_adds_working_memory_without_changing_core_tables(tmp_path) -> None:
    engine = SqliteEngine(tmp_path)
    conn = engine._connect(TENANT)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"evidence", "assertions", "relations", "audit_log", "working_memory"} <= tables
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(working_memory)")
    }
    assert {"tenant_id", "session_id", "item_id", "expires_at", "status", "evidence_ids"} <= columns


def test_sqlite_working_memory_is_scoped_detached_and_ttl_is_half_open(tmp_path) -> None:
    engine = SqliteEngine(tmp_path)
    first = _item(_evidence(engine, session_id="s1"), item_id="same", session_id="s1")
    second = _item(_evidence(engine, session_id="s2"), item_id="same", session_id="s2")
    engine.put_working(first)
    engine.put_working(second)

    first.metadata["priority"] = "mutated"
    first.evidence_ids.append("caller-mutation")
    fetched = engine.get_working(TENANT, "s1", "same", as_of=EXPIRES_AT - timedelta(microseconds=1))
    assert fetched is not None
    fetched.metadata["priority"] = "return-mutation"
    assert engine.get_working(TENANT, "s1", "same", as_of=CREATED_AT).metadata == {"priority": "high"}
    assert engine.get_working(TENANT, "s2", "same", as_of=CREATED_AT).content == second.content
    assert engine.get_working("other-tenant", "s1", "same", as_of=CREATED_AT) is None

    assert engine.list_working(TENANT, "s1", as_of=EXPIRES_AT - timedelta(microseconds=1))
    assert engine.get_working(TENANT, "s1", "same", as_of=EXPIRES_AT) is None
    expired = engine.expire_working(TENANT, session_id="s1", expired_at=EXPIRES_AT)
    assert [item.item_id for item in expired] == ["same"]
    assert engine.expire_working(TENANT, session_id="s1", expired_at=EXPIRES_AT) == []
    audits = [
        row
        for row in engine.export_tenant(TENANT)["audit_log"]
        if row["target_id"] == "same" and row["diff"]["session_id"] == "s1"
    ]
    assert [row["op"] for row in audits] == ["put_working", "expire_working"]
    assert audits[-1]["diff"]["sweep"] == EXPIRES_AT.isoformat()


def test_sqlite_working_memory_uses_composite_scope_and_deterministic_list_order(tmp_path) -> None:
    engine = SqliteEngine(tmp_path)
    tenant_item = _item(_evidence(engine, session_id=SESSION), item_id="same")
    other_tenant = "tenant-other"
    other_tenant_item = _item(
        _evidence(engine, tenant_id=other_tenant, session_id=SESSION),
        tenant_id=other_tenant,
        item_id="same",
    )
    earlier = _item(
        _evidence(engine, session_id=SESSION),
        item_id="later-id",
        created_at=CREATED_AT - timedelta(seconds=1),
        expires_at=EXPIRES_AT - timedelta(seconds=1),
    )
    first = _item(_evidence(engine, session_id=SESSION), item_id="first")

    engine.put_working(tenant_item)
    engine.put_working(other_tenant_item)
    engine.put_working(earlier)
    engine.put_working(first)

    assert [item.item_id for item in engine.list_working(TENANT, SESSION, as_of=CREATED_AT)] == [
        "later-id",
        "first",
        "same",
    ]
    assert engine.get_working(other_tenant, SESSION, "same", as_of=CREATED_AT).tenant_id == other_tenant
    with pytest.raises(ValueError, match="already exists"):
        engine.put_working(_item(_evidence(engine, session_id=SESSION), item_id="same"))


def test_sqlite_working_memory_expiry_orders_and_prevalidates_provenance(tmp_path) -> None:
    engine = SqliteEngine(tmp_path)
    evidence = [_evidence(engine) for _ in range(3)]
    engine.put_working(_item(evidence[1], item_id="b"))
    engine.put_working(_item(evidence[0], item_id="a"))
    engine.put_working(_item(evidence[2], item_id="c", expires_at=EXPIRES_AT + timedelta(seconds=1)))
    # Simulate stale backing provenance without using a Local oracle.
    conn = engine._connect(TENANT)
    conn.execute(
        "UPDATE evidence SET erased = 1 WHERE tenant_id = ? AND cid = ?",
        (TENANT, evidence[2]),
    )
    conn.commit()
    with pytest.raises(ValueError):
        engine.expire_working(TENANT, expired_at=EXPIRES_AT + timedelta(seconds=1))
    assert conn.execute("SELECT count(*) FROM working_memory WHERE status = 'active'").fetchone()[0] == 3
    assert not [row for row in engine.export_tenant(TENANT)["audit_log"] if row["op"] == "expire_working"]


def test_sqlite_working_memory_validates_provenance_on_put_and_get(tmp_path) -> None:
    engine = SqliteEngine(tmp_path)
    evidence_id = _evidence(engine)

    with pytest.raises(ValueError, match="session must match"):
        engine.put_working(_item(evidence_id, session_id="wrong-session"))
    with pytest.raises(ValueError, match="user must match"):
        engine.put_working(_item(evidence_id, user_id="wrong-user"))

    engine.put_working(_item(evidence_id))
    conn = engine._connect(TENANT)
    conn.execute(
        "UPDATE evidence SET erased = 1 WHERE tenant_id = ? AND cid = ?",
        (TENANT, evidence_id),
    )
    conn.commit()
    with pytest.raises(ValueError, match="is erased"):
        engine.get_working(TENANT, SESSION, "item-a", as_of=CREATED_AT)


def test_sqlite_working_memory_accepts_inclusive_24_hour_ttl(tmp_path) -> None:
    engine = SqliteEngine(tmp_path)
    evidence_id = _evidence(engine)
    expires_at = CREATED_AT + timedelta(hours=24)
    engine.put_working(_item(evidence_id, expires_at=expires_at))

    assert engine.get_working(TENANT, SESSION, "item-a", as_of=expires_at - timedelta(microseconds=1)) is not None
    assert engine.get_working(TENANT, SESSION, "item-a", as_of=expires_at) is None
    with pytest.raises(ValueError, match="cannot exceed 24 hours"):
        _item(
            evidence_id,
            item_id="too-long",
            expires_at=expires_at + timedelta(microseconds=1),
        )


def test_sqlite_working_memory_put_and_expiry_audits_share_transaction(tmp_path) -> None:
    engine = SqliteEngine(tmp_path)
    evidence_id = _evidence(engine)
    conn = engine._connect(TENANT)
    conn.execute(
        """
        CREATE TRIGGER fail_working_audit AFTER INSERT ON audit_log
        WHEN json_extract(NEW.record, '$.op') IN ('put_working', 'expire_working')
        BEGIN SELECT RAISE(ABORT, 'working audit unavailable'); END
        """
    )
    conn.commit()
    with pytest.raises(sqlite3.Error, match="working audit unavailable"):
        engine.put_working(_item(evidence_id))
    assert conn.execute("SELECT count(*) FROM working_memory").fetchone()[0] == 0
    conn.execute("DROP TRIGGER fail_working_audit")
    conn.commit()
    engine.put_working(_item(evidence_id))

    conn.execute(
        """
        CREATE TRIGGER fail_working_audit AFTER INSERT ON audit_log
        WHEN json_extract(NEW.record, '$.op') = 'expire_working'
        BEGIN SELECT RAISE(ABORT, 'working expiry audit unavailable'); END
        """
    )
    conn.commit()
    with pytest.raises(sqlite3.Error, match="working expiry audit unavailable"):
        engine.expire_working(TENANT, expired_at=EXPIRES_AT)
    assert conn.execute("SELECT status FROM working_memory WHERE item_id = 'item-a'").fetchone()[0] == "active"
    assert not [row for row in engine.export_tenant(TENANT)["audit_log"] if row["op"] == "expire_working"]


def test_sqlite_working_memory_same_database_expiry_is_exactly_once(tmp_path) -> None:
    first = SqliteEngine(tmp_path)
    evidence_id = _evidence(first)
    first.put_working(_item(evidence_id))
    second = SqliteEngine(tmp_path)

    def expire(engine: SqliteEngine) -> list[str]:
        return [item.item_id for item in engine.expire_working(TENANT, expired_at=EXPIRES_AT)]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(expire, (first, second)))
    assert sorted(results) == [[], ["item-a"]]
    audits = [row for row in first.export_tenant(TENANT)["audit_log"] if row["op"] == "expire_working"]
    assert len(audits) == 1


def test_sqlite_working_memory_unavailable_storage_fails_closed(tmp_path, monkeypatch) -> None:
    engine = SqliteEngine(tmp_path)
    evidence_id = _evidence(engine)
    item = _item(evidence_id)

    def unavailable(_tenant: str):
        raise sqlite3.OperationalError("unavailable")

    monkeypatch.setattr(engine, "_connect", unavailable)
    with pytest.raises(sqlite3.OperationalError, match="unavailable"):
        engine.put_working(item)
    with pytest.raises(sqlite3.OperationalError, match="unavailable"):
        engine.get_working(TENANT, SESSION, item.item_id, as_of=CREATED_AT)
    with pytest.raises(sqlite3.OperationalError, match="unavailable"):
        engine.list_working(TENANT, SESSION, as_of=CREATED_AT)
    with pytest.raises(sqlite3.OperationalError, match="unavailable"):
        engine.expire_working(TENANT, expired_at=EXPIRES_AT)


def test_sqlite_working_memory_normalizes_offset_instants_before_sql_comparison(tmp_path) -> None:
    engine = SqliteEngine(tmp_path)
    offset_created = datetime.fromisoformat("2026-07-17T05:00:00-07:00")
    offset_expires = datetime.fromisoformat("2026-07-17T05:00:30-07:00")
    item = _SQLiteWorkingMemoryItem(
        item_id="offset",
        tenant_id=TENANT,
        session_id=SESSION,
        user_id=USER,
        agent_id=AGENT,
        kind="active_goal",
        task_id="task-offset",
        content="offset content",
        created_at=offset_created,
        expires_at=offset_expires,
        evidence_ids=[_evidence(engine)],
        access_policy={"tenant": TENANT},
    )
    engine.put_working(item)
    assert engine.get_working(TENANT, SESSION, "offset", as_of=CREATED_AT + timedelta(seconds=29)) is not None
    assert engine.get_working(TENANT, SESSION, "offset", as_of=EXPIRES_AT) is None
    assert [row.item_id for row in engine.expire_working(TENANT, expired_at=EXPIRES_AT)] == ["offset"]
