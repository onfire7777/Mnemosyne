"""Lane B3: batch embedding client + consolidation embedder batching parity.

The batch paths are transport optimizations only — every test here pins the
invariant that batched embedding returns vectors identical to (and in the same
order as) sequential per-item ``embed`` calls.
"""

from __future__ import annotations

import json
import threading
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import Any, Iterator

import pytest

from mnemosyne.consolidation import (
    DEFAULT_EMBED_BATCH_SIZE,
    ConsolidationWorker,
    _embed_batch_size,
    embed_texts_batched,
)
from mnemosyne.models import Evidence
from mnemosyne.retrieval import HashingEmbeddingProvider, HttpEmbeddingProvider
from mnemosyne.text import hashing_embedding


def _raw_vector(text: str) -> list[float]:
    """Deterministic non-zero per-text vector, shared by both server routes."""
    return [float(b) + 1.0 for b in sha256(text.encode("utf-8")).digest()[:4]]


class _EmbedHandler(BaseHTTPRequestHandler):
    """Stub of services/embedding/app.py `handle_embed`: string input returns
    the compact ``{"embedding": [...]}`` shape, list input returns the
    OpenAI-style ``{"data": [{"index": i, "embedding": [...]}]}`` shape."""

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback name.
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        raw = payload.get("input")
        self.server.requests.append(raw)  # type: ignore[attr-defined]
        if isinstance(raw, list):
            if not self.server.batch_enabled:  # type: ignore[attr-defined]
                self._send(
                    int(self.server.batch_error_status),  # type: ignore[attr-defined]
                    {"error": "list input not supported"},
                )
                return
            data = [
                {"object": "embedding", "index": i, "embedding": _raw_vector(text)}
                for i, text in enumerate(raw)
            ]
            if self.server.reverse_batch_order:  # type: ignore[attr-defined]
                data = list(reversed(data))
            self._send(200, {"object": "list", "data": data})
            return
        self._send(200, {"embedding": _raw_vector(raw)})

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:  # keep test output quiet
        return


@pytest.fixture
def embed_server() -> Iterator[ThreadingHTTPServer]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _EmbedHandler)
    server.batch_enabled = True  # type: ignore[attr-defined]
    server.batch_error_status = 400  # type: ignore[attr-defined]
    server.reverse_batch_order = False  # type: ignore[attr-defined]
    server.requests = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _provider(
    server: ThreadingHTTPServer,
    dims: int = 4,
    *,
    cache_size: int = 0,
    model: str | None = None,
    model_revision: str | None = None,
) -> HttpEmbeddingProvider:
    return HttpEmbeddingProvider(
        url=f"http://127.0.0.1:{server.server_address[1]}/embed",
        dims=dims,
        cache_size=cache_size,
        model=model,
        model_revision=model_revision,
    )


def test_embed_many_matches_sequential_in_one_batch_request(embed_server: ThreadingHTTPServer) -> None:
    provider = _provider(embed_server)
    texts = ["alpha", "beta", "gamma", "delta"]
    sequential = [provider.embed(text) for text in texts]
    embed_server.requests.clear()
    batched = provider.embed_many(texts)
    assert batched == sequential
    assert embed_server.requests == [texts]


def test_embed_many_restores_order_from_index_fields(embed_server: ThreadingHTTPServer) -> None:
    embed_server.reverse_batch_order = True
    provider = _provider(embed_server)
    texts = ["one", "two", "three"]
    assert provider.embed_many(texts) == [provider.embed(text) for text in texts]


def test_embed_many_falls_back_sequentially_without_batch_route(embed_server: ThreadingHTTPServer) -> None:
    provider = _provider(embed_server)
    texts = ["alpha", "beta", "gamma"]
    expected = [provider.embed(text) for text in texts]
    embed_server.batch_enabled = False
    embed_server.requests.clear()
    assert provider.embed_many(texts) == expected
    # One rejected batch probe, then one single-item request per text, in order.
    assert embed_server.requests == [texts, *texts]


def test_embed_many_does_not_mask_server_failures(embed_server: ThreadingHTTPServer) -> None:
    embed_server.batch_enabled = False
    embed_server.batch_error_status = 500
    provider = _provider(embed_server)
    with pytest.raises(ValueError, match="HTTP 500"):
        provider.embed_many(["alpha", "beta"])


def test_embed_many_single_and_empty_inputs(embed_server: ThreadingHTTPServer) -> None:
    provider = _provider(embed_server)
    assert provider.embed_many([]) == []
    assert embed_server.requests == []
    assert provider.embed_many(["solo"]) == [provider.embed("solo")]
    # Single-item batches take the single-input route (no list payloads sent).
    assert all(isinstance(request, str) for request in embed_server.requests)


def test_http_embedding_cache_reuses_warm_items_inside_batch(embed_server: ThreadingHTTPServer) -> None:
    uncached = _provider(embed_server, cache_size=0)
    texts = ["warm", "cold", "warm", "second"]
    expected = [uncached.embed(text) for text in texts]

    provider = _provider(embed_server, cache_size=8, model_revision="sha256:cache-a")
    assert provider.embed("warm") == expected[0]
    embed_server.requests.clear()

    assert provider.embed_many(texts) == expected
    assert embed_server.requests == [["cold", "second"]]


