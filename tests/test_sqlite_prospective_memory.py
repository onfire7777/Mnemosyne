"""SqliteEngine prospective-memory parity (Phase 2, Task B).

Mirrors ``tests/test_prospective_memory.py``'s Phase-1 exact_time contract
against ``SqliteEngine``, asserting byte-identical audit records and the same
deterministic / idempotent / fail-closed / tenant-scoped behavior as the
frozen ``LocalMemoryEngine`` oracle. The originating episode is written via
``SqliteEngine.append_evidence`` (the real ledger path) so the evidence rows,
cids, and provenance are exercise the actual SQLite store.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

from mnemosyne.audit_chain import (
    build_audit_chain,
    local_hmac_provider,
    verify_audit_chain,
)
from mnemosyne.engine import (
    Evidence,
    Intention,
    LocalMemoryEngine,
    ProspectiveOperatingPoint,
    TriggerEvaluationContext,
)
from mnemosyne.policy import OperatingPolicy
from mnemosyne.privacy import ErasureMode
from mnemosyne.sqlite_engine import SqliteEngine


TENANT_ID = "tenant-prospective"
USER_ID = "user-prospective"
AGENT_ID = "agent-prospective"
EVALUATED_AT = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
OPERATING_POINT = ProspectiveOperatingPoint(
    operating_point_id="sqlite-test-op",
    threshold=0.8,
    measured_precision=0.95,
    measured_recall=0.9,
    measurement_cid="sqlite-test-measurement",
)


def _context(tenant_id: str = TENANT_ID) -> TriggerEvaluationContext:
    return TriggerEvaluationContext(
        infrastructure_available=True,
        tenant_id=tenant_id,
        events=[],
        conditions={},
    )


def _evaluate(
    engine: SqliteEngine | LocalMemoryEngine,
    tenant_id: str,
    *,
    evaluated_at: datetime,
) -> list[Intention]:
    return engine.evaluate_due_intentions(
        tenant_id,
        evaluated_at=evaluated_at,
        trigger_context=_context(tenant_id),
        operating_point=OPERATING_POINT,
    )


def _audit_log(engine: SqliteEngine, tenant_id: str = TENANT_ID) -> list[dict[str, Any]]:
    """Read the per-tenant audit log the way export_tenant does."""
    return engine.export_tenant(tenant_id)["audit_log"]


def _originating_episode(
    engine: SqliteEngine | LocalMemoryEngine,
    *,
    tenant_id: str = TENANT_ID,
    user_id: str = USER_ID,
    agent_id: str = AGENT_ID,
    trust_tier: int = 2,
    capability_tags: list[str] | None = None,
    branch: str = "main",
) -> str:
    return engine.append_evidence(
        Evidence(
            tenant_id=tenant_id,
            user_id=user_id,
            actor=agent_id,
            source_type="episode",
            source_identity="conversation:prospective-memory-contract",
            content="Remind me to submit the report.",
            trust_tier=trust_tier,
            capability_tags=capability_tags or ["prospective-memory"],
            access_policy={"tenant": tenant_id},
        ),
        branch=branch,
    )


def _intention(*, evidence_id: str, due_at: datetime, **overrides: Any) -> Intention:
    values: dict[str, Any] = {
        "intention_id": "intention-submit-report",
        "tenant_id": TENANT_ID,
        "user_id": USER_ID,
        "agent_id": AGENT_ID,
        "trigger_type": "exact_time",
        "trigger_expression": {"at": due_at.isoformat()},
        "action": {"type": "remind", "message": "Submit the report."},
        "status": "scheduled",
        "priority": "normal",
        "due_at": due_at,
        "dependencies": [],
        "reschedule_history": [],
        "cancellation_state": None,
        "evidence_ids": [evidence_id],
    }
    values.update(overrides)
    return Intention(**values)


def test_sqlite_update_intention_matches_local_and_persists_session(tmp_path: Path) -> None:
    sqlite = SqliteEngine(tmp_path / "sqlite")
    local = LocalMemoryEngine()
    for engine in (sqlite, local):
        evidence_id = _originating_episode(engine)
        engine.schedule_intention(_intention(
            evidence_id=evidence_id, due_at=EVALUATED_AT + timedelta(hours=1),
            session_id="session-a",
        ))
        engine.update_intention(
            TENANT_ID, "intention-submit-report", user_id=USER_ID, agent_id=AGENT_ID,
            session_id="session-a", due_at=EVALUATED_AT + timedelta(hours=2),
            action={"type": "remind", "message": "Updated."},
        )
    assert sqlite.list_intentions(TENANT_ID) == local.list_intentions(TENANT_ID)
    sqlite_update = next(row for row in _audit_log(sqlite) if row["op"] == "update_intention")
    local_update = next(row for row in local.audit_log if row["op"] == "update_intention")
    assert sqlite_update["diff"] == local_update["diff"]
    assert sqlite_update["trust_tier"] == local_update["trust_tier"]
    assert sqlite_update["capability_tags"] == local_update["capability_tags"]


def test_sqlite_recurrence_and_update_replay_match_local(tmp_path: Path) -> None:
    engines = [SqliteEngine(tmp_path / "sqlite-recurrence"), LocalMemoryEngine()]
    for engine in engines:
        evidence_id = _originating_episode(engine)
        due = EVALUATED_AT
        engine.schedule_intention(_intention(
            evidence_id=evidence_id, due_at=due, session_id="session-a",
            recurrence_policy={"type": "interval", "interval_seconds": 60, "max_occurrences": 2},
        ))
        for index in range(2):
            assert len(_evaluate(engine, TENANT_ID, evaluated_at=due + timedelta(minutes=index))) == 1
        terminal = engine.list_intentions(TENANT_ID)[0]
        assert terminal.status == "fired"
        assert terminal.recurrence_state["occurrence"] == 1

    for engine in engines:
        evidence_id = _originating_episode(
            engine, tenant_id="tenant-replay", user_id=USER_ID, agent_id=AGENT_ID
        )
        due = EVALUATED_AT + timedelta(hours=1)
        engine.schedule_intention(_intention(
            evidence_id=evidence_id, due_at=due, tenant_id="tenant-replay",
            intention_id="replay", session_id="session-a",
        ))
        engine.update_intention(
            "tenant-replay", "replay", user_id=USER_ID, agent_id=AGENT_ID,
            session_id="session-a", action={"type": "remind", "message": "Same."},
        )
        before = len(engine.audit_log) if isinstance(engine, LocalMemoryEngine) else len(
            _audit_log(engine, "tenant-replay")
        )
        engine.update_intention(
            "tenant-replay", "replay", user_id=USER_ID, agent_id=AGENT_ID,
            session_id="session-a", action={"type": "remind", "message": "Same."},
        )
        after = len(engine.audit_log) if isinstance(engine, LocalMemoryEngine) else len(
            _audit_log(engine, "tenant-replay")
        )
        assert after == before


def test_sqlite_recurring_fire_keeps_due_at_column_in_sync(tmp_path: Path) -> None:
    from mnemosyne.models import dt_to_json

    engine = SqliteEngine(tmp_path / "due-column")
    evidence_id = _originating_episode(engine)
    due = EVALUATED_AT
    engine.schedule_intention(_intention(
        evidence_id=evidence_id, due_at=due, session_id="session-a",
        recurrence_policy={"type": "interval", "interval_seconds": 3600},
    ))
    assert len(_evaluate(engine, TENANT_ID, evaluated_at=due)) == 1
    stored = engine.list_intentions(TENANT_ID)[0]
    assert stored.due_at == due + timedelta(seconds=3600)
    row = engine._connect(TENANT_ID).execute(
        "SELECT due_at FROM intentions WHERE tenant_id = ? AND intention_id = ?",
        (TENANT_ID, stored.intention_id),
    ).fetchone()
    assert row["due_at"] == dt_to_json(stored.due_at)
    engine.close()


def test_sqlite_legacy_sessionless_update_binds_persists_and_rejects_rebinding(
    tmp_path: Path,
) -> None:
    root = tmp_path / "legacy-session"
    engine = SqliteEngine(root)
    evidence_id = _originating_episode(engine)
    due = EVALUATED_AT + timedelta(hours=1)
    engine.schedule_intention(_intention(evidence_id=evidence_id, due_at=due))
    bound = engine.update_intention(
        TENANT_ID,
        "intention-submit-report",
        user_id=USER_ID,
        agent_id=AGENT_ID,
        session_id="session-a",
        action={"type": "remind", "message": "Bound."},
    )
    assert bound.session_id == "session-a"
    engine.close()

    reopened = SqliteEngine(root)
    before = reopened.list_intentions(TENANT_ID)[0]
    audit_before = list(_audit_log(reopened))
    assert before.session_id == "session-a"
    with pytest.raises(PermissionError, match="session"):
        reopened.update_intention(
            TENANT_ID,
            before.intention_id,
            user_id=USER_ID,
            agent_id=AGENT_ID,
            session_id="session-b",
            action={"type": "remind", "message": "Denied."},
        )
    assert reopened.list_intentions(TENANT_ID)[0] == before
    assert _audit_log(reopened) == audit_before
    reopened.close()


def test_sqlite_recurring_event_watermark_survives_reload(tmp_path: Path) -> None:
    root = tmp_path / "recurrence-watermark"
    due = EVALUATED_AT
    engine = SqliteEngine(root)
    evidence_id = _originating_episode(engine)
    engine.schedule_intention(_intention(
        evidence_id=evidence_id, due_at=due, trigger_type="event",
        trigger_expression={"event_type": "report.submitted", "match": {}},
        recurrence_policy={"type": "interval", "interval_seconds": 60},
    ))

    def context(event_id: str, occurred_at: datetime) -> TriggerEvaluationContext:
        return TriggerEvaluationContext(
            infrastructure_available=True, tenant_id=TENANT_ID,
            events=[{"event_id": event_id, "event_type": "report.submitted",
                     "occurred_at": occurred_at.isoformat(), "payload": {},
                     "confidence": 0.99, "tenant_id": TENANT_ID}], conditions={},
        )

    first = due + timedelta(minutes=1)
    assert len(engine.evaluate_due_intentions(
        TENANT_ID, evaluated_at=first, trigger_context=context("event-1", first),
        operating_point=OPERATING_POINT,
    )) == 1
    engine.close()
    reopened = SqliteEngine(root)
    state = reopened.list_intentions(TENANT_ID)[0].recurrence_state
    assert state["consumed_signal"] == {"event_id": "event-1", "occurred_at": first.isoformat()}
    assert "consumed_signals" not in state
    second = due + timedelta(minutes=2)
    assert reopened.evaluate_due_intentions(
        TENANT_ID, evaluated_at=second, trigger_context=context("event-1", first),
        operating_point=OPERATING_POINT,
    ) == []
    assert len(reopened.evaluate_due_intentions(
        TENANT_ID, evaluated_at=second + timedelta(seconds=1),
        trigger_context=context("event-2", second), operating_point=OPERATING_POINT,
    )) == 1
    reopened.close()


def test_sqlite_legacy_sessionless_cancel_binds_persists_and_stays_session_bound(
    tmp_path: Path,
) -> None:
    root = tmp_path / "legacy-cancel-session"
    engine = SqliteEngine(root)
    evidence_id = _originating_episode(engine)
    intention = _intention(
        evidence_id=evidence_id, due_at=EVALUATED_AT + timedelta(hours=1)
    )
    engine.schedule_intention(intention)
    engine.cancel_intention(
        TENANT_ID,
        intention.intention_id,
        cancelled_by=USER_ID,
        session_id="session-a",
    )
    assert len([row for row in _audit_log(engine) if row["op"] == "cancel_intention"]) == 1
    engine.close()

    reopened = SqliteEngine(root)
    before = reopened.list_intentions(TENANT_ID)[0]
    audit_before = list(_audit_log(reopened))
    assert before.status == "cancelled"
    assert before.session_id == "session-a"
    with pytest.raises(PermissionError, match="session"):
        reopened.cancel_intention(
            TENANT_ID,
            intention.intention_id,
            cancelled_by=USER_ID,
            session_id="session-b",
        )
    reopened.cancel_intention(
        TENANT_ID,
        intention.intention_id,
        cancelled_by=USER_ID,
        session_id="session-a",
    )
    assert reopened.list_intentions(TENANT_ID)[0] == before
    assert _audit_log(reopened) == audit_before
    reopened.close()


def test_due_exact_time_intention_fires_once_with_provenance_and_audit(
    tmp_path: Path,
) -> None:
    engine = SqliteEngine(tmp_path / "root")
    evidence_id = _originating_episode(engine)
    intention = _intention(
        evidence_id=evidence_id, due_at=EVALUATED_AT - timedelta(minutes=1)
    )

    engine.schedule_intention(intention)
    first_firings = _evaluate(engine, TENANT_ID, evaluated_at=EVALUATED_AT)
    replay_firings = _evaluate(engine,
        TENANT_ID, evaluated_at=EVALUATED_AT
    )

    assert [firing.intention_id for firing in first_firings] == [intention.intention_id]
    assert replay_firings == []
    stored = engine.list_intentions(TENANT_ID)
    assert len(stored) == 1
    assert stored[0].status == "fired"
    assert stored[0].evidence_ids == [evidence_id]
    firing_audits = [
        entry
        for entry in _audit_log(engine)
        if entry["op"] == "fire_intention"
        and entry["target_id"] == intention.intention_id
    ]
    assert len(firing_audits) == 1
    assert firing_audits[0]["tenant_id"] == TENANT_ID
    assert firing_audits[0]["diff"]["evidence_ids"] == [evidence_id]


def test_sqlite_intention_provenance_uses_main_branch_only(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "root")
    engine.branch("scratch", tenant_id=TENANT_ID)
    scratch_cid = _originating_episode(
        engine,
        capability_tags=["data-only", "no-write-authority"],
        branch="scratch",
    )
    main_cid = _originating_episode(engine, branch="main")
    assert scratch_cid == main_cid

    engine.schedule_intention(_intention(evidence_id=main_cid, due_at=EVALUATED_AT))


def test_fire_audit_byte_matches_local_oracle(tmp_path: Path) -> None:
    """The SQLite fire audit record is byte-identical to Local's for the same
    inputs (deterministic id, at, diff, actor, source, trust_tier, tags)."""
    local = LocalMemoryEngine()
    leid = _originating_episode(local)
    li = _intention(evidence_id=leid, due_at=EVALUATED_AT)
    local.schedule_intention(li)
    _evaluate(local, TENANT_ID, evaluated_at=EVALUATED_AT)
    laudit = next(r for r in local.audit_log if r["op"] == "fire_intention")

    engine = SqliteEngine(tmp_path / "root")
    seid = _originating_episode(engine)
    si = _intention(evidence_id=seid, due_at=EVALUATED_AT)
    engine.schedule_intention(si)
    _evaluate(engine, TENANT_ID, evaluated_at=EVALUATED_AT)
    saudit = next(r for r in _audit_log(engine) if r["op"] == "fire_intention")

    assert saudit == laudit


def test_future_exact_time_intention_does_not_fire(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "root")
    evidence_id = _originating_episode(engine)
    intention = _intention(
        evidence_id=evidence_id, due_at=EVALUATED_AT + timedelta(minutes=1)
    )

    engine.schedule_intention(intention)

    assert _evaluate(engine, TENANT_ID, evaluated_at=EVALUATED_AT) == []
    assert engine.list_intentions(TENANT_ID)[0].status == "scheduled"


def test_cancelled_intention_never_fires(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "root")
    evidence_id = _originating_episode(engine)
    intention = _intention(
        evidence_id=evidence_id, due_at=EVALUATED_AT - timedelta(minutes=1)
    )

    engine.schedule_intention(intention)
    engine.cancel_intention(TENANT_ID, intention.intention_id, cancelled_by=USER_ID, session_id="session-a")

    assert _evaluate(engine, TENANT_ID, evaluated_at=EVALUATED_AT) == []
    stored = engine.list_intentions(TENANT_ID)[0]
    assert stored.status == "cancelled"
    assert stored.cancellation_state is not None


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"intention_id": 7}, "intention_id must be a non-empty string"),
        ({"tenant_id": ""}, "tenant_id must be a non-empty string"),
        ({"trigger_type": "event"}, "trigger_expression.event_type"),
        ({"trigger_expression": {}}, "trigger_expression.at"),
        ({"trigger_expression": {"at": "not-a-time"}}, "must be ISO-8601"),
        (
            {
                "trigger_expression": {
                    "at": (EVALUATED_AT + timedelta(days=1)).isoformat()
                }
            },
            "same instant as due_at",
        ),
        ({"action": {"payload": object()}}, "must contain JSON data only"),
        (
            {
                "trigger_type": "dependency_completion",
                "trigger_expression": {"require": "all"},
            },
            "requires non-empty dependencies",
        ),
        (
            {"cancellation_state": {"cancelled_by": USER_ID}},
            "cannot have cancellation state",
        ),
        ({"evidence_ids": []}, "must contain originating evidence"),
    ],
)
def test_intention_rejects_invalid_phase_one_state(
    overrides: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _intention(evidence_id="evidence", due_at=EVALUATED_AT, **overrides)


def test_intention_rejects_naive_clocks_and_evaluator_accepts_equal_offset_time(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="due_at must be timezone-aware"):
        _intention(
            evidence_id="evidence",
            due_at=EVALUATED_AT.replace(tzinfo=None),
        )

    engine = SqliteEngine(tmp_path / "root")
    evidence_id = _originating_episode(engine)
    offset_due = EVALUATED_AT.astimezone(timezone(timedelta(hours=-7)))
    intention = _intention(evidence_id=evidence_id, due_at=offset_due)
    engine.schedule_intention(intention)

    fired = _evaluate(engine, TENANT_ID, evaluated_at=EVALUATED_AT)

    assert [item.intention_id for item in fired] == [intention.intention_id]
    assert fired[0].due_at == EVALUATED_AT

    with pytest.raises(ValueError, match="evaluated_at must be timezone-aware"):
        _evaluate(engine,
            TENANT_ID,
            evaluated_at=EVALUATED_AT.replace(tzinfo=None),
        )


def test_intention_from_dict_rejects_malformed_persisted_containers_and_owner() -> None:
    row = _intention(
        evidence_id="evidence",
        due_at=EVALUATED_AT,
    ).to_dict()
    row["evidence_ids"] = "evidence"
    with pytest.raises(ValueError, match="evidence_ids must be a list"):
        Intention.from_dict(row)

    row = _intention(
        evidence_id="evidence",
        due_at=EVALUATED_AT,
    ).to_dict()
    row["status"] = "cancelled"
    row["cancellation_state"] = {"cancelled_by": "other-user"}
    with pytest.raises(ValueError, match="owning user or agent"):
        Intention.from_dict(row)


@pytest.mark.parametrize(
    "case",
    ["missing", "erased", "foreign_tenant", "wrong_user", "over_ceiling", "tainted"],
)
def test_schedule_rejects_invalid_provenance_without_mutation(
    tmp_path: Path, case: str
) -> None:
    policy = OperatingPolicy(max_trust_tier=1) if case == "over_ceiling" else None
    engine = SqliteEngine(tmp_path / "root", policy=policy)
    if case == "missing":
        evidence_id = "missing-evidence"
    elif case == "foreign_tenant":
        evidence_id = _originating_episode(engine, tenant_id="other-tenant")
    elif case == "wrong_user":
        evidence_id = _originating_episode(engine)
    elif case == "tainted":
        evidence_id = _originating_episode(
            engine,
            capability_tags=["data-only", "no-write-authority"],
        )
    else:
        evidence_id = _originating_episode(engine, trust_tier=2)
        if case == "erased":
            engine.forget(TENANT_ID, evidence_id)

    overrides: dict[str, Any] = {}
    if case == "wrong_user":
        overrides["user_id"] = "other-user"
    intention = _intention(
        evidence_id=evidence_id,
        due_at=EVALUATED_AT,
        **overrides,
    )
    audit_count = len(_audit_log(engine))

    error = PermissionError if case in {"over_ceiling", "tainted"} else ValueError
    with pytest.raises(error):
        engine.schedule_intention(intention)

    assert engine.list_intentions(TENANT_ID) == []
    assert len(_audit_log(engine)) == audit_count


def test_intention_tenant_scope_and_cancellation_ownership(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "root")
    evidence_id = _originating_episode(engine)
    intention = _intention(evidence_id=evidence_id, due_at=EVALUATED_AT)
    engine.schedule_intention(intention)

    assert engine.list_intentions("other-tenant") == []
    assert (
        _evaluate(engine,"other-tenant", evaluated_at=EVALUATED_AT) == []
    )
    with pytest.raises(KeyError):
        engine.cancel_intention(
            "other-tenant",
            intention.intention_id,
            cancelled_by=USER_ID, session_id="session-a",
        )
    with pytest.raises(PermissionError, match="owning user or agent"):
        engine.cancel_intention(
            TENANT_ID,
            intention.intention_id,
            cancelled_by="other-user", session_id="session-a",
        )

    engine.cancel_intention(
        TENANT_ID,
        intention.intention_id,
        cancelled_by=AGENT_ID, session_id="session-a",
    )
    engine.cancel_intention(
        TENANT_ID,
        intention.intention_id,
        cancelled_by=AGENT_ID, session_id="session-a",
    )

    cancellation_audits = [
        row
        for row in _audit_log(engine)
        if row["op"] == "cancel_intention"
        and row["target_id"] == intention.intention_id
    ]
    assert len(cancellation_audits) == 1
    assert cancellation_audits[0]["actor"] == AGENT_ID
    assert cancellation_audits[0]["trust_tier"] == 2
    assert cancellation_audits[0]["capability_tags"] == ["prospective-memory"]
    assert cancellation_audits[0]["diff"]["intention_digest"]


@pytest.mark.parametrize(
    ("erasure_mode", "requested_by"),
    [
        (ErasureMode.TOMBSTONE_RECOMPUTE, "user"),
        (ErasureMode.HARD_DELETE_LEGAL, "legal"),
    ],
)
def test_forget_removes_intentions_derived_from_erased_evidence(
    tmp_path: Path, erasure_mode: ErasureMode, requested_by: str
) -> None:
    engine = SqliteEngine(tmp_path / "root")
    evidence_id = _originating_episode(engine)
    intention = _intention(evidence_id=evidence_id, due_at=EVALUATED_AT)
    engine.schedule_intention(intention)

    report = engine.forget(
        TENANT_ID,
        evidence_id,
        requested_by=requested_by,
        erasure_mode=erasure_mode,
    )

    assert report["erased"] is True
    assert report["propagated"]["removed_intentions"] == [intention.intention_id]
    assert engine.list_intentions(TENANT_ID) == []
    assert _evaluate(engine, TENANT_ID, evaluated_at=EVALUATED_AT) == []


def test_evaluation_fails_closed_if_provenance_becomes_invalid(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "root")
    evidence_id = _originating_episode(engine)
    intention = _intention(evidence_id=evidence_id, due_at=EVALUATED_AT)
    engine.schedule_intention(intention)
    # Mark the evidence erased via SQL WITHOUT going through forget (which would
    # cascade-remove the intention). This leaves the intention row in place but
    # invalidates its provenance, so the evaluator must fail closed before
    # firing — matching Local's ``evidence.erased = True`` direct mutation.
    conn = engine._connect(TENANT_ID)
    with conn:
        conn.execute(
            "UPDATE evidence SET erased = 1, content = '' "
            "WHERE tenant_id = ? AND cid = ?",
            (TENANT_ID, evidence_id),
        )

    with pytest.raises(ValueError, match="missing or outside"):
        _evaluate(engine, TENANT_ID, evaluated_at=EVALUATED_AT)

    assert engine.list_intentions(TENANT_ID)[0].status == "scheduled"
    assert not any(row["op"] == "fire_intention" for row in _audit_log(engine))


def test_evaluation_validates_clock_without_stored_intentions(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "root")

    with pytest.raises(ValueError, match="evaluated_at must be timezone-aware"):
        _evaluate(engine,
            TENANT_ID,
            evaluated_at=EVALUATED_AT.replace(tzinfo=None),
        )


def test_evaluation_prevalidates_all_due_provenance_before_firing(
    tmp_path: Path,
) -> None:
    engine = SqliteEngine(tmp_path / "root")
    valid_evidence_id = _originating_episode(
        engine,
        agent_id="agent-valid",
    )
    invalid_evidence_id = _originating_episode(
        engine,
        agent_id="agent-invalid",
    )
    valid = _intention(
        evidence_id=valid_evidence_id,
        due_at=EVALUATED_AT,
        intention_id="intention-a-valid",
        agent_id="agent-valid",
    )
    invalid = _intention(
        evidence_id=invalid_evidence_id,
        due_at=EVALUATED_AT,
        intention_id="intention-b-invalid",
        agent_id="agent-invalid",
    )
    engine.schedule_intention(valid)
    engine.schedule_intention(invalid)
    # Mark the invalid intention's evidence erased via SQL WITHOUT going through
    # forget (which would cascade-remove the intention). This leaves both
    # intention rows scheduled but invalidates one's provenance, so the
    # evaluator's prevalidation loop must abort the whole batch before firing.
    conn = engine._connect(TENANT_ID)
    with conn:
        conn.execute(
            "UPDATE evidence SET erased = 1, content = '' "
            "WHERE tenant_id = ? AND cid = ?",
            (TENANT_ID, invalid_evidence_id),
        )

    with pytest.raises(ValueError, match="missing or outside"):
        _evaluate(engine, TENANT_ID, evaluated_at=EVALUATED_AT)

    assert [item.status for item in engine.list_intentions(TENANT_ID)] == [
        "scheduled",
        "scheduled",
    ]
    assert not any(row["op"] == "fire_intention" for row in _audit_log(engine))


def test_audit_custody_is_complete_deterministic_and_hash_chain_compatible(
    tmp_path: Path,
) -> None:
    def _fire_audit_from_fresh_engine(root: Path) -> dict[str, Any]:
        engine = SqliteEngine(root)
        evidence_id = _originating_episode(engine)
        intention = _intention(evidence_id=evidence_id, due_at=EVALUATED_AT)
        engine.schedule_intention(intention)
        _evaluate(engine, TENANT_ID, evaluated_at=EVALUATED_AT)
        return next(row for row in _audit_log(engine) if row["op"] == "fire_intention")

    first = _fire_audit_from_fresh_engine(tmp_path / "root-a")
    second = _fire_audit_from_fresh_engine(tmp_path / "root-b")

    assert first == second
    assert first["actor"] == AGENT_ID
    assert first["source"] == "prospective_memory"
    assert first["trust_tier"] == 2
    assert first["capability_tags"] == ["prospective-memory"]
    assert first["at"] == EVALUATED_AT.isoformat()
    assert first["diff"]["evaluated_at"] == EVALUATED_AT.isoformat()
    assert first["diff"]["trigger_type"] == "exact_time"
    assert first["diff"]["due_at"] == EVALUATED_AT.isoformat()
    assert first["diff"]["intention_digest"]

    # Hash-chain compatibility: the audit entries round-trip through the
    # shared chain builder/verifier exactly like Local's do.
    engine = SqliteEngine(tmp_path / "root-chain")
    evidence_id = _originating_episode(engine)
    intention = _intention(evidence_id=evidence_id, due_at=EVALUATED_AT)
    engine.schedule_intention(intention)
    _evaluate(engine, TENANT_ID, evaluated_at=EVALUATED_AT)
    entries = _audit_log(engine)
    provider = local_hmac_provider("prospective-memory-test")
    document = build_audit_chain(
        entries,
        tenant_id=TENANT_ID,
        provider_name="local-hmac",
        hmac_provider=provider,
    )
    verification = verify_audit_chain(
        document,
        entries,
        tenant_id=TENANT_ID,
        hmac_provider=provider,
    )
    assert verification["verified"] is True


def test_concurrent_evaluation_fires_each_intention_once_in_stable_order(
    tmp_path: Path,
) -> None:
    engine = SqliteEngine(tmp_path / "root")
    evidence_id = _originating_episode(engine)
    intentions = [
        _intention(
            evidence_id=evidence_id,
            due_at=EVALUATED_AT - timedelta(minutes=2),
            intention_id="intention-b",
        ),
        _intention(
            evidence_id=evidence_id,
            due_at=EVALUATED_AT - timedelta(minutes=2),
            intention_id="intention-a",
        ),
        _intention(
            evidence_id=evidence_id,
            due_at=EVALUATED_AT - timedelta(minutes=1),
            intention_id="intention-c",
        ),
    ]
    for intention in intentions:
        engine.schedule_intention(intention)
    barrier = Barrier(2)

    def evaluate() -> list[Intention]:
        barrier.wait()
        return _evaluate(engine, TENANT_ID, evaluated_at=EVALUATED_AT)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: evaluate(), range(2)))

    nonempty = [result for result in results if result]
    assert len(nonempty) == 1
    assert [item.intention_id for item in nonempty[0]] == [
        "intention-a",
        "intention-b",
        "intention-c",
    ]
    firing_audits = [row for row in _audit_log(engine) if row["op"] == "fire_intention"]
    assert len(firing_audits) == 3
    assert len({row["id"] for row in firing_audits}) == 3


def test_intention_values_are_isolated_from_caller_mutation(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "root")
    evidence_id = _originating_episode(engine)
    intention = _intention(evidence_id=evidence_id, due_at=EVALUATED_AT)
    engine.schedule_intention(intention)

    intention.action["message"] = "changed by caller"
    intention.evidence_ids.clear()
    listed = engine.list_intentions(TENANT_ID)
    assert listed[0].action["message"] == "Submit the report."
    assert listed[0].evidence_ids == [evidence_id]

    fired = _evaluate(engine, TENANT_ID, evaluated_at=EVALUATED_AT)
    fired[0].status = "scheduled"
    fired[0].action.clear()
    listed[0].status = "scheduled"

    stored = engine.list_intentions(TENANT_ID)[0]
    assert stored.status == "fired"
    assert stored.action["message"] == "Submit the report."
    assert _evaluate(engine, TENANT_ID, evaluated_at=EVALUATED_AT) == []


def test_duplicate_schedule_raises_without_mutation_or_audit(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "root")
    evidence_id = _originating_episode(engine)
    intention = _intention(evidence_id=evidence_id, due_at=EVALUATED_AT)
    engine.schedule_intention(intention)
    audit_count = len(_audit_log(engine))

    with pytest.raises(ValueError, match="already exists"):
        engine.schedule_intention(intention)

    assert len(engine.list_intentions(TENANT_ID)) == 1
    assert len(_audit_log(engine)) == audit_count


def test_cancel_fired_intention_raises(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "root")
    evidence_id = _originating_episode(engine)
    intention = _intention(evidence_id=evidence_id, due_at=EVALUATED_AT)
    engine.schedule_intention(intention)
    _evaluate(engine, TENANT_ID, evaluated_at=EVALUATED_AT)

    with pytest.raises(ValueError, match="fired intention cannot be cancelled"):
        engine.cancel_intention(
            TENANT_ID, intention.intention_id, cancelled_by=USER_ID, session_id="session-a"
        )


def test_persistence_survives_reopen(tmp_path: Path) -> None:
    root = tmp_path / "root"
    engine = SqliteEngine(root)
    evidence_id = _originating_episode(engine)
    intention = _intention(evidence_id=evidence_id, due_at=EVALUATED_AT)
    engine.schedule_intention(intention)
    _evaluate(engine, TENANT_ID, evaluated_at=EVALUATED_AT)
    engine.close()

    reopened = SqliteEngine(root)
    stored = reopened.list_intentions(TENANT_ID)
    assert len(stored) == 1
    assert stored[0].status == "fired"
    assert stored[0].evidence_ids == [evidence_id]
    # Re-evaluation after reopen is a no-op (idempotent replay).
    assert _evaluate(reopened, TENANT_ID, evaluated_at=EVALUATED_AT) == []
    audits = [
        row for row in _audit_log(reopened) if row["op"] == "fire_intention"
    ]
    assert len(audits) == 1


def test_all_five_canonical_trigger_types_fire_with_sqlite_parity(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "root")
    evidence_id = _originating_episode(engine)
    due_at = EVALUATED_AT - timedelta(minutes=5)
    prerequisite = _intention(
        evidence_id=evidence_id,
        due_at=due_at,
        intention_id="intention-prerequisite",
    )
    intentions = [
        prerequisite,
        _intention(
            evidence_id=evidence_id,
            due_at=due_at,
            intention_id="intention-window",
            trigger_type="time_window",
            trigger_expression={
                "start": due_at.isoformat(),
                "end": (EVALUATED_AT + timedelta(minutes=1)).isoformat(),
            },
        ),
        _intention(
            evidence_id=evidence_id,
            due_at=due_at,
            intention_id="intention-event",
            trigger_type="event",
            trigger_expression={
                "event_type": "report.submitted",
                "match": {"report_id": "r-1"},
            },
        ),
        _intention(
            evidence_id=evidence_id,
            due_at=due_at,
            intention_id="intention-condition",
            trigger_type="condition",
            trigger_expression={
                "condition_id": "report-ready",
                "operator": "eq",
                "value": True,
            },
        ),
        _intention(
            evidence_id=evidence_id,
            due_at=EVALUATED_AT,
            intention_id="intention-dependent",
            trigger_type="dependency_completion",
            trigger_expression={"require": "all"},
            dependencies=["intention-prerequisite"],
        ),
    ]
    for intention in intentions:
        engine.schedule_intention(intention)

    context = TriggerEvaluationContext(
        infrastructure_available=True,
        tenant_id=TENANT_ID,
        events=[
            {
                "event_id": "event-report-1",
                "event_type": "report.submitted",
                "occurred_at": (EVALUATED_AT - timedelta(minutes=1)).isoformat(),
                "payload": {"report_id": "r-1", "pages": 3},
                "confidence": 0.99,
                "tenant_id": TENANT_ID,
            }
        ],
        conditions={
            "report-ready": {
                "value": True,
                "observed_at": (EVALUATED_AT - timedelta(minutes=1)).isoformat(),
                "confidence": 0.99,
                "tenant_id": TENANT_ID,
            }
        },
    )
    first = engine.evaluate_due_intentions(
        TENANT_ID,
        evaluated_at=EVALUATED_AT,
        trigger_context=context,
        operating_point=OPERATING_POINT,
    )
    assert [item.intention_id for item in first] == [
        "intention-condition",
        "intention-event",
        "intention-prerequisite",
        "intention-window",
    ]
    second = engine.evaluate_due_intentions(
        TENANT_ID,
        evaluated_at=EVALUATED_AT,
        trigger_context=context,
        operating_point=OPERATING_POINT,
    )
    assert [item.intention_id for item in second] == ["intention-dependent"]
    assert all(item.status == "fired" for item in engine.list_intentions(TENANT_ID))


def test_separate_sqlite_connections_create_one_fire_receipt(tmp_path: Path) -> None:
    root = tmp_path / "root"
    engine_a = SqliteEngine(root)
    engine_b = SqliteEngine(root)
    evidence_id = _originating_episode(engine_a)
    intention = _intention(evidence_id=evidence_id, due_at=EVALUATED_AT)
    engine_a.schedule_intention(intention)
    barrier = Barrier(2)

    def evaluate(engine: SqliteEngine) -> list[Intention]:
        barrier.wait()
        return _evaluate(engine, TENANT_ID, evaluated_at=EVALUATED_AT)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(evaluate, (engine_a, engine_b)))

    assert sum(bool(result) for result in results) == 1
    conn = engine_a._connect(TENANT_ID)
    receipt_count = conn.execute(
        "SELECT COUNT(*) FROM intention_fire_receipts WHERE tenant_id = ?",
        (TENANT_ID,),
    ).fetchone()[0]
    assert receipt_count == 1
    fire_audits = [row for row in _audit_log(engine_a) if row["op"] == "fire_intention"]
    assert len(fire_audits) == 1
    assert fire_audits[0]["id"] == conn.execute(
        "SELECT event_id FROM intention_fire_receipts WHERE tenant_id = ?",
        (TENANT_ID,),
    ).fetchone()[0]


def test_separate_connection_cancel_and_fire_have_one_winner(tmp_path: Path) -> None:
    root = tmp_path / "root"
    engine_a = SqliteEngine(root)
    engine_b = SqliteEngine(root)
    evidence_id = _originating_episode(engine_a)
    intention = _intention(evidence_id=evidence_id, due_at=EVALUATED_AT)
    engine_a.schedule_intention(intention)
    barrier = Barrier(2)

    def fire() -> tuple[str, Any]:
        barrier.wait()
        try:
            return ("fire", _evaluate(engine_a, TENANT_ID, evaluated_at=EVALUATED_AT))
        except Exception as exc:  # pragma: no cover - records unexpected race failure
            return ("fire-error", exc)

    def cancel() -> tuple[str, Any]:
        barrier.wait()
        try:
            engine_b.cancel_intention(
                TENANT_ID, intention.intention_id, cancelled_by=USER_ID, session_id="session-a"
            )
            return ("cancel", None)
        except Exception as exc:
            return ("cancel-error", exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        fire_result, cancel_result = executor.map(lambda fn: fn(), (fire, cancel))

    assert fire_result[0] == "fire"
    assert cancel_result[0] in {"cancel", "cancel-error"}
    stored = engine_a.list_intentions(TENANT_ID)[0]
    assert stored.status in {"fired", "cancelled"}
    if stored.status == "fired":
        assert cancel_result[0] == "cancel-error"
        assert isinstance(cancel_result[1], ValueError)
    else:
        assert cancel_result[0] == "cancel"
        assert fire_result[1] == []
    operations = [row["op"] for row in _audit_log(engine_a)]
    assert operations.count("fire_intention") + operations.count("cancel_intention") == 1


@pytest.mark.parametrize("terminal_operation", ["fire", "cancel"])
def test_separate_connection_update_and_terminal_transition_have_one_winner(
    tmp_path: Path, terminal_operation: str
) -> None:
    root = tmp_path / "root"
    engine_a = SqliteEngine(root)
    engine_b = SqliteEngine(root)
    evidence_id = _originating_episode(engine_a)
    intention = _intention(evidence_id=evidence_id, due_at=EVALUATED_AT)
    engine_a.schedule_intention(intention)
    barrier = Barrier(2)

    def update() -> tuple[str, Any]:
        barrier.wait()
        try:
            updated = engine_a.update_intention(
                TENANT_ID,
                intention.intention_id,
                user_id=USER_ID,
                agent_id=AGENT_ID,
                session_id="session-a",
                due_at=EVALUATED_AT + timedelta(hours=1),
            )
            return ("update", updated)
        except Exception as exc:
            return ("update-error", exc)

    def terminate() -> tuple[str, Any]:
        barrier.wait()
        try:
            if terminal_operation == "fire":
                return (
                    "fire",
                    _evaluate(engine_b, TENANT_ID, evaluated_at=EVALUATED_AT),
                )
            engine_b.cancel_intention(
                TENANT_ID,
                intention.intention_id,
                cancelled_by=USER_ID,
                session_id="session-a",
            )
            return ("cancel", None)
        except Exception as exc:
            return (f"{terminal_operation}-error", exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        update_result, terminal_result = executor.map(lambda fn: fn(), (update, terminate))

    stored = engine_a.list_intentions(TENANT_ID)[0]
    if terminal_operation == "cancel":
        assert terminal_result == ("cancel", None)
        assert stored.status == "cancelled"
        assert update_result[0] in {"update", "update-error"}
        if update_result[0] == "update-error":
            assert isinstance(update_result[1], ValueError)
    elif update_result[0] == "update":
        assert stored.status == "scheduled"
        assert stored.due_at == EVALUATED_AT + timedelta(hours=1)
        if terminal_operation == "fire":
            assert terminal_result == ("fire", [])
    else:
        assert isinstance(update_result[1], ValueError)
        assert stored.status == ("fired" if terminal_operation == "fire" else "cancelled")
    operations = [row["op"] for row in _audit_log(engine_a)]
    assert operations.count(f"{terminal_operation}_intention") == (
        1 if terminal_operation == "cancel" or stored.status == "fired" else 0
    )
    assert operations.count("update_intention") == (1 if update_result[0] == "update" else 0)


def test_fire_transaction_rolls_back_status_audit_and_receipt(tmp_path: Path, monkeypatch):
    engine = SqliteEngine(tmp_path / "root")
    evidence_id = _originating_episode(engine)
    intention = _intention(evidence_id=evidence_id, due_at=EVALUATED_AT)
    engine.schedule_intention(intention)
    audit_count = len(_audit_log(engine))

    def fail_audit(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(engine, "_audit_row", fail_audit)
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        _evaluate(engine, TENANT_ID, evaluated_at=EVALUATED_AT)

    assert engine.list_intentions(TENANT_ID)[0].status == "scheduled"
    assert len(_audit_log(engine)) == audit_count
    assert engine._connect(TENANT_ID).execute(
        "SELECT COUNT(*) FROM intention_fire_receipts"
    ).fetchone()[0] == 0


def test_update_transaction_rolls_back_state_history_audit_and_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = SqliteEngine(tmp_path / "update-rollback")
    evidence_id = _originating_episode(engine)
    due = EVALUATED_AT + timedelta(hours=1)
    intention = _intention(
        evidence_id=evidence_id, due_at=due, session_id="session-a"
    )
    engine.schedule_intention(intention)
    before = engine.list_intentions(TENANT_ID)[0]
    audit_before = list(_audit_log(engine))
    moved = due + timedelta(hours=1)
    original_audit = engine._audit_row

    def fail_audit(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("synthetic update audit failure")

    monkeypatch.setattr(engine, "_audit_row", fail_audit)
    with pytest.raises(RuntimeError, match="synthetic update audit failure"):
        engine.update_intention(
            TENANT_ID,
            intention.intention_id,
            user_id=USER_ID,
            agent_id=AGENT_ID,
            session_id="session-a",
            due_at=moved,
        )
    assert engine.list_intentions(TENANT_ID)[0] == before
    assert _audit_log(engine) == audit_before

    monkeypatch.setattr(engine, "_audit_row", original_audit)
    retried = engine.update_intention(
        TENANT_ID,
        intention.intention_id,
        user_id=USER_ID,
        agent_id=AGENT_ID,
        session_id="session-a",
        due_at=moved,
    )
    assert retried.due_at == moved
    assert len(retried.reschedule_history) == 1
    assert len(_audit_log(engine)) == len(audit_before) + 1
