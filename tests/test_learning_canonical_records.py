"""One native owner for legacy compatibility objects and observed learning."""

from copy import deepcopy
import json

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.guards import LearningGuardError
from mnemosyne.experience.receipts import digest
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.experience.store import empty_state
from mnemosyne.learning import LearningSystem, Lesson, Procedure, Trajectory
from mnemosyne.models import Evidence
from mnemosyne.runtime_state import RuntimeState


def old_trajectory(**kwargs):
    return Trajectory("t", "u", "s", "a task", [{"name": "validate"}], "success", 1, "v1", **kwargs)


def observed_candidate(engine):
    runtime = LearningRuntime(engine)
    receipt = runtime.prepare_context("t", "u", "s", "Deploy inventory", task_type="deploy")
    episode = runtime.observe_turn("t", "u", "s", "Deploy inventory", "ran upload",
        receipt_ids=[receipt["receipt_id"]], tool_events=[{
            "name": "benchmark_verifier", "success": False,
            "expected_steps": ["validate", "upload"], "output": "validate then upload"}])
    runtime.record_signal("t", episode_id=episode["episode_id"], kind="verifier", value=-1, final=True)
    runtime.consolidate("t")
    return runtime, next(iter(runtime.writer.read("t")["artifacts"]))


def test_returned_compatibility_objects_keep_identity_and_save_mutations():
    engine = LocalMemoryEngine()
    system = LearningSystem(engine)
    trajectory = old_trajectory()
    system.log_trajectory(trajectory)
    attribution = system.attribute_failure(trajectory.id)
    lesson = system.induce_lesson(attribution)
    procedure = system.induce_procedure(lesson)
    system.persist_native()
    assert system.trajectories[trajectory.id] is trajectory
    assert system.lessons[lesson.id] is lesson
    assert system.procedures[procedure.id] is procedure
    lesson.content = "corrected historical observation"
    procedure.body = "corrected historical sequence"
    trajectory.task = "corrected task"
    system.persist_native()
    state = LearningRuntime(engine).writer.read("t")
    assert state["episodes"][trajectory.id]["user_text"] == "corrected task"
    assert state["episodes"][trajectory.id]["reward"] is None
    assert state["artifacts"][lesson.id]["content"] == lesson.content
    assert state["artifacts"][procedure.id]["content"] == procedure.body
    assert "legacy_learning" not in state["policy"]


def test_native_models_roundtrip_rich_records_and_unchanged_save_is_noop():
    runtime, key = observed_candidate(LocalMemoryEngine())
    state = runtime.writer.read("t")
    artifact = state["artifacts"][key]
    assert Procedure.from_record(artifact).to_record() == artifact
    episode = next(iter(state["episodes"].values()))
    assert Trajectory.from_record(episode).to_record() == episode
    system = LearningSystem(runtime.engine)
    system.load_native(["t"])
    system.persist_native()
    assert runtime.writer.read("t") == state
    system.procedures[key].name = "Human readable label"
    system.persist_native()
    updated = runtime.writer.read("t")["artifacts"][key]
    assert updated["gate_evidence"] == artifact["gate_evidence"]
    assert updated["source_quotes"] == artifact["source_quotes"]
    assert updated["name"] == "Human readable label"


def test_concurrent_distinct_compatibility_edits_merge_and_conflicts_fail():
    engine = LocalMemoryEngine()
    first = LearningSystem(engine)
    item = Procedure("t", "checklist", "old", "observed text", {})
    first.procedures[item.id] = item
    first.persist_native()
    second = LearningSystem(engine)
    second.load_native(["t"])
    first.procedures[item.id].name = "first writer"
    first.persist_native()
    second.procedures[item.id].n_trials = 3
    second.persist_native()
    assert second.procedures[item.id].name == "first writer"
    first.procedures[item.id].name = "third writer"
    second.procedures[item.id].name = "conflicting writer"
    first.persist_native()
    with pytest.raises(ValueError, match="concurrent learning edit"):
        second.persist_native()
    assert not LearningRuntime(engine).status("t")["frozen"]


