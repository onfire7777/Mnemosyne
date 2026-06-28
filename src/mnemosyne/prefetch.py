"""Anticipatory prefetch with a predictability gate."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import RetrievalResult


@dataclass(frozen=True, slots=True)
class PrefetchCandidate:
    query: str
    probability: float
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PrefetchResult:
    candidate: PrefetchCandidate
    executed: bool
    reason: str
    retrieval: RetrievalResult | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["retrieval"] = self.retrieval.to_dict() if self.retrieval else None
        return data


class PredictabilityGate:
    """Blocks speculative retrieval unless confidence and safety allow it."""

    def __init__(self, min_probability: float = 0.65, max_candidates: int = 5):
        if not 0.0 <= min_probability <= 1.0:
            raise ValueError("min_probability must be between 0 and 1")
        self.min_probability = min_probability
        self.max_candidates = max_candidates

    def allow(self, candidate: PrefetchCandidate) -> tuple[bool, str]:
        if candidate.probability < self.min_probability:
            return False, "candidate below predictability threshold"
        if not candidate.query.strip():
            return False, "empty query"
        if candidate.metadata.get("requires_network") is True:
            return False, "prefetch cannot perform network side effects"
        return True, "allowed"


class AnticipatoryPrefetcher:
    """Warms retrieval contexts without writing durable memory."""

    def __init__(self, engine: LocalMemoryEngine, gate: PredictabilityGate | None = None):
        self.engine = engine
        self.gate = gate or PredictabilityGate()
        self.cache: dict[tuple[str, str, str], RetrievalResult] = {}

    def prefetch(
        self,
        tenant_id: str,
        candidates: list[PrefetchCandidate],
        branch: str = "main",
        access_context: dict[str, Any] | None = None,
    ) -> list[PrefetchResult]:
        selected = set(
            id(candidate)
            for candidate in sorted(candidates, key=lambda item: item.probability, reverse=True)[: self.gate.max_candidates]
        )
        results: list[PrefetchResult] = []
        for candidate in candidates:
            if id(candidate) not in selected:
                results.append(PrefetchResult(candidate, False, "candidate outside prefetch limit"))
                continue
            allowed, reason = self.gate.allow(candidate)
            if not allowed:
                results.append(PrefetchResult(candidate, False, reason))
                continue
            retrieval = self.engine.retrieve(candidate.query, tenant_id, branch=branch, filt=dict(access_context or {}))
            self.cache[(tenant_id, branch, candidate.query)] = retrieval
            results.append(PrefetchResult(candidate, True, reason, retrieval))
        return results

    def get_warmed(self, tenant_id: str, query: str, branch: str = "main") -> RetrievalResult | None:
        return self.cache.get((tenant_id, branch, query))
