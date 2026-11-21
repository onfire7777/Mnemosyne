"""Request-owned query vectors, local Unix-socket embedding client, and vector-space guards."""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import math
import os
import re
import socket
import threading
from typing import Any


class VectorSpaceMismatchError(ValueError):
    """Raised when an embedding provider's model/dimensions do not match the store's vector space."""


@dataclass(frozen=True)
class VectorSpaceIdentity:
    """Canonical identity for one embedding vector space (never mix spaces without re-embedding)."""

    model: str
    dims: int
    provider_kind: str = "http"
    query_prefix: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("vector space model must be a non-empty string")
        if type(self.dims) is not int or self.dims <= 0:
            raise ValueError("vector space dims must be a positive integer")

    @property
    def space_id(self) -> str:
        return f"{self.model}@{self.dims}"

    def cache_scope(self, tenant_id: str = "personal") -> str:
        # Preserve exact legacy live OpenRouter Qwen3-8B 4096-d cache scope.
        if self.model == "qwen/qwen3-embedding-8b" and self.dims == 4096:
            return f"{tenant_id}-qwen3-8b-4096"
        slug = re.sub(r"[^a-z0-9]+", "-", self.model.lower()).strip("-") or "model"
        return f"{tenant_id}-{slug}-{self.dims}"


def _normalize_l2(values: Sequence[float], dims: int) -> list[float]:
    if len(values) < dims:
        raise VectorSpaceMismatchError(
            f"embedding vector has {len(values)} dimensions, expected at least {dims}"
        )
    clipped = [float(values[i]) for i in range(dims)]
    if any(not math.isfinite(v) for v in clipped):
        raise ValueError("embedding vector contains non-finite values")
    norm = math.sqrt(math.fsum(v * v for v in clipped))
    if norm <= 0.0:
        raise ValueError("embedding vector has zero norm")
    return [v / norm for v in clipped]


def assert_vector_space_compatible(
    expected: VectorSpaceIdentity,
    actual_dims: Sequence[int] | set[int] | int | None,
    *,
    actual_model: str | None = None,
) -> None:
    """Fail closed if persisted vectors belong to a different model or dimension space."""
    if isinstance(actual_dims, int):
        dims_set = {actual_dims} if actual_dims > 0 else set()
    elif actual_dims:
        dims_set = {int(d) for d in actual_dims if int(d) > 0}
    else:
        dims_set = set()
    if dims_set and dims_set != {expected.dims}:
        found = ", ".join(str(d) for d in sorted(dims_set))
        raise VectorSpaceMismatchError(
            f"Store contains embeddings with dimensions [{found}] which cannot be mixed with "
            f"{expected.space_id}. Run an explicit offline re-embed (embedding_service.py reembed "
            f"--confirm-reembed) before switching vector spaces."
        )
    if actual_model and actual_model.strip() and actual_model.strip() != expected.model:
        raise VectorSpaceMismatchError(
            f"Store/daemon model {actual_model!r} does not match expected vector space "
            f"{expected.space_id}. Keep vector spaces strictly separated or run an explicit re-embed."
        )


