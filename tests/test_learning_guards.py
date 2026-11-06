from copy import deepcopy

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.guards import LearningGuardError, validate
from mnemosyne.experience.monitors import diagnostics, run_monitors
from mnemosyne.experience.receipts import digest
from mnemosyne.experience.runtime import LearningRuntime
from tests.fault_injection.learning import baseline, credit, source_lookup


def test_valid_snapshot_passes_all_boundaries():
    state = baseline()
    validate(state, deepcopy(state), "monitor", source_lookup=source_lookup)
    assert diagnostics(state, source_lookup=source_lookup) == []


def test_writer_contains_uncredited_utility_change():
    runtime = LearningRuntime(LocalMemoryEngine())
    with pytest.raises(LearningGuardError, match="X1"):
        runtime.writer.apply(
            "t",
            "invalid_update",
            lambda state: state["stats"].update(forged={"utility": 1.1}),
        )
    state = runtime.writer.read("t")
    assert state["stats"] == {}
    assert state["policy"]["frozen"] is True
    assert [row["class"] for row in state["defects"].values()] == ["X1"]


def test_outcome_credit_allows_matching_utility_update():
    before = baseline()
    after = deepcopy(before)
    after["credit"]["new-credit"] = credit()
    key = digest(["item", "source", 1, "deploy"])
    after["stats"][key] = {"utility": 1.05}
    validate(before, after, "resolve", source_lookup=source_lookup)


def test_credit_cannot_be_redirected_to_an_unserved_target():
    before = baseline()
    after = deepcopy(before)
    after["credit"]["forged"] = {**credit(), "target_id": "not-served"}
    with pytest.raises(LearningGuardError, match="X3"):
        validate(before, after, "resolve", source_lookup=source_lookup)


def test_erasure_can_remove_receipts_but_cannot_leave_episode_text():
    before = baseline()
    after = deepcopy(before)
    after["receipts"].clear()
    after["episodes"]["episode"].update(
        receipt_ids=[],
        status="erased",
        signals=[],
        source_cids=[],
        tool_events=[],
        user_text="",
    )
    after["artifacts"].clear()
    validate(before, after, "erasure", source_lookup=source_lookup)
    after["episodes"]["episode"]["user_text"] = "residual secret"
    with pytest.raises(LearningGuardError, match="X17"):
        validate(before, after, "erasure", source_lookup=source_lookup)


def test_new_artifact_cannot_skip_probation():
    before = baseline()
    after = deepcopy(before)
    del before["artifacts"]["artifact"]
    after["artifacts"]["artifact"]["state"] = "active"
    with pytest.raises(LearningGuardError, match="X21"):
        validate(before, after, "consolidate", source_lookup=source_lookup)


def test_source_erasure_blocks_an_existing_servable_artifact():
    state = baseline()
    with pytest.raises(LearningGuardError, match="X15"):
        validate(state, deepcopy(state), "monitor", source_lookup=lambda _: None)


def test_scope_expansion_requires_real_successful_episode():
    before = baseline()
    after = deepcopy(before)
    after["artifacts"]["artifact"].update(scope="broader", scope_evidence=["missing"])
    with pytest.raises(LearningGuardError, match="X9"):
        validate(before, after, "scope_evidence", source_lookup=source_lookup)


def test_locked_artifact_allows_only_explicit_unlock():
    before = baseline()
    before["artifacts"]["artifact"]["locked"] = True
    after = deepcopy(before)
    after["artifacts"]["artifact"]["pinned"] = True
    with pytest.raises(LearningGuardError, match="X18"):
        validate(before, after, "pin", source_lookup=source_lookup)
    after = deepcopy(before)
    after["artifacts"]["artifact"]["locked"] = False
    validate(before, after, "lock", source_lookup=source_lookup)


def test_calibration_monitor_does_not_judge_a_small_sample():
    state = baseline()
    state["artifacts"].clear()
    for index in range(98):
        episode = deepcopy(state["episodes"]["episode"])
        episode.update(
            id=str(index), receipt_ids=[], prediction=1.0, reward=-1.0, rpe=-2.0
        )
        state["episodes"][str(index)] = episode
    assert not any(row["class"] == "X5" for row in diagnostics(state))


