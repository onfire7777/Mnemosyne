from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.receipts import digest
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.frameworks import AutoMemorySession
from mnemosyne.mcp_tools import MemoryTools


def test_sdk_exposes_every_receipted_hit_and_infers_chat_task(monkeypatch):
    session = AutoMemorySession(LocalMemoryEngine(), "t", "u", auto_consolidate=False)
    seen = []

    def prepare(*args, **kwargs):
        seen.append(kwargs.get("task_type"))
        return {
            "receipt_id": "r",
            "hits": [
                {"id": str(i), "text": f"hit-{i}-" + ("x" * 300)} for i in range(8)
            ],
            "procedures": [],
            "lessons": [],
            "skills": [],
        }

    monkeypatch.setattr(session.learning_runtime, "prepare_context", prepare)
    result = session.pre_turn_retrieve("Find deployments")
    assert seen == [None]
    assert all(f"hit-{i}-" + ("x" * 300) in result["context_text"] for i in range(8))


@pytest.mark.parametrize("mode", ["paused", "frozen", "off", "shadow"])
def test_skill_outbox_does_not_flush_when_learning_disabled(mode):
    calls = []
    runtime = LearningRuntime(
        LocalMemoryEngine(),
        skill_store=SimpleNamespace(outcome=lambda **kw: calls.append(kw)),
    )
    runtime.writer.apply(
        "t",
        "seed_outbox",
        lambda s: s["policy"].update(
            skill_outbox={
                "event": {
                    "skill_id": "s",
                    "revision": 1,
                    "success": 1,
                    "evidence": "e",
                    "episode_id": "e",
                }
            }
        ),
    )
    if mode == "paused":
        runtime.pause("t")
    elif mode == "frozen":
        runtime.writer.apply("t", "freeze", lambda s: s["policy"].update(frozen=True))
    else:
        runtime.mode("t", "skills", mode)
    runtime._flush_skill_outbox("t")
    assert calls == []
    assert runtime.writer.read("t")["policy"]["skill_outbox"]


def test_delayed_skill_outcome_after_pause_does_not_enqueue():
    runtime = LearningRuntime(LocalMemoryEngine())
    state = {
        "policy": {"enabled": False},
        "episodes": {
            "e": {
                "id": "e",
                "tenant_id": "t",
                "status": "open",
                "signals": [{"kind": "verifier", "weight": 1.0, "value": 1.0}],
                "created_at": "2026-11-05T00:00:00+00:00",
                "prediction": 0.5,
                "session_id": "s",
                "turn_index": 0,
                "receipt_ids": ["r"],
                "used_skills": ["a"],
                "task_class": "x",
            }
        },
        "receipts": {
            "r": {
                "prediction": 0.5,
                "prediction_hash": digest(0.5),
                "items": [{"item_id": "a"}],
            }
        },
        "artifacts": {
            "a": {
                "id": "a",
                "task_class": "x",
                "state": "probation",
                "source_skill_id": "s",
                "source_skill_revision": 1,
            }
        },
        "stats": {},
        "defects": {},
        "credit": {},
    }

    class Writer:
        def read(self, tenant):
            return copy.deepcopy(state)

        def apply(self, tenant, operation, mutate):
            return mutate(state)

    runtime.writer = Writer()
    runtime.resolve("t", "e")
    assert not state["policy"].get("skill_outbox")


def test_explicit_user_correction_updates_scoped_profile():
    tools = MemoryTools(LocalMemoryEngine())
    context = tools.prepare_context("t", "u", "s", "Describe deployment")
    tools.observe_turn(
        "t",
        "u",
        "s",
        "No, use bullet points instead.",
        "Understood.",
        receipt_ids=[context["receipt_id"]],
    )
    entries = list(tools.user_model.entries.values())
    assert any(
        e.statement == "No, use bullet points instead."
        and e.tenant_id == "t"
        and e.user_id == "u"
        for e in entries
    )
    assert not tools.profile_context("t", "other")["authoritative"]


def test_user_model_automatic_writes_respect_pause():
    tools = MemoryTools(LocalMemoryEngine())
    tools._learning_runtime().pause("t")
    tools.observe_turn("t", "u", "s", "I prefer bullet points.", "Okay.")
    assert not tools.user_model.entries


def test_correction_signal_has_real_source_in_same_episode():
    runtime = LearningRuntime(LocalMemoryEngine())
    context = runtime.prepare_context("t", "u", "s", "write report")
    observed = runtime.observe_turn(
        "t", "u", "s", "write report", "report", receipt_ids=[context["receipt_id"]]
    )
    episode = runtime.record_signal(
        "t",
        episode_id=observed["episode_id"],
        kind="correction",
        value=-1,
        evidence="No, use bullet points instead.",
        final=True,
    )
    sources = [runtime.engine.get_evidence("t", cid) for cid in episode["source_cids"]]
    assert any(
        source.actor == "user" and source.content == "No, use bullet points instead."
        for source in sources
    )


def test_only_self_reported_mistakes_update_support_profile():
    tools = MemoryTools(LocalMemoryEngine())
    tools.observe_turn("t", "u", "s", "You made a mistake in the date.", "Corrected.")
    assert not tools.user_model.mistake_events
    tools.observe_turn("t", "u", "s", "I forgot to check the date.", "Okay.")
    assert len(tools.user_model.mistake_events) == 1
    assert (
        tools.user_model.mistake_events[0].description == "I forgot to check the date."
    )


def test_automatic_profile_erasure_removes_source_text_and_mistakes():
    tools = MemoryTools(LocalMemoryEngine())
    seen = tools.observe_turn("t", "u", "s", "I prefer bullet points.", "Okay.")
    episode = tools._learning_runtime().episode("t", seen["episode_id"])
    cid = next(
        cid
        for cid in episode["source_cids"]
        if tools.engine.get_evidence("t", cid).actor == "user"
    )
    tools.engine._learning_profile_erasure("t", cid)
    assert all(
        entry.statement != "I prefer bullet points."
        for entry in tools.user_model.entries.values()
    )
    seen = tools.observe_turn("t", "u", "s", "I forgot the due date.", "Okay.")
    episode = tools._learning_runtime().episode("t", seen["episode_id"])
    cid = next(
        cid
        for cid in episode["source_cids"]
        if tools.engine.get_evidence("t", cid).actor == "user"
    )
    tools.engine._learning_profile_erasure("t", cid)
    assert not tools.user_model.mistake_events