def inspect_store_vector_space(
    engine: Any,
    tenant_id: str,
    branch: str = "main",
) -> dict[str, Any]:
    """Inspect active embedding dimensions per table without reading or returning private text."""
    from mnemosyne.sqlite_schema import unpack_embedding

    counts_by_dim: dict[int, int] = {}
    tables_report: dict[str, dict[str, Any]] = {}

    if hasattr(engine, "_connect"):
        conn = engine._connect(tenant_id)
        queries = (
            (
                "evidence",
                "SELECT embedding FROM evidence WHERE tenant_id = ? AND branch = ? "
                "AND erased = 0 AND retired_at IS NULL AND modality = 'text' "
                "AND source_type != 'learning_tool_result'",
                (tenant_id, branch),
            ),
            (
                "assertions",
                "SELECT embedding FROM assertions WHERE tenant_id = ? AND branch = ? "
                "AND status IN ('active', 'contested')",
                (tenant_id, branch),
            ),
            (
                "observations",
                "SELECT embedding FROM observations WHERE tenant_id = ? AND branch = ? "
                "AND status = 'active'",
                (tenant_id, branch),
            ),
            (
                "preferences",
                "SELECT embedding FROM preferences WHERE tenant_id = ? "
                "AND COALESCE(json_extract(record, '$.status'), 'active') = 'active'",
                (tenant_id,),
            ),
            (
                "knowledge_pages",
                "SELECT embedding FROM knowledge_pages WHERE tenant_id = ? AND branch = ? "
                "AND status = 'active'",
                (tenant_id, branch),
            ),
        )
        lock = getattr(engine, "_lock", None)
        for table, sql, params in queries:
            try:
                if lock is not None:
                    with lock:
                        rows = conn.execute(sql, params).fetchall()
                else:
                    rows = conn.execute(sql, params).fetchall()
            except Exception:
                tables_report[table] = {"embedded": 0, "unembedded": 0, "dims": []}
                continue
            embedded = 0
            unembedded = 0
            t_dims: set[int] = set()
            for row in rows:
                blob = row[0]
                if blob is None:
                    unembedded += 1
                    continue
                vec = unpack_embedding(blob)
                if not vec:
                    unembedded += 1
                    continue
                dim = len(vec)
                embedded += 1
                t_dims.add(dim)
                counts_by_dim[dim] = counts_by_dim.get(dim, 0) + 1
            tables_report[table] = {
                "embedded": embedded,
                "unembedded": unembedded,
                "dims": sorted(t_dims),
            }
    else:
        exported = engine.export_tenant(tenant_id)
        ev_embedded = 0
        ev_unembedded = 0
        ev_dims: set[int] = set()
        for row in exported.get("evidence", []):
            if row.get("branch", "main") != branch or row.get("erased") or row.get("retired_at"):
                continue
            if row.get("source_type") == "learning_tool_result":
                continue
            emb = row.get("embedding")
            if emb:
                dim = len(emb)
                ev_embedded += 1
                ev_dims.add(dim)
                counts_by_dim[dim] = counts_by_dim.get(dim, 0) + 1
            else:
                ev_unembedded += 1
        tables_report["evidence"] = {
            "embedded": ev_embedded,
            "unembedded": ev_unembedded,
            "dims": sorted(ev_dims),
        }

    dims_sorted = sorted(counts_by_dim)
    return {
        "tenant_id": tenant_id,
        "branch": branch,
        "dimensions": dims_sorted,
        "counts_by_dim": counts_by_dim,
        "tables": tables_report,
        "mixed": len(dims_sorted) > 1,
    }


