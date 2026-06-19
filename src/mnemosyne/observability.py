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

