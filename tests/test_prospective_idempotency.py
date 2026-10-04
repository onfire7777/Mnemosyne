"""Creation retries are durable, scoped, and cannot repeat a state transition."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from uuid import uuid4

import pytest

from mnemosyne.engine import (
    Intention,
    LocalMemoryEngine,
    ProspectiveOperatingPoint,
    TriggerEvaluationContext,
)
from mnemosyne.mcp_tools import MemoryTools
from mnemosyne.models import Evidence
from mnemosyne.security import SessionIdentity
from mnemosyne.sqlite_engine import SqliteEngine


@pytest.fixture(params=["local", "sqlite", "postgres"])
def setup(request, tmp_path):
    tenant = f"retry-{uuid4().hex}"
    if request.param == "postgres":
        dsn = os.environ.get("MNEMOSYNE_POSTGRES_DSN")
        if not dsn:
            pytest.skip("MNEMOSYNE_POSTGRES_DSN is not set")
        from mnemosyne.postgres_engine import PostgresEngine, _stable_uuid

        factory = partial(PostgresEngine, dsn, require_safe_role=False)
        close = PostgresEngine.close_connections
    elif request.param == "sqlite":
        factory = partial(SqliteEngine, tmp_path / "db")
        close = SqliteEngine.close
    else:
        factory = partial(LocalMemoryEngine, tmp_path / "store.json")
        close = LocalMemoryEngine.close
    engine = factory()
    identity = SessionIdentity(
        tenant_id=tenant,
        user_id="owner",
        agent_id="agent",
        role="agent",
        source_trust_tier=1,
        session_id="session",
    )
    cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id="owner",
            actor="user",
            source_type="episode",
            content="Call the customer",
            trust_tier=1,
            access_policy={"tenant": tenant},
        )
    )
    due = "2026-10-04T12:00:00+00:00"
    arguments = dict(
        tenant_id=tenant,
        user_id="owner",
        agent_id="agent",
        trigger_type="exact_time",
        trigger_expression={"at": due},
        action={"kind": "notify", "message": "Call"},
        due_at=due,
        evidence_ids=[cid],
        session_identity=identity,
        idempotency_key="creation-1",
    )
    state = dict(
        engine=engine, arguments=arguments, factory=factory, close=close, tenant=tenant
    )
    try:
        yield state
    finally:
        engine = state["engine"]
        if request.param == "postgres":
            with engine.connect() as conn:
                conn.execute(
                    "DELETE FROM tenants WHERE id = %s",
                    (_stable_uuid("tenant", tenant),),
                )
        close(engine)


def _schedule(state, **changes):
    return MemoryTools(state["engine"]).schedule_intention(
        **{**state["arguments"], **changes}
    )


def test_concurrent_retries_survive_reopening_without_duplicate_audit(setup):
    with ThreadPoolExecutor(max_workers=4) as pool:
        acknowledgements = list(pool.map(lambda _: _schedule(setup), range(8)))
    assert all(item == acknowledgements[0] for item in acknowledgements)
    before = setup["engine"].export_tenant(setup["tenant"])["audit_log"]
    assert len([row for row in before if row["op"] == "schedule_intention"]) == 1
    setup["close"](setup["engine"])
    setup["engine"] = setup["factory"]()
    assert _schedule(setup) == acknowledgements[0]
    assert setup["engine"].export_tenant(setup["tenant"])["audit_log"] == before
    assert len(setup["engine"].list_intentions(setup["tenant"])) == 1


@pytest.mark.parametrize("transition", ["update", "cancel", "fire"])
def test_retry_acknowledges_creation_without_reverting_later_state(setup, transition):
    original = _schedule(setup)
    engine, tenant = setup["engine"], setup["tenant"]
    if transition == "update":
        engine.update_intention(
            tenant,
            original["intention_id"],
            user_id="owner",
            agent_id="agent",
            session_id="session",
            action={"kind": "notify", "message": "Changed"},
        )
    elif transition == "cancel":
        engine.cancel_intention(
            tenant, original["intention_id"], cancelled_by="owner", session_id="session"
        )
    else:
        assert (
            len(
                engine.evaluate_due_intentions(
                    tenant,
                    evaluated_at=datetime(2026, 10, 4, 13, tzinfo=UTC),
                    trigger_context=TriggerEvaluationContext(
                        tenant_id=tenant,
                        infrastructure_available=True,
                        events=[],
                        conditions={},
                    ),
                    operating_point=ProspectiveOperatingPoint(
                        operating_point_id="test",
                        threshold=0.5,
                        measured_precision=0.9,
                        measured_recall=0.9,
                        measurement_cid="test-only",
                    ),
                )
            )
            == 1
        )
    before = engine.export_tenant(tenant)
    assert _schedule(setup) == original
    assert engine.export_tenant(tenant) == before


def test_key_conflict_is_nonmutating_and_session_scope_is_distinct(setup):
    first = _schedule(setup)
    before = setup["engine"].export_tenant(setup["tenant"])
    with pytest.raises(ValueError, match="idempotency conflict"):
        _schedule(setup, action={"kind": "notify", "message": "Different request"})
    assert setup["engine"].export_tenant(setup["tenant"]) == before
    second = _schedule(
        setup,
        session_identity=replace(
            setup["arguments"]["session_identity"], session_id="other"
        ),
    )
    assert second["intention_id"] != first["intention_id"]


def test_retry_rechecks_authority_and_cannot_restore_erased_intention(setup):
    _schedule(setup)
    with pytest.raises(PermissionError):
        _schedule(
            setup,
            session_identity=replace(
                setup["arguments"]["session_identity"], role="reader"
            ),
        )
    setup["engine"].forget(setup["tenant"], setup["arguments"]["evidence_ids"][0])
    with pytest.raises((ValueError, KeyError)):
        _schedule(setup)
    assert setup["engine"].list_intentions(setup["tenant"]) == []


@pytest.mark.parametrize("key", ["", "space key", "x" * 129, "é", 123, True])
def test_invalid_key_does_not_create_an_intention(setup, key):
    with pytest.raises(ValueError, match="idempotency_key"):
        _schedule(setup, idempotency_key=key)
    assert setup["engine"].list_intentions(setup["tenant"]) == []


def test_no_key_preserves_distinct_creation_behavior(setup):
    assert (
        _schedule(setup, idempotency_key=None)["intention_id"]
        != _schedule(setup, idempotency_key=None)["intention_id"]
    )


@pytest.mark.parametrize("missing", ["intention", "receipt"])
def test_incomplete_creation_history_fails_closed(setup, missing):
    original = _schedule(setup)
    engine, tenant = setup["engine"], setup["tenant"]
    retry = partial(_schedule, setup)
    if isinstance(engine, LocalMemoryEngine):
        if missing == "intention":
            del engine.intentions[(tenant, original["intention_id"])]
        else:
            engine.audit_log = [
                row for row in engine.audit_log if row["op"] != "schedule_intention"
            ]
        engine._persist()
    elif isinstance(engine, SqliteEngine):
        conn = engine._connect(tenant)
        if missing == "intention":
            conn.execute("DELETE FROM intentions WHERE tenant_id = ?", (tenant,))
        else:
            conn.execute("DELETE FROM audit_log WHERE tenant_id = ?", (tenant,))
        conn.commit()
    else:
        from mnemosyne.postgres_engine import _stable_uuid

        with engine.connect() as conn:
            if missing == "intention":
                conn.execute(
                    "DELETE FROM intentions WHERE tenant_id = %s",
                    (_stable_uuid("tenant", tenant),),
                )
            else:
                # Audit rows are append-only. Model an orphaned import without
                # disabling that production protection or deleting history.
                orphan = Intention.from_dict(original)
                orphan.intention_id = str(uuid4())
                conn.execute(
                    "UPDATE intentions SET intention_id = %s WHERE tenant_id = %s",
                    (orphan.intention_id, _stable_uuid("tenant", tenant)),
                )
                retry = partial(engine.schedule_intention, orphan, idempotent=True)
    before = engine.export_tenant(tenant)
    with pytest.raises(ValueError, match="removed intention|missing creation receipt"):
        retry()
    assert engine.export_tenant(tenant) == before


def test_recurring_creation_retry_does_not_rewind_occurrence(setup):
    policy = {"type": "interval", "interval_seconds": 3600, "max_occurrences": 3}
    original = _schedule(setup, recurrence_policy=policy)
    engine, tenant = setup["engine"], setup["tenant"]
    engine.evaluate_due_intentions(
        tenant,
        evaluated_at=datetime(2026, 10, 4, 12, tzinfo=UTC),
        trigger_context=TriggerEvaluationContext(
            tenant_id=tenant, infrastructure_available=True, events=[], conditions={}
        ),
        operating_point=ProspectiveOperatingPoint(
            operating_point_id="test",
            threshold=0.5,
            measured_precision=0.9,
            measured_recall=0.9,
            measurement_cid="test-only",
        ),
    )
    before = engine.export_tenant(tenant)
    assert engine.list_intentions(tenant)[0].recurrence_state["occurrence"] == 1
    assert _schedule(setup, recurrence_policy=policy) == original
    assert engine.export_tenant(tenant) == before


def _update_arguments(state):
    original = _schedule(state)
    identity = state["arguments"]["session_identity"]
    tools = MemoryTools(state["engine"])
    assert (
        "revision"
        not in tools.list_intentions(state["tenant"], identity)["intentions"][0]
    )
    snapshot = tools.list_intentions(state["tenant"], identity, include_revision=True)[
        "intentions"
    ][0]
    return dict(
        tenant_id=state["tenant"],
        intention_id=original["intention_id"],
        user_id="owner",
        agent_id="agent",
        session_identity=identity,
        action={"kind": "notify", "message": "Revised"},
        expected_revision=snapshot["revision"],
        idempotency_key="update-1",
    )


def test_concurrent_update_retries_are_durable_and_audit_only_digests(setup):
    arguments = _update_arguments(setup)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda _: MemoryTools(setup["engine"]).update_intention(**arguments),
                range(8),
            )
        )
    assert all(item == results[0] for item in results)
    assert results[0]["revision"] != arguments["expected_revision"]
    before = setup["engine"].export_tenant(setup["tenant"])
    updates = [row for row in before["audit_log"] if row["op"] == "update_intention"]
    assert len(updates) == 1
    receipt = updates[0]["diff"]["update_request"]
    assert set(receipt) == {"key_digest", "request_digest", "result_revision"}
    assert all(len(value) == 64 for value in receipt.values())
    setup["close"](setup["engine"])
    setup["engine"] = setup["factory"]()
    assert MemoryTools(setup["engine"]).update_intention(**arguments) == results[0]
    assert setup["engine"].export_tenant(setup["tenant"]) == before


def test_concurrent_different_updates_cannot_both_use_stale_revision(setup):
    arguments = _update_arguments(setup)

    def attempt(number):
        try:
            return MemoryTools(setup["engine"]).update_intention(
                **{
                    **arguments,
                    "idempotency_key": f"update-{number}",
                    "action": {"kind": "notify", "message": f"Winner {number}"},
                }
            )
        except ValueError as error:
            assert "revision conflict" in str(error)
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(4)))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert (
        setup["engine"].list_intentions(setup["tenant"])[0].action
        == winners[0]["action"]
    )


@pytest.mark.parametrize("later", ["update", "cancel", "fire"])
def test_old_update_retry_returns_current_state_without_reapplying(setup, later):
    arguments = _update_arguments(setup)
    tools = MemoryTools(setup["engine"])
    tools.update_intention(**arguments)
    engine, tenant = setup["engine"], setup["tenant"]
    if later == "update":
        tools.update_intention(
            **{
                **arguments,
                "idempotency_key": None,
                "expected_revision": None,
                "action": {"kind": "notify", "message": "Later edit"},
            }
        )
    elif later == "cancel":
        engine.cancel_intention(
            tenant,
            arguments["intention_id"],
            cancelled_by="owner",
            session_id="session",
        )
    else:
        engine.evaluate_due_intentions(
            tenant,
            evaluated_at=datetime(2026, 10, 4, 13, tzinfo=UTC),
            trigger_context=TriggerEvaluationContext(
                tenant_id=tenant,
                infrastructure_available=True,
                events=[],
                conditions={},
            ),
            operating_point=ProspectiveOperatingPoint(
                operating_point_id="test",
                threshold=0.5,
                measured_precision=0.9,
                measured_recall=0.9,
                measurement_cid="test-only",
            ),
        )
    before = engine.export_tenant(tenant)
    expected = tools.list_intentions(
        tenant, arguments["session_identity"], include_revision=True
    )["intentions"][0]
    assert tools.update_intention(**arguments) == expected
    assert engine.export_tenant(tenant) == before
    with pytest.raises(ValueError, match="idempotency conflict"):
        tools.update_intention(
            **{**arguments, "action": {"kind": "notify", "message": "Forged retry"}}
        )
    with pytest.raises(PermissionError):
        tools.update_intention(
            **{
                **arguments,
                "session_identity": replace(
                    arguments["session_identity"], session_id="wrong"
                ),
            }
        )


def test_keyed_noop_gets_durable_receipt_and_rejects_repurposed_key(setup):
    arguments = _update_arguments(setup)
    arguments["action"] = setup["engine"].list_intentions(setup["tenant"])[0].action
    tools = MemoryTools(setup["engine"])
    result = tools.update_intention(**arguments)
    assert result["revision"] == arguments["expected_revision"]
    before = setup["engine"].export_tenant(setup["tenant"])
    assert (
        len([row for row in before["audit_log"] if row["op"] == "update_intention"])
        == 1
    )
    assert tools.update_intention(**arguments) == result
    with pytest.raises(ValueError, match="idempotency conflict"):
        tools.update_intention(
            **{**arguments, "action": {"kind": "notify", "message": "Changed"}}
        )
    assert setup["engine"].export_tenant(setup["tenant"]) == before


@pytest.mark.parametrize(
    "overrides",
    [
        {"expected_revision": None},
        {"idempotency_key": None},
        {"expected_revision": "invalid"},
        {"idempotency_key": "space key"},
    ],
)
def test_update_retry_requires_both_valid_key_and_revision(setup, overrides):
    arguments = _update_arguments(setup)
    before = setup["engine"].export_tenant(setup["tenant"])
    with pytest.raises(ValueError):
        MemoryTools(setup["engine"]).update_intention(**{**arguments, **overrides})
    assert setup["engine"].export_tenant(setup["tenant"]) == before


def test_failed_update_rolls_back_state_and_receipt_then_allows_retry(
    setup, monkeypatch
):
    arguments = _update_arguments(setup)
    engine, tenant = setup["engine"], setup["tenant"]
    before = engine.export_tenant(tenant)
    method = "_audit_row" if isinstance(engine, SqliteEngine) else "_audit"
    original = getattr(engine, method)

    def fail_after_audit(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected before commit")

    with monkeypatch.context() as patch:
        patch.setattr(engine, method, fail_after_audit)
        with pytest.raises(RuntimeError, match="injected before commit"):
            MemoryTools(engine).update_intention(**arguments)
    assert engine.export_tenant(tenant) == before
    result = MemoryTools(engine).update_intention(**arguments)
    assert result["action"] == arguments["action"]


def test_update_retry_rechecks_erased_provenance(setup):
    arguments = _update_arguments(setup)
    tools = MemoryTools(setup["engine"])
    tools.update_intention(**arguments)
    setup["engine"].forget(setup["tenant"], setup["arguments"]["evidence_ids"][0])
    with pytest.raises((KeyError, ValueError)):
        tools.update_intention(**arguments)
    assert setup["engine"].list_intentions(setup["tenant"]) == []
