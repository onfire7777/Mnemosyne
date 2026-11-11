"""Learning distinguishes task evidence from debugging and unrelated memories."""

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.experience.signals import reward, tool_signals
from mnemosyne.policy import OperatingPolicy


def test_diagnostic_exits_do_not_outvote_verified_results():
    events = [{"name": "shell", "exit_code": 1, "command": "rg missing"}] * 15
    events += [{"name": "shell", "command": "pytest", "passed": 20, "failed": 0}]
    assert reward(tool_signals(events)) == 1


def test_unclassified_command_exit_is_not_a_task_judgment():
    assert reward(tool_signals([{"name": "shell", "exit_code": 1}])) is None
    assert reward(tool_signals([{
        "name": "shell", "exit_code": 1, "outcome_scope": "task", "final": True,
    }])) == -1


def test_verified_retry_replaces_only_the_same_check():
    events = [
        {"check_id": "unit", "passed": 0, "failed": 10},
        {"check_id": "unit", "passed": 10, "failed": 0},
    ]
    assert reward(tool_signals(events)) == 1
    events.append({"check_id": "integration", "passed": 0, "failed": 10})
    assert reward(tool_signals(events)) == -1


def test_a_shared_tool_name_does_not_establish_the_same_check():
    assert reward(tool_signals([
        {"name": "verifier", "verdict": False},
        {"name": "verifier", "verdict": True},
    ])) == -1


def test_final_task_verifier_supersedes_attempts_but_not_user_correction():
    events = [
        {"check_id": "attempt", "verdict": False},
        {"check_id": "task", "verdict": True, "outcome_scope": "task", "final": True},
    ]
    assert reward(tool_signals(events)) == 1


def _lesson():
    runtime = LearningRuntime(LocalMemoryEngine(policy=OperatingPolicy(learning_exploration_rate=1)))
    observed = runtime.observe_turn("t", "u", "s", "Format the build summary", "Draft")
    runtime.record_signal("t", episode_id=observed["episode_id"], kind="correction",
                          value=-1, evidence="Use JSON for build summaries.", final=True)
    runtime.consolidate("t")
    lesson = next(row for row in runtime.writer.read("t")["artifacts"].values()
                  if row["kind"] == "lesson")
    return runtime, lesson


@pytest.mark.parametrize("targeted", [False, True])
def test_task_pass_does_not_verify_an_unchecked_lesson(targeted):
    from mnemosyne.experience.runtime import stat_key
    runtime, lesson = _lesson()
    context = runtime.prepare_context("t", "u", "next", "Format the build summary")
    assert [row["id"] for row in context["lessons"]] == [lesson["id"]]
    event = {"name": "json_validator", "verdict": True, "output": "JSON object validated"}
    if targeted:
        event["target_ids"] = [lesson["id"]]
    observed = runtime.observe_turn("t", "u", "next", "Format the build summary", '{"ok":true}',
        receipt_ids=[context["receipt_id"]], used_lessons=[lesson["id"]], tool_events=[event])
    runtime.resolve("t", observed["episode_id"])
    row = runtime.writer.read("t")["stats"][stat_key("lesson", lesson["id"], 1, lesson["task_class"])]
    assert row["served_n"] == 1
    assert row.get("verified_n", 0) == int(targeted)


def test_self_authored_target_verdict_is_never_learning_evidence():
    assert tool_signals([{"source": "assistant", "verdict": True, "target_ids": ["lesson"]}]) == []


def test_target_failure_is_not_hidden_by_unrelated_success():
    from mnemosyne.experience.runtime import stat_key
    runtime, lesson = _lesson()
    context = runtime.prepare_context("t", "u", "next", "Format the build summary")
    observed = runtime.observe_turn("t", "u", "next", "Format the build summary", "Not JSON",
        receipt_ids=[context["receipt_id"]], tool_events=[
            {"check_id": "build", "verdict": True},
            {"check_id": "format", "verdict": False, "target_ids": [lesson["id"]]},
        ])
    runtime.resolve("t", observed["episode_id"])
    row = runtime.writer.read("t")["stats"][stat_key("lesson", lesson["id"], 1, lesson["task_class"])]
    assert row["verified_n"] == 1
    assert row["verified_successes"] == 0
    assert row["served_successes"] == 0
    assert row["beta"] == 2


def test_targeted_retrieved_fact_failure_has_its_own_outcome():
    from mnemosyne.models import Evidence
    from mnemosyne.experience.runtime import stat_key
    engine = LocalMemoryEngine()
    cid = engine.append_evidence(Evidence(tenant_id="t", user_id="u", actor="user",
        source_type="chat", content="The release checklist is in docs/release.md.",
        trust_tier=1, access_policy={"tenant": "t"}))
    runtime = LearningRuntime(engine)
    runtime.mode("t", "exploration", "off")
    context = runtime.prepare_context("t", "u", "s", "Where is the release checklist?")
    state = runtime.writer.read("t")
    receipt = state["receipts"][context["receipt_id"]]
    item = next(item for item in receipt["items"] if item["item_id"] == cid)
    assert cid not in state["artifacts"]
    observed = runtime.observe_turn("t", "u", "s", receipt["query"], "Found it",
        receipt_ids=[context["receipt_id"]], tool_events=[
            {"check_id": "build", "verdict": True},
            {"check_id": "file_exists", "verdict": False, "target_ids": [cid]},
        ])
    episode = runtime.resolve("t", observed["episode_id"])
    assert episode["target_outcomes"][cid]["value"] == -1
    row = runtime.writer.read("t")["stats"][stat_key("item", cid, item["revision"], receipt["task_class"])]
    assert row["verified_n"] == 1
    assert row["verified_successes"] == row["served_successes"] == 0
    assert row["last_outcome"] == -1


def test_legacy_reward_repair_is_audited_idempotent_and_preserves_observations():
    from copy import deepcopy
    from mnemosyne.experience.signals import signal
    runtime = LearningRuntime(LocalMemoryEngine())
    context = runtime.prepare_context("t", "u", "legacy", "Check project tests")
    events = [{"name": "shell", "exit_code": 1, "command": "rg missing"}] * 15
    events.append({"name": "shell", "command": "pytest", "passed": 20, "failed": 0})
    key = runtime.observe_turn("t", "u", "legacy", "Check project tests", "Finished",
        tool_events=events, receipt_ids=[context["receipt_id"]])["episode_id"]
    # Model the persisted pre-v2 row before its original resolution.
    def legacy(state):
        row = state["episodes"][key]
        row.pop("outcome_version")
        row["signals"] = [signal("exit_code", -1)] * 15 + [signal("tests", 1)]
    runtime.writer.apply("t", "capture", legacy)
    before = deepcopy(runtime.resolve("t", key))
    receipts = deepcopy(runtime.writer.read("t")["receipts"])
    assert before["reward"] < 0
    assert runtime.reprocess_outcomes("t")["reprocessed"] == 1
    after = runtime.episode("t", key)
    assert after["reward"] == 1
    assert after["tool_events"] == before["tool_events"]
    assert after["source_cids"] == before["source_cids"]
    assert after["prediction"] == before["prediction"]
    assert runtime.writer.read("t")["receipts"] == receipts
    assert runtime.reprocess_outcomes("t")["reprocessed"] == 0
    assert any(event["op"] == "learning.outcome_reprocess" for event in runtime.writer.store.history("t"))
