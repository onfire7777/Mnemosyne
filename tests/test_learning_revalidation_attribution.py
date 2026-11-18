"""Only exact-revision, independently checked artifacts earn retention credit."""

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from eval.learning.probes import VirtualClock
from mnemosyne.experience.candidates import verification_request_id
from mnemosyne.experience.revalidate import revalidate
from mnemosyne.experience.signals import reprocessed_episode, reward, tool_signals, verified_target_outcome
from tests.test_learning_outcome_relevance import _lesson


def _active_due_lesson(clock):
    runtime, lesson = _lesson()
    for served, count in ((False, 8), (True, 12)):
        runtime.mode("t", "exploration", "active" if served else "off")
        for index in range(count):
            clock.advance(seconds=1)
            session = f"train-{served}-{index}"
            context = runtime.prepare_context("t", "u", session, lesson["goal"])
            ids = [row["id"] for row in context["lessons"]]
            assert (lesson["id"] in ids) == served
            events = [{"name": "json_validator", "source": "tool", "check_id": "json",
                       "verdict": served, "target_ids": ids}]
            observed = runtime.observe_turn(
                "t", "u", session, lesson["goal"], '{"ok":true}' if served else "Not JSON",
                receipt_ids=[context["receipt_id"]], used_lessons=ids, tool_events=events,
            )
            runtime.resolve("t", observed["episode_id"])
    runtime.consolidate("t")
    clock.advance(days=2)
    runtime.consolidate("t")
    artifact = runtime.writer.read("t")["artifacts"][lesson["id"]]
    assert artifact["state"] == "active" and artifact["revalidation_step"] == 1
    return runtime, artifact


@pytest.mark.parametrize("target_value,task_value", [(1, -1), (-1, 1), (None, 1)])
def test_runtime_revalidation_uses_the_served_target_not_task_reward(target_value, task_value):
    with VirtualClock() as clock:
        runtime, before = _active_due_lesson(clock)
        clock.advance(seconds=1)
        context = runtime.prepare_context("t", "u", "probe", before["goal"])
        assert before["id"] in [row["id"] for row in context["lessons"]]
        events = []
        if target_value is not None:
            events.append({"name": "json_validator", "source": "tool", "check_id": "json",
                           "verdict": target_value > 0, "target_ids": [before["id"]]})
        events.append({"name": "task_checker", "source": "tool", "check_id": "other-task",
                       "verdict": task_value > 0, "outcome_scope": "task", "final": True})
        observed = runtime.observe_turn(
            "t", "u", "probe", before["goal"], "Result", tool_events=events,
            receipt_ids=[context["receipt_id"]], used_lessons=[before["id"]],
        )
        resolved = runtime.resolve("t", observed["episode_id"])
        assert resolved["reward"] == task_value
        assert resolved["target_outcomes"].get(before["id"], {}).get("value") == target_value
        due = datetime.fromisoformat(before["next_revalidation_at"])
        clock.advance(seconds=(due - clock.value).total_seconds() + 1)
        runtime.consolidate("t")
        state = runtime.writer.read("t")
        after = state["artifacts"][before["id"]]
        assert after["state"] == ("demoted" if target_value == -1 else "active")
        assert after["revalidation_step"] == (2 if target_value == 1 else 1)
        assert after["revalidation_pending"] == (target_value is None)
        assert (resolved["id"] in after["revalidation_episode_ids"]) == (target_value is not None)
        assert state["defects"] == {}
        # Resolving and consolidating the same retained episode is not a new trial.
        assert runtime.resolve("t", resolved["id"]) == resolved
        runtime.consolidate("t")
        replayed = runtime.writer.read("t")["artifacts"][before["id"]]
        assert replayed["revalidation_step"] == after["revalidation_step"]
        assert replayed["revalidation_episode_ids"] == after["revalidation_episode_ids"]


