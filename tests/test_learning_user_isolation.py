from datetime import UTC, datetime

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience import sleep
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.policy import OperatingPolicy


def capture(runtime, user, steps, *, correction=None):
    session = f"{user}-{len(runtime.writer.read('t')['episodes'])}"
    context = runtime.prepare_context(
        "t", user, session, "Check inventory", task_type="inventory"
    )
    observed = runtime.observe_turn(
        "t", user, session, "Check inventory", "checked",
        receipt_ids=[context["receipt_id"]],
        tool_events=[] if correction else [
            {"name": step, "output": step, "success": True} for step in steps
        ],
    )
    runtime.record_signal(
        "t", episode_id=observed["episode_id"],
        kind="correction" if correction else "verifier",
        value=-1 if correction else 1, evidence=correction or "", final=True,
    )
    return observed["episode_id"]


@pytest.mark.parametrize("bob_steps", [["check"], ["inspect"]])
def test_same_class_users_learn_separate_servable_procedures(bob_steps):
    runtime = LearningRuntime(LocalMemoryEngine(
        policy=OperatingPolicy(learning_exploration_rate=1)
    ))
    owned = {}
    for user, steps in [("alice", ["check"]), ("bob", bob_steps)]:
        owned[user] = {capture(runtime, user, steps) for _ in range(2)}
    assert runtime.consolidate("t")["candidates"] == 2
    state = runtime.writer.read("t")
    artifacts = {row["user_id"]: row for row in state["artifacts"].values()}
    assert len({row["id"] for row in artifacts.values()}) == 2
    for user, item in artifacts.items():
        assert item["state"] == "probation"
        assert item["gate_passed"]
        assert set(item["source_episode_ids"]) == owned[user]
        assert {state["episodes"][key]["user_id"]
                for key in item["gate_evidence"]["replay_episode_ids"]} == {user}
        context = runtime.prepare_context(
            "t", user, f"serve-{user}", "Check inventory", task_type="inventory"
        )
        assert [row["id"] for row in context["procedures"]] == [item["id"]]
    assert runtime.consolidate("t")["candidates"] == 0
    assert runtime.writer.read("t")["artifacts"] == state["artifacts"]


def test_identical_corrections_have_distinct_user_owned_ids():
    runtime = LearningRuntime(LocalMemoryEngine())
    for user in ("alice", "bob"):
        capture(runtime, user, [], correction="Use inventory totals instead")
    assert runtime.consolidate("t")["candidates"] == 2
    artifacts = list(runtime.writer.read("t")["artifacts"].values())
    assert {row["user_id"] for row in artifacts} == {"alice", "bob"}
    assert len({row["id"] for row in artifacts}) == 2
    assert all(row["state"] == "candidate" for row in artifacts)
    assert all(row["pending_reason"] == "external_verification_pending_or_failed"
               for row in artifacts)
    for item in artifacts:
        assert {runtime.engine.get_evidence("t", cid).user_id
                for cid in item["source_cids"]} == {item["user_id"]}
    assert runtime.consolidate("t")["candidates"] == 0


@pytest.mark.parametrize("retire", [False, True])
def test_unscoped_existing_identity_is_reused_without_reviving_it(monkeypatch, retire):
    runtime = LearningRuntime(LocalMemoryEngine())
    for _ in range(2):
        capture(runtime, "alice", ["check"])
    digest = sleep.digest

    def old_digest(value):
        if isinstance(value, list) and len(value) == 6 and value[0] == "procedure":
            value = [value[0], *value[3:]]
        return digest(value)

    with monkeypatch.context() as patch:
        patch.setattr(sleep, "digest", old_digest)
        runtime.consolidate("t")
    original = next(iter(runtime.writer.read("t")["artifacts"].values()))
    assert original["id"] == digest(["procedure", "inventory", "check", None])
    if retire:
        runtime.retire_artifact("t", original["id"])
    capture(runtime, "alice", ["check"])
    for _ in range(2):
        capture(runtime, "bob", ["check"])
    runtime.consolidate("t")
    artifacts = runtime.writer.read("t")["artifacts"]
    assert len(artifacts) == 2
    assert artifacts[original["id"]]["state"] == ("retired" if retire else "probation")
    bob = next(row for row in artifacts.values() if row["user_id"] == "bob")
    assert bob["id"] != original["id"]
    assert bob["state"] == "probation"


