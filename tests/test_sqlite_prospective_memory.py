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
from mnemosyne.engine import Evidence, Intention, LocalMemoryEngine
from mnemosyne.policy import OperatingPolicy
from mnemosyne.privacy import ErasureMode
from mnemosyne.sqlite_engine import SqliteEngine


TENANT_ID = "tenant-prospective"
USER_ID = "user-prospective"
AGENT_ID = "agent-prospective"
EVALUATED_AT = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)


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
        )
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


def test_due_exact_time_intention_fires_once_with_provenance_and_audit(
    tmp_path: Path,
) -> None:
    engine = SqliteEngine(tmp_path / "root")
    evidence_id = _originating_episode(engine)
    intention = _intention(
        evidence_id=evidence_id, due_at=EVALUATED_AT - timedelta(minutes=1)
    )

    engine.schedule_intention(intention)
    first_firings = engine.evaluate_due_intentions(TENANT_ID, evaluated_at=EVALUATED_AT)
    replay_firings = engine.evaluate_due_intentions(
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


def test_fire_audit_byte_matches_local_oracle(tmp_path: Path) -> None:
    """The SQLite fire audit record is byte-identical to Local's for the same
    inputs (deterministic id, at, diff, actor, source, trust_tier, tags)."""
    local = LocalMemoryEngine()
    leid = _originating_episode(local)
    li = _intention(evidence_id=leid, due_at=EVALUATED_AT)
    local.schedule_intention(li)
    local.evaluate_due_intentions(TENANT_ID, evaluated_at=EVALUATED_AT)
    laudit = next(r for r in local.audit_log if r["op"] == "fire_intention")

    engine = SqliteEngine(tmp_path / "root")
    seid = _originating_episode(engine)
    si = _intention(evidence_id=seid, due_at=EVALUATED_AT)
    engine.schedule_intention(si)
    engine.evaluate_due_intentions(TENANT_ID, evaluated_at=EVALUATED_AT)
    saudit = next(r for r in _audit_log(engine) if r["op"] == "fire_intention")

    assert saudit == laudit


def test_future_exact_time_intention_does_not_fire(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "root")
    evidence_id = _originating_episode(engine)
    intention = _intention(
        evidence_id=evidence_id, due_at=EVALUATED_AT + timedelta(minutes=1)
    )

    engine.schedule_intention(intention)

    assert engine.evaluate_due_intentions(TENANT_ID, evaluated_at=EVALUATED_AT) == []
    assert engine.list_intentions(TENANT_ID)[0].status == "scheduled"


def test_cancelled_intention_never_fires(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "root")
    evidence_id = _originating_episode(engine)
    intention = _intention(
        evidence_id=evidence_id, due_at=EVALUATED_AT - timedelta(minutes=1)
    )

    engine.schedule_intention(intention)
    engine.cancel_intention(TENANT_ID, intention.intention_id, cancelled_by=USER_ID)

    assert engine.evaluate_due_intentions(TENANT_ID, evaluated_at=EVALUATED_AT) == []
    stored = engine.list_intentions(TENANT_ID)[0]
    assert stored.status == "cancelled"
    assert stored.cancellation_state is not None


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"intention_id": 7}, "intention_id must be a non-empty string"),
        ({"tenant_id": ""}, "tenant_id must be a non-empty string"),
        ({"trigger_type": "event"}, "supports only exact_time"),
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
            {"dependencies": ["future-intention"]},
            "does not support dependency triggers",
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

    fired = engine.evaluate_due_intentions(TENANT_ID, evaluated_at=EVALUATED_AT)

    assert [item.intention_id for item in fired] == [intention.intention_id]
    assert fired[0].due_at == EVALUATED_AT

    with pytest.raises(ValueError, match="evaluated_at must be timezone-aware"):
        engine.evaluate_due_intentions(
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
        engine.evaluate_due_intentions("other-tenant", evaluated_at=EVALUATED_AT) == []
    )
    with pytest.raises(KeyError):
        engine.cancel_intention(
            "other-tenant",
            intention.intention_id,
            cancelled_by=USER_ID,
        )
    with pytest.raises(PermissionError, match="owning user or agent"):
        engine.cancel_intention(
            TENANT_ID,
            intention.intention_id,
            cancelled_by="other-user",
        )

    engine.cancel_intention(
        TENANT_ID,
        intention.intention_id,
        cancelled_by=AGENT_ID,
    )
    engine.cancel_intention(
        TENANT_ID,
        intention.intention_id,
        cancelled_by=AGENT_ID,
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
    assert engine.evaluate_due_intentions(TENANT_ID, evaluated_at=EVALUATED_AT) == []


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
        engine.evaluate_due_intentions(TENANT_ID, evaluated_at=EVALUATED_AT)

    assert engine.list_intentions(TENANT_ID)[0].status == "scheduled"
    assert not any(row["op"] == "fire_intention" for row in _audit_log(engine))


def test_evaluation_validates_clock_without_stored_intentions(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "root")

    with pytest.raises(ValueError, match="evaluated_at must be timezone-aware"):
        engine.evaluate_due_intentions(
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
        engine.evaluate_due_intentions(TENANT_ID, evaluated_at=EVALUATED_AT)

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
        engine.evaluate_due_intentions(TENANT_ID, evaluated_at=EVALUATED_AT)
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
    engine.evaluate_due_intentions(TENANT_ID, evaluated_at=EVALUATED_AT)
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
        return engine.evaluate_due_intentions(TENANT_ID, evaluated_at=EVALUATED_AT)

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

    fired = engine.evaluate_due_intentions(TENANT_ID, evaluated_at=EVALUATED_AT)
    fired[0].status = "scheduled"
    fired[0].action.clear()
    listed[0].status = "scheduled"

    stored = engine.list_intentions(TENANT_ID)[0]
    assert stored.status == "fired"
    assert stored.action["message"] == "Submit the report."
    assert engine.evaluate_due_intentions(TENANT_ID, evaluated_at=EVALUATED_AT) == []


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
    engine.evaluate_due_intentions(TENANT_ID, evaluated_at=EVALUATED_AT)

    with pytest.raises(ValueError, match="fired intention cannot be cancelled"):
        engine.cancel_intention(
            TENANT_ID, intention.intention_id, cancelled_by=USER_ID
        )


def test_persistence_survives_reopen(tmp_path: Path) -> None:
    root = tmp_path / "root"
    engine = SqliteEngine(root)
    evidence_id = _originating_episode(engine)
    intention = _intention(evidence_id=evidence_id, due_at=EVALUATED_AT)
    engine.schedule_intention(intention)
    engine.evaluate_due_intentions(TENANT_ID, evaluated_at=EVALUATED_AT)
    engine.close()

    reopened = SqliteEngine(root)
    stored = reopened.list_intentions(TENANT_ID)
    assert len(stored) == 1
    assert stored[0].status == "fired"
    assert stored[0].evidence_ids == [evidence_id]
    # Re-evaluation after reopen is a no-op (idempotent replay).
    assert reopened.evaluate_due_intentions(TENANT_ID, evaluated_at=EVALUATED_AT) == []
    audits = [
        row for row in _audit_log(reopened) if row["op"] == "fire_intention"
    ]
    assert len(audits) == 1
