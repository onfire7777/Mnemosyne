"""User instructions retain exact provenance and need real outcomes for promotion."""

import json
import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.candidates import evaluate_candidate
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.experience.sleep import _candidate
from mnemosyne.gate import Candidate, PromotionGate, RegressionCase

QUERY = "Format the build summary"
CORRECTION = "Use a JSON object for build summaries."


def record_correction(runtime, correction=CORRECTION, query=QUERY):
    context = runtime.prepare_context("t", "u", "chat", query, task_type="build-summary")
    result = runtime.observe_turn("t", "u", "chat", query, "Build passed.",
                                  receipt_ids=[context["receipt_id"]])
    runtime.record_signal("t", episode_id=result["episode_id"], kind="correction",
                          value=-1, evidence=correction, final=True)
    return result["episode_id"]


def test_authoritative_user_quote_enters_probation_without_factual_confidence():
    runtime = LearningRuntime(LocalMemoryEngine())
    record_correction(runtime)
    quoted = runtime.engine.retrieve(
        CORRECTION, "t", record_access=False,
        filt={"principal": "u", "user_id": "u", "role": "reader"},
    )
    assert quoted.abstained
    assert CORRECTION in [hit.text for hit in quoted.hits]
    runtime.consolidate("t")
    lesson = next(a for a in runtime.writer.read("t")["artifacts"].values()
                  if a["kind"] == "lesson")
    assert lesson["state"] == "probation"
    assert lesson["gate_evidence"]["protected_passed"]
    assert lesson["source_quotes"][0]["quote"] == CORRECTION
    assert lesson["scope_match"] == {"kind": "exact_query", "query": QUERY}


def test_default_factual_gate_still_requires_nonabstaining_retrieval():
    runtime = LearningRuntime(LocalMemoryEngine())
    record_correction(runtime)
    case = RegressionCase("fact", "build-summary", CORRECTION, CORRECTION,
                          protected=True)
    proposal = Candidate("fact-candidate", "fact", "build-summary", CORRECTION,
                         "fact-check", [])
    result = PromotionGate(runtime.engine, [case], retrieval_context={
        "principal": "u", "user_id": "u", "role": "reader",
    }).evaluate("t", proposal, lambda engine, branch: None)
    assert not result.promoted
    assert result.failed_cases == ["fact"]


def test_runtime_case_with_same_id_retains_its_factual_contract():
    runtime = LearningRuntime(LocalMemoryEngine())
    record_correction(runtime)
    runtime.consolidate("t")
    case_id = next(iter(runtime.writer.read("t")["policy"]["protected_cases"]))
    runtime.protected_cases = [RegressionCase(
        case_id, "build-summary", CORRECTION, "required unsupported factual answer",
        protected=True,
    )]
    episode = runtime.episode("t", record_correction(runtime))
    proposed = _candidate("build-summary", [CORRECTION], [episode], kind="lesson")
    assert not evaluate_candidate(runtime, "t", proposed, [episode])
    assert case_id in proposed["gate_evidence"]["failed_cases"]


def test_imported_candidate_cannot_claim_user_quote_proof():
    runtime = LearningRuntime(LocalMemoryEngine())
    episode = runtime.episode("t", record_correction(runtime))
    proposed = _candidate("build-summary", [CORRECTION], [episode], kind="lesson")
    proposed.update(origin="imported", source_quote_proof=True,
                    source_origin={"tenant_id": "t", "user_id": "u", "source_sha": "import"})
    assert not evaluate_candidate(runtime, "t", proposed, [episode])


def test_previous_retained_user_quote_does_not_block_a_new_correction():
    runtime = LearningRuntime(LocalMemoryEngine())
    record_correction(runtime)
    runtime.consolidate("t")
    second = "Use bullet points for release notes."
    record_correction(runtime, second, "Format the release notes")
    runtime.consolidate("t")
    lessons = [a for a in runtime.writer.read("t")["artifacts"].values()
               if a["kind"] == "lesson"]
    assert {a["content"] for a in lessons if a["state"] == "probation"} == {CORRECTION, second}


