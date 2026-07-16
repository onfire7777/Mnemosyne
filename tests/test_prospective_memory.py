from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mnemosyne.engine import Evidence, Intention, LocalMemoryEngine


TENANT_ID = "tenant-prospective"
USER_ID = "user-prospective"
AGENT_ID = "agent-prospective"
EVALUATED_AT = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)


def _originating_episode(engine: LocalMemoryEngine) -> str:
    return engine.append_evidence(
        Evidence(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            actor=AGENT_ID,
            source_type="episode",
            source_identity="conversation:prospective-memory-contract",
            content="Remind me to submit the report.",
            trust_tier=2,
            capability_tags=["prospective-memory"],
            access_policy={"tenant": TENANT_ID},
        )
    )


def _intention(*, evidence_id: str, due_at: datetime) -> Intention:
    return Intention(
        intention_id="intention-submit-report",
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        agent_id=AGENT_ID,
        trigger_type="exact_time",
        trigger_expression={"at": due_at.isoformat()},
        action={"type": "remind", "message": "Submit the report."},
        status="scheduled",
        priority="normal",
        due_at=due_at,
        dependencies=[],
        reschedule_history=[],
        cancellation_state=None,
        evidence_ids=[evidence_id],
    )


def test_due_exact_time_intention_fires_once_with_provenance_and_audit() -> None:
    engine = LocalMemoryEngine()
    evidence_id = _originating_episode(engine)
    intention = _intention(evidence_id=evidence_id, due_at=EVALUATED_AT - timedelta(minutes=1))

    engine.schedule_intention(intention)
    first_firings = engine.evaluate_due_intentions(TENANT_ID, evaluated_at=EVALUATED_AT)
    replay_firings = engine.evaluate_due_intentions(TENANT_ID, evaluated_at=EVALUATED_AT)

    assert [firing.intention_id for firing in first_firings] == [intention.intention_id]
    assert replay_firings == []
    stored = engine.list_intentions(TENANT_ID)
    assert len(stored) == 1
    assert stored[0].status == "fired"
    assert stored[0].evidence_ids == [evidence_id]
    firing_audits = [
        entry
        for entry in engine.audit_log
        if entry["op"] == "fire_intention" and entry["target_id"] == intention.intention_id
    ]
    assert len(firing_audits) == 1
    assert firing_audits[0]["tenant_id"] == TENANT_ID
    assert firing_audits[0]["diff"]["evidence_ids"] == [evidence_id]


def test_future_exact_time_intention_does_not_fire() -> None:
    engine = LocalMemoryEngine()
    evidence_id = _originating_episode(engine)
    intention = _intention(evidence_id=evidence_id, due_at=EVALUATED_AT + timedelta(minutes=1))

    engine.schedule_intention(intention)

    assert engine.evaluate_due_intentions(TENANT_ID, evaluated_at=EVALUATED_AT) == []
    assert engine.list_intentions(TENANT_ID)[0].status == "scheduled"


def test_cancelled_intention_never_fires() -> None:
    engine = LocalMemoryEngine()
    evidence_id = _originating_episode(engine)
    intention = _intention(evidence_id=evidence_id, due_at=EVALUATED_AT - timedelta(minutes=1))

    engine.schedule_intention(intention)
    engine.cancel_intention(TENANT_ID, intention.intention_id, cancelled_by=USER_ID)

    assert engine.evaluate_due_intentions(TENANT_ID, evaluated_at=EVALUATED_AT) == []
    stored = engine.list_intentions(TENANT_ID)[0]
    assert stored.status == "cancelled"
    assert stored.cancellation_state is not None
