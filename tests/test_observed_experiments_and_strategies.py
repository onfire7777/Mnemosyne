from copy import deepcopy

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.candidates import applies_to
from mnemosyne.experience.experiment_planner import propose_observed_experiments
from mnemosyne.experience.guards import LearningGuardError
from mnemosyne.experience.hypotheses import process_reviews
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.experience.receipts import digest
from mnemosyne.experience.strategies import propose_strategies, strategy_applies, validated_strategy
from mnemosyne.experience.task_class import semantic_contract


def observe(runtime, session, query, *, command="pytest -q", passed=True, task_type=None, risk=None):
    context = runtime.prepare_context("t", "u", session, query, ["shell"],
                                      task_type=task_type, risk_level=risk)
    event = {"name": "shell", "source": "tool", "command": command,
             "cwd": "/workspace", "output": "2 passed" if passed else "2 failed", "verdict": passed}
    observed = runtime.observe_turn("t", "u", session, query, "", receipt_ids=[context["receipt_id"]],
                                    tool_events=[event])
    runtime.resolve("t", observed["episode_id"])
    return runtime.episode("t", observed["episode_id"])


def experiment_runtime():
    runtime = LearningRuntime(LocalMemoryEngine())
    for i in range(4):
        observe(runtime, str(i), "fix cache loading", command="pytest -q" if i % 2 else "pytest broken",
                passed=bool(i % 2), task_type="cache-repair")
    return runtime


def test_consolidation_plans_executes_heldout_experiment_from_ordinary_tool_history():
    runtime = experiment_runtime()
    before = deepcopy(runtime.writer.read("t"))
    result = runtime.consolidate("t")
    state = runtime.writer.read("t")
    reviews = [row for row in state["policy"]["hypotheses"].values()
               if row.get("sandbox_event", {}).get("scope") == "observed_trace_prediction"]
    assert result["hypotheses_reviewed"] >= 1 and len(reviews) == 1
    review = reviews[0]
    assert review["status"] == "inconclusive"
    assert review["reason"] == "heldout_replay_passed_awaiting_real_outcomes"
    assert review["partitions"] == {"training": {"passed": 2, "total": 2}, "heldout": {"passed": 2, "total": 2}}
    assert state["episodes"] == before["episodes"]
    assert state["credit"] == before["credit"]
    attempts = review["review_attempts"]
    runtime.consolidate("t")
    latest = runtime.writer.read("t")["policy"]["hypotheses"][review["id"]]
    assert latest["review_attempts"] == attempts
    assert latest["prediction_candidate_id"] in runtime.writer.read("t")["artifacts"]
    from mnemosyne.experience.candidates import verification_requests
    request = next(item for item in verification_requests(runtime, "t", "u", "cache-repair", "fix cache loading")
                   if item["id"] == review["id"])
    assert request["experiment_result"]["scope"] == "outcome_prediction_not_causal_proof"
    assert request["experiment_result"]["partitions"]["heldout"]["passed"] == 2


def test_planner_never_discloses_heldout_labels_to_provider():
    runtime = experiment_runtime()
    calls = []
    runtime.engine._learning_configuration = {"experiment_proposer": lambda **payload: calls.append(payload)}
    proposals = propose_observed_experiments(runtime, "t", list(runtime.writer.read("t")["episodes"].values()))
    assert proposals and calls
    assert all(case["partition"] == "training" for case in calls[0]["training_cases"])
    assert len(calls[0]["training_cases"]) == 2


def test_modified_expected_result_cannot_pass_grounded_review():
    runtime = experiment_runtime()
    rows = propose_observed_experiments(runtime, "t", list(runtime.writer.read("t")["episodes"].values()))
    row = rows[0]
    row["review_contract"]["sandbox_check"]["cases"][0]["expected"] = "forged"
    row["contract_hash"] = digest(row["review_contract"])
    # Proposal records are untrusted; the independent review rebuilds cases.
    runtime.writer.apply("t", "queue_review", lambda state: state["policy"].update(hypotheses={row["id"]: row}))
    process_reviews(runtime, "t")
    stored = runtime.writer.read("t")["policy"]["hypotheses"][row["id"]]
    assert stored["reason"] == "observed_cases_no_longer_grounded"
    assert "sandbox_event" not in stored


