"""Provider proposals complement source-grounded learning in one candidate stream."""

import json
import sys
from copy import deepcopy

import pytest

from mnemosyne.consolidation import CommandProcedureInducer
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.experience.receipts import digest
from mnemosyne.experience.sleep import _candidate, _patch_parent


def runtime_with_proposals(procedures):
    runtime = LearningRuntime(LocalMemoryEngine())
    runtime.engine.policy.learning_distill_mode = "provider"
    response = json.dumps({"procedures": procedures})
    runtime.procedure_inducer = CommandProcedureInducer(
        [sys.executable, "-c",
         f"import json,sys; json.load(sys.stdin); print({response!r})"]
    )
    return runtime


def failed_inspection(runtime, session="s", user="u", query="inspect task", task_type=None):
    receipt_ids = []
    if task_type is not None:
        context = runtime.prepare_context("t", user, session, query, task_type=task_type)
        receipt_ids.append(context["receipt_id"])
    observed = runtime.observe_turn(
        "t", user, session, query, "",
        receipt_ids=receipt_ids,
        tool_events=[{"name": "verifier", "source": "tool", "success": False,
                      "output": "inspect", "expected_steps": ["inspect"]}],
    )
    runtime.record_signal("t", episode_id=observed["episode_id"], kind="verifier",
                          value=-1, final=True)
    return observed["episode_id"]


def test_provider_with_no_proposals_preserves_grounded_local_learning():
    runtime = runtime_with_proposals([])
    episode_id = failed_inspection(runtime)
    runtime.consolidate("t")
    state = runtime.writer.read("t")
    assert len(state["artifacts"]) == 1
    item = next(iter(state["artifacts"].values()))
    assert item["steps"] == ["inspect"]
    assert item["state"] == "probation"
    assert item["source_episode_ids"] == [episode_id]
    assert state["policy"]["distillation"]["status"] == "proposals_evaluated"


def test_identical_provider_and_local_proposals_have_one_owned_artifact():
    proposal = {"name": "inspect", "body": "inspect", "signature": {"steps": ["inspect"]}}
    runtime = runtime_with_proposals([proposal, proposal])
    failed_inspection(runtime)
    runtime.consolidate("t")
    state = runtime.writer.read("t")
    assert len(state["artifacts"]) == 1
    item = next(iter(state["artifacts"].values()))
    assert item["state"] == "probation"
    assert item["proposal_record"]["cid"]
    assert len(item["proposal_records"]) == 1
    assert runtime.consolidate("t")["candidates"] == 0


def test_repeated_grounded_support_is_preserved_without_duplicate_candidates():
    runtime = runtime_with_proposals([])
    episode_ids = [failed_inspection(runtime, session=str(index)) for index in range(2)]
    runtime.consolidate("t")
    items = list(runtime.writer.read("t")["artifacts"].values())
    assert len(items) == 1
    assert items[0]["source_episode_ids"] == sorted(episode_ids)
    assert items[0]["explanation_sources"] == sorted(episode_ids)
    assert items[0]["scope_match"] == {"kind": "exact_query", "query": "inspect task"}


def test_repeated_same_task_does_not_create_broader_provider_duplicate():
    proposal = {"name": "inspect", "body": "inspect", "signature": {"steps": ["inspect"]}}
    runtime = runtime_with_proposals([proposal])
    episode_ids = [failed_inspection(runtime, session=str(index)) for index in range(2)]
    runtime.consolidate("t")
    items = list(runtime.writer.read("t")["artifacts"].values())
    assert len(items) == 1
    assert items[0]["source_episode_ids"] == sorted(episode_ids)
    assert items[0]["scope_match"] == {"kind": "exact_query", "query": "inspect task"}
    assert items[0]["proposal_record"]["cid"]


