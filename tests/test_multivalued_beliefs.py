"""Compatible personal facts coexist while targeted corrections stay scoped."""

from datetime import UTC, datetime, timedelta

import pytest

from mnemosyne.belief import BeliefRevisionCore
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.episodic_facts import extract_episodic_facts
from mnemosyne.mcp_tools import MemoryTools
from mnemosyne.models import Assertion, Evidence, Relation
from mnemosyne.sqlite_engine import SqliteEngine


START = datetime(2026, 11, 1, tzinfo=UTC)


@pytest.fixture(params=["local", "sqlite"])
def engine(request, tmp_path):
    store = LocalMemoryEngine() if request.param == "local" else SqliteEngine(tmp_path / "memory")
    yield store
    store.close()


def pet(engine, name, *, user="alice", day=0):
    timestamp = START + timedelta(days=day)
    text = f"I have a dog named {name}."
    policy = {"tenant": "t", "allow_principals": [user]}
    cid = engine.append_evidence(Evidence(
        tenant_id="t", user_id=user, actor="user", source_type="chat", content=text,
        created_at=timestamp, trust_tier=0, access_policy=policy,
        document_segment_id=f"{user}-{name}-{day}",
    ))
    facts = extract_episodic_facts(text, tenant_id="t", user_id=user,
                                  source_evidence_cids=[cid], created_at=timestamp,
                                  trust_tier=0, access_policy=policy)
    fact = next(row for row in facts.assertions if row.predicate == "has_pet")
    return engine.upsert_assertion(fact)


def rows(engine):
    return {row["id"]: row for row in engine.export_tenant("t")["assertions"]}


def test_two_dogs_remain_current_and_keep_original_validity(engine):
    first = pet(engine, "Buster")
    second = pet(engine, "Fido", day=1)
    state = rows(engine)
    assert first != second
    assert {state[first]["status"], state[second]["status"]} == {"active"}
    assert state[first]["valid_from"] == START.isoformat().replace("+00:00", "Z")
    assert state[first]["valid_to"] is None
    assert state[first]["superseded_by"] is None


def test_same_named_pet_owned_by_different_users_is_not_reinforced(engine):
    first = pet(engine, "Buster", user="alice")
    second = pet(engine, "Buster", user="bob")
    assert first != second
    state = rows(engine)
    assert state[first]["user_id"] == "alice"
    assert state[second]["user_id"] == "bob"
    assert set(state[first]["source_evidence_cids"]).isdisjoint(state[second]["source_evidence_cids"])
    assert state[first]["access_policy"]["allow_principals"] == ["alice"]


def test_single_value_changes_only_for_its_owner_and_scope(engine):
    ids = []
    for user, scope, place, day in (
        ("alice", {}, "Paris", 0), ("bob", {}, "Rome", 1),
        ("alice", {"home": "holiday"}, "Oslo", 2), ("alice", {}, "Berlin", 3),
    ):
        ids.append(engine.upsert_assertion(Assertion(
            tenant_id="t", user_id=user, subject="user", predicate="residence",
            object=place, scope=scope, valid_from=START + timedelta(days=day),
            status="active", trust_tier=0,
        )))
    state = rows(engine)
    assert state[ids[0]]["status"] == "superseded"
    assert all(state[identifier]["status"] == "active" for identifier in ids[1:])
    assert state[ids[0]]["valid_to"] == (START + timedelta(days=3)).isoformat().replace("+00:00", "Z")


def test_explicit_supersede_replaces_one_pet_only(engine):
    first = pet(engine, "Buster")
    second = pet(engine, "Fido", day=1)
    result = MemoryTools(engine).supersede(
        "t", "alice", first, {"object": "Barney"},
        valid_from=(START + timedelta(days=2)).isoformat(),
    )
    state = rows(engine)
    assert state[first]["status"] == "superseded"
    assert state[first]["superseded_by"] == result["id"]
    assert state[second]["status"] == "active"
    assert state[result["id"]]["user_id"] == "alice"
    assert state[result["id"]]["object"] == "Barney"
    assert state[result["id"]]["status"] == "active"


def test_targeted_replacement_cannot_cross_owner(engine):
    first = pet(engine, "Buster", user="alice")
    before = rows(engine)
    with pytest.raises((PermissionError, ValueError)):
        engine.upsert_assertion(Assertion(
            tenant_id="t", user_id="bob", subject="user", predicate="has_pet",
            object="Fido", scope={"species": "dog"}, status="active",
            calibration={"replaces_assertion_id": first},
        ))
    assert rows(engine) == before


def test_reinforcement_keeps_other_additive_values(engine):
    first = pet(engine, "Buster")
    second = pet(engine, "Fido", day=1)
    assert pet(engine, "Buster", day=2) == first
    assert rows(engine)[second]["status"] == "active"


