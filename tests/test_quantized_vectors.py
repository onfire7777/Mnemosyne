"""Tests for quantized two-stage vector prefiltering and local adapter discovery."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence
from mnemosyne.quantized_vectors import (
    QuantizedVectorIndex,
    auto_local_retrieval_adapters,
    discover_local_embedding_provider,
    discover_local_reranker,
)
from mnemosyne.retrieval import (
    HashingEmbeddingProvider,
    LocalSimilarityReranker,
    RetrievalAdapters,
)


def test_quantized_index_recall_and_memory_compression():
    rng = np.random.default_rng(42)
    n_docs, dims = 1600, 384
    # Clustered synthetic dense embeddings so nearest neighbors have realistic margins
    centers = rng.standard_normal((32, dims), dtype=np.float32)
    assign = rng.integers(0, 32, size=n_docs)
    docs = centers[assign] + 0.35 * rng.standard_normal((n_docs, dims), dtype=np.float32)
    ids = [f"doc-{i:04d}" for i in range(n_docs)]

    idx = QuantizedVectorIndex.from_vectors(ids, docs)
    mem = idx.memory_bytes()
    assert mem["binary_bytes"] * 30 <= mem["float32_bytes"]
    assert mem["int8_bytes"] * 3 <= mem["float32_bytes"]

    queries = centers[rng.integers(0, 32, size=25)] + 0.25 * rng.standard_normal((25, dims), dtype=np.float32)
    recalls_i8 = []
    recalls_bin = []
    for q in queries:
        exact_top = [doc_id for doc_id, _ in idx.search(q, k=10, mode="exact")]
        i8_top = [doc_id for doc_id, _ in idx.search(q, k=10, mode="int8_rescore")]
        bin_top = [doc_id for doc_id, _ in idx.search(q, k=10, mode="binary_int8_rescore")]
        recalls_i8.append(len(set(exact_top) & set(i8_top)) / 10.0)
        recalls_bin.append(len(set(exact_top) & set(bin_top)) / 10.0)

    assert float(np.mean(recalls_i8)) >= 0.99
    assert float(np.mean(recalls_bin)) >= 0.96


def test_quantized_index_serialization_and_erasure():
    rng = np.random.default_rng(7)
    docs = rng.standard_normal((128, 128), dtype=np.float32)
    ids = [f"cid-{i:03d}" for i in range(128)]
    idx = QuantizedVectorIndex.from_vectors(ids, docs)
    q = docs[17]

    top_before = idx.search(q, k=5, mode="int8_rescore")
    assert top_before[0][0] == "cid-017"

    # Round-trip with float32 and compact int8-only
    restored_full = QuantizedVectorIndex.from_bytes(idx.to_bytes(include_float32=True))
    assert restored_full.search(q, k=5, mode="exact") == idx.search(q, k=5, mode="exact")

    compact_bytes = idx.to_bytes(include_float32=False)
    assert len(compact_bytes) < len(idx.to_bytes(include_float32=True)) // 2
    restored_compact = QuantizedVectorIndex.from_bytes(compact_bytes)
    assert restored_compact.search(q, k=5, mode="int8_rescore")[0][0] == "cid-017"

    # Physical erasure removes target ID completely
    removed = idx.remove_ids(["cid-017", "nonexistent"])
    assert removed == 1
    assert "cid-017" not in idx.ids
    top_after = idx.search(q, k=10, mode="exact")
    assert all(doc_id != "cid-017" for doc_id, _ in top_after)


def test_loopback_cross_encoder_discovery_and_logit_sigmoid(monkeypatch):
    class MockRerankHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002
            return

        def do_GET(self):
            if self.path == "/health":
                body = json.dumps(
                    {"status": "ok", "reranker": {"model": "mock-ce", "backend": "cross-encoder"}}
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            # Verify raw query was sent without E5 "query: " prefix
            assert not payload["query"].startswith("query: ")
            docs = payload["documents"]
            # Emit raw CrossEncoder logits including negative values
            results = [
                {"index": i, "score": 4.0 if "gold" in doc else -5.0}
                for i, doc in enumerate(docs)
            ]
            body = json.dumps({"model": "mock-ce", "results": results}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), MockRerankHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("MNEMOSYNE_LOCAL_RERANKER_URL", f"http://127.0.0.1:{port}/rerank")
        monkeypatch.setenv("MNEMOSYNE_LOCAL_EMBEDDING_URL", "http://127.0.0.1:9/v1/embeddings")
        monkeypatch.setenv("MNEMOSYNE_ALLOWED_INTERNAL_HOSTS", "127.0.0.1")
        reranker = discover_local_reranker(probe_timeout_seconds=1.0)
        from mnemosyne.models import Hit

        hits = [
            Hit(id="a", kind="evidence", tenant_id="t", branch="main", text="distractor", score=0.8, channel="dense"),
            Hit(id="b", kind="evidence", tenant_id="t", branch="main", text="gold answer", score=0.4, channel="dense"),
        ]
        ranked = reranker.rerank("find gold", hits, k=2)
        assert [h.id for h in ranked] == ["b", "a"]
        # Sigmoid(4.0) ~ 0.982, Sigmoid(-5.0) ~ 0.0067 -> both strictly inside (0, 1)
        assert 0.95 < ranked[0].score < 1.0
        assert 0.0 < ranked[1].score < 0.05
        assert ranked[0].metadata["rerank_raw_score"] == 4.0
    finally:
        server.shutdown()
        server.server_close()

    # Offline fallback returns deterministic LocalSimilarityReranker & HashingEmbeddingProvider
    adapters = auto_local_retrieval_adapters(allow_loopback_http=False, allow_inprocess_onnx=False)
    assert isinstance(adapters.embedding, HashingEmbeddingProvider)
    assert isinstance(adapters.reranker, LocalSimilarityReranker)
    assert isinstance(discover_local_embedding_provider(allow_loopback_http=False, allow_inprocess_onnx=False), HashingEmbeddingProvider)


def test_engine_quantized_prefilter_custody_parity():
    @dataclass(frozen=True)
    class DenseMockProvider:
        dims: int = 64
        name: str = "dense-mock"

        def embed(self, text: str) -> list[float]:
            return HashingEmbeddingProvider(dims=self.dims).embed(text)

    eng = LocalMemoryEngine(adapters=RetrievalAdapters(embedding=DenseMockProvider()))
    for i in range(80):
        eng.append_evidence(
            Evidence(
                tenant_id="t1",
                user_id="u1",
                actor="user",
                source_type="note",
                content=f"Document {i} about distributed database consensus raft paxos" if i == 42 else f"Filler note {i} gardening",
                access_policy={"tenant": "t1", "allow_principals": ["u1"]},
            )
        )
    # Cross-tenant secret item must never leak through quantized prefilter
    secret_cid = eng.append_evidence(
        Evidence(
            tenant_id="t2",
            user_id="u2",
            actor="user",
            source_type="note",
            content="distributed database consensus raft paxos secret",
            access_policy={"tenant": "t2", "allow_principals": ["u2"]},
        )
    )
    hits_q = eng.vector_search(
        "distributed database consensus raft",
        k=5,
        filt={"tenant_id": "t1", "user_id": "u1", "quantized_prefilter": True, "quantized_mode": "int8_rescore"},
    )
    hits_exact = eng.vector_search(
        "distributed database consensus raft",
        k=5,
        filt={"tenant_id": "t1", "user_id": "u1"},
    )
    assert hits_q[0].id == hits_exact[0].id
    assert all(h.id != secret_cid for h in hits_q)
    assert hits_q[0].metadata.get("quantized_prefilter") == "int8_rescore"
