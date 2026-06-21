"""Real embedding + cross-encoder reranker microservice for Mnemosyne.

This service implements the exact HTTP provider contract that Mnemosyne's
``HttpEmbeddingProvider`` and ``HttpReranker`` adapters speak
(see ``src/mnemosyne/retrieval.py``):

``POST /embed``
    Request:  ``{"input": "<text>", "model"?: "<model-id>"}``
    Response: ``{"embedding": [float, ...], "model": "<id>", "dimensions": <int>}``
    (also accepts batch ``{"input": ["t1", "t2"]}`` -> OpenAI-style
    ``{"data": [{"index": 0, "embedding": [...]}, ...], "model": "<id>"}``)

``POST /rerank``
    Request:  ``{"query": "<q>", "documents": ["d0", "d1", ...], "top_n"?: int,
                 "model"?: "<model-id>"}``
    Response: ``{"results": [{"index": <int>, "score": <float>}, ...],
                 "model": "<id>"}``

``GET /health``
    Response: ``{"status": "ok", "embedding": {...}, "reranker": {...}}``

Mnemosyne's adapter Matryoshka-truncates or zero-pads the returned embedding to
its configured dimension (default ``VECTOR(1024)``) and L2-normalizes it, then
rejects an all-zero vector. We therefore emit a dense, non-zero vector of
exactly ``EMBED_DIMS`` (default 1024) values. The reranker returns
``{index, score}`` rows; Mnemosyne sorts by score descending, so the only
semantic requirement is that more relevant documents score higher.

Two execution paths:

* **Real path** (preferred): sentence-transformers / torch.
  - Embedding model:  ``BAAI/bge-small-en-v1.5`` (384-dim) by default, projected
    to ``EMBED_DIMS`` via a deterministic, seeded random projection (a real,
    information-preserving linear map), or ``all-MiniLM-L6-v2``.
  - Reranker model:   ``cross-encoder/ms-marco-MiniLM-L-6-v2`` (real
    cross-encoder relevance scoring).

* **Fallback path** (no torch / offline / model download blocked): a clearly
  marked, *contract-correct* deterministic encoder. It produces dense non-zero
  1024-dim vectors and a lexical-overlap reranker that still ranks relevant
  documents above irrelevant ones — so the Mnemosyne adapter contract and this
  package's self-test pass NOW, with no network. Flip to the real path simply by
  ``pip install -r requirements.txt`` (and allowing model download).

The HTTP layer prefers FastAPI + uvicorn when installed; otherwise it serves
the identical routes on the Python standard-library ``http.server`` so the
service runs with zero third-party dependencies.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import struct
from dataclasses import dataclass, field
from typing import Any, Sequence

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

#: Target embedding dimension. MUST match Mnemosyne's VECTOR(1024) columns and
#: the ``MNEMOSYNE_EMBEDDING_DIMS`` default. Overridable for experiments.
EMBED_DIMS: int = int(os.environ.get("EMBEDDING_SERVICE_DIMS", "1024"))

#: Default real embedding model. ``BAAI/bge-small-en-v1.5`` is a strong, small
#: (384-dim) retrieval encoder; ``sentence-transformers/all-MiniLM-L6-v2`` is the
#: lighter alternative named in the blueprint.
DEFAULT_EMBED_MODEL: str = os.environ.get(
    "EMBEDDING_SERVICE_MODEL", "BAAI/bge-small-en-v1.5"
)

#: Default real cross-encoder reranker model.
DEFAULT_RERANK_MODEL: str = os.environ.get(
    "RERANKER_SERVICE_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"
)

#: Force the deterministic fallback even if torch is importable (useful in CI).
FORCE_FALLBACK: bool = os.environ.get("EMBEDDING_SERVICE_FORCE_FALLBACK", "") not in (
    "",
    "0",
    "false",
    "False",
)

HOST: str = os.environ.get("EMBEDDING_SERVICE_HOST", "127.0.0.1")
PORT: int = int(os.environ.get("EMBEDDING_SERVICE_PORT", "8000"))


# --------------------------------------------------------------------------- #
# Deterministic, contract-correct fallback encoder
# --------------------------------------------------------------------------- #
#
# This mirrors the spirit of Mnemosyne's own ``hashing_embedding`` but produces a
# dense, guaranteed-non-zero ``EMBED_DIMS`` vector. It is fully deterministic and
# needs no network or native deps, so the service is runnable and testable now.


def _token_floats(token: str, dims: int) -> list[float]:
    """Expand one token into ``dims`` deterministic floats in roughly [-1, 1]."""

    out: list[float] = []
    counter = 0
    while len(out) < dims:
        digest = hashlib.sha256(f"{token}\x00{counter}".encode("utf-8")).digest()
        # 8 bytes -> one double in [0, 1); recenter to [-1, 1).
        for i in range(0, len(digest), 8):
            chunk = digest[i : i + 8]
            (raw,) = struct.unpack("<Q", chunk)
            out.append((raw / 0xFFFFFFFFFFFFFFFF) * 2.0 - 1.0)
            if len(out) >= dims:
                break
        counter += 1
    return out[:dims]


def _tokenize(text: str) -> list[str]:
    return [t for t in "".join(c.lower() if c.isalnum() else " " for c in text).split() if t]


def fallback_embed(text: str, dims: int = EMBED_DIMS) -> list[float]:
    """Deterministic dense bag-of-tokens embedding, guaranteed non-zero.

    Uses term frequency weighting over per-token hashed basis vectors. Identical
    text yields identical vectors; texts that share tokens have higher cosine
    similarity, which is enough for the reranker fallback and the contract test.
    """

    tokens = _tokenize(text)
    acc = [0.0] * dims
    if not tokens:
        # Stable non-zero vector for empty/symbol-only input so the adapter's
        # non-zero-vector requirement is always satisfied.
        seed = _token_floats("\x01empty-document\x01", dims)
        return seed
    for tok in tokens:
        basis = _token_floats(tok, dims)
        for i in range(dims):
            acc[i] += basis[i]
    norm = math.sqrt(sum(v * v for v in acc))
    if norm == 0.0:  # pragma: no cover - astronomically unlikely
        return _token_floats("\x01empty-document\x01", dims)
    return [v / norm for v in acc]


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return num / (na * nb)


def _lexical_overlap(query: str, document: str) -> float:
    """Jaccard-ish lexical overlap in [0, 1]; relevant docs score higher."""

    q = set(_tokenize(query))
    d = set(_tokenize(document))
    if not q or not d:
        return 0.0
    inter = len(q & d)
    return inter / math.sqrt(len(q) * len(d))


def fallback_rerank_scores(query: str, documents: Sequence[str]) -> list[float]:
    """Real (non-trivial) relevance scores using lexical + dense overlap.

    Combines token overlap with cosine similarity of the deterministic dense
    embeddings so that semantically/lexically relevant documents outrank
    irrelevant ones — the property the Mnemosyne provider-check asserts.
    """

    q_vec = fallback_embed(query)
    scores: list[float] = []
    for doc in documents:
        lexical = _lexical_overlap(query, doc)
        dense = max(0.0, _cosine(q_vec, fallback_embed(doc)))
        scores.append(0.6 * lexical + 0.4 * dense)
    return scores


# --------------------------------------------------------------------------- #
# Real model backend (lazy, optional)
# --------------------------------------------------------------------------- #


@dataclass
class Backend:
    """Resolves embedding/reranking to the real model path or the fallback."""

    embed_model_name: str = DEFAULT_EMBED_MODEL
    rerank_model_name: str = DEFAULT_RERANK_MODEL
    dims: int = EMBED_DIMS

    _embed_model: Any = field(default=None, init=False, repr=False)
    _rerank_model: Any = field(default=None, init=False, repr=False)
    _proj: Any = field(default=None, init=False, repr=False)
    _backend_kind: str = field(default="uninitialized", init=False)
    _rerank_kind: str = field(default="uninitialized", init=False)

    # -- embeddings -------------------------------------------------------- #

    def _ensure_embed_model(self) -> None:
        if self._backend_kind != "uninitialized":
            return
        if FORCE_FALLBACK:
            self._backend_kind = "fallback"
            return
        try:  # pragma: no cover - exercised only when torch is installed.
            from sentence_transformers import SentenceTransformer  # type: ignore

            self._embed_model = SentenceTransformer(self.embed_model_name)
            self._backend_kind = "sentence-transformers"
        except Exception:
            self._embed_model = None
            self._backend_kind = "fallback"

    def _projection_matrix(self, src_dim: int) -> list[list[float]]:
        """Deterministic seeded random projection src_dim -> self.dims.

        A real, information-preserving linear map (Johnson–Lindenstrauss style)
        so true model semantics survive the lift to VECTOR(1024). Cached.
        """

        if self._proj is not None:
            return self._proj
        rows: list[list[float]] = []
        scale = 1.0 / math.sqrt(src_dim)
        for j in range(self.dims):
            rows.append([v * scale for v in _token_floats(f"proj:{src_dim}:{j}", src_dim)])
        self._proj = rows
        return rows

    def _project(self, vec: Sequence[float]) -> list[float]:
        """Map a model vector to exactly ``self.dims`` and L2-normalize."""

        n = len(vec)
        if n == self.dims:
            out = list(vec)
        elif n > self.dims:
            out = list(vec[: self.dims])  # Matryoshka truncation
        else:
            proj = self._projection_matrix(n)
            out = [sum(row[i] * vec[i] for i in range(n)) for row in proj]
        norm = math.sqrt(sum(v * v for v in out))
        if norm == 0.0:
            return fallback_embed("\x01zero-model-output\x01", self.dims)
        return [v / norm for v in out]

    def embed_batch(self, texts: Sequence[str]) -> tuple[list[list[float]], str]:
        self._ensure_embed_model()
        if self._backend_kind == "sentence-transformers":  # pragma: no cover
            raw = self._embed_model.encode(list(texts), normalize_embeddings=False)
            vectors = [self._project(list(map(float, row))) for row in raw]
            return vectors, self._backend_kind
        return [fallback_embed(t, self.dims) for t in texts], "fallback"

    # -- reranking --------------------------------------------------------- #

    def _ensure_rerank_model(self) -> None:
        if self._rerank_kind != "uninitialized":
            return
        if FORCE_FALLBACK:
            self._rerank_kind = "fallback"
            return
        try:  # pragma: no cover - exercised only when torch is installed.
            from sentence_transformers import CrossEncoder  # type: ignore

            self._rerank_model = CrossEncoder(self.rerank_model_name)
            self._rerank_kind = "cross-encoder"
        except Exception:
            self._rerank_model = None
            self._rerank_kind = "fallback"

    def rerank_scores(self, query: str, documents: Sequence[str]) -> tuple[list[float], str]:
        self._ensure_rerank_model()
        if self._rerank_kind == "cross-encoder":  # pragma: no cover
            pairs = [[query, doc] for doc in documents]
            raw = self._rerank_model.predict(pairs)
            return [float(s) for s in raw], self._rerank_kind
        return fallback_rerank_scores(query, documents), "fallback"

    # -- introspection ----------------------------------------------------- #

    def info(self) -> dict[str, Any]:
        self._ensure_embed_model()
        self._ensure_rerank_model()
        return {
            "embedding": {
                "model": self.embed_model_name,
                "dimensions": self.dims,
                "backend": self._backend_kind,
            },
            "reranker": {
                "model": self.rerank_model_name,
                "backend": self._rerank_kind,
            },
        }


BACKEND = Backend()


# --------------------------------------------------------------------------- #
# Request handlers (framework-agnostic core)
# --------------------------------------------------------------------------- #


class BadRequest(ValueError):
    """Raised for malformed client payloads -> HTTP 400."""


def handle_embed(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or "input" not in payload:
        raise BadRequest("request body must be a JSON object with an `input` field")
    raw = payload["input"]
    model = payload.get("model") or BACKEND.embed_model_name
    batched = isinstance(raw, list)
    texts = list(raw) if batched else [raw]
    if not texts:
        raise BadRequest("`input` must contain at least one text")
    for t in texts:
        if not isinstance(t, str):
            raise BadRequest("`input` values must be strings")

    vectors, _kind = BACKEND.embed_batch(texts)

    if batched:
        # OpenAI-style batch response; Mnemosyne reads data[0].embedding, but a
        # well-formed list keeps full OpenAI compatibility for batch callers.
        return {
            "object": "list",
            "model": model,
            "dimensions": BACKEND.dims,
            "data": [
                {"object": "embedding", "index": i, "embedding": vec}
                for i, vec in enumerate(vectors)
            ],
        }
    # Compact single-vector shape consumed by HttpEmbeddingProvider.
    return {"embedding": vectors[0], "model": model, "dimensions": BACKEND.dims}


def handle_rerank(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise BadRequest("request body must be a JSON object")
    query = payload.get("query")
    documents = payload.get("documents")
    if not isinstance(query, str) or not query:
        raise BadRequest("`query` must be a non-empty string")
    if not isinstance(documents, list) or not documents:
        raise BadRequest("`documents` must be a non-empty array")
    for d in documents:
        if not isinstance(d, str):
            raise BadRequest("`documents` values must be strings")
    model = payload.get("model") or BACKEND.rerank_model_name
    top_n = payload.get("top_n")

    scores, _kind = BACKEND.rerank_scores(query, documents)
    ranked = sorted(
        ({"index": i, "score": float(s)} for i, s in enumerate(scores)),
        key=lambda r: r["score"],
        reverse=True,
    )
    if isinstance(top_n, int) and not isinstance(top_n, bool) and top_n > 0:
        ranked = ranked[:top_n]
    return {"results": ranked, "model": model}


def handle_health() -> dict[str, Any]:
    info = BACKEND.info()
    return {"status": "ok", **info}


# --------------------------------------------------------------------------- #
# HTTP layer: FastAPI when available, else stdlib http.server
# --------------------------------------------------------------------------- #


def build_fastapi_app():  # pragma: no cover - only when fastapi installed
    from fastapi import Body, FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI(title="Mnemosyne Embedding + Reranker Service", version="1.0.0")

    @app.get("/health")
    async def _health() -> dict[str, Any]:
        return handle_health()

    # ``payload: dict = Body(...)`` makes FastAPI parse the raw JSON body into a
    # dict and hand it straight to our framework-agnostic handlers. We must NOT
    # name a parameter ``request`` with a non-special type, or FastAPI treats it
    # as a query parameter.
    @app.post("/embed")
    async def _embed(payload: dict = Body(...)):  # noqa: B008 - FastAPI idiom
        try:
            return handle_embed(payload)
        except BadRequest as exc:
            return JSONResponse(status_code=400, content={"error": str(exc)})

    @app.post("/rerank")
    async def _rerank(payload: dict = Body(...)):  # noqa: B008 - FastAPI idiom
        try:
            return handle_rerank(payload)
        except BadRequest as exc:
            return JSONResponse(status_code=400, content={"error": str(exc)})

    return app


def _make_stdlib_handler():
    from http.server import BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, status: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            if self.path.rstrip("/") in ("/health", ""):
                self._send(200, handle_health())
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802 - stdlib naming
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self._send(400, {"error": "request body must be valid JSON"})
                return
            route = self.path.rstrip("/")
            try:
                if route == "/embed":
                    self._send(200, handle_embed(payload))
                elif route == "/rerank":
                    self._send(200, handle_rerank(payload))
                else:
                    self._send(404, {"error": "not found"})
            except BadRequest as exc:
                self._send(400, {"error": str(exc)})

        def log_message(self, *args: Any) -> None:  # quiet by default
            if os.environ.get("EMBEDDING_SERVICE_VERBOSE"):
                super().log_message(*args)

    return Handler


def serve(host: str = HOST, port: int = PORT) -> None:
    """Start the service. Uses uvicorn+FastAPI if importable, else stdlib."""

    try:  # pragma: no cover - depends on optional deps
        import uvicorn  # type: ignore

        app = build_fastapi_app()  # raises ImportError if fastapi is absent
        print(f"[embedding-service] FastAPI/uvicorn on http://{host}:{port}", flush=True)
        uvicorn.run(app, host=host, port=port, log_level="warning")
        return
    except Exception:
        pass

    from http.server import ThreadingHTTPServer

    handler = _make_stdlib_handler()
    httpd = ThreadingHTTPServer((host, port), handler)
    print(
        f"[embedding-service] stdlib http.server on http://{host}:{port} "
        f"(install requirements.txt for FastAPI + real models)",
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover
        httpd.shutdown()


if __name__ == "__main__":  # pragma: no cover
    serve()