def test_verified_lesson_reuse_promotes_only_after_real_trial_outcomes():
    runtime = LearningRuntime(LocalMemoryEngine())
    record_correction(runtime)
    runtime.consolidate("t")
    state = runtime.writer.read("t")
    lesson = next(a for a in state["artifacts"].values() if a["kind"] == "lesson")
    assert lesson["state"] == "probation"
    assert not state["stats"].get(lesson["id"])
    for _ in range(100):
        context = runtime.prepare_context("t", "u", "chat", QUERY, task_type="build-summary")
        used = [item["id"] for item in context["lessons"]]
        output = '{"passed": true}' if used else 'Build passed.'
        try:
            verified = isinstance(json.loads(output), dict)
        except json.JSONDecodeError:
            verified = False
        observed = runtime.observe_turn(
            "t", "u", "chat", QUERY, output, receipt_ids=[context["receipt_id"]],
            used_lessons=used, tool_events=[{
                "source": "tool", "verdict": verified,
                "output": "JSON object validation passed" if verified else "JSON object validation failed",
            }],
        )
        runtime.resolve("t", observed["episode_id"])
        runtime.consolidate("t")
        if runtime.writer.read("t")["artifacts"][lesson["id"]]["state"] == "active":
            break
    assert runtime.writer.read("t")["artifacts"][lesson["id"]]["state"] == "active"
    assert runtime.prepare_context("t", "u", "chat", QUERY,
                                   task_type="build-summary")["lessons"]
    assert not runtime.prepare_context("t", "u", "chat", "Format a different report",
                                       task_type="build-summary")["lessons"]
    runtime.engine.forget("t", lesson["source_quotes"][0]["cid"])
    assert not runtime.prepare_context("t", "u", "chat", QUERY,
                                       task_type="build-summary")["lessons"]


def completed_answer(tools, *, user="u", session="chat", query=QUERY):
    context = tools.prepare_context("t", user, session, query, task_type="build-summary")
    result = tools.observe_turn(
        "t", user, session, query, "The answer is four.",
        receipt_ids=[context["receipt_id"]],
        tool_events=[{"name": "calculator", "source": "tool", "verdict": 2 + 2 == 4,
                      "output": "4"}],
    )
    return result["episode_id"], context["receipt_id"]


@pytest.mark.parametrize("backend", ["local", "sqlite"])
def test_followup_correction_preserves_completed_outcome_and_creates_scoped_feedback(backend, tmp_path):
    from copy import deepcopy
    from mnemosyne.mcp_tools import MemoryTools
    from mnemosyne.sqlite_engine import SqliteEngine

    path = tmp_path / "memory"
    engine = LocalMemoryEngine() if backend == "local" else SqliteEngine(path)
    tools = MemoryTools(engine)
    previous, receipt = completed_answer(tools)
    runtime = tools._learning_runtime()
    original_episode = deepcopy(runtime.episode("t", previous))
    original_receipt = deepcopy(runtime.writer.read("t")["receipts"][receipt])
    correction = "No, use a JSON object for build summaries."
    context = tools.prepare_context("t", "u", "chat", correction, task_type="format-followup")
    current = tools.observe_turn("t", "u", "chat", correction, '{"answer": 4}',
                                 receipt_ids=[context["receipt_id"]])
    state = runtime.writer.read("t")
    feedbacks = [row for row in state["episodes"].values()
                 if row.get("feedback_for_episode_id") == previous]
    assert len(feedbacks) == 1
    feedback = feedbacks[0]
    assert runtime.episode("t", previous) == original_episode
    assert state["receipts"][receipt] == original_receipt
    assert feedback["status"] == "resolved" and feedback["reward"] == -1
    assert feedback["prediction"] == 0.5
    assert not feedback["receipt_ids"] and not feedback["tool_events"]
    assert feedback["user_text"] == QUERY
    assert feedback["task_class"] == original_episode["task_class"]
    assert feedback["signals"][0]["evidence"] == correction
    assert not any(row["episode_id"] == feedback["id"] for row in state["credit"].values())
    assert any((source := tools.engine.get_evidence("t", cid)) is not None
               and source.actor == "user" and source.content == correction
               for cid in feedback["source_cids"])
    lesson = next(a for a in state["artifacts"].values() if a["kind"] == "lesson")
    assert lesson["state"] == "probation"
    assert lesson["scope_match"] == {"kind": "exact_query", "query": QUERY}
    assert state["episodes"][current["episode_id"]]["turn_index"] == 1
    assert state["policy"]["turns"]["chat"] == 2
    next_context = tools.prepare_context("t", "u", "chat", QUERY)
    final = tools.observe_turn("t", "u", "chat", QUERY, "done",
                               receipt_ids=[next_context["receipt_id"]])
    assert runtime.episode("t", final["episode_id"])["turn_index"] == 2
    if backend == "sqlite":
        engine.close()
        reloaded = SqliteEngine(path)
        try:
            saved = LearningRuntime(reloaded).writer.read("t")
            assert saved["episodes"][feedback["id"]] == feedback
            assert saved["episodes"][previous] == original_episode
            assert saved["receipts"][receipt] == original_receipt
            assert saved["artifacts"][lesson["id"]]["scope_match"] == lesson["scope_match"]
            assert saved["artifacts"][lesson["id"]]["state"] == "probation"
            assert any(reloaded.get_evidence("t", cid).content == correction
                       for cid in feedback["source_cids"])
        finally:
            reloaded.close()