def test_stale_compatibility_save_does_not_revive_native_retirement():
    runtime, key = observed_candidate(LocalMemoryEngine())
    system = LearningSystem(runtime.engine)
    system.load_native(["t"])
    procedure = system.procedures[key]
    runtime.retire_artifact("t", key)
    procedure.name = "updated label"
    system.persist_native()
    assert procedure.status == "retired"
    assert runtime.writer.read("t")["artifacts"][key]["state"] == "retired"
    assert not system.validate_procedure(procedure, []).promoted


@pytest.mark.parametrize("state", ["probation", "active", "labile", "demoted"])
def test_admission_retries_preserve_current_native_status_and_locks(state):
    runtime, key = observed_candidate(LocalMemoryEngine())
    # A pre-existing native revision (activation itself is tested by the learner).
    native = runtime.engine._learning_data["t"]["artifacts"][key]
    native.update(state=state, locked=True)
    system = LearningSystem(runtime.engine)
    system.load_native(["t"])
    before = deepcopy(runtime.writer.read("t"))
    assert system.validate_procedure(system.procedures[key], []).promoted
    assert runtime.writer.read("t") == before
    system.procedures[key].body = "unrevisioned change"
    result = system.validate_procedure(system.procedures[key], [])
    assert not result.promoted
    assert "content_change_requires_new_revision" in result.failed_cases
    assert runtime.writer.read("t") == before


def test_existing_archive_and_trajectory_copies_migrate_to_one_record(tmp_path):
    engine = LocalMemoryEngine(store_path=tmp_path / "memory.json")
    trajectory = old_trajectory(id="original")
    procedure = Procedure("t", "checklist", "old", "unverified sequence", {}, id="old-procedure")
    payload = {"trajectories": [trajectory.to_dict()], "procedures": [procedure.to_dict()],
               "attributions": [{"trajectory_id": trajectory.id, "signature": "sig", "cause": "old cause", "evidence": [], "confidence": 0.0}]}
    state = empty_state()
    state["policy"]["legacy_learning"] = json.dumps(payload)
    wrapper_id = "legacy-" + digest(["t", trajectory.id])
    state["episodes"][wrapper_id] = {"id": wrapper_id, "tenant_id": "t", "status": "legacy",
        "prediction": None, "reward": None, "signals": [], "legacy_trajectory": trajectory.to_dict()}
    engine._learning_data = {"t": state}
    runtime = LearningRuntime(engine)
    migrated = runtime.writer.read("t")
    assert set(migrated["episodes"]) == {"original"}
    assert "legacy_learning" not in migrated["policy"]
    assert "legacy_trajectory" not in str(migrated)
    assert migrated["episodes"]["original"]["reported_reward"] == 1
    assert migrated["episodes"]["original"]["reward"] is None
    assert migrated["episodes"]["original"]["failure_attribution"]["cause"] == "old cause"
    assert migrated["artifacts"][procedure.id]["state"] == "candidate"
    again = runtime.writer.read("t")
    assert again == migrated
    side = RuntimeState(tmp_path / "runtime.json")
    side.data["learning"] = payload
    system = side.load_learning(LearningSystem(engine))
    assert set(system.trajectories) == {"original"}
    assert side.data["learning"] == {"engine_tenants": ["t"]}


def test_source_erasure_removes_canonical_and_audit_copies_and_stale_views():
    engine = LocalMemoryEngine()
    cid = engine.append_evidence(Evidence(tenant_id="t", user_id="u", actor="user",
        source_type="note", content="sensitive source"))
    system = LearningSystem(engine)
    trajectory = old_trajectory(evidence_cid=cid)
    system.log_trajectory(trajectory)
    lesson = system.induce_lesson(system.attribute_failure(trajectory.id))
    procedure = system.induce_procedure(lesson)
    system.rollback_procedure(procedure.id)
    engine.forget("t", cid)
    trajectory.task = "stale sensitive edit"
    system.persist_native()
    state = LearningRuntime(engine).writer.read("t")
    assert state["episodes"][trajectory.id]["status"] == "erased"
    assert not state["episodes"][trajectory.id].get("reported_outcome")
    assert not state["episodes"][trajectory.id].get("failure_attribution")
    assert state["artifacts"][procedure.id]["state"] == "retired"
    assert state["artifacts"][procedure.id]["erased"]
    assert not system.trajectories
    assert not system.lessons
    assert not system.procedures
    assert "sensitive source" not in json.dumps(state)


