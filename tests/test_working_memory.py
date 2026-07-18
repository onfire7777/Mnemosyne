from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

from mnemosyne.engine import Evidence, LocalMemoryEngine, WorkingMemoryItem
from mnemosyne.gate import Candidate, PromotionGate, RegressionCase
from mnemosyne.models import Assertion
from mnemosyne.security import is_write_tainted

CREATED_AT = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
EXPIRES_AT = CREATED_AT + timedelta(seconds=30)
TENANT = "tenant-working"
USER = "user-working"
SESSION = "session-working"
AGENT = "agent-working"


def _evidence(
    engine: LocalMemoryEngine,
    *,
    tenant_id: str = TENANT,
    user_id: str = USER,
    session_id: str | None = SESSION,
    content: str = "Current task evidence",
    capability_tags: list[str] | None = None,
    trust_tier: int = 2,
) -> str:
    return engine.append_evidence(
        Evidence(
            tenant_id=tenant_id,
            user_id=user_id,
            actor=AGENT,
            source_type="episode",
            source_identity="working-memory-test",
            session_id=session_id,
            content=content,
            trust_tier=trust_tier,
            capability_tags=capability_tags or ["working-memory"],
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
    content: str = "Finish the working-memory task.",
    task_id: str = "task-1",
    **overrides: Any,
) -> WorkingMemoryItem:
    values: dict[str, Any] = {
        "item_id": item_id,
        "tenant_id": tenant_id,
        "session_id": session_id,
        "user_id": user_id,
        "agent_id": AGENT,
        "kind": "active_goal",
        "task_id": task_id,
        "content": content,
        "created_at": created_at,
        "expires_at": expires_at,
        "evidence_ids": [evidence_id],
        "access_policy": {"tenant": tenant_id},
        "metadata": {"priority": "high"},
    }
    values.update(overrides)
    return WorkingMemoryItem(**values)


def _put(engine: LocalMemoryEngine, **kwargs: Any) -> WorkingMemoryItem:
    evidence_id = kwargs.pop("evidence_id", _evidence(engine))
    item = _item(evidence_id, **kwargs)
    assert engine.put_working(item) == item.item_id
    return item


def test_working_item_rejects_invalid_identity_clock_ttl_and_payload() -> None:
    invalid = [
        {"item_id": ""},
        {"tenant_id": ""},
        {"session_id": ""},
        {"user_id": ""},
        {"agent_id": ""},
        {"kind": "unsupported"},
        {"task_id": ""},
        {"content": ""},
        {"created_at": CREATED_AT.replace(tzinfo=None)},
        {"expires_at": EXPIRES_AT.replace(tzinfo=None)},
        {"expires_at": CREATED_AT},
        {"expires_at": CREATED_AT + timedelta(hours=24, microseconds=1)},
        {"metadata": {"bad": object()}},
        {"evidence_ids": []},
        {"evidence_ids": ["a", "a"]},
        {"evidence_ids": [7]},
    ]
    for overrides in invalid:
        with pytest.raises(ValueError):
            _item("evidence", **overrides)


def test_ttl_boundary_is_half_open_and_expiry_is_audited_once() -> None:
    engine = LocalMemoryEngine()
    item = _put(engine)

    assert engine.get_working(TENANT, SESSION, item.item_id, as_of=EXPIRES_AT - timedelta(microseconds=1)) is not None
    assert [row.item_id for row in engine.list_working(TENANT, SESSION, as_of=EXPIRES_AT - timedelta(microseconds=1))] == [item.item_id]
    assert engine.expire_working(TENANT, expired_at=EXPIRES_AT - timedelta(microseconds=1)) == []

    expired = engine.get_working(TENANT, SESSION, item.item_id, as_of=EXPIRES_AT)
    assert expired is None
    assert engine.list_working(TENANT, SESSION, as_of=EXPIRES_AT) == []
    transitioned = engine.expire_working(TENANT, expired_at=EXPIRES_AT)
    assert [row.item_id for row in transitioned] == [item.item_id]
    assert transitioned[0].status == "expired"
    assert transitioned[0].expired_at == EXPIRES_AT

    audits = [row for row in engine.audit_log if row["target_id"] == item.item_id]
    assert [row["op"] for row in audits] == ["put_working", "expire_working"]
    assert audits[0]["source"] == "working_memory"
    assert audits[0]["diff"]["status"] == "active"
    assert audits[1]["diff"]["session_id"] == SESSION
    assert audits[1]["diff"]["deadline"] == EXPIRES_AT.isoformat()
    assert audits[1]["diff"]["sweep"] == EXPIRES_AT.isoformat()
    assert audits[1]["diff"]["status"] == "expired"


def test_repeated_expiry_is_idempotent_and_clock_rollback_cannot_resurrect(tmp_path: Path) -> None:
    store = tmp_path / "working.json"
    engine = LocalMemoryEngine(store_path=store)
    item = _put(engine)
    assert engine.expire_working(TENANT, expired_at=EXPIRES_AT) == [item]
    assert engine.expire_working(TENANT, expired_at=EXPIRES_AT) == []
    assert engine.expire_working(TENANT, expired_at=EXPIRES_AT + timedelta(hours=1)) == []
    earlier = EXPIRES_AT - timedelta(seconds=1)
    assert engine.get_working(TENANT, SESSION, item.item_id, as_of=earlier) is None
    assert engine.list_working(TENANT, SESSION, as_of=earlier) == []
    assert engine.expire_working(TENANT, expired_at=earlier) == []

    reloaded = LocalMemoryEngine(store_path=store)
    assert reloaded.get_working(TENANT, SESSION, item.item_id, as_of=earlier) is None
    assert reloaded.expire_working(TENANT, expired_at=earlier) == []
    assert len([row for row in reloaded.audit_log if row["op"] == "expire_working"]) == 1


def test_expiry_prevalidates_batch_and_orders_by_deadline_then_session_then_id() -> None:
    engine = LocalMemoryEngine()
    evidence_a = _evidence(engine, content="A")
    evidence_b = _evidence(engine, content="B")
    evidence_c = _evidence(engine, content="C")
    _put(engine, evidence_id=evidence_b, item_id="b")
    _put(engine, evidence_id=evidence_a, item_id="a")
    _put(
        engine,
        evidence_id=evidence_c,
        item_id="c",
        expires_at=EXPIRES_AT + timedelta(seconds=1),
    )

    engine.evidence[engine._evidence_key(TENANT, "main", evidence_c)].erased = True
    with pytest.raises(ValueError):
        engine.expire_working(TENANT, expired_at=EXPIRES_AT + timedelta(seconds=1))
    assert all(item.status == "active" for item in engine.working_memory.values())
    assert not [row for row in engine.audit_log if row["op"] == "expire_working"]

    engine.evidence[engine._evidence_key(TENANT, "main", evidence_c)].erased = False
    assert [row.item_id for row in engine.expire_working(TENANT, expired_at=EXPIRES_AT + timedelta(seconds=1))] == ["a", "b", "c"]


def test_two_concurrent_expirers_remove_each_item_exactly_once() -> None:
    engine = LocalMemoryEngine()
    for item_id in ("a", "b", "c"):
        _put(engine, item_id=item_id)
    barrier = Barrier(2)

    def sweep() -> list[str]:
        barrier.wait()
        return [row.item_id for row in engine.expire_working(TENANT, expired_at=EXPIRES_AT)]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: sweep(), range(2)))
    assert sorted(results) == [[], ["a", "b", "c"]]
    assert len([row for row in engine.audit_log if row["op"] == "expire_working"]) == 3
    assert len({row["id"] for row in engine.audit_log if row["op"] == "expire_working"}) == 3


