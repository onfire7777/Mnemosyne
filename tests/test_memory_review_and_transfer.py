from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.hypotheses import process_reviews, typed_hypothesis
from mnemosyne.experience.hypothesis_sandbox import run_experiment
from mnemosyne.experience.receipts import digest
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.experience.task_contracts import grounded_contract
from mnemosyne.experience.utility import selection_utility, randomized_opportunity
from mnemosyne.models import Evidence


def queued(content, *, proposed=None, sandbox_check=None):
    runtime = LearningRuntime(LocalMemoryEngine())
    cid = runtime.engine.append_evidence(Evidence(
        tenant_id="t", user_id="u", actor="user", source_type="chat", trust_tier=1,
        content=content, access_policy={"tenant": "t", "allow_principals": ["u"]},
    ))
    row = {"id": "theory", "content": proposed or content, "source_cids": [cid],
           "source_episode_ids": [], "task_class": "x", "user_id": "u", "conditions": []}
    if sandbox_check:
        row.update(steps=[sandbox_check["expression"]], sandbox_check={
            **sandbox_check, "source_cid": cid, "source_quote": content})
    row = typed_hypothesis(runtime, "t", row)
    runtime.writer.apply("t", "queue_review", lambda state: state["policy"].update(hypotheses={row["id"]: row}))
    return runtime, cid


def test_content_only_review_projects_exact_supported_fact_once():
    runtime, _ = queued("I prefer concise answers.")
    assert process_reviews(runtime, "t")["reviewed"] == 1
    state = runtime.writer.read("t")
    review = state["policy"]["hypotheses"]["theory"]
    assert review["status"] == "verified"
    assert review["support"][0]["quote"] == "I prefer concise answers."
    assert runtime.engine.export_tenant("t")["assertions"]
    original = deepcopy(runtime.engine.export_tenant("t")["assertions"])
    assert process_reviews(runtime, "t")["reviewed"] == 0
    assert runtime.engine.export_tenant("t")["assertions"] == original
    assert state["episodes"] == {} and state["credit"] == {}


def test_unsupported_theory_stays_inconclusive_and_source_change_retries():
    runtime, cid = queued("I prefer concise answers.", proposed="Concise answers may cause better memory.")
    process_reviews(runtime, "t")
    assert runtime.writer.read("t")["policy"]["hypotheses"]["theory"]["status"] == "inconclusive"
    assert runtime.engine.export_tenant("t")["assertions"] == []
    runtime.engine.update_evidence_metadata("t", cid, {"review_revision": 2})
    assert process_reviews(runtime, "t")["reviewed"] == 1
    review = runtime.writer.read("t")["policy"]["hypotheses"]["theory"]
    assert review["review_attempts"] == 2
    assert any(item["reason"] == "source_version_changed" for item in review["review_history"])


def test_interrupted_review_recovers_after_lease():
    runtime, _ = queued("I prefer concise answers.")
    timestamp = datetime.now(UTC)
    runtime.writer.apply("t", "claim_review", lambda state: state["policy"]["hypotheses"]["theory"].update(
        status="running", lease_until=(timestamp + timedelta(minutes=5)).isoformat()))
    assert process_reviews(runtime, "t", now=timestamp)["reviewed"] == 0
    assert process_reviews(runtime, "t", now=timestamp + timedelta(minutes=6))["reviewed"] == 1
    assert runtime.writer.read("t")["policy"]["hypotheses"]["theory"]["status"] == "verified"


@pytest.mark.parametrize(("first", "second", "status"), [
    ("I like tea.", "I like coffee.", "inconclusive"),
    ("I live in Paris.", "I live in Berlin.", "verified"),
])
def test_contradiction_review_uses_cardinality_and_semantic_writer(first, second, status):
    runtime, cid = queued(first)
    other = runtime.engine.append_evidence(Evidence(tenant_id="t", user_id="u", actor="user", source_type="chat",
        trust_tier=1, content=second, access_policy={"tenant": "t", "allow_principals": ["u"]}))
    row = typed_hypothesis(runtime, "t", {"id": "conflict", "content": "Review conflicting source claims",
        "source_cids": [cid, other], "source_episode_ids": [], "task_class": "x", "user_id": "u"}, kind="contradiction")
    runtime.writer.apply("t", "queue_review", lambda state: state["policy"].update(hypotheses={"conflict": row}))
    process_reviews(runtime, "t")
    assert runtime.writer.read("t")["policy"]["hypotheses"]["conflict"]["status"] == status
    if status == "verified":
        claims = runtime.engine.export_tenant("t")["assertions"]
        assert any(claim["object"] == "Berlin" and claim["status"] == "active" for claim in claims)