def test_calibration_monitor_rejects_systematically_wrong_predictions():
    state = baseline()
    state["artifacts"].clear()
    state["episodes"] = {
        str(index): {
            "id": str(index),
            "task_class": "deploy",
            "status": "resolved",
            "prediction": 1.0,
            "reward": -1.0,
            "rpe": -2.0,
            "signals": [],
            "receipt_ids": [],
        }
        for index in range(100)
    }
    failures = diagnostics(state)
    assert any(row["class"] == "X5" and row["value"] == 1 for row in failures)


def test_monitor_failure_uses_writer_defect_containment():
    runtime = LearningRuntime(LocalMemoryEngine())
    # Simulate persisted state damage; never install a production fault toggle.
    runtime.engine._learning_data = {"t": baseline()}
    runtime.engine._learning_data["t"]["artifacts"].clear()
    runtime.engine._learning_data["t"]["policy"]["protected_suite_results"] = [
        {"passed": False}
    ]
    with pytest.raises(LearningGuardError, match="X18"):
        run_monitors(runtime.writer, "t")
    state = runtime.writer.read("t")
    assert state["policy"]["frozen"] is True
    assert len(state["defects"]) == 1


def test_exploration_monitor_needs_statistical_evidence():
    state = baseline()
    state["artifacts"].clear()
    receipt = state["receipts"]["receipt"]
    state["receipts"] = {
        str(index): {**receipt, "id": str(index), "exploration": False}
        for index in range(300)
    }
    state["episodes"].clear()
    assert any(row["class"] == "X4" for row in diagnostics(state))


def test_balanced_stationary_predictions_have_no_calibration_defect():
    state = baseline()
    state["artifacts"].clear()
    state["episodes"] = {
        str(index): {
            "id": str(index),
            "task_class": "deploy",
            "status": "resolved",
            "prediction": 0.5,
            "reward": 1.0 if index % 2 else -1.0,
            "rpe": 1.0 if index % 2 else -1.0,
            "signals": [],
            "receipt_ids": [],
        }
        for index in range(100)
    }
    assert diagnostics(state) == []


def test_disabled_metacognition_is_not_scored_as_a_learned_prediction():
    runtime = LearningRuntime(LocalMemoryEngine())
    runtime.pause("t")
    for index in range(100):
        context = runtime.prepare_context(
            "t", "u", str(index), "lookup", task_type="lookup"
        )
        observed = runtime.observe_turn(
            "t",
            "u",
            str(index),
            "lookup",
            "unknown",
            receipt_ids=[context["receipt_id"]],
        )
        runtime.record_signal(
            "t",
            episode_id=observed["episode_id"],
            kind="verifier",
            value=-1,
            final=True,
        )
    assert diagnostics(runtime.writer.read("t")) == []


def test_calibration_monitor_accounts_for_finite_sample_uncertainty():
    state = baseline()
    state["artifacts"].clear()
    state["receipts"].clear()
    state["episodes"].clear()
    for bucket, (prediction, successes) in enumerate(
        zip((0.1, 0.3, 0.5, 0.7, 0.9), (6, 3, 14, 11, 18))
    ):
        for trial in range(20):
            outcome = 1.0 if trial < successes else -1.0
            identifier = f"{bucket}-{trial}"
            state["episodes"][identifier] = {
                "id": identifier,
                "task_class": "lookup",
                "status": "resolved",
                "prediction": prediction,
                "reward": outcome,
                "rpe": outcome - (2 * prediction - 1),
                "signals": [],
                "receipt_ids": [],
            }
    assert diagnostics(state) == []


def test_consistent_posterior_cannot_be_inflated_by_retrievals():
    before = baseline()
    after = deepcopy(before)
    key = digest(["item", "source", 1, "deploy"])
    after["stats"][key] = {"alpha": 11.0, "beta": 1.0, "n": 10.0}
    with pytest.raises(LearningGuardError, match="X16"):
        validate(before, after, "capture", source_lookup=source_lookup)


