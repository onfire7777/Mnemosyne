from __future__ import annotations

from copy import deepcopy

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.frameworks import AutoMemorySession
from mnemosyne.jobs import RuntimeJobHandlers
from mnemosyne.queue import InProcessQueue


def test_sdk_original_cids_are_episode_sources_without_duplicate_chat_copies():
    engine = LocalMemoryEngine()
    session = AutoMemorySession(engine, "t", "u", auto_consolidate=False)
    session.pre_turn_retrieve("hello")
    captured = session.post_turn_capture("hello", "hi")
    episode = session.learning_runtime.episode(
        "t", captured["learning_episode"]["episode_id"]
    )
    assert captured["user_cid"] in episode["source_cids"]
    assert captured["assistant_cid"] in episode["source_cids"]
    assert (
        len([row for row in engine.evidence.values() if row.content in {"hello", "hi"}])
        == 2
    )


def test_policy_candidates_learn_real_outcomes_but_stay_shadow_without_gate():
    engine = LocalMemoryEngine()
    runtime = LearningRuntime(engine)
    context = runtime.prepare_context("t", "u", "s", "find release")
    request = context["policy_verification_request"]
    original = engine.policy.to_dict()
    event = {
        "name": "policy_variant_verifier",
        "source": "tool",
        "verdict": True,
        "output": "independent replay complete",
        "policy_replay": {
            "policy_fingerprint": request["policy_fingerprint"],
            "baseline_success": False,
            "candidate_success": True,
            "predicted_lift": 1.0,
        },
    }
    captured = runtime.observe_turn(
        "t",
        "u",
        "s",
        "find release",
        "result",
        receipt_ids=[context["receipt_id"]],
        tool_events=[event],
    )
    runtime.resolve("t", captured["episode_id"])
    state = runtime.writer.read("t")
    assert state["policy"]["policy_outcomes"][captured["episode_id"]]["reward"] == 1
    assert (
        state["policy"]["policy_replay_pairs"][captured["episode_id"]]["observed_lift"]
        == 1
    )
    assert (
        state["policy"]["policy_candidates"][context["task_class"]]["status"]
        == "shadow"
    )
    assert not state["policy"].get("active_policy_variants")
    assert engine.policy.to_dict() == original


def test_breaker_restores_checkpoint_policy_but_keeps_outcome_evidence():
    runtime = LearningRuntime(LocalMemoryEngine())
    state = runtime.writer.read("t")
    state["policy"].update(
        routes={"x": {"lexical": 0.6, "graph": 0.4}},
        last_good={
            "x": {"policy": {"routes": {"lexical": 0.4, "graph": 0.6}}, "artifacts": {}}
        },
    )
    state["episodes"] = {
        str(i): {
            "id": str(i),
            "task_class": "x",
            "status": "resolved",
            "reward": 1 if i < 20 else -1,
            "created_at": f"2026-11-05T00:00:{i:02d}+00:00",
        }
        for i in range(40)
    }
    before = deepcopy(state["episodes"])
    runtime._breaker(state, state["episodes"]["39"])
    assert state["policy"]["frozen"]
    assert state["policy"]["routes"]["x"] == {"lexical": 0.4, "graph": 0.6}
    assert state["episodes"] == before


def test_breaker_requires_statistically_supported_regression():
    runtime = LearningRuntime(LocalMemoryEngine())
    state = runtime.writer.read("t")
    # Three fewer successes in twenty trials can occur under a stationary policy.
    state["episodes"] = {
        str(index): {
            "id": str(index),
            "task_class": "x",
            "status": "resolved",
            "reward": 1 if index < 12 or 20 <= index < 29 else -1,
            "created_at": f"2026-11-05T00:00:{index:02d}+00:00",
        }
        for index in range(40)
    }
    runtime._breaker(state, state["episodes"]["39"])
    assert not state["policy"].get("frozen", False)
    assert "breaker" not in state["policy"]


