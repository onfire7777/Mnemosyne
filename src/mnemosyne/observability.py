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
    require_clean_vector_hygiene: bool = False,
) -> dict[str, Any]:
    exported = engine.export_tenant(tenant_id)
    assertions = exported.get("assertions", [])
    contradictions = exported.get("contradictions", [])
    open_contradictions = sum(1 for item in contradictions if item.get("status") == "open")
    metric_counters = metrics.counters if metrics else {}
    learning_counts = _learning_counts(learning, tenant_id)
    diversity = learning_counts["lesson_diversity"]
    proxy_gap = abs(proxy_score - true_score) if proxy_score is not None and true_score is not None else None
    vector_hygiene = _postgres_vector_hygiene(engine, tenant_id)
    vector_hygiene_passed = (
        not require_clean_vector_hygiene
        or (vector_hygiene.get("available") is True and vector_hygiene.get("ok") is True)
    )
    tripwire_passed = (
        diversity >= min_diversity
        and (proxy_gap is None or proxy_gap <= max_proxy_gap)
        and open_contradictions <= max_open_contradictions
        and vector_hygiene_passed
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
            "vector_hygiene_required": require_clean_vector_hygiene,
            "vector_hygiene_available": vector_hygiene.get("available") is True,
            "vector_hygiene_clean": vector_hygiene.get("ok") is True,
            "vector_hygiene_ok": vector_hygiene_passed,
        },
        "postgres_vector_hygiene": vector_hygiene,
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


def _postgres_vector_hygiene(engine: Any, tenant_id: str) -> dict[str, Any]:
    probe = getattr(engine, "vector_hygiene_snapshot", None)
    if probe is None:
        return {
            "backend": type(engine).__name__,
            "available": False,
            "ok": None,
            "reason": "postgres vector hygiene probe unavailable for this engine",
        }
    try:
        snapshot = probe(tenant_id)
    except Exception as exc:  # noqa: BLE001 - ops report should surface probe failure, not hide it
        return {
            "backend": type(engine).__name__,
            "available": True,
            "ok": False,
            "error": str(exc),
        }
    if not isinstance(snapshot, dict):
        return {
            "backend": type(engine).__name__,
            "available": True,
            "ok": False,
            "error": "postgres vector hygiene probe returned a non-object",
        }
    plan_probe = getattr(engine, "vector_backfill_plan", None)
    if plan_probe is not None:
        try:
            plan = plan_probe(tenant_id)
        except Exception as exc:  # noqa: BLE001 - ops report should expose probe failure.
            plan = {"available": True, "ok": False, "error": str(exc)}
        if not isinstance(plan, dict):
            plan = {"available": True, "ok": False, "error": "postgres vector backfill plan returned a non-object"}
        snapshot = {**snapshot, "backfill_plan": {"available": True, **plan}}
    return {"available": True, **snapshot}


