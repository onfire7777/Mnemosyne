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
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Literal

from mnemosyne.dreamer import SandboxedDreamer

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
    "SandboxedDreamer",
    # Adapter bundle + env convenience
    "RetrievalAdapters",
    "retrieval_adapters_from_env",
    # Registry-driven construction
    "ProviderRegistry",
    "SpecialistBudget",
    "SpecialistFactory",
    "SpecialistModuleRegistry",
    "SpecialistModuleSpec",
    "SpecialistRole",
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
SpecialistRole = Literal[
    "reasoner",
    "extractor",
    "resolver",
    "embedder",
    "media_embedder",
    "reranker",
    "lexical_retriever",
    "graph_retriever",
    "parametric_trainer",
    "dreamer",
    "reality_monitor",
    "workspace_controller",
]
SpecialistFactory = Callable[[Mapping[str, Any]], Any]


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


def _build_sandboxed_dreamer(config: Mapping[str, Any]) -> SandboxedDreamer:
    max_candidates = max(0, min(3, _as_int(config.get("dreamer_max_candidates"), default=3)))
    min_sources = max(2, _as_int(config.get("dreamer_min_sources"), default=2))
    return SandboxedDreamer(
        max_candidates=max_candidates,
        min_sources=min_sources,
    )


@dataclass(frozen=True, slots=True)
class SpecialistBudget:
    """Invocation budget and trust boundary for a specialist module."""

    max_calls_per_task: int = 1
    max_latency_ms: float = 30_000.0
    max_cost_usd: float = 0.0
    token_budget: int = 0
    critical_path_allowed: bool = False
    answer_authority_allowed: bool = False
    promotion_gate_required: bool = False

    def __post_init__(self) -> None:
        if self.max_calls_per_task < 0:
            raise ValueError("max_calls_per_task must be non-negative")
        if self.max_latency_ms < 0:
            raise ValueError("max_latency_ms must be non-negative")
        if self.max_cost_usd < 0:
            raise ValueError("max_cost_usd must be non-negative")
        if self.token_budget < 0:
            raise ValueError("token_budget must be non-negative")
        if self.answer_authority_allowed and not self.critical_path_allowed:
            raise ValueError("answer-authority specialists must be critical-path allowed")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SpecialistModuleSpec:
    """Typed Layer-3 specialist contract.

    Specialist modules wrap provider factories with role, budget, and critical
    path metadata so the workspace controller can recruit them explicitly.
    """

    name: str
    role: SpecialistRole
    factory: SpecialistFactory
    budget: SpecialistBudget
    input_contract: str
    output_contract: str
    provider_kind: str = "local"
    description: str = ""
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("specialist name must not be empty")
        if not self.input_contract.strip():
            raise ValueError("specialist input_contract must not be empty")
        if not self.output_contract.strip():
            raise ValueError("specialist output_contract must not be empty")

    def build(self, config: Mapping[str, Any] | None = None) -> Any:
        return self.factory(dict(config or {}))

    def manifest(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "provider_kind": self.provider_kind,
            "description": self.description,
            "input_contract": self.input_contract,
            "output_contract": self.output_contract,
            "budget": self.budget.to_dict(),
            "tags": list(self.tags),
        }


@dataclass(slots=True)
class SpecialistModuleRegistry:
    """Typed registry for on-demand cognitive specialist modules."""

    specialists: dict[str, SpecialistModuleSpec] = field(default_factory=dict)

    def register_specialist(self, spec: SpecialistModuleSpec, *, replace: bool = False) -> None:
        key = spec.name.lower()
        if not replace and key in self.specialists:
            raise ValueError(f"specialist {spec.name!r} is already registered")
        self.specialists[key] = spec

    def specialist(self, name: str) -> SpecialistModuleSpec:
        key = name.lower()
        spec = self.specialists.get(key)
        if spec is None:
            raise ValueError(f"unsupported specialist module: {name}")
        return spec

    def specialists_by_role(self, role: SpecialistRole) -> list[SpecialistModuleSpec]:
        return sorted(
            [spec for spec in self.specialists.values() if spec.role == role],
            key=lambda spec: spec.name,
        )

    def build_specialist(
        self,
        name: str,
        config: Mapping[str, Any] | None = None,
        *,
        critical_path: bool = False,
    ) -> Any:
        spec = self.specialist(name)
        if critical_path and not spec.budget.critical_path_allowed:
            raise ValueError(f"specialist {name!r} is not approved for critical-path use")
        return spec.build(config)

    def specialist_manifest(self) -> list[dict[str, Any]]:
        return [spec.manifest() for spec in sorted(self.specialists.values(), key=lambda item: item.name)]


