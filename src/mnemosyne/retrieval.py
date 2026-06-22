"""Retrieval adapter boundaries and local deterministic fallbacks."""

from __future__ import annotations

import json
import math
import os
import shlex
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping, Protocol, Sequence

from mnemosyne.models import Hit, parse_dt, utc_now
from mnemosyne.policy import OperatingPolicy
from mnemosyne.security import trust_weight
from mnemosyne.text import cosine, hashing_embedding, lexical_score, tokenize


class EmbeddingProvider(Protocol):
    """Boundary for production embedding models.

    The blueprint calls for a real dense embedding provider. This protocol keeps
    that integration explicit while tests and local development use a
    deterministic provider that has no network dependency.
    """

    name: str
    dims: int

    def embed(self, text: str) -> list[float]:
        """Return a normalized embedding vector for text."""


class MediaEmbeddingProvider(Protocol):
    """Boundary for image/audio/video embedding providers."""

    name: str
    dims: int

    def embed_media(
        self,
        payload: bytes,
        *,
        media_type: str,
        modality: str,
        metadata: dict[str, object] | None = None,
    ) -> list[float]:
        """Return a normalized embedding vector for raw media bytes."""


class Reranker(Protocol):
    """Boundary for production cross-encoder or LLM rerankers."""

    name: str

    def rerank(self, query: str, hits: Sequence[Hit], k: int) -> list[Hit]:
        """Return the top-k hits after reranking."""


class LexicalRetriever(Protocol):
    """Boundary for production lexical/BM25 retrieval backends."""

    name: str

    def search(
        self,
        query: str,
        *,
        tenant_id: str,
        branch: str,
        k: int,
        filt: Mapping[str, object] | None = None,
    ) -> list[Hit]:
        """Return lexical hits for a tenant-scoped query."""


class GraphRetriever(Protocol):
    """Boundary for production graph/PPR retrieval backends."""

    name: str

    def search(
        self,
        seeds: Sequence[str],
        *,
        tenant_id: str,
        branch: str,
        k: int,
        as_of: datetime | None = None,
    ) -> list[Hit]:
        """Return graph hits for tenant-scoped seed terms."""


def _run_json_command(
    command: Sequence[str],
    payload: Mapping[str, object],
    *,
    timeout_seconds: float,
    role: str,
) -> Mapping[str, Any]:
    try:
        completed = subprocess.run(
            list(command),
            input=json.dumps(payload),
            check=True,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"{role} command timed out") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()[:512]
        suffix = f": {detail}" if detail else ""
        raise ValueError(f"{role} command failed{suffix}") from exc
    output = completed.stdout.strip()
    if not output:
        raise ValueError(f"{role} command returned no JSON")
    if len(output.encode("utf-8")) > 1_048_576:
        raise ValueError(f"{role} command response exceeded 1 MiB")
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{role} command response must be valid JSON") from exc
    if not isinstance(parsed, Mapping):
        raise ValueError(f"{role} command response must be a JSON object")
    return parsed


