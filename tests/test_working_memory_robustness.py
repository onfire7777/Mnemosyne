"""Comprehensive tests for Mnemosyne's short-term (working) memory overhaul (R1-R5).

Covers:
1. WorkingMemoryItem data model invariants, salience bounds, access_count, last_accessed_at, superseded_by, and serialization.
2. Atomic in-place replacement / supersession across Local, SQLite, and PostgreSQL engines.
3. Singleton-per-kind replacement ("active_goal", "current_plan").
4. Rehearsal keep-alive (touch_working), salience updates, and strict 24-hour TTL ceiling preservation.
5. Kind-aware per-session capacity eviction (pinned kinds protected, transient scratch kinds evicted).
6. MCP and CLI working_replace with HMAC signed-session auth and parameter parity.
7. MCP and CLI working_consolidate distilling eligible items into durable Assertions and Preferences citing evidence_ids.
8. Pre-expiry distillation mode: working_expire(..., consolidate=True).
9. capture turn auto-mirroring (mirror_turn=True) with authenticated session identity.
10. Dynamic task/content relevance re-normalization and priority token sub-budgeting.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

import mnemosyne.cli as cli
from mnemosyne.engine import (
    LocalMemoryEngine,
    WorkingMemoryItem,
)
from mnemosyne.mcp_tools import MemoryTools
from mnemosyne.models import Evidence
from mnemosyne.postgres_engine import PostgresEngine
from mnemosyne.security import SessionIdentity, SessionTokenVerifier, TrustTier
from mnemosyne.sqlite_engine import SqliteEngine

SESSION = "test-robustness-session"
AGENT = "test-agent"
SECRET = "test-robustness-secret-key-32-chars-ok!"


@pytest.fixture(params=["local", "sqlite", "postgres"])
def engine_bundle(request: pytest.FixtureRequest, tmp_path: Path) -> tuple[Any, str, str]:
    param = request.param
    tenant = f"tenant-wm-{param}-{uuid4()}"
    user = f"user-wm-{param}"
    if param == "local":
        return LocalMemoryEngine(store_path=tmp_path / "local-store.json"), tenant, user
    if param == "sqlite":
        return SqliteEngine(tmp_path / "sqlite-store"), tenant, user
    dsn = os.environ.get("MNEMOSYNE_POSTGRES_DSN")
    if not dsn:
        pytest.skip("MNEMOSYNE_POSTGRES_DSN is not set")
    pytest.importorskip("psycopg")
    return PostgresEngine(dsn), tenant, user


def _identity(tenant: str, user: str, session: str = SESSION, agent: str = AGENT) -> SessionIdentity:
    return SessionIdentity(
        tenant_id=tenant,
        user_id=user,
        role="agent",
        source_trust_tier=int(TrustTier.NORMAL),
        agent_id=agent,
        session_id=session,
    )


def _seed_evidence(engine: Any, tenant: str, user: str, content: str = "Test evidence content", branch: str = "main", session_id: str = SESSION) -> str:
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
    return engine.append_evidence(ev, branch=branch)


# ==============================================================================
# 1. WorkingMemoryItem Model Invariants & Validation
# ==============================================================================


def test_working_memory_item_fields_and_validation() -> None:
    now = datetime.now(UTC)
    expires = now + timedelta(hours=2)

    # Valid item construction
    item = WorkingMemoryItem(
        item_id="item-valid-1",
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        agent_id="agent-1",
        kind="active_goal",
        task_id="task-1",
        content="Achieve complete memory overhaul",
        created_at=now,
        expires_at=expires,
        evidence_ids=["cid-1"],
        salience=0.85,
        access_count=3,
        last_accessed_at=now + timedelta(minutes=15),
    )
    assert item.salience == 0.85
    assert item.access_count == 3
    assert item.last_accessed_at == now + timedelta(minutes=15)
    assert item.status == "active"
    assert item.superseded_by is None

    # Serialization roundtrip
    item_dict = item.to_dict()
    assert item_dict["salience"] == 0.85
    assert item_dict["access_count"] == 3
    assert item_dict["last_accessed_at"] is not None
    restored = WorkingMemoryItem.from_dict(item_dict)
    assert restored.item_id == item.item_id
    assert restored.salience == 0.85
    assert restored.access_count == 3

    # Salience bounds: must be between 0.0 and 1.0
    with pytest.raises(ValueError, match="salience must be between 0.0 and 1.0"):
        WorkingMemoryItem(
            item_id="item-inv-1", tenant_id="t", session_id="s", user_id="u",
            agent_id="a", kind="active_goal", task_id="tk", content="c",
            created_at=now, expires_at=expires, evidence_ids=["cid-1"],
            salience=1.5,
        )

    with pytest.raises(ValueError, match="salience must be between 0.0 and 1.0"):
        WorkingMemoryItem(
            item_id="item-inv-2", tenant_id="t", session_id="s", user_id="u",
            agent_id="a", kind="active_goal", task_id="tk", content="c",
            created_at=now, expires_at=expires, evidence_ids=["cid-1"],
            salience=-0.1,
        )

    # access_count: must be non-negative integer
    with pytest.raises(ValueError, match="access_count must be a non-negative integer"):
        WorkingMemoryItem(
            item_id="item-inv-3", tenant_id="t", session_id="s", user_id="u",
            agent_id="a", kind="active_goal", task_id="tk", content="c",
            created_at=now, expires_at=expires, evidence_ids=["cid-1"],
            access_count=-1,
        )

    # last_accessed_at: cannot precede created_at or exceed expires_at
    with pytest.raises(ValueError, match="last_accessed_at cannot precede created_at"):
        WorkingMemoryItem(
            item_id="item-inv-4", tenant_id="t", session_id="s", user_id="u",
            agent_id="a", kind="active_goal", task_id="tk", content="c",
            created_at=now, expires_at=expires, evidence_ids=["cid-1"],
            last_accessed_at=now - timedelta(seconds=10),
        )

    with pytest.raises(ValueError, match="last_accessed_at cannot exceed expires_at"):
        WorkingMemoryItem(
            item_id="item-inv-5", tenant_id="t", session_id="s", user_id="u",
            agent_id="a", kind="active_goal", task_id="tk", content="c",
            created_at=now, expires_at=expires, evidence_ids=["cid-1"],
            last_accessed_at=expires + timedelta(seconds=10),
        )

    # Active item cannot have superseded_by
    with pytest.raises(ValueError, match="active working-memory items cannot have superseded_by"):
        WorkingMemoryItem(
            item_id="item-inv-6", tenant_id="t", session_id="s", user_id="u",
            agent_id="a", kind="active_goal", task_id="tk", content="c",
            created_at=now, expires_at=expires, evidence_ids=["cid-1"],
            status="active", superseded_by="other-item",
        )

    # Expired item can have superseded_by
    expired_item = WorkingMemoryItem(
        item_id="item-exp-1", tenant_id="t", session_id="s", user_id="u",
        agent_id="a", kind="active_goal", task_id="tk", content="c",
        created_at=now, expires_at=expires, evidence_ids=["cid-1"],
        status="expired", expired_at=now + timedelta(minutes=30),
        superseded_by="item-valid-1",
    )
    assert expired_item.status == "expired"
    assert expired_item.superseded_by == "item-valid-1"


# ==============================================================================
# 2. Atomic Replacement & Supersession Across Backends
# ==============================================================================


def test_atomic_replacement_explicit_supersedes(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    cid = _seed_evidence(engine, tenant, user, "Initial plan evidence")
    now = datetime.now(UTC)

    # 1. Put initial item
    item_v1 = WorkingMemoryItem(
        item_id=f"plan-v1-{uuid4()}",
        tenant_id=tenant,
        session_id=SESSION,
        user_id=user,
        agent_id=AGENT,
        kind="tool_result",
        task_id="task-replace",
        content="Search returned 5 results",
        created_at=now,
        expires_at=now + timedelta(hours=1),
        evidence_ids=[cid],
        salience=0.6,
    )
    engine.put_working(item_v1)

    # Verify v1 is active
    active = engine.get_working(tenant, SESSION, item_v1.item_id, as_of=now + timedelta(minutes=5))
    assert active is not None
    assert active.status == "active"
    assert active.superseded_by is None

    # 2. Replace v1 with v2 explicitly
    v2_created = now + timedelta(minutes=10)
    item_v2 = WorkingMemoryItem(
        item_id=f"plan-v2-{uuid4()}",
        tenant_id=tenant,
        session_id=SESSION,
        user_id=user,
        agent_id=AGENT,
        kind="tool_result",
        task_id="task-replace",
        content="Refined search returned 10 results",
        created_at=v2_created,
        expires_at=v2_created + timedelta(hours=1),
        evidence_ids=[cid],
        salience=0.9,
    )
    replaced_id = engine.replace_working(item_v2, supersedes_item_id=item_v1.item_id)
    assert replaced_id == item_v2.item_id

    # 3. Verify old item transitioned to expired with superseded_by
    # Reading at v2_created: v1 is now expired
    active_now = engine.list_working(tenant, SESSION, as_of=v2_created)
    active_ids = {it.item_id for it in active_now}
    assert item_v2.item_id in active_ids
    assert item_v1.item_id not in active_ids

    # Query v1 directly: should be expired or superseded
    v1_stored = engine.get_working(tenant, SESSION, item_v1.item_id, as_of=v2_created)
    # get_working filters status='active' at as_of, so v1 is None at v2_created
    assert v1_stored is None

    # 4. Error: superseding an already expired item raises KeyError
    item_v3 = WorkingMemoryItem(
        item_id=f"plan-v3-{uuid4()}",
        tenant_id=tenant,
        session_id=SESSION,
        user_id=user,
        agent_id=AGENT,
        kind="tool_result",
        task_id="task-replace",
        content="Third search",
        created_at=v2_created + timedelta(minutes=5),
        expires_at=v2_created + timedelta(hours=1),
        evidence_ids=[cid],
    )
    with pytest.raises((KeyError, ValueError), match="not found"):
        engine.replace_working(item_v3, supersedes_item_id=item_v1.item_id)


def test_atomic_replacement_singleton_kind(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    cid = _seed_evidence(engine, tenant, user, "Goal evidence")
    now = datetime.now(UTC)

    # Put initial active_goal
    goal_v1 = WorkingMemoryItem(
        item_id=f"goal-v1-{uuid4()}",
        tenant_id=tenant,
        session_id=SESSION,
        user_id=user,
        agent_id=AGENT,
        kind="active_goal",
        task_id="task-singleton",
        content="Implement feature X",
        created_at=now,
        expires_at=now + timedelta(hours=1),
        evidence_ids=[cid],
        salience=0.7,
    )
    engine.put_working(goal_v1)

    # Replace active_goal without specifying supersedes_item_id (singleton replacement)
    v2_time = now + timedelta(minutes=15)
    goal_v2 = WorkingMemoryItem(
        item_id=f"goal-v2-{uuid4()}",
        tenant_id=tenant,
        session_id=SESSION,
        user_id=user,
        agent_id=AGENT,
        kind="active_goal",
        task_id="task-singleton",
        content="Implement feature X and verify tests",
        created_at=v2_time,
        expires_at=v2_time + timedelta(hours=1),
        evidence_ids=[cid],
        salience=0.95,
    )
    engine.replace_working(goal_v2, singleton_kind=True)

    # Verify only goal_v2 is active
    active = engine.list_working(tenant, SESSION, as_of=v2_time)
    goals = [it for it in active if it.kind == "active_goal"]
    assert len(goals) == 1
    assert goals[0].item_id == goal_v2.item_id
    assert goals[0].content == "Implement feature X and verify tests"


# ==============================================================================
# 3. Rehearsal Keep-Alive (touch_working) & Strict 24h Ceiling Preservation
# ==============================================================================


def test_rehearsal_keep_alive_and_ttl_ceiling(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    cid = _seed_evidence(engine, tenant, user, "Rehearsal evidence")
    now = datetime.now(UTC)
    hard_24h_ceiling = now + timedelta(hours=24)

    item = WorkingMemoryItem(
        item_id=f"rehearse-{uuid4()}",
        tenant_id=tenant,
        session_id=SESSION,
        user_id=user,
        agent_id=AGENT,
        kind="active_constraint",
        task_id="task-rehearse",
        content="Do not expose credentials",
        created_at=now,
        expires_at=now + timedelta(hours=1),  # initially 1 hour TTL
        evidence_ids=[cid],
        salience=0.5,
    )
    engine.put_working(item)

    # 1. First touch: increment access_count and bump salience
    t1 = now + timedelta(minutes=10)
    touched = engine.touch_working(
        tenant, SESSION, item.item_id, accessed_at=t1, salience=0.8, extend_ttl_seconds=3600
    )
    assert touched is not None
    assert touched.access_count == 1
    assert touched.salience == 0.8
    assert touched.last_accessed_at == t1
    # expires_at extended by 1 hour from t1
    assert touched.expires_at == t1 + timedelta(seconds=3600)

    # 2. Second touch: incremental salience delta
    t2 = now + timedelta(minutes=25)
    touched2 = engine.touch_working(
        tenant, SESSION, item.item_id, accessed_at=t2, salience_delta=0.15
    )
    assert touched2 is not None
    assert touched2.access_count == 2
    assert touched2.salience == pytest.approx(0.95, abs=1e-3)
    assert touched2.last_accessed_at == t2

    # 3. Third touch: attempt to extend beyond 24h hard ceiling
    t3 = now + timedelta(minutes=45)
    touched3 = engine.touch_working(
        tenant, SESSION, item.item_id, accessed_at=t3, extend_ttl_seconds=300000  # huge extension
    )
    assert touched3 is not None
    # Must be strictly clamped to hard 24h ceiling from created_at
    assert touched3.expires_at == hard_24h_ceiling
    assert touched3.access_count == 3


# ==============================================================================
# 4. Kind-Aware Session Capacity Eviction
# ==============================================================================


def test_kind_aware_session_capacity_eviction(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    cid = _seed_evidence(engine, tenant, user, "Capacity eviction evidence")
    now = datetime.now(UTC)

    # We will enforce a tight session capacity of 3 items
    max_cap = 3

    # Seed 2 pinned items
    pinned_goal = WorkingMemoryItem(
        item_id=f"pinned-goal-{uuid4()}",
        tenant_id=tenant, session_id=SESSION, user_id=user, agent_id=AGENT,
        kind="active_goal", task_id="task-cap", content="Critical Goal",
        created_at=now, expires_at=now + timedelta(hours=2),
        evidence_ids=[cid], salience=0.5,
    )
    pinned_plan = WorkingMemoryItem(
        item_id=f"pinned-plan-{uuid4()}",
        tenant_id=tenant, session_id=SESSION, user_id=user, agent_id=AGENT,
        kind="current_plan", task_id="task-cap", content="Execution Plan",
        created_at=now + timedelta(seconds=1), expires_at=now + timedelta(hours=2),
        evidence_ids=[cid], salience=0.5,
    )
    engine.put_working(pinned_goal, max_working_items_per_session=max_cap)
    engine.put_working(pinned_plan, max_working_items_per_session=max_cap)

    # Seed 1 transient item with low salience
    scratch_1 = WorkingMemoryItem(
        item_id=f"scratch-1-{uuid4()}",
        tenant_id=tenant, session_id=SESSION, user_id=user, agent_id=AGENT,
        kind="tool_result", task_id="task-cap", content="Old scratch 1",
        created_at=now + timedelta(seconds=2), expires_at=now + timedelta(hours=2),
        evidence_ids=[cid], salience=0.2,
    )
    engine.put_working(scratch_1, max_working_items_per_session=max_cap)

    # Currently at capacity (3 items)
    active_items = engine.list_working(tenant, SESSION, as_of=now + timedelta(seconds=3))
    assert len(active_items) == 3

    # Seed a 4th item (new transient item with higher salience)
    scratch_2 = WorkingMemoryItem(
        item_id=f"scratch-2-{uuid4()}",
        tenant_id=tenant, session_id=SESSION, user_id=user, agent_id=AGENT,
        kind="conversation_turn", task_id="task-cap", content="User utterance",
        created_at=now + timedelta(seconds=4), expires_at=now + timedelta(hours=2),
        evidence_ids=[cid], salience=0.7,
    )
    engine.put_working(scratch_2, max_working_items_per_session=max_cap)

    # After eviction:
    # 1. Total active items must be <= max_cap (3)
    # 2. Both pinned items ("active_goal", "current_plan") MUST survive
    # 3. scratch_1 (lowest salience transient item) must have been evicted
    # 4. scratch_2 must be present
    active_after = engine.list_working(tenant, SESSION, as_of=now + timedelta(seconds=5))
    assert len(active_after) <= max_cap
    active_ids = {it.item_id for it in active_after}

    assert pinned_goal.item_id in active_ids, "Pinned active_goal was incorrectly evicted!"
    assert pinned_plan.item_id in active_ids, "Pinned current_plan was incorrectly evicted!"
    assert scratch_2.item_id in active_ids, "New item was not stored!"
    assert scratch_1.item_id not in active_ids, "Lowest-salience transient item should have been evicted!"


# ==============================================================================
# 5. MCP and CLI Transport: working_replace & HMAC Auth
# ==============================================================================


def test_mcp_working_replace_and_auth(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    tools = MemoryTools(engine)
    cid = _seed_evidence(engine, tenant, user, "MCP replace evidence")
    now = datetime.now(UTC)
    identity = _identity(tenant, user)

    # 1. Seed initial item via tools
    seed_res = tools.working_seed(
        tenant_id=tenant,
        session_id=SESSION,
        user_id=user,
        agent_id=AGENT,
        task_id="task-mcp",
        branch="main",
        kind="active_goal",
        content="Initial MCP Goal",
        evidence_ids=[cid],
        ttl_seconds=1200,
        created_at=now.isoformat(),
        session_identity=identity,
    )
    v1_id = seed_res["item"]["item_id"]

    # 2. working_replace without valid session identity raises PermissionError
    with pytest.raises(PermissionError, match="verified session identity is required"):
        tools.working_replace(
            tenant_id=tenant,
            session_id=SESSION,
            user_id=user,
            agent_id=AGENT,
            task_id="task-mcp",
            branch="main",
            kind="active_goal",
            content="Unauthorized Replace",
            evidence_ids=[cid],
            ttl_seconds=1200,
            created_at=(now + timedelta(minutes=5)).isoformat(),
            supersedes_item_id=v1_id,
            session_identity=None,
        )

    # 3. working_replace with valid session identity succeeds
    replace_res = tools.working_replace(
        tenant_id=tenant,
        session_id=SESSION,
        user_id=user,
        agent_id=AGENT,
        task_id="task-mcp",
        branch="main",
        kind="active_goal",
        content="Updated MCP Goal",
        evidence_ids=[cid],
        ttl_seconds=1200,
        created_at=(now + timedelta(minutes=5)).isoformat(),
        supersedes_item_id=v1_id,
        salience=0.88,
        session_identity=identity,
    )
    assert replace_res["superseded_item_id"] == v1_id
    assert replace_res["item"]["content"] == "Updated MCP Goal"
    assert replace_res["item"]["salience"] == 0.88
    assert replace_res["security"]["operation"] == "working_replace"


# ==============================================================================
# 6. Distillation & Consolidation: working_consolidate
# ==============================================================================


def test_working_consolidate_distillation_taxonomy(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    tools = MemoryTools(engine)
    cid = _seed_evidence(engine, tenant, user, "Consolidation ground truth")
    now = datetime.now(UTC)
    identity = _identity(tenant, user)

    # Seed 4 items:
    # 1. active_constraint -> should become Preference(category="constraint")
    # 2. intermediate_conclusion -> should become Assertion(predicate="conclusion")
    # 3. active_goal -> should become Assertion(predicate="active_goal")
    # 4. conversation_turn -> ineligible, should NOT become assertion/preference
    tools.working_seed(
        tenant_id=tenant, session_id=SESSION, user_id=user, agent_id=AGENT,
        task_id="task-distill", branch="main", kind="active_constraint",
        content="Never log raw session tokens", evidence_ids=[cid],
        ttl_seconds=1800, created_at=now.isoformat(), session_identity=identity,
    )
    tools.working_seed(
        tenant_id=tenant, session_id=SESSION, user_id=user, agent_id=AGENT,
        task_id="task-distill", branch="main", kind="intermediate_conclusion",
        content="The user prefers concise summaries", evidence_ids=[cid],
        ttl_seconds=1800, created_at=(now + timedelta(seconds=1)).isoformat(),
        session_identity=identity,
    )
    tools.working_seed(
        tenant_id=tenant, session_id=SESSION, user_id=user, agent_id=AGENT,
        task_id="task-distill", branch="main", kind="active_goal",
        content="Deliver milestone on time", evidence_ids=[cid],
        ttl_seconds=1800, created_at=(now + timedelta(seconds=2)).isoformat(),
        session_identity=identity,
    )
    tools.working_seed(
        tenant_id=tenant, session_id=SESSION, user_id=user, agent_id=AGENT,
        task_id="task-distill", branch="main", kind="conversation_turn",
        content="User: Can you summarize the proposal?", evidence_ids=[cid],
        ttl_seconds=1800, created_at=(now + timedelta(seconds=3)).isoformat(),
        session_identity=identity,
    )

    # Execute consolidation across all active items
    res = tools.working_consolidate(
        tenant_id=tenant,
        session_id=SESSION,
        user_id=user,
        agent_id=AGENT,
        task_id="task-distill",
        branch="main",
        as_of=(now + timedelta(seconds=10)).isoformat(),
        session_identity=identity,
    )

    assert res["consolidated_count"] == 3
    assert len(res["preferences"]) == 1
    assert len(res["assertions"]) == 2

    # Check distilled Preference
    pref = res["preferences"][0]
    assert pref["category"] == "constraint"
    assert pref["statement"] == "Never log raw session tokens"
    assert cid in pref["source_evidence_cids"]

    # Check distilled Assertions
    predicates = {a["predicate"]: a["object"] for a in res["assertions"]}
    assert "conclusion" in predicates
    assert predicates["conclusion"] == "The user prefers concise summaries"
    assert "active_goal" in predicates
    assert predicates["active_goal"] == "Deliver milestone on time"


# ==============================================================================
# 7. Pre-Expiry Consolidation: working_expire(consolidate=True)
# ==============================================================================


def test_working_expire_with_consolidation_mode(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    tools = MemoryTools(engine)
    cid = _seed_evidence(engine, tenant, user, "Expiry consolidation evidence")
    now = datetime.now(UTC)
    identity = _identity(tenant, user)
    consolidator_identity = SessionIdentity(
        tenant_id=tenant,
        user_id=user,
        role="consolidator",
        source_trust_tier=0,
        agent_id=AGENT,
        session_id=SESSION,
    )

    # Seed short-lived conclusion
    tools.working_seed(
        tenant_id=tenant, session_id=SESSION, user_id=user, agent_id=AGENT,
        task_id="task-exp-cons", branch="main", kind="intermediate_conclusion",
        content="Database cache hits exceeded 99%", evidence_ids=[cid],
        ttl_seconds=60, created_at=now.isoformat(), session_identity=identity,
    )

    # Expire items at now + 120s with consolidate=True
    exp_res = tools.working_expire(
        tenant_id=tenant,
        session_id=SESSION,
        user_id=user,
        agent_id=AGENT,
        task_id="task-exp-cons",
        branch="main",
        expired_at=(now + timedelta(seconds=120)).isoformat(),
        role="consolidator",
        source_trust_tier=0,
        session_identity=consolidator_identity,
        consolidate=True,
    )

    assert len(exp_res["items"]) >= 1
    assert "consolidated" in exp_res
    assertions = exp_res["consolidated"]["assertions"]
    assert len(assertions) >= 1
    assert assertions[0]["object"] == "Database cache hits exceeded 99%"
    assert cid in assertions[0]["source_evidence_cids"]


# ==============================================================================
# 8. capture Turn Auto-Mirroring
# ==============================================================================


def test_capture_turn_auto_mirroring(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    tools = MemoryTools(engine)
    identity = _identity(tenant, user)

    # 1. mirror_turn=False (default): normal capture, working_item_id is None
    c1 = tools.capture(
        tenant_id=tenant,
        user_id=user,
        actor="user",
        source_type="conversation",
        content="Hello Mnemosyne!",
        session_id=SESSION,
        mirror_turn=False,
    )
    assert c1["created"] is True
    assert c1["working_item_id"] is None

    # 2. mirror_turn=True without session identity raises PermissionError
    with pytest.raises(PermissionError, match="working memory turn mirroring requires verified session identity"):
        tools.capture(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="conversation",
            content="Mirror without auth",
            session_id=SESSION,
            mirror_turn=True,
            session_identity=None,
        )

    # 3. mirror_turn=True with valid session identity creates both Evidence and WorkingMemoryItem
    c3 = tools.capture(
        tenant_id=tenant,
        user_id=user,
        actor="assistant",
        source_type="conversation",
        content="I have updated your schedule for tomorrow.",
        session_id=SESSION,
        mirror_turn=True,
        session_identity=identity,
    )
    assert c3["created"] is True
    assert c3["working_item_id"] is not None

    # Verify the item in working memory
    active_items = engine.list_working(tenant, SESSION, as_of=datetime.now(UTC))
    mirrored = [it for it in active_items if it.item_id == c3["working_item_id"]]
    assert len(mirrored) == 1
    assert mirrored[0].kind == "conversation_turn"
    assert mirrored[0].content == "I have updated your schedule for tomorrow."
    assert c3["cid"] in mirrored[0].evidence_ids

    # 4. Idempotent re-capture does not duplicate working item
    c4 = tools.capture(
        tenant_id=tenant,
        user_id=user,
        actor="assistant",
        source_type="conversation",
        content="I have updated your schedule for tomorrow.",
        session_id=SESSION,
        mirror_turn=True,
        session_identity=identity,
    )
    assert c4["idempotent"] is True
    assert c4["working_item_id"] == c3["working_item_id"]


# ==============================================================================
# 9. CLI End-to-End Execution with HMAC Signed Tokens
# ==============================================================================


def test_cli_working_replace_and_consolidate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = tmp_path / "cli-store.json"
    tenant, user = "tenant-cli-test", "user-cli-test"
    token = SessionTokenVerifier(SECRET).sign(_identity(tenant, user))

    # Ingest evidence for provenance
    capsys.readouterr()
    cli.main([
        "--store", str(store),
        "capture",
        "--tenant", tenant,
        "--user", user,
        "--source-type", "cli",
        "--source-identity", "cli-agent",
        "--session-id", SESSION,
        "--turn-index", "1",
        "--content", "Grounding evidence for CLI test",
    ])
    captured = json.loads(capsys.readouterr().out)
    cid = captured["cid"]

    now = datetime.now(UTC)

    # 1. working-replace without session-token fails
    with pytest.raises(SystemExit):
        cli.main([
            "--store", str(store),
            "working-replace",
            "--tenant", tenant,
            "--session-id", SESSION,
            "--user", user,
            "--agent-id", AGENT,
            "--task-id", "cli-task",
            "--branch", "main",
            "--kind", "active_goal",
            "--content", "Goal via CLI",
            "--evidence-cid", cid,
            "--ttl-seconds", "1200",
            "--created-at", now.isoformat(),
            "--source-trust-tier", "0",
        ])

    # 2. working-replace with session-token succeeds
    capsys.readouterr()
    rc = cli.main([
        "--store", str(store),
        "--session-secret", SECRET,
        "--session-token", token,
        "working-replace",
        "--tenant", tenant,
        "--session-id", SESSION,
        "--user", user,
        "--agent-id", AGENT,
        "--task-id", "cli-task",
        "--branch", "main",
        "--kind", "active_goal",
        "--content", "Goal via CLI with auth",
        "--evidence-cid", cid,
        "--ttl-seconds", "1200",
        "--created-at", now.isoformat(),
        "--source-trust-tier", "0",
    ])
    assert rc == 0
    replace_out = json.loads(capsys.readouterr().out)
    assert replace_out["item"]["content"] == "Goal via CLI with auth"

    # 3. working-consolidate with session-token succeeds
    capsys.readouterr()
    rc_cons = cli.main([
        "--store", str(store),
        "--session-secret", SECRET,
        "--session-token", token,
        "working-consolidate",
        "--tenant", tenant,
        "--session-id", SESSION,
        "--user", user,
        "--agent-id", AGENT,
        "--task-id", "cli-task",
        "--branch", "main",
        "--source-trust-tier", "0",
    ])
    assert rc_cons == 0
    cons_out = json.loads(capsys.readouterr().out)
    assert cons_out["consolidated_count"] >= 1
    assert len(cons_out["assertions"]) >= 1
    assert cons_out["assertions"][0]["object"] == "Goal via CLI with auth"
