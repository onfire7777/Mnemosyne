"""Benchmark harnesses for memory retrieval and graph adapters."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any

from mnemosyne.engine import LocalMemoryEngine


@dataclass(slots=True)
class LatencyBenchmarkResult:
    name: str
    query_count: int
    p50_ms: float
    p95_ms: float
    max_ms: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def retrieval_latency_benchmark(engine: LocalMemoryEngine, tenant_id: str, queries: list[str], branch: str = "main") -> LatencyBenchmarkResult:
    durations: list[float] = []
    for query in queries:
        start = time.perf_counter()
        engine.retrieve(query, tenant_id=tenant_id, branch=branch, deep=False)
        durations.append((time.perf_counter() - start) * 1000.0)
    ordered = sorted(durations)
    if not ordered:
        return LatencyBenchmarkResult("fast-retrieval", 0, 0.0, 0.0, 0.0)
    p50_index = min(len(ordered) - 1, int(len(ordered) * 0.50))
    p95_index = min(len(ordered) - 1, int(len(ordered) * 0.95))
    return LatencyBenchmarkResult("fast-retrieval", len(ordered), ordered[p50_index], ordered[p95_index], max(ordered))