def _command_int(value: object, *, default: int, field: str) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError(f"hit field {field} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"hit field {field} must be an integer") from exc


def _command_provenance(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("hit field provenance must be an array")
    return [str(item) for item in value if str(item)]


def _command_hit(
    item: object,
    *,
    tenant_id: str,
    branch: str,
    default_channel: str,
    backend: str,
) -> Hit:
    if not isinstance(item, Mapping):
        raise ValueError("retrieval command hits must contain JSON objects")
    hit_id = str(item.get("id") or "").strip()
    text = str(item.get("text") or "").strip()
    if not hit_id:
        raise ValueError("retrieval command hit requires id")
    if not text:
        raise ValueError("retrieval command hit requires text")
    kind = str(item.get("kind") or "evidence")
    if kind not in {"evidence", "assertion", "relation", "preference"}:
        raise ValueError(f"retrieval command hit kind {kind!r} is not supported")
    score_raw = item.get("score")
    if isinstance(score_raw, bool):
        raise ValueError("retrieval command hit score must be numeric")
    try:
        score = float(score_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("retrieval command hit score must be numeric") from exc
    if not math.isfinite(score):
        raise ValueError("retrieval command hit score must be finite")
    metadata_raw = item.get("metadata")
    metadata = dict(metadata_raw) if isinstance(metadata_raw, Mapping) else {}
    metadata.setdefault("backend", backend)
    metadata["command_retrieval"] = True
    return Hit(
        id=hit_id,
        kind=kind,  # type: ignore[arg-type]
        tenant_id=str(item.get("tenant_id") or tenant_id),
        branch=str(item.get("branch") or branch),
        text=text,
        score=score,
        channel=str(item.get("channel") or default_channel),
        provenance=_command_provenance(item.get("provenance")),
        trust_tier=_command_int(item.get("trust_tier"), default=0, field="trust_tier"),
        sensitivity=_command_int(item.get("sensitivity"), default=0, field="sensitivity"),
        metadata=metadata,
    )


def _command_hits(
    parsed: Mapping[str, Any],
    *,
    tenant_id: str,
    branch: str,
    k: int,
    default_channel: str,
    backend: str,
) -> list[Hit]:
    raw_hits = parsed.get("hits")
    if not isinstance(raw_hits, list):
        raise ValueError("retrieval command response requires hits array")
    hits = [
        _command_hit(item, tenant_id=tenant_id, branch=branch, default_channel=default_channel, backend=backend)
        for item in raw_hits
    ]
    return sorted(hits, key=lambda item: item.score, reverse=True)[: max(k, 0)]


@dataclass(frozen=True, slots=True)
class HashingEmbeddingProvider:
    """Local embedding provider with deterministic hashing vectors."""

    dims: int = 256
    name: str = "local-hashing"

    def embed(self, text: str) -> list[float]:
        return hashing_embedding(text, dims=self.dims)


@dataclass(frozen=True, slots=True)
class LocalSimilarityReranker:
    """Dependency-free reranker using lexical and deterministic dense signals."""

    embedding_provider: EmbeddingProvider = HashingEmbeddingProvider()
    lexical_weight: float = 0.55
    dense_weight: float = 0.45
    name: str = "local-similarity"

    def rerank(self, query: str, hits: Sequence[Hit], k: int) -> list[Hit]:
        query_vec = self.embedding_provider.embed(query)
        scored: list[Hit] = []
        for hit in hits:
            dense = cosine(query_vec, self.embedding_provider.embed(hit.text))
            lexical = lexical_score(query, hit.text)
            clone = Hit(
                id=hit.id,
                kind=hit.kind,
                tenant_id=hit.tenant_id,
                branch=hit.branch,
                text=hit.text,
                score=max(0.0, self.lexical_weight * lexical + self.dense_weight * dense),
                channel=f"{hit.channel}+rerank",
                provenance=list(hit.provenance),
                trust_tier=hit.trust_tier,
                sensitivity=hit.sensitivity,
                metadata={**hit.metadata, "reranker": self.name},
            )
            scored.append(clone)
        return sorted(scored, key=lambda item: item.score, reverse=True)[:k]


@dataclass(frozen=True, slots=True)
class HttpEmbeddingProvider:
    """HTTP JSON embedding provider for managed or self-hosted models.

    The adapter accepts OpenAI-style responses (`data[0].embedding`) and a
    compact generic shape (`embedding`). Vectors are Matryoshka-truncated or
    zero-padded to the configured target dimension, then normalized.
    """

    url: str
    model: str | None = None
    api_key: str | None = None
    dims: int = 1024
    timeout_seconds: float = 30.0
    name: str = "http-embedding"

    def embed(self, text: str) -> list[float]:
        payload: dict[str, object] = {"input": text}
        if self.model:
            payload["model"] = self.model
        response = _post_json(self.url, payload, self.api_key, self.timeout_seconds)
        vector = _extract_embedding(response)
        return _normalize_vector(vector, self.dims)


class CommandMediaEmbeddingProvider:
    """Shell-free command adapter for operator-managed multimodal embedders.

    The command is invoked as `<command> <tmp-media-path>` with JSON metadata on
    stdin. It must write a JSON object containing `embedding` or
    `data[0].embedding` to stdout.
    """

    name = "command-media-embedding"

    def __init__(self, command: str | Sequence[str], *, dims: int = 1024, timeout_seconds: float = 30.0):
        self.command = shlex.split(command) if isinstance(command, str) else list(command)
        if not self.command:
            raise ValueError("media embedding command must not be empty")
        if dims <= 0:
            raise ValueError("media embedding dimensions must be positive")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("media embedding timeout must be positive")
        self.dims = dims
        self.timeout_seconds = timeout_seconds

    def embed_media(
        self,
        payload: bytes,
        *,
        media_type: str,
        modality: str,
        metadata: dict[str, object] | None = None,
    ) -> list[float]:
        with tempfile.NamedTemporaryFile() as tmp:
            tmp.write(payload)
            tmp.flush()
            request = {
                "path": tmp.name,
                "media_type": media_type,
                "modality": modality,
                "metadata": metadata or {},
            }
            try:
                completed = subprocess.run(
                    [*self.command, tmp.name],
                    input=json.dumps(request),
                    check=True,
                    text=True,
                    capture_output=True,
                    timeout=self.timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                raise ValueError("media embedding command timed out") from exc
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or exc.stdout or "").strip()[:512]
                suffix = f": {detail}" if detail else ""
                raise ValueError(f"media embedding command failed{suffix}") from exc
        output = completed.stdout.strip()
        if not output:
            raise ValueError("media embedding command returned no JSON")
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError as exc:
            raise ValueError("media embedding response must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("media embedding response must be a JSON object")
        return _normalize_vector(_extract_embedding(parsed), self.dims)


class CommandLexicalRetriever:
    """Shell-free command adapter for production lexical/BM25 retrieval.

    The command receives a JSON request on stdin and must return
    `{"hits": [...]}`. Deployments can back the command with ParadeDB BM25,
    another Postgres extension, or a managed lexical retrieval service without
    changing the Mnemosyne engine contract.
    """

    name = "command-lexical-retriever"

    def __init__(
        self,
        command: str | Sequence[str],
        *,
        backend: str = "command-lexical",
        timeout_seconds: float = 30.0,
    ):
        self.command = shlex.split(command) if isinstance(command, str) else list(command)
        if not self.command:
            raise ValueError("lexical retrieval command must not be empty")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("lexical retrieval timeout must be positive")
        self.backend = backend
        self.timeout_seconds = timeout_seconds

    def search(
        self,
        query: str,
        *,
        tenant_id: str,
        branch: str,
        k: int,
        filt: Mapping[str, object] | None = None,
    ) -> list[Hit]:
        payload: dict[str, object] = {
            "role": "lexical_search",
            "query": query,
            "tenant_id": tenant_id,
            "branch": branch,
            "k": k,
            "filter": dict(filt or {}),
        }
        parsed = _run_json_command(
            self.command,
            payload,
            timeout_seconds=self.timeout_seconds,
            role="lexical retrieval",
        )
        return _command_hits(
            parsed,
            tenant_id=tenant_id,
            branch=branch,
            k=k,
            default_channel="command_lexical",
            backend=self.backend,
        )


class CommandGraphRetriever:
    """Shell-free command adapter for production specialist graph retrieval."""

    name = "command-graph-retriever"

    def __init__(
        self,
        command: str | Sequence[str],
        *,
        backend: str = "command-graph",
        timeout_seconds: float = 30.0,
    ):
        self.command = shlex.split(command) if isinstance(command, str) else list(command)
        if not self.command:
            raise ValueError("graph retrieval command must not be empty")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("graph retrieval timeout must be positive")
        self.backend = backend
        self.timeout_seconds = timeout_seconds

    def search(
        self,
        seeds: Sequence[str],
        *,
        tenant_id: str,
        branch: str,
        k: int,
        as_of: datetime | None = None,
    ) -> list[Hit]:
        payload: dict[str, object] = {
            "role": "graph_ppr",
            "seeds": [str(seed) for seed in seeds],
            "tenant_id": tenant_id,
            "branch": branch,
            "k": k,
        }
        if as_of is not None:
            payload["as_of"] = as_of.isoformat()
        parsed = _run_json_command(
            self.command,
            payload,
            timeout_seconds=self.timeout_seconds,
            role="graph retrieval",
        )
        return _command_hits(
            parsed,
            tenant_id=tenant_id,
            branch=branch,
            k=k,
            default_channel="command_graph_ppr",
            backend=self.backend,
        )


@dataclass(frozen=True, slots=True)
class HttpReranker:
    """HTTP JSON reranker for cross-encoder-style providers.

    The adapter accepts Cohere-style responses (`results[{index, relevance_score}]`)
    and a compact generic shape (`results[{index, score}]`).
    """

    url: str
    model: str | None = None
    api_key: str | None = None
    timeout_seconds: float = 30.0
    name: str = "http-reranker"

    def rerank(self, query: str, hits: Sequence[Hit], k: int) -> list[Hit]:
        if k <= 0 or not hits:
            return []
        documents = [hit.text for hit in hits]
        payload: dict[str, object] = {"query": query, "documents": documents, "top_n": k}
        if self.model:
            payload["model"] = self.model
        response = _post_json(self.url, payload, self.api_key, self.timeout_seconds)
        scored = _extract_rerank_scores(response)
        ranked: list[Hit] = []
        seen: set[int] = set()
        for index, score in scored:
            if index < 0 or index >= len(hits):
                raise ValueError(f"reranker response index {index} is out of range")
            if index in seen:
                raise ValueError(f"reranker response contains duplicate index {index}")
            seen.add(index)
            hit = hits[index]
            ranked.append(
                Hit(
                    id=hit.id,
                    kind=hit.kind,
                    tenant_id=hit.tenant_id,
                    branch=hit.branch,
                    text=hit.text,
                    score=float(score),
                    channel=f"{hit.channel}+rerank",
                    provenance=list(hit.provenance),
                    trust_tier=hit.trust_tier,
                    sensitivity=hit.sensitivity,
                    metadata={**hit.metadata, "reranker": self.name},
                )
            )
        return sorted(ranked, key=lambda item: item.score, reverse=True)[:k]


@dataclass(frozen=True, slots=True)
class RetrievalAdapters:
    """Configured retrieval boundaries used by runtime implementations."""

    embedding: EmbeddingProvider = HashingEmbeddingProvider()
    reranker: Reranker = LocalSimilarityReranker()
    lexical_backend: str = "local-bm25-lite"
    graph_backend: str = "local-ppr"
    lexical_retriever: LexicalRetriever | None = None
    graph_retriever: GraphRetriever | None = None


def retrieval_adapters_from_env(prefix: str = "MNEMOSYNE") -> RetrievalAdapters:
    """Build retrieval adapters from environment variables.

    Supported provider values:
    - `{prefix}_EMBEDDING_PROVIDER=local|http`
    - `{prefix}_RERANKER_PROVIDER=local|http`
    - `{prefix}_LEXICAL_PROVIDER=postgres|command`
    - `{prefix}_GRAPH_PROVIDER=postgres|command`
    """

    embedding_provider = os.environ.get(f"{prefix}_EMBEDDING_PROVIDER", "local").lower()
    reranker_provider = os.environ.get(f"{prefix}_RERANKER_PROVIDER", "local").lower()
    lexical_provider = os.environ.get(f"{prefix}_LEXICAL_PROVIDER", "postgres").lower()
    graph_provider = os.environ.get(f"{prefix}_GRAPH_PROVIDER", "postgres").lower()
    dims = int(os.environ.get(f"{prefix}_EMBEDDING_DIMS", "1024"))
    timeout = float(os.environ.get(f"{prefix}_RETRIEVAL_TIMEOUT", "30"))
    if embedding_provider == "http":
        embedding = HttpEmbeddingProvider(
            url=_required_env(f"{prefix}_EMBEDDING_URL"),
            model=os.environ.get(f"{prefix}_EMBEDDING_MODEL"),
            api_key=os.environ.get(f"{prefix}_EMBEDDING_API_KEY"),
            dims=dims,
            timeout_seconds=timeout,
        )
    elif embedding_provider in {"local", "local-hashing", "hashing"}:
        embedding = HashingEmbeddingProvider(dims=dims)
    else:
        raise ValueError(f"unsupported embedding provider: {embedding_provider}")

    if reranker_provider == "http":
        reranker: Reranker = HttpReranker(
            url=_required_env(f"{prefix}_RERANKER_URL"),
            model=os.environ.get(f"{prefix}_RERANKER_MODEL"),
            api_key=os.environ.get(f"{prefix}_RERANKER_API_KEY"),
            timeout_seconds=timeout,
        )
    elif reranker_provider in {"local", "local-similarity"}:
        reranker = LocalSimilarityReranker(embedding_provider=embedding)
    else:
        raise ValueError(f"unsupported reranker provider: {reranker_provider}")

    lexical_backend = os.environ.get(f"{prefix}_LEXICAL_BACKEND", "postgres-fts")
    graph_backend = os.environ.get(f"{prefix}_GRAPH_BACKEND", "postgres-recursive-ppr")
    if lexical_provider == "command":
        lexical_retriever: LexicalRetriever | None = CommandLexicalRetriever(
            _required_env(f"{prefix}_LEXICAL_COMMAND"),
            backend=lexical_backend,
            timeout_seconds=timeout,
        )
    elif lexical_provider in {"postgres", "native"}:
        lexical_retriever = None
    else:
        raise ValueError(f"unsupported lexical provider: {lexical_provider}")

    if graph_provider == "command":
        graph_retriever: GraphRetriever | None = CommandGraphRetriever(
            _required_env(f"{prefix}_GRAPH_COMMAND"),
            backend=graph_backend,
            timeout_seconds=timeout,
        )
    elif graph_provider in {"postgres", "native"}:
        graph_retriever = None
    else:
        raise ValueError(f"unsupported graph provider: {graph_provider}")

    return RetrievalAdapters(
        embedding=embedding,
        reranker=reranker,
        lexical_backend=lexical_backend,
        graph_backend=graph_backend,
        lexical_retriever=lexical_retriever,
        graph_retriever=graph_retriever,
    )


def semantic_entropy(alternatives: Sequence[str]) -> float:
    """Estimate answer uncertainty from lexical clusters of alternatives.

    This is not a substitute for model-logprob entropy. It is a deterministic
    local signal for tests, abstention explanations, and offline canary runs.
    Identical alternatives produce zero entropy; divergent alternatives increase
    toward one.
    """

    normalized = [" ".join(tokenize(item)) for item in alternatives if tokenize(item)]
    if len(normalized) <= 1:
        return 0.0
    counts = Counter(normalized)
    total = sum(counts.values())
    if total <= 0:
        return 0.0
    entropy = -sum((count / total) * math.log(count / total, 2) for count in counts.values())
    max_entropy = math.log(len(counts), 2) if len(counts) > 1 else 1.0
    return entropy / max_entropy if max_entropy else 0.0


def gist_support_report(hits: Sequence[Hit]) -> dict[str, object]:
    """Return whether retrieved support is only fidelity-demoted gist evidence."""

    if not hits:
        return {"applied": False, "gist_hit_ids": [], "hit_count": 0}
    gist_ids = [hit.id for hit in hits if _is_gist_hit(hit)]
    return {
        "applied": len(gist_ids) == len(hits),
        "gist_hit_ids": gist_ids,
        "hit_count": len(hits),
    }


def _is_gist_hit(hit: Hit) -> bool:
    metadata = hit.metadata if isinstance(hit.metadata, dict) else {}
    summary = metadata.get("summary")
    lifecycle = metadata.get("lifecycle")
    source_type = str(metadata.get("source_type") or "")
    relation_predicate = str(metadata.get("predicate") or "").lower()
    summary_kind = str(summary.get("kind") or "").lower() if isinstance(summary, dict) else ""
    lifecycle_tier = str(lifecycle.get("tier") or "").lower() if isinstance(lifecycle, dict) else ""
    confabulation_risk = bool(metadata.get("confabulation_risk")) or (
        isinstance(summary, dict) and bool(summary.get("confabulation_risk"))
    ) or (isinstance(lifecycle, dict) and bool(lifecycle.get("confabulation_risk")))
    return (
        summary_kind in {"abstractive_gist", "statistical_trace"}
        or lifecycle_tier in {"abstractive_gist", "statistical_trace"}
        or source_type in {"consolidation-summary", "statistical-trace"}
        or (hit.kind == "relation" and relation_predicate == "summary-derived-gist")
        or confabulation_risk
    )


def is_retired_summary_metadata(metadata: object) -> bool:
    if not isinstance(metadata, dict):
        return False
    summary = metadata.get("summary")
    if not isinstance(summary, dict):
        return False
    status = str(summary.get("status") or "").lower()
    return status in {"retired", "superseded", "stale"} or bool(
        summary.get("retired_at") or summary.get("superseded_by")
    )


def apply_activation_scores(hits: Sequence[Hit], policy: OperatingPolicy, *, now: datetime | None = None) -> list[Hit]:
    """Apply blueprint-style activation scoring to already retrieved hits."""

    if not hits:
        return []
    moment = now or utc_now()
    max_relevance = max((max(hit.score, 0.0) for hit in hits), default=0.0)
    weights = dict(policy.activation_weights)
    total_weight = max(sum(max(float(value), 0.0) for value in weights.values()), 0.01)
    activated: list[Hit] = []
    for hit in hits:
        semantic = max(hit.score, 0.0) / max(max_relevance, 0.01)
        confidence = _bounded_float(hit.metadata.get("confidence", 0.7), default=0.7)
        access_count = _bounded_int(hit.metadata.get("access_count", 0))
        base_level = min(1.0, math.log1p(access_count) / math.log(11))
        recency = _recency_score(hit.metadata.get("last_accessed"), moment, policy.decay)
        importance = confidence * trust_weight(hit.trust_tier)
        activation = (
            max(weights.get("base_level", 0.0), 0.0) * base_level
            + max(weights.get("semantic", 0.0), 0.0) * semantic
            + max(weights.get("importance", 0.0), 0.0) * importance
            + max(weights.get("recency", 0.0), 0.0) * recency
        ) / total_weight
        metadata = {
            **hit.metadata,
            "activation": {
                "score": round(max(0.0, min(1.0, activation)), 6),
                "components": {
                    "base_level": round(base_level, 6),
                    "semantic": round(semantic, 6),
                    "importance": round(importance, 6),
                    "recency": round(recency, 6),
                },
            },
        }
        activated.append(
            Hit(
                id=hit.id,
                kind=hit.kind,
                tenant_id=hit.tenant_id,
                branch=hit.branch,
                text=hit.text,
                score=max(hit.score, 0.0) * (0.5 + max(0.0, min(1.0, activation))),
                channel=hit.channel,
                provenance=list(hit.provenance),
                trust_tier=hit.trust_tier,
                sensitivity=hit.sensitivity,
                metadata=metadata,
            )
        )
    return sorted(activated, key=lambda item: item.score, reverse=True)


def activation_explain(hits: Sequence[Hit], policy: OperatingPolicy) -> dict[str, object]:
    return {
        "weights": dict(policy.activation_weights),
        "applied": True,
        "hits": [
            {
                "id": hit.id,
                "kind": hit.kind,
                "score": round(hit.score, 6),
                "activation": hit.metadata.get("activation", {}),
            }
            for hit in hits
        ],
    }


def _recency_score(value: object, now: datetime, decay: float) -> float:
    accessed = value if isinstance(value, datetime) else parse_dt(value)
    if accessed is None:
        return 0.0
    accessed = accessed.astimezone(UTC) if accessed.tzinfo else accessed.replace(tzinfo=UTC)
    age_days = max((now - accessed).total_seconds(), 0.0) / 86_400.0
    return 1.0 / (1.0 + max(decay, 0.0) * age_days)


def _bounded_float(value: object, *, default: float) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(0.0, min(1.0, number))


def _bounded_int(value: object) -> int:
    try:
        return max(0, int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _post_json(url: str, payload: dict[str, object], api_key: str | None, timeout: float) -> dict[str, object]:
    _validate_http_provider_config(url, timeout)
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL is operator-configured.
            decoded = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read(512).decode("utf-8", errors="replace").strip()
        suffix = f": {detail}" if detail else ""
        raise ValueError(f"provider returned HTTP {exc.code}{suffix}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"provider request failed: {exc.reason}") from exc
    try:
        parsed = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise ValueError("provider response must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("provider response must be a JSON object")
    return parsed


def _extract_embedding(response: dict[str, object]) -> list[float]:
    if isinstance(response.get("embedding"), list):
        return _coerce_vector(response["embedding"], field="embedding")  # type: ignore[arg-type,index]
    data = response.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict) and isinstance(data[0].get("embedding"), list):
        return _coerce_vector(data[0]["embedding"], field="data[0].embedding")
    raise ValueError("embedding response must contain `embedding` or `data[0].embedding`")


def _extract_rerank_scores(response: dict[str, object]) -> list[tuple[int, float]]:
    results = response.get("results")
    if not isinstance(results, list):
        raise ValueError("reranker response must contain `results`")
    scored: list[tuple[int, float]] = []
    for item in results:
        if not isinstance(item, dict):
            raise ValueError("reranker results must be objects")
        index = item.get("index")
        score = item.get("score", item.get("relevance_score"))
        if not isinstance(index, int) or isinstance(index, bool):
            raise ValueError("reranker result index must be an integer")
        scored.append((index, _finite_float(score, field="reranker score")))
    if not scored:
        raise ValueError("reranker response must contain at least one scored result")
    return scored


def _normalize_vector(vector: Sequence[float], dims: int) -> list[float]:
    if dims <= 0:
        raise ValueError("embedding dimensions must be positive")
    adjusted = list(vector[:dims])
    if len(adjusted) < dims:
        adjusted.extend([0.0] * (dims - len(adjusted)))
    norm = math.sqrt(sum(value * value for value in adjusted))
    if norm == 0.0:
        raise ValueError("embedding response must contain a non-zero vector")
    return [value / norm for value in adjusted]


def _validate_http_provider_config(url: str, timeout: float) -> None:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("retrieval provider timeout must be positive")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("retrieval provider URL must be absolute HTTP or HTTPS")


def _coerce_vector(values: Sequence[object], *, field: str) -> list[float]:
    if not values:
        raise ValueError(f"{field} must contain at least one value")
    return [_finite_float(value, field=field) for value in values]


def _finite_float(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} values must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} values must be finite")
    return number