def _revalidation_fixture():
    artifact = {
        "id": "procedure", "kind": "procedure", "revision": 2, "state": "active",
        "steps": ["inspect", "verify"], "created_at": "2026-01-01T00:00:00+00:00",
        "next_revalidation_at": "2026-01-02T00:00:00+00:00", "revalidation_step": 0,
        "source_cids": [], "source_episode_ids": [], "explanation_sources": [],
    }
    episode = {"id": "trial", "status": "resolved", "receipt_ids": [],
               "created_at": "2026-01-03T00:00:00+00:00", "target_outcomes": {}}
    return artifact, episode, {"episodes": {episode["id"]: episode}, "receipts": {}}


def _revalidate(artifact, state):
    revalidate(SimpleNamespace(_sources_live=lambda *args: True), "t", state, artifact,
               datetime(2026, 1, 4, tzinfo=UTC))


@pytest.mark.parametrize("value", [1, -1])
def test_requested_revalidation_uses_its_own_check_not_task_reward(value):
    artifact, episode, state = _revalidation_fixture()
    episode["tool_events"] = [
        {"name": "benchmark_verifier", "source": "tool", "check_id": "retention",
         "verdict": value > 0, "revalidation_request_id": verification_request_id(artifact),
         "tested_steps": artifact["steps"]},
        {"name": "task_checker", "source": "tool", "check_id": "unrelated",
         "verdict": value < 0, "outcome_scope": "task", "final": True},
    ]
    episode["signals"] = tool_signals(episode["tool_events"])
    episode["reward"] = reward(episode["signals"])
    assert episode["reward"] == -value
    _revalidate(artifact, state)
    assert artifact["state"] == ("active" if value == 1 else "demoted")
    assert artifact["revalidation_step"] == int(value == 1)
    assert artifact["revalidation_episode_ids"] == [episode["id"]]
    before = deepcopy(artifact)
    revalidate(SimpleNamespace(_sources_live=lambda *args: True), "t", state, artifact,
               datetime(2026, 1, 20, tzinfo=UTC))
    assert artifact["revalidation_step"] == before["revalidation_step"]
    assert artifact["revalidation_episode_ids"] == before["revalidation_episode_ids"]


@pytest.mark.parametrize("change", [
    {"verdict": None},
    {"revalidation_request_id": "another-request"},
    {"tested_steps": ["verify", "inspect"]},
    {"source": "assistant"},
    {"source": "self_generated"},
    {"source": "provider_self_grade"},
    {"target_ids": ["another-artifact"]},
])
def test_request_annotation_cannot_borrow_an_unrelated_check(change):
    artifact, episode, state = _revalidation_fixture()
    request = {"name": "benchmark_verifier", "source": "tool", "verdict": True,
               "check_id": "retention", "tested_steps": artifact["steps"],
               "revalidation_request_id": verification_request_id(artifact), **change}
    episode["tool_events"] = [request, {"name": "other_checker", "source": "tool",
                                       "check_id": "unrelated", "verdict": True}]
    episode["signals"] = tool_signals(episode["tool_events"])
    episode["reward"] = reward(episode["signals"])
    _revalidate(artifact, state)
    assert artifact["revalidation_step"] == 0
    assert artifact["revalidation_pending"] is True
    assert not artifact.get("revalidation_episode_ids")


@pytest.mark.parametrize("actual,expected", [
    (["verify", "inspect"], ["inspect", "verify"]),
    (["skip"], ["other", "steps"]),
    (["inspect", "verify", "unrelated"], ["inspect", "verify"]),
])
@pytest.mark.parametrize("task_value", [-1, 1])
def test_corrective_steps_do_not_grade_an_unexecuted_or_unassociated_procedure(actual, expected, task_value):
    artifact = {"id": "procedure", "kind": "procedure", "steps": ["inspect", "verify"]}
    events = [{"name": step, "source": "tool", "status": "completed"} for step in actual]
    events.append({"name": "benchmark_verifier", "source": "tool", "verdict": task_value > 0,
                   "expected_steps": expected})
    episode = {"tool_events": events, "signals": tool_signals(events), "used_skills": []}
    assert verified_target_outcome(artifact, episode) is None


