"""Legacy entry points share native induction identities and observations."""

from copy import deepcopy

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.learning import LearningSystem, Trajectory


def observed_failure(engine, *, user="u", correction=False):
    runtime = LearningRuntime(engine)
    query = "Deploy inventory"
    receipt = runtime.prepare_context("t", user, "s-" + user, query, task_type="deploy")
    observed = runtime.observe_turn("t", user, "s-" + user, query, "ran upload",
        receipt_ids=[receipt["receipt_id"]], tool_events=[{
            "name": "benchmark_verifier", "success": False, "source": "tool",
            "expected_steps": ["validate", "upload"], "output": "validate then upload"}])
    runtime.record_signal("t", episode_id=observed["episode_id"],
        kind="correction" if correction else "verifier", value=-1,
        evidence="Validate before uploading." if correction else "validation missing", final=True)
    return runtime, observed["episode_id"]


def test_legacy_correction_induction_reuses_native_lesson_and_its_lifecycle():
    runtime, episode_id = observed_failure(LocalMemoryEngine(), correction=True)
    runtime.consolidate("t")
    native = next(row for row in runtime.writer.read("t")["artifacts"].values()
                  if row["kind"] == "lesson")
    system = LearningSystem(runtime.engine)
    system.load_native(["t"])
    attribution = system.attribute_failure(episode_id)
    before = deepcopy(runtime.writer.read("t"))
    lesson = system.induce_lesson(attribution)
    assert lesson.id == native["id"]
    assert lesson.content == "Validate before uploading."
    assert lesson.status == native["state"]
    assert runtime.writer.read("t") == before


def test_legacy_procedure_induction_reuses_native_corrective_steps():
    runtime, episode_id = observed_failure(LocalMemoryEngine())
    runtime.consolidate("t")
    native = next(row for row in runtime.writer.read("t")["artifacts"].values()
                  if row["kind"] == "procedure")
    system = LearningSystem(runtime.engine)
    system.load_native(["t"])
    lesson = system.induce_lesson(system.attribute_failure(episode_id))
    before = deepcopy(runtime.writer.read("t"))
    procedure = system.induce_procedure(lesson)
    assert procedure.id == native["id"]
    assert procedure.body == "validate\nupload"
    assert procedure.status == native["state"]
    assert runtime.writer.read("t") == before


def test_legacy_first_then_native_consolidation_keeps_one_procedure():
    runtime, episode_id = observed_failure(LocalMemoryEngine())
    system = LearningSystem(runtime.engine)
    system.load_native(["t"])
    lesson = system.induce_lesson(system.attribute_failure(episode_id))
    procedure = system.induce_procedure(lesson)
    assert procedure.status == "candidate"
    metadata = {key: procedure.to_record()[key] for key in ("name", "signature", "procedure_kind")}
    runtime.consolidate("t")
    procedures = [row for row in runtime.writer.read("t")["artifacts"].values()
                  if row["kind"] == "procedure"]
    assert len(procedures) == 1
    assert procedures[0]["id"] == procedure.id
    assert procedures[0]["state"] == "probation"
    assert {key: procedures[0].get(key) for key in metadata} == metadata


def test_repeated_historical_induction_keeps_one_unverified_record():
    system = LearningSystem(LocalMemoryEngine())
    trajectory = Trajectory("t", "u", "s", "calculate",
        [{"name": "arithmetic", "status": "failed", "error": "wrong sum"}],
        "failure", -1, "v1")
    system.log_trajectory(trajectory)
    attribution = system.attribute_failure(trajectory.id)
    lesson = system.induce_lesson(attribution)
    procedure = system.induce_procedure(lesson)
    before = deepcopy(LearningRuntime(system.engine).writer.read("t"))
    assert system.induce_lesson(attribution) is lesson
    assert system.induce_procedure(lesson) is procedure
    after = LearningRuntime(system.engine).writer.read("t")
    assert after == before
    assert after["artifacts"][lesson.id]["origin"] == "legacy"
    assert after["artifacts"][procedure.id]["state"] == "candidate"
    assert not after["credit"]


