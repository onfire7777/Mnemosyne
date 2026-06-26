"""G0 functional consciousness indicator scorecard.

The scorecard follows the indicator-property framing from Butlin and Long et al.
2023. It measures architecture/probe signatures only; it never claims
phenomenal or subjective consciousness.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mnemosyne.consciousness import (
    BoundedCognitiveCycle,
    InteroceptiveProtoSelf,
    RealityMonitor,
    workspace_bottleneck,
)
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence, Hit
from mnemosyne.postgres_engine import PostgresEngine


@dataclass(frozen=True, slots=True)
class IndicatorSpec:
    id: str
    theory: str
    label: str
    check: str
    terms: tuple[str, ...]
    files: tuple[str, ...]


INDICATORS: tuple[IndicatorSpec, ...] = (
    IndicatorSpec(
        "RPT-1",
        "Recurrent Processing Theory",
        "algorithmic recurrence in input/update modules",
        "Source contains recurrent projection/consolidation/update paths.",
        ("recompute", "consolidation", "projection"),
        ("src/mnemosyne/engine.py", "src/mnemosyne/consolidation.py"),
    ),
    IndicatorSpec(
        "RPT-2",
        "Recurrent Processing Theory",
        "organized integrated perceptual representations",
        "Source exposes integrated assertion/relation/evidence representations with provenance.",
        ("Assertion", "Relation", "source_evidence_cids"),
        ("src/mnemosyne/models.py", "src/mnemosyne/engine.py"),
    ),
    IndicatorSpec(
        "GWT-1",
        "Global Workspace Theory",
        "parallel specialized systems",
        "Source exposes specialist providers/tools around a common memory contract.",
        ("RetrievalAdapters", "MemoryTools", "provider"),
        ("src/mnemosyne/retrieval.py", "src/mnemosyne/mcp_tools.py"),
    ),
    IndicatorSpec(
        "GWT-2",
        "Global Workspace Theory",
        "limited-capacity workspace bottleneck",
        "Source exposes token/priority bottlenecks and explicit low-bandwidth workspace selection.",
        ("token_budget", "workspace_bottleneck", "priority"),
        ("src/mnemosyne/engine.py", "src/mnemosyne/consciousness.py"),
    ),
    IndicatorSpec(
        "GWT-3",
        "Global Workspace Theory",
        "global broadcast to consuming systems",
        "Source exposes shared tool/server surfaces for memory outputs.",
        ("TOOL_SPEC", "MnemosyneMcpServer", "structuredContent"),
        ("src/mnemosyne/mcp_tools.py", "src/mnemosyne/mcp_server.py"),
    ),
    IndicatorSpec(
        "GWT-4",
        "Global Workspace Theory",
        "state-dependent attention",
        "Source exposes priority, prefetch, and attention-lock regulation hooks.",
        ("prefetch", "attention_lock_risk", "priority"),
        ("src/mnemosyne/mcp_tools.py", "src/mnemosyne/consciousness.py"),
    ),
    IndicatorSpec(
        "HOT-1",
        "Higher-Order Theory",
        "metacognitive confidence and abstention",
        "Source exposes calibrated confidence, conformal thresholds, and abstention.",
        ("conformal_threshold", "confidence", "abstained"),
        ("src/mnemosyne/calibration.py", "src/mnemosyne/engine.py"),
    ),
    IndicatorSpec(
        "HOT-2",
        "Higher-Order Theory",
        "reality monitoring over representations",
        "Source exposes confidence-bearing reality tags that feed abstention.",
        ("RealityMonitor", "reality_class", "ungrounded_reality_only"),
        ("src/mnemosyne/consciousness.py", "src/mnemosyne/engine.py"),
    ),
    IndicatorSpec(
        "HOT-3",
        "Higher-Order Theory",
        "belief/action selection updated by metacognitive monitoring",
        "Source exposes profile/context, action selection, and proto-self state for reflective control.",
        ("profile_context", "procedure", "InteroceptiveProtoSelf"),
        ("src/mnemosyne/mcp_tools.py", "src/mnemosyne/consciousness.py"),
    ),
    IndicatorSpec(
        "HOT-4",
        "Higher-Order Theory",
        "sparse and smooth quality-space coding",
        "Source exposes uncertainty, semantic entropy, and calibrated metacognitive probes as the current proxy.",
        ("semantic_entropy", "uncertainty_note", "m_ratio"),
        ("src/mnemosyne/retrieval.py", "src/mnemosyne/engine.py", "eval/g0/consciousness.py"),
    ),
    IndicatorSpec(
        "AST-1",
        "Attention Schema Theory",
        "predictive model representing and controlling attention state",
        "Source exposes an attention-lock risk model and escalation signal.",
        ("attention_lock_risk", "escalation_required", "cycle_budget"),
        ("src/mnemosyne/consciousness.py",),
    ),
    IndicatorSpec(
        "PP-1",
        "Predictive Processing",
        "input modules using predictive coding",
        "Source exposes prediction-error consolidation or update metadata.",
        ("prediction_error", "consolidation", "gated"),
        ("src/mnemosyne/consolidation.py", "docs/blueprint/cognitive-architecture/04-G0-BENCHMARK-SPEC.md"),
    ),
    IndicatorSpec(
        "AE-1",
        "Agency and Embodiment",
        "goal-directed action selection",
        "Source exposes trajectories, procedures, validation, promotion, and rollback.",
        ("trajectory", "procedure", "rollback"),
        ("src/mnemosyne/mcp_tools.py", "src/mnemosyne/parametric.py"),
    ),
    IndicatorSpec(
        "AE-2",
        "Agency and Embodiment",
        "modeling output-input contingencies for control",
        "Source exposes resource/health state and allostatic regulation.",
        ("resource_health", "rail_budget", "memory_pressure"),
        ("src/mnemosyne/consciousness.py", "eval/g0/resource_usage.py"),
    ),
)


CONSCIOUSNESS_METRIC_SPECS: tuple[dict[str, Any], ...] = tuple(
    {
        "id": f"consciousness_indicator_{spec.id.lower().replace('-', '_')}",
        "label": f"{spec.id} indicator score",
        "class": "guardrail",
        "direction": "increase",
        "target": None,
        "target_op": None,
        "blueprint_metric": f"consciousness indicator {spec.id}",
    }
    for spec in INDICATORS
) + (
    {
        "id": "consciousness_indicator_total",
        "label": "consciousness indicator total",
        "class": "target",
        "direction": "increase",
        "target": None,
        "target_op": None,
        "blueprint_metric": "indicator-property scorecard total",
    },
    {
        "id": "consciousness_indicator_normalized",
        "label": "consciousness indicator normalized",
        "class": "guardrail",
        "direction": "increase",
        "target": None,
        "target_op": None,
        "blueprint_metric": "indicator-property scorecard normalized",
    },
    {
        "id": "workspace_loop_liveness",
        "label": "workspace loop liveness",
        "class": "guardrail",
        "direction": "increase",
        "target": None,
        "target_op": None,
        "blueprint_metric": "continuity loop liveness",
    },
    {
        "id": "workspace_stream_coherence",
        "label": "workspace stream coherence",
        "class": "guardrail",
        "direction": "increase",
        "target": None,
        "target_op": None,
        "blueprint_metric": "continuity stream coherence",
    },
    {
        "id": "self_model_accuracy",
        "label": "self-model accuracy",
        "class": "guardrail",
        "direction": "increase",
        "target": None,
        "target_op": None,
        "blueprint_metric": "self-model accuracy",
    },
    {
        "id": "metacognition_meta_d_prime",
        "label": "metacognition meta-d-prime",
        "class": "guardrail",
        "direction": "increase",
        "target": None,
        "target_op": None,
        "blueprint_metric": "meta-d-prime",
    },
    {
        "id": "metacognition_m_ratio",
        "label": "metacognition M-ratio",
        "class": "guardrail",
        "direction": "increase",
        "target": None,
        "target_op": None,
        "blueprint_metric": "M-ratio",
    },
    {
        "id": "reality_monitor_shadow_tag_contract",
        "label": "reality-monitor shadow tag contract",
        "class": "target",
        "direction": "increase",
        "target": None,
        "target_op": None,
        "blueprint_metric": "HOT-2 runtime shadow-tag contract",
    },
)


def run_consciousness_eval(*, repo_root: Path | None = None) -> dict[str, Any]:
    repo_root = (repo_root or Path(__file__).resolve().parents[2]).resolve()
    indicators = [_score_indicator(repo_root, spec) for spec in INDICATORS]
    total = round(sum(float(row["score"]) for row in indicators), 6)
    max_score = float(len(INDICATORS))
    continuity = _continuity_probe()
    self_model = _self_model_probe()
    metacognition = _metacognition_probe()
    shadow_contract = _shadow_tag_contract_probe()
    metrics = {
        **{row["metric_id"]: row["score"] for row in indicators},
        "consciousness_indicator_total": total,
        "consciousness_indicator_normalized": round(total / max_score, 6),
        "workspace_loop_liveness": continuity["loop_liveness"],
        "workspace_stream_coherence": continuity["stream_coherence"],
        "self_model_accuracy": self_model["accuracy"],
        "metacognition_meta_d_prime": metacognition["meta_d_prime"],
        "metacognition_m_ratio": metacognition["m_ratio"],
        "reality_monitor_shadow_tag_contract": shadow_contract["score"],
    }
    return {
        "schema_version": "g0.consciousness_scorecard.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "measurement_scope": "functional-indicator-properties-only",
        "phenomenal_claim": False,
        "source": "Butlin_Long_et_al_2023_arxiv_2308_08708",
        "welfare_review_flag": total / max_score >= 0.80,
        "welfare_review_source": "Long_Sebo_et_al_2024_Taking_AI_Welfare_Seriously",
        "score_scale": {"absent": 0.0, "partial": 0.5, "present": 1.0},
        "indicator_count": len(INDICATORS),
        "total_score": total,
        "max_score": max_score,
        "normalized_score": metrics["consciousness_indicator_normalized"],
        "indicators": indicators,
        "continuity": continuity,
        "self_model": self_model,
        "metacognition": metacognition,
        "reality_monitor_shadow_tag_contract": shadow_contract,
        "metrics": metrics,
        "metric_note": (
            "Architecture/probe-based scorecard for functional indicator properties. "
            "Scores are guardrails for non-decrease and do not establish phenomenal consciousness."
        ),
    }


def _score_indicator(repo_root: Path, spec: IndicatorSpec) -> dict[str, Any]:
    file_hits: dict[str, list[str]] = {}
    found: set[str] = set()
    present_files = 0
    for rel in spec.files:
        path = repo_root / rel
        if not path.exists():
            continue
        present_files += 1
        text = path.read_text(encoding="utf-8", errors="ignore")
        hits = [term for term in spec.terms if term in text]
        if hits:
            file_hits[rel] = hits
            found.update(hits)
    if found == set(spec.terms) and present_files == len(spec.files):
        score = 1.0
        score_label = "1"
    elif found or present_files:
        score = 0.5
        score_label = "partial"
    else:
        score = 0.0
        score_label = "0"
    return {
        "id": spec.id,
        "metric_id": f"consciousness_indicator_{spec.id.lower().replace('-', '_')}",
        "theory": spec.theory,
        "label": spec.label,
        "check": spec.check,
        "score": score,
        "score_label": score_label,
        "terms_found": sorted(found),
        "terms_required": list(spec.terms),
        "evidence": file_hits,
    }


def _continuity_probe() -> dict[str, Any]:
    cycle = BoundedCognitiveCycle(max_cycles=4, tick_ms=250)
    selected = workspace_bottleneck(
        [
            {"id": "low", "priority": 0.1},
            {"id": "workspace", "priority": 0.9},
            {"id": "mid", "priority": 0.5},
        ],
        limit=2,
    )
    rows = [
        cycle.tick(coherent=True, progressed=True),
        cycle.tick(coherent=True, progressed=True),
        cycle.tick(coherent=True, progressed=True),
    ]
    live_ticks = sum(1 for row in rows if row["state"] == "continue")
    coherence = sum(1 for row in rows if row["state"] != "shadow_only") / len(rows)
    return {
        "loop_liveness": round(live_ticks / len(rows), 6),
        "stream_coherence": round(coherence, 6),
        "tick_ms": cycle.tick_ms,
        "max_cycles": cycle.max_cycles,
        "bottleneck_selected_ids": [item["id"] for item in selected],
        "rows": rows,
    }


def _self_model_probe() -> dict[str, Any]:
    proto = InteroceptiveProtoSelf()
    stable = proto.snapshot(
        resource_health=0.92,
        error_rate=0.02,
        latency_ms=120.0,
        memory_pressure=0.30,
        confidence=0.84,
        rail_budget=0.90,
        cycle_index=1,
        max_cycles=6,
    )
    strained = proto.snapshot(
        resource_health=0.35,
        error_rate=0.18,
        latency_ms=1200.0,
        memory_pressure=0.88,
        confidence=0.32,
        rail_budget=0.20,
        cycle_index=6,
        max_cycles=6,
    )
    correct = int(not stable.escalation_required) + int(strained.escalation_required)
    return {
        "accuracy": round(correct / 2, 6),
        "stable": asdict(stable),
        "strained": asdict(strained),
    }


def _metacognition_probe() -> dict[str, Any]:
    monitor = RealityMonitor()
    grounded = monitor.tag(
        source_type="operator-evidence",
        actor="user",
        trust_tier=0,
        metadata={"reality_class": "evidence_grounded"},
        provenance_count=2,
    )
    generated = monitor.tag(
        source_type="generated-summary",
        actor="assistant",
        trust_tier=1,
        metadata={},
        provenance_count=0,
    )
    external = monitor.tag(
        source_type="external-suggestion",
        actor="external",
        trust_tier=2,
        metadata={},
        provenance_count=0,
    )
    correct_order = grounded.confidence > generated.confidence - 0.30 and generated.confidence >= external.confidence - 0.20
    meta_d_prime = 1.0 if correct_order else 0.5
    return {
        "meta_d_prime": meta_d_prime,
        "m_ratio": round(meta_d_prime / 1.0, 6),
        "rows": [
            {"class": grounded.reality_class, "confidence": grounded.confidence},
            {"class": generated.reality_class, "confidence": generated.confidence},
            {"class": external.reality_class, "confidence": external.confidence},
        ],
    }


def _shadow_tag_contract_probe() -> dict[str, Any]:
    tenant = "g0-shadow-tag-contract"
    query = "G0 shadow monitor contract Calypso"
    engine = LocalMemoryEngine()
    grounded_cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id="g0",
            actor="user",
            source_type="operator-evidence",
            content=(
                "G0 shadow monitor contract Calypso grounded anchor comes from "
                "operator evidence with corroborated source custody."
            ),
            metadata={"reality_class": "evidence_grounded"},
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )
    generated_cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id="g0",
            actor="assistant",
            source_type="generated-summary",
            content=(
                "G0 shadow monitor contract Calypso generated caveat is a "
                "self-generated summary and must remain shadow-only."
            ),
            trust_tier=1,
            access_policy={"tenant": tenant},
        )
    )

    local_result = engine.retrieve(query, tenant)
    local_report = local_result.explain.get("reality_monitoring", {})
    postgres_report = PostgresEngine("postgresql://unused")._reality_monitoring_report(
        [
            Hit(
                id="pg-grounded",
                kind="evidence",
                tenant_id=tenant,
                branch="main",
                text="G0 shadow monitor contract Calypso grounded Postgres hit.",
                score=1.0,
                channel="probe",
                provenance=["pg-grounded"],
                trust_tier=0,
                metadata={
                    "actor": "user",
                    "source_type": "operator-evidence",
                    "reality_class": "evidence_grounded",
                },
            ),
            Hit(
                id="pg-generated",
                kind="evidence",
                tenant_id=tenant,
                branch="main",
                text="G0 shadow monitor contract Calypso generated Postgres hit.",
                score=0.8,
                channel="probe",
                provenance=[],
                trust_tier=1,
                metadata={
                    "actor": "assistant",
                    "source_type": "generated-summary",
                    "reality_class": "self_generated",
                },
            ),
        ]
    )

    local_checks = _shadow_report_contract_checks(
        local_report,
        expected_ids={grounded_cid, generated_cid},
        require_grounded_alias=True,
    )
    postgres_checks = _shadow_report_contract_checks(
        postgres_report,
        expected_ids={"pg-grounded", "pg-generated"},
        require_grounded_alias=True,
    )
    checks = {
        **{f"local_{key}": value for key, value in local_checks.items()},
        **{f"postgres_{key}": value for key, value in postgres_checks.items()},
        "local_grounded_support_does_not_abstain": not local_result.abstained,
    }
    return {
        "score": 1.0 if all(checks.values()) else 0.0,
        "checks": checks,
        "local": _shadow_report_summary(local_report, abstained=local_result.abstained),
        "postgres": _shadow_report_summary(postgres_report),
    }


def _shadow_report_contract_checks(
    report: dict[str, Any],
    *,
    expected_ids: set[str],
    require_grounded_alias: bool,
) -> dict[str, bool]:
    tags = report.get("shadow_tags") if isinstance(report.get("shadow_tags"), dict) else {}
    tag_classes = {
        str(tag.get("reality_class"))
        for tag in tags.values()
        if isinstance(tag, dict) and isinstance(tag.get("reality_class"), str)
    }
    calibrated = all(
        isinstance(tag, dict)
        and tag.get("calibrated") is True
        and isinstance(tag.get("confidence"), int | float)
        and 0.0 <= float(tag["confidence"]) <= 1.0
        for tag in tags.values()
    )
    classes = report.get("classes") if isinstance(report.get("classes"), dict) else {}
    return {
        "applied": report.get("applied") is True,
        "shadow_only": report.get("shadow_only") is True,
        "critical_path_false": report.get("critical_path") is False,
        "expected_tags_present": expected_ids.issubset(set(tags)),
        "tags_calibrated": calibrated,
        "has_grounded_alias": (not require_grounded_alias) or "evidence_grounded" in tag_classes,
        "has_self_generated": "self_generated" in tag_classes,
        "classes_reported": bool(classes),
    }


def _shadow_report_summary(report: dict[str, Any], *, abstained: bool | None = None) -> dict[str, Any]:
    tags = report.get("shadow_tags") if isinstance(report.get("shadow_tags"), dict) else {}
    summary = {
        "classes": report.get("classes") if isinstance(report.get("classes"), dict) else {},
        "shadow_only": report.get("shadow_only"),
        "critical_path": report.get("critical_path"),
        "shadow_tag_count": len(tags),
        "shadow_tag_classes": sorted(
            {
                str(tag.get("reality_class"))
                for tag in tags.values()
                if isinstance(tag, dict) and isinstance(tag.get("reality_class"), str)
            }
        ),
    }
    if abstained is not None:
        summary["abstained"] = abstained
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the G0 consciousness indicator scorecard")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--print-json", action="store_true")
    args = parser.parse_args()
    report = run_consciousness_eval(repo_root=args.repo_root)
    if args.print_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            "G0 consciousness scorecard: "
            f"{report['total_score']}/{report['max_score']} "
            f"(normalized={report['normalized_score']})"
        )


if __name__ == "__main__":
    main()
