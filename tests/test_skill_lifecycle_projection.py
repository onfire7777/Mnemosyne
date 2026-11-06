"""Native skill lifecycle is authoritative; the library is a scoped projection."""

from copy import deepcopy

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.candidates import candidate_score, observed_steps
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.models import Evidence
from mnemosyne.skills import SkillStore


def managed_skill(tmp_path):
    engine = LocalMemoryEngine()
    content = "Read the release checklist."
    cid = engine.append_evidence(Evidence(
        tenant_id="t", user_id="u", actor="user", source_type="skill_import",
        content=content, access_policy={"tenant": "t", "allow_principals": ["u"]},
    ))
    path = tmp_path / "SKILL.md"
    path.write_text("---\nname: release-guide\n---\n" + content)
    store = SkillStore(str(tmp_path / "skills.sqlite"))
    imported = store.import_skill(str(path), "", memory={"tenant": "t", "user": "u", "source_cids": [cid]})
    engine._learning_skill_store = store
    runtime = LearningRuntime(engine, skill_store=store)
    runtime.prepare_context("t", "u", "import", "release-guide", task_type="release")
    artifact = next(iter(runtime.writer.read("t")["artifacts"].values()))
    assert store.status(imported["skill_id"])["lifecycle_owner"] == "experience"
    return runtime, store, imported["skill_id"], artifact, cid


def observe(runtime, session, *, success, served=True):
    runtime.engine.policy.learning_exploration_rate = 1.0
    runtime.mode("t", "exploration", "active" if served else "off")
    context = runtime.prepare_context("t", "u", session, "release-guide", task_type="release")
    assert bool(context["skills"]) is served
    result = runtime.observe_turn(
        "t", "u", session, "release-guide", "checked",
        receipt_ids=[context["receipt_id"]],
        used_skills=[item["id"] for item in context["skills"]],
        tool_events=[{"name": "benchmark_verifier", "success": success,
                      "output": "passed" if success else "failed"}],
    )
    runtime.record_signal("t", episode_id=result["episode_id"], kind="verifier",
                          value=1 if success else -1, final=True)
    return result["episode_id"]


def test_twelve_positive_outcomes_cannot_bypass_native_control_requirement(tmp_path):
    runtime, store, skill_id, artifact, _ = managed_skill(tmp_path)
    initial = store.outcome(skill_id, 1, True, "before any native outcome")
    assert initial["recorded"] is False and initial["runs"] == 0
    for index in range(12):
        observe(runtime, f"served-{index}", success=True)
    runtime.consolidate("t")
    state = runtime.writer.read("t")
    assert state["artifacts"][artifact["id"]]["state"] == "probation"
    assert not [row for row in state["credit"].values() if row["target_id"] == artifact["id"]]
    assert store.status(skill_id)["state"] == "probation"
    assert store.status(skill_id)["posterior"]["outcomes"] == 12
    runtime._flush_skill_outbox("t")
    runtime._sync_library_revision_states("t")
    assert store.status(skill_id)["posterior"]["outcomes"] == 12
    direct = store.outcome(skill_id, 1, True, "not a native receipt", episode_id="manual")
    assert direct["recorded"] is False
    assert store.status(skill_id)["posterior"]["outcomes"] == 12
    with pytest.raises(ValueError, match="native-managed"):
        store.set_state(skill_id, "active")
    for state in ("active", "labile"):
        with pytest.raises(ValueError, match="native probation"):
            runtime.set_import_state("t", skill_id, 1, state)
    assert not runtime.status("t")["frozen"]