def test_belief_core_adds_compatible_facts_without_contradictions():
    engine = LocalMemoryEngine()
    core = BeliefRevisionCore(engine)
    for day, name in enumerate(("Buster", "Fido")):
        report = core.revise(Assertion(
            tenant_id="t", user_id="alice", subject="user", predicate="has_pet",
            object=name, scope={"species": "dog"}, status="active",
            valid_from=START + timedelta(days=day),
        ))
        assert report.operation == "ADD"
        assert report.contradictions == []
    assert len(rows(engine)) == 2


def test_explicit_removal_keeps_other_pet():
    engine = LocalMemoryEngine()
    first = pet(engine, "Buster")
    second = pet(engine, "Fido", day=1)
    report = BeliefRevisionCore(engine).contract("t", first, reason="user removed this pet")
    assert report.operation == "CONTRACTION"
    assert rows(engine)[first]["status"] == "retracted"
    assert rows(engine)[second]["status"] == "active"


def test_replacement_to_existing_member_reuses_it_and_closes_target(engine):
    first = pet(engine, "Buster")
    second = pet(engine, "Fido", day=1)
    result = MemoryTools(engine).supersede(
        "t", "alice", first, {"object": "Fido"},
        valid_from=(START + timedelta(days=2)).isoformat(),
    )
    assert result["id"] == second
    state = rows(engine)
    assert len(state) == 2
    assert state[first]["superseded_by"] == second
    assert state[first]["status"] == "superseded"
    assert state[second]["status"] == "active"


def test_replaying_applied_replacement_remains_idempotent(engine):
    first = pet(engine, "Buster")
    result = MemoryTools(engine).supersede(
        "t", "alice", first, {"object": "Barney"},
        valid_from=(START + timedelta(days=2)).isoformat(),
    )
    row = Assertion.from_dict(rows(engine)[result["id"]])
    assert engine.upsert_assertion(row) == result["id"]
    assert len(rows(engine)) == 2


def test_replacement_cannot_remove_a_more_trusted_member(engine):
    first = pet(engine, "Buster")
    weak = Assertion(
        tenant_id="t", user_id="alice", subject="user", predicate="has_pet",
        object="Barney", scope={"species": "dog"}, status="active", trust_tier=3,
        valid_from=START + timedelta(days=2), calibration={"replaces_assertion_id": first},
    )
    rejected = engine.upsert_assertion(weak)
    assert rows(engine)[first]["status"] == "active"
    assert rows(engine)[rejected]["status"] == "superseded"


def test_single_value_relation_closure_does_not_cross_source_owner(engine):
    old = []
    for user in ("alice", "bob"):
        cid = engine.append_evidence(Evidence(
            tenant_id="t", user_id=user, actor="user", source_type="chat",
            content="I live in Paris.", document_segment_id=user, trust_tier=0,
            access_policy={"tenant": "t", "allow_principals": [user]},
        ))
        engine.upsert_assertion(Assertion(
            tenant_id="t", user_id=user, subject="user", predicate="residence",
            object="Paris", valid_from=START, source_evidence_cids=[cid], status="active",
        ))
        relation = Relation(tenant_id="t", source="user", predicate="lives_in",
                            target="Paris", valid_from=START, source_evidence_cids=[cid])
        engine.add_relation(relation)
        old.append((cid, relation.id))
    engine.upsert_assertion(Assertion(
        tenant_id="t", user_id="alice", subject="user", predicate="residence",
        object="Berlin", valid_from=START + timedelta(days=1),
        source_evidence_cids=[old[0][0]], status="active",
    ))
    relations = {row["id"]: row for row in engine.export_tenant("t")["relations"]}
    assert relations[old[0][1]]["valid_to"] is not None
    assert relations[old[1][1]]["valid_to"] is None


def test_sqlite_concurrent_replacements_have_one_successor(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    path = tmp_path / "shared"
    first_engine, second_engine = SqliteEngine(path), SqliteEngine(path)
    target = pet(first_engine, "Buster")
    barrier = Barrier(2)

    def replace_member(engine, name):
        barrier.wait()
        try:
            return engine.upsert_assertion(Assertion(
                tenant_id="t", user_id="alice", subject="user", predicate="has_pet",
                object=name, scope={"species": "dog"}, status="active",
                valid_from=START + timedelta(days=2),
                calibration={"replaces_assertion_id": target},
            ))
        except ValueError:
            return None

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(replace_member, engine, name)
                       for engine, name in ((first_engine, "Fido"), (second_engine, "Barney"))]
            successors = [future.result() for future in futures]
        assert sum(value is not None for value in successors) == 1
        assert sum(row["status"] == "active" for row in rows(first_engine).values()) == 1
    finally:
        first_engine.close()
        second_engine.close()


def test_historical_graph_keeps_both_additive_members(engine):
    pet(engine, "Buster")
    pet(engine, "Fido", day=1)
    result = MemoryTools(engine).graph_as_of(
        "t", "user", "has_pet", (START + timedelta(days=2)).isoformat(), user_id="alice",
    )
    assert {row["object"] for row in result["assertions"]} == {"Buster", "Fido"}