def test_case_only_queries_share_one_exact_candidate_and_all_sources():
    proposal = {"name": "inspect", "body": "inspect", "signature": {"steps": ["inspect"]}}
    runtime = runtime_with_proposals([proposal])
    ids = [failed_inspection(runtime, session=str(index), query=query, task_type="inspection")
           for index, query in enumerate(("Inspect task", "inspect task"))]
    runtime.consolidate("t")
    items = list(runtime.writer.read("t")["artifacts"].values())
    assert len(items) == 1
    assert items[0]["scope_match"]["query"].casefold() == "inspect task"
    assert items[0]["source_episode_ids"] == sorted(ids)
    assert items[0]["proposal_record"]["cid"]


@pytest.mark.parametrize("status", ["probation", "retired"])
@pytest.mark.parametrize("old_scope", [None, {"kind": "exact_query", "query": "Inspect task"}])
@pytest.mark.parametrize("owned_id", [False, True])
def test_previous_scope_identity_and_lifecycle_remain_authoritative(status, old_scope, owned_id):
    runtime = runtime_with_proposals([])
    for index in range(2):
        failed_inspection(runtime, session=str(index), query="Inspect task", task_type="inspection")
    runtime.consolidate("t")
    state = runtime.engine._learning_data["t"]
    current = next(iter(state["artifacts"].values()))
    old = deepcopy(current)
    old.update(scope_match=old_scope, conditions=[] if old_scope is None else [old_scope["query"]], state=status)
    old["id"] = digest([
        old["kind"], *(["t", "u"] if owned_id else []), old["task_class"], old["content"], old_scope,
    ])
    # Model a persisted artifact written before normalized exact-query identities.
    state["artifacts"] = {old["id"]: old}
    before = deepcopy(old)
    failed_inspection(runtime, session="new", query="inspect task", task_type="inspection")
    runtime.consolidate("t")
    assert runtime.writer.read("t")["artifacts"] == {old["id"]: before}


def test_alias_resolution_precedes_coalescing_candidate_provenance():
    runtime = runtime_with_proposals([])
    ids = [failed_inspection(runtime, session=str(index), query=query, task_type="inspection")
           for index, query in enumerate(("Inspect task", "inspect task"))]
    state = runtime.writer.read("t")
    episodes = [state["episodes"][key] for key in ids]
    old = _candidate(episodes[0]["task_class"], ["inspect"], episodes)
    old.update(scope_match=None, conditions=[])
    old["id"] = digest([old["kind"], "t", "u", old["task_class"], old["content"], None])
    runtime.writer.apply("t", "prior_candidate_fixture", lambda data: data["artifacts"].update({old["id"]: old}))
    runtime.consolidate("t")
    artifacts = runtime.writer.read("t")["artifacts"]
    assert list(artifacts) == [old["id"]]
    assert artifacts[old["id"]]["scope_match"] is None
    assert artifacts[old["id"]]["conditions"] == []
    assert artifacts[old["id"]]["source_episode_ids"] == sorted(ids)
    assert artifacts[old["id"]]["state"] == "probation"


def test_case_only_query_changes_keep_revision_parent_without_widening_scope():
    runtime = runtime_with_proposals([])
    source_ids = [failed_inspection(runtime, session=str(index), query="Inspect task", task_type="inspection")
                  for index in range(2)]
    episodes = [runtime.episode("t", key) for key in source_ids]
    parent = _candidate(episodes[0]["task_class"], ["inspect", "report"], episodes)
    parent["state"] = "active"
    before = deepcopy(parent)
    revised_episodes = [{**episode, "user_text": "inspect task"} for episode in episodes]
    candidate = _candidate(parent["task_class"], ["inspect", "reports"], revised_episodes)
    assert _patch_parent(candidate, [parent]) is parent
    assert parent == before
    assert _patch_parent(candidate, [{**parent, "scope_match": None, "conditions": []}]) is None
    assert _patch_parent(candidate, [{**parent, "conditions": [*parent["conditions"], "production"]}]) is None