@pytest.mark.parametrize("expression", ["__import__('os').system('whoami')", "value.__class__", "'x' * 1000000000"])
def test_sandbox_refuses_effects_and_unbounded_operations(expression):
    check = {"version": 1, "kind": "python_expression", "expression": expression,
             "cases": [{"input": [3, 1], "expected": [1, 3]}]}
    assert run_experiment(check)["status"] == "inconclusive"


@pytest.mark.parametrize(("expected", "status"), [([1, 3], "inconclusive"), ([3, 1], "rejected")])
def test_sandbox_records_real_result_without_manufacturing_live_reward(expected, status):
    check = {"version": 1, "kind": "python_expression", "expression": "sorted(value)",
             "cases": [{"input": [3, 1], "expected": expected}]}
    content = json.dumps({"expression": check["expression"], "cases": check["cases"]})
    runtime, _ = queued(content, sandbox_check=check)
    process_reviews(runtime, "t")
    state = runtime.writer.read("t")
    review = state["policy"]["hypotheses"]["theory"]
    assert review["status"] == status
    event = review["sandbox_event"]
    assert event["source"] == "tool" and event["check_id"].startswith("sandbox:")
    assert json.loads(event["output"])["results"][0]["actual"] == [1, 3]
    assert state["episodes"] == {} and state["credit"] == {} and state["artifacts"] == {}


def test_semantic_transfer_preserves_historical_identity_and_constraint_boundaries():
    runtime = LearningRuntime(LocalMemoryEngine())
    first = runtime.prepare_context("t", "u", "first", "fix the cache bug", ["shell"])
    outcome = runtime.observe_turn("t", "u", "first", "fix the cache bug", "",
        receipt_ids=[first["receipt_id"]], tool_events=[{"name": "shell", "source": "tool", "verdict": True,
                                                      "command": "pytest cache_tests", "output": "1 passed"}])
    runtime.resolve("t", outcome["episode_id"])
    before = deepcopy(runtime.episode("t", outcome["episode_id"]))
    second = runtime.prepare_context("t", "u", "second", "help me fix the caching issue", ["shell"])
    assert second["task_class"] == first["task_class"]
    receipt = runtime.writer.read("t")["receipts"][second["receipt_id"]]
    assert receipt["task_match"]["method"] == "semantic_applicability:v1"
    assert runtime.episode("t", outcome["episode_id"]) == before
    for query in ["fix the authentication issue", "fix the caching issue without deleting entries", "fix the cache invalidation bug"]:
        assert runtime.prepare_context("t", "u", query, query, ["shell"])["task_class"] != first["task_class"]


def roles(text, action, entity):
    def span(value):
        start = text.index(value)
        return {"start": start, "end": start + len(value), "quote": value}
    return {"version": 1, "intent": "fix", "action": span(action), "entity": span(entity), "constraints": []}


def test_provider_roles_cover_every_constraint_and_keep_literal_entities():
    text = "The cache bug needs fixing"
    proposal = roles(text, "fixing", "cache bug")
    result = grounded_contract(text, proposal, ["shell"], "normal")
    assert result["entity"] == "cache defect"
    assert grounded_contract(text + " without deleting entries", proposal, ["shell"], "normal") is None
    forged = deepcopy(proposal)
    forged["entity"]["quote"] = "authentication bug"
    assert grounded_contract(text, forged, ["shell"], "normal") is None
    assert grounded_contract(text, {**proposal, "required_tools": ["network"]}, ["shell"], "normal") is None