def episode(user, key, *, condition=""):
    return {
        "id": key, "tenant_id": "t", "user_id": user, "task_class": "inventory",
        "created_at": datetime.now(UTC).isoformat(), "status": "resolved",
        "source_cids": [key], "user_text": f"Check inventory {condition}",
        "signals": [{"kind": "correction", "evidence": "check\nreport"}],
        "reward": 1, "rpe": 1,
    }


def test_chunk_support_and_abstraction_holdouts_do_not_cross_users():
    parents = []
    sources = {}
    for user in ("alice", "bob"):
        for index in range(5):
            row = episode(user, f"{user}-{index}")
            sources[row["id"]] = row
            item = sleep._candidate("inventory", ["check", "report"], [row])
            item.update(id=row["id"], state="active", task_class=str(index % 2))
            parents.append(item)
    chunks = sleep.mine_chunks(parents)
    assert len(chunks) == 2
    by_id = {row["id"]: row for row in parents}
    assert all(len({by_id[key]["user_id"] for key in chunk["parents"]}) == 1
               for chunk in chunks)
    assert sleep.mine_chunks(parents[:3] + parents[5:7]) == []

    lessons = {}
    for user in ("alice", "bob"):
        for index, condition in enumerate(("prod", "stage")):
            row = sources[f"{user}-{index}"]
            item = sleep._candidate("inventory", ["check", "report"], [row], kind="lesson")
            item.update(id=row["id"], state="active", conditions=[condition], scope_match=None)
            lessons[row["id"]] = item
    # Only Bob has an independent holdout. It cannot validate Alice's abstraction.
    sources = {key: row for key, row in sources.items() if key in lessons}
    sources["bob-holdout"] = episode("bob", "bob-holdout", condition="prod")
    proposals = sleep._abstract_rules({"artifacts": lessons, "episodes": sources})
    assert len(proposals) == 2
    by_user = {row["user_id"]: row for row in proposals}
    assert by_user["alice"]["abstraction_pending"]
    assert not by_user["bob"].get("abstraction_pending")
    assert all({sources[key]["user_id"] for key in row["source_episode_ids"]} == {user}
               for user, row in by_user.items())


def test_candidate_constructor_rejects_mixed_owners():
    with pytest.raises(ValueError, match="one tenant and user"):
        sleep._candidate("inventory", ["check"], [episode("alice", "a"), episode("bob", "b")])


def test_pattern_splits_keep_owners_and_ids_separate():
    state = {"episodes": {}, "artifacts": {}, "receipts": {}, "policy": {}}
    for user in ("alice", "bob"):
        parent = sleep._candidate("inventory", ["wrong"], [episode(user, user)])
        state["artifacts"][parent["id"]] = parent
        for condition, outcome, steps in [
            ("prod", 1, ["check", "report"]),
            ("stage", -1, ["report", "check"]),
        ]:
            for index in range(4):
                key = f"{user}-{condition}-{index}"
                row = episode(user, key)
                row.update(
                    user_text="one two three four five six seven eight nine ten " + condition,
                    reward=outcome, receipt_ids=[key],
                    tool_events=[{"expected_steps": steps, "context_features": {"env": condition}}],
                )
                state["episodes"][key] = row
                state["receipts"][key] = {"items": [{"item_id": parent["id"]}]}
    splits = sleep._scoped_splits(state, "t")
    assert len(splits) == 2
    assert len({row["id"] for row in splits}) == 2
    for split in splits:
        ids = [key for _, keys, _ in split["groups"] for key in keys]
        assert {state["episodes"][key]["user_id"] for key in ids} == {split["user_id"]}
    state["policy"]["pattern_splits"] = {row["id"]: row for row in splits}
    assert sleep._scoped_splits(state, "t") == splits
