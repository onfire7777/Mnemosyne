"""The native learning loop and the existing route learner share one bounded update."""

import copy

import pytest

from mnemosyne.experience.learners import update_routes
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.self_optimization import AdaptiveRouteWeighter


def _rewards():
    return {route: 1.0 if route == "lexical" else -1.0
            for route in AdaptiveRouteWeighter.DEFAULT_ROUTES}


def test_existing_route_learning_preserves_normalization_and_bounds():
    learner = AdaptiveRouteWeighter()
    for _ in range(120):
        weights = learner.record_outcome("tenant", _rewards())
        assert sum(weights.values()) == pytest.approx(1.0, abs=1e-9)
        assert all(0.05 <= weight <= 0.65 for weight in weights.values())
    assert weights["lexical"] > weights["graph"]


def test_intent_adjustment_preserves_the_existing_route_caps():
    learner = AdaptiveRouteWeighter()
    for _ in range(120):
        learner.record_outcome("tenant", _rewards())
    weights = learner.get_weights("tenant", query_intent="lexical")
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-9)
    assert all(0.05 <= weight <= 0.65 for weight in weights.values())


def test_native_route_updates_preserve_daily_bounds_and_normalization():
    state = {"policy": {}}
    for _ in range(120):
        update_routes(state, "deployment", _rewards())
        weights = state["policy"]["routes"]["deployment"]
        assert sum(weights.values()) == pytest.approx(1.0, abs=1e-9)
        assert all(0.1 - 1e-12 <= weight <= 0.3 + 1e-12
                   for weight in weights.values())
    assert weights["lexical"] == pytest.approx(0.3)


def test_native_route_state_reloads_without_a_second_learning_history():
    state = {"policy": {}}
    for _ in range(8):
        update_routes(state, "deployment", _rewards())
    restored = copy.deepcopy(state)
    update_routes(state, "deployment", {"graph": 1.0, "lexical": -1.0})
    update_routes(restored, "deployment", {"graph": 1.0, "lexical": -1.0})
    assert state == restored


def _record_policy_comparison(runtime, session):
    context = runtime.prepare_context("tenant", "user", session, "find release", task_type="release")
    request = context["policy_verification_request"]
    observed = runtime.observe_turn(
        "tenant", "user", session, "find release", "result",
        receipt_ids=[context["receipt_id"]],
        tool_events=[{
            "name": "policy_variant_verifier", "source": "tool", "verdict": False,
            "output": "baseline failed; candidate passed",
            "policy_replay": {
                "policy_fingerprint": request["policy_fingerprint"],
                "baseline_success": False, "candidate_success": True, "predicted_lift": 1.0,
            },
        }],
    )
    runtime.resolve("tenant", observed["episode_id"])
    return context, observed


def test_existing_bandit_sees_current_external_comparison_immediately():
    runtime = LearningRuntime(LocalMemoryEngine())
    context, _ = _record_policy_comparison(runtime, "session")
    candidate = runtime.writer.read("tenant")["policy"]["policy_candidates"][context["task_class"]]
    assert candidate["variant"]["id"] == context["policy_verification_request"]["variant"]["id"]
    assert candidate["outcome_count"] == 2
    assert candidate["status"] == "shadow"


def test_bandit_counts_each_episode_variant_once_across_live_and_replay_evidence():
    runtime = LearningRuntime(LocalMemoryEngine())
    for index in range(3):
        context, observed = _record_policy_comparison(runtime, f"session-{index}")
    state = runtime.writer.read("tenant")
    candidate = state["policy"]["policy_candidates"][context["task_class"]]
    assert candidate["outcome_count"] == 6
    assert not state["policy"].get("active_policy_variants")
    runtime.resolve("tenant", observed["episode_id"])
    assert runtime.writer.read("tenant")["policy"]["policy_candidates"] == state["policy"]["policy_candidates"]
