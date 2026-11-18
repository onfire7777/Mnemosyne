"""Recall server provider wrappers: hedged query embedding and the reranker retry."""
import importlib.util
import sys
import time
import types
from dataclasses import dataclass, field
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1] / "integrations/codex/recall_server.py"


@pytest.fixture(scope="module")
def server():
    # The deployed runtime.py is not importable in tests; the wrappers do not use it.
    stub = types.ModuleType("runtime")
    stub.AGENT, stub.ROOT, stub.STATE = "codex", Path("/nonexistent"), Path("/nonexistent")
    stub.configure_retrieval = stub.invoke = stub.open_facade = None
    saved = sys.modules.get("runtime")
    sys.modules["runtime"] = stub
    try:
        spec = importlib.util.spec_from_file_location("recall_server_under_test", SERVER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        if saved is None:
            sys.modules.pop("runtime", None)
        else:
            sys.modules["runtime"] = saved


@dataclass(frozen=True)
class Scripted:
    """Each call takes the next (outcome, delay) step."""
    plan: tuple
    timeout_seconds: float = 1.0
    calls: list = field(default_factory=list, compare=False)

    def embed(self, text):
        step = len(self.calls)
        self.calls.append(step)
        outcome, delay = self.plan[step]
        time.sleep(delay)
        if outcome == "error":
            raise ValueError("provider error")
        return [step]


def run(server, plan, deadline=2.0):
    calls = []
    embedder = server.HedgedEmbedder(Scripted(plan, calls=calls), 0.2, deadline)
    try:
        return embedder.embed("q"), len(calls)
    except Exception as error:
        return type(error).__name__, len(calls)


def test_fast_error_is_retried(server):
    assert run(server, (("error", 0), ("ok", 0.05))) == ([1], 2)


def test_slow_request_is_hedged(server):
    assert run(server, (("ok", 1.0), ("ok", 0.05))) == ([1], 2)


def test_at_most_three_attempts(server):
    assert run(server, (("error", 0),) * 3) == ("ValueError", 3)


def test_deadline(server):
    assert run(server, (("ok", 5), ("ok", 5)), deadline=0.5) == ("TimeoutError", 2)


def test_deadline_sets_attempt_timeout(server):
    embedder = server.HedgedEmbedder(Scripted(()), 0.2, 2.0)
    embedder.set_deadline(4.0)
    assert (embedder.deadline, embedder.inner.timeout_seconds) == (4.0, 4.0)


def test_reranker_retries_once_on_timeout(server):
    class Flaky:
        name = "http"
        calls = 0

        def rerank(self, query, hits, k):
            Flaky.calls += 1
            if Flaky.calls == 1:
                raise TimeoutError("timed out")
            return hits[:k]

    reranker = server.RetryingReranker(Flaky())
    assert reranker.rerank("q", [1, 2, 3], 2) == [1, 2] and Flaky.calls == 2
    assert reranker.name == "http" and getattr(reranker, "embedding_provider", None) is None
