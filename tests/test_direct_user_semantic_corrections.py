"""Natural language corrections preserve value, owner, time and raw custody."""
from datetime import UTC, datetime, timedelta
from copy import deepcopy
import json
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

import pytest

from mnemosyne.belief import BeliefRevisionCore
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.memory_formation import project_direct_user_memory, preview_direct_user_memory
from mnemosyne.models import Assertion, Evidence
from mnemosyne.sqlite_engine import SqliteEngine

START = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture(params=["local", "sqlite"])
def engine(request, tmp_path):
    store = LocalMemoryEngine() if request.param == "local" else SqliteEngine(tmp_path / "memory")
    yield store
    store.close()


def capture(engine, text, day=0, user="alice", trust=1, metadata=None):
    cid = engine.append_evidence(Evidence(
        tenant_id="t", user_id=user, actor="user", source_type="chat", content=text,
        created_at=START + timedelta(days=day), trust_tier=trust, metadata=metadata or {},
        document_segment_id=sha256(f"{user}-{day}-{text}".encode()).hexdigest(),
        access_policy={"tenant": "t", "allow_principals": [user]},
    ))
    result = project_direct_user_memory(engine, "t", cid)
    return cid, result


def assertions(engine):
    return engine.export_tenant("t")["assertions"]


@pytest.mark.parametrize("positive,negative,predicate,obj", [
    ("I like coffee.", "I do not like coffee.", "do_not_like", "coffee"),
    ("I prefer dark mode.", "I no longer prefer dark mode.", "not_prefer", "dark mode"),
    ("I live in Paris.", "I no longer live in Paris.", "not_residence", "Paris"),
    ("I live in Paris.", "I don't live in Paris.", "not_residence", "Paris"),
])
def test_explicit_negation_supersedes_same_value_and_closes_graph(engine, positive, negative, predicate, obj):
    first_cid, first = capture(engine, positive)
    _, second = capture(engine, negative, day=1)
    state = {row["id"]: row for row in assertions(engine)}
    old, new = state[first["assertion_ids"][0]], state[second["assertion_ids"][0]]
    assert old["status"] == "superseded"
    assert old["valid_to"] == "2026-01-02T00:00:00Z"
    assert old["superseded_by"] == new["id"]
    assert (new["predicate"], new["object"], new["status"]) == (predicate, obj, "active")
    assert engine.get_evidence("t", first_cid).content == positive
    for row in engine.export_tenant("t")["relations"]:
        if row["id"] in first["relation_ids"]:
            assert row["valid_to"] == old["valid_to"]
    hits = engine.retrieve(obj, "t", filt={"user_id": "alice", "principal": "alice"}).hits
    assert old["id"] not in {hit.id for hit in hits if hit.kind == "assertion"}
    assert new["id"] in {hit.id for hit in hits if hit.kind == "assertion"}
    # Replaying the old source never revives the corrected claim or edge.
    project_direct_user_memory(engine, "t", first_cid)
    assert {row["id"]: row for row in assertions(engine)}[old["id"]]["status"] == "superseded"


def test_opposite_polarity_preserves_other_values_and_owners(engine):
    for text, day, user in [
        ("I like tea.", 0, "alice"), ("I like coffee.", 0, "alice"),
        ("I like coffee.", 0, "bob"), ("I do not like coffee.", 1, "alice"),
        ("I do not like cocoa.", 2, "alice"), ("I like coffee.", 3, "alice"),
    ]:
        capture(engine, text, day, user)
    active = {(r["user_id"], r["predicate"], r["object"]) for r in assertions(engine) if r["status"] == "active"}
    assert active == {("alice", "like", "tea"), ("alice", "like", "coffee"),
                      ("alice", "do_not_like", "cocoa"), ("bob", "like", "coffee")}


def test_historical_state_is_attested_only_in_reported_interval(engine):
    capture(engine, "I live in Berlin.", day=0)
    cid, result = capture(engine, "I lived in Paris in 2020.", day=1)
    state = {r["id"]: r for r in assertions(engine)}
    old = state[result["assertion_ids"][0]]
    assert old["status"] == "superseded"
    assert old["valid_from"] == "2020-01-01T00:00:00Z"
    assert old["valid_to"] == "2021-01-01T00:00:00Z"
    assert old["calibration"]["qualifiers"]["current_state"] == "unknown"
    assert old["calibration"]["source_quote"] == "I lived in Paris in 2020."
    assert [r["object"] for r in state.values() if r["status"] == "active"] == ["Berlin"]
    assert all(r["valid_to"] for r in engine.export_tenant("t")["relations"] if cid in r["source_evidence_cids"])
    hits = engine.retrieve("Paris residence", "t", filt={"user_id": "alice", "principal": "alice"}).hits
    assert old["id"] not in {h.id for h in hits if h.kind == "assertion"}


@pytest.mark.parametrize("text", ["I lived in Paris.", "I lived in Paris since 2020.", "I was a software engineer.", "I used to live in Paris."])
def test_unknown_historical_end_is_never_invented(engine, text):
    cid, result = capture(engine, text)
    row = next(r for r in assertions(engine) if r["id"] in result["assertion_ids"])
    assert row["status"] == "superseded"
    assert row["valid_to"] is None
    assert row["calibration"]["qualifiers"]["end_known"] is False
    assert not [r for r in engine.export_tenant("t")["relations"] if cid in r["source_evidence_cids"]]


