"""Operational metrics for retrieval, consolidation, calibration, and gates."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class MetricsSnapshot:
    counters: dict[str, int] = field(default_factory=dict)
    gauges: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MetricsRegistry:
    def __init__(self) -> None:
        self.counters: Counter[str] = Counter()
        self.gauges: dict[str, float] = {}

    def increment(self, name: str, amount: int = 1) -> None:
        self.counters[name] += amount

    def gauge(self, name: str, value: float) -> None:
        self.gauges[name] = value

    def snapshot(self) -> MetricsSnapshot:
        return MetricsSnapshot(dict(self.counters), dict(self.gauges))

    def record_retrieval(self, channel_counts: dict[str, int], latency_ms: float, abstained: bool) -> None:
        for channel, count in channel_counts.items():
            self.increment(f"retrieval.channel.{channel}.hits", count)
        self.gauge("retrieval.p95_ms.latest_sample", latency_ms)
        if abstained:
            self.increment("retrieval.abstentions", 1)

    def record_gate(self, promoted: bool, rolled_back: bool) -> None:
        if promoted:
            self.increment("gate.promotions", 1)
        if rolled_back:
            self.increment("gate.rollbacks", 1)


def build_ops_report(
    *,
    engine: Any,
    tenant_id: str,
    queue_snapshot: dict[str, int] | None = None,
    learning: Any | None = None,
    metrics: MetricsSnapshot | None = None,
    proxy_score: float | None = None,
    true_score: float | None = None,
    min_diversity: float = 0.2,
    max_proxy_gap: float = 0.15,
) -> dict[str, Any]:
    exported = engine.export_tenant(tenant_id)
    assertions = exported.get("assertions", [])
    learning_counts = _learning_counts(learning, tenant_id)
    diversity = learning_counts["lesson_diversity"]
    proxy_gap = abs(proxy_score - true_score) if proxy_score is not None and true_score is not None else None
    tripwire_passed = diversity >= min_diversity and (proxy_gap is None or proxy_gap <= max_proxy_gap)
    return {
        "tenant_id": tenant_id,
        "counts": {
            "evidence": len(exported.get("evidence", [])),
            "assertions": len(assertions),
            "active_assertions": sum(1 for item in assertions if item.get("status") == "active"),
            "contested_assertions": sum(1 for item in assertions if item.get("status") == "contested"),
            "relations": len(exported.get("relations", [])),
            "preferences": len(exported.get("preferences", [])),
            "contradictions": len(exported.get("contradictions", [])),
            "deletions": len(exported.get("deletion_log", [])),
            "audit_events": len(exported.get("audit_log", [])),
        },
        "queue": queue_snapshot or {},
        "metrics": metrics.to_dict() if metrics else {"counters": {}, "gauges": {}},
        "learning": learning_counts,
        "tripwires": {
            "passed": tripwire_passed,
            "lesson_diversity": diversity,
            "min_diversity": min_diversity,
            "proxy_true_gap": proxy_gap,
            "max_proxy_gap": max_proxy_gap,
        },
    }


def _learning_counts(learning: Any | None, tenant_id: str) -> dict[str, Any]:
    if learning is None:
        return {"lessons": 0, "procedures": 0, "lesson_diversity": 1.0}
    lessons = [item for item in learning.lessons.values() if item.tenant_id == tenant_id]
    procedures = [item for item in learning.procedures.values() if item.tenant_id == tenant_id]
    diversity = 1.0 if not lessons else len({item.failure_signature for item in lessons}) / len(lessons)
    return {
        "lessons": len(lessons),
        "procedures": len(procedures),
        "lesson_diversity": diversity,
    }
