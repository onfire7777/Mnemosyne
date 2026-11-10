"""Current exact-query corrections can enter independently scored revision trials."""

from copy import deepcopy

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.runtime import LearningRuntime

QUERY = "Inspect the weekly dependency report"
TASK = "weekly-report"
OLD_STEPS = ["read_report", "inspect_dependencies"]
NEW_STEPS = ["read_report", "compare_digest", "inspect_dependencies"]


def context(runtime, query=QUERY):
    return runtime.prepare_context("t", "u", "release", query, task_type=TASK)


def turn(runtime, steps, *, success, expected=None, prepared=None, query=QUERY,
         verification_source="tool", verifier_value=None, additional_signals=()):
    prepared = prepared or context(runtime, query)
    verification = {"source": verification_source, "success": success,
                    "output": "Report checker checked the executed sequence"}
    if expected is not None:
        verification["expected_steps"] = expected
    result = runtime.observe_turn(
        "t", "u", "release", query, "", receipt_ids=[prepared["receipt_id"]],
        tool_events=[*({"name": step, "source": "tool", "output": step} for step in steps),
                     verification],
    )
    for kind, value in additional_signals:
        runtime.record_signal("t", episode_id=result["episode_id"], kind=kind,
                              value=value)
    value = (1 if success else -1) if verifier_value is None else verifier_value
    runtime.record_signal("t", episode_id=result["episode_id"], kind="verifier",
                          value=value, final=True)
    return result["episode_id"]


def proven_runtime():
    runtime = LearningRuntime(LocalMemoryEngine())
    runtime.engine.policy.learning_exploration_rate = 0.5
    for _ in range(2):
        turn(runtime, OLD_STEPS, success=True)
    runtime.consolidate("t")
    for _ in range(240):
        prepared = context(runtime)
        offered = prepared["procedures"]
        turn(runtime, OLD_STEPS if offered else ["skip_report"],
             success=bool(offered), expected=None if offered else OLD_STEPS,
             prepared=prepared)
        runtime.consolidate("t")
        active = [item for item in runtime.writer.read("t")["artifacts"].values()
                  if item["state"] == "active"]
        if active:
            return runtime, active[0]
    raise AssertionError("Actual served and control outcomes did not establish an incumbent")


def served_context(runtime, artifact_id):
    for _ in range(100):
        prepared = context(runtime)
        if any(item["id"] == artifact_id for item in prepared["procedures"]):
            return prepared
    raise AssertionError("The active incumbent was never offered")


def changed_release(runtime, incumbent):
    prepared = served_context(runtime, incumbent["id"])
    correction = turn(runtime, OLD_STEPS, success=False, expected=NEW_STEPS,
                      prepared=prepared)
    supports = [turn(runtime, NEW_STEPS, success=True) for _ in range(2)]
    return correction, supports


def test_verified_current_correction_enters_revision_trial_without_erasing_history():
    runtime, incumbent = proven_runtime()
    before = deepcopy(runtime.writer.read("t"))
    correction, supports = changed_release(runtime, incumbent)
    runtime.consolidate("t")
    state = runtime.writer.read("t")
    revisions = [item for item in state["artifacts"].values()
                 if item.get("revision_evidence")]
    assert len(revisions) == 1
    revision = revisions[0]
    assert revision["steps"] == NEW_STEPS
    assert revision["state"] == "probation"
    assert revision["parent_revision"] == incumbent["id"]
    assert revision["ab_trial"]["status"] == "pending"
    assert revision["gate_passed"]
    assert revision["gate_evidence"]["protected_passed"]
    assert set(revision["source_episode_ids"]) == {correction, *supports}
    assert set(revision["gate_evidence"]["replay_episode_ids"]) == {correction, *supports}
    assert state["artifacts"][incumbent["id"]]["content"] == incumbent["content"]
    assert all(state["episodes"][key] == row for key, row in before["episodes"].items())
    runtime.consolidate("t")
    assert set(runtime.writer.read("t")["artifacts"]) == set(state["artifacts"])
    for _ in range(120):
        prepared = context(runtime)
        offered = prepared["procedures"]
        executed = offered[0]["steps"] if offered else ["skip_report"]
        success = executed == NEW_STEPS
        turn(runtime, executed, success=success,
             expected=None if success else NEW_STEPS, prepared=prepared)
        runtime.consolidate("t")
        state = runtime.writer.read("t")
        if state["artifacts"][revision["id"]]["state"] == "active":
            break
    updated = state["artifacts"][revision["id"]]
    assert updated["state"] == "active"
    assert updated["ab_trial"]["status"] == "promote"
    assert state["artifacts"][incumbent["id"]]["state"] == "retired"
    served = served_context(runtime, revision["id"])
    assert served["procedures"][0]["steps"] == NEW_STEPS


@pytest.mark.parametrize("failure", [
    "one_success", "different_query", "contrary_current_success", "erased_support",
    "erased_correction", "expired_support", "expired_correction", "assistant_correction",
    "positive_correction_verdict", "negative_support_verdict",
])
def test_current_revision_requires_matching_live_external_support(failure):
    runtime, incumbent = proven_runtime()
    prepared = served_context(runtime, incumbent["id"])
    correction = turn(
        runtime, OLD_STEPS, success=False, expected=NEW_STEPS, prepared=prepared,
        verification_source="assistant" if failure == "assistant_correction" else "tool",
        verifier_value=1 if failure == "positive_correction_verdict" else None,
        additional_signals=(("critic", -1), ("rating", -1))
        if failure == "positive_correction_verdict" else (),
    )
    support = turn(
        runtime, NEW_STEPS, success=True,
        verifier_value=-1 if failure == "negative_support_verdict" else None,
        additional_signals=(("critic", 1), ("rating", 1))
        if failure == "negative_support_verdict" else (),
    )
    if failure != "one_success":
        turn(runtime, NEW_STEPS, success=True,
             query="Inspect the emergency dependency report" if failure == "different_query" else QUERY)
    if failure == "contrary_current_success":
        turn(runtime, OLD_STEPS, success=True)
    if failure.startswith(("erased_", "expired_")):
        source = correction if failure.endswith("correction") else support
        cid = runtime.writer.read("t")["episodes"][source]["source_cids"][0]
        if failure.startswith("erased_"):
            runtime.engine.forget("t", cid)
        else:
            evidence = runtime.engine.evidence[runtime.engine._evidence_key("t", "main", cid)]
            evidence.access_policy = {
                **evidence.access_policy, "expires_at": "2000-01-01T00:00:00+00:00",
            }
    runtime.consolidate("t")
    revisions = [item for item in runtime.writer.read("t")["artifacts"].values()
                 if item.get("revision_evidence")]
    assert not any(item["state"] == "probation" for item in revisions)


@pytest.mark.parametrize("mode", ["off", "shadow", "paused"])
def test_corrected_revision_obeys_learning_collection_controls(mode):
    runtime, incumbent = proven_runtime()
    changed_release(runtime, incumbent)
    if mode == "paused":
        runtime.pause("t")
    else:
        runtime.mode("t", "lessons", mode)
    before = deepcopy(runtime.writer.read("t")["artifacts"])
    runtime.consolidate("t")
    assert runtime.writer.read("t")["artifacts"] == before