def test_legacy_origin_never_bypasses_serving_guard():
    runtime = LearningRuntime(LocalMemoryEngine())
    row = Procedure("t", "checklist", "old", "unverified", {}).to_record()
    row["state"] = "probation"
    with pytest.raises(LearningGuardError, match="unverified historical artifacts"):
        runtime.writer.apply("t", "forgery", lambda state: state["artifacts"].update({row["id"]: row}))


def test_compatibility_procedure_view_excludes_other_artifact_families():
    runtime, key = observed_candidate(LocalMemoryEngine())
    for kind in ("schema", "chunk", "rule", "skill"):
        row = deepcopy(runtime.engine._learning_data["t"]["artifacts"][key])
        row.update(id=kind, kind=kind)
        runtime.engine._learning_data["t"]["artifacts"][kind] = row
    system = LearningSystem(runtime.engine)
    system.load_native(["t"])
    assert set(system.procedures) == {key}


def test_native_failure_attribution_is_metadata_only_and_keeps_outcome_immutable():
    runtime, _ = observed_candidate(LocalMemoryEngine())
    system = LearningSystem(runtime.engine)
    system.load_native(["t"])
    key = next(iter(system.trajectories))
    before = runtime.episode("t", key)
    attribution = system.attribute_failure(key)
    after = runtime.episode("t", key)
    assert after.pop("failure_attribution") == attribution.to_dict()
    assert after == before
    system.trajectories[key].reward = 1
    with pytest.raises(LearningGuardError, match="finalized episode"):
        system.persist_native()


def test_erased_hash_alias_blocks_stale_lesson_even_without_source_cids():
    engine = LocalMemoryEngine()
    runtime = LearningRuntime(engine)
    trajectory = old_trajectory(id="original")
    state = empty_state()
    alias = "legacy-" + digest(["t", "original"])
    state["episodes"][alias] = {
        "id": alias, "tenant_id": "t", "user_id": "u", "session_id": "s", "task_class": "legacy",
        "status": "erased", "signals": [], "source_cids": [], "tool_events": [], "user_text": "",
        "reward": None, "rpe": None, "prediction": None, "receipt_ids": [], "created_at": trajectory.created_at.isoformat()}
    engine._learning_data = {"t": state}
    lesson = Lesson("t", "corrective", "old", "private stale lesson", source_episode_ids=["original"])
    system = LearningSystem(engine)
    system.import_legacy({"trajectories": [trajectory.to_dict()], "lessons": [lesson.to_dict()]})
    current = runtime.writer.read("t")
    assert current["episodes"]["original"]["status"] == "erased"
    assert current["artifacts"] == {}
    assert "private stale lesson" not in json.dumps(current)


def test_ephemeral_side_state_uses_one_native_checkpoint_with_evidence_and_audit(tmp_path):
    runtime, key = observed_candidate(LocalMemoryEngine())
    system = LearningSystem(runtime.engine)
    system.load_native(["t"])
    side = RuntimeState(tmp_path / "runtime.json")
    side.save_learning(system)
    before = runtime.writer.read("t")
    assert set(side.data["learning"]) == {"engine_tenants", "engine_path"}
    assert "source_quotes" not in side.path.read_text()
    loaded = RuntimeState(side.path).load_learning(LearningSystem(LocalMemoryEngine()))
    restored = LearningRuntime(loaded.engine)
    assert restored.writer.read("t") == before
    assert restored.writer.store.history("t") == runtime.writer.store.history("t")
    for cid in before["artifacts"][key]["source_cids"]:
        assert loaded.engine.get_evidence("t", cid).content == runtime.engine.get_evidence("t", cid).content
    loaded.procedures[key].name = "persisted label"
    side.save_learning(loaded)
    assert RuntimeState(side.path).load_learning(LearningSystem(LocalMemoryEngine())).procedures[key].name == "persisted label"


def test_side_state_rejects_arbitrary_checkpoint_pointer(tmp_path):
    side = RuntimeState(tmp_path / "runtime.json")
    side.data["learning"] = {"engine_tenants": ["t"], "engine_path": "../../elsewhere.json"}
    with pytest.raises(ValueError, match="adjacent"):
        side.load_learning(LearningSystem(LocalMemoryEngine()))


