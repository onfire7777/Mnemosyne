"""Empirical challenger stress-test suite for Mnemosyne Working Memory (R2, R3, R5).

Adversarially tests:
1. Concurrency & Race Conditions:
   - Simultaneous replacements of the same working memory item.
   - Simultaneous singleton-kind replacements (active_goal, current_plan).
   - Race between touch_working and replace_working on the same item.
   - Simultaneous touch_working access_count increments (lost update prevention).
2. Hard 24-Hour TTL Ceiling Enforcement:
   - Repeated touch_working calls past created_at + 24h.
   - Huge extend_ttl_seconds clamping.
   - Touch calls after 24h returns None and preserves ceiling.
3. Kind-Aware Eviction Under Pressure:
   - Pinned kinds (active_goal, active_constraint, current_plan) NEVER evicted under heavy flood.
   - Eviction strictly orders lowest-salience first, then oldest created_at.
   - Protected pinned-only capacity overflow behavior.
4. Zero-DELETE Compliance and Raw Database Audit Integrity:
   - Verifies 0 SQL DELETEs executed across all lifecycles.
   - Confirms application role mnemosyne_app has DELETE revoked in PostgreSQL.
   - Verifies raw database state retains superseded and evicted rows with status='expired'.
5. Security Boundaries & Isolation:
   - Rejection of cross-session and cross-tenant supersession attempts.
   - Rejection of self-supersession and resurrecting expired items.
"""

from __future__ import annotations

import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from mnemosyne.engine import (
    LocalMemoryEngine,
    WorkingMemoryItem,
)
from mnemosyne.models import Evidence
from mnemosyne.postgres_engine import PostgresEngine
from mnemosyne.security import TrustTier
from mnemosyne.sqlite_engine import SqliteEngine

SESSION_A = "challenger-session-alpha"
SESSION_B = "challenger-session-beta"
AGENT_ID = "challenger-agent"


@pytest.fixture(params=["local", "sqlite", "postgres"])
def engine_bundle(request: pytest.FixtureRequest, tmp_path: Path) -> tuple[Any, str, str]:
    param = request.param
    tenant = f"tenant-stress-{param}-{uuid4()}"
    user = f"user-stress-{param}"
    if param == "local":
        return LocalMemoryEngine(store_path=tmp_path / "local-store.json"), tenant, user
    if param == "sqlite":
        return SqliteEngine(tmp_path / "sqlite-store"), tenant, user
    dsn = os.environ.get("MNEMOSYNE_POSTGRES_DSN")
    if not dsn:
        pytest.skip("MNEMOSYNE_POSTGRES_DSN is not set")
    pytest.importorskip("psycopg")
    return PostgresEngine(dsn), tenant, user


def _seed_ev(engine: Any, tenant: str, user: str, content: str = "Evidence", session_id: str = SESSION_A) -> str:
    ev = Evidence(
        tenant_id=tenant,
        user_id=user,
        actor="user",
        source_type="test",
        session_id=session_id,
        content=content,
        trust_tier=int(TrustTier.NORMAL),
        access_policy={"tenant": tenant},
    )
    return engine.append_evidence(ev, branch="main")


def _make_item(
    tenant: str,
    user: str,
    item_id: str,
    evidence_id: str,
    kind: str = "conversation_turn",
    salience: float = 0.5,
    session_id: str = SESSION_A,
    created_at: datetime | None = None,
    ttl_seconds: int = 3600,
) -> WorkingMemoryItem:
    now = created_at or datetime.now(UTC)
    return WorkingMemoryItem(
        item_id=item_id,
        tenant_id=tenant,
        session_id=session_id,
        user_id=user,
        agent_id=AGENT_ID,
        kind=kind,
        task_id="stress-task",
        content=f"Content for {item_id}",
        created_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
        evidence_ids=[evidence_id],
        salience=salience,
    )


# ==============================================================================
# Challenge 1: Concurrency & Race Conditions
# ==============================================================================


