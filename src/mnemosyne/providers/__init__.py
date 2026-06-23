"""Pluggable retrieval-provider surface and registry.

The blueprint frames the engine as a *pluggable contract* with adapters that
"swap in specialists at scale" (§0, §30.1, §35). The concrete adapter
implementations live in :mod:`mnemosyne.retrieval` (the engine's import home);
this package is the **organized, extensible public surface** over them:

* it re-exports the provider protocols and concrete adapters so callers can
  ``from mnemosyne.providers import HttpEmbeddingProvider`` instead of reaching
  into the retrieval internals;
* it adds a :class:`ProviderRegistry` so a deployment can register a *new*
  embedding / reranker / lexical / graph provider by name and build
  :class:`RetrievalAdapters` from a plain config mapping, without editing engine
  code — the "swap a backend without touching the agent" property.

The built-in registry reproduces, exactly, the provider selection performed by
:func:`mnemosyne.retrieval.retrieval_adapters_from_env`, so the env-driven and
config-driven construction paths stay behaviorally aligned (guarded by tests).
This is an additive layer: it imports from :mod:`mnemosyne.retrieval` one-way
and never mutates it, so every existing import site is unaffected.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Callable

from mnemosyne.retrieval import (
    CommandGraphRetriever,
    CommandLexicalRetriever,
    CommandMediaEmbeddingProvider,
    EmbeddingProvider,
    GraphRetriever,
    HashingEmbeddingProvider,
    HttpEmbeddingProvider,
    HttpReranker,
    LexicalRetriever,
    LocalSimilarityReranker,
    MediaEmbeddingProvider,
    Reranker,
    RetrievalAdapters,
    retrieval_adapters_from_env,
)

__all__ = [
    # Protocols (boundaries)
    "EmbeddingProvider",
    "MediaEmbeddingProvider",
    "Reranker",
    "LexicalRetriever",
    "GraphRetriever",
    # Concrete adapters
    "HashingEmbeddingProvider",
    "LocalSimilarityReranker",
    "HttpEmbeddingProvider",
    "HttpReranker",
    "CommandLexicalRetriever",
    "CommandGraphRetriever",
    "CommandMediaEmbeddingProvider",
    # Adapter bundle + env convenience
    "RetrievalAdapters",
    "retrieval_adapters_from_env",
    # Registry-driven construction
    "ProviderRegistry",
    "default_registry",
    "build_adapters_from_config",
]

# A provider factory receives the (already-defaulted) config mapping and returns
# a constructed provider. Lexical/graph factories may return ``None`` to signal
# "use the engine-native (Postgres) channel".
EmbeddingFactory = Callable[[Mapping[str, Any]], EmbeddingProvider]
RerankerFactory = Callable[[Mapping[str, Any]], Reranker]
LexicalFactory = Callable[[Mapping[str, Any]], "LexicalRetriever | None"]
GraphFactory = Callable[[Mapping[str, Any]], "GraphRetriever | None"]


def _as_int(value: Any, *, default: int) -> int:
    if value is None:
        return default
    return int(value)


def _as_float(value: Any, *, default: float) -> float:
    if value is None:
        return default
    return float(value)


def _require(config: Mapping[str, Any], key: str, *, role: str) -> str:
    value = config.get(key)
    if not value:
        raise ValueError(f"{key} is required for the {role} provider")
    return str(value)


# --------------------------------------------------------------------------- #
# Built-in factories (mirror retrieval_adapters_from_env exactly)
# --------------------------------------------------------------------------- #


def _build_http_embedding(config: Mapping[str, Any]) -> EmbeddingProvider:
    return HttpEmbeddingProvider(
        url=_require(config, "embedding_url", role="http embedding"),
        model=config.get("embedding_model"),
        api_key=config.get("embedding_api_key"),
        dims=_as_int(config.get("embedding_dims"), default=1024),
        timeout_seconds=_as_float(config.get("retrieval_timeout"), default=30.0),
    )


def _build_local_embedding(config: Mapping[str, Any]) -> EmbeddingProvider:
    return HashingEmbeddingProvider(dims=_as_int(config.get("embedding_dims"), default=1024))


def _build_http_reranker(config: Mapping[str, Any]) -> Reranker:
    return HttpReranker(
        url=_require(config, "reranker_url", role="http reranker"),
        model=config.get("reranker_model"),
        api_key=config.get("reranker_api_key"),
        timeout_seconds=_as_float(config.get("retrieval_timeout"), default=30.0),
    )


def _build_local_reranker(config: Mapping[str, Any]) -> Reranker:
    # ``EmbeddingProvider`` is a non-runtime-checkable Protocol, so we cannot
    # ``isinstance``-check it. The builder always injects the constructed
    # embedding under ``_embedding``; bind it when present, else use the default.
    embedding = config.get("_embedding")
    if embedding is not None:
        return LocalSimilarityReranker(embedding_provider=embedding)
    return LocalSimilarityReranker()


def _build_command_lexical(config: Mapping[str, Any]) -> LexicalRetriever | None:
    return CommandLexicalRetriever(
        _require(config, "lexical_command", role="command lexical"),
        backend=str(config.get("lexical_backend") or "postgres-fts"),
        timeout_seconds=_as_float(config.get("retrieval_timeout"), default=30.0),
    )


def _build_native_lexical(_config: Mapping[str, Any]) -> LexicalRetriever | None:
    return None


def _build_command_graph(config: Mapping[str, Any]) -> GraphRetriever | None:
    return CommandGraphRetriever(
        _require(config, "graph_command", role="command graph"),
        backend=str(config.get("graph_backend") or "postgres-recursive-ppr"),
        timeout_seconds=_as_float(config.get("retrieval_timeout"), default=30.0),
    )


def _build_native_graph(_config: Mapping[str, Any]) -> GraphRetriever | None:
    return None


@dataclass(slots=True)
class ProviderRegistry:
    """Name → factory tables for each retrieval provider boundary.

    Use :func:`default_registry` for the built-in set, then ``register_*`` to add
    deployment-specific providers before calling :func:`build_adapters_from_config`.
    """

    embedding: dict[str, EmbeddingFactory] = field(default_factory=dict)
    reranker: dict[str, RerankerFactory] = field(default_factory=dict)
    lexical: dict[str, LexicalFactory] = field(default_factory=dict)
    graph: dict[str, GraphFactory] = field(default_factory=dict)

    def register_embedding_provider(self, name: str, factory: EmbeddingFactory) -> None:
        self.embedding[name.lower()] = factory

    def register_reranker(self, name: str, factory: RerankerFactory) -> None:
        self.reranker[name.lower()] = factory

    def register_lexical_provider(self, name: str, factory: LexicalFactory) -> None:
        self.lexical[name.lower()] = factory

    def register_graph_provider(self, name: str, factory: GraphFactory) -> None:
        self.graph[name.lower()] = factory


def default_registry() -> ProviderRegistry:
    """Return a fresh registry pre-populated with the built-in providers."""

    registry = ProviderRegistry()
    for name in ("local", "local-hashing", "hashing"):
        registry.register_embedding_provider(name, _build_local_embedding)
    registry.register_embedding_provider("http", _build_http_embedding)
    for name in ("local", "local-similarity"):
        registry.register_reranker(name, _build_local_reranker)
    registry.register_reranker("http", _build_http_reranker)
    for name in ("postgres", "native"):
        registry.register_lexical_provider(name, _build_native_lexical)
        registry.register_graph_provider(name, _build_native_graph)
    registry.register_lexical_provider("command", _build_command_lexical)
    registry.register_graph_provider("command", _build_command_graph)
    return registry


def build_adapters_from_config(
    config: Mapping[str, Any] | None = None,
    *,
    registry: ProviderRegistry | None = None,
) -> RetrievalAdapters:
    """Build :class:`RetrievalAdapters` from a plain config mapping via a registry.

    Recognized keys (all optional, defaults match the env builder):
    ``embedding_provider`` (default ``"local"``), ``embedding_dims`` (1024),
    ``embedding_url`` / ``embedding_model`` / ``embedding_api_key``;
    ``reranker_provider`` (``"local"``), ``reranker_url`` / ``reranker_model`` /
    ``reranker_api_key``; ``lexical_provider`` (``"postgres"``),
    ``lexical_command`` / ``lexical_backend`` (``"postgres-fts"``);
    ``graph_provider`` (``"postgres"``), ``graph_command`` / ``graph_backend``
    (``"postgres-recursive-ppr"``); ``retrieval_timeout`` (30.0).
    """

    config = dict(config or {})
    registry = registry or default_registry()

    embedding_name = str(config.get("embedding_provider", "local")).lower()
    embedding_factory = registry.embedding.get(embedding_name)
    if embedding_factory is None:
        raise ValueError(f"unsupported embedding provider: {embedding_name}")
    embedding = embedding_factory(config)

    reranker_name = str(config.get("reranker_provider", "local")).lower()
    reranker_factory = registry.reranker.get(reranker_name)
    if reranker_factory is None:
        raise ValueError(f"unsupported reranker provider: {reranker_name}")
    reranker = reranker_factory({**config, "_embedding": embedding})

    lexical_name = str(config.get("lexical_provider", "postgres")).lower()
    lexical_factory = registry.lexical.get(lexical_name)
    if lexical_factory is None:
        raise ValueError(f"unsupported lexical provider: {lexical_name}")
    lexical_retriever = lexical_factory(config)

    graph_name = str(config.get("graph_provider", "postgres")).lower()
    graph_factory = registry.graph.get(graph_name)
    if graph_factory is None:
        raise ValueError(f"unsupported graph provider: {graph_name}")
    graph_retriever = graph_factory(config)

    return RetrievalAdapters(
        embedding=embedding,
        reranker=reranker,
        lexical_backend=str(config.get("lexical_backend", "postgres-fts")),
        graph_backend=str(config.get("graph_backend", "postgres-recursive-ppr")),
        lexical_retriever=lexical_retriever,
        graph_retriever=graph_retriever,
    )