def test_native_checkpoint_refuses_overwrite_and_shares_existing_owner(tmp_path):
    path = tmp_path / "native.json"
    engine = LocalMemoryEngine()
    engine.attach_store(path)
    assert LocalMemoryEngine.shared_writer(path) is engine
    original = path.read_bytes()
    with pytest.raises(FileExistsError, match="overwrite"):
        LocalMemoryEngine().attach_store(path)
    assert path.read_bytes() == original
    engine.close()
    reopened = LocalMemoryEngine.shared_writer(path)
    assert reopened is not engine
    reopened.close()


def test_native_checkpoint_refuses_read_only_and_transactional_engines(tmp_path):
    with pytest.raises(RuntimeError, match="read-only"):
        LocalMemoryEngine(read_only=True).attach_store(tmp_path / "read-only.json")
    engine = LocalMemoryEngine()
    with engine.source_transaction("t"):
        with pytest.raises(RuntimeError, match="transaction"):
            engine.attach_store(tmp_path / "transaction.json")


def test_cross_engine_legacy_migration_writes_only_destination():
    from mnemosyne.runtime_state import migrate_legacy_learning
    source = LearningSystem(LocalMemoryEngine())
    item = old_trajectory()
    source.log_trajectory(item)
    target = LearningRuntime(LocalMemoryEngine())
    assert migrate_legacy_learning(target, source, "t") == {"archived": 1}
    assert target.writer.read("t")["episodes"][item.id]["reward"] is None
    assert migrate_legacy_learning(target, source, "t") == {"archived": 0}


def test_postgres_rebinding_rejects_nonempty_native_learning_without_loss():
    from mnemosyne.postgres_runtime_state import PostgresRuntimeState
    runtime, key = observed_candidate(LocalMemoryEngine())
    system = LearningSystem(runtime.engine)
    system.load_native(["t"])
    adapter = object.__new__(PostgresRuntimeState)
    adapter.dsn = "postgresql://unused"
    adapter.require_safe_role = True
    before = runtime.writer.read("t")
    with pytest.raises(ValueError, match="owning engine"):
        adapter._bind_learning(system)
    assert system.engine is runtime.engine
    assert runtime.writer.read("t") == before
    assert key in system.procedures


def test_parametric_export_rejects_reported_legacy_activation_and_filters_provider_inputs():
    from mnemosyne.parametric import ParametricTier

    class Trainer:
        adapter_kind = "test-adapter"
        received = None

        def propose(self, tenant, lessons, procedures, source_ids, rails):
            self.received = (lessons, procedures, source_ids)
            return {}

    engine = LocalMemoryEngine()
    system = LearningSystem(engine)
    historical = Lesson("t", "corrective", "reported-active", "unverified historical text", status="active")
    curated = Lesson("t", "corrective", "operator", "operator-authored transport", status="active", origin="curated")
    foreign = Lesson("other", "corrective", "private", "other tenant content", status="active", origin="curated")
    system.import_legacy({"lessons": [historical.to_dict(), curated.to_dict(), foreign.to_dict()]})
    assert system.lessons[historical.id].status == "active"  # Historical API view remains readable.
    trainer = Trainer()
    artifact = ParametricTier(trainer=trainer).propose_from_lessons("t", list(system.lessons.values()), [])
    assert artifact.source_ids == [curated.id]
    assert [item.id for item in trainer.received[0]] == [curated.id]
    assert trainer.received[1] == []
    assert trainer.received[2] == [curated.id]


def test_parametric_export_requires_admitted_native_snapshot_and_unchanged_content():
    from mnemosyne.parametric import ParametricTier

    runtime, key = observed_candidate(LocalMemoryEngine())
    system = LearningSystem(runtime.engine)
    system.load_native(["t"])
    procedure = system.procedures[key]
    procedure.status = "active"  # An unsaved caller claim cannot skip probation.
    tier = ParametricTier()
    assert tier.propose_from_lessons("t", [], [procedure]).source_ids == []
    native = runtime.engine._learning_data["t"]["artifacts"][key]
    native["state"] = "active"  # The activation algorithm has separate end-to-end coverage.
    system.load_native(["t"])
    assert tier.propose_from_lessons("t", [], [procedure]).source_ids == [key]
    procedure.body = "unadmitted replacement content"
    assert tier.propose_from_lessons("t", [], [procedure]).source_ids == []