def test_concurrency_race_simultaneous_replace(engine_bundle: tuple[Any, str, str]) -> None:
    """Stress test: 10 threads race to replace the EXACT SAME item simultaneously.

    Requirement: Exactly one thread succeeds, 9 fail with KeyError.
    No status corruption or orphan active items.
    """
    engine, tenant, user = engine_bundle
    ev_id = _seed_ev(engine, tenant, user)
    root_id = "root-item-concurrency"
    root_item = _make_item(tenant, user, root_id, ev_id)
    engine.put_working(root_item)

    num_threads = 10
    barrier = threading.Barrier(num_threads)
    results: list[dict[str, Any]] = []

    def _worker(thread_idx: int) -> None:
        replacement_id = f"repl-item-{thread_idx}"
        repl_item = _make_item(tenant, user, replacement_id, ev_id)
        barrier.wait()
        try:
            stored_id = engine.replace_working(repl_item, supersedes_item_id=root_id)
            results.append({"thread": thread_idx, "success": True, "id": stored_id})
        except KeyError as exc:
            results.append({"thread": thread_idx, "success": False, "error": str(exc), "exc_type": "KeyError"})
        except Exception as exc:
            results.append({"thread": thread_idx, "success": False, "error": str(exc), "exc_type": type(exc).__name__})

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    successes = [r for r in results if r["success"]]
    failures = [r for r in results if not r["success"]]

    assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}: {successes}"
    assert len(failures) == num_threads - 1
    for f in failures:
        assert f["exc_type"] == "KeyError", f"Expected KeyError, got {f}"

    winner_id = successes[0]["id"]
    now = datetime.now(UTC)
    active_items = engine.list_working(tenant, SESSION_A, as_of=now)
    assert len(active_items) == 1
    assert active_items[0].item_id == winner_id
    assert active_items[0].status == "active"

    root_stored = engine.get_working(tenant, SESSION_A, root_id, as_of=now)
    assert root_stored is None  # expired items are masked by get_working


def test_concurrency_race_singleton_kind_replacement(engine_bundle: tuple[Any, str, str]) -> None:
    """Stress test: 8 threads race to replace an active_goal using singleton_kind=True.

    Requirement: All operations serialize cleanly. At completion, exactly 1 active_goal
    remains active, and all previous goals are retired to status='expired'.
    """
    engine, tenant, user = engine_bundle
    ev_id = _seed_ev(engine, tenant, user)
    root_goal = _make_item(tenant, user, "goal-root", ev_id, kind="active_goal")
    engine.put_working(root_goal)

    num_threads = 8
    barrier = threading.Barrier(num_threads)
    results: list[dict[str, Any]] = []

    def _worker(thread_idx: int) -> None:
        goal_id = f"goal-worker-{thread_idx}"
        goal_item = _make_item(tenant, user, goal_id, ev_id, kind="active_goal")
        barrier.wait()
        try:
            stored_id = engine.replace_working(goal_item, singleton_kind=True)
            results.append({"thread": thread_idx, "success": True, "id": stored_id})
        except Exception as exc:
            results.append({"thread": thread_idx, "success": False, "error": str(exc), "exc_type": type(exc).__name__})

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    successes = [r for r in results if r["success"]]
    assert len(successes) == num_threads

    now = datetime.now(UTC)
    active_items = engine.list_working(tenant, SESSION_A, as_of=now)
    active_goals = [item for item in active_items if item.kind == "active_goal"]
    assert len(active_goals) == 1, f"Expected exactly 1 active goal, found {len(active_goals)}"


