"""Corrected historical outcomes retract unsupported serving authority."""

from copy import deepcopy

import pytest

from mnemosyne.experience.runtime import stat_key
from mnemosyne.experience.stats import Posterior
from tests.test_learning_outcome_relevance import _lesson


def legacy_proven_lesson(*, diagnostic_successes=False):
    runtime, lesson = _lesson()
    for success, count in [(False, 8), (True, 12)]:
        runtime.mode("t", "exploration", "active" if success else "off")
        for index in range(count):
            session = f"legacy-{success}-{index}"
            context = runtime.prepare_context("t", "u", session, lesson["goal"])
            event = {
                "name": "benchmark_verifier" if diagnostic_successes else "check",
                "source": "tool", "verdict": success, "output": "Observed check",
            }
            if diagnostic_successes and success:
                event["outcome_scope"] = "diagnostic"
            result = runtime.observe_turn("t", "u", session, lesson["goal"], "",
                receipt_ids=[context["receipt_id"]],
                tool_events=[event])
            def legacy_outcome(state):
                row = state["episodes"][result["episode_id"]]
                row.pop("outcome_version")
                if diagnostic_successes:
                    # Older derived signals lost scope; retain the raw event so
                    # audited migration can retract diagnostic-only successes.
                    for signal in row["signals"]:
                        signal.pop("outcome_scope", None)
            runtime.writer.apply("t", "capture", legacy_outcome)
            runtime.resolve("t", result["episode_id"])
    runtime.consolidate("t")
    assert runtime.writer.read("t")["artifacts"][lesson["id"]]["state"] == "active"
    return runtime, lesson


@pytest.mark.parametrize("protection", [None, "pin", "lock"])
def test_reprocessing_withdraws_unsupported_active_lesson(protection):
    runtime, lesson = legacy_proven_lesson()
    if protection:
        getattr(runtime, protection)("t", lesson["id"])
    before = deepcopy(runtime.writer.read("t")["receipts"])
    assert runtime.reprocess_outcomes("t")["reprocessed"] == 20
    state = runtime.writer.read("t")
    key = stat_key("lesson", lesson["id"], 1, lesson["task_class"])
    assert state["stats"][key].get("verified_n", 0) == 0
    assert state["receipts"] == before
    if protection:
        assert lesson["id"] in state["policy"]["outcome_quarantine"]
        assert runtime.prepare_context("t", "u", "after", lesson["goal"])["lessons"] == []
        getattr(runtime, protection)("t", lesson["id"], False)
        state = runtime.writer.read("t")
        assert lesson["id"] not in state["policy"]["outcome_quarantine"]
    assert state["artifacts"][lesson["id"]]["state"] == "probation"
    assert runtime.reprocess_outcomes("t")["reprocessed"] == 0


def test_quarantined_protected_confidence_stays_a_historical_snapshot():
    runtime, lesson = legacy_proven_lesson(diagnostic_successes=True)
    key = stat_key("lesson", lesson["id"], 1, lesson["task_class"])
    def retain_confidence(state):
        state["artifacts"][lesson["id"]]["confidence"] = Posterior.from_dict(state["stats"][key]).mean
    runtime.writer.apply("t", "capture", retain_confidence)
    runtime.lock("t", lesson["id"])
    before = runtime.writer.read("t")
    snapshot = deepcopy(before["artifacts"][lesson["id"]])
    assert snapshot["locked"] is True
    assert before["stats"][key]["n"] > 0
    assert snapshot["confidence"] == Posterior.from_dict(before["stats"][key]).mean
    assert runtime.reprocess_outcomes("t")["reprocessed"] == 20
    state = runtime.writer.read("t")
    assert state["receipts"] == before["receipts"]
    diagnostic_ids = [
        key for key, row in before["episodes"].items()
        if any(event.get("outcome_scope") == "diagnostic" for event in row["tool_events"])
    ]
    assert len(diagnostic_ids) == 12
    for episode_id in diagnostic_ids:
        repaired = state["episodes"][episode_id]
        assert repaired["tool_events"] == before["episodes"][episode_id]["tool_events"]
        assert repaired["status"] == "unknown" and repaired["reward"] is None
    assert state["stats"][key]["n"] == 0
    assert state["stats"][key].get("verified_n", 0) == 0
    assert state["artifacts"][lesson["id"]] == snapshot
    assert snapshot["confidence"] != Posterior.from_dict(state["stats"][key]).mean
    assert state["policy"]["outcome_quarantine"][lesson["id"]]["reason"] == "reprocessed_outcomes_require_verification"
    assert state["defects"] == {}
    assert runtime.prepare_context("t", "u", "blocked", lesson["goal"])["lessons"] == []
    assert runtime.writer.read("t")["artifacts"][lesson["id"]] == snapshot
    runtime.lock("t", lesson["id"], False)
    state = runtime.writer.read("t")
    saved = state["artifacts"][lesson["id"]]
    assert saved["state"] == "probation" and "confidence" not in saved
    assert saved["locked"] is False
    assert lesson["id"] not in state["policy"]["outcome_quarantine"]
    assert state["defects"] == {}


def test_skill_library_projects_targeted_failure_and_quarantine(tmp_path):
    from tests.test_skill_lifecycle_projection import managed_skill

    runtime, store, skill_id, artifact, _ = managed_skill(tmp_path)
    runtime.engine.policy.learning_exploration_rate = 1
    context = runtime.prepare_context("t", "u", "targeted", "release-guide", task_type="release")
    assert context["skills"]
    observed = runtime.observe_turn("t", "u", "targeted", "release-guide", "",
        receipt_ids=[context["receipt_id"]], tool_events=[
            {"verdict": False, "target_ids": [artifact["id"]]},
            {"verdict": True, "outcome_scope": "task", "final": True},
        ])
    resolved = runtime.resolve("t", observed["episode_id"])
    assert resolved["reward"] == 1
    assert resolved["target_outcomes"][artifact["id"]]["value"] == -1
    runtime._sync_library_revision_states("t")
    events = store._rows("SELECT probability FROM skill_outcome_events WHERE skill_id = ?", (skill_id,))
    assert [row["probability"] for row in events] == [0]
    runtime.writer.apply("t", "capture", lambda state: state["policy"].setdefault("outcome_quarantine", {}).update({artifact["id"]: {"reason": "outcomes_reprocessed"}}))
    runtime._sync_library_revision_states("t")
    assert store.status(skill_id)["native_states"][artifact["id"]] == "probation"