@pytest.mark.parametrize("targeted,actual,expected,value", [
    (False, ["inspect", "verify"], ["inspect", "verify"], -1),
    (False, ["inspect", "verify"], ["verify", "inspect"], -1),
    (False, ["inspect", "verify"], ["inspect", "verify"], 1),
    (True, ["verify", "inspect"], ["inspect", "verify"], -1),
    (True, ["verify", "inspect"], ["inspect", "verify"], 1),
])
def test_executed_or_explicitly_verified_target_keeps_its_real_outcome(targeted, actual, expected, value):
    artifact = {"id": "procedure", "kind": "procedure", "steps": ["inspect", "verify"]}
    events = [{"name": step, "source": "tool", "status": "completed"} for step in actual]
    check = {"name": "benchmark_verifier", "source": "tool", "verdict": value > 0,
             "expected_steps": expected}
    if targeted:
        check["target_ids"] = [artifact["id"]]
    events.append(check)
    assert verified_target_outcome(artifact, {"tool_events": events, "signals": tool_signals(events)}) == value


def test_v3_false_target_attribution_is_repaired_once_from_retained_events():
    artifact, episode, state = _revalidation_fixture()
    events = [{"name": step, "source": "tool"} for step in reversed(artifact["steps"])]
    events.append({"name": "benchmark_verifier", "source": "tool", "verdict": False,
                   "expected_steps": artifact["steps"]})
    episode.update(tool_events=events, signals=tool_signals(events), reward=-1, rpe=-1,
                   prediction=0.5, receipt_ids=["receipt"], outcome_version=3, event_parser_version=2,
                   target_outcomes={artifact["id"]: {"value": -1, "rpe": -1}})
    receipts = {"receipt": {"items": [{"kind": "procedure", "item_id": artifact["id"],
                                       "revision": artifact["revision"]}]}}
    before = deepcopy(episode)
    updated = reprocessed_episode(episode, {artifact["id"]: artifact}, receipts)
    assert updated["target_outcomes"] == {}
    assert updated["reward"] == -1  # The task really failed; the ignored procedure did not.
    assert updated["outcome_version"] > 3
    assert updated["tool_events"] == before["tool_events"]
    assert updated["receipt_ids"] == before["receipt_ids"]
    assert episode == before
    assert reprocessed_episode(updated, {artifact["id"]: artifact}, receipts) == updated


@pytest.mark.parametrize("target_value", [-1, 1])
@pytest.mark.parametrize("evidence", [
    "verified", "unrelated_target", "assistant", "self_generated", "provider_self_grade",
])
def test_runtime_v4_repair_preserves_target_diagnostics_without_task_credit(monkeypatch, target_value, evidence):
    runtime, lesson = _lesson()
    context = runtime.prepare_context("t", "u", "diagnostic", lesson["goal"])
    assert [row["id"] for row in context["lessons"]] == [lesson["id"]]
    event = {
        "name": "json_validator", "source": "tool", "check_id": "format",
        "verdict": target_value > 0, "outcome_scope": "diagnostic",
        "target_ids": [lesson["id"]],
    }
    if evidence == "unrelated_target":
        event["target_ids"] = ["unserved-lesson"]
    elif evidence != "verified":
        event["source"] = evidence
    # Exercise real capture/resolution using the persisted v3 contract. Only
    # the version marker changes; no outcomes or finalized rows are fabricated.
    with monkeypatch.context() as legacy:
        legacy.setattr("mnemosyne.experience.runtime.OUTCOME_VERSION", 3)
        observed = runtime.observe_turn(
            "t", "u", "diagnostic", lesson["goal"], "Partial result",
            receipt_ids=[context["receipt_id"]], used_lessons=[lesson["id"]],
            tool_events=[event],
        )
        episode = runtime.resolve("t", observed["episode_id"], expired=True)
    expected = {lesson["id"]: {
        "value": target_value, "rpe": target_value - (2 * episode["prediction"] - 1),
    }} if evidence == "verified" else {}
    assert episode["outcome_version"] == 3
    assert episode["status"] == "unknown"
    assert episode["reward"] is episode["rpe"] is None
    assert episode["target_outcomes"] == expected
    before = runtime.writer.read("t")
    served = next(item for item in before["receipts"][context["receipt_id"]]["items"]
                  if item["item_id"] == lesson["id"])
    assert served["revision"] == lesson["revision"]

    assert runtime.reprocess_outcomes("t") == {"reprocessed": 1, "episode_ids": [episode["id"]]}
    repaired = runtime.episode("t", episode["id"])
    assert repaired["target_outcomes"] == expected
    assert repaired["status"] == "unknown"
    assert repaired["reward"] is repaired["rpe"] is None
    assert repaired["outcome_version"] == 4
    assert repaired["event_parser_version"] == 2
    for field in ("tool_events", "source_cids", "receipt_ids", "prediction", "signals"):
        assert repaired[field] == episode[field]
    state = runtime.writer.read("t")
    assert state["receipts"] == before["receipts"]
    assert state["stats"] == before["stats"]
    assert state["credit"] == before["credit"] == {}
    assert state["artifacts"][lesson["id"]]["state"] == before["artifacts"][lesson["id"]]["state"] == "probation"
    assert state["defects"] == {}
    assert any(row["op"] == "learning.outcome_reprocess" for row in runtime.writer.store.history("t"))
    assert runtime.reprocess_outcomes("t") == {"reprocessed": 0, "episode_ids": []}
    assert runtime.writer.read("t") == state
    runtime.consolidate("t")
    replayed = runtime.writer.read("t")
    assert replayed["episodes"][episode["id"]] == repaired
    assert replayed["stats"] == state["stats"]
    assert replayed["credit"] == {}
    assert replayed["artifacts"][lesson["id"]]["state"] == "probation"
    assert replayed["defects"] == {}


