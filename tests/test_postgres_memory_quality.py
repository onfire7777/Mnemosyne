"""Audit custody regressions and source lock ordering (unit + opt-in live SQL)."""

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest

from mnemosyne.engine import (
    Intention, ProspectiveOperatingPoint, TriggerEvaluationContext, intention_fire_receipt_id,
)
from mnemosyne.models import Evidence
from mnemosyne.postgres_engine import PostgresEngine, _stable_uuid


def test_source_transaction_takes_both_guards_before_body(monkeypatch):
    """Capture-only unit check; the documents suite exercises live contention."""
    statements = []
    cursor = SimpleNamespace(execute=lambda sql, params=None: statements.append((sql, params)))
    connection = SimpleNamespace(cursor=lambda: nullcontext(cursor), rollback=lambda: None)
    engine = PostgresEngine("postgresql://unit-test-fake", require_safe_role=False)
    monkeypatch.setattr(engine, "connect", lambda: nullcontext(connection))

    with engine.source_transaction("source-tenant"):
        locks = [(sql, params) for sql, params in statements if "pg_advisory_xact_lock" in sql]
        assert len(locks) == 2, "source guard must precede any body row/schema locks"
        assert locks[0][1] == ("source-tenant",)
        assert "mnemosyne.source_guard:" in locks[1][0]
        assert locks[1][1] == (_stable_uuid("tenant", "source-tenant"),)
        before_nested = list(statements)
        with engine.source_transaction("source-tenant"):
            assert statements == before_nested, "nested scopes must not reacquire guards"


@pytest.fixture
def live_engine():
    """Only use an explicitly supplied disposable database; never discover one."""
    pytest.importorskip("psycopg")
    dsn = os.environ.get("MNEMOSYNE_POSTGRES_DSN")
    if not dsn:
        pytest.skip("MNEMOSYNE_POSTGRES_DSN is not set")
    engine = PostgresEngine(dsn)
    tenant = f"memory-quality-{uuid4().hex}"
    engine.ensure_tenant_and_branch(tenant)
    try:
        yield engine, tenant
    finally:
        engine.close_connections()


def _insert_receipt(engine, tenant, event_id, intention_id, *, legacy=False, occurrence=0):
    with engine.connect() as conn:
        with conn.cursor() as cur:
            tenant_id = _stable_uuid("tenant", tenant)
            engine._set_tenant(cur, tenant_id)
            if legacy:
                cur.execute(
                    "INSERT INTO intention_firing_receipts "
                    "(tenant_id, intention_id, operation, canonical_event_id) "
                    "VALUES (%s, %s, 'fire', %s)",
                    (tenant_id, intention_id, event_id),
                )
            else:
                cur.execute(
                    "INSERT INTO intention_firing_receipts_v2 "
                    "(tenant_id, intention_id, operation, canonical_event_id, occurrence) "
                    "VALUES (%s, %s, 'fire', %s, %s)",
                    (tenant_id, intention_id, event_id, occurrence),
                )


@pytest.mark.parametrize("receipt_kind", [
    "v2", "legacy", "both", "wrong_tenant", "wrong_event", "missing", "ambiguous",
])
def test_live_redacted_audit_recovers_only_matching_receipt_identity(live_engine, receipt_kind):
    engine, tenant = live_engine
    event_id = f"fire-{uuid4().hex}"
    intention_id = "arbitrary-intention-id"
    erased_diff = {"source_payload_erased": True}
    with engine.connect() as conn:
        with conn.cursor() as cur:
            tenant_id = _stable_uuid("tenant", tenant)
            engine._set_tenant(cur, tenant_id)
            cur.execute(
                "INSERT INTO audit_log (tenant_id, actor, op, target_id, diff, event_id) "
                "VALUES (%s, 'agent', 'fire_intention', NULL, %s, %s)",
                (tenant_id, engine._jsonb(erased_diff), event_id),
            )
    if receipt_kind != "missing":
        _insert_receipt(
            engine, tenant + "-other" if receipt_kind == "wrong_tenant" else tenant,
            event_id + "-other" if receipt_kind == "wrong_event" else event_id,
            intention_id, legacy=receipt_kind == "legacy",
        )
    if receipt_kind in {"both", "ambiguous"}:
        _insert_receipt(engine, tenant, event_id,
                        "conflicting-id" if receipt_kind == "ambiguous" else intention_id,
                        legacy=True)

    rows = [row for row in engine.export_tenant(tenant)["audit_log"] if row["id"] == event_id]
    assert len(rows) == 1, "duplicate receipts must not multiply audit rows"
    expected_target = intention_id if receipt_kind in {"v2", "legacy", "both"} else None
    assert rows[0]["target_id"] == expected_target
    assert rows[0]["diff"] == erased_diff, "only identity, never erased payload, may be recovered"
    assert "firing_intention_id" not in rows[0]
    with engine.connect() as conn:
        with conn.cursor() as cur:
            engine._set_tenant(cur, tenant_id)
            cur.execute("SELECT target_id, diff FROM audit_log WHERE tenant_id = %s AND event_id = %s",
                        (tenant_id, event_id))
            assert cur.fetchone() == (None, erased_diff), "export must be read-only"


