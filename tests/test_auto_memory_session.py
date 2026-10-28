"""Tests for AutoMemorySession 1-line middleware SDK, wrap_chat_callable,
dynamic turn novelty scoring, adaptive context budgeting, and ContextVar isolation.
"""

from __future__ import annotations

import threading
from pathlib import Path
import pytest

from mnemosyne import AutoMemorySession, wrap_chat_callable
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.frameworks import (
    CACHE,
    MODEL,
    adaptive_context_budget,
    cache_scope,
    framework_context,
    model_scope,
    score_turn_novelty,
)


@pytest.fixture
def engine(tmp_path: Path) -> LocalMemoryEngine:
    return LocalMemoryEngine(store_path=tmp_path / "store.json")


# --- 1. Dynamic Turn Novelty Scoring ---


def test_score_turn_novelty_basic_and_repeated() -> None:
    prior_turns = ["Hello world, how are you today?"]

    # Brand new text should have higher novelty
    novel_text = "Quantum computing uses superposition and entanglement to factor prime numbers."
    novel_score = score_turn_novelty(novel_text, prior_turns)
    assert 0.0 <= novel_score <= 1.0
    assert novel_score > 0.5

    # Completely repeated text should have low novelty
    repeated_score = score_turn_novelty("Hello world, how are you today?", prior_turns)
    assert repeated_score < 0.3


def test_score_turn_novelty_directives_and_facts() -> None:
    # Goal declarations should get a novelty boost
    goal_text = "Goal: we must implement zero-copy deserialization for IPC."
    goal_score = score_turn_novelty(goal_text, [])
    assert goal_score >= 0.7

    # Constraint declarations should get a novelty boost
    constraint_text = "Never use unsafe pointers in production handlers."
    constraint_score = score_turn_novelty(constraint_text, [])
    assert constraint_score >= 0.7

    # Factual declarations should get a boost
    fact_text = "The server returned HTTP status 503 during load testing at 10000 req/s."
    fact_score = score_turn_novelty(fact_text, [])
    assert fact_score >= 0.6


def test_score_turn_novelty_edge_cases() -> None:
    # Empty string
    assert score_turn_novelty("", []) == 0.0
    assert score_turn_novelty("   ", []) == 0.0

    # Punctuation only
    assert score_turn_novelty("...", []) <= 0.1

    # Single word conversational acknowledgment
    score = score_turn_novelty("Thanks", ["Thanks"])
    assert score <= 0.3


# --- 2. Adaptive Context Sub-Budgeting ---


def test_adaptive_context_budget_partition() -> None:
    total_budget = 4096
    budgets = adaptive_context_budget(
        total_budget=total_budget,
        active_goal_count=2,
        history_turn_count=3,
        turn_novelty=0.8,
    )

    assert "goals" in budgets
    assert "knowledge" in budgets
    assert "evidence" in budgets

    assert budgets["goals"] > 0
    assert budgets["knowledge"] > 0
    assert budgets["evidence"] > 0

    assert sum(budgets.values()) <= total_budget


def test_adaptive_context_budget_shifts_with_goals_and_novelty() -> None:
    total_budget = 2000

    # With zero goals, goal budget is minimal
    no_goals = adaptive_context_budget(
        total_budget=total_budget,
        active_goal_count=0,
        history_turn_count=2,
        turn_novelty=0.2,
    )

    # With multiple active goals, goal budget increases
    with_goals = adaptive_context_budget(
        total_budget=total_budget,
        active_goal_count=5,
        history_turn_count=2,
        turn_novelty=0.2,
    )

    assert with_goals["goals"] > no_goals["goals"]

    # High novelty shifts budget towards evidence
    high_novelty = adaptive_context_budget(
        total_budget=total_budget,
        active_goal_count=1,
        history_turn_count=2,
        turn_novelty=0.95,
    )
    low_novelty = adaptive_context_budget(
        total_budget=total_budget,
        active_goal_count=1,
        history_turn_count=2,
        turn_novelty=0.1,
    )

    assert high_novelty["evidence"] > low_novelty["evidence"]


def test_adaptive_context_budget_low_total_clamped() -> None:
    low_total = 60
    budgets = adaptive_context_budget(total_budget=low_total, active_goal_count=1)
    assert sum(budgets.values()) <= low_total
    for val in budgets.values():
        assert val >= 0


# --- 3. AutoMemorySession Lifecycle & Dual-Plane Storage ---