def test_surprised_fast_path_recovers_only_after_verified_matching_goal():
    runtime = LearningRuntime(LocalMemoryEngine())
    state = runtime.writer.read("t")
    state["policy"]["surprised"] = {"x": True}
    state["artifacts"]["a"] = {"state": "active", "goal": "deploy inventory"}
    state["receipts"]["r"] = {"query": "different goal", "items": [{"item_id": "a"}]}
    episode = {
        "task_class": "x",
        "rpe": 0.2,
        "reward": 1,
        "signals": [{"kind": "verifier"}],
        "receipt_ids": ["r"],
    }
    runtime._update_goal_state(state, episode)
    assert state["policy"]["surprised"]["x"]
    state["receipts"]["r"]["query"] = "deploy inventory"
    episode["signals"] = [{"kind": "acceptance"}]
    runtime._update_goal_state(state, episode)
    assert state["policy"]["surprised"]["x"]
    episode["signals"] = [{"kind": "verifier"}]
    runtime._update_goal_state(state, episode)
    assert "x" not in state["policy"]["surprised"]


def test_learning_calibration_consumes_resolved_external_outcomes():
    runtime = LearningRuntime(LocalMemoryEngine())
    for i in range(20):
        context = runtime.prepare_context("t", "u", str(i), f"question {i}")
        captured = runtime.observe_turn(
            "t",
            "u",
            str(i),
            f"question {i}",
            "answer",
            receipt_ids=[context["receipt_id"]],
        )
        runtime.record_signal(
            "t",
            episode_id=captured["episode_id"],
            kind="verifier",
            value=(i % 2 == 0),
            final=True,
        )
    handlers = RuntimeJobHandlers(runtime.engine, InProcessQueue())
    result = handlers.run_calibration({"tenant_id": "t", "memory_type": "learning"})
    recorded = runtime.writer.read("t")["policy"]["learning_calibration"]
    assert recorded["calibration"]["memory_type"] == "learning"
    assert result.details == recorded


def test_receipt_freezes_effective_trace_configuration():
    engine = LocalMemoryEngine()
    engine.policy.learning_trace_lambda = 0.3
    engine.policy.learning_trace_tau_minutes = 17
    runtime = LearningRuntime(engine)
    context = runtime.prepare_context("t", "u", "s", "query")
    engine.policy.learning_trace_lambda = 0.9
    receipt = runtime.writer.read("t")["receipts"][context["receipt_id"]]
    assert receipt["effective_policy"]["learning_trace_lambda"] == 0.3
    assert receipt["effective_policy"]["learning_trace_tau_minutes"] == 17


def test_sparse_task_prior_uses_outcomes_and_disappears_after_twenty():
    from mnemosyne.experience.runtime import stat_key

    runtime = LearningRuntime(LocalMemoryEngine())
    state = runtime.writer.read("t")
    state["episodes"] = {"e": {"task_class": "other", "status": "resolved"}}
    state["stats"][stat_key("skill", "s", 1, "other")] = {
        "alpha": 10.0,
        "beta": 2.0,
        "n": 10.0,
    }
    prior = runtime._target_posterior(state, "skill", "s", 1, "new")
    assert prior.mean > 0.5
    state["stats"][stat_key("skill", "s", 1, "new")] = {
        "alpha": 1.0,
        "beta": 21.0,
        "n": 20.0,
    }
    assert runtime._target_posterior(state, "skill", "s", 1, "new").mean == 1 / 22


def test_retracting_skill_outcome_removes_its_utility(tmp_path):
    from mnemosyne.skills import SkillStore

    path = tmp_path / "skill.md"
    path.write_text("---\nname: check\n---\nRead the release checklist.")
    store = SkillStore(str(tmp_path / "skills.sqlite"))
    row = store.import_skill(str(path), "")
    for i in range(12):
        store.outcome(row["skill_id"], 1, True, "verified", episode_id=str(i))
    assert store.status(row["skill_id"])["state"] == "active"
    assert store.retract_outcome("0")["retracted"] == 1
    assert store.status(row["skill_id"])["state"] == "probation"
    assert store.status(row["skill_id"])["posterior"]["outcomes"] == 11
    assert store.retract_outcome("0")["retracted"] == 0