def test_repeated_induction_preserves_pending_compatibility_edits():
    system = LearningSystem(LocalMemoryEngine())
    trajectory = Trajectory("t", "u", "s", "calculate",
        [{"name": "arithmetic", "status": "failed", "error": "wrong sum"}],
        "failure", -1, "v1")
    system.log_trajectory(trajectory)
    attribution = system.attribute_failure(trajectory.id)
    lesson = system.induce_lesson(attribution)
    procedure = system.induce_procedure(lesson)

    lesson.votes = 7
    assert system.induce_procedure(lesson) is procedure
    assert lesson.votes == 7
    procedure.name = "Checked calculation sequence"
    assert system.induce_lesson(attribution) is lesson
    assert procedure.name == "Checked calculation sequence"
    state = LearningRuntime(system.engine).writer.read("t")
    assert state["artifacts"][lesson.id]["votes"] == 7
    assert state["artifacts"][procedure.id]["name"] == procedure.name
    assert len(state["artifacts"]) == 2
    assert not state["credit"]


def test_repeated_induction_preserves_compatibility_conflict_detection():
    system = LearningSystem(LocalMemoryEngine())
    trajectory = Trajectory("t", "u", "s", "calculate",
        [{"name": "arithmetic", "status": "failed", "error": "wrong sum"}],
        "failure", -1, "v1")
    system.log_trajectory(trajectory)
    lesson = system.induce_lesson(system.attribute_failure(trajectory.id))
    system.induce_procedure(lesson)
    other = LearningSystem(system.engine)
    other.load_native(["t"])
    lesson.votes = 1
    other.lessons[lesson.id].votes = 2
    other.persist_native(["t"])
    with pytest.raises(ValueError, match="concurrent learning edit"):
        system.induce_procedure(lesson)
    assert LearningRuntime(system.engine).writer.read("t")["artifacts"][lesson.id]["votes"] == 2


def test_same_correction_for_distinct_users_keeps_distinct_native_artifacts():
    engine = LocalMemoryEngine()
    runtime, first = observed_failure(engine, correction=True)
    _, second = observed_failure(engine, user="other", correction=True)
    system = LearningSystem(engine)
    system.load_native(["t"])
    one = system.induce_lesson(system.attribute_failure(first))
    two = system.induce_lesson(system.attribute_failure(second))
    assert one.id != two.id
    assert one.to_record()["user_id"] == "u"
    assert two.to_record()["user_id"] == "other"
    assert one.content == two.content == "Validate before uploading."
    assert not runtime.writer.read("t")["credit"]


def test_hot_loop_diagnostics_deduplicate_without_widening_scope_or_reward():
    system = LearningSystem(LocalMemoryEngine())
    claim = {"category": "math", "expression": "1+1", "expected": 3, "task": "invoice"}
    _, first = system.hot_loop_verify("t", claim)
    before = deepcopy(LearningRuntime(system.engine).writer.read("t"))
    _, repeated = system.hot_loop_verify("t", claim)
    assert repeated is first
    assert LearningRuntime(system.engine).writer.read("t") == before
    _, other = system.hot_loop_verify("t", {**claim, "task": "calendar"})
    assert other.id != first.id
    assert first.status == other.status == "candidate"
    state = LearningRuntime(system.engine).writer.read("t")
    assert not state["episodes"] and not state["credit"] and not state["stats"]


@pytest.mark.parametrize("event", [
    {"name": "validator", "verdict": "fail", "output": "schema mismatch"},
    {"name": "tests", "passed": 0, "failed": 2, "output": "two failing checks"},
    {"name": "compile", "exit_code": 1, "error": "syntax error"},
])
def test_failure_attribution_accepts_the_shared_external_outcome_formats(event):
    system = LearningSystem(LocalMemoryEngine())
    trajectory = Trajectory("t", "u", "s", "check", [event], "failure", -1, "v1")
    system.log_trajectory(trajectory)
    attribution = system.attribute_failure(trajectory.id)
    assert attribution.cause == event.get("error", event.get("output"))
    assert len(attribution.evidence) == 1
    assert attribution.confidence == 0
    assert not LearningRuntime(system.engine).writer.read("t")["credit"]
