"""Benchmark harnesses for memory retrieval and graph adapters.

Two complementary, fully deterministic harnesses are provided:

* :func:`retrieval_latency_benchmark` measures the fast-path latency contract
  (blueprint §15/§22.5: fast-mode memory overhead P95 ≤ ~300–400 ms);
* :func:`retrieval_quality_benchmark` measures the leading retrieval-quality
  metrics (blueprint §16 / Evaluation-and-Test-Plan: recall@k, nDCG@k,
  context precision, MRR) against a caller-supplied labeled corpus.

These harnesses only *measure*; threshold/floor enforcement belongs to the
evaluation lane (``mnemosyne.eval``), keeping the measurement surface free of
opinionated pass/fail policy.
"""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
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


@dataclass(frozen=True, slots=True)
class LabeledQuery:
    """A benchmark query paired with the ids of its known-relevant memories.

    ``relevant_ids`` are matched against the ``Hit.id`` values returned by the
    engine (assertion / evidence ids). Queries with no relevant ids are skipped
    from the aggregate so an unlabeled probe cannot deflate the score.
    """

    query: str
    relevant_ids: tuple[str, ...] = ()


@dataclass(slots=True)
class RetrievalQualityBenchmarkResult:
    """Aggregate retrieval-quality metrics over a labeled corpus (blueprint §16)."""

    name: str
    query_count: int
    k: int
    recall_at_k: float
    precision_at_k: float
    ndcg_at_k: float
    mrr: float
    per_query: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _dcg(retrieved: Sequence[str], relevant: set[str]) -> float:
    """Binary-relevance discounted cumulative gain over a ranked id list."""

    return sum(
        1.0 / math.log2(rank + 1)
        for rank, hit_id in enumerate(retrieved, start=1)
        if hit_id in relevant
    )


def retrieval_quality_benchmark(
    engine: LocalMemoryEngine,
    tenant_id: str,
    labeled_queries: Sequence[LabeledQuery],
    *,
    k: int = 8,
    branch: str = "main",
    deep: bool = False,
) -> RetrievalQualityBenchmarkResult:
    """Score recall@k, nDCG@k, context precision, and MRR on a labeled corpus.

    The engine is queried in fast mode by default so the metric reflects the
    blueprint's *leading* first-stage retrieval quality. Only queries carrying
    at least one relevant id contribute to the aggregate.
    """

    if k <= 0:
        raise ValueError("k must be positive")
    recalls: list[float] = []
    precisions: list[float] = []
    ndcgs: list[float] = []
    reciprocal_ranks: list[float] = []
    per_query: list[dict[str, Any]] = []
    for labeled in labeled_queries:
        relevant = {rid for rid in labeled.relevant_ids if rid}
        if not relevant:
            continue
        result = engine.retrieve(labeled.query, tenant_id=tenant_id, branch=branch, deep=deep)
        retrieved = [hit.id for hit in result.hits][:k]
        retrieved_relevant = sum(1 for hit_id in retrieved if hit_id in relevant)
        recall = retrieved_relevant / len(relevant)
        precision = retrieved_relevant / len(retrieved) if retrieved else 0.0
        ideal = min(len(relevant), k)
        idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal + 1))
        ndcg = (_dcg(retrieved, relevant) / idcg) if idcg else 0.0
        reciprocal_rank = next(
            (1.0 / rank for rank, hit_id in enumerate(retrieved, start=1) if hit_id in relevant),
            0.0,
        )
        recalls.append(recall)
        precisions.append(precision)
        ndcgs.append(ndcg)
        reciprocal_ranks.append(reciprocal_rank)
        per_query.append(
            {
                "query": labeled.query,
                "recall_at_k": round(recall, 6),
                "precision_at_k": round(precision, 6),
                "ndcg_at_k": round(ndcg, 6),
                "reciprocal_rank": round(reciprocal_rank, 6),
            }
        )

    count = len(recalls)
    if count == 0:
        return RetrievalQualityBenchmarkResult("retrieval-quality", 0, k, 0.0, 0.0, 0.0, 0.0, [])
    return RetrievalQualityBenchmarkResult(
        name="retrieval-quality",
        query_count=count,
        k=k,
        recall_at_k=sum(recalls) / count,
        precision_at_k=sum(precisions) / count,
        ndcg_at_k=sum(ndcgs) / count,
        mrr=sum(reciprocal_ranks) / count,
        per_query=per_query,
    )