def test_concurrent_access_is_linearizable_at_expiry() -> None:
    engine = LocalMemoryEngine()
    item = _put(engine)
    barrier = Barrier(3)

    def get() -> WorkingMemoryItem | None:
        barrier.wait()
        return engine.get_working(TENANT, SESSION, item.item_id, as_of=EXPIRES_AT)

    def listing() -> list[WorkingMemoryItem]:
        barrier.wait()
        return engine.list_working(TENANT, SESSION, as_of=EXPIRES_AT)

    def sweep() -> list[WorkingMemoryItem]:
        barrier.wait()
        return engine.expire_working(TENANT, expired_at=EXPIRES_AT)

    with ThreadPoolExecutor(max_workers=3) as pool:
        get_result, list_result, expire_result = [future.result() for future in (pool.submit(get), pool.submit(listing), pool.submit(sweep))]
    assert get_result is None
    assert list_result == []
    assert [row.item_id for row in expire_result] == [item.item_id]
    assert engine.get_working(TENANT, SESSION, item.item_id, as_of=EXPIRES_AT - timedelta(seconds=1)) is None


def test_tenant_and_session_are_both_hard_scope_keys() -> None:
    engine = LocalMemoryEngine()
    a1 = _put(engine, item_id="same", session_id="s1", content="tenant A session 1")
    a2 = _put(engine, item_id="same", session_id="s2", content="tenant A session 2")
    b1 = _put(engine, item_id="same", tenant_id="tenant-b", session_id="s1", content="tenant B session 1", evidence_id=_evidence(engine, tenant_id="tenant-b"))

    assert engine.get_working(TENANT, "s1", "same", as_of=CREATED_AT).content == a1.content
    assert engine.get_working(TENANT, "s2", "same", as_of=CREATED_AT).content == a2.content
    assert engine.get_working("tenant-b", "s1", "same", as_of=CREATED_AT).content == b1.content
    assert engine.get_working(TENANT, "missing", "same", as_of=CREATED_AT) is None
    assert engine.expire_working(TENANT, session_id="missing", expired_at=EXPIRES_AT) == []
    assert engine.get_working(TENANT, "s1", "same", as_of=CREATED_AT).content != b1.content

    exported = engine.export_tenant(TENANT)
    assert "tenant B session 1" not in str(exported)
    assert all(row["tenant_id"] == TENANT for row in exported["working_memory"])