def test_unchanged_replay_cannot_emit_another_artifact():
    before = baseline()
    before["policy"]["replayed"] = {
        "episode": digest(before["episodes"]["episode"]["signals"])
    }
    after = deepcopy(before)
    after["artifacts"]["another"] = {**after["artifacts"]["artifact"], "id": "another"}
    with pytest.raises(LearningGuardError, match="X8"):
        validate(before, after, "consolidate", source_lookup=source_lookup)


def test_route_update_cannot_borrow_credit_from_another_class():
    before = baseline()
    after = deepcopy(before)
    after["credit"]["new-credit"] = credit()
    after["policy"]["routes"] = {"unrelated": {"lexical": 0.5, "vector": 0.5}}
    with pytest.raises(LearningGuardError, match="X1"):
        validate(before, after, "resolve", source_lookup=source_lookup)


def test_malformed_collection_fails_through_guard():
    before = baseline()
    after = deepcopy(before)
    after["stats"] = []
    with pytest.raises(LearningGuardError, match="X1"):
        validate(before, after, "corruption", source_lookup=source_lookup)


def test_imported_provenance_can_enter_probation_without_fabricated_outcome():
    from mnemosyne.experience.store import empty_state

    before = empty_state()
    after = baseline()
    after["receipts"].clear()
    after["episodes"]["episode"].update(
        status="imported", reward=None, rpe=None, signals=[], receipt_ids=[]
    )
    after["artifacts"]["artifact"]["origin"] = "imported"
    validate(before, after, "import", source_lookup=source_lookup)
    after["episodes"]["episode"]["reward"] = 1.0
    with pytest.raises(LearningGuardError, match="X7"):
        validate(before, after, "import", source_lookup=source_lookup)


@pytest.mark.parametrize("verified", [True, False])
def test_activation_requires_external_verification_after_probation(verified):
    before = baseline()
    after = deepcopy(before)
    for index in range(40):
        receipt_id = f"trial-{index}"
        receipt = deepcopy(before["receipts"]["receipt"])
        receipt.update(id=receipt_id, items=[])
        served = index < 20
        if served:
            receipt["items"] = [
                {"kind": "procedure", "item_id": "artifact", "revision": 1}
            ]
        after["receipts"][receipt_id] = receipt
        episode = deepcopy(before["episodes"]["episode"])
        episode.update(
            id=receipt_id,
            receipt_ids=[receipt_id],
            reward=1.0 if served else -1.0,
            rpe=1.0 if served else -1.0,
        )
        if not verified and served:
            episode.update(reward=0.6, rpe=0.6)
            episode["signals"] = [{"kind": "acceptance", "value": 0.6, "weight": 0.3}]
        after["episodes"][receipt_id] = episode
    key = digest(["procedure", "artifact", 1, "deploy"])
    after["stats"][key] = {
        "alpha": 21.0 if verified else 17.0,
        "beta": 1.0 if verified else 5.0,
        "n": 20.0,
        "control_n": 20,
        "control_successes": 0.0,
        "utility": 1.0,
        "verified_n": 20 if verified else 0,
        "verified_successes": 20.0 if verified else 0.0,
    }
    after["artifacts"]["artifact"]["state"] = "active"
    if verified:
        validate(before, after, "consolidate", source_lookup=source_lookup)
    else:
        with pytest.raises(LearningGuardError, match="X7"):
            validate(before, after, "consolidate", source_lookup=source_lookup)


def test_servable_steps_require_quote_coverage():
    before = baseline()
    after = deepcopy(before)
    after["artifacts"]["artifact"]["source_quotes"][0]["quote"] = "validate"
    with pytest.raises(LearningGuardError, match="X15"):
        validate(before, after, "monitor", source_lookup=source_lookup)


def test_verified_counts_cannot_exceed_external_outcome_records():
    before = baseline()
    after = deepcopy(before)
    key = digest(["item", "source", 1, "deploy"])
    after["stats"][key] = {
        "alpha": 2.0,
        "beta": 1.0,
        "n": 1.0,
        "verified_n": 2,
        "verified_successes": 1.0,
    }
    with pytest.raises(LearningGuardError, match="X7"):
        validate(before, after, "resolve", source_lookup=source_lookup)