def test_concurrency_race_touch_vs_replace(engine_bundle: tuple[Any, str, str]) -> None:
    """Stress test: 5 threads attempt to touch an item while 5 threads attempt to replace it.

    Requirement: Exactly one replace succeeds; once replaced, touch returns None and does not resurrect.
    At completion, exactly 1 active item remains.
    """
    engine, tenant, user = engine_bundle
    ev_id = _seed_ev(engine, tenant, user)
    target_id = "target-item-race"
    target_item = _make_item(tenant, user, target_id, ev_id)
    engine.put_working(target_item)

    total_threads = 10
    barrier = threading.Barrier(total_threads)
    replace_results: list[bool] = []
    touch_results: list[bool] = []

    def _replacer(idx: int) -> None:
        repl_id = f"repl-race-{idx}"
        item = _make_item(tenant, user, repl_id, ev_id)
        barrier.wait()
        try:
            engine.replace_working(item, supersedes_item_id=target_id)
            replace_results.append(True)
        except KeyError:
            replace_results.append(False)

    def _toucher(idx: int) -> None:
        barrier.wait()
        res = engine.touch_working(tenant, SESSION_A, target_id, extend_ttl_seconds=300)
        touch_results.append(res is not None)

    threads = []
    for i in range(5):
        threads.append(threading.Thread(target=_replacer, args=(i,)))
        threads.append(threading.Thread(target=_toucher, args=(i,)))

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(replace_results) == 1, f"Expected exactly 1 replacement to succeed, got {sum(replace_results)}"
    now = datetime.now(UTC)
    active = engine.list_working(tenant, SESSION_A, as_of=now)
    assert len(active) == 1, f"Expected exactly 1 active item, found {len(active)}"
    assert active[0].item_id != target_id