@dataclass(frozen=True)
class UnixSocketEmbeddingProvider:
    """Zero-egress local embedding client over a private 0600 Unix domain socket.

    Frozen dataclass so ``dataclasses.replace(provider, timeout_seconds=...)`` works
    identically to :class:`HttpEmbeddingProvider` inside ``recall_server.py``.
    """

    socket_path: str
    model: str = "BAAI/bge-small-en-v1.5"
    dims: int = 384
    query_prefix: str = "Represent this sentence for searching relevant passages: "
    timeout_seconds: float = 5.0
    name: str = "unix-local-embedding"
    max_batch: int = 64
    verify_space: bool = True

    @property
    def vector_space(self) -> VectorSpaceIdentity:
        return VectorSpaceIdentity(
            model=self.model,
            dims=self.dims,
            provider_kind="local_unix",
            query_prefix=self.query_prefix,
        )

    def _rpc(self, payload: dict[str, Any]) -> dict[str, Any]:
        encoded = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(self.timeout_seconds)
            client.connect(os.path.expanduser(self.socket_path))
            client.sendall(encoded)
            raw = client.makefile("rb").readline(16 << 20)
        if not raw:
            raise ConnectionError("local embedding daemon closed connection without a reply")
        try:
            reply = json.loads(raw)
        except ValueError as exc:
            raise ValueError("local embedding daemon returned malformed JSON") from exc
        if not isinstance(reply, dict):
            raise ValueError("local embedding daemon reply must be a JSON object")
        if "error" in reply:
            raise RuntimeError(f"local embedding daemon error: {reply['error']}")
        return reply

    def _check_reply_space(self, reply: dict[str, Any]) -> None:
        if not self.verify_space:
            return
        reply_model = reply.get("model")
        reply_dims = reply.get("dimensions")
        if isinstance(reply_model, str) and reply_model and reply_model != self.model:
            raise VectorSpaceMismatchError(
                f"Local embedding daemon serves {reply_model!r}, expected {self.model!r}."
            )
        if type(reply_dims) is int and reply_dims != self.dims:
            raise VectorSpaceMismatchError(
                f"Local embedding daemon returned dims={reply_dims}, expected {self.dims}."
            )

    def health(self) -> dict[str, Any]:
        reply = self._rpc({"op": "health"})
        if self.verify_space:
            reply_model = reply.get("model")
            reply_dims = reply.get("dimensions")
            if isinstance(reply_model, str) and reply_model and reply_model != self.model:
                raise VectorSpaceMismatchError(
                    f"Local embedding daemon serves {reply_model!r}, expected {self.model!r}."
                )
            if type(reply_dims) is int and reply_dims < self.dims:
                raise VectorSpaceMismatchError(
                    f"Local embedding daemon max dims={reply_dims} < required {self.dims}."
                )
        return reply

    def _embed_one(self, text: str, *, sensitive: bool) -> list[float]:
        if not isinstance(text, str) or not text:
            raise ValueError("embedding input must be a non-empty string")
        reply = self._rpc(
            {
                "op": "embed",
                "input": text,
                "model": self.model,
                "dimensions": self.dims,
                "sensitive": sensitive,
            }
        )
        self._check_reply_space(reply)
        raw_vec = reply.get("embedding")
        if not isinstance(raw_vec, list):
            raise ValueError("local embedding daemon response missing embedding vector")
        return _normalize_l2(raw_vec, self.dims)

    def embed(self, text: str) -> list[float]:
        return self._embed_one(text, sensitive=False)

    def embed_sensitive(self, text: str) -> list[float]:
        return self._embed_one(text, sensitive=True)

    def embed_many(self, texts: Sequence[str], *, sensitive: bool = False) -> list[list[float]]:
        items = list(texts)
        if not items:
            return []
        if any(not isinstance(item, str) or not item for item in items):
            raise ValueError("embedding batch inputs must be non-empty strings")
        step = max(1, int(self.max_batch))
        out: list[list[float]] = []
        for start in range(0, len(items), step):
            chunk = items[start : start + step]
            reply = self._rpc(
                {
                    "op": "embed",
                    "input": chunk,
                    "model": self.model,
                    "dimensions": self.dims,
                    "sensitive": sensitive,
                }
            )
            self._check_reply_space(reply)
            data = reply.get("data")
            if not isinstance(data, list) or len(data) != len(chunk):
                raise ValueError("local embedding daemon returned mismatched batch size")
            ordered = sorted(data, key=lambda row: int(row["index"]))
            for expected_idx, row in enumerate(ordered):
                if int(row.get("index", -1)) != expected_idx:
                    raise ValueError("local embedding daemon returned out-of-order batch indices")
                out.append(_normalize_l2(row["embedding"], self.dims))
        return out

    def embed_query(self, query: str) -> list[float]:
        prefix = self.query_prefix
        text = query if (not prefix or query.startswith(prefix)) else prefix + query
        return self.embed(text)

    def embed_query_sensitive(self, query: str) -> list[float]:
        prefix = self.query_prefix
        text = query if (not prefix or query.startswith(prefix)) else prefix + query
        return self.embed_sensitive(text)


OPENROUTER_QWEN3_8B_MODEL = "qwen/qwen3-embedding-8b"
OPENROUTER_QWEN3_8B_URL = "https://openrouter.ai/api/v1/embeddings"
OPENROUTER_QWEN3_8B_QUERY_PREFIX = (
    "Instruct: Given a query, retrieve relevant passages that answer the query\nQuery: "
)
OPENROUTER_QWEN3_MRL_DIMS = (4096, 2048, 1024, 512, 256)


def build_openrouter_mrl_provider(
    *,
    api_key: str,
    dims: int = 4096,
    model: str = OPENROUTER_QWEN3_8B_MODEL,
    url: str = OPENROUTER_QWEN3_8B_URL,
    cache_path: str | None = None,
    tenant_id: str = "personal",
    timeout_seconds: float = 60.0,
    provider_order: Sequence[str] = ("SiliconFlow", "Nebius"),
) -> tuple[Any, VectorSpaceIdentity]:
    """Build an OpenRouter Qwen3-8B provider (4096-d legacy or opt-in MRL-1024) with isolated scope."""
    from mnemosyne.retrieval import HttpEmbeddingProvider

    if model == OPENROUTER_QWEN3_8B_MODEL and dims not in OPENROUTER_QWEN3_MRL_DIMS:
        raise ValueError(
            f"Unsupported Qwen3-8B MRL dimension {dims}; expected one of {OPENROUTER_QWEN3_MRL_DIMS}"
        )
    space = VectorSpaceIdentity(
        model=model,
        dims=dims,
        provider_kind="openrouter",
        query_prefix=OPENROUTER_QWEN3_8B_QUERY_PREFIX,
    )
    extra: dict[str, Any] = {
        "provider": {"order": list(provider_order), "allow_fallbacks": True},
    }
    if dims != 4096:
        extra["dimensions"] = dims
    provider = HttpEmbeddingProvider(
        url,
        model=model,
        api_key=api_key,
        dims=dims,
        query_prefix=space.query_prefix,
        timeout_seconds=timeout_seconds,
        cache_path=cache_path,
        cache_scope=space.cache_scope(tenant_id),
        extra_body_json=json.dumps(extra, separators=(",", ":")),
    )
    return provider, space


