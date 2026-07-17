"""PostgreSQL prospective-memory tests (W3 Phase 2).

These tests exercise the PostgreSQL intention persistence, RLS, and evaluator
against a live database, covering all five trigger types, provenance fail-closed
paths, cancellation ownership, tenant isolation, idempotent firing, and the
audit/provenance invariants from the frozen contract.

The Local Intention dataclass (Phase 1) only validates exact_time in
__post_init__, so non-exact_time intentions are constructed via a bypass helper
that sets fields directly without triggering Phase 1 validation. The PostgreSQL
backend's _validate_intention_for_pg performs the full Phase 2 validation.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pytest

from mnemosyne.engine import Intention
from mnemosyne.models import Evidence
from mnemosyne.postgres_engine import (
    PostgresEngine,
    ProspectiveOperatingPoint,
    TriggerEvaluationContext,
)
from mnemosyne.privacy import ErasureMode

pytest.importorskip("psycopg")

_DSN = os.environ.get("MNEMOSYNE_POSTGRES_DSN", "postgresql://admin@localhost:5432/mnemosyne_pm_test_1784305188")
_EVALUATED_AT = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
_OP = ProspectiveOperatingPoint(
    operating_point_id="op-test",
    threshold=0.5,
    measured_precision=0.9,
    measured_recall=0.85,
    measurement_cid="cidv1:test-measurement",
)


def _ctx(infra: bool = True, events=None, conditions=None) -> TriggerEvaluationContext:
    return TriggerEvaluationContext(
        infrastructure_available=infra,
        events=events or [],
        conditions=conditions or {},
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
) -> Intention:
    """Construct an Intention bypassing Phase 1 exact_time-only validation.

    The Local Intention.__post_init__ rejects non-exact_time triggers (Phase 1
    limitation). Phase 2 needs all five types, so we bypass __post_init__ and
    set fields directly. The PostgreSQL backend validates via
    _validate_intention_for_pg.
    """

    obj = object.__new__(Intention)
    obj.intention_id = intention_id or f"intention-{uuid4().hex[:12]}"
    obj.tenant_id = tenant_id
    obj.user_id = user_id
    obj.agent_id = agent_id
    obj.trigger_type = trigger_type
    obj.trigger_expression = dict(trigger_expression)
    obj.action = action or {"type": "remind", "message": "Submit the report."}
    obj.due_at = due_at.astimezone(UTC)
    obj.status = "scheduled"
    obj.priority = "normal"
    obj.dependencies = list(dependencies or [])
    obj.reschedule_history = []
    obj.cancellation_state = None
    obj.evidence_ids = [evidence_id]
    return obj


def _append_evidence(engine: PostgresEngine, *, tenant_id: str, user_id: str, agent_id: str, trust_tier: int = 2, capability_tags=None) -> str:
    return engine.append_evidence(
        Evidence(
            tenant_id=tenant_id,
            user_id=user_id,
            actor="assistant",
            source_type="episode",
            source_identity=f"conversation:prospective-memory-pg:{agent_id}",
            content="Remind me to submit the report.",
            trust_tier=trust_tier,
            capability_tags=capability_tags or ["prospective-memory"],
            access_policy={"tenant": tenant_id},
        )
    )


@pytest.fixture
def engine():
    eng = PostgresEngine(_DSN, require_safe_role=False)
    yield eng
    eng.close_connections()


@pytest.fixture
def tenant_user_agent():
    tid = f"tenant-pm-{uuid4().hex[:8]}"
    uid = f"user-pm-{uuid4().hex[:8]}"
    aid = f"agent-pm-{uuid4().hex[:8]}"
    return tid, uid, aid


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
        engine.forget(tid, eid, erasure_mode=ErasureMode.TOMBSTONE_RECOMPUTE)
        # The intention is removed by forget (parity with Local), so there
        # are no candidates to evaluate and no firing occurs.
        assert engine.list_intentions(tid) == []
        assert engine.evaluate_due_intentions(tid, evaluated_at=_EVALUATED_AT, trigger_context=_ctx(), operating_point=_OP) == []


class TestCancel:
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
        engine.cancel_intention(tid, intention.intention_id, cancelled_by=uid)
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
        engine.cancel_intention(tid, intention.intention_id, cancelled_by=aid)
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
            engine.cancel_intention(tid, intention.intention_id, cancelled_by="other-user")

    def test_cancel_missing_raises_keyerror(self, engine, tenant_user_agent):
        tid, uid, aid = tenant_user_agent
        with pytest.raises(KeyError):
            engine.cancel_intention(tid, "nonexistent", cancelled_by=uid)

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
            engine.cancel_intention(tid, intention.intention_id, cancelled_by=uid)

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
        engine.cancel_intention(tid, intention.intention_id, cancelled_by=uid)
        engine.cancel_intention(tid, intention.intention_id, cancelled_by=uid)
        assert engine.list_intentions(tid)[0].status == "cancelled"


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
        assert engine.evaluate_due_intentions("other-tenant", evaluated_at=_EVALUATED_AT, trigger_context=_ctx(), operating_point=_OP) == []

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
            engine.cancel_intention("other-tenant", intention.intention_id, cancelled_by=uid)


class TestIdempotency:
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
        assert engine.evaluate_due_intentions(tid, evaluated_at=_EVALUATED_AT, trigger_context=_ctx(), operating_point=_OP) == []

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


class TestInfrastructureGate:
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
        assert audit["source"] == "prospective_memory"
        assert audit["diff"]["trigger_type"] == "exact_time"
        assert audit["diff"]["status"] == "fired"
        assert audit["diff"]["evidence_ids"] == [eid]
        assert audit["diff"]["intention_digest"]
        assert audit["diff"]["evaluated_at"] == _EVALUATED_AT.isoformat()
        assert audit["diff"]["canonical_event_id"]
        assert audit["diff"]["operating_point_id"] == "op-test"

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
