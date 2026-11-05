from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.frameworks import AutoMemorySession
from mnemosyne.skills import SkillStore


def imported(
    tmp_path, *, content="Read the release checklist.", meta="", name="release-guide"
):
    path = tmp_path / (name + ".md")
    path.write_text(f"---\nname: {name}\n{meta}\n---\n{content}")
    store = SkillStore(str(tmp_path / "skills.sqlite"))
    result = store.import_skill(
        str(path), "", memory={"tenant": "t", "user": "u", "cids": ["cid"]}
    )
    return store, result


def test_import_enters_probation_and_popularity_is_not_a_prior(tmp_path):
    store, result = imported(tmp_path, meta="popularity: 999999\nsuccesses: 99999")
    status = store.status(result["skill_id"])
    assert status["state"] == "probation"
    assert status["posterior"]["outcomes"] == 0
    assert status["posterior"]["mean"] == 0.5
    assert status["posterior"]["lower_bound"] == 0


def test_outcomes_are_idempotent_and_can_promote_after_local_evidence(tmp_path):
    store, result = imported(tmp_path)
    skill_id = result["skill_id"]
    for n in range(12):
        store.outcome(skill_id, 1, True, "verified", episode_id=str(n))
    duplicate = store.outcome(skill_id, 1, True, "verified", episode_id="0")
    assert duplicate["duplicate"]
    assert store.status(skill_id)["posterior"]["outcomes"] == 12
    assert store.status(skill_id)["state"] == "active"
    store.outcome(skill_id, 1, False, "one unlucky result", episode_id="bad")
    assert store.status(skill_id)["state"] == "active"
    with pytest.raises(ValueError, match="immutable"):
        store.outcome(skill_id, 1, False, "different", episode_id="0")


def test_concurrent_duplicate_outcomes_credit_once(tmp_path):
    store, result = imported(tmp_path)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(
            pool.map(
                lambda _: store.outcome(
                    result["skill_id"], 1, 1.0, "verified", episode_id="once"
                ),
                range(6),
            )
        )
    assert store.status(result["skill_id"])["posterior"]["outcomes"] == 1


def test_effectful_import_needs_approval_and_scoped_context(tmp_path):
    store, result = imported(tmp_path, content="Delete the deployment files.")
    skill_id = result["skill_id"]
    for n in range(12):
        store.outcome(skill_id, 1, True, "verified", episode_id=str(n))
    assert store.status(skill_id)["state"] == "probation"
    assert store.status(skill_id)["needs_approval"]
    assert not store.learning_context("release-guide", tenant_id="t", user_id="u")
    store.approve_effects(skill_id, 1)
    store.set_state(skill_id, "active")
    context = store.learning_context("release-guide", tenant_id="t", user_id="u")
    assert context[0]["kind"] == "imported_skill"
    assert context[0]["source_cids"] == ["cid"]
    assert not store.learning_context("release-guide", tenant_id="foreign", user_id="u")
    store.set_state(skill_id, "retired")
    assert not store.learning_context("release-guide", tenant_id="t", user_id="u")
    with pytest.raises(ValueError, match="retired"):
        store.set_state(skill_id, "active")


def test_exact_name_matches_keep_priority_after_failure(tmp_path):
    store, result = imported(tmp_path)
    for n in range(12):
        store.outcome(result["skill_id"], 1, False, "failed", episode_id=str(n))
    hit = store.search("release-guide")["skills"][0]
    assert hit["score"] == 1
    assert hit["posterior"]["mean"] < 0.5


def test_scalar_rewards_are_bounded(tmp_path):
    store, result = imported(tmp_path)
    with pytest.raises(ValueError):
        store.outcome(result["skill_id"], 1, float("nan"), "failed")
    with pytest.raises(ValueError):
        store.outcome(result["skill_id"], 1, 1, "")
    store.outcome(result["skill_id"], 1, 0.0, "neutral", episode_id="neutral")
    assert store.status(result["skill_id"])["posterior"]["mean"] == 0.5


def test_sdk_stream_capture_waits_for_exhaustion():
    session = AutoMemorySession(LocalMemoryEngine(), "t", "u", auto_consolidate=False)
    response = session.wrap(lambda _: iter(["hel", "lo"]))("query")
    assert not session.learning_runtime.writer.read("t")["episodes"]
    assert list(response) == ["hel", "lo"]
    state = session.learning_runtime.writer.read("t")
    assert len(state["episodes"]) == 1
    assistant = [e for e in session.engine.evidence.values() if e.actor == "assistant"]
    assert any(e.content == "hello" for e in assistant)


def test_sdk_cancelled_stream_does_not_invent_completion():
    session = AutoMemorySession(LocalMemoryEngine(), "t", "u", auto_consolidate=False)
    response = session.wrap(lambda _: iter(["first", "last"]))("query")
    assert next(response) == "first"
    response.close()
    assert not session.learning_runtime.writer.read("t")["episodes"]


def test_sdk_async_stream_preserves_chunks_and_real_events():
    session = AutoMemorySession(LocalMemoryEngine(), "t", "u", auto_consolidate=False)

    async def chunks():
        yield {"choices": [{"delta": {"content": "done"}}]}
        yield {"tool_events": [{"name": "checker", "verdict": True}]}

    response = session.wrap(lambda _: chunks())("query")

    async def consume():
        return [chunk async for chunk in response]

    assert len(asyncio.run(consume())) == 2
    episode = next(iter(session.learning_runtime.writer.read("t")["episodes"].values()))
    assert episode["status"] == "resolved"
    assert episode["signals"][0]["value"] == 1


def test_stream_contextvars_apply_during_iteration_without_leaking():
    from mnemosyne.frameworks import MODEL

    session = AutoMemorySession(
        LocalMemoryEngine(), "t", "u", model="stream-model", auto_consolidate=False
    )

    def chunks():
        yield MODEL.get()
        yield MODEL.get()

    before = MODEL.get()
    response = session.wrap(lambda _: chunks())("query")
    assert next(response) == "stream-model"
    assert MODEL.get() == before
    assert list(response) == ["stream-model"]
    assert MODEL.get() == before


def test_skill_candidates_enter_real_runtime_before_receipt(tmp_path):
    from mnemosyne.mcp_tools import MemoryTools
    from mnemosyne.models import Evidence

    engine = LocalMemoryEngine(store_path=tmp_path / "memory.json")
    cid = engine.append_evidence(
        Evidence(
            tenant_id="t",
            user_id="u",
            actor="user",
            source_type="import",
            content="Read the release checklist.",
            access_policy={"tenant": "t"},
        )
    )
    store, result = imported(tmp_path)
    with store._sql() as conn:
        import json

        conn.execute(
            "UPDATE skill_revisions SET memory = ?",
            (json.dumps({"tenant": "t", "user": "u", "cids": [cid]}),),
        )
    tools = MemoryTools(engine, skill_store=store)
    tools._remember_skills(store)
    context = tools.prepare_context("t", "u", "s", "release-guide")
    runtime = tools._learning_runtime()
    state = runtime.writer.read("t")
    assert any(
        a.get("source_origin", {}).get("kind") == "import"
        or a.get("origin") == "imported"
        for a in state["artifacts"].values()
    )
    assert context["receipt_id"] in state["receipts"]
