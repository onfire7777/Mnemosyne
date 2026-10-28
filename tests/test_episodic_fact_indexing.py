"""Tests for deterministic episodic-to-semantic fact and milestone indexing (R4).

Covers:
1. Deterministic extraction across all 4 fact families (Residence, Family/Pet, Expenses/Counts, Milestones).
2. Explicit date/timestamp parsing and fallback to utterance created_at.
3. Cryptographic provenance preservation (source_evidence_cids, trust_tier).
4. Atomic supersession across successive temporal updates (e.g. Sacramento -> San Diego).
5. Cross-engine parity across LocalMemoryEngine and SqliteEngine.
6. End-to-end integration via MemoryTools.working_consolidate and working_expire(consolidate=True).
7. Negative cases (non-factual conversational dialogue produces 0 assertions).
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.episodic_facts import (
    ExtractedFacts,
    extract_episodic_facts,
    parse_explicit_date,
)
from mnemosyne.mcp_tools import MemoryTools
from mnemosyne.models import Evidence
from mnemosyne.security import SessionIdentity, TrustTier
from mnemosyne.sqlite_engine import SqliteEngine

TENANT = "tenant-episodic-test"
USER = "user-episodic-test"
SESSION = "session-episodic-test"
AGENT = "agent-episodic-test"


def _make_identity(tenant: str = TENANT, user: str = USER) -> SessionIdentity:
    return SessionIdentity(
        tenant_id=tenant,
        user_id=user,
        role="agent",
        source_trust_tier=int(TrustTier.DIRECT_USER),
        agent_id=AGENT,
        session_id=SESSION,
    )


def _seed_evidence(engine: Any, tenant: str, user: str, content: str) -> str:
    ev = Evidence(
        tenant_id=tenant,
        user_id=user,
        actor="user",
        source_type="chat",
        session_id=SESSION,
        content=content,
        trust_tier=int(TrustTier.DIRECT_USER),
        access_policy={"tenant": tenant},
    )
    return engine.append_evidence(ev)


# ==============================================================================
# 1. Date Parsing Unit Tests
# ==============================================================================


def test_parse_explicit_date_various_formats() -> None:
    # 4-digit year
    dt = parse_explicit_date("In 2021, I moved")
    assert dt == datetime(2021, 1, 1, 0, 0, 0, tzinfo=UTC)

    # Month Day, Year
    dt = parse_explicit_date("born on May 4, 2018")
    assert dt == datetime(2018, 5, 4, 0, 0, 0, tzinfo=UTC)

    # ISO Date
    dt = parse_explicit_date("event on 2020-06-15")
    assert dt == datetime(2020, 6, 15, 0, 0, 0, tzinfo=UTC)

    # Month and Year
    dt = parse_explicit_date("started in August 2023")
    assert dt == datetime(2023, 8, 1, 0, 0, 0, tzinfo=UTC)

    # Non-dates
    assert parse_explicit_date("") is None
    assert parse_explicit_date("hello world") is None
    assert parse_explicit_date(None) is None


# ==============================================================================
# 2. Fact Extraction Across All 4 Fact Families
# ==============================================================================


def test_extract_residence_family() -> None:
    cid = "cid-residence-1"

    # Moving to a new location with explicit year
    t1 = "In 2024, I moved to San Diego."
    f1 = extract_episodic_facts(t1, evidence_ids=[cid])
    assert isinstance(f1, ExtractedFacts)
    assert len(f1.assertions) >= 1
    assert any(a.subject == "user" and a.predicate == "residence" and a.object == "San Diego" for a in f1.assertions)
    a1 = next(a for a in f1.assertions if a.predicate == "residence")
    assert a1.valid_from == datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    assert cid in a1.source_evidence_cids
    assert any(r.source == "user" and r.target == "San Diego" and r.predicate in {"lives_in", "residence"} for r in f1.relations)

    # Living in / residing
    t2 = "I currently live in Sacramento."
    now = datetime(2023, 5, 1, 12, 0, 0, tzinfo=UTC)
    f2 = extract_episodic_facts(t2, evidence_ids=[cid], created_at=now)
    a2 = next(a for a in f2.assertions if a.predicate == "residence")
    assert a2.object == "Sacramento"
    assert a2.valid_from == now

    # Apartment in location
    t3 = "My current apartment is in Shibuya."
    f3 = extract_episodic_facts(t3, evidence_ids=[cid])
    a3 = next(a for a in f3.assertions if a.predicate == "residence")
    assert a3.object == "Shibuya"

    # Bought house in location
    t4 = "I bought a house in Portland."
    f4 = extract_episodic_facts(t4, evidence_ids=[cid])
    a4 = next(a for a in f4.assertions if a.predicate == "residence")
    assert a4.object == "Portland"


def test_extract_family_and_pet_family() -> None:
    cid = "cid-family-1"
    now = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)

    # Family member with birthdate
    t1 = "My daughter Emily was born on May 4, 2018."
    f1 = extract_episodic_facts(t1, evidence_ids=[cid], created_at=now)
    assert any(a.predicate == "has_family" and a.object == "Emily" for a in f1.assertions)
    a1 = next(a for a in f1.assertions if a.object == "Emily")
    assert a1.valid_from == datetime(2018, 5, 4, 0, 0, 0, tzinfo=UTC)
    assert a1.scope.get("relation") == "daughter"
    assert any(r.source == "user" and r.target == "Emily" and r.predicate == "has_family" for r in f1.relations)

    # Pet with breed
    t2 = "My dog Buster is a Golden Retriever."
    f2 = extract_episodic_facts(t2, evidence_ids=[cid], created_at=now)
    assert any(a.predicate == "has_pet" and a.object == "Buster" for a in f2.assertions)
    assert any(a.subject == "Buster" and a.predicate == "breed" and a.object == "Golden Retriever" for a in f2.assertions)
    assert any(r.source == "user" and r.target == "Buster" and r.predicate == "has_pet" for r in f2.relations)
    assert any(r.source == "Buster" and r.target == "dog" and r.predicate == "is_a" for r in f2.relations)

    # Pet named
    t3 = "I have a cat named Luna."
    f3 = extract_episodic_facts(t3, evidence_ids=[cid])
    assert any(a.predicate == "has_pet" and a.object == "Luna" for a in f3.assertions)


def test_extract_expenses_and_counts_family() -> None:
    cid = "cid-expense-1"

    # Direct expense statement
    t1 = "I spent $450 on bike repairs."
    f1 = extract_episodic_facts(t1, evidence_ids=[cid])
    assert any(a.predicate == "expense" and "$450 on bike repairs" in a.object for a in f1.assertions)
    a1 = next(a for a in f1.assertions if a.predicate == "expense")
    assert a1.scope.get("amount") == 450.0
    assert any(r.source == "user" and r.target == "bike repairs" for r in f1.relations)

    # Total money spent
    t2 = "Total money spent on bike repairs was $450."
    f2 = extract_episodic_facts(t2, evidence_ids=[cid])
    assert any(a.predicate == "expense" and "450" in a.object for a in f2.assertions)

    # Counts
    t3 = "I bought 3 guitars and I have two monitors."
    f3 = extract_episodic_facts(t3, evidence_ids=[cid])
    assert any(a.predicate == "count" and "3 guitars" in a.object for a in f3.assertions)
    assert any(r.source == "user" and r.target == "guitars" for r in f3.relations)


def test_extract_dated_milestones_family() -> None:
    cid = "cid-milestone-1"

    # Education graduation
    t1 = "In 2021, I graduated from Stanford."
    f1 = extract_episodic_facts(t1, evidence_ids=[cid])
    assert any(a.predicate in {"education", "milestone"} and "Stanford" in a.object for a in f1.assertions)
    a1 = next(a for a in f1.assertions if "Stanford" in a.object)
    assert a1.valid_from == datetime(2021, 1, 1, 0, 0, 0, tzinfo=UTC)
    assert any(r.source == "user" and r.target == "Stanford" and r.predicate in {"graduated_from", "education"} for r in f1.relations)

    # Career milestone
    t2 = "In 2019, I started working at Google."
    f2 = extract_episodic_facts(t2, evidence_ids=[cid])
    assert any(a.predicate == "milestone" and "Google" in a.object for a in f2.assertions)
    a2 = next(a for a in f2.assertions if "Google" in a.object)
    assert a2.valid_from == datetime(2019, 1, 1, 0, 0, 0, tzinfo=UTC)
    assert any(r.source == "user" and r.target == "Google" and r.predicate in {"works_at", "employed_by"} for r in f2.relations)

    # Marriage milestone
    t3 = "On October 12, 2015, I got married to Sarah."
    f3 = extract_episodic_facts(t3, evidence_ids=[cid])
    assert any(a.predicate == "milestone" and "married" in a.object for a in f3.assertions)
    a3 = next(a for a in f3.assertions if a.predicate == "milestone")
    assert a3.valid_from == datetime(2015, 10, 12, 0, 0, 0, tzinfo=UTC)


def test_extract_non_factual_dialogue_returns_empty() -> None:
    cid = "cid-neg-1"
    texts = [
        "Can you please summarize our project roadmap?",
        "What is the weather like today?",
        "Let's write a python function to compute fibonacci numbers.",
        "That sounds like a great idea, thank you!",
    ]
    for text in texts:
        facts = extract_episodic_facts(text, evidence_ids=[cid])
        assert len(facts.assertions) == 0
        assert len(facts.relations) == 0


# ==============================================================================
# 3. Provenance and Cryptographic Traceability
# ==============================================================================


def test_provenance_and_trust_derivation() -> None:
    cids = ["cid-evidence-alpha", "cid-evidence-beta"]
    trust = int(TrustTier.DIRECT_USER)
    policy = {"tenant": TENANT, "classification": "confidential"}

    text = "I live in Sacramento. My daughter Emily was born on May 4, 2018. I spent $450 on bike repairs. In 2021, I graduated from Stanford."
    facts = extract_episodic_facts(
        text,
        tenant_id=TENANT,
        user_id=USER,
        evidence_ids=cids,
        trust_tier=trust,
        access_policy=policy,
    )

    assert len(facts.assertions) >= 4
    for a in facts.assertions:
        assert a.tenant_id == TENANT
        assert a.user_id == USER
        assert a.source_evidence_cids == cids
        assert a.trust_tier == trust
        assert a.access_policy == policy

    assert len(facts.relations) >= 4
    for r in facts.relations:
        assert r.tenant_id == TENANT
        assert r.source_evidence_cids == cids
        assert r.access_policy == policy


# ==============================================================================
# 4. Atomic Supersession Across Storage Engines (Local & SQLite)
# ==============================================================================


def test_atomic_supersession_local_memory_engine() -> None:
    engine = LocalMemoryEngine()
    cid1 = _seed_evidence(engine, TENANT, USER, "First residence statement")
    cid2 = _seed_evidence(engine, TENANT, USER, "Second residence statement")

    # Step 1: In 2022, user lived in Sacramento
    t1 = "I live in Sacramento."
    f1 = extract_episodic_facts(
        t1, tenant_id=TENANT, user_id=USER,
        valid_from=datetime(2022, 1, 1, 0, 0, 0, tzinfo=UTC),
        evidence_ids=[cid1],
    )
    for a in f1.assertions:
        engine.upsert_assertion(a)

    # Verify Sacramento is active
    active = [a for a in engine.assertions.values() if a.predicate == "residence" and a.status == "active"]
    assert len(active) == 1
    assert active[0].object == "Sacramento"

    # Step 2: In 2024, user moved to San Diego
    t2 = "In 2024, I moved to San Diego."
    f2 = extract_episodic_facts(
        t2, tenant_id=TENANT, user_id=USER,
        evidence_ids=[cid2],
    )
    for a in f2.assertions:
        engine.upsert_assertion(a)

    # Verify San Diego is active and Sacramento is superseded
    all_res = [a for a in engine.assertions.values() if a.predicate == "residence"]
    assert len(all_res) == 2

    active_res = next(a for a in all_res if a.status == "active")
    superseded_res = next(a for a in all_res if a.status == "superseded")

    assert active_res.object == "San Diego"
    assert active_res.valid_from == datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)

    assert superseded_res.object == "Sacramento"
    assert superseded_res.superseded_by == active_res.id
    assert superseded_res.valid_to == active_res.valid_from


def test_atomic_supersession_sqlite_engine() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = SqliteEngine(tmpdir)
        cid1 = _seed_evidence(engine, TENANT, USER, "First residence statement")
        cid2 = _seed_evidence(engine, TENANT, USER, "Second residence statement")

        # Step 1: Sacramento in 2022
        t1 = "I live in Sacramento."
        f1 = extract_episodic_facts(
            t1, tenant_id=TENANT, user_id=USER,
            valid_from=datetime(2022, 1, 1, 0, 0, 0, tzinfo=UTC),
            evidence_ids=[cid1],
        )
        for a in f1.assertions:
            engine.upsert_assertion(a)

        # Step 2: San Diego in 2024
        t2 = "In 2024, I moved to San Diego."
        f2 = extract_episodic_facts(
            t2, tenant_id=TENANT, user_id=USER,
            evidence_ids=[cid2],
        )
        for a in f2.assertions:
            engine.upsert_assertion(a)

        # Query SQLite assertions table
        with engine._connect(TENANT) as conn:
            rows = conn.execute(
                "SELECT id, subject, predicate, object, status, valid_from, superseded_by "
                "FROM assertions WHERE tenant_id = ? AND predicate = 'residence'",
                (TENANT,),
            ).fetchall()

        assert len(rows) == 2
        rows_by_status = {r["status"]: dict(r) for r in rows}

        assert "active" in rows_by_status
        assert "superseded" in rows_by_status

        active = rows_by_status["active"]
        superseded = rows_by_status["superseded"]

        assert active["object"] == "San Diego"
        assert superseded["object"] == "Sacramento"
        assert superseded["superseded_by"] == active["id"]


# ==============================================================================
# 5. Integration via MemoryTools.working_consolidate
# ==============================================================================


@pytest.mark.parametrize("engine_type", ["local", "sqlite"])
def test_working_consolidate_episodic_fact_extraction(engine_type: str) -> None:
    if engine_type == "local":
        engine: Any = LocalMemoryEngine()
    else:
        tmp = tempfile.mkdtemp()
        engine = SqliteEngine(tmp)

    tools = MemoryTools(engine)
    cid = _seed_evidence(engine, TENANT, USER, "Conversation transcript with milestone")
    now = datetime.now(UTC)
    identity = _make_identity()

    # Seed conversation_turn working memory item containing episodic facts
    tools.working_seed(
        tenant_id=TENANT,
        session_id=SESSION,
        user_id=USER,
        agent_id=AGENT,
        task_id="task-episodic-1",
        branch="main",
        kind="conversation_turn",
        content="I moved to San Diego in 2024. My daughter Emily was born on May 4, 2018. I spent $450 on bike repairs. In 2021, I graduated from Stanford.",
        evidence_ids=[cid],
        ttl_seconds=1800,
        created_at=now.isoformat(),
        session_identity=identity,
    )

    # Seed an intermediate conclusion as well to verify coexistence
    tools.working_seed(
        tenant_id=TENANT,
        session_id=SESSION,
        user_id=USER,
        agent_id=AGENT,
        task_id="task-episodic-1",
        branch="main",
        kind="intermediate_conclusion",
        content="User has moved across California recently",
        evidence_ids=[cid],
        ttl_seconds=1800,
        created_at=(now + timedelta(seconds=1)).isoformat(),
        session_identity=identity,
    )

    # Consolidate working memory
    res = tools.working_consolidate(
        tenant_id=TENANT,
        session_id=SESSION,
        user_id=USER,
        agent_id=AGENT,
        task_id="task-episodic-1",
        branch="main",
        as_of=(now + timedelta(seconds=10)).isoformat(),
        session_identity=identity,
    )

    assert res["consolidated_count"] >= 5
    assert "assertions" in res
    assert "relations" in res

    predicates = {a["predicate"] for a in res["assertions"]}
    assert "conclusion" in predicates
    assert "residence" in predicates
    assert "has_family" in predicates
    assert "expense" in predicates
    assert any(p in predicates for p in {"education", "milestone"})

    # Check relation targets and provenance
    relation_targets = {r["target"] for r in res["relations"]}
    assert "San Diego" in relation_targets
    assert "Emily" in relation_targets
    assert "bike repairs" in relation_targets
    assert "Stanford" in relation_targets

    for r in res["relations"]:
        assert cid in r["source_evidence_cids"]


def test_working_expire_with_episodic_consolidation() -> None:
    engine = LocalMemoryEngine()
    tools = MemoryTools(engine)
    cid = _seed_evidence(engine, TENANT, USER, "Expiring episodic evidence")
    now = datetime.now(UTC)
    identity = _make_identity()
    consolidator_identity = SessionIdentity(
        tenant_id=TENANT,
        user_id=USER,
        role="consolidator",
        source_trust_tier=0,
        agent_id=AGENT,
        session_id=SESSION,
    )

    # Seed a short-lived conversation turn
    tools.working_seed(
        tenant_id=TENANT,
        session_id=SESSION,
        user_id=USER,
        agent_id=AGENT,
        task_id="task-expire-facts",
        branch="main",
        kind="conversation_turn",
        content="I live in Sacramento. In 2021, I graduated from Stanford.",
        evidence_ids=[cid],
        ttl_seconds=60,
        created_at=now.isoformat(),
        session_identity=identity,
    )

    # Expire at now + 120s with consolidate=True
    exp_res = tools.working_expire(
        tenant_id=TENANT,
        session_id=SESSION,
        user_id=USER,
        agent_id=AGENT,
        task_id="task-expire-facts",
        branch="main",
        expired_at=(now + timedelta(seconds=120)).isoformat(),
        role="consolidator",
        source_trust_tier=0,
        session_identity=consolidator_identity,
        consolidate=True,
    )

    assert "consolidated" in exp_res
    assertions = exp_res["consolidated"]["assertions"]
    relations = exp_res["consolidated"]["relations"]

    assert any(a["predicate"] == "residence" and a["object"] == "Sacramento" for a in assertions)
    assert any("Stanford" in a["object"] for a in assertions)
    assert len(relations) >= 2
