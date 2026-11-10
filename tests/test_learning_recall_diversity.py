"""Repeated captured requests must not crowd useful evidence out of recall."""

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.models import Assertion, Evidence, parse_dt
from mnemosyne.policy import OperatingPolicy
from mnemosyne.sqlite_engine import SqliteEngine


@pytest.mark.parametrize("backend", ["local", "sqlite"])
@pytest.mark.parametrize("mixed", [False, True], ids=["sources", "mixed-memory"])
def test_repeated_requests_leave_room_for_the_answer(tmp_path, backend, mixed):
    policy = OperatingPolicy(top_k=3, rerank_width=8)
    engine = (
        SqliteEngine(tmp_path / "memory", policy=policy)
        if backend == "sqlite" else LocalMemoryEngine(policy=policy)
    )
    runtime = LearningRuntime(engine)
    query = "Where is the project release checklist stored?"
    answer = engine.append_evidence(Evidence(
        tenant_id="t", user_id="u", actor="user", source_type="note",
        content="The project release checklist is stored in docs/release/checklist.md.",
        trust_tier=0, access_policy={"tenant": "t"},
    ))
    if mixed:
        engine.upsert_assertion(Assertion(
            tenant_id="t", user_id="u", subject="project release", predicate="has",
            object="a checklist", source_evidence_cids=[answer], confidence=0.9,
            trust_tier=0, access_policy={"tenant": "t"},
        ))
    requests = []
    for i in range(40):
        observed = runtime.observe_turn("t", "u", f"chat-{i}", query, "")
        episode = runtime.writer.read("t")["episodes"][observed["episode_id"]]
        requests.extend(episode["source_cids"])

    result = engine.retrieve(query, tenant_id="t", record_access=False,
                             filt={"user_id": "u", "principal": "u"})

    assert answer in {hit.id for hit in result.hits}
    assert sum(hit.text == query for hit in result.hits) == 1
    # Diversity is a read-time choice, not erasure or merged source custody.
    assert len(set(requests)) == 40
    assert all(engine.get_evidence("t", cid).content == query for cid in requests)
    question = next(hit for hit in result.hits if hit.text == query)
    assert question.id in requests
    assert question.provenance == [question.id]
    other_user = engine.retrieve(query, tenant_id="t", record_access=False,
                                 filt={"user_id": "other", "principal": "other"})
    assert not set(requests) & {hit.id for hit in other_user.hits}


@pytest.mark.parametrize("backend", ["local", "sqlite"])
@pytest.mark.parametrize("source_type,history", [
    ("learning_turn", "ordered"), ("learning_turn", "deep"),
    ("learning_turn", "as_of"), ("event", "ordinary"),
])
def test_repeated_events_keep_their_history_and_non_transcript_identity(tmp_path, backend, source_type, history):
    policy = OperatingPolicy(top_k=5, rerank_width=8)
    engine = (
        SqliteEngine(tmp_path / "history", policy=policy)
        if backend == "sqlite" else LocalMemoryEngine(policy=policy)
    )
    cids = [engine.append_evidence(Evidence(
        tenant_id="t", user_id="u", actor="user", source_type=source_type,
        content="I checked the project release checklist.",
        document_segment_id=f"event-{day}", created_at=parse_dt(f"2026-11-0{day}T12:00:00Z"),
        trust_tier=0, access_policy={"tenant": "t"},
    )) for day in range(1, 4)]
    query = (
        "Show the project release checklist history earliest to latest"
        if history == "ordered" else "project release checklist"
    )
    filt = {
        "user_id": "u", "principal": "u", "evaluated_at": "2026-11-09T12:00:00Z",
    }
    if history == "as_of":
        filt["as_of"] = "2026-11-09T12:00:00Z"
    result = engine.retrieve(query, tenant_id="t", record_access=False,
                             deep=history == "deep", filt=filt)
    assert {hit.id for hit in result.hits} == set(cids)
    if history == "ordered":
        assert [hit.id for hit in result.hits] == cids


@pytest.mark.parametrize("backend", ["local", "sqlite"])
def test_identical_shared_turns_preserve_distinct_authors(tmp_path, backend):
    policy = OperatingPolicy(top_k=5, rerank_width=8, max_sensitivity=2)
    engine = (
        SqliteEngine(tmp_path / "shared", policy=policy)
        if backend == "sqlite" else LocalMemoryEngine(policy=policy)
    )
    owners = {}
    for owner in ("alice", "bob"):
        cid = engine.append_evidence(Evidence(
            tenant_id="t", user_id=owner, actor="user", source_type="learning_turn",
            content="The project release checklist is ready.",
            sensitivity=2, trust_tier=0,
            access_policy={"tenant": "t"},
        ))
        owners[cid] = owner
    assert len(owners) == 2
    # The agent role can read these tenant-shared S2 sources directly.
    result = engine.retrieve("project release checklist", tenant_id="t", record_access=False,
                             filt={"max_sensitivity": 2, "role": "agent"})
    assert sorted(owners[hit.id] for hit in result.hits) == ["alice", "bob"]