def test_same_session_label_does_not_bridge_users() -> None:
    engine = LocalMemoryEngine()
    first = _put(engine, item_id="first", user_id="user-a", content="user A")
    second = _put(engine, item_id="second", user_id="user-b", content="user B", evidence_id=_evidence(engine, user_id="user-b"))
    rows = engine.list_working(TENANT, SESSION, as_of=CREATED_AT)
    assert [(row.item_id, row.user_id) for row in rows] == [("first", "user-a"), ("second", "user-b")]
    assert engine.get_working(TENANT, SESSION, first.item_id, as_of=CREATED_AT).user_id == "user-a"
    assert engine.get_working(TENANT, SESSION, second.item_id, as_of=CREATED_AT).user_id == "user-b"


def test_working_values_are_isolated_from_caller_and_return_mutation() -> None:
    engine = LocalMemoryEngine()
    evidence_id = _evidence(engine)
    item = _item(evidence_id)
    original_metadata = copy.deepcopy(item.metadata)
    original_ids = list(item.evidence_ids)
    engine.put_working(item)
    item.metadata["priority"] = "mutated"
    item.evidence_ids.append("other")

    fetched = engine.get_working(TENANT, SESSION, item.item_id, as_of=CREATED_AT)
    assert fetched is not None
    fetched.metadata["priority"] = "mutated-return"
    fetched.evidence_ids.clear()
    listed = engine.list_working(TENANT, SESSION, as_of=CREATED_AT)[0]
    listed.metadata["priority"] = "mutated-list"
    assert engine.get_working(TENANT, SESSION, item.item_id, as_of=CREATED_AT).metadata == original_metadata
    assert engine.get_working(TENANT, SESSION, item.item_id, as_of=CREATED_AT).evidence_ids == original_ids


def test_put_and_expiry_never_auto_promote() -> None:
    engine = LocalMemoryEngine()
    before = (copy.deepcopy(engine.assertions), copy.deepcopy(engine.preferences), copy.deepcopy(engine.entities), copy.deepcopy(engine.relations))
    item = _put(engine)
    assert (engine.assertions, engine.preferences, engine.entities, engine.relations) == before
    assert engine.get_working(TENANT, SESSION, item.item_id, as_of=CREATED_AT) is not None
    engine.expire_working(TENANT, expired_at=EXPIRES_AT)
    assert (engine.assertions, engine.preferences, engine.entities, engine.relations) == before
    assert not [row for row in engine.audit_log if "promot" in row["op"]]