def test_http_embedding_cache_key_includes_model_revision(embed_server: ThreadingHTTPServer) -> None:
    rev_a = _provider(embed_server, cache_size=8, model="embed-model", model_revision="sha256:a")
    rev_b = _provider(embed_server, cache_size=8, model="embed-model", model_revision="sha256:b")

    first = rev_a.embed("stable")
    embed_server.requests.clear()

    assert rev_a.embed("stable") == first
    assert embed_server.requests == []
    assert rev_b.embed("stable") == first
    assert embed_server.requests == ["stable"]


def test_http_embedding_cache_size_zero_disables_reuse(embed_server: ThreadingHTTPServer) -> None:
    provider = _provider(embed_server, cache_size=0)

    assert provider.embed("repeat") == provider.embed("repeat")
    assert embed_server.requests == ["repeat", "repeat"]
    embed_server.requests.clear()

    provider.embed_many(["repeat", "other"])
    assert embed_server.requests == [["repeat", "other"]]


def test_hashing_provider_embed_many_matches_per_item() -> None:
    provider = HashingEmbeddingProvider(dims=16)
    texts = ["alpha", "beta", "gamma"]
    assert provider.embed_many(texts) == [hashing_embedding(text, dims=16) for text in texts]


class _RecordingBatchProvider:
    def __init__(self, dims: int = 8):
        self.dims = dims
        self.chunk_sizes: list[int] = []

    def embed(self, text: str) -> list[float]:
        return hashing_embedding(text, dims=self.dims)

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        self.chunk_sizes.append(len(texts))
        return [self.embed(text) for text in texts]


def test_embed_texts_batched_chunks_by_env_and_preserves_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MNEMOSYNE_EMBED_BATCH_SIZE", "3")
    provider = _RecordingBatchProvider()
    texts = [f"text {i}" for i in range(8)]
    vectors = embed_texts_batched(provider, texts)
    assert vectors == [hashing_embedding(text, dims=8) for text in texts]
    assert provider.chunk_sizes == [3, 3, 2]


def test_embed_texts_batched_uses_per_item_embed_without_batch_capability() -> None:
    provider = SimpleNamespace(embed=lambda text: hashing_embedding(text, dims=8))
    texts = ["a", "b", "c"]
    assert embed_texts_batched(provider, texts, batch_size=2) == [
        hashing_embedding(text, dims=8) for text in texts
    ]


def test_embed_batch_size_env_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MNEMOSYNE_EMBED_BATCH_SIZE", raising=False)
    assert _embed_batch_size() == DEFAULT_EMBED_BATCH_SIZE
    monkeypatch.setenv("MNEMOSYNE_EMBED_BATCH_SIZE", "5")
    assert _embed_batch_size() == 5
    monkeypatch.setenv("MNEMOSYNE_EMBED_BATCH_SIZE", "not-a-number")
    assert _embed_batch_size() == DEFAULT_EMBED_BATCH_SIZE
    monkeypatch.setenv("MNEMOSYNE_EMBED_BATCH_SIZE", "-2")
    assert _embed_batch_size() == DEFAULT_EMBED_BATCH_SIZE


class _StubEmbedEngine:
    """Just enough engine surface for ConsolidationWorker._embed_evidence."""

    def __init__(self, dims: int):
        self.adapters = SimpleNamespace(embedding=SimpleNamespace(dims=dims))
        self.calls: list[tuple[str, list[float]]] = []

    def set_evidence_embedding(
        self,
        tenant_id: str,
        cid: str,
        vector: list[float],
        *,
        branch: str,
        actor: str,
        source: str,
    ) -> bool:
        self.calls.append((cid, list(vector)))
        return True


def _evidence(index: int, **overrides: Any) -> Evidence:
    fields: dict[str, Any] = {
        "tenant_id": "tenant-batch",
        "user_id": "user-batch",
        "actor": "user",
        "source_type": "note",
        "content": f"evidence content {index}",
        "cid": f"cid-{index}",
    }
    fields.update(overrides)
    return Evidence(**fields)


def test_embedder_pass_batched_vectors_match_per_item_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    # Chunk size below the item count forces multiple chunks through the seam.
    monkeypatch.setenv("MNEMOSYNE_EMBED_BATCH_SIZE", "2")
    dims = 32
    engine = _StubEmbedEngine(dims=dims)
    worker = ConsolidationWorker(engine, gate_cases=[])
    pending = [_evidence(i) for i in range(5)]
    evidence = [
        *pending,
        _evidence(97, embedding=[1.0] * dims),  # already embedded: untouched
        _evidence(98, cid=None),  # no cid: skipped entirely
    ]
    result = worker._embed_evidence("tenant-batch", "main", evidence)
    assert result["backend_supported"] is True
    assert result["embedded"] == 5
    assert result["already_embedded"] == 1
    assert result["embedded_cids"] == [item.cid for item in pending]
    # Engine writes happen in evidence order with the canonical per-item vectors.
    assert engine.calls == [
        (item.cid, hashing_embedding(item.content, dims=dims)) for item in pending
    ]
    for item in pending:
        assert item.embedding == hashing_embedding(item.content, dims=dims)