def test_modes_and_freeze_are_in_effective_receipt_snapshot():
    runtime = LearningRuntime(LocalMemoryEngine())
    first = runtime.prepare_context("t", "u", "s", "query")
    runtime.mode("t", "skills", "off")
    second = runtime.prepare_context("t", "u", "s", "query")
    receipts = runtime.writer.read("t")["receipts"]
    assert (
        receipts[first["receipt_id"]]["policy_version"]
        != receipts[second["receipt_id"]]["policy_version"]
    )
    assert (
        receipts[second["receipt_id"]]["effective_policy"]["learning_modes"]["skills"]
        == "off"
    )


def test_high_risk_never_explores():
    engine = LocalMemoryEngine()
    engine.policy.learning_exploration_rate = 1.0
    runtime = LearningRuntime(engine)
    context = runtime.prepare_context(
        "t", "u", "s", "check treatment", task_type="medical:treatment"
    )
    assert context["exploration"] is False
    assert (
        runtime.writer.read("t")["receipts"][context["receipt_id"]]["risk_level"]
        == "high"
    )


def test_paused_breaker_keeps_behavior_state_unchanged():
    runtime = LearningRuntime(LocalMemoryEngine())
    state = runtime.writer.read("t")
    state["policy"].update(enabled=False, routes={"x": {"lexical": 0.6, "graph": 0.4}})
    state["episodes"] = {
        str(i): {
            "id": str(i),
            "task_class": "x",
            "status": "resolved",
            "reward": 1 if i < 20 else -1,
            "created_at": f"2026-11-05T00:00:{i:02d}+00:00",
        }
        for i in range(40)
    }
    before = deepcopy(state)
    runtime._breaker(state, state["episodes"]["39"])
    assert state == before


def test_sdk_runtime_rejects_unserved_artifact_usage():
    session = AutoMemorySession(LocalMemoryEngine(), "t", "u", auto_consolidate=False)
    captured = session.post_turn_capture(
        "question", "answer", used_skills=["used-skill"], used_lessons=["used-lesson"]
    )
    episode = session.learning_runtime.episode(
        "t", captured["learning_episode"]["episode_id"]
    )
    assert episode["used_skills"] == []
    assert episode["used_lessons"] == []


def test_native_library_mirror_is_append_only_cas_and_retractable(tmp_path):
    from mnemosyne.skills import SkillStore

    path = tmp_path / "skill.md"
    path.write_text("---\nname: check\n---\nRead the checklist.")
    store = SkillStore(str(tmp_path / "skills.sqlite"))
    original = store.import_skill(
        str(path), "", memory={"tenant": "t", "user": "u", "source_cids": ["original"]}
    )
    artifact = {
        "id": "native",
        "state": "active",
        "gate_passed": True,
        "source_episode_ids": ["e"],
        "source_cids": ["derived-source"],
        "content": "Read the checklist twice.",
        "approved": True,
        "_library_statistics": {"verified_n": 12, "verified_successes": 12},
    }
    result = store.mirror_learned_revision(original["skill_id"], 1, artifact)
    assert result["revision"] == 2
    assert store.status(original["skill_id"], 1)["state"] == "probation"
    assert store.get(original["skill_id"], 2)["text"] == "Read the checklist twice."
    assert store.mirror_learned_revision(original["skill_id"], 1, artifact)["duplicate"]
    with pytest.raises(ValueError, match="parent revision conflict"):
        store.mirror_learned_revision(
            original["skill_id"], 1, {**artifact, "id": "another"}
        )
    assert store.retract_source("derived-source")["retracted"] == 1
    assert store.status(original["skill_id"], 2)["state"] == "retired"
    assert store.get(original["skill_id"], 1)["text"].endswith("Read the checklist.")


