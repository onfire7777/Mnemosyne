"""Readable source evidence must not broaden a learned artifact's owner scope."""

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience import candidates
from mnemosyne.experience.candidates import register_import
from mnemosyne.experience.receipts import digest
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.mcp_tools import MemoryTools
from mnemosyne.models import Evidence


@pytest.mark.parametrize("source_access", [
    {"tenant": "t"},
    {"tenant": "t", "allow_principals": ["alice", "bob"]},
], ids=["tenant-readable", "shared-with-both-users"])
def test_readable_source_does_not_share_owned_skill(source_access):
    engine = LocalMemoryEngine()
    engine.policy.learning_exploration_rate = 1.0
    runtime = LearningRuntime(engine)
    content = "Check the deployment logs"
    cid = engine.append_evidence(Evidence(
        tenant_id="t", user_id="alice", actor="user", source_type="skill",
        content=content, access_policy=source_access,
    ))
    artifact = register_import(runtime, "t", {
        "id": "deployment-skill", "revision": 1, "task_class": "deploy",
        "content": content, "steps": [content], "source_cids": [cid],
        "source_origin": {"tenant_id": "t", "user_id": "alice", "source_sha": "sha"},
    })
    assert artifact["state"] == "probation"
    assert runtime._sources_live("t", [cid], "bob")

    owner = runtime.prepare_context("t", "alice", "owner-session", "deploy", task_type="deploy")
    assert [item["id"] for item in owner["skills"]] == [artifact["id"]]
    other = runtime.prepare_context("t", "bob", "other-session", "deploy", task_type="deploy")
    assert other["skills"] == []
    receipt = runtime.writer.read("t")["receipts"][other["receipt_id"]]
    assert all(item["item_id"] != artifact["id"] for item in receipt["items"])
    assert all(item["item_id"] != artifact["id"] for item in receipt["eligible_targets"])
    assert receipt["source_cids"] == []


def test_same_import_revision_has_independent_user_owners():
    runtime = LearningRuntime(LocalMemoryEngine())
    content = "Check the deployment logs"
    cid = runtime.engine.append_evidence(Evidence(
        tenant_id="t", user_id="alice", actor="user", source_type="skill",
        content=content, access_policy={"tenant": "t"},
    ))
    source = {"id": "deployment-skill", "revision": 1, "task_class": "deploy",
              "content": content, "steps": [content], "source_cids": [cid]}
    artifacts = [register_import(runtime, "t", {
        **source, "source_origin": {"tenant_id": "t", "user_id": user, "source_sha": "sha"},
    }) for user in ("alice", "bob")]
    assert [item["user_id"] for item in artifacts] == ["alice", "bob"]
    assert len({item["id"] for item in artifacts}) == 2
    assert all(item["state"] == "probation" for item in artifacts)


def test_existing_import_identity_is_reused_only_for_its_owner(monkeypatch):
    runtime = LearningRuntime(LocalMemoryEngine())
    content = "Check the deployment logs"
    cid = runtime.engine.append_evidence(Evidence(
        tenant_id="t", user_id="alice", actor="user", source_type="skill",
        content=content, access_policy={"tenant": "t"},
    ))
    source = {"id": "deployment-skill", "revision": 1, "task_class": "deploy",
              "content": content, "steps": [content], "source_cids": [cid],
              "source_origin": {"tenant_id": "t", "user_id": "alice", "source_sha": "sha"}}
    legacy_id = digest(["import", source["id"], 1, "deploy"])
    with monkeypatch.context() as patch:
        patch.setattr(candidates, "digest", lambda value: legacy_id if isinstance(value, list) and value[0] == "import" else digest(value))
        original = register_import(runtime, "t", source)
    assert original["id"] == legacy_id
    assert register_import(runtime, "t", source)["id"] == legacy_id
    other = register_import(runtime, "t", {
        **source, "source_origin": {**source["source_origin"], "user_id": "bob"},
    })
    assert other["id"] != legacy_id
    assert other["user_id"] == "bob"
    assert len(runtime.writer.read("t")["artifacts"]) == 2


def test_created_learning_sources_keep_user_session_and_actor_custody():
    runtime = LearningRuntime(LocalMemoryEngine())
    sources = []
    for user, session in (("alice", "s"), ("bob", "s"), ("alice", "other")):
        result = runtime.observe_turn("t", user, session, "same text", "same text",
                                      tool_events=[{"name": "inspect", "output": "same text"}])
        runtime.record_signal("t", episode_id=result["episode_id"], kind="correction",
                              value=-1, evidence="same correction")
        episode = runtime.writer.read("t")["episodes"][result["episode_id"]]
        rows = [runtime.engine.get_evidence("t", cid) for cid in episode["source_cids"]]
        assert len(rows) == 4
        assert {row.user_id for row in rows} == {user}
        assert {row.session_id for row in rows} == {session}
        assert {row.actor for row in rows if row.source_type == "learning_turn"} == {"user", "assistant"}
        assert runtime._sources_live("t", episode["source_cids"], user)
        sources.extend(episode["source_cids"])
    assert len(set(sources)) == 12


def test_scoped_text_source_hard_delete_does_not_shred_a_blob(monkeypatch):
    tools = MemoryTools(LocalMemoryEngine())
    runtime = tools._learning_runtime()
    result = runtime.observe_turn("t", "alice", "s", "text to erase", "")
    episode = runtime.writer.read("t")["episodes"][result["episode_id"]]
    cid = episode["source_cids"][0]
    source = tools.engine.get_evidence("t", cid)
    assert source.document_segment_id.startswith("learning:")
    assert source.content_pointer is None

    def unexpected_shred(*args, **kwargs):
        pytest.fail("inline learning text has no object to shred")

    monkeypatch.setattr(tools.ingestion.object_store, "shred", unexpected_shred)
    assert tools.forget("t", cid, erasure_mode="hard_delete_legal")["erased"]
    assert tools.engine.get_evidence("t", cid) is None
    assert runtime.writer.read("t")["episodes"][result["episode_id"]]["status"] == "erased"