def test_auto_memory_session_context_manager(engine: LocalMemoryEngine) -> None:
    tenant = "tenant-sdk"
    user = "user-sdk"
    session_id = "sess-100"

    with AutoMemorySession(engine, tenant_id=tenant, user_id=user, session_id=session_id) as session:
        assert session.session_id == session_id
        assert session.tenant_id == tenant
        assert session.user_id == user

        def dummy_chat(prompt: str) -> str:
            return f"Processed: {prompt}"

        # Turn 1
        resp1 = session.step("I need to deploy Redis cluster on port 6379.", dummy_chat)
        assert resp1 == "Processed: I need to deploy Redis cluster on port 6379."

        # Turn 2 with goal declaration
        resp2 = session.step("Goal: ensure high availability with 3 replicas.", dummy_chat)
        assert "replicas" in resp2

    # After exit, session is closed and auto-consolidation ran
    assert session._closed is True
    assert len(session._session_evidence_cids) >= 2

    # Working memory items were recorded in engine
    working_items = [item for (t, s, _), item in engine.working_memory.items() if t == tenant and s == session_id]
    assert len(working_items) >= 2


def test_auto_memory_session_consolidation_into_observations(engine: LocalMemoryEngine) -> None:
    tenant = "tenant-consolidation"
    user = "user-consolidation"
    session_id = "sess-obs-1"

    with AutoMemorySession(engine, tenant_id=tenant, user_id=user, session_id=session_id) as session:
        def dummy_chat(prompt: str) -> str:
            return "Understood."

        session.step("Goal: migrate MySQL database to PostgreSQL 16.", dummy_chat)
        session.step("Always use TLS 1.3 for all database connections.", dummy_chat)

    # Check observations created in engine
    obs_list = engine.observation_list(tenant)
    assert len(obs_list) >= 1

    # Verify that observation contains proof quotes grounded in source evidence CIDs
    for obs in obs_list:
        assert obs.tenant_id == tenant
        assert obs.user_id == user
        if obs.proof_quotes:
            for pq in obs.proof_quotes:
                assert pq.cid in session._session_evidence_cids


# --- 4. 1-Line wrap_chat_callable Middleware ---


def test_wrap_chat_callable_string_prompt(engine: LocalMemoryEngine) -> None:
    call_log: list[str] = []

    def mock_llm(prompt: str) -> str:
        call_log.append(prompt)
        return "I will use Python 3.12 syntax."

    wrapped = wrap_chat_callable(
        mock_llm,
        engine=engine,
        tenant_id="t-wrapped",
        user_id="u-wrapped",
        session_id="s-wrapped",
    )

    # First call
    out1 = wrapped("Please write a typing example.")
    assert out1 == "I will use Python 3.12 syntax."
    assert len(call_log) == 1

    # Second call - working memory should be updated and pre-turn context retrieved
    out2 = wrapped("Now add generic type aliases.")
    assert out2 == "I will use Python 3.12 syntax."
    assert len(call_log) == 2


def test_wrap_chat_callable_message_list(engine: LocalMemoryEngine) -> None:
    def mock_chat(messages: list[dict[str, str]]) -> str:
        assert isinstance(messages, list)
        return "Acknowledged."

    wrapped = wrap_chat_callable(
        mock_chat,
        engine=engine,
        tenant_id="t-list",
        user_id="u-list",
        session_id="s-list",
    )

    msgs = [
        {"role": "user", "content": "Always prefer concise explanations."}
    ]
    res = wrapped(msgs)
    assert res == "Acknowledged."

    # Inspect wrapped session
    session = getattr(wrapped, "session")
    assert session is not None
    assert "Always prefer concise explanations." in session._active_constraints or any(
        "Always prefer concise" in c for c in session._active_constraints
    )


# --- 5. Strict ContextVar Isolation ---


def test_contextvar_scopes_pairing() -> None:
    # Ensure CACHE and MODEL start empty
    assert CACHE.get() == ""
    assert MODEL.get() == ""

    # cache_scope guarantees reset
    with cache_scope("/tmp/test_cache"):
        assert CACHE.get() == "/tmp/test_cache"
    assert CACHE.get() == ""

    # model_scope guarantees reset
    with model_scope("custom-llm-v1"):
        assert MODEL.get() == "custom-llm-v1"
    assert MODEL.get() == ""

    # framework_context handles multiple variables
    with framework_context(cache="/tmp/fc", model="m-fc"):
        assert CACHE.get() == "/tmp/fc"
        assert MODEL.get() == "m-fc"
    assert CACHE.get() == ""
    assert MODEL.get() == ""


def test_contextvar_isolation_on_exception() -> None:
    assert MODEL.get() == ""

    with pytest.raises(RuntimeError, match="simulated failure"):
        with framework_context(model="failing-model"):
            assert MODEL.get() == "failing-model"
            raise RuntimeError("simulated failure")

    # Guaranteed reset even when exception was raised
    assert MODEL.get() == ""


def test_contextvar_thread_isolation() -> None:
    results: dict[str, str] = {}

    def worker(name: str, model_name: str) -> None:
        with framework_context(model=model_name):
            # Sleep briefly to ensure overlapping execution
            import time
            time.sleep(0.01)
            results[name] = MODEL.get()

    t1 = threading.Thread(target=worker, args=("t1", "model-thread-1"))
    t2 = threading.Thread(target=worker, args=("t2", "model-thread-2"))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert results["t1"] == "model-thread-1"
    assert results["t2"] == "model-thread-2"
    assert MODEL.get() == ""