def test_activation_demotion_rollback_and_source_erasure_share_one_owner(tmp_path):
    runtime, store, skill_id, artifact, cid = managed_skill(tmp_path)
    for index in range(8):
        observe(runtime, f"control-{index}", success=False, served=False)
    for index in range(12):
        observe(runtime, f"served-{index}", success=True)
    runtime.consolidate("t")
    assert runtime.writer.read("t")["artifacts"][artifact["id"]]["state"] == "active"
    assert store.status(skill_id)["state"] == "active"
    runtime.set_import_state("t", skill_id, 1, "demoted")
    event = next(row for row in reversed(runtime.writer.store.history("t")) if row["op"] == "learning.skill_state")
    assert store.status(skill_id)["state"] == "demoted"
    runtime.rollback("t", event["id"])
    assert store.status(skill_id)["state"] == "active"
    tested = next(row for row in runtime.writer.read("t")["episodes"].values()
                  if row["session_id"] == "served-0")
    runtime.engine.forget("t", tested["source_cids"][0])
    assert runtime.writer.read("t")["artifacts"][artifact["id"]]["state"] == "probation"
    assert store.status(skill_id)["state"] == "probation"
    assert store.status(skill_id)["posterior"]["outcomes"] < 12
    runtime.erase("t", cid)
    assert not runtime.writer.read("t")["artifacts"][artifact["id"]]["source_cids"]
    assert store.status(skill_id)["state"] == "retired"
    with pytest.raises(ValueError, match="erased"):
        store.get(skill_id)


def test_multi_scope_projection_is_conservative_and_counts_each_episode_once(tmp_path):
    runtime, store, skill_id, original, _ = managed_skill(tmp_path)
    first = {**original, "state": "active"}
    second = {**deepcopy(original), "id": "second-scope", "task_class": "other"}
    outcomes = [{"episode_id": "same", "probability": 1.0}] * 2
    result = store.sync_learning_revision(skill_id, 1, [first, second], outcomes=outcomes)
    assert result["state"] == "probation"
    assert result["posterior"]["outcomes"] == 1
    assert result["native_states"] == {first["id"]: "active", "second-scope": "probation"}
    second["state"] = "active"
    assert store.sync_learning_revision(skill_id, 1, [first, second], outcomes=outcomes)["state"] == "active"
    first["state"] = "archived"
    assert store.sync_learning_revision(skill_id, 1, [first, second])["state"] == "demoted"


def test_induction_and_scoring_use_identical_external_step_contract():
    runtime = LearningRuntime(LocalMemoryEngine())
    events = [
        {"name": "", "output": "empty"}, {"name": 7, "output": "7"},
        {"name": "   ", "output": "blank"},
        {"name": "invented", "source": "assistant", "output": "invented"},
        {"name": "self", "source": "self_generated", "output": "self"},
        {"name": "grade", "source": "provider_self_grade", "output": "grade"},
        {"name": "inspect", "source": "host", "output": "inspect"},
        {"name": "verify", "output": "verify"},
        {"name": "benchmark_verifier", "success": True, "output": "passed"},
    ]
    ids = []
    for index in range(2):
        observed = runtime.observe_turn("t", "u", f"s{index}", "release", "", tool_events=events)
        runtime.record_signal("t", episode_id=observed["episode_id"], kind="verifier", value=1, final=True)
        ids.append(observed["episode_id"])
    runtime.consolidate("t")
    state = runtime.writer.read("t")
    artifact = next(item for item in state["artifacts"].values() if item["kind"] == "procedure")
    assert artifact["steps"] == ["inspect", "verify"]
    for episode_id in ids:
        episode = state["episodes"][episode_id]
        assert observed_steps(episode) == artifact["steps"]
        assert candidate_score(artifact, episode) == 1.0


def test_retired_revision_rollback_creates_new_candidate_without_aliasing_library(tmp_path):
    runtime, store, skill_id, original, _ = managed_skill(tmp_path)
    runtime.set_import_state("t", skill_id, 1, "retired")
    event = next(row for row in reversed(runtime.writer.store.history("t")) if row["op"] == "learning.skill_state")
    result = runtime.rollback("t", event["id"])
    restored = runtime.writer.read("t")["artifacts"][result["restored_candidates"][0]]
    assert restored["state"] == "candidate"
    assert "source_skill_id" not in restored
    assert restored["source_library_skill_id"] == skill_id
    assert restored["source_library_parent_artifact"] == original["id"]
    assert store.status(skill_id)["state"] == "retired"