def render_ops_dashboard(report: dict[str, Any]) -> str:
    counts = report.get("counts", {})
    queue = report.get("queue", {})
    tripwires = report.get("tripwires", {})
    learning = report.get("learning", {})
    metrics = report.get("metrics", {})
    vector_hygiene = report.get("postgres_vector_hygiene", {})
    counters = metrics.get("counters", {}) if isinstance(metrics, dict) else {}
    gauges = metrics.get("gauges", {}) if isinstance(metrics, dict) else {}
    samples = metrics.get("samples", {}) if isinstance(metrics, dict) else {}
    memory_cards = [
        ("Evidence", counts.get("evidence", 0)),
        ("Assertions", counts.get("assertions", 0)),
        ("Active assertions", counts.get("active_assertions", 0)),
        ("Contested assertions", counts.get("contested_assertions", 0)),
        ("Relations", counts.get("relations", 0)),
        ("Preferences", counts.get("preferences", 0)),
        ("Audit events", counts.get("audit_events", 0)),
        ("Deletions", counts.get("deletions", 0)),
        ("Open contradictions", tripwires.get("open_contradictions", 0)),
    ]
    queue_cards = [
        ("Queue depth", queue.get("queued", 0)),
        ("Active jobs", queue.get("running", queue.get("active", 0))),
        ("Retry jobs", queue.get("retry", 0)),
        ("Completed jobs", queue.get("complete", 0)),
        ("Dead jobs", queue.get("dead", 0)),
    ]
    retrieval_cards = [
        ("Requests", counters.get("retrieval.requests", 0)),
        ("Abstentions", counters.get("retrieval.abstentions", 0)),
        ("Lexical hits", counters.get("retrieval.channel.lexical.hits", 0)),
        ("Dense hits", counters.get("retrieval.channel.dense_hash.hits", 0)),
        ("Graph hits", counters.get("retrieval.channel.graph_ppr.hits", 0)),
        ("p95 latency ms", gauges.get("retrieval.latency_ms.p95", 0)),
        ("Latency samples", len(samples.get("retrieval.latency_ms", []))),
    ]
    calibration_cards = [
        ("Calibration jobs", counters.get("calibration.jobs", 0)),
        ("Calibration abstentions", counters.get("calibration.abstentions", 0)),
        ("Proxy true gap", tripwires.get("proxy_true_gap", "n/a")),
        ("Max proxy gap", tripwires.get("max_proxy_gap", "n/a")),
        ("Fact threshold", gauges.get("calibration.fact.threshold", "n/a")),
        ("Preference threshold", gauges.get("calibration.preference.threshold", "n/a")),
    ]
    learning_cards = [
        ("Lessons", learning.get("lessons", 0)),
        ("Procedures", learning.get("procedures", 0)),
        ("Lesson diversity", learning.get("lesson_diversity", "n/a")),
        ("Min diversity", tripwires.get("min_diversity", "n/a")),
    ]
    gate_cards = [
        ("Gate promotions", tripwires.get("gate_promotions", counters.get("gate.promotions", 0))),
        ("Gate rollbacks", tripwires.get("gate_rollbacks", counters.get("gate.rollbacks", 0))),
        ("Eval passed", counters.get("eval.cases.passed", 0)),
        ("Eval failed", counters.get("eval.cases.failed", 0)),
        ("Lifecycle sweeps", counters.get("lifecycle.sweeps", 0)),
        ("Lifecycle demotions", counters.get("lifecycle.demotions", 0)),
    ]
    vector_cards = [
        ("Probe available", vector_hygiene.get("available", False)),
        ("Clean", vector_hygiene.get("ok", "n/a")),
        ("Embeddable null vectors", vector_hygiene.get("embeddable_null_embeddings", "n/a")),
        ("Evidence null vectors", vector_hygiene.get("evidence_embeddable_null_embeddings", "n/a")),
        ("Assertion null vectors", vector_hygiene.get("assertion_embeddable_null_embeddings", "n/a")),
        ("None-partition vectors", vector_hygiene.get("none_partition_vectors", "n/a")),
        ("Stored vectors", vector_hygiene.get("stored_vectors", "n/a")),
        ("Live rows", vector_hygiene.get("live_rows", "n/a")),
        ("Backfill backlog", (vector_hygiene.get("backfill_plan") or {}).get("total_backlog", "n/a")),
        ("Backfill sampled", (vector_hygiene.get("backfill_plan") or {}).get("sampled", "n/a")),
        ("Backfill truncated", (vector_hygiene.get("backfill_plan") or {}).get("truncated", "n/a")),
    ]
    sections = "\n".join(
        [
            _render_dashboard_section("Memory State", memory_cards),
            _render_dashboard_section("Queue", queue_cards),
            _render_dashboard_section("Retrieval", retrieval_cards),
            _render_dashboard_section("Calibration", calibration_cards),
            _render_dashboard_section("Learning", learning_cards),
            _render_dashboard_section("Gates and Eval", gate_cards),
            _render_dashboard_section("Postgres Vector Hygiene", vector_cards),
        ]
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
    section.dashboard-section {{ margin: 0 0 24px; }}
    h2 {{ margin: 0 0 12px; }}
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
    {sections}
    <h2>Snapshot JSON</h2>
    <pre>{snapshot}</pre>
  </main>
</body>
</html>
"""


def _render_dashboard_section(title: str, cards: list[tuple[str, Any]]) -> str:
    card_html = "\n".join(
        f"<section class=\"card\"><div class=\"label\">{html.escape(label)}</div>"
        f"<div class=\"value\">{html.escape(_format_dashboard_value(value))}</div></section>"
        for label, value in cards
    )
    return (
        f"<section class=\"dashboard-section\"><h2>{html.escape(title)}</h2>"
        f"<div class=\"grid\">{card_html}</div></section>"
    )


def _format_dashboard_value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, ceil(percentile / 100 * len(ordered)) - 1))
    return ordered[index]
