"""PostgreSQL prospective-memory tests (W3 Phase 2).

These tests exercise the PostgreSQL intention persistence, RLS, and evaluator
against a live database, covering all five trigger types, provenance fail-closed
paths, cancellation ownership, tenant isolation, idempotent firing, and the
audit/provenance invariants from the frozen contract.

The canonical engine contract validates all five trigger types and is used
directly by these PostgreSQL parity tests.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier, Event
from typing import Any
from uuid import uuid4

import pytest

from mnemosyne.engine import (
    Intention,
    ProspectiveOperatingPoint,
    TriggerEvaluationContext,
)
from mnemosyne.ids import content_cid
from mnemosyne.models import Evidence
from mnemosyne.postgres_engine import PostgresEngine, _cid_to_bytes, _stable_uuid
from mnemosyne.privacy import ErasureMode

psycopg = pytest.importorskip("psycopg")
psycopg_sql = pytest.importorskip("psycopg.sql")

_DSN = os.environ.get("MNEMOSYNE_POSTGRES_DSN")
_RLS_TEST_ROLE = os.environ.get("MNEMOSYNE_POSTGRES_RLS_TEST_ROLE", "mnemosyne_pm_app")
TENANT_ID = "tenant-a"
_EVALUATED_AT = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
_OP = ProspectiveOperatingPoint(
    operating_point_id="op-test",
    threshold=0.5,
    measured_precision=0.9,
    measured_recall=0.85,
    measurement_cid="cidv1:test-measurement",
)


def _ctx(
    infra: bool = True, events=None, conditions=None, tenant_id: str | None = None
) -> TriggerEvaluationContext:
    tenant_id = tenant_id or TENANT_ID
    normalized_events = [
        {**event, "tenant_id": event.get("tenant_id", tenant_id)} for event in events or []
    ]
    normalized_conditions = {
        condition_id: {
            **observation,
            "tenant_id": observation.get("tenant_id", tenant_id),
        }
        for condition_id, observation in (conditions or {}).items()
    }
    return TriggerEvaluationContext(
        infrastructure_available=infra,
        tenant_id=tenant_id,
        events=normalized_events,
        conditions=normalized_conditions,
    )


def _make_intention(
    *,
    tenant_id: str,
    user_id: str,
    agent_id: str,
    evidence_id: str,
    trigger_type: str,
    trigger_expression: dict[str, Any],
    due_at: datetime,
    intention_id: str | None = None,
    dependencies: list[str] | None = None,
    action: dict[str, Any] | None = None,
    session_id: str | None = None,
    recurrence_policy: dict[str, Any] | None = None,
) -> Intention:
    """Construct an intention through the canonical public contract."""

    return Intention(
        intention_id=intention_id or f"intention-{uuid4().hex[:12]}",
        tenant_id=tenant_id,
        user_id=user_id,
        agent_id=agent_id,
        trigger_type=trigger_type,
        trigger_expression=dict(trigger_expression),
        action=action or {"type": "remind", "message": "Submit the report."},
        due_at=due_at.astimezone(UTC),
        dependencies=list(dependencies or []),
        evidence_ids=[evidence_id],
        session_id=session_id,
        recurrence_policy=recurrence_policy or {"type": "none"},
    )


def _append_evidence(
    engine: PostgresEngine,
    *,
    tenant_id: str,
    user_id: str,
    agent_id: str,
    trust_tier: int = 2,
    capability_tags=None,
    content: str = "Remind me to submit the report.",
) -> str:
    engine._prospective_test_tenants.add(tenant_id)
    return engine.append_evidence(
        Evidence(
            tenant_id=tenant_id,
            user_id=user_id,
            actor="assistant",
            source_type="episode",
            source_identity=f"conversation:prospective-memory-pg:{agent_id}",
            content=content,
            trust_tier=trust_tier,
            capability_tags=capability_tags or ["prospective-memory"],
            access_policy={"tenant": tenant_id},
        )
    )


@pytest.fixture
def engine():
    if not _DSN:
        pytest.skip("MNEMOSYNE_POSTGRES_DSN is not set")
    eng = PostgresEngine(_DSN, require_safe_role=False)
    eng._prospective_test_tenants = set()
    try:
        with eng.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    except psycopg.OperationalError as exc:
        eng.close_connections()
        pytest.skip(f"live PostgreSQL prerequisite unavailable: {exc}")
    try:
        yield eng
    finally:
        with eng.connect() as conn:
            with conn.cursor() as cur:
                for tenant_id in sorted(eng._prospective_test_tenants):
                    cur.execute(
                        "DELETE FROM tenants WHERE id = %s",
                        (_stable_uuid("tenant", tenant_id),),
                    )
        eng.close_connections()


def _require_rls_test_role(engine: PostgresEngine) -> None:
    with engine.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s",
                (_RLS_TEST_ROLE,),
            )
            if cur.fetchone() is None:
                pytest.skip(f"PostgreSQL RLS test role {_RLS_TEST_ROLE!r} is unavailable")
            cur.execute(
                "SELECT pg_has_role(current_user, %s, 'MEMBER')",
                (_RLS_TEST_ROLE,),
            )
            if cur.fetchone() != (True,):
                pytest.skip(
                    f"current PostgreSQL user cannot SET ROLE to {_RLS_TEST_ROLE!r}"
                )
            cur.execute(
                """
                SELECT has_table_privilege(%s, 'intentions', 'SELECT')
                   AND has_table_privilege(%s, 'intention_firing_receipts', 'SELECT')
                   AND has_table_privilege(%s, 'intention_firing_receipts_v2', 'SELECT')
                """,
                (_RLS_TEST_ROLE, _RLS_TEST_ROLE, _RLS_TEST_ROLE),
            )
            if cur.fetchone() != (True,):
                pytest.skip(
                    f"PostgreSQL RLS test role {_RLS_TEST_ROLE!r} lacks required SELECT grants"
                )


@pytest.fixture
def tenant_user_agent():
    global TENANT_ID
    original = TENANT_ID
    tid = f"tenant-pm-{uuid4().hex[:8]}"
    TENANT_ID = tid
    uid = f"user-pm-{uuid4().hex[:8]}"
    aid = f"agent-pm-{uuid4().hex[:8]}"
    yield tid, uid, aid
    TENANT_ID = original


def test_postgres_schema_migration_is_additive_and_occurrence_aware() -> None:
    schema = (Path(__file__).parent.parent / "sql" / "schema.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS intention_firing_receipts_v2" in schema
    assert "PRIMARY KEY (tenant_id, intention_id, operation, occurrence)" in schema
    assert "DROP CONSTRAINT IF EXISTS intention_firing_receipts_pkey" not in schema


def test_live_schema_upgrade_preserves_legacy_receipts_and_adds_v2() -> None:
    if not _DSN:
        pytest.skip("MNEMOSYNE_POSTGRES_DSN is not set")
    schema_name = f"p5_receipt_upgrade_{uuid4().hex}"
    runtime_tenant = f"upgrade-{uuid4().hex}"
    legacy_tenant = _stable_uuid("tenant", runtime_tenant)
    legacy_event = f"legacy-event-{uuid4().hex}"
    schema_sql = (Path(__file__).parent.parent / "sql" / "schema.sql").read_text()
    isolated_dsn = psycopg.conninfo.make_conninfo(
        _DSN, options=f"-csearch_path={schema_name},public"
    )
    engine = None
    with psycopg.connect(_DSN, autocommit=True) as admin:
        try:
            with admin.cursor() as cur:
                cur.execute(
                    psycopg_sql.SQL("CREATE SCHEMA {}").format(
                        psycopg_sql.Identifier(schema_name)
                    )
                )
                cur.execute(
                    psycopg_sql.SQL("SET search_path TO {}, public").format(
                        psycopg_sql.Identifier(schema_name)
                    )
                )
                cur.execute(
                    """
                    CREATE TABLE intention_firing_receipts (
                      tenant_id UUID NOT NULL,
                      intention_id TEXT NOT NULL,
                      operation TEXT NOT NULL CHECK (operation = 'fire'),
                      canonical_event_id TEXT NOT NULL,
                      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                      PRIMARY KEY (tenant_id, intention_id, operation)
                    )
                    """
                )
                cur.execute(
                    "INSERT INTO intention_firing_receipts "
                    "(tenant_id, intention_id, operation, canonical_event_id) "
                    "VALUES (%s, 'legacy-intention', 'fire', %s)",
                    (legacy_tenant, legacy_event),
                )
                cur.execute(
                    """
                    SELECT c.oid, con.oid, pg_get_constraintdef(con.oid)
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    JOIN pg_constraint con ON con.conrelid = c.oid
                    WHERE n.nspname = %s AND c.relname = 'intention_firing_receipts'
                      AND con.contype = 'p'
                    """,
                    (schema_name,),
                )
                legacy_identity = cur.fetchone()
                for _ in range(2):
                    cur.execute(schema_sql, prepare=False)
                cur.execute(
                    """
                    SELECT c.oid, con.oid, pg_get_constraintdef(con.oid)
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    JOIN pg_constraint con ON con.conrelid = c.oid
                    WHERE n.nspname = %s AND c.relname = 'intention_firing_receipts'
                      AND con.contype = 'p'
                    """,
                    (schema_name,),
                )
                assert cur.fetchone() == legacy_identity
                cur.execute(
                    "SELECT canonical_event_id FROM intention_firing_receipts "
                    "WHERE tenant_id = %s AND intention_id = 'legacy-intention'",
                    (legacy_tenant,),
                )
                assert cur.fetchone() == (legacy_event,)

            engine = PostgresEngine(isolated_dsn, require_safe_role=False)
            engine._prospective_test_tenants = set()
            tenant = runtime_tenant
            user = "upgrade-user"
            agent = "upgrade-agent"
            evidence_id = _append_evidence(
                engine, tenant_id=tenant, user_id=user, agent_id=agent
            )
            due = _EVALUATED_AT
            legacy_collision = _make_intention(
                tenant_id=tenant, user_id=user, agent_id=agent,
                evidence_id=evidence_id, trigger_type="exact_time",
                trigger_expression={"at": due.isoformat()}, due_at=due,
                intention_id="legacy-intention", session_id="upgrade-session",
            )
            with pytest.raises(ValueError, match="durable firing receipt"):
                engine.schedule_intention(legacy_collision)
            intention = _make_intention(
                tenant_id=tenant, user_id=user, agent_id=agent,
                evidence_id=evidence_id, trigger_type="exact_time",
                trigger_expression={"at": due.isoformat()}, due_at=due,
                intention_id="upgrade-recurrence", session_id="upgrade-session",
                recurrence_policy={
                    "type": "interval", "interval_seconds": 60, "max_occurrences": 2
                },
            )
            engine.schedule_intention(intention)
            for index in range(2):
                evaluated = due + timedelta(minutes=index)
                assert len(engine.evaluate_due_intentions(
                    tenant, evaluated_at=evaluated,
                    trigger_context=_ctx(tenant_id=tenant), operating_point=_OP,
                )) == 1
            engine.close_connections()
            engine = None

            with admin.cursor() as cur:
                cur.execute(
                    psycopg_sql.SQL("SET search_path TO {}, public").format(
                        psycopg_sql.Identifier(schema_name)
                    )
                )
                cur.execute(schema_sql, prepare=False)
                cur.execute(
                    "SELECT canonical_event_id FROM intention_firing_receipts "
                    "WHERE tenant_id = %s AND intention_id = 'legacy-intention'",
                    (legacy_tenant,),
                )
                assert cur.fetchone() == (legacy_event,)
                cur.execute(
                    "SELECT occurrence FROM intention_firing_receipts_v2 "
                    "WHERE intention_id = 'upgrade-recurrence' ORDER BY occurrence"
                )
                assert cur.fetchall() == [(0,), (1,)]
        finally:
            if engine is not None:
                engine.close_connections()
            with admin.cursor() as cur:
                cur.execute(
                    psycopg_sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                        psycopg_sql.Identifier(schema_name)
                    )
                )


def test_backwards_evaluation_raises_even_after_recurrence_advance(
    engine, tenant_user_agent
) -> None:
    tid, uid, aid = tenant_user_agent
    evidence_id = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
    due = _EVALUATED_AT
    engine.schedule_intention(_make_intention(
        tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=evidence_id,
        trigger_type="exact_time", trigger_expression={"at": due.isoformat()},
        due_at=due, session_id="session-a",
        recurrence_policy={"type": "interval", "interval_seconds": 3600},
    ))
    assert len(engine.evaluate_due_intentions(
        tid, evaluated_at=due, trigger_context=_ctx(tenant_id=tid),
        operating_point=_OP,
    )) == 1
    # The recurrence advanced due_at past the next evaluation clock; the
    # backwards-clock guard must still raise exactly as Local and SQLite do
    # instead of silently skipping the no-longer-due candidate.
    with pytest.raises(ValueError, match="evaluated_at cannot move backwards"):
        engine.evaluate_due_intentions(
            tid, evaluated_at=due - timedelta(minutes=1),
            trigger_context=_ctx(tenant_id=tid), operating_point=_OP,
        )


def test_cancel_accepts_owner_external_id_on_pre_backfill_rows(
    engine, tenant_user_agent
) -> None:
    tid, uid, aid = tenant_user_agent
    evidence_id = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
    due = _EVALUATED_AT + timedelta(hours=1)
    intention = _make_intention(
        tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=evidence_id,
        trigger_type="exact_time", trigger_expression={"at": due.isoformat()},
        due_at=due,
    )
    engine.schedule_intention(intention)
    db_tenant_id = _stable_uuid("tenant", tid)
    with engine.connect() as conn:
        with conn.cursor() as cur:
            engine._set_tenant(cur, db_tenant_id)
            # Simulate pre-backfill rows: external_user_id holds the internal
            # user UUID text exactly as the schema backfill produces it, and
            # pre-migration evidence has no _external_user_id metadata.
            cur.execute(
                "UPDATE intentions SET external_user_id = user_id::text "
                "WHERE tenant_id = %s AND intention_id = %s",
                (db_tenant_id, intention.intention_id),
            )
            cur.execute(
                "UPDATE evidence SET metadata = metadata - '_external_user_id' "
                "WHERE tenant_id = %s AND cid = %s",
                (db_tenant_id, _cid_to_bytes(evidence_id)),
            )
    engine.cancel_intention(
        tid, intention.intention_id, cancelled_by=uid, session_id="session-a"
    )
    stored = engine.list_intentions(tid)[0]
    assert stored.status == "cancelled"
    assert stored.cancellation_state is not None


class TestUpdateAndRecurrence:
    @pytest.mark.parametrize("trigger_type", ["exact_time", "time_window"])
    def test_update_rewrites_trigger_persists_and_replay_is_zero_mutation(
        self, engine, tenant_user_agent, trigger_type
    ):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT + timedelta(hours=1)
        expression = {"at": due.isoformat()} if trigger_type == "exact_time" else {
            "start": due.isoformat(), "end": (due + timedelta(minutes=30)).isoformat()
        }
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type=trigger_type, trigger_expression=expression, due_at=due,
            session_id="session-a",
        )
        engine.schedule_intention(intention)
        moved = due + timedelta(hours=1)
        updated = engine.update_intention(
            tid, intention.intention_id, user_id=uid, agent_id=aid,
            session_id="session-a", due_at=moved,
        )
        replay = engine.update_intention(
            tid, intention.intention_id, user_id=uid, agent_id=aid,
            session_id="session-a", due_at=moved,
        )
        stored = engine.list_intentions(tid)[0]
        key = "at" if trigger_type == "exact_time" else "start"
        assert stored.trigger_expression[key] == moved.isoformat()
        if trigger_type == "time_window":
            assert stored.trigger_expression["end"] == (
                moved + timedelta(minutes=30)
            ).isoformat()
        assert stored == updated == replay
        assert len(stored.reschedule_history) == 1
        assert engine.evaluate_due_intentions(
            tid, evaluated_at=moved, trigger_context=_ctx(tenant_id=tid),
            operating_point=_OP,
        )[0].intention_id == intention.intention_id

    def test_recurrence_has_per_occurrence_receipts_and_terminal_max(
        self, engine, tenant_user_agent
    ):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="exact_time", trigger_expression={"at": due.isoformat()},
            due_at=due, session_id="session-a",
            recurrence_policy={"type": "interval", "interval_seconds": 60, "max_occurrences": 2},
        )
        engine.schedule_intention(intention)
        for index in range(2):
            evaluated = due + timedelta(minutes=index)
            assert len(engine.evaluate_due_intentions(
                tid, evaluated_at=evaluated, trigger_context=_ctx(tenant_id=tid),
                operating_point=_OP,
            )) == 1
            assert engine.evaluate_due_intentions(
                tid, evaluated_at=evaluated, trigger_context=_ctx(tenant_id=tid),
                operating_point=_OP,
            ) == []
        assert engine.list_intentions(tid)[0].status == "fired"
        with engine.connect() as conn:
            with conn.cursor() as cur:
                engine._set_tenant(cur, _stable_uuid("tenant", tid))
                cur.execute(
                    "SELECT occurrence FROM intention_firing_receipts_v2 "
                    "WHERE tenant_id = %s AND intention_id = %s ORDER BY occurrence",
                    (_stable_uuid("tenant", tid), intention.intention_id),
                )
                assert [row[0] for row in cur.fetchall()] == [0, 1]

    def test_event_watermark_survives_fresh_engine_reload(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="event",
            trigger_expression={"event_type": "report.submitted", "match": {}},
            due_at=due,
            recurrence_policy={"type": "interval", "interval_seconds": 60},
        )
        engine.schedule_intention(intention)
        first = due + timedelta(minutes=1)
        context = _ctx(events=[{
            "event_id": "event-1", "event_type": "report.submitted",
            "occurred_at": first.isoformat(), "payload": {}, "confidence": 0.99,
        }], tenant_id=tid)
        assert len(engine.evaluate_due_intentions(
            tid, evaluated_at=first, trigger_context=context, operating_point=_OP,
        )) == 1
        reloaded = PostgresEngine(_DSN, require_safe_role=False)
        try:
            state = reloaded.list_intentions(tid)[0].recurrence_state
            assert state["consumed_signal"] == {
                "event_id": "event-1", "occurred_at": first.isoformat(),
            }
            assert "consumed_signals" not in state
            assert reloaded.evaluate_due_intentions(
                tid, evaluated_at=first + timedelta(minutes=1),
                trigger_context=context, operating_point=_OP,
            ) == []
        finally:
            reloaded.close_connections()

    def test_legacy_sessionless_update_binds_survives_reload_and_rejects_rebinding(
        self, engine, tenant_user_agent
    ):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT + timedelta(hours=1)
        intention = _make_intention(
            tenant_id=tid,
            user_id=uid,
            agent_id=aid,
            evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
        )
        engine.schedule_intention(intention)
        bound = engine.update_intention(
            tid,
            intention.intention_id,
            user_id=uid,
            agent_id=aid,
            session_id="session-a",
            action={"type": "remind", "message": "Bound."},
        )
        assert bound.session_id == "session-a"

        reloaded = PostgresEngine(_DSN, require_safe_role=False)
        try:
            before = reloaded.list_intentions(tid)[0]
            audit_before = list(reloaded.export_tenant(tid)["audit_log"])
            assert before.session_id == "session-a"
            with pytest.raises(PermissionError, match="session"):
                reloaded.update_intention(
                    tid,
                    intention.intention_id,
                    user_id=uid,
                    agent_id=aid,
                    session_id="session-b",
                    action={"type": "remind", "message": "Denied."},
                )
            assert reloaded.list_intentions(tid)[0] == before
            assert reloaded.export_tenant(tid)["audit_log"] == audit_before
        finally:
            reloaded.close_connections()

    def test_update_audit_failure_rolls_back_state_history_and_retries(
        self, engine, tenant_user_agent, monkeypatch
    ):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT + timedelta(hours=1)
        intention = _make_intention(
            tenant_id=tid,
            user_id=uid,
            agent_id=aid,
            evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
            session_id="session-a",
        )
        engine.schedule_intention(intention)
        before = engine.list_intentions(tid)[0]
        audit_before = list(engine.export_tenant(tid)["audit_log"])
        moved = due + timedelta(hours=1)
        original_audit = engine._audit

        def fail_audit(*_args, **_kwargs):
            raise RuntimeError("injected update audit failure")

        monkeypatch.setattr(engine, "_audit", fail_audit)
        with pytest.raises(RuntimeError, match="injected update audit failure"):
            engine.update_intention(
                tid,
                intention.intention_id,
                user_id=uid,
                agent_id=aid,
                session_id="session-a",
                due_at=moved,
            )
        assert engine.list_intentions(tid)[0] == before
        assert engine.export_tenant(tid)["audit_log"] == audit_before

        monkeypatch.setattr(engine, "_audit", original_audit)
        retried = engine.update_intention(
            tid,
            intention.intention_id,
            user_id=uid,
            agent_id=aid,
            session_id="session-a",
            due_at=moved,
        )
        assert retried.due_at == moved
        assert len(retried.reschedule_history) == 1
        assert len(engine.export_tenant(tid)["audit_log"]) == len(audit_before) + 1


class TestExactTime:
    def test_due_exact_time_fires_once_with_audit(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
            intention_id="intention-exact-1",
        )
        engine.schedule_intention(intention)
        fired = engine.evaluate_due_intentions(tid, evaluated_at=_EVALUATED_AT, trigger_context=_ctx(), operating_point=_OP)
        replay = engine.evaluate_due_intentions(tid, evaluated_at=_EVALUATED_AT, trigger_context=_ctx(), operating_point=_OP)
        assert [f.intention_id for f in fired] == ["intention-exact-1"]
        assert fired[0].status == "fired"
        assert replay == []
        stored = engine.list_intentions(tid)
        assert len(stored) == 1
        assert stored[0].status == "fired"
        assert stored[0].evidence_ids == [eid]

    def test_future_exact_time_does_not_fire(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT + timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
        )
        engine.schedule_intention(intention)
        assert engine.evaluate_due_intentions(tid, evaluated_at=_EVALUATED_AT, trigger_context=_ctx(), operating_point=_OP) == []
        assert engine.list_intentions(tid)[0].status == "scheduled"


class TestTimeWindow:
    def test_time_window_fires_within_window(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        start = _EVALUATED_AT - timedelta(minutes=5)
        end = _EVALUATED_AT + timedelta(minutes=5)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="time_window",
            trigger_expression={"start": start.isoformat(), "end": end.isoformat()},
            due_at=start,
        )
        engine.schedule_intention(intention)
        fired = engine.evaluate_due_intentions(tid, evaluated_at=_EVALUATED_AT, trigger_context=_ctx(), operating_point=_OP)
        assert len(fired) == 1
        assert engine.list_intentions(tid)[0].status == "fired"

    def test_time_window_does_not_fire_at_or_after_end(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        start = _EVALUATED_AT - timedelta(minutes=10)
        end = _EVALUATED_AT - timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="time_window",
            trigger_expression={"start": start.isoformat(), "end": end.isoformat()},
            due_at=start,
        )
        engine.schedule_intention(intention)
        assert engine.evaluate_due_intentions(tid, evaluated_at=_EVALUATED_AT, trigger_context=_ctx(), operating_point=_OP) == []
        assert engine.list_intentions(tid)[0].status == "scheduled"


class TestEvent:
    def test_event_fires_on_matching_event(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=5)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="event",
            trigger_expression={"event_type": "deploy", "match": {"service": "api"}},
            due_at=due,
        )
        engine.schedule_intention(intention)
        ctx = _ctx(events=[{
            "event_id": "evt-1",
            "event_type": "deploy",
            "occurred_at": (_EVALUATED_AT - timedelta(minutes=1)).isoformat(),
            "payload": {"service": "api", "version": "2.0"},
            "confidence": 0.9,
        }])
        fired = engine.evaluate_due_intentions(tid, evaluated_at=_EVALUATED_AT, trigger_context=ctx, operating_point=_OP)
        assert len(fired) == 1
        assert engine.list_intentions(tid)[0].status == "fired"

    def test_event_does_not_fire_on_non_matching_payload(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=5)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="event",
            trigger_expression={"event_type": "deploy", "match": {"service": "api"}},
            due_at=due,
        )
        engine.schedule_intention(intention)
        ctx = _ctx(events=[{
            "event_id": "evt-2",
            "event_type": "deploy",
            "occurred_at": (_EVALUATED_AT - timedelta(minutes=1)).isoformat(),
            "payload": {"service": "web"},
            "confidence": 0.9,
        }])
        assert engine.evaluate_due_intentions(tid, evaluated_at=_EVALUATED_AT, trigger_context=ctx, operating_point=_OP) == []
        assert engine.list_intentions(tid)[0].status == "scheduled"

    def test_event_low_confidence_does_not_fire(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=5)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="event",
            trigger_expression={"event_type": "deploy", "match": {}},
            due_at=due,
        )
        engine.schedule_intention(intention)
        ctx = _ctx(events=[{
            "event_id": "evt-3",
            "event_type": "deploy",
            "occurred_at": (_EVALUATED_AT - timedelta(minutes=1)).isoformat(),
            "payload": {},
            "confidence": 0.3,
        }])
        assert engine.evaluate_due_intentions(tid, evaluated_at=_EVALUATED_AT, trigger_context=ctx, operating_point=_OP) == []


class TestCondition:
    def test_condition_eq_fires(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=5)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="condition",
            trigger_expression={"condition_id": "temp", "operator": "gt", "value": 30},
            due_at=due,
        )
        engine.schedule_intention(intention)
        ctx = _ctx(conditions={
            "temp": {"value": 35, "observed_at": (_EVALUATED_AT - timedelta(minutes=1)).isoformat(), "confidence": 0.9},
        })
        fired = engine.evaluate_due_intentions(tid, evaluated_at=_EVALUATED_AT, trigger_context=ctx, operating_point=_OP)
        assert len(fired) == 1
        assert engine.list_intentions(tid)[0].status == "fired"

    def test_condition_lt_does_not_fire_when_false(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=5)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="condition",
            trigger_expression={"condition_id": "temp", "operator": "lt", "value": 30},
            due_at=due,
        )
        engine.schedule_intention(intention)
        ctx = _ctx(conditions={
            "temp": {"value": 35, "observed_at": (_EVALUATED_AT - timedelta(minutes=1)).isoformat(), "confidence": 0.9},
        })
        assert engine.evaluate_due_intentions(tid, evaluated_at=_EVALUATED_AT, trigger_context=ctx, operating_point=_OP) == []

    def test_condition_in_operator_fires(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=5)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="condition",
            trigger_expression={"condition_id": "status", "operator": "in", "value": ["ready", "done"]},
            due_at=due,
        )
        engine.schedule_intention(intention)
        ctx = _ctx(conditions={
            "status": {"value": "ready", "observed_at": (_EVALUATED_AT - timedelta(minutes=1)).isoformat(), "confidence": 0.9},
        })
        fired = engine.evaluate_due_intentions(tid, evaluated_at=_EVALUATED_AT, trigger_context=ctx, operating_point=_OP)
        assert len(fired) == 1


class TestDependencyCompletion:
    def test_dependency_completion_fires_when_all_deps_fired(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due_a = _EVALUATED_AT - timedelta(minutes=10)
        due_b = _EVALUATED_AT - timedelta(minutes=5)
        intention_a = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due_a.isoformat()},
            due_at=due_a,
            intention_id="dep-a",
        )
        engine.schedule_intention(intention_a)
        engine.evaluate_due_intentions(tid, evaluated_at=_EVALUATED_AT, trigger_context=_ctx(), operating_point=_OP)
        assert engine.list_intentions(tid)[0].status == "fired"
        intention_b = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="dependency_completion",
            trigger_expression={"require": "all"},
            due_at=due_b,
            intention_id="dep-b",
            dependencies=["dep-a"],
        )
        engine.schedule_intention(intention_b)
        fired = engine.evaluate_due_intentions(tid, evaluated_at=_EVALUATED_AT, trigger_context=_ctx(), operating_point=_OP)
        assert [f.intention_id for f in fired] == ["dep-b"]

    def test_dependency_completion_does_not_fire_when_dep_not_fired(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due_a = _EVALUATED_AT + timedelta(minutes=10)
        due_b = _EVALUATED_AT - timedelta(minutes=5)
        intention_a = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due_a.isoformat()},
            due_at=due_a,
            intention_id="dep-pending-a",
        )
        engine.schedule_intention(intention_a)
        intention_b = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="dependency_completion",
            trigger_expression={"require": "all"},
            due_at=due_b,
            intention_id="dep-pending-b",
            dependencies=["dep-pending-a"],
        )
        engine.schedule_intention(intention_b)
        # dep-pending-a is still scheduled (future due_at), not fired
        result = engine.evaluate_due_intentions(tid, evaluated_at=_EVALUATED_AT, trigger_context=_ctx(), operating_point=_OP)
        assert [f.intention_id for f in result] == []
        assert engine.list_intentions(tid)[1].status == "scheduled"


class TestProvenanceFailClosed:
    def test_schedule_rejects_missing_evidence(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        due = _EVALUATED_AT - timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id="missing-evidence",
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
        )
        with pytest.raises(ValueError, match="missing or outside"):
            engine.schedule_intention(intention)
        assert engine.list_intentions(tid) == []

    def test_schedule_rejects_foreign_tenant_evidence(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        other_eid = _append_evidence(engine, tenant_id="other-tenant", user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=other_eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
        )
        with pytest.raises(ValueError, match="missing or outside"):
            engine.schedule_intention(intention)

    def test_schedule_rejects_wrong_user_evidence(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        other_eid = _append_evidence(engine, tenant_id=tid, user_id="other-user", agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=other_eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
        )
        with pytest.raises(ValueError, match="intention user must match"):
            engine.schedule_intention(intention)

    def test_schedule_rejects_tainted_evidence(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid, capability_tags=["data-only", "no-write-authority"])
        due = _EVALUATED_AT - timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
        )
        with pytest.raises(PermissionError, match="data-only evidence"):
            engine.schedule_intention(intention)

    def test_schedule_rejects_over_ceiling_trust(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid, trust_tier=5)
        due = _EVALUATED_AT - timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
        )
        eng = PostgresEngine(_DSN, require_safe_role=False)
        eng.policy.max_trust_tier = 1
        with pytest.raises(PermissionError, match="write trust ceiling"):
            eng.schedule_intention(intention)
        eng.close_connections()

    def test_evaluate_fails_closed_if_provenance_erased(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
        )
        engine.schedule_intention(intention)
        with engine.connect() as conn:
            with conn.cursor() as cur:
                engine._set_tenant(cur, _stable_uuid("tenant", tid))
                cur.execute(
                    "UPDATE evidence SET erased = TRUE WHERE tenant_id = %s AND cid = %s",
                    (_stable_uuid("tenant", tid), _cid_to_bytes(eid)),
                )
        with pytest.raises(ValueError, match="missing or outside"):
            engine.evaluate_due_intentions(
                tid,
                evaluated_at=_EVALUATED_AT,
                trigger_context=_ctx(),
                operating_point=_OP,
            )
        assert engine.list_intentions(tid)[0].status == "scheduled"

    def test_unsatisfied_trigger_does_not_validate_erased_provenance(
        self, engine, tenant_user_agent
    ):
        tid, uid, aid = tenant_user_agent
        valid_eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        invalid_eid = _append_evidence(
            engine,
            tenant_id=tid,
            user_id=uid,
            agent_id=aid,
            content="Only fire when the condition is true.",
        )
        due = _EVALUATED_AT - timedelta(minutes=1)
        engine.schedule_intention(
            _make_intention(
                tenant_id=tid,
                user_id=uid,
                agent_id=aid,
                evidence_id=valid_eid,
                trigger_type="exact_time",
                trigger_expression={"at": due.isoformat()},
                due_at=due,
                intention_id="valid-fire",
            )
        )
        engine.schedule_intention(
            _make_intention(
                tenant_id=tid,
                user_id=uid,
                agent_id=aid,
                evidence_id=invalid_eid,
                trigger_type="condition",
                trigger_expression={"condition_id": "never", "operator": "eq", "value": True},
                due_at=due,
                intention_id="invalid-no-fire",
            )
        )
        with engine.connect() as conn:
            with conn.cursor() as cur:
                engine._set_tenant(cur, _stable_uuid("tenant", tid))
                cur.execute(
                    "UPDATE evidence SET erased = TRUE WHERE tenant_id = %s AND cid = %s",
                    (_stable_uuid("tenant", tid), _cid_to_bytes(invalid_eid)),
                )

        fired = engine.evaluate_due_intentions(
            tid,
            evaluated_at=_EVALUATED_AT,
            trigger_context=_ctx(conditions={"never": {"value": False, "confidence": 1.0, "observed_at": _EVALUATED_AT.isoformat()}}),
            operating_point=_OP,
        )
        assert [item.intention_id for item in fired] == ["valid-fire"]


class TestCancel:
    def test_legacy_sessionless_cancel_binds_survives_reload_and_rejects_rebinding(
        self, engine, tenant_user_agent
    ):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT + timedelta(hours=1)
        intention = _make_intention(
            tenant_id=tid,
            user_id=uid,
            agent_id=aid,
            evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
        )
        engine.schedule_intention(intention)
        engine.cancel_intention(
            tid,
            intention.intention_id,
            cancelled_by=uid,
            session_id="session-a",
        )

        reloaded = PostgresEngine(_DSN, require_safe_role=False)
        try:
            before = reloaded.list_intentions(tid)[0]
            audit_before = list(reloaded.export_tenant(tid)["audit_log"])
            assert before.status == "cancelled"
            assert before.session_id == "session-a"
            with pytest.raises(PermissionError, match="session"):
                reloaded.cancel_intention(
                    tid,
                    intention.intention_id,
                    cancelled_by=uid,
                    session_id="session-b",
                )
            reloaded.cancel_intention(
                tid,
                intention.intention_id,
                cancelled_by=uid,
                session_id="session-a",
            )
            assert reloaded.list_intentions(tid)[0] == before
            assert reloaded.export_tenant(tid)["audit_log"] == audit_before
        finally:
            reloaded.close_connections()

    def test_cancel_by_owner_user(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
        )
        engine.schedule_intention(intention)
        engine.cancel_intention(tid, intention.intention_id, cancelled_by=uid, session_id="session-a")
        stored = engine.list_intentions(tid)[0]
        assert stored.status == "cancelled"
        assert stored.cancellation_state is not None

    def test_cancel_by_owner_agent(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
        )
        engine.schedule_intention(intention)
        engine.cancel_intention(tid, intention.intention_id, cancelled_by=aid, session_id="session-a")
        assert engine.list_intentions(tid)[0].status == "cancelled"

    def test_cancel_by_non_owner_raises(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
        )
        engine.schedule_intention(intention)
        with pytest.raises(PermissionError, match="owning user or agent"):
            engine.cancel_intention(tid, intention.intention_id, cancelled_by="other-user", session_id="session-a")

    def test_cancel_missing_raises_keyerror(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        with pytest.raises(KeyError):
            engine.cancel_intention(tid, "nonexistent", cancelled_by=uid, session_id="session-a")

    def test_cancel_fired_raises_valueerror(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
        )
        engine.schedule_intention(intention)
        engine.evaluate_due_intentions(tid, evaluated_at=_EVALUATED_AT, trigger_context=_ctx(), operating_point=_OP)
        with pytest.raises(ValueError, match="cannot be cancelled"):
            engine.cancel_intention(tid, intention.intention_id, cancelled_by=uid, session_id="session-a")

    def test_cancel_already_cancelled_is_noop(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
        )
        engine.schedule_intention(intention)
        engine.cancel_intention(tid, intention.intention_id, cancelled_by=uid, session_id="session-a")
        engine.cancel_intention(tid, intention.intention_id, cancelled_by=uid, session_id="session-a")
        assert engine.list_intentions(tid)[0].status == "cancelled"
        audits = [
            item
            for item in engine.export_tenant(tid)["audit_log"]
            if item["op"] == "cancel_intention"
        ]
        assert len(audits) == 1

    def test_two_connections_cancel_once(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT + timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid,
            user_id=uid,
            agent_id=aid,
            evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
            intention_id="two-connection-cancel",
        )
        engine.schedule_intention(intention)
        contenders = [
            PostgresEngine(_DSN, require_safe_role=False),
            PostgresEngine(_DSN, require_safe_role=False),
        ]
        start = Barrier(2)

        def cancel(contender: PostgresEngine) -> None:
            start.wait(timeout=5)
            contender.cancel_intention(tid, intention.intention_id, cancelled_by=uid, session_id="session-a")

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(cancel, contender) for contender in contenders]
                for future in futures:
                    future.result(timeout=15)
        finally:
            for contender in contenders:
                contender.close_connections()

        assert engine.list_intentions(tid)[0].status == "cancelled"
        audits = [
            item
            for item in engine.export_tenant(tid)["audit_log"]
            if item["op"] == "cancel_intention"
        ]
        assert len(audits) == 1

    def test_two_connections_cancel_and_fire_have_one_winner(
        self, engine, tenant_user_agent
    ):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid,
            user_id=uid,
            agent_id=aid,
            evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
            intention_id="cancel-fire-race",
        )
        engine.schedule_intention(intention)
        cancel_engine = PostgresEngine(_DSN, require_safe_role=False)
        fire_engine = PostgresEngine(_DSN, require_safe_role=False)
        start = Barrier(2)

        def cancel() -> str:
            start.wait(timeout=5)
            try:
                cancel_engine.cancel_intention(
                    tid, intention.intention_id, cancelled_by=uid, session_id="session-a"
                )
            except ValueError as exc:
                assert "cannot be cancelled" in str(exc)
                return "already-fired"
            return "cancelled"

        def fire() -> str:
            start.wait(timeout=5)
            fired = fire_engine.evaluate_due_intentions(
                tid,
                evaluated_at=_EVALUATED_AT,
                trigger_context=_ctx(),
                operating_point=_OP,
            )
            if not fired:
                return "already-cancelled"
            assert [(item.intention_id, item.status) for item in fired] == [
                (intention.intention_id, "fired")
            ]
            return "fired"

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                cancel_future = executor.submit(cancel)
                fire_future = executor.submit(fire)
                results = {
                    cancel_future.result(timeout=15),
                    fire_future.result(timeout=15),
                }
        finally:
            cancel_engine.close_connections()
            fire_engine.close_connections()

        assert results in (
            {"already-fired", "fired"},
            {"already-cancelled", "cancelled"},
        )
        final_status = engine.list_intentions(tid)[0].status
        expected_op = "fire_intention" if final_status == "fired" else "cancel_intention"
        transition_audits = [
            item
            for item in engine.export_tenant(tid)["audit_log"]
            if item["target_id"] == intention.intention_id
            and item["op"] in {"cancel_intention", "fire_intention"}
        ]
        assert [item["op"] for item in transition_audits] == [expected_op]


class TestTenantIsolation:
    def test_list_is_tenant_scoped(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
        )
        engine.schedule_intention(intention)
        assert engine.list_intentions("other-tenant") == []

    def test_evaluate_is_tenant_scoped(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
        )
        engine.schedule_intention(intention)
        assert engine.evaluate_due_intentions(
            "other-tenant", evaluated_at=_EVALUATED_AT,
            trigger_context=_ctx(tenant_id="other-tenant"), operating_point=_OP,
        ) == []

    def test_cancel_cross_tenant_raises_keyerror(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
        )
        engine.schedule_intention(intention)
        with pytest.raises(KeyError):
            engine.cancel_intention("other-tenant", intention.intention_id, cancelled_by=uid, session_id="session-a")

    def test_rls_and_owner_ids_are_isolated(self, engine, tenant_user_agent):
        _require_rls_test_role(engine)
        tid, uid, aid = tenant_user_agent
        other_tid = f"tenant-pm-{uuid4().hex[:8]}"
        other_uid = f"user-pm-{uuid4().hex[:8]}"
        other_aid = f"agent-pm-{uuid4().hex[:8]}"
        due = _EVALUATED_AT - timedelta(minutes=1)

        for tenant_id, user_id, agent_id, intention_id in (
            (tid, uid, aid, "visible-intention"),
            (other_tid, other_uid, other_aid, "hidden-intention"),
        ):
            evidence_id = _append_evidence(
                engine,
                tenant_id=tenant_id,
                user_id=user_id,
                agent_id=agent_id,
            )
            engine.schedule_intention(
                _make_intention(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    agent_id=agent_id,
                    evidence_id=evidence_id,
                    trigger_type="exact_time",
                    trigger_expression={"at": due.isoformat()},
                    due_at=due,
                    intention_id=intention_id,
                )
            )

        with pytest.raises(PermissionError, match="owning user or agent"):
            engine.cancel_intention(tid, "visible-intention", cancelled_by=other_uid, session_id="session-a")
        with pytest.raises(PermissionError, match="owning user or agent"):
            engine.cancel_intention(tid, "visible-intention", cancelled_by=other_aid, session_id="session-a")

        for tenant_id in (tid, other_tid):
            fired = engine.evaluate_due_intentions(
                tenant_id,
                evaluated_at=_EVALUATED_AT,
                trigger_context=_ctx(tenant_id=tenant_id),
                operating_point=_OP,
            )
            assert len(fired) == 1

        with engine.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    psycopg_sql.SQL("SET LOCAL ROLE {}").format(
                        psycopg_sql.Identifier(_RLS_TEST_ROLE)
                    )
                )
                engine._set_tenant(cur, _stable_uuid("tenant", tid))
                cur.execute(
                    "SELECT intention_id, external_user_id, agent_id FROM intentions"
                )
                assert cur.fetchall() == [("visible-intention", uid, aid)]
                cur.execute(
                    "SELECT intention_id FROM intention_firing_receipts_v2"
                )
                assert cur.fetchall() == [("visible-intention",)]


class TestIdempotency:
    @pytest.mark.parametrize("terminal_operation", ["fire", "cancel"])
    def test_update_races_terminal_transition_without_stale_overwrite(
        self, engine, tenant_user_agent, terminal_operation
    ):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        intention = _make_intention(
            tenant_id=tid,
            user_id=uid,
            agent_id=aid,
            evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": _EVALUATED_AT.isoformat()},
            due_at=_EVALUATED_AT,
            intention_id=f"update-{terminal_operation}-race",
        )
        engine.schedule_intention(intention)
        contenders = [
            PostgresEngine(_DSN, require_safe_role=False),
            PostgresEngine(_DSN, require_safe_role=False),
        ]
        start = Barrier(2)

        def update() -> tuple[str, Any]:
            start.wait(timeout=5)
            try:
                return (
                    "update",
                    contenders[0].update_intention(
                        tid,
                        intention.intention_id,
                        user_id=uid,
                        agent_id=aid,
                        session_id="session-a",
                        due_at=_EVALUATED_AT + timedelta(hours=1),
                    ),
                )
            except Exception as exc:
                return ("update-error", exc)

        def terminate() -> tuple[str, Any]:
            start.wait(timeout=5)
            try:
                if terminal_operation == "fire":
                    return (
                        "fire",
                        contenders[1].evaluate_due_intentions(
                            tid,
                            evaluated_at=_EVALUATED_AT,
                            trigger_context=_ctx(tenant_id=tid),
                            operating_point=_OP,
                        ),
                    )
                contenders[1].cancel_intention(
                    tid,
                    intention.intention_id,
                    cancelled_by=uid,
                    session_id="session-a",
                )
                return ("cancel", None)
            except Exception as exc:
                return (f"{terminal_operation}-error", exc)

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                update_future = executor.submit(update)
                terminal_future = executor.submit(terminate)
                update_result = update_future.result(timeout=15)
                terminal_result = terminal_future.result(timeout=15)
        finally:
            for contender in contenders:
                contender.close_connections()

        stored = engine.list_intentions(tid)[0]
        if terminal_operation == "cancel":
            assert terminal_result == ("cancel", None)
            assert stored.status == "cancelled"
        elif update_result[0] == "update":
            assert stored.status == "scheduled"
            assert terminal_result == ("fire", [])
        else:
            assert stored.status == "fired"
        if update_result[0] == "update-error":
            assert isinstance(update_result[1], ValueError)
        operations = [item["op"] for item in engine.export_tenant(tid)["audit_log"]]
        assert operations.count("update_intention") == (
            1 if update_result[0] == "update" else 0
        )
        assert operations.count(f"{terminal_operation}_intention") == (
            1 if terminal_operation == "cancel" or stored.status == "fired" else 0
        )

    def test_two_connections_race_to_one_durable_firing(
        self, engine, tenant_user_agent
    ):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=1)
        engine.schedule_intention(
            _make_intention(
                tenant_id=tid,
                user_id=uid,
                agent_id=aid,
                evidence_id=eid,
                trigger_type="exact_time",
                trigger_expression={"at": due.isoformat()},
                due_at=due,
                intention_id="two-connection-race",
            )
        )

        contenders = [
            PostgresEngine(_DSN, require_safe_role=False),
            PostgresEngine(_DSN, require_safe_role=False),
        ]
        start = Barrier(2)

        def evaluate(contender: PostgresEngine) -> list[tuple[str, str]]:
            start.wait(timeout=5)
            return [
                (item.intention_id, item.status)
                for item in contender.evaluate_due_intentions(
                    tid,
                    evaluated_at=_EVALUATED_AT,
                    trigger_context=_ctx(),
                    operating_point=_OP,
                )
            ]

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(evaluate, contender) for contender in contenders]
                results = [future.result(timeout=15) for future in futures]
        finally:
            for contender in contenders:
                contender.close_connections()

        assert sorted(results, key=len) == [[], [("two-connection-race", "fired")]]
        assert engine.list_intentions(tid)[0].status == "fired"
        with engine.connect() as conn:
            with conn.cursor() as cur:
                engine._set_tenant(cur, _stable_uuid("tenant", tid))
                cur.execute(
                    """
                    SELECT count(*)
                    FROM intention_firing_receipts_v2
                    WHERE tenant_id = %s AND intention_id = %s
                    """,
                    (_stable_uuid("tenant", tid), "two-connection-race"),
                )
                assert cur.fetchone() == (1,)
        fire_audits = [
            item
            for item in engine.export_tenant(tid)["audit_log"]
            if item["op"] == "fire_intention"
            and item["target_id"] == "two-connection-race"
        ]
        assert len(fire_audits) == 1
        assert fire_audits[0]["id"] == fire_audits[0]["diff"]["canonical_event_id"]

    def test_replay_evaluation_returns_empty(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
        )
        engine.schedule_intention(intention)
        engine.evaluate_due_intentions(tid, evaluated_at=_EVALUATED_AT, trigger_context=_ctx(), operating_point=_OP)
        assert engine.evaluate_due_intentions(
            tid,
            evaluated_at=_EVALUATED_AT + timedelta(hours=1),
            trigger_context=_ctx(),
            operating_point=_OP,
        ) == []
        db_tenant_id = _stable_uuid("tenant", tid)
        expected_event_id = content_cid(
            "fire_intention",
            {"tenant_id": tid, "intention_id": intention.intention_id, "op": "fire"},
        )
        with engine.connect() as conn:
            with conn.cursor() as cur:
                engine._set_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    SELECT operation, canonical_event_id
                    FROM intention_firing_receipts_v2
                    WHERE tenant_id = %s AND intention_id = %s
                    """,
                    (db_tenant_id, intention.intention_id),
                )
                assert cur.fetchall() == [("fire", expected_event_id)]

    def test_audit_failure_rolls_back_receipt_and_state(
        self, engine, tenant_user_agent, monkeypatch
    ):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid,
            user_id=uid,
            agent_id=aid,
            evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
        )
        engine.schedule_intention(intention)

        def fail_audit(*_args, **_kwargs):
            raise RuntimeError("injected audit failure")

        monkeypatch.setattr(engine, "_audit", fail_audit)
        with pytest.raises(RuntimeError, match="injected audit failure"):
            engine.evaluate_due_intentions(
                tid,
                evaluated_at=_EVALUATED_AT,
                trigger_context=_ctx(),
                operating_point=_OP,
            )

        assert engine.list_intentions(tid)[0].status == "scheduled"
        db_tenant_id = _stable_uuid("tenant", tid)
        with engine.connect() as conn:
            with conn.cursor() as cur:
                engine._set_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    SELECT count(*)
                    FROM intention_firing_receipts_v2
                    WHERE tenant_id = %s AND intention_id = %s
                    """,
                    (db_tenant_id, intention.intention_id),
                )
                assert cur.fetchone() == (0,)

    def test_duplicate_schedule_raises(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
            intention_id="dup-1",
        )
        engine.schedule_intention(intention)
        with pytest.raises(ValueError, match="already exists"):
            engine.schedule_intention(intention)

    def test_concurrent_duplicate_schedule_raises_value_error(
        self, engine, tenant_user_agent
    ):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid,
            user_id=uid,
            agent_id=aid,
            evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
            intention_id="concurrent-duplicate",
        )
        contenders = [
            PostgresEngine(_DSN, require_safe_role=False),
            PostgresEngine(_DSN, require_safe_role=False),
        ]
        start = Barrier(2)

        def schedule(contender: PostgresEngine) -> str:
            start.wait(timeout=5)
            try:
                contender.schedule_intention(intention)
            except ValueError as exc:
                return str(exc)
            return "scheduled"

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = [
                    future.result(timeout=15)
                    for future in [
                        executor.submit(schedule, contender)
                        for contender in contenders
                    ]
                ]
        finally:
            for contender in contenders:
                contender.close_connections()

        assert sorted(results) == [
            "intention 'concurrent-duplicate' already exists",
            "scheduled",
        ]


class TestSnapshotLocks:
    def test_schedule_holds_dependency_and_evidence_snapshots(
        self, engine, tenant_user_agent
    ):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        dependency = _make_intention(
            tenant_id=tid,
            user_id=uid,
            agent_id=aid,
            evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": (_EVALUATED_AT + timedelta(hours=1)).isoformat()},
            due_at=_EVALUATED_AT + timedelta(hours=1),
            intention_id="locked-schedule-dependency",
        )
        engine.schedule_intention(dependency)
        dependent = _make_intention(
            tenant_id=tid,
            user_id=uid,
            agent_id=aid,
            evidence_id=eid,
            trigger_type="dependency_completion",
            trigger_expression={"require": "all"},
            due_at=_EVALUATED_AT + timedelta(hours=2),
            intention_id="locked-schedule-dependent",
            dependencies=[dependency.intention_id],
        )
        contender = PostgresEngine(_DSN, require_safe_role=False)
        original = contender._intention_provenance_rows
        snapshots_locked = Event()
        release = Event()

        def pause_after_locks(cur, *, db_tenant_id, intention):
            rows = original(
                cur, db_tenant_id=db_tenant_id, intention=intention
            )
            snapshots_locked.set()
            if not release.wait(timeout=5):
                raise TimeoutError("test did not release the schedule transaction")
            return rows

        contender._intention_provenance_rows = pause_after_locks
        db_tenant_id = _stable_uuid("tenant", tid)
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(contender.schedule_intention, dependent)
                assert snapshots_locked.wait(timeout=5)
                for statement, params in (
                    (
                        "UPDATE evidence SET erased = TRUE "
                        "WHERE tenant_id = %s AND branch = 'main' AND cid = %s",
                        (db_tenant_id, _cid_to_bytes(eid)),
                    ),
                    (
                        "DELETE FROM intentions "
                        "WHERE tenant_id = %s AND intention_id = %s",
                        (db_tenant_id, dependency.intention_id),
                    ),
                ):
                    with pytest.raises(psycopg.errors.LockNotAvailable):
                        with engine.connect() as conn:
                            with conn.cursor() as cur:
                                engine._set_tenant(cur, db_tenant_id)
                                cur.execute("SET LOCAL lock_timeout = '100ms'")
                                cur.execute(statement, params)
                release.set()
                assert future.result(timeout=10) == dependent.intention_id
        finally:
            release.set()
            contender.close_connections()

    def test_evaluation_holds_dependency_snapshot_until_fire_commits(
        self, engine, tenant_user_agent
    ):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        dependency = _make_intention(
            tenant_id=tid,
            user_id=uid,
            agent_id=aid,
            evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": (_EVALUATED_AT - timedelta(minutes=2)).isoformat()},
            due_at=_EVALUATED_AT - timedelta(minutes=2),
            intention_id="locked-evaluate-dependency",
        )
        engine.schedule_intention(dependency)
        engine.evaluate_due_intentions(
            tid,
            evaluated_at=_EVALUATED_AT,
            trigger_context=_ctx(),
            operating_point=_OP,
        )
        dependent = _make_intention(
            tenant_id=tid,
            user_id=uid,
            agent_id=aid,
            evidence_id=eid,
            trigger_type="dependency_completion",
            trigger_expression={"require": "all"},
            due_at=_EVALUATED_AT - timedelta(minutes=1),
            intention_id="locked-evaluate-dependent",
            dependencies=[dependency.intention_id],
        )
        engine.schedule_intention(dependent)
        contender = PostgresEngine(_DSN, require_safe_role=False)
        original = contender._intention_provenance_rows
        snapshots_locked = Event()
        release = Event()

        def pause_after_locks(cur, *, db_tenant_id, intention):
            rows = original(
                cur, db_tenant_id=db_tenant_id, intention=intention
            )
            snapshots_locked.set()
            if not release.wait(timeout=5):
                raise TimeoutError("test did not release the evaluation transaction")
            return rows

        contender._intention_provenance_rows = pause_after_locks
        db_tenant_id = _stable_uuid("tenant", tid)
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    contender.evaluate_due_intentions,
                    tid,
                    evaluated_at=_EVALUATED_AT,
                    trigger_context=_ctx(),
                    operating_point=_OP,
                )
                assert snapshots_locked.wait(timeout=5)
                with pytest.raises(psycopg.errors.LockNotAvailable):
                    with engine.connect() as conn:
                        with conn.cursor() as cur:
                            engine._set_tenant(cur, db_tenant_id)
                            cur.execute("SET LOCAL lock_timeout = '100ms'")
                            cur.execute(
                                "DELETE FROM intentions "
                                "WHERE tenant_id = %s AND intention_id = %s",
                                (db_tenant_id, dependency.intention_id),
                            )
                release.set()
                fired = future.result(timeout=10)
                assert [(item.intention_id, item.status) for item in fired] == [
                    (dependent.intention_id, "fired")
                ]
        finally:
            release.set()
            contender.close_connections()


class TestHostileDependencyId:
    def test_dependency_id_is_bound_data_not_sql(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        hostile_id = "dep'); DROP TABLE intentions; --"
        dependency_due = _EVALUATED_AT - timedelta(minutes=2)
        dependent_due = _EVALUATED_AT - timedelta(minutes=1)
        engine.schedule_intention(
            _make_intention(
                tenant_id=tid,
                user_id=uid,
                agent_id=aid,
                evidence_id=eid,
                trigger_type="exact_time",
                trigger_expression={"at": dependency_due.isoformat()},
                due_at=dependency_due,
                intention_id=hostile_id,
            )
        )
        assert [
            item.intention_id
            for item in engine.evaluate_due_intentions(
                tid,
                evaluated_at=_EVALUATED_AT,
                trigger_context=_ctx(),
                operating_point=_OP,
            )
        ] == [hostile_id]

        engine.schedule_intention(
            _make_intention(
                tenant_id=tid,
                user_id=uid,
                agent_id=aid,
                evidence_id=eid,
                trigger_type="dependency_completion",
                trigger_expression={"require": "all"},
                due_at=dependent_due,
                intention_id="hostile-id-dependent",
                dependencies=[hostile_id],
            )
        )
        fired = engine.evaluate_due_intentions(
            tid,
            evaluated_at=_EVALUATED_AT,
            trigger_context=_ctx(),
            operating_point=_OP,
        )

        assert [item.intention_id for item in fired] == ["hostile-id-dependent"]
        assert [item.intention_id for item in engine.list_intentions(tid)] == [
            hostile_id,
            "hostile-id-dependent",
        ]


class TestInfrastructureGate:
    def test_empty_tenant_raises_value_error(self, engine):
        with pytest.raises(ValueError, match="tenant_id must be a non-empty string"):
            engine.evaluate_due_intentions(
                "",
                evaluated_at=_EVALUATED_AT,
                trigger_context=_ctx(),
                operating_point=_OP,
            )

    def test_infra_unavailable_raises_runtimeerror(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
        )
        engine.schedule_intention(intention)
        with pytest.raises(RuntimeError, match="infrastructure is not available"):
            engine.evaluate_due_intentions(tid, evaluated_at=_EVALUATED_AT, trigger_context=_ctx(infra=False), operating_point=_OP)
        assert engine.list_intentions(tid)[0].status == "scheduled"


class TestAudit:
    def test_fire_audit_has_prospective_memory_source(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
            intention_id="audit-1",
        )
        engine.schedule_intention(intention)
        engine.evaluate_due_intentions(tid, evaluated_at=_EVALUATED_AT, trigger_context=_ctx(), operating_point=_OP)
        exported = engine.export_tenant(tid)
        fire_audits = [e for e in exported["audit_log"] if e["op"] == "fire_intention" and e["target_id"] == "audit-1"]
        assert len(fire_audits) == 1
        audit = fire_audits[0]
        expected_event_id = content_cid(
            "fire_intention",
            {"tenant_id": tid, "intention_id": intention.intention_id, "op": "fire"},
        )
        assert audit["id"] == expected_event_id
        assert audit["source"] == "prospective_memory"
        assert audit["diff"]["trigger_type"] == "exact_time"
        assert audit["diff"]["status"] == "fired"
        assert audit["diff"]["evidence_ids"] == [eid]
        assert audit["diff"]["intention_digest"]
        assert audit["diff"]["evaluated_at"] == _EVALUATED_AT.isoformat()
        assert audit["diff"]["canonical_event_id"] == expected_event_id
        assert audit["at"] == _EVALUATED_AT.isoformat().replace("+00:00", "Z")
        assert audit["diff"]["operating_point"] == _OP.to_dict()

    def test_fire_audit_canonical_event_id_is_unique(
        self, engine, tenant_user_agent
    ):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid,
            user_id=uid,
            agent_id=aid,
            evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
            intention_id="unique-audit-event",
        )
        engine.schedule_intention(intention)
        engine.evaluate_due_intentions(
            tid,
            evaluated_at=_EVALUATED_AT,
            trigger_context=_ctx(),
            operating_point=_OP,
        )
        event_id = content_cid(
            "fire_intention",
            {"tenant_id": tid, "intention_id": intention.intention_id, "op": "fire"},
        )
        db_tenant_id = _stable_uuid("tenant", tid)

        with pytest.raises(psycopg.errors.UniqueViolation):
            with engine.connect() as conn:
                with conn.cursor() as cur:
                    engine._set_tenant(cur, db_tenant_id)
                    cur.execute(
                        """
                        INSERT INTO audit_log(event_id, tenant_id, actor, op, diff)
                        VALUES (%s, %s, %s, %s, '{}'::jsonb)
                        """,
                        (event_id, db_tenant_id, aid, "duplicate_fire_intention"),
                    )

    def test_schedule_audit_has_provenance(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
            intention_id="audit-sched-1",
        )
        engine.schedule_intention(intention)
        exported = engine.export_tenant(tid)
        sched_audits = [e for e in exported["audit_log"] if e["op"] == "schedule_intention"]
        assert len(sched_audits) == 1
        audit = sched_audits[0]
        assert isinstance(audit["id"], int)
        assert "event_id" not in audit
        assert audit["source"] == "prospective_memory"
        assert audit["trust_tier"] == 2
        assert "prospective-memory" in audit["capability_tags"]


class TestForget:
    def test_forget_removes_intentions_derived_from_erased_evidence(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
            intention_id="forget-1",
        )
        engine.schedule_intention(intention)
        report = engine.forget(tid, eid, erasure_mode=ErasureMode.TOMBSTONE_RECOMPUTE)
        assert report["erased"] is True
        assert report["propagated"]["removed_intentions"] == ["forget-1"]
        assert engine.list_intentions(tid) == []

    def test_forget_removes_multi_source_intention_instead_of_trimming(
        self, engine, tenant_user_agent
    ):
        tid, uid, aid = tenant_user_agent
        first_eid = _append_evidence(
            engine,
            tenant_id=tid,
            user_id=uid,
            agent_id=aid,
            content="First prospective source.",
        )
        second_eid = _append_evidence(
            engine,
            tenant_id=tid,
            user_id=uid,
            agent_id=aid,
            content="Second prospective source.",
        )
        due = _EVALUATED_AT - timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid,
            user_id=uid,
            agent_id=aid,
            evidence_id=first_eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
            intention_id="forget-multi-source",
        )
        intention.evidence_ids.append(second_eid)
        engine.schedule_intention(intention)

        report = engine.forget(
            tid, first_eid, erasure_mode=ErasureMode.TOMBSTONE_RECOMPUTE
        )

        assert report["propagated"]["removed_intentions"] == [
            "forget-multi-source"
        ]
        assert engine.list_intentions(tid) == []

    def test_fired_receipt_and_audit_survive_intention_forget(
        self, engine, tenant_user_agent
    ):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid,
            user_id=uid,
            agent_id=aid,
            evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
            intention_id="forget-fired-receipt",
        )
        engine.schedule_intention(intention)
        engine.evaluate_due_intentions(
            tid,
            evaluated_at=_EVALUATED_AT,
            trigger_context=_ctx(),
            operating_point=_OP,
        )
        expected_event_id = content_cid(
            "fire_intention",
            {"tenant_id": tid, "intention_id": intention.intention_id, "op": "fire"},
        )

        engine.forget(tid, eid, erasure_mode=ErasureMode.TOMBSTONE_RECOMPUTE)

        assert engine.list_intentions(tid) == []
        with engine.connect() as conn:
            with conn.cursor() as cur:
                engine._set_tenant(cur, _stable_uuid("tenant", tid))
                cur.execute(
                    """
                    SELECT canonical_event_id
                    FROM intention_firing_receipts_v2
                    WHERE tenant_id = %s AND intention_id = %s
                    """,
                    (_stable_uuid("tenant", tid), intention.intention_id),
                )
                assert cur.fetchall() == [(expected_event_id,)]
        fire_audits = [
            item
            for item in engine.export_tenant(tid)["audit_log"]
            if item["op"] == "fire_intention"
            and item["target_id"] == intention.intention_id
        ]
        assert [item["id"] for item in fire_audits] == [expected_event_id]

        replacement_eid = _append_evidence(
            engine,
            tenant_id=tid,
            user_id=uid,
            agent_id=aid,
            content="Replacement evidence must not reuse a fired intention id.",
        )
        replacement = _make_intention(
            tenant_id=tid,
            user_id=uid,
            agent_id=aid,
            evidence_id=replacement_eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
            intention_id=intention.intention_id,
        )
        with pytest.raises(ValueError, match="already has a durable firing receipt"):
            engine.schedule_intention(replacement)

    def test_firing_receipts_reject_update_and_delete(
        self, engine, tenant_user_agent
    ):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=1)
        intention = _make_intention(
            tenant_id=tid,
            user_id=uid,
            agent_id=aid,
            evidence_id=eid,
            trigger_type="exact_time",
            trigger_expression={"at": due.isoformat()},
            due_at=due,
            intention_id="immutable-receipt",
        )
        engine.schedule_intention(intention)
        engine.evaluate_due_intentions(
            tid,
            evaluated_at=_EVALUATED_AT,
            trigger_context=_ctx(),
            operating_point=_OP,
        )
        db_tenant_id = _stable_uuid("tenant", tid)

        for statement in (
            "UPDATE intention_firing_receipts_v2 SET canonical_event_id = 'changed' "
            "WHERE tenant_id = %s AND intention_id = %s",
            "DELETE FROM intention_firing_receipts_v2 "
            "WHERE tenant_id = %s AND intention_id = %s",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with engine.connect() as conn:
                    with conn.cursor() as cur:
                        engine._set_tenant(cur, db_tenant_id)
                        cur.execute(statement, (db_tenant_id, intention.intention_id))


class TestFiringOrder:
    def test_firing_order_is_due_at_then_intention_id(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        eid = _append_evidence(engine, tenant_id=tid, user_id=uid, agent_id=aid)
        due = _EVALUATED_AT - timedelta(minutes=2)
        for iid in ["intention-b", "intention-a", "intention-c"]:
            intention = _make_intention(
                tenant_id=tid, user_id=uid, agent_id=aid, evidence_id=eid,
                trigger_type="exact_time",
                trigger_expression={"at": (due if iid != "intention-c" else _EVALUATED_AT - timedelta(minutes=1)).isoformat()},
                due_at=due if iid != "intention-c" else _EVALUATED_AT - timedelta(minutes=1),
                intention_id=iid,
            )
            engine.schedule_intention(intention)
        fired = engine.evaluate_due_intentions(tid, evaluated_at=_EVALUATED_AT, trigger_context=_ctx(), operating_point=_OP)
        assert [f.intention_id for f in fired] == ["intention-a", "intention-b", "intention-c"]


class TestNaiveClock:
    def test_naive_evaluated_at_raises(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        with pytest.raises(ValueError, match="evaluated_at must be timezone-aware"):
            engine.evaluate_due_intentions(
                tid,
                evaluated_at=_EVALUATED_AT.replace(tzinfo=None),
                trigger_context=_ctx(),
                operating_point=_OP,
            )