def test_explicit_promotion_gate_approval_preserves_working_item() -> None:
    engine = LocalMemoryEngine()
    evidence_id = _evidence(engine, content="The task evidence is grounded.")
    item = _put(engine, evidence_id=evidence_id, content="Transient working note")
    candidate = Candidate("candidate-working", "fact", "grounded task", "working promotion", "main", [evidence_id])
    gate = PromotionGate(
        engine,
        [RegressionCase("protected-working", "grounded", "grounded", "grounded", protected=True)],
    )

    def apply_candidate(target: LocalMemoryEngine, branch: str) -> None:
        target.upsert_assertion(
            Assertion(
                tenant_id=TENANT,
                user_id=USER,
                subject="task",
                predicate="state",
                object="grounded",
                branch=branch,
                source_evidence_cids=[evidence_id],
                status="active",
                access_policy={"tenant": TENANT},
            ),
            branch=branch,
        )

    result = gate.evaluate(
        TENANT,
        candidate,
        apply_candidate,
        pre_merge_check=lambda target, _branch: None
        if target.get_working(TENANT, SESSION, item.item_id, as_of=CREATED_AT) is not None
        else "working item missing",
    )
    assert result.promoted is True
    assert engine.get_working(TENANT, SESSION, item.item_id, as_of=CREATED_AT) is not None
    assert any(assertion.object == "grounded" for assertion in engine.assertions.values())


def test_promotion_regression_failure_does_not_mutate_working_or_durable_state() -> None:
    engine = LocalMemoryEngine()
    evidence_id = _evidence(engine)
    item = _put(engine, evidence_id=evidence_id)
    before = copy.deepcopy(engine.assertions)
    candidate = Candidate("candidate-denied", "fact", "protected", "working denial", "main", [evidence_id])
    gate = PromotionGate(
        engine,
        [RegressionCase("protected-working", "protected", "never-present", "missing", protected=True)],
    )
    result = gate.evaluate(
        TENANT,
        candidate,
        lambda target, branch: target.upsert_assertion(
            Assertion(
                tenant_id=TENANT,
                user_id=USER,
                subject="task",
                predicate="state",
                object="candidate",
                branch=branch,
                source_evidence_cids=[evidence_id],
                status="active",
                access_policy={"tenant": TENANT},
            ),
            branch=branch,
        ),
    )
    assert result.promoted is False
    assert result.protected_regressions == ["protected-working"]
    assert engine.assertions == before
    assert engine.get_working(TENANT, SESSION, item.item_id, as_of=CREATED_AT) is not None


def test_put_rejects_missing_foreign_erased_and_invalid_provenance() -> None:
    engine = LocalMemoryEngine()
    with pytest.raises(ValueError):
        engine.put_working(_item("missing"))

    foreign = _evidence(engine, tenant_id="tenant-foreign", user_id=USER)
    with pytest.raises(ValueError):
        engine.put_working(_item(foreign))

    wrong_user = _evidence(engine, user_id="other-user")
    with pytest.raises(ValueError):
        engine.put_working(_item(wrong_user))

    wrong_session = _evidence(engine, session_id="other-session")
    with pytest.raises(ValueError):
        engine.put_working(_item(wrong_session))

    erased = _evidence(engine)
    engine.evidence[engine._evidence_key(TENANT, "main", erased)].erased = True
    with pytest.raises(ValueError):
        engine.put_working(_item(erased))

    tainted = _evidence(engine, capability_tags=["data-only", "no-write-authority"])
    tainted_item = _item(tainted, item_id="tainted")
    engine.put_working(tainted_item)
    stored = engine.get_working(TENANT, SESSION, "tainted", as_of=CREATED_AT)
    assert stored is not None
    assert is_write_tainted(stored.capability_tags)


def test_erasure_cascades_to_working_items_and_blocks_recovery() -> None:
    for mode, requested_by in (("tombstone_recompute", "user"), ("hard_delete_legal", "legal")):
        engine = LocalMemoryEngine()
        evidence_id = _evidence(engine)
        item = _put(engine, evidence_id=evidence_id)
        report = engine.forget(TENANT, evidence_id, requested_by=requested_by, erasure_mode=mode)
        assert report["erased"] is True
        assert report["propagated"]["removed_working_items"] == [
            {"tenant_id": TENANT, "session_id": SESSION, "item_id": item.item_id}
        ]
        assert engine.get_working(TENANT, SESSION, item.item_id, as_of=CREATED_AT) is None
        assert engine.list_working(TENANT, SESSION, as_of=CREATED_AT) == []
        assert engine.expire_working(TENANT, expired_at=EXPIRES_AT) == []