def test_shared_store_projection_does_not_change_other_tenant(tmp_path):
    runtime, store, skill_id, _, _ = managed_skill(tmp_path)
    before = store.status(skill_id)
    runtime._sync_library_revision_states("other-tenant")
    assert store.status(skill_id) == before


def test_reassigned_library_revision_projects_only_current_owner(tmp_path):
    runtime, store, skill_id, original, _ = managed_skill(tmp_path)
    old_episode = observe(runtime, "old-owner", success=True)
    previous = deepcopy(runtime.writer.read("t")["artifacts"][original["id"]])
    content = "Read the release checklist."
    cid = runtime.engine.append_evidence(Evidence(
        tenant_id="t", user_id="next-owner", actor="user", source_type="skill_import",
        content=content, document_segment_id="next-owner-import",
        access_policy={"tenant": "t", "allow_principals": ["next-owner"]},
    ))
    store.remembered(skill_id, 1, {"tenant": "t", "user": "next-owner", "source_cids": [cid]})
    context = runtime.prepare_context("t", "next-owner", "next-session", "release-guide", task_type="release")
    current = next(item for item in runtime.writer.read("t")["artifacts"].values()
                   if item.get("user_id") == "next-owner")
    assert current["id"] != original["id"]
    assert store.status(skill_id)["native_states"] == {current["id"]: "probation"}
    assert store.status(skill_id)["posterior"]["outcomes"] == 0

    observed = runtime.observe_turn("t", "next-owner", "next-session", "release-guide", "checked",
                                    receipt_ids=[context["receipt_id"]],
                                    tool_events=[{"name": "benchmark_verifier", "success": False}])
    runtime.record_signal("t", episode_id=observed["episode_id"], kind="verifier", value=-1, final=True)
    events = store._rows("SELECT episode_id FROM skill_outcome_events WHERE skill_id = ? AND revision = 1", (skill_id,))
    assert {row["episode_id"] for row in events} == {observed["episode_id"]}
    assert old_episode not in {row["episode_id"] for row in events}
    assert store.status(skill_id)["posterior"]["outcomes"] == 1
    runtime.writer.apply("t", "current_owner_state", lambda state: state["artifacts"][current["id"]].update(state="demoted"))
    runtime._sync_library_revision_states("t")
    assert store.status(skill_id)["state"] == "demoted"
    assert store.status(skill_id)["native_states"] == {current["id"]: "demoted"}
    assert runtime.writer.read("t")["artifacts"][original["id"]] == previous


def test_disabled_skill_component_does_not_collect_delayed_receipt_outcome(tmp_path):
    from mnemosyne.experience.runtime import stat_key

    runtime, store, skill_id, artifact, _ = managed_skill(tmp_path)
    runtime.engine.policy.learning_exploration_rate = 1.0
    context = runtime.prepare_context("t", "u", "late", "release-guide", task_type="release")
    assert context["skills"]
    runtime.mode("t", "skills", "off")
    captured = runtime.observe_turn("t", "u", "late", "release-guide", "checked",
                                    receipt_ids=[context["receipt_id"]],
                                    used_skills=[artifact["id"]])
    runtime.record_signal("t", episode_id=captured["episode_id"], kind="verifier", value=1, final=True)
    runtime.mode("t", "skills", "active")
    runtime._sync_library_revision_states("t")
    assert store.status(skill_id)["posterior"]["outcomes"] == 0
    key = stat_key("skill", artifact["id"], artifact["revision"], "release")
    assert key not in runtime.writer.read("t")["stats"]


def test_explicit_conversion_does_not_copy_native_revision_ownership(tmp_path, monkeypatch):
    _, store, skill_id, _, _ = managed_skill(tmp_path)
    monkeypatch.setattr(store._jobs, "put", lambda job: None)
    conversion = store.make_burnskill(skill_id, "test-model")
    assert conversion["revision"] == 2
    assert store.status(skill_id, 1)["lifecycle_owner"] == "experience"
    assert store.status(skill_id, 2)["lifecycle_owner"] == "skill_store"
    assert not store.status(skill_id, 2)["native_states"]