def test_synthesis_keeps_identical_content_owned_by_each_user():
    runtime = runtime_with_proposals([])
    for user in ("alice", "bob"):
        failed_inspection(runtime, session=user, user=user)
    runtime.consolidate("t")
    items = list(runtime.writer.read("t")["artifacts"].values())
    assert len(items) == 2
    assert {item["user_id"] for item in items} == {"alice", "bob"}
    assert len({item["id"] for item in items}) == 2


def test_coalesced_verified_hypotheses_keep_each_lifecycle_link():
    proposal = {"name": "inspect", "body": "inspect", "signature": {"steps": ["inspect"]}}
    runtime = runtime_with_proposals([proposal])
    observed = runtime.observe_turn(
        "t", "u", "s", "inspect task", "",
        tool_events=[{"name": "verifier", "source": "tool", "success": True,
                      "output": "inspect", "tested_steps": ["inspect"], "hypothesis_id": key}
                     for key in ("h1", "h2")],
    )
    runtime.record_signal("t", episode_id=observed["episode_id"], kind="verifier", value=1, final=True)
    episode = runtime.episode("t", observed["episode_id"])
    hypotheses = {key: {"id": key, "steps": ["inspect"], "content": "inspect",
                        "task_class": episode["task_class"], "user_id": "u",
                        "source_cids": episode["source_cids"], "source_episode_ids": [episode["id"]],
                        "status": "awaiting_external_verifier", "reward_weight": 0.0,
                        "reality_class": "self_generated", "shadow_only": True}
                  for key in ("h1", "h2")}
    runtime.writer.apply("t", "hypothesis_fixture", lambda state: state["policy"].update(hypotheses=hypotheses))
    runtime.consolidate("t")
    state = runtime.writer.read("t")
    assert len(state["artifacts"]) == 1
    item = next(iter(state["artifacts"].values()))
    assert item["state"] == "probation"
    for key in ("h1", "h2"):
        assert state["policy"]["hypotheses"][key]["status"] == "verified"
        assert state["policy"]["hypotheses"][key]["candidate_id"] == item["id"]
    assert item["proposal_record"]["cid"]


def test_sdk_legacy_api_worker_and_reload_share_one_learning_record(tmp_path):
    from mnemosyne.frameworks import AutoMemorySession
    from mnemosyne.jobs import RuntimeJobHandlers
    from mnemosyne.learning import LearningSystem
    from mnemosyne.mcp_tools import MemoryTools
    from mnemosyne.queue import InProcessQueue

    path = tmp_path / "memory.json"
    engine = LocalMemoryEngine(store_path=path)
    engine.policy.learning_distill_mode = "provider"
    worker = RuntimeJobHandlers(engine, InProcessQueue())
    session = AutoMemorySession(engine, "t", "u", session_id="s")
    provider = runtime_with_proposals([]).procedure_inducer
    tools = MemoryTools(engine, procedure_inducer=provider)
    captured = session.post_turn_capture(
        "inspect task", "The inspection failed.",
        tool_events=[{"name": "verifier", "source": "tool", "verdict": False,
                      "output": "inspect", "expected_steps": ["inspect"]}],
    )
    runtime = session.learning_runtime
    state = runtime.writer.read("t")
    procedure = next(row for row in state["artifacts"].values() if row["kind"] == "procedure")
    legacy = LearningSystem(engine)
    legacy.load_native(["t"])
    attribution = legacy.attribute_failure(captured["learning_episode"]["episode_id"])
    assert legacy.induce_procedure(legacy.induce_lesson(attribution)).id == procedure["id"]
    worker.run_learning_consolidation({"tenant_id": "t"})
    assert tools._learning_runtime().procedure_inducer is provider
    session.close()
    # Release the owning engine before reopening its journal.
    engine.close()
    restored = LocalMemoryEngine(store_path=path)
    try:
        state = LearningRuntime(restored).writer.read("t")
        procedures = [row for row in state["artifacts"].values() if row["kind"] == "procedure"]
        assert [row["id"] for row in procedures] == [procedure["id"]]
        assert procedures[0]["state"] == "probation"
        assert len(state["episodes"]) == 1
    finally:
        restored.close()
