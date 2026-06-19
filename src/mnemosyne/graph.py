"""Graph adapter contract and benchmark harness."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Protocol

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Hit


class GraphAdapter(Protocol):
    name: str

    def ppr(
        self,
        seeds: list[str],
        k: int,
        as_of: datetime | None = None,
        tenant_id: str | None = None,
        branch: str | None = None,
    ) -> list[Hit]:
        raise NotImplementedError


class LocalRelationGraphAdapter:
    name = "local-relation-ppr"

    def __init__(self, engine: LocalMemoryEngine):
        self.engine = engine

    def ppr(
        self,
        seeds: list[str],
        k: int,
        as_of: datetime | None = None,
        tenant_id: str | None = None,
        branch: str | None = None,
    ) -> list[Hit]:
        return self.engine.graph_ppr(seeds, k, as_of=as_of, tenant_id=tenant_id, branch=branch)


@dataclass(slots=True)
class GraphBenchmarkResult:
    adapter: str
    query_count: int
    p50_ms: float
    p95_ms: float
    max_ms: float
    total_hits: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def benchmark_graph_adapter(adapter: GraphAdapter, queries: list[list[str]], k: int = 8) -> GraphBenchmarkResult:
    durations: list[float] = []
    total_hits = 0
    for seeds in queries:
        started = time.perf_counter()
        hits = adapter.ppr(seeds, k)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        durations.append(elapsed_ms)
        total_hits += len(hits)
    ordered = sorted(durations)
    if not ordered:
        return GraphBenchmarkResult(adapter.name, 0, 0.0, 0.0, 0.0, 0)
    p50_index = min(len(ordered) - 1, int(len(ordered) * 0.50))
    p95_index = min(len(ordered) - 1, int(len(ordered) * 0.95))
    return GraphBenchmarkResult(
        adapter=adapter.name,
        query_count=len(ordered),
        p50_ms=ordered[p50_index],
        p95_ms=ordered[p95_index],
        max_ms=max(ordered),
        total_hits=total_hits,
    )