def test_no_experiment_without_independent_positive_and_negative_holdouts():
    runtime = LearningRuntime(LocalMemoryEngine())
    observe(runtime, "a", "fix cache loading", task_type="cache-repair")
    observe(runtime, "b", "fix cache loading", task_type="cache-repair", passed=False)
    assert propose_observed_experiments(runtime, "t", list(runtime.writer.read("t")["episodes"].values())) == []


def strategy_runtime():
    runtime = LearningRuntime(LocalMemoryEngine())
    observe(runtime, "cache", "fix the cache bug")
    observe(runtime, "auth", "fix the authentication bug")
    return runtime


def test_transfer_keeps_task_identities_but_exposes_verified_entity_independent_strategy():
    runtime = strategy_runtime()
    state = runtime.writer.read("t")
    assert len({row["task_class"] for row in state["episodes"].values()}) == 2
    proposals = propose_strategies(state)
    assert len(proposals) == 1
    proposal = proposals[0]
    assert validated_strategy(proposal, state["episodes"], state["receipts"])
    assert strategy_applies(proposal, "repair the payments issue", tools=["shell"], risk="normal")
    assert applies_to(proposal, "new-distinct-task", "fix the payments bug")
    assert not strategy_applies(proposal, "fix the payments bug without deleting entries", tools=["shell"])
    assert not strategy_applies(proposal, "fix the payments bug", tools=["other"])
    assert not strategy_applies(proposal, "fix the payments bug", tools=["shell"], risk="high")
    forged = deepcopy(proposal)
    forged["strategy_contract"]["shape"]["constraints"] = ["without deleting entries"]
    assert not validated_strategy(forged, state["episodes"], state["receipts"])


def test_consolidation_gates_strategy_and_real_receipt_can_serve_new_entity():
    runtime = strategy_runtime()
    runtime.consolidate("t")
    state = runtime.writer.read("t")
    strategies = [row for row in state["artifacts"].values() if row.get("strategy_contract")]
    assert len(strategies) == 1
    artifact = strategies[0]
    assert artifact["state"] == "probation" and artifact["gate_passed"]
    packets = [runtime.prepare_context("t", "u", f"payment-{i}", "fix the payments bug", ["shell"], workspace="/workspace")
               for i in range(2)]
    assert any(any(row["id"] == artifact["id"] for row in packet["procedures"]) for packet in packets)
    assert all(packet["task_class"] != artifact["task_class"] for packet in packets)
    assert all(packet["mode"] != "fast" for packet in packets)
    for workspace in (None, "/different-project"):
        packet = runtime.prepare_context("t", "u", "other", "fix the payments bug", ["shell"], workspace=workspace)
        assert not packet["procedures"]


def test_entity_specific_actions_never_become_general_strategy():
    runtime = LearningRuntime(LocalMemoryEngine())
    observe(runtime, "a", "fix the cache bug", command="pytest cache_tests")
    observe(runtime, "b", "fix the authentication bug", command="pytest cache_tests")
    assert propose_strategies(runtime.writer.read("t")) == []


def test_strategy_guard_rejects_forged_cross_owner_evidence():
    runtime = strategy_runtime()
    proposal = propose_strategies(runtime.writer.read("t"))[0]
    proposal["user_id"] = "someone-else"
    with pytest.raises(LearningGuardError):
        runtime.writer.apply("t", "consolidate", lambda state: state["artifacts"].update({proposal["id"]: proposal}))


@pytest.mark.parametrize("query,intent", [
    ("optimize the cache implementation", "optimize"), ("debug the authentication issue", "diagnose"),
    ("implement the reporting feature", "implement"), ("verify the migration", "verify"),
])
def test_richer_task_intents_retain_explicit_scope(query, intent):
    assert semantic_contract(query)["intent"] == intent
    assert semantic_contract(query + " without deleting files")["constraints"] == ["without deleting files"]
