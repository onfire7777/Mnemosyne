"""Late host evidence amends derived outcomes through the existing native gates."""

from copy import deepcopy

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.guards import LearningGuardError, validate
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.hosts.codex import _tool_event


def fixture(outcome=True):
    runtime = LearningRuntime(LocalMemoryEngine())
    context = runtime.prepare_context("t", "u", "s", "Check fixture")
    events = [] if outcome is None else [_tool_event("checker", {"verdict": outcome}, tool_id="first")]
    result = runtime.observe_turn("t", "u", "s", "Check fixture", "Result",
                                  receipt_ids=[context["receipt_id"]], tool_events=events)
    runtime.resolve("t", result["episode_id"])
    return runtime, result["episode_id"]


@pytest.mark.parametrize("initial,late,expected", [(True, False, -1), (None, True, 1)])
def test_late_evidence_changes_only_derived_outcome_and_is_idempotent(initial, late, expected):
    runtime, identifier = fixture(initial)
    original = runtime.episode("t", identifier)
    event = _tool_event("checker", {"verdict": late}, tool_id="late")
    assert runtime.reconcile_host_tool_events("t", "u", "s", identifier, [event])["amended"] == 1
    repaired = runtime.episode("t", identifier)
    assert repaired["status"] == "resolved" and repaired["reward"] == expected
    assert repaired["tool_events"] == [*original["tool_events"], event]
    for field in ("id", "user_text", "assistant_text", "receipt_ids", "prediction", "used_skills", "used_lessons"):
        assert repaired.get(field) == original.get(field)
    assert len(repaired["late_event_source_cids"]) == 1
    source = runtime.engine.get_evidence("t", repaired["late_event_source_cids"][0])
    assert source.metadata["source_episode_id"] == identifier
    before = runtime.writer.read("t")
    assert runtime.reconcile_host_tool_events("t", "u", "s", identifier, [event])["amended"] == 0
    assert runtime.writer.read("t") == before


@pytest.mark.parametrize("mutation", ["owner", "session", "self_grade", "missing_id", "existing_call"])
def test_invalid_late_event_is_rejected_without_state_mutation(mutation):
    runtime, identifier = fixture()
    before = runtime.writer.read("t")
    event = _tool_event("checker", {"verdict": False}, tool_id="late")
    if mutation == "self_grade":
        event["source"] = "provider_self_grade"
    elif mutation == "missing_id":
        event.pop("call_id")
    elif mutation == "existing_call":
        event["call_id"] = event["tool_use_id"] = "first"
    with pytest.raises(ValueError):
        runtime.reconcile_host_tool_events("t", "other" if mutation == "owner" else "u",
            "other" if mutation == "session" else "s", identifier, [event])
    assert runtime.writer.read("t") == before


@pytest.mark.parametrize("mutation", ["reward_override", "replace_event", "wrong_episode", "wrong_owner", "missing_source"])
def test_x3_accepts_only_exact_source_bound_reprocessing(mutation):
    runtime, identifier = fixture()
    before = runtime.writer.read("t")
    runtime.reconcile_host_tool_events("t", "u", "s", identifier,
        [_tool_event("checker", {"verdict": False}, tool_id="late")])
    after = runtime.writer.read("t")
    source_id = after["episodes"][identifier]["late_event_source_cids"][0]
    source_override = None
    if mutation == "reward_override":
        after["episodes"][identifier].update(reward=1, rpe=1)
    elif mutation == "replace_event":
        after["episodes"][identifier]["tool_events"][0]["verdict"] = False
    else:
        source_override = deepcopy(runtime.engine.get_evidence("t", source_id))
        if mutation == "wrong_episode":
            source_override.metadata["source_episode_id"] = "another"
        elif mutation == "wrong_owner":
            source_override.user_id = "other"

    def lookup(cid):
        if mutation == "missing_source" and cid == source_id:
            return None
        if source_override is not None and cid == source_id:
            return source_override
        return runtime.engine.get_evidence("t", cid)

    with pytest.raises(LearningGuardError, match="X3"):
        validate(before, after, "outcome_reprocess", source_lookup=lookup)


def test_erased_episode_cannot_receive_late_evidence():
    runtime, identifier = fixture()
    source = runtime.episode("t", identifier)["source_cids"][0]
    runtime.engine.forget("t", source)
    with pytest.raises(ValueError, match="live owned"):
        runtime.reconcile_host_tool_events("t", "u", "s", identifier,
            [_tool_event("checker", {"verdict": True}, tool_id="late")])