def test_item_movement_budget_preserves_all_observed_statistics():
    from mnemosyne.experience.runtime import stat_key

    runtime = LearningRuntime(LocalMemoryEngine())
    state = runtime.writer.read("t")
    for index in range(50):
        served = index >= 20
        rid = f"r{index}"
        item = {"kind": "item", "item_id": "target", "revision": 1, "routes": []}
        state["receipts"][rid] = {
            "created_at": "2026-11-05T00:00:00+00:00",
            "turn_index": 0,
            "items": [item] if served else [],
            "eligible_targets": [item],
        }
        episode = {
            "id": str(index),
            "tenant_id": "t",
            "user_id": "u",
            "session_id": "s",
            "task_class": "x",
            "reward": 1 if served else -1,
            "rpe": 1 if served else -1,
            "receipt_ids": [rid],
            "turn_index": 0,
            "resolved_turn_index": 1,
            "resolved_at": "2026-11-05T00:00:00+00:00",
            "status": "resolved",
            "signals": [{"kind": "verifier", "value": 1 if served else -1}],
            "cited_cids": ["target"] if served else [],
        }
        state["episodes"][str(index)] = episode
        runtime._credit(state, episode)
    row = state["stats"][stat_key("item", "target", 1, "x")]
    assert row["served_n"] == 30 and row["control_n"] == 20
    assert (
        sum(abs(credit["step"]) for credit in state["credit"].values()) <= 0.100000001
    )
    assert row["utility"] <= 1.100000001


def test_proven_fast_path_skips_retrieval_except_configured_comparisons(monkeypatch):
    from mnemosyne.experience.runtime import stat_key
    from mnemosyne.models import Evidence

    engine = LocalMemoryEngine()
    engine.policy.learning_modes["exploration"] = "off"
    cid = engine.append_evidence(
        Evidence(
            tenant_id="t",
            user_id="u",
            actor="user",
            source_type="test",
            content="Perform the proven step.",
            access_policy={"tenant": "t"},
        )
    )
    runtime = LearningRuntime(engine)
    state = runtime.writer.read("t")
    # This spy fixture supplies already-admitted data. Admission and outcome
    # validation have their own real-store tests.
    state["artifacts"]["a"] = {
        "id": "a",
        "kind": "procedure",
        "state": "active",
        "task_class": "task",
        "scope": "task",
        "conditions": [],
        "content": "Perform the proven step.",
        "steps": ["Perform the proven step."],
        "source_cids": [cid],
        "source_episode_ids": [],
        "revision": 1,
        "user_id": "u",
        "goal": "run proven task",
        "next_revalidation_at": "2099-01-01T00:00:00+00:00",
        "needs_approval": False,
    }
    state["stats"][stat_key("procedure", "a", 1, "task")] = {
        "alpha": 100.0,
        "beta": 1.0,
        "n": 99.0,
    }

    class Writer:
        def read(self, tenant):
            return deepcopy(state)

        def apply(self, tenant, operation, mutate):
            return mutate(state)

    runtime.writer = Writer()
    calls = []
    original = engine.retrieve

    def retrieve(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(engine, "retrieve", retrieve)
    for index in range(30):
        context = runtime.prepare_context(
            "t", "u", f"s-{index}", "run proven task", task_type="task"
        )
        receipt = state["receipts"][context["receipt_id"]]
        if not receipt["comparison_sample"]:
            assert context["mode"] == "fast"
            assert not receipt["full_retrieval_performed"]
            break
    else:
        raise AssertionError(
            "seeded comparison sample never produced an ordinary fast serve"
        )
    before = len(calls)
    engine.policy.learning_goal_check_comparison_rate = 1.0
    context = runtime.prepare_context(
        "t", "u", "comparison", "run proven task", task_type="task"
    )
    assert len(calls) == before + 1
    assert state["receipts"][context["receipt_id"]]["comparison_sample"]


def test_erasing_sdk_returned_user_cid_retracts_learning_and_profile():
    import json

    engine = LocalMemoryEngine()
    session = AutoMemorySession(engine, "t", "u", auto_consolidate=False)
    text = "I prefer concise responses."
    session.pre_turn_retrieve(text)
    captured = session.post_turn_capture(text, "Understood.")
    episode_id = captured["learning_episode"]["episode_id"]
    assert (
        captured["user_cid"]
        in session.learning_runtime.episode("t", episode_id)["source_cids"]
    )
    engine.forget("t", captured["user_cid"])
    state = session.learning_runtime.writer.read("t")
    assert state["episodes"][episode_id]["status"] == "erased"
    assert text not in json.dumps(state)
    assert all(
        entry.statement != text
        for entry in session._learning_tools.user_model.entries.values()
    )