@dataclass(slots=True)
class ProviderRegistry(SpecialistModuleRegistry):
    """Name → factory tables for each retrieval provider boundary and specialist.

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
    _register_builtin_specialists(registry)
    return registry


def _critical_budget(
    *,
    max_calls_per_task: int = 1,
    max_latency_ms: float = 30_000.0,
    max_cost_usd: float = 0.0,
    token_budget: int = 0,
) -> SpecialistBudget:
    return SpecialistBudget(
        max_calls_per_task=max_calls_per_task,
        max_latency_ms=max_latency_ms,
        max_cost_usd=max_cost_usd,
        token_budget=token_budget,
        critical_path_allowed=True,
        answer_authority_allowed=False,
        promotion_gate_required=False,
    )


def _register_builtin_specialists(registry: ProviderRegistry) -> None:
    registry.register_specialist(
        SpecialistModuleSpec(
            name="embedder.local",
            role="embedder",
            factory=_build_local_embedding,
            budget=_critical_budget(max_latency_ms=250.0),
            input_contract="text -> dense vector",
            output_contract="normalized embedding vector",
            provider_kind="local",
            description="Deterministic local hashing embedder.",
            tags=("retrieval", "offline"),
        )
    )
    registry.register_specialist(
        SpecialistModuleSpec(
            name="embedder.http",
            role="embedder",
            factory=_build_http_embedding,
            budget=_critical_budget(max_latency_ms=30_000.0, max_cost_usd=0.05),
            input_contract="text -> hosted embedding request",
            output_contract="normalized embedding vector",
            provider_kind="hosted_http",
            description="Hosted embedding provider boundary.",
            tags=("retrieval", "production-provider"),
        )
    )
    registry.register_specialist(
        SpecialistModuleSpec(
            name="reranker.local",
            role="reranker",
            factory=_build_local_reranker,
            budget=_critical_budget(max_latency_ms=250.0),
            input_contract="query + hits -> ranked hits",
            output_contract="score-ordered retrieval hits",
            provider_kind="local",
            description="Deterministic local reranker.",
            tags=("retrieval", "offline"),
        )
    )
    registry.register_specialist(
        SpecialistModuleSpec(
            name="reranker.http",
            role="reranker",
            factory=_build_http_reranker,
            budget=_critical_budget(max_latency_ms=30_000.0, max_cost_usd=0.05),
            input_contract="query + hits -> hosted rerank request",
            output_contract="score-ordered retrieval hits",
            provider_kind="hosted_http",
            description="Hosted cross-encoder reranker boundary.",
            tags=("retrieval", "production-provider"),
        )
    )
    registry.register_specialist(
        SpecialistModuleSpec(
            name="graph.command",
            role="graph_retriever",
            factory=_build_command_graph,
            budget=_critical_budget(max_latency_ms=30_000.0),
            input_contract="seed terms + custody filter -> relation hits",
            output_contract="ledger-backed relation hits only",
            provider_kind="command",
            description="Shell-free command graph specialist.",
            tags=("retrieval", "graph", "custody-required"),
        )
    )
    registry.register_specialist(
        SpecialistModuleSpec(
            name="dreamer.shadow",
            role="dreamer",
            factory=_build_sandboxed_dreamer,
            budget=SpecialistBudget(
                max_calls_per_task=1,
                max_latency_ms=1_000.0,
                token_budget=512,
                critical_path_allowed=False,
                answer_authority_allowed=False,
                promotion_gate_required=True,
            ),
            input_contract="retained evidence rows with CIDs",
            output_contract="low-trust replay candidates requiring promotion gate",
            provider_kind="shadow_local",
            description="Sandboxed generative replay specialist; never on answer critical path.",
            tags=("generative-replay", "low-groundedness", "g3"),
        )
    )


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
