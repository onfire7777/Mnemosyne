"""Operational metrics for retrieval, consolidation, calibration, and gates."""

from __future__ import annotations

import html
import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from math import ceil
from typing import Any


@dataclass(slots=True)
class MetricsSnapshot:
    counters: dict[str, int] = field(default_factory=dict)
    gauges: dict[str, float] = field(default_factory=dict)
    samples: dict[str, list[float]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MetricsRegistry:
    def __init__(self, snapshot: MetricsSnapshot | dict[str, Any] | None = None) -> None:
        if isinstance(snapshot, MetricsSnapshot):
            source = snapshot.to_dict()
        else:
            source = snapshot or {}
        self.counters: Counter[str] = Counter(source.get("counters") or {})
        self.gauges: dict[str, float] = dict(source.get("gauges") or {})
        self.samples: dict[str, list[float]] = {
            name: [float(value) for value in values][-200:]
            for name, values in (source.get("samples") or {}).items()
        }

    def increment(self, name: str, amount: int = 1) -> None:
        self.counters[name] += amount

    def gauge(self, name: str, value: float) -> None:
        self.gauges[name] = value

    def observe(self, name: str, value: float) -> None:
        values = self.samples.setdefault(name, [])
        values.append(float(value))
        del values[:-200]
        self.gauge(f"{name}.p95", _percentile(values, 95))

    def snapshot(self) -> MetricsSnapshot:
        return MetricsSnapshot(dict(self.counters), dict(self.gauges), {name: list(values) for name, values in self.samples.items()})

    def record_retrieval(self, channel_counts: dict[str, int], latency_ms: float, abstained: bool) -> None:
        self.increment("retrieval.requests", 1)
        for channel, count in channel_counts.items():
            self.increment(f"retrieval.channel.{channel}.hits", count)
        self.gauge("retrieval.p95_ms.latest_sample", latency_ms)
        self.observe("retrieval.latency_ms", latency_ms)
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
    max_open_contradictions: int = 0,
) -> dict[str, Any]:
    exported = engine.export_tenant(tenant_id)
    assertions = exported.get("assertions", [])
    contradictions = exported.get("contradictions", [])
    open_contradictions = sum(1 for item in contradictions if item.get("status") == "open")
    metric_counters = metrics.counters if metrics else {}
    learning_counts = _learning_counts(learning, tenant_id)
    diversity = learning_counts["lesson_diversity"]
    proxy_gap = abs(proxy_score - true_score) if proxy_score is not None and true_score is not None else None
    tripwire_passed = (
        diversity >= min_diversity
        and (proxy_gap is None or proxy_gap <= max_proxy_gap)
        and open_contradictions <= max_open_contradictions
    )
    return {
        "tenant_id": tenant_id,
        "counts": {
            "evidence": len(exported.get("evidence", [])),
            "assertions": len(assertions),
            "active_assertions": sum(1 for item in assertions if item.get("status") == "active"),
            "contested_assertions": sum(1 for item in assertions if item.get("status") == "contested"),
            "relations": len(exported.get("relations", [])),
            "preferences": len(exported.get("preferences", [])),
            "contradictions": len(contradictions),
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
            "open_contradictions": open_contradictions,
            "max_open_contradictions": max_open_contradictions,
            "gate_promotions": int(metric_counters.get("gate.promotions", 0)),
            "gate_rollbacks": int(metric_counters.get("gate.rollbacks", 0)),
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


def render_ops_dashboard(report: dict[str, Any]) -> str:
    counts = report.get("counts", {})
    queue = report.get("queue", {})
    tripwires = report.get("tripwires", {})
    metrics = report.get("metrics", {})
    counters = metrics.get("counters", {}) if isinstance(metrics, dict) else {}
    cards = [
        ("Evidence", counts.get("evidence", 0)),
        ("Assertions", counts.get("assertions", 0)),
        ("Relations", counts.get("relations", 0)),
        ("Preferences", counts.get("preferences", 0)),
        ("Open contradictions", tripwires.get("open_contradictions", 0)),
        ("Queue depth", queue.get("queued", 0)),
        ("Gate promotions", tripwires.get("gate_promotions", counters.get("gate.promotions", 0))),
        ("Gate rollbacks", tripwires.get("gate_rollbacks", counters.get("gate.rollbacks", 0))),
    ]
    card_html = "\n".join(
        f"<section class=\"card\"><div class=\"label\">{html.escape(label)}</div>"
        f"<div class=\"value\">{html.escape(str(value))}</div></section>"
        for label, value in cards
    )
    tripwire_class = "ok" if tripwires.get("passed") else "alert"
    tripwire_text = "PASS" if tripwires.get("passed") else "ATTENTION"
    snapshot = html.escape(json.dumps(report, sort_keys=True, indent=2))
    tenant = html.escape(str(report.get("tenant_id", "unknown")))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Mnemosyne Ops Dashboard - {tenant}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; color: #18202a; background: #f6f7f9; }}
    header {{ padding: 24px 32px; background: #132033; color: white; }}
    main {{ padding: 24px 32px; max-width: 1080px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }}
    .card {{ background: white; border: 1px solid #d9dee7; border-radius: 6px; padding: 16px; }}
    .label {{ color: #5b6675; font-size: 13px; }}
    .value {{ font-size: 28px; font-weight: 700; margin-top: 6px; }}
    .status {{ display: inline-block; margin-top: 8px; padding: 4px 8px; border-radius: 4px; font-weight: 700; }}
    .ok {{ background: #dcfce7; color: #14532d; }}
    .alert {{ background: #fee2e2; color: #7f1d1d; }}
    pre {{ white-space: pre-wrap; background: #101827; color: #e6edf7; border-radius: 6px; padding: 16px; overflow: auto; }}
  </style>
</head>
<body>
  <header>
    <h1>Mnemosyne Ops Dashboard</h1>
    <div>Tenant: {tenant}</div>
    <span class="status {tripwire_class}">{tripwire_text}</span>
  </header>
  <main>
    <div class="grid">{card_html}</div>
    <h2>Snapshot JSON</h2>
    <pre>{snapshot}</pre>
  </main>
</body>
</html>
"""


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, ceil(percentile / 100 * len(ordered)) - 1))
    return ordered[index]