def test_followup_correction_uses_latest_actual_open_turn():
    from copy import deepcopy
    from mnemosyne.mcp_tools import MemoryTools

    tools = MemoryTools(LocalMemoryEngine())
    previous, _ = completed_answer(tools)
    runtime = tools._learning_runtime()
    before = deepcopy(runtime.episode("t", previous))
    latest = tools.observe_turn("t", "u", "chat", "Explain the dependency tree", "Draft")
    tools.observe_turn("t", "u", "chat", "No, use bullet points.", "Corrected")
    state = runtime.writer.read("t")
    assert runtime.episode("t", previous) == before
    assert runtime.episode("t", latest["episode_id"])["signals"][0]["kind"] == "correction"
    assert not any(row.get("feedback_for_episode_id") for row in state["episodes"].values())


def test_followup_receipt_retry_does_not_duplicate_feedback():
    import pytest
    from mnemosyne.mcp_tools import MemoryTools

    tools = MemoryTools(LocalMemoryEngine())
    previous, _ = completed_answer(tools)
    correction = "No, use bullet points."
    context = tools.prepare_context("t", "u", "chat", correction)
    args = ("t", "u", "chat", correction, "Corrected")
    tools.observe_turn(*args, receipt_ids=[context["receipt_id"]])
    with pytest.raises(ValueError, match="different turn"):
        tools.observe_turn(*args, receipt_ids=[context["receipt_id"]])
    assert sum(row.get("feedback_for_episode_id") == previous
               for row in tools._learning_runtime().writer.read("t")["episodes"].values()) == 1


def test_feedback_scope_text_erases_with_original_query_source():
    from mnemosyne.mcp_tools import MemoryTools

    tools = MemoryTools(LocalMemoryEngine())
    previous, _ = completed_answer(tools)
    runtime = tools._learning_runtime()
    query_cid = next(cid for cid in runtime.episode("t", previous)["source_cids"]
                     if tools.engine.get_evidence("t", cid).content == QUERY)
    tools.observe_turn("t", "u", "chat", "No, use bullet points.", "Corrected")
    feedback = next(row for row in runtime.writer.read("t")["episodes"].values()
                    if row.get("feedback_for_episode_id") == previous)
    assert query_cid in feedback["source_cids"]
    runtime.erase("t", query_cid)
    assert runtime.episode("t", feedback["id"])["user_text"] == ""
    observed = runtime.observe_turn("t", "u", "chat", "Check the next item", "")
    assert runtime.episode("t", observed["episode_id"])["turn_index"] == 2


@pytest.mark.parametrize("case", ["other_user", "other_session", "old", "acceptance", "neutral"])
def test_closed_feedback_link_requires_recent_explicit_same_chat_correction(case, monkeypatch):
    from datetime import timedelta
    from mnemosyne.experience import runtime as runtime_module
    from mnemosyne.mcp_tools import MemoryTools

    tools = MemoryTools(LocalMemoryEngine())
    completed_answer(tools)
    runtime = tools._learning_runtime()
    if case == "old":
        later = runtime_module.now() + timedelta(minutes=16)
        monkeypatch.setattr(runtime_module, "now", lambda: later)
    text = {"acceptance": "Thanks", "neutral": "What is the next step?"}.get(
        case, "No, use bullet points.",
    )
    runtime.observe_turn("t", "other" if case == "other_user" else "u",
                         "other" if case == "other_session" else "chat", text, "")
    assert not any(row.get("feedback_for_episode_id")
                   for row in runtime.writer.read("t")["episodes"].values())