def test_stale_erased_provenance_fails_closed_before_expiry() -> None:
    engine = LocalMemoryEngine()
    evidence_id = _evidence(engine)
    item = _put(engine, evidence_id=evidence_id)
    engine.evidence[engine._evidence_key(TENANT, "main", evidence_id)].erased = True
    before = copy.deepcopy(engine.audit_log)
    with pytest.raises(ValueError):
        engine.get_working(TENANT, SESSION, item.item_id, as_of=CREATED_AT)
    with pytest.raises(ValueError):
        engine.expire_working(TENANT, expired_at=EXPIRES_AT)
    assert engine.working_memory[(TENANT, SESSION, item.item_id)].status == "active"
    assert engine.audit_log == before


def test_put_rolls_back_when_audit_or_persistence_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = LocalMemoryEngine()
    item = _item(_evidence(engine))
    before = (copy.deepcopy(engine.working_memory), copy.deepcopy(engine.audit_log), engine._store_version)
    original_audit = engine._audit

    def fail_audit(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(engine, "_audit", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        engine.put_working(item)
    assert (engine.working_memory, engine.audit_log, engine._store_version) == before

    monkeypatch.setattr(engine, "_audit", original_audit)
    original_persist = engine._persist

    def fail_persist() -> None:
        raise OSError("store unavailable")

    monkeypatch.setattr(engine, "_persist", fail_persist)
    with pytest.raises(OSError, match="store unavailable"):
        engine.put_working(item)
    assert (engine.working_memory, engine.audit_log, engine._store_version) == before
    monkeypatch.setattr(engine, "_persist", original_persist)
    assert engine.put_working(item) == item.item_id


def test_expiry_batch_rolls_back_when_audit_or_persistence_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = LocalMemoryEngine()
    for item_id in ("a", "b", "c"):
        _put(engine, item_id=item_id)
    before = (copy.deepcopy(engine.working_memory), copy.deepcopy(engine.audit_log), engine._store_version)
    original_audit = engine._audit
    calls = 0

    def fail_second_expiry(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        if args[2] == "expire_working":
            calls += 1
            if calls == 2:
                raise RuntimeError("audit unavailable")
        original_audit(*args, **kwargs)

    monkeypatch.setattr(engine, "_audit", fail_second_expiry)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        engine.expire_working(TENANT, expired_at=EXPIRES_AT)
    assert (engine.working_memory, engine.audit_log, engine._store_version) == before

    monkeypatch.setattr(engine, "_audit", original_audit)
    original_persist = engine._persist
    monkeypatch.setattr(engine, "_persist", lambda: (_ for _ in ()).throw(OSError("store unavailable")))
    with pytest.raises(OSError, match="store unavailable"):
        engine.expire_working(TENANT, expired_at=EXPIRES_AT)
    assert (engine.working_memory, engine.audit_log, engine._store_version) == before
    monkeypatch.setattr(engine, "_persist", original_persist)
    assert [row.item_id for row in engine.expire_working(TENANT, expired_at=EXPIRES_AT)] == ["a", "b", "c"]


def test_persistence_round_trip_preserves_working_item_and_audit(tmp_path: Path) -> None:
    store = tmp_path / "working.json"
    engine = LocalMemoryEngine(store_path=store)
    item = _put(engine)
    reloaded = LocalMemoryEngine(store_path=store)
    assert reloaded.get_working(TENANT, SESSION, item.item_id, as_of=CREATED_AT) == item
    assert [row["op"] for row in reloaded.audit_log if row["target_id"] == item.item_id] == ["put_working"]


def test_explicit_promotion_requires_gate_and_tainted_content_cannot_authorize_it() -> None:
    engine = LocalMemoryEngine()
    evidence_id = _evidence(engine, capability_tags=["data-only", "no-write-authority"])
    item = _put(engine, evidence_id=evidence_id, item_id="tainted")
    assert engine.assertions == {}
    assert is_write_tainted(item.capability_tags)
    assert engine.get_working(TENANT, SESSION, item.item_id, as_of=CREATED_AT) is not None