class ScopedQueryEmbeddingProvider:
    """Share query work inside one facade, optionally using an owner's cache.

    Supports thread-safe in-flight deduplication so background query prefetch
    and downstream wiki/vector retrieval share a single provider call. Source
    embeddings retain the wrapped provider's public/private policy; private
    page content is never entered into this query cache. Cache entries are
    scoped by vector space (model + dims) so switching models never mixes vectors.
    """

    _MAX_QUERIES = 256

    def __init__(self, provider, *, owner_query_cache=False):
        self.provider = provider
        self.owner_query_cache = owner_query_cache
        self._queries: OrderedDict[tuple[str, str], tuple[float, ...]] = OrderedDict()
        self._lock = threading.Lock()
        self._inflight: dict[tuple[str, str], threading.Event] = {}
        self._prefetch_pool: ThreadPoolExecutor | None = None

    def __getattr__(self, name):
        return getattr(self.provider, name)

    @property
    def vector_space(self) -> VectorSpaceIdentity | None:
        space = getattr(self.provider, "vector_space", None)
        if isinstance(space, VectorSpaceIdentity):
            return space
        model = getattr(self.provider, "model", None) or getattr(self.provider, "name", None)
        dims = getattr(self.provider, "dims", None)
        if isinstance(model, str) and model and type(dims) is int and dims > 0:
            return VectorSpaceIdentity(
                model=model,
                dims=dims,
                query_prefix=str(getattr(self.provider, "query_prefix", "") or ""),
            )
        return None

    def _space_key(self) -> str:
        space = self.vector_space
        if space is not None:
            return space.space_id
        return f"{getattr(self.provider, 'model', '')}@{getattr(self.provider, 'dims', '')}"

    def embed(self, text):
        return self.provider.embed(text)

    def embed_sensitive(self, text):
        return self.provider.embed_sensitive(text)

    def embed_many(self, texts: Sequence[str]):
        if hasattr(self.provider, "embed_many"):
            return self.provider.embed_many(texts)
        return [self.provider.embed(text) for text in texts]

    def _prefixed(self, text: str) -> str:
        prefix = getattr(self.provider, "query_prefix", "")
        return text if prefix and text.startswith(prefix) else prefix + text

    def _query(self, text: str) -> list[float]:
        cache_key = (self._space_key(), text)
        while True:
            with self._lock:
                cached = self._queries.get(cache_key)
                if cached is not None:
                    self._queries.move_to_end(cache_key)
                    return list(cached)
                wait_event = self._inflight.get(cache_key)
                if wait_event is None:
                    wait_event = threading.Event()
                    self._inflight[cache_key] = wait_event
                    owner = True
                else:
                    owner = False
            if not owner:
                wait_event.wait()
                continue
            try:
                # A single-owner authenticated host may opt into its existing
                # owner-scoped query cache. Source/page text never uses this path.
                embed = self.provider.embed if self.owner_query_cache else self.provider.embed_sensitive
                vec = tuple(embed(text))
                with self._lock:
                    self._queries[cache_key] = vec
                    self._queries.move_to_end(cache_key)
                    while len(self._queries) > self._MAX_QUERIES:
                        self._queries.popitem(last=False)
                return list(vec)
            finally:
                with self._lock:
                    self._inflight.pop(cache_key, None)
                    wait_event.set()

    def prefetch_query(self, text: str) -> None:
        """Start fetching a query vector in the background while local work runs."""
        if not isinstance(text, str) or not text.strip():
            return
        prefixed = self._prefixed(text)
        cache_key = (self._space_key(), prefixed)
        with self._lock:
            if cache_key in self._queries or cache_key in self._inflight:
                return
            if self._prefetch_pool is None:
                self._prefetch_pool = ThreadPoolExecutor(
                    max_workers=2, thread_name_prefix="query-embed-prefetch"
                )
            pool = self._prefetch_pool

        def _run() -> None:
            try:
                self._query(prefixed)
            except Exception:
                # Never surface background errors; foreground callers retry and handle them.
                pass

        pool.submit(_run)

    def embed_query(self, text):
        return self._query(self._prefixed(text))

    def embed_query_sensitive(self, text):
        """Explicit query channel; source strings can never impersonate it."""
        return self.embed_query(text)

    def close(self) -> None:
        with self._lock:
            pool = self._prefetch_pool
            self._prefetch_pool = None
        if pool is not None:
            pool.shutdown(wait=False)