@pytest.mark.parametrize("text,expected", [
    ("I am a software engineer.", {("user", "is_a", "software engineer")}),
    ("I'm a software engineer.", {("user", "is_a", "software engineer")}),
    ("My name is Alice.", {("user", "name", "Alice")}),
    ("My daughter Emma was born on May 4, 2018.", {("user", "has_family", "Emma")}),
    ("I live in Paris and work at Acme.", {("user", "residence", "Paris"), ("user", "work_at", "Acme")}),
    ("I live in Paris and I work at Acme.", {("user", "residence", "Paris"), ("user", "work_at", "Acme")}),
    ("In May 2020, I moved to Paris.", {("user", "residence", "Paris")}),
])
def test_durable_personal_grammar_preserves_original_source(engine, text, expected):
    cid, _ = capture(engine, text)
    rows = assertions(engine)
    assert {(r["subject"], r["predicate"], r["object"]) for r in rows} == expected
    assert all(r["calibration"]["source_quote"] in text for r in rows)
    assert all(r["user_id"] == "alice" and r["trust_tier"] == 1 and r["source_evidence_cids"] == [cid] for r in rows)
    assert engine.get_evidence("t", cid).content == text


@pytest.mark.parametrize("text", [
    "I mean inside of Brave Browser.", "I see a button.", "I clicked the settings button.",
    "I need you to open Brave.", "I may live in Paris.", "My daughter may be a student.",
])
def test_operational_or_uncertain_claims_stay_raw_only(engine, text):
    cid, result = capture(engine, text)
    assert not result["assertion_ids"]
    assert not result["relation_ids"]
    assert engine.get_evidence("t", cid).content == text


def test_belief_core_recognizes_negation_and_trust_scope():
    engine = LocalMemoryEngine()
    core = BeliefRevisionCore(engine)
    positive = Assertion(tenant_id="t", user_id="alice", subject="user", predicate="likes", object="coffee", status="active", valid_from=START, trust_tier=0)
    original = core.revise(positive)
    weak = Assertion(tenant_id="t", user_id="alice", subject="user", predicate="do_not_like", object="coffee", status="active", valid_from=START+timedelta(days=1), trust_tier=3)
    weak_id = engine.upsert_assertion(weak)
    assert next(r for r in assertions(engine) if r["id"] == weak_id)["status"] == "superseded"
    weak.trust_tier = 0
    revised = core.revise(weak)
    assert revised.operation == "SUPERSEDE"
    assert revised.contradictions
    assert original.assertion_id in revised.affected_assertion_ids


def test_repair_preview_is_deterministic_and_preserves_raw_and_manual_records(engine):
    cid, _ = capture(engine, "I mean inside of Brave Browser.")
    identity = ["direct-user-assertion", "t", "alice", "main", cid, "user", "mean", "inside of Brave Browser", {}]
    malformed = Assertion(tenant_id="t", user_id="alice", subject="user", predicate="mean", object="inside of Brave Browser", status="active", source_evidence_cids=[cid], calibration={"source_quote": "I mean inside of Brave Browser."}, id=str(uuid5(NAMESPACE_URL, json.dumps(identity, sort_keys=True))))
    engine.upsert_assertion(malformed)
    before = deepcopy(engine.export_tenant("t"))
    preview = preview_direct_user_memory(engine, "t", cid)
    assert preview == preview_direct_user_memory(engine, "t", cid)
    assert preview["obsolete_assertion_ids"] == [malformed.id]
    assert preview["assertions"] == []
    assert engine.export_tenant("t") == before


def test_historical_negation_does_not_retract_present_residence(engine):
    capture(engine, "I live in Paris.")
    capture(engine, "I did not live in Paris in 2020.", day=1)
    active = [r for r in assertions(engine) if r["status"] == "active"]
    assert [(r["predicate"], r["object"]) for r in active] == [("residence", "Paris")]
    historical = next(r for r in assertions(engine) if r["predicate"] == "not_residence")
    assert historical["valid_to"] == "2021-01-01T00:00:00Z"


def test_owned_property_negation_keeps_its_value_and_polarity(engine):
    capture(engine, "My name is Alice.")
    capture(engine, "My name is not Alice.", day=1)
    active = [r for r in assertions(engine) if r["status"] == "active"]
    assert [(r["predicate"], r["object"]) for r in active] == [("not_name", "Alice")]


def test_out_of_order_projection_does_not_create_current_positive_edge(engine):
    capture(engine, "I do not like coffee.", day=2)
    capture(engine, "I like coffee.", day=0)
    relations = engine.export_tenant("t")["relations"]
    assert all(r["valid_to"] == "2026-01-03T00:00:00Z" for r in relations if r["predicate"] == "like")


def test_preview_supported_projection_is_deterministic(engine):
    cid, _ = capture(engine, "I am a software engineer.")
    assert preview_direct_user_memory(engine, "t", cid) == preview_direct_user_memory(engine, "t", cid)


def test_postgres_semantic_correction_live():
    import os
    from uuid import uuid4
    from mnemosyne.postgres_engine import PostgresEngine

    dsn = os.environ.get("MNEMOSYNE_POSTGRES_DSN")
    if not dsn:
        pytest.skip("MNEMOSYNE_POSTGRES_DSN is not set")
    pytest.importorskip("psycopg")
    store = PostgresEngine(dsn)
    tenant, user = str(uuid4()), str(uuid4())
    try:
        first = store.upsert_assertion(Assertion(
            tenant_id=tenant, user_id=user, subject="user", predicate="like", object="coffee",
            status="active", valid_from=START, trust_tier=0,
        ))
        second = store.upsert_assertion(Assertion(
            tenant_id=tenant, user_id=user, subject="user", predicate="do_not_like", object="coffee",
            status="active", valid_from=START + timedelta(days=1), trust_tier=0,
        ))
        rows = {r["id"]: r for r in store.export_tenant(tenant)["assertions"]}
        assert rows[first]["status"] == "superseded"
        assert rows[first]["superseded_by"] == second
        assert rows[second]["status"] == "active"
    finally:
        store.close()