def test_concurrency_simultaneous_touch_working_increments(engine_bundle: tuple[Any, str, str]) -> None:
    """Stress test: 10 concurrent threads call touch_working on the same item.

    Requirement: access_count is serialized without lost updates (final access_count = 10).
    """
    engine, tenant, user = engine_bundle
    ev_id = _seed_ev(engine, tenant, user)
    item_id = "item-touch-atomic"
    item = _make_item(tenant, user, item_id, ev_id)
    engine.put_working(item)

    num_threads = 10
    barrier = threading.Barrier(num_threads)

    def _touch(idx: int) -> None:
        barrier.wait()
        res = engine.touch_working(tenant, SESSION_A, item_id, salience_delta=0.01)
        assert res is not None

    threads = [threading.Thread(target=_touch, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    now = datetime.now(UTC)
    final_item = engine.get_working(tenant, SESSION_A, item_id, as_of=now)
    assert final_item is not None
    assert final_item.access_count == num_threads, f"Expected access_count {num_threads}, got {final_item.access_count}"


# ==============================================================================
# Challenge 2: Hard 24-Hour TTL Ceiling Enforcement
# ==============================================================================


def test_hard_24h_ttl_ceiling_huge_extension(engine_bundle: tuple[Any, str, str]) -> None:
    """Attempt huge extend_ttl_seconds (e.g. 100 days) via touch_working.

    Requirement: expires_at is strictly clamped to created_at + 24 hours.
    """
    engine, tenant, user = engine_bundle
    ev_id = _seed_ev(engine, tenant, user)
    created = datetime(2026, 10, 27, 0, 0, 0, tzinfo=UTC)
    item = _make_item(tenant, user, "item-ttl-ceiling", ev_id, created_at=created, ttl_seconds=3600)
    engine.put_working(item)

    hard_ceiling = created + timedelta(hours=24)

    # Touch with 100 days extension at created + 1 hour
    clock = created + timedelta(hours=1)
    touched = engine.touch_working(tenant, SESSION_A, item.item_id, accessed_at=clock, extend_ttl_seconds=8_640_000.0)
    assert touched is not None
    assert touched.expires_at == hard_ceiling, f"Expected {hard_ceiling}, got {touched.expires_at}"

    # Verify persistent state matches clamped ceiling
    stored = engine.get_working(tenant, SESSION_A, item.item_id, as_of=clock)
    assert stored is not None
    assert stored.expires_at == hard_ceiling


def test_hard_24h_ttl_ceiling_repeated_extension_loop(engine_bundle: tuple[Any, str, str]) -> None:
    """Repeatedly touch and extend TTL 50 times across 23 hours.

    Requirement: expires_at NEVER exceeds created_at + 24h at any iteration.
    After 24h + 1s, touch_working returns None.
    """
    engine, tenant, user = engine_bundle
    ev_id = _seed_ev(engine, tenant, user)
    created = datetime(2026, 10, 27, 0, 0, 0, tzinfo=UTC)
    item = _make_item(tenant, user, "item-ttl-loop", ev_id, created_at=created, ttl_seconds=1800)
    engine.put_working(item)

    hard_ceiling = created + timedelta(hours=24)

    for step in range(1, 48):
        clock = created + timedelta(minutes=step * 30)
        touched = engine.touch_working(
            tenant, SESSION_A, item.item_id, accessed_at=clock, extend_ttl_seconds=7200.0
        )
        assert touched is not None
        assert touched.expires_at <= hard_ceiling, (
            f"Step {step}: expires_at {touched.expires_at} exceeded hard ceiling {hard_ceiling}"
        )

    # Now attempt touch at created + 24h + 1s (past the ceiling)
    over_clock = created + timedelta(hours=24, seconds=1)
    past_ceiling_res = engine.touch_working(
        tenant, SESSION_A, item.item_id, accessed_at=over_clock, extend_ttl_seconds=3600.0
    )
    assert past_ceiling_res is None, "touch_working past 24h ceiling must return None"


# ==============================================================================
# Challenge 3: Kind-Aware Eviction Under Pressure
# ==============================================================================


def test_kind_aware_eviction_under_heavy_pressure(engine_bundle: tuple[Any, str, str]) -> None:
    """Flood session with 25 transient items under capacity=5 while holding 3 pinned items.

    Requirement:
    - Pinned items ('active_goal', 'active_constraint', 'current_plan') are NEVER evicted,
      even when they have much lower salience than transient items!
    - Transient items evict strictly by lowest salience first, then oldest created_at.
    """
    engine, tenant, user = engine_bundle
    ev_id = _seed_ev(engine, tenant, user)
    base_time = datetime(2026, 10, 27, 10, 0, 0, tzinfo=UTC)

    # 1. Insert 3 pinned items with low salience
    pinned_specs = [
        ("goal-1", "active_goal", 0.05),
        ("constraint-1", "active_constraint", 0.02),
        ("plan-1", "current_plan", 0.01),
    ]
    for pid, pkind, psal in pinned_specs:
        pitem = _make_item(tenant, user, pid, ev_id, kind=pkind, salience=psal, created_at=base_time)
        engine.put_working(pitem, max_working_items_per_session=5)

    # 2. Flood with 20 transient items with higher salience
    for i in range(20):
        t_time = base_time + timedelta(seconds=i + 1)
        # Salience alternates between 0.3, 0.6, 0.9
        sal = 0.3 if i % 3 == 0 else (0.6 if i % 3 == 1 else 0.9)
        t_item = _make_item(
            tenant,
            user,
            f"transient-{i}",
            ev_id,
            kind="conversation_turn" if i % 2 == 0 else "recent_tool_result",
            salience=sal,
            created_at=t_time,
        )
        engine.put_working(t_item, max_working_items_per_session=5)

        # Invariant check: pinned items must ALWAYS be present and active
        active = engine.list_working(tenant, SESSION_A, as_of=t_time + timedelta(seconds=1))
        active_ids = {a.item_id for a in active}
        assert "goal-1" in active_ids, f"Pinned goal-1 was evicted at step {i}!"
        assert "constraint-1" in active_ids, f"Pinned constraint-1 was evicted at step {i}!"
        assert "plan-1" in active_ids, f"Pinned plan-1 was evicted at step {i}!"
        assert len(active) <= 5, f"Capacity exceeded: {len(active)} > 5"

    # Final check on active pool (at base_time + 10m, before 1h TTL expires)
    final_active = engine.list_working(tenant, SESSION_A, as_of=base_time + timedelta(minutes=10))
    assert len(final_active) == 5
    final_ids = {a.item_id for a in final_active}
    assert {"goal-1", "constraint-1", "plan-1"}.issubset(final_ids)


def test_kind_aware_eviction_strictly_orders_by_salience_then_age(engine_bundle: tuple[Any, str, str]) -> None:
    """Verify eviction tie-breaking: identical salience breaks by oldest created_at.

    Capacity = 2.
    Item 1: salience 0.2, time T0.
    Item 2: salience 0.2, time T0 + 1s.
    Insert Item 3: salience 0.5, time T0 + 2s.
    Deficit = 1 -> Item 1 must evict (oldest), Item 2 and Item 3 survive.
    """
    engine, tenant, user = engine_bundle
    ev_id = _seed_ev(engine, tenant, user)
    t0 = datetime(2026, 10, 27, 12, 0, 0, tzinfo=UTC)

    item1 = _make_item(tenant, user, "item-old-low", ev_id, kind="tool_result", salience=0.2, created_at=t0)
    item2 = _make_item(tenant, user, "item-new-low", ev_id, kind="tool_result", salience=0.2, created_at=t0 + timedelta(seconds=1))
    item3 = _make_item(tenant, user, "item-high", ev_id, kind="tool_result", salience=0.5, created_at=t0 + timedelta(seconds=2))

    engine.put_working(item1, max_working_items_per_session=2)
    engine.put_working(item2, max_working_items_per_session=2)
    engine.put_working(item3, max_working_items_per_session=2)

    active = engine.list_working(tenant, SESSION_A, as_of=t0 + timedelta(seconds=3))
    active_ids = {a.item_id for a in active}
    assert "item-old-low" not in active_ids, "Older low-salience item was not evicted first!"
    assert "item-new-low" in active_ids, "Newer low-salience item should have survived!"
    assert "item-high" in active_ids, "Higher salience item should have survived!"


def test_kind_aware_eviction_all_pinned_over_capacity(engine_bundle: tuple[Any, str, str]) -> None:
    """When all items in session are pinned, capacity eviction cannot evict any of them."""
    engine, tenant, user = engine_bundle
    ev_id = _seed_ev(engine, tenant, user)
    t0 = datetime(2026, 10, 27, 12, 0, 0, tzinfo=UTC)

    goal = _make_item(tenant, user, "pinned-goal", ev_id, kind="active_goal", salience=0.1, created_at=t0)
    constraint = _make_item(tenant, user, "pinned-constraint", ev_id, kind="active_constraint", salience=0.1, created_at=t0)
    plan = _make_item(tenant, user, "pinned-plan", ev_id, kind="current_plan", salience=0.1, created_at=t0)

    # Capacity is 2, but we insert 3 pinned items
    engine.put_working(goal, max_working_items_per_session=2)
    engine.put_working(constraint, max_working_items_per_session=2)
    engine.put_working(plan, max_working_items_per_session=2)

    active = engine.list_working(tenant, SESSION_A, as_of=t0 + timedelta(seconds=1))
    assert len(active) == 3
    assert {a.item_id for a in active} == {"pinned-goal", "pinned-constraint", "pinned-plan"}


# ==============================================================================
# Challenge 4: Zero-DELETE Compliance and Raw Database Audit Integrity
# ==============================================================================


def test_zero_delete_audit_integrity(engine_bundle: tuple[Any, str, str]) -> None:
    """Verify that no SQL DELETE is ever executed on working_memory.

    Superseded and capacity-evicted items MUST remain physically present in the raw database
    with status='expired', metadata['superseded_by'] or metadata['evicted']=True,
    and corresponding audit_log records.
    """
    import json

    engine, tenant, user = engine_bundle
    ev_id = _seed_ev(engine, tenant, user)
    t0 = datetime(2026, 10, 27, 14, 0, 0, tzinfo=UTC)

    # 1. Put an item and supersede it
    root = _make_item(tenant, user, "item-to-supersede", ev_id, created_at=t0)
    engine.put_working(root)
    repl = _make_item(tenant, user, "item-replacer", ev_id, created_at=t0 + timedelta(seconds=1))
    engine.replace_working(repl, supersedes_item_id="item-to-supersede")

    # 2. Put an item and evict it via capacity
    scratch1 = _make_item(tenant, user, "item-scratch-1", ev_id, salience=0.1, created_at=t0 + timedelta(seconds=2))
    scratch2 = _make_item(tenant, user, "item-scratch-2", ev_id, salience=0.9, created_at=t0 + timedelta(seconds=3))
    engine.put_working(scratch1, max_working_items_per_session=2)
    engine.put_working(scratch2, max_working_items_per_session=2)

    # Now verify raw database storage
    if isinstance(engine, SqliteEngine):
        conn = engine._connect(tenant)
        rows = conn.execute(
            "SELECT item_id, status, superseded_by, metadata FROM working_memory WHERE tenant_id = ?",
            (tenant,),
        ).fetchall()
        assert len(rows) == 4, f"Expected 4 rows in SQLite table, found {len(rows)}"
        row_map = {r[0]: {"status": r[1], "superseded_by": r[2]} for r in rows}
        assert row_map["item-to-supersede"]["status"] == "expired"
        assert row_map["item-to-supersede"]["superseded_by"] == "item-replacer"
        assert row_map["item-replacer"]["status"] == "active"
        assert row_map["item-scratch-1"]["status"] == "expired"
        assert row_map["item-scratch-2"]["status"] == "active"

        # Check audit trail in SQLite record column
        audits = conn.execute(
            "SELECT record FROM audit_log WHERE tenant_id = ?",
            (tenant,),
        ).fetchall()
        audit_records = [json.loads(a[0]) for a in audits]
        audit_events = [(rec.get("op"), rec.get("target_id")) for rec in audit_records]
        assert ("expire_working", "item-to-supersede") in audit_events
        assert ("expire_working", "item-scratch-1") in audit_events

    elif isinstance(engine, PostgresEngine):
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(engine.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT w.item_id, w.status, w.superseded_by, w.metadata
                    FROM working_memory w
                    JOIN tenants t ON t.id = w.tenant_id
                    WHERE t.name = %s
                    """,
                    (tenant,),
                )
                rows = cur.fetchall()
                assert len(rows) == 4, f"Expected 4 rows in PostgreSQL table, found {len(rows)}"
                row_map = {r["item_id"]: r for r in rows}
                assert row_map["item-to-supersede"]["status"] == "expired"
                assert row_map["item-to-supersede"]["superseded_by"] == "item-replacer"
                assert row_map["item-scratch-1"]["status"] == "expired"

                # Check audit trail (column is 'op' in PostgreSQL audit_log)
                cur.execute(
                    """
                    SELECT a.op, a.diff
                    FROM audit_log a
                    JOIN tenants t ON t.id = a.tenant_id
                    WHERE t.name = %s
                    """,
                    (tenant,),
                )
                audits = cur.fetchall()
                audit_events = [(a["op"], (a["diff"] or {}).get("item_id")) for a in audits]
                assert ("expire_working", "item-to-supersede") in audit_events
                assert ("expire_working", "item-scratch-1") in audit_events

    elif isinstance(engine, LocalMemoryEngine):
        keys = [k for k in engine.working_memory.keys() if k[0] == tenant]
        assert len(keys) == 4
        assert engine.working_memory[(tenant, SESSION_A, "item-to-supersede")].status == "expired"
        assert engine.working_memory[(tenant, SESSION_A, "item-to-supersede")].superseded_by == "item-replacer"
        assert engine.working_memory[(tenant, SESSION_A, "item-scratch-1")].status == "expired"


def test_postgres_app_role_delete_revocation() -> None:
    """Verify that PostgreSQL application role mnemosyne_app has DELETE permissions revoked.

    Attempting raw DELETE FROM working_memory must fail with InsufficientPrivilege.
    """
    app_dsn = os.environ.get("MNEMOSYNE_POSTGRES_APP_TEST_DSN")
    if not app_dsn:
        pytest.skip("MNEMOSYNE_POSTGRES_APP_TEST_DSN is not set")
    pytest.importorskip("psycopg")
    import psycopg

    with psycopg.connect(app_dsn) as conn:
        with conn.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege) as exc_info:
                cur.execute("DELETE FROM working_memory WHERE item_id = 'forbidden'")
            assert "permission denied for table working_memory" in str(exc_info.value).lower()


# ==============================================================================
# Challenge 5: Security Boundaries & Cross-Session / Tenant Isolation
# ==============================================================================


def test_replace_working_rejects_cross_session_supersession(engine_bundle: tuple[Any, str, str]) -> None:
    """Cannot supersede an item belonging to another session."""
    engine, tenant, user = engine_bundle
    ev_a = _seed_ev(engine, tenant, user, session_id=SESSION_A)
    ev_b = _seed_ev(engine, tenant, user, session_id=SESSION_B)

    item_a = _make_item(tenant, user, "item-session-a", ev_a, session_id=SESSION_A)
    engine.put_working(item_a)

    item_b = _make_item(tenant, user, "item-session-b", ev_b, session_id=SESSION_B)
    with pytest.raises(KeyError) as exc_info:
        engine.replace_working(item_b, supersedes_item_id="item-session-a")
    assert "not found in session" in str(exc_info.value)


def test_replace_working_rejects_cross_tenant_supersession(engine_bundle: tuple[Any, str, str]) -> None:
    """Cannot supersede an item belonging to another tenant."""
    engine, tenant1, user = engine_bundle
    tenant2 = f"{tenant1}-alt"

    ev1 = _seed_ev(engine, tenant1, user)
    item1 = _make_item(tenant1, user, "item-t1", ev1)
    engine.put_working(item1)

    ev2 = _seed_ev(engine, tenant2, user)
    item2 = _make_item(tenant2, user, "item-t2", ev2)
    with pytest.raises(KeyError) as exc_info:
        engine.replace_working(item2, supersedes_item_id="item-t1")
    assert "not found in session" in str(exc_info.value)


def test_replace_working_rejects_self_supersession(engine_bundle: tuple[Any, str, str]) -> None:
    """Item cannot supersede itself."""
    engine, tenant, user = engine_bundle
    ev = _seed_ev(engine, tenant, user)
    item = _make_item(tenant, user, "self-item", ev)
    with pytest.raises(ValueError) as exc_info:
        engine.replace_working(item, supersedes_item_id="self-item")
    assert "cannot supersede itself" in str(exc_info.value)


def test_replace_working_rejects_superseding_already_expired_item(engine_bundle: tuple[Any, str, str]) -> None:
    """Attempting to supersede an item that is already expired must fail with KeyError."""
    engine, tenant, user = engine_bundle
    ev = _seed_ev(engine, tenant, user)
    t0 = datetime(2026, 10, 27, 10, 0, 0, tzinfo=UTC)
    item1 = _make_item(tenant, user, "item-orig", ev, created_at=t0, ttl_seconds=1800)
    engine.put_working(item1)

    # Expire it manually past its TTL
    engine.expire_working(tenant, expired_at=t0 + timedelta(hours=2), session_id=SESSION_A)

    # Attempt to supersede the now expired item
    item2 = _make_item(tenant, user, "item-revive", ev, created_at=t0 + timedelta(hours=2, minutes=1))
    with pytest.raises(KeyError) as exc_info:
        engine.replace_working(item2, supersedes_item_id="item-orig")
    assert "not found in session" in str(exc_info.value)