@pytest.mark.parametrize("case", ["stale_attribution", "rating_with_unrelated_test", "wrong_revision", "missing_target"])
def test_serving_requires_an_independent_result_for_the_exact_revision(case):
    artifact, episode, state = _revalidation_fixture()
    artifact["kind"] = "lesson" if case == "rating_with_unrelated_test" else "procedure"
    events = [{"name": step, "source": "tool"} for step in reversed(artifact["steps"])]
    events.append({"name": "benchmark_verifier", "source": "tool", "verdict": False,
                   "expected_steps": artifact["steps"]})
    episode.update(tool_events=events, signals=tool_signals(events), reward=-1,
                   receipt_ids=["receipt"], target_outcomes={artifact["id"]: {"value": -1}})
    if case == "rating_with_unrelated_test":
        episode["signals"].append({"kind": "rating", "weight": .9, "value": 1,
                                   "target_ids": [artifact["id"]]})
        episode["target_outcomes"][artifact["id"]]["value"] = 1
    if case in {"wrong_revision", "missing_target"}:
        episode["tool_events"][-1]["target_ids"] = [artifact["id"]]
        episode["signals"] = tool_signals(episode["tool_events"])
    if case == "missing_target":
        episode["target_outcomes"] = {}
    state["receipts"]["receipt"] = {"items": [{"item_id": artifact["id"],
        "revision": 1 if case == "wrong_revision" else artifact["revision"]}]}
    _revalidate(artifact, state)
    assert artifact["state"] == "active"
    assert artifact["revalidation_step"] == 0
    assert artifact["revalidation_pending"] is True
    assert not artifact.get("revalidation_episode_ids")


def test_independent_failed_request_is_not_hidden_by_a_served_target_pass():
    artifact, episode, state = _revalidation_fixture()
    episode["tool_events"] = [
        {"name": "benchmark_verifier", "source": "tool", "verdict": False,
         "check_id": "requested", "revalidation_request_id": verification_request_id(artifact),
         "tested_steps": artifact["steps"]},
        {"name": "benchmark_verifier", "source": "tool", "verdict": True,
         "check_id": "targeted", "target_ids": [artifact["id"]]},
    ]
    episode.update(signals=tool_signals(episode["tool_events"]), reward=-1,
                   target_outcomes={artifact["id"]: {"value": 1}}, receipt_ids=["receipt"])
    state["receipts"]["receipt"] = {"items": [{"item_id": artifact["id"], "revision": artifact["revision"]}]}
    _revalidate(artifact, state)
    assert artifact["state"] == "demoted"
    assert artifact["revalidation_step"] == 0
    assert artifact["revalidation_episode_ids"] == [episode["id"]]
