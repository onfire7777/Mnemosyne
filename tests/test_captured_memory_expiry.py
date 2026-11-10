"""Captured transient facts expire through every current source-custody read."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from mnemosyne.answering import AnswerReadContext
from mnemosyne.access_policy import evidence_expiry_deadline
from mnemosyne.engine import LocalMemoryEngine, WorkingMemoryItem
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.mcp_tools import MemoryTools
from mnemosyne.mental_models import MentalModelService
from mnemosyne.models import Assertion, Evidence
from mnemosyne.retrieval import projection_sources_readable, readable_working_items
from mnemosyne.sqlite_engine import SqliteEngine
from mnemosyne.security import SessionIdentity
from mnemosyne.text import hashing_embedding


TENANT = "captured-expiry"
QUERY = "temporary release checklist amber cabinet"
TEXT = "The temporary release checklist is in the amber cabinet."


@pytest.fixture(params=["local", "sqlite"])
def engine(request, tmp_path):
    store = (LocalMemoryEngine() if request.param == "local"
             else SqliteEngine(tmp_path / "memory"))
    yield store
    store.close()


@pytest.fixture
def clock(monkeypatch):
    instant = [datetime.now(UTC)]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant[0].astimezone(tz) if tz else instant[0].replace(tzinfo=None)

    monkeypatch.setattr("mnemosyne.access_policy.datetime", Clock)
    monkeypatch.setattr("mnemosyne.engine.utc_now", lambda: instant[0])
    monkeypatch.setattr("mnemosyne.retrieval.utc_now", lambda: instant[0])
    monkeypatch.setenv("MNEMOSYNE_RETRIEVAL_RESULT_CACHE_SIZE", "16")
    return instant


def capture(tools, metadata):
    return tools.capture(
        TENANT, "u", "user", "chat", TEXT, metadata=metadata,
    )["cid"]


def derive(engine, cid):
    return engine.upsert_assertion(Assertion(
        tenant_id=TENANT, user_id="u", subject="temporary release checklist",
        predicate="location", object="amber cabinet", source_evidence_cids=[cid],
        trust_tier=1, access_policy={"tenant": TENANT},
    ))


@pytest.mark.parametrize("key", ["expires_at", "valid_until"])
def test_expired_capture_and_derived_fact_are_not_recalled(engine, key):
    tools = MemoryTools(engine)
    cid = capture(tools, {key: "2000-01-01T00:00:00Z"})
    original = deepcopy(engine.get_evidence(TENANT, cid).to_dict())
    fact = derive(engine, cid)
    hits = tools.search(TENANT, QUERY, user_id="u")["hits"]
    assert not {cid, fact} & {hit["id"] for hit in hits}
    assert not projection_sources_readable(
        engine, [cid], tenant_id=TENANT, branch="main",
        filt={"tenant_id": TENANT, "user_id": "u"}, policy=engine.policy,
    )
    assert engine.get_evidence(TENANT, cid).to_dict() == original


@pytest.mark.parametrize("key", ["expires_at", "valid_until"])
def test_warm_reads_recheck_expiry_without_a_write(engine, clock, key):
    tools = MemoryTools(engine)
    deadline = clock[0] + timedelta(minutes=1)
    cid = capture(tools, {key: deadline.isoformat()})
    fact = derive(engine, cid)
    original = deepcopy(engine.get_evidence(TENANT, cid).to_dict())
    filt = {"tenant_id": TENANT, "user_id": "u"}
    for _ in range(2):
        result = engine.retrieve(QUERY, tenant_id=TENANT, record_access=False, filt=filt)
        assert {cid, fact} <= {hit.id for hit in result.hits}
    clock[0] = deadline
    result = engine.retrieve(QUERY, tenant_id=TENANT, record_access=False, filt=filt)
    assert not {cid, fact} & {hit.id for hit in result.hits}
    assert not {cid, fact} & {hit.id for hit in engine.vector_search(QUERY, 10, filt)}
    assert not {cid, fact} & {hit.id for hit in engine.lexical_search(QUERY, 10, filt)}
    # A historical query retains the current custody restriction.
    result = engine.retrieve(QUERY, tenant_id=TENANT, record_access=False,
                             filt={**filt, "as_of": (deadline - timedelta(seconds=1)).isoformat()})
    assert not {cid, fact} & {hit.id for hit in result.hits}
    assert engine.get_evidence(TENANT, cid).to_dict() == original


def test_expiry_flows_through_profile_and_learning_sources(engine, clock):
    tools = MemoryTools(engine)
    deadline = clock[0] + timedelta(minutes=1)
    cid = capture(tools, {"expires_at": deadline.isoformat()})
    summary = engine.append_evidence(Evidence(
        tenant_id=TENANT, user_id="u", actor="user", source_type="consolidation-summary",
        content=TEXT, metadata={"summary": {"source_evidence_cids": [cid]}},
        access_policy={"tenant": TENANT},
    ))
    profile = tools.profile_record_explicit(TENANT, "u", TEXT, source_evidence_cids=[summary])
    runtime = LearningRuntime(engine)
    assert runtime._sources_live(TENANT, [summary], "u")
    assert profile["id"] in {row["id"] for row in tools.profile_context(TENANT, "u")["authoritative"]}
    clock[0] = deadline
    assert not runtime._sources_live(TENANT, [summary], "u")
    assert tools.profile_context(TENANT, "u")["authoritative"] == []


def test_maintained_answer_snapshot_expires_without_source_mutation(engine, clock):
    tools = MemoryTools(engine)
    deadline = clock[0] + timedelta(minutes=1)
    cid = capture(tools, {"valid_until": deadline.isoformat()})
    service = MentalModelService(engine, lambda: pytest.fail("source snapshot needs no provider"))
    context = AnswerReadContext(tenant_id=TENANT, user_id="u", role="agent", max_sensitivity=0)
    before, sources = service._snapshot(context)
    assert cid in sources
    assert service._snapshot(context)[0] == before
    clock[0] = deadline
    after, sources = service._snapshot(context)
    assert after != before
    assert cid not in sources


@pytest.mark.parametrize("value", [
    "not-a-date", " ", {}, [], False, 0,
    "0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00",
])
def test_malformed_populated_expiry_fails_closed(value):
    deadline = evidence_expiry_deadline({}, {"expires_at": value})
    assert deadline == datetime.min.replace(tzinfo=UTC)


@pytest.mark.parametrize("value", ["2030-01-02T03:04:05Z", "2030-01-02T03:04:05", "2030-01-02T05:04:05+02:00"])
def test_metadata_expiry_uses_utc_and_earliest_constraint(value):
    expected = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert evidence_expiry_deadline(
        {"expires_at": "2031-01-01"}, {"expires_at": value, "valid_until": "2032-01-01"},
    ) == expected
    assert evidence_expiry_deadline({"expires_at": value}, {"valid_until": "2032-01-01"}) == expected
    assert evidence_expiry_deadline({}, {"valid_until": value}) == expected


def test_absent_expiry_preserves_durable_memory():
    assert evidence_expiry_deadline({}, {}) is None
    assert evidence_expiry_deadline(None, {"expires_at": None, "valid_until": ""}) is None


def test_thin_canary_rechecks_captured_source_expiry(clock):
    engine = LocalMemoryEngine()
    tools = MemoryTools(engine)
    deadline = clock[0] + timedelta(minutes=1)
    cid = capture(tools, {"expires_at": deadline.isoformat()})
    fact = derive(engine, cid)
    engine.branch("canary", kind="canary", tenant_id=TENANT)
    filt = {"tenant_id": TENANT, "branch": "canary", "user_id": "u"}
    assert {cid, fact} <= {hit.id for hit in engine.lexical_search(QUERY, 10, filt)}
    clock[0] = deadline
    assert not {cid, fact} & {hit.id for hit in engine.lexical_search(QUERY, 10, filt)}
    assert engine._overlays
    engine.close()


def test_persisted_capture_expiry_is_enforced_after_reload(tmp_path):
    path = tmp_path / "persisted"
    engine = SqliteEngine(path)
    cid = capture(MemoryTools(engine), {"valid_until": "2000-01-01T00:00:00Z"})
    original = deepcopy(engine.get_evidence(TENANT, cid).to_dict())
    engine.close()
    reloaded = SqliteEngine(path)
    try:
        assert MemoryTools(reloaded).search(TENANT, QUERY, user_id="u")["hits"] == []
        assert reloaded.get_evidence(TENANT, cid).to_dict() == original
    finally:
        reloaded.close()


def test_working_recall_rechecks_its_captured_source(engine, clock):
    tools = MemoryTools(engine)
    deadline = clock[0] + timedelta(minutes=1)
    cid = tools.capture(
        TENANT, "u", "user", "chat", TEXT, session_id="s",
        metadata={"expires_at": deadline.isoformat()},
    )["cid"]
    engine.put_working(WorkingMemoryItem(
        item_id="working-source", tenant_id=TENANT, session_id="s", user_id="u",
        agent_id="agent", task_id="checklist", kind="current_plan", content=TEXT,
        created_at=clock[0], expires_at=clock[0] + timedelta(hours=1), evidence_ids=[cid],
        metadata={"branch": "main"},
    ))
    identity = SessionIdentity(tenant_id=TENANT, user_id="u", role="agent",
                               source_trust_tier=1, agent_id="agent", session_id="s")
    scope = dict(tenant_id=TENANT, session_id="s", user_id="u", agent_id="agent",
                 task_id="checklist", branch="main", session_identity=identity)
    assert len(tools.working_query(**scope, as_of=clock[0])["items"]) == 1
    filt = {"user_id": "u", "principal": "u", "session_id": "s", "include_working": True}
    assert any(hit.kind == "working" for hit in engine.retrieve(
        QUERY, tenant_id=TENANT, filt=filt, record_access=False,
    ).hits)
    clock[0] = deadline
    assert tools.working_query(**scope, as_of=clock[0])["items"] == []
    assert engine.retrieve(QUERY, tenant_id=TENANT, filt=filt, record_access=False).hits == []


def test_source_free_working_adapter_items_retain_existing_behavior(engine):
    item = {"item_id": "working-local", "evidence_ids": []}
    assert readable_working_items(
        engine, [item], tenant_id=TENANT, filt={"user_id": "u"}, policy=engine.policy,
    ) == [item]


def test_expired_working_text_is_withheld_before_embedding(engine, clock):
    tools = MemoryTools(engine)
    cid = tools.capture(
        TENANT, "u", "user", "chat", TEXT, session_id="s",
        metadata={"expires_at": "2000-01-01T00:00:00Z"},
    )["cid"]
    engine.put_working(WorkingMemoryItem(
        item_id="expired-working-source", tenant_id=TENANT, session_id="s", user_id="u",
        agent_id="agent", task_id="checklist", kind="current_plan", content=TEXT,
        created_at=clock[0], expires_at=clock[0] + timedelta(hours=1), evidence_ids=[cid],
        metadata={"branch": "main"},
    ))

    class Recorder:
        name = "expiry-custody-recorder"
        dims = 64

        def __init__(self):
            self.texts = []

        def embed(self, text):
            self.texts.append(text)
            return hashing_embedding(text, dims=self.dims)

    recorder = Recorder()
    engine.adapters = replace(engine.adapters, embedding=recorder)
    result = engine.retrieve(QUERY, tenant_id=TENANT, record_access=False, filt={
        "user_id": "u", "principal": "u", "session_id": "s", "include_working": True,
    })
    assert result.hits == []
    assert TEXT not in recorder.texts
