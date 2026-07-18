from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import json
import sqlite3
from typing import Any

import pytest

from mnemosyne.engine import WorkingMemoryItem
from mnemosyne.models import Evidence
from mnemosyne.sqlite_engine import SqliteEngine


CREATED_AT = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
EXPIRES_AT = CREATED_AT + timedelta(seconds=30)
TENANT = "tenant-working"
USER = "user-working"
SESSION = "session-working"
AGENT = "agent-working"


def _evidence(
    engine: SqliteEngine,
    *,
    tenant_id: str = TENANT,
    session_id: str = SESSION,
    capability_tags: list[str] | None = None,
    sensitivity: int = 0,
    access_policy: dict[str, Any] | None = None,
    content: str | None = None,
    trust_tier: int = 0,
) -> str:
    return engine.append_evidence(
        Evidence(
            tenant_id=tenant_id,
            user_id=USER,
            actor=AGENT,
            source_type="episode",
            source_identity="sqlite-working-test",
            session_id=session_id,
            content=content or f"evidence-{tenant_id}-{session_id}",
            trust_tier=trust_tier,
            capability_tags=capability_tags or ["working-memory"],
            sensitivity=sensitivity,
            access_policy=access_policy or {"tenant": tenant_id},
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
    capability_tags: list[str] | None = None,
    sensitivity: int = 0,
    access_policy: dict[str, Any] | None = None,
    trust_tier: int = 0,
) -> Any:
    return WorkingMemoryItem(
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
        trust_tier=trust_tier,
        access_policy=access_policy or {"tenant": tenant_id},
        metadata={"priority": "high"},
        capability_tags=capability_tags or [],
        sensitivity=sensitivity,
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
    assert {
        "tenant_id", "session_id", "item_id", "expires_at", "trust_tier", "status", "evidence_ids"
    } <= columns
    assert "working_memory" in engine.export_tenant(TENANT)
    assert "working_memory" in engine.export_all()


def test_sqlite_export_all_migrates_legacy_database_before_enumerating_tables(tmp_path) -> None:
    engine = SqliteEngine(tmp_path)
    _evidence(engine)
    conn = engine._connect(TENANT)
    conn.execute("DROP TABLE working_memory")
    conn.commit()
    engine.close()

    reopened = SqliteEngine(tmp_path)
    exported = reopened.export_all()

    assert exported["tenants"][0]["tenant_id"] == TENANT
    assert exported["tenants"][0]["working_memory"] == []


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
    sweep = EXPIRES_AT + timedelta(seconds=1)
    expired = engine.expire_working(TENANT, session_id="s1", expired_at=sweep)
    assert [item.item_id for item in expired] == ["same"]
    assert expired[0].expired_at == sweep
    assert engine.expire_working(TENANT, session_id="s1", expired_at=sweep) == []
    audits = [
        row
        for row in engine.export_tenant(TENANT)["audit_log"]
        if row["target_id"] == "same" and row["diff"]["session_id"] == "s1"
    ]
    assert [row["op"] for row in audits] == ["put_working", "expire_working"]
    assert audits[-1]["diff"]["sweep"] == sweep.isoformat()
    assert audits[-1]["diff"]["item_id"] == "same"
    assert audits[-1]["diff"]["evidence_ids"] == first.evidence_ids[:1]
    assert audits[-1]["diff"]["working_digest"]


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
    first = _item(
        _evidence(engine, session_id=SESSION),
        item_id="first",
        expires_at=EXPIRES_AT + timedelta(seconds=5),
    )

    engine.put_working(tenant_item)
    engine.put_working(other_tenant_item)
    engine.put_working(earlier)
    engine.put_working(first)

    assert [item.item_id for item in engine.list_working(TENANT, SESSION, as_of=CREATED_AT)] == [
        "later-id",
        "same",
        "first",
    ]
    assert engine.get_working(other_tenant, SESSION, "same", as_of=CREATED_AT).tenant_id == other_tenant
    with pytest.raises(ValueError, match="already exists"):
        engine.put_working(_item(_evidence(engine, session_id=SESSION), item_id="same"))


def test_sqlite_working_memory_rejects_falsy_status_mutation(tmp_path) -> None:
    engine = SqliteEngine(tmp_path)
    item = _item(_evidence(engine))
    item.status = None

    with pytest.raises(ValueError, match="status"):
        engine.put_working(item)


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


def test_sqlite_working_memory_persists_restrictive_provenance_envelope(tmp_path) -> None:
    engine = SqliteEngine(tmp_path)
    evidence_id = _evidence(
        engine,
        capability_tags=["source-capability"],
        sensitivity=2,
        access_policy={"tenant": TENANT, "max_sensitivity": 1},
    )
    item = _item(evidence_id, capability_tags=["item-capability"])

    engine.put_working(item)

    stored = engine.get_working(TENANT, SESSION, item.item_id, as_of=CREATED_AT)
    assert stored is not None
    assert stored.sensitivity == 2
    assert stored.capability_tags == ["item-capability", "source-capability"]
    assert stored.access_policy["max_sensitivity"] == 1


def test_sqlite_working_memory_persists_effective_trust_tier_across_reload(tmp_path) -> None:
    engine = SqliteEngine(tmp_path)
    evidence_id = _evidence(engine, trust_tier=3)
    item = _item(evidence_id, trust_tier=2)

    engine.put_working(item)
    assert item.trust_tier == 3
    engine.close()

    reopened = SqliteEngine(tmp_path)
    stored = reopened.get_working(TENANT, SESSION, item.item_id, as_of=CREATED_AT)
    listed = reopened.list_working(TENANT, SESSION, as_of=CREATED_AT)
    assert stored is not None
    assert stored.trust_tier == 3
    assert [entry.trust_tier for entry in listed] == [3]


def test_sqlite_expiry_persists_refreshed_provenance_envelope(tmp_path) -> None:
    engine = SqliteEngine(tmp_path)
    evidence_id = _evidence(engine)
    engine.put_working(_item(evidence_id))
    assert engine.backfill_evidence_privacy(TENANT, evidence_id, ["email"])

    engine.expire_working(TENANT, expired_at=EXPIRES_AT)

    row = engine._connect(TENANT).execute(
        "SELECT capability_tags, sensitivity, access_policy FROM working_memory WHERE item_id = ?",
        ("item-a",),
    ).fetchone()
    assert json.loads(row["capability_tags"]) == ["working-memory"]
    assert row["sensitivity"] == 3
    assert json.loads(row["access_policy"])["max_sensitivity"] == 3


def test_sqlite_audit_event_ids_are_idempotent(tmp_path) -> None:
    engine = SqliteEngine(tmp_path)
    evidence_id = _evidence(engine)
    engine.put_working(_item(evidence_id))
    audit = next(
        row for row in engine.export_tenant(TENANT)["audit_log"] if row["op"] == "put_working"
    )

    conn = engine._connect(TENANT)
    with conn:
        engine._audit_row(
            conn,
            TENANT,
            AGENT,
            "put_working",
            "item-a",
            {"status": "active"},
            source="working_memory",
            event_id=audit["id"],
            occurred_at=CREATED_AT,
        )

    assert len([row for row in engine.export_tenant(TENANT)["audit_log"] if row["id"] == audit["id"]]) == 1


def test_sqlite_working_memory_accepts_inclusive_24_hour_ttl(tmp_path) -> None:
    engine = SqliteEngine(tmp_path)
    evidence_id = _evidence(engine)
    expires_at = CREATED_AT + timedelta(hours=24)
    engine.put_working(_item(evidence_id, expires_at=expires_at))

    assert engine.get_working(TENANT, SESSION, "item-a", as_of=expires_at - timedelta(microseconds=1)) is not None
    assert engine.get_working(TENANT, SESSION, "item-a", as_of=expires_at) is None
    with pytest.raises(ValueError, match="24 hours"):
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
    item = WorkingMemoryItem(
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


def test_sqlite_forget_trims_multi_provenance_working_items(tmp_path) -> None:
    engine = SqliteEngine(tmp_path)
    first = _evidence(engine)
    second = _evidence(engine, content="second-evidence")
    item = _item(first)
    item.evidence_ids.append(second)
    engine.put_working(item)

    report = engine.forget(TENANT, first)

    assert report["propagated"]["removed_working_items"] == []
    assert report["propagated"]["trimmed_working_items"] == [
        {"tenant_id": TENANT, "session_id": SESSION, "item_id": item.item_id}
    ]
    retained = engine.get_working(TENANT, SESSION, item.item_id, as_of=CREATED_AT)
    assert retained is not None
    assert retained.evidence_ids == [second]


def test_sqlite_forget_orders_working_item_removals_by_identity(tmp_path) -> None:
    engine = SqliteEngine(tmp_path)
    evidence_id = _evidence(engine)
    engine.put_working(_item(evidence_id, item_id="b"))
    engine.put_working(_item(evidence_id, item_id="a"))

    report = engine.forget(TENANT, evidence_id)

    assert report["propagated"]["removed_working_items"] == [
        {"tenant_id": TENANT, "session_id": SESSION, "item_id": "a"},
        {"tenant_id": TENANT, "session_id": SESSION, "item_id": "b"},
    ]


def test_sqlite_hard_delete_redacts_prior_working_audit_custody(tmp_path) -> None:
    engine = SqliteEngine(tmp_path)
    evidence_id = _evidence(engine)
    item = _item(evidence_id)
    engine.put_working(item)
    original_put_id = next(
        row["id"] for row in engine.export_tenant(TENANT)["audit_log"] if row["op"] == "put_working"
    )

    engine.forget(TENANT, evidence_id, requested_by="legal", erasure_mode="hard_delete_legal")

    exported = engine.export_tenant(TENANT)
    put_audit = next(row for row in exported["audit_log"] if row["op"] == "put_working")
    assert "working_digest" not in put_audit["diff"]
    assert put_audit["id"] != original_put_id
    assert evidence_id not in str(exported)


@pytest.mark.parametrize(
    ("column", "value"),
    (("trust_tier", 4.9), ("sensitivity", 4.9), ("capability_tags", "data-only")),
)
def test_sqlite_rejects_malformed_evidence_security_fields(tmp_path, column, value) -> None:
    engine = SqliteEngine(tmp_path)
    evidence_id = _evidence(engine)
    conn = engine._connect(TENANT)
    stored = json.dumps(value) if column == "capability_tags" else value
    conn.execute(f"UPDATE evidence SET {column} = ? WHERE cid = ?", (stored, evidence_id))
    conn.commit()

    with pytest.raises(ValueError):
        engine.put_working(_item(evidence_id))


def test_sqlite_working_memory_rejects_non_finite_json(tmp_path) -> None:
    engine = SqliteEngine(tmp_path)
    item = _item(_evidence(engine))
    item.metadata["not-json"] = float("nan")

    with pytest.raises(ValueError, match="finite JSON"):
        engine.put_working(item)