def test_live_receipt_without_audit_does_not_invent_an_event(live_engine):
    engine, tenant = live_engine
    event_id = f"fire-{uuid4().hex}"
    before = engine.export_tenant(tenant)["audit_log"]
    _insert_receipt(engine, tenant, event_id, "missing-audit")
    assert engine.export_tenant(tenant)["audit_log"] == before


@pytest.mark.parametrize("op,diff,target_id,expected_target", [
    ("schedule_intention", {"source_payload_erased": True}, None, None),
    ("fire_intention", {}, None, None),
    ("fire_intention", {"source_payload_erased": False}, None, None),
    ("fire_intention", {"source_payload_erased": "true"}, None, None),
    ("fire_intention", {"target_id": "original-id"}, None, "original-id"),
    ("fire_intention", {"source_payload_erased": True},
     "bbf413bc-b6ee-4d4d-8751-995eab102582", "bbf413bc-b6ee-4d4d-8751-995eab102582"),
])
def test_live_receipt_does_not_override_other_audit_identity(
    live_engine, op, diff, target_id, expected_target,
):
    engine, tenant = live_engine
    event_id = f"fire-{uuid4().hex}"
    with engine.connect() as conn:
        with conn.cursor() as cur:
            tenant_id = _stable_uuid("tenant", tenant)
            engine._set_tenant(cur, tenant_id)
            cur.execute(
                "INSERT INTO audit_log (tenant_id, actor, op, target_id, diff, event_id) "
                "VALUES (%s, 'agent', %s, %s, %s, %s)",
                (tenant_id, op, target_id, engine._jsonb(diff), event_id),
            )
    _insert_receipt(engine, tenant, event_id, "must-not-replace-identity")
    rows = [row for row in engine.export_tenant(tenant)["audit_log"] if row["id"] == event_id]
    assert len(rows) == 1 and rows[0]["target_id"] == expected_target
    assert rows[0]["diff"] == {key: value for key, value in diff.items() if key != "target_id"}


@pytest.mark.parametrize("erasure_mode", ["tombstone_recompute", "hard_delete_legal"])
def test_live_recurrence_retains_event_identity_without_erased_payload(live_engine, erasure_mode):
    engine, tenant = live_engine
    secret = "PRIVATE original reminder payload"
    cid = engine.append_evidence(Evidence(
        tenant_id=tenant, user_id="owner", actor="user", source_type="chat",
        content=secret, trust_tier=1, access_policy={"tenant": tenant},
    ))
    due = datetime(2026, 7, 16, 12, tzinfo=UTC)
    intention_id = "arbitrary-recurring-intention"
    engine.schedule_intention(Intention(
        intention_id=intention_id, tenant_id=tenant, user_id="owner", agent_id="agent",
        trigger_type="exact_time", trigger_expression={"at": due.isoformat()}, due_at=due,
        action={"type": "remind", "message": secret}, evidence_ids=[cid], session_id="session",
        recurrence_policy={"type": "interval", "interval_seconds": 60, "max_occurrences": 2},
    ))
    operating_point = ProspectiveOperatingPoint(
        operating_point_id="quality-op", threshold=0.5, measured_precision=0.9,
        measured_recall=0.85, measurement_cid="cidv1:quality-measurement",
    )
    for occurrence in range(2):
        fired = engine.evaluate_due_intentions(
            tenant, evaluated_at=due + timedelta(minutes=occurrence),
            trigger_context=TriggerEvaluationContext(tenant_id=tenant, infrastructure_available=True, events=[], conditions={}),
            operating_point=operating_point,
        )
        assert len(fired) == 1
    expected_ids = {intention_fire_receipt_id(tenant, intention_id, occurrence) for occurrence in range(2)}
    engine.forget(tenant, cid, erasure_mode=erasure_mode)
    assert engine.list_intentions(tenant) == []
    rows = [row for row in engine.export_tenant(tenant)["audit_log"] if row["op"] == "fire_intention"]
    assert len(rows) == 2 and {row["id"] for row in rows} == expected_ids
    for row in rows:
        assert row["target_id"] == intention_id
        assert row["diff"] == {"source_payload_erased": True}
        assert secret not in str(row) and cid not in str(row)
    # Projection does not recreate an intention or reset occurrence idempotency.
    assert engine.evaluate_due_intentions(
        tenant, evaluated_at=due + timedelta(minutes=2),
        trigger_context=TriggerEvaluationContext(tenant_id=tenant, infrastructure_available=True, events=[], conditions={}),
        operating_point=operating_point,
    ) == []