def test_provider_role_proof_runs_through_real_receipt_guard():
    runtime = LearningRuntime(LocalMemoryEngine())
    query = "fix the cache bug"
    first = runtime.prepare_context("t", "u", "first", query, ["shell"])
    observed = runtime.observe_turn("t", "u", "first", query, "", receipt_ids=[first["receipt_id"]],
        tool_events=[{"name": "shell", "source": "tool", "command": "pytest cache_tests", "output": "1 passed", "verdict": True}])
    runtime.resolve("t", observed["episode_id"])
    new_query = "The cache bug needs fixing"
    runtime.engine._learning_configuration = {"semantic_contract_proposer": lambda **_: {
        "matched_episode_id": observed["episode_id"], "query_roles": roles(new_query, "fixing", "cache bug"),
        "reference_roles": roles(query, "fix", "the cache bug")}}
    second = runtime.prepare_context("t", "u", "second", new_query, ["shell"])
    assert second["task_class"] == first["task_class"]
    proof = runtime.writer.read("t")["receipts"][second["receipt_id"]]["task_match"]
    assert proof["method"] == "grounded_semantic_applicability:v1"
    assert proof["source_cids"]


def test_live_consolidation_executes_reviews_without_manual_dispatch():
    runtime = LearningRuntime(LocalMemoryEngine())
    context = runtime.prepare_context("t", "u", "s", "I prefer concise answers.")
    observed = runtime.observe_turn("t", "u", "s", "I prefer concise answers.", "",
        receipt_ids=[context["receipt_id"]], tool_events=[{"name": "checker", "source": "tool", "verdict": True, "output": "passed"}])
    runtime.resolve("t", observed["episode_id"])
    result = runtime.consolidate("t")
    assert result["hypotheses_reviewed"] >= 1
    reviews = runtime.writer.read("t")["policy"]["hypotheses"]
    assert any(row["status"] == "verified" and row["review_contract"]["kind"] == "factual" for row in reviews.values())


def test_live_consolidation_discovers_and_executes_typed_experiment():
    runtime = LearningRuntime(LocalMemoryEngine())
    request = json.dumps({"version": 1, "kind": "python_expression", "expression": "sorted(value)",
                          "cases": [{"input": [4, 2], "expected": [2, 4]}]})
    context = runtime.prepare_context("t", "u", "s", request)
    captured = runtime.observe_turn("t", "u", "s", request, "", receipt_ids=[context["receipt_id"]],
        tool_events=[{"name": "checker", "source": "tool", "verdict": True, "output": "retained check"}])
    runtime.resolve("t", captured["episode_id"])
    runtime.consolidate("t")
    state = runtime.writer.read("t")
    experiments = [row for row in state["policy"]["hypotheses"].values() if row.get("sandbox_event")]
    assert len(experiments) == 1
    assert experiments[0]["sandbox_event"]["passed"] == 1
    assert experiments[0]["status"] == "inconclusive"
    assert len(state["episodes"]) == 1  # The experiment did not invent another live outcome.


def test_selection_utility_requires_applied_verified_target_and_honors_rollback():
    key = digest(["item", "memory", 1, "task"])
    state = {"stats": {key: {"utility": 1.1}}, "credit": {"c": {
        "episode_id": "e", "target_kind": "item", "target_id": "memory", "revision": 1, "task_class": "task", "step": 0.1,
        "evidence_version": 3}},
        "episodes": {"e": {"user_id": "u", "cited_cids": ["memory"]}}}
    assert selection_utility(state, "item", "memory", 1, "task", user_id="u") == 1
    state["episodes"]["e"]["target_outcomes"] = {"memory": {"value": 1}}
    assert selection_utility(state, "item", "memory", 1, "task", user_id="u") == 1.1
    assert selection_utility(state, "item", "memory", 1, "task", user_id="other") == 1
    state["stats"][key]["utility"] = 1
    assert selection_utility(state, "item", "memory", 1, "task", user_id="u") == 1


def test_composition_drops_cannot_become_randomized_controls():
    record = {"item_id": "memory", "kind": "item", "revision": 1, "served": False, "propensity": None}
    assert randomized_opportunity({}, [{"selection_exposures": [record]}], "item", "memory", 1) is None
    record["propensity"] = 0.9
    assert randomized_opportunity({}, [{"selection_exposures": [record]}], "item", "memory", 1)["served"] is False
