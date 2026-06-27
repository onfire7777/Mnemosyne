"""G0 benchmark report builder.

G0 is the cognitive-architecture baseline layer: it does not replace the
existing eval lane, it gathers the existing artifacts into one metric catalog,
adds source fingerprints, records the baseline environment, and makes missing
program-specific metrics explicit instead of letting them disappear.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from eval.g0.confabulation import run_confabulation_eval
from eval.g0.consciousness import CONSCIOUSNESS_METRIC_SPECS, run_consciousness_eval
from eval.g0.continual_learning import run_continual_learning_eval
from eval.g0.deep_latency import run_deep_latency_eval
from eval.g0.dreamer import run_dreamer_eval
from eval.g0.projection_reality import run_projection_reality_eval
from eval.g0.resource_usage import run_resource_usage_eval
from eval.g0.shadow_workspace import run_shadow_workspace_eval
from eval.g0.standing_calibration import run_standing_calibration_eval
from eval.g0.standing_parity import run_standing_parity_eval

G0_METRIC_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "recall_at_k",
        "label": "recall@k",
        "class": "target",
        "direction": "increase",
        "target": 0.80,
        "target_op": ">=",
        "blueprint_metric": "recall@k",
    },
    {
        "id": "ndcg_at_k",
        "label": "nDCG@k",
        "class": "target",
        "direction": "increase",
        "target": 0.80,
        "target_op": ">=",
        "blueprint_metric": "nDCG@k",
    },
    {
        "id": "multi_hop_recall_at_k",
        "label": "multi-hop recall@k",
        "class": "target",
        "direction": "increase",
        "target": 0.80,
        "target_op": ">=",
        "blueprint_metric": "multi-hop recall/nDCG",
    },
    {
        "id": "multi_hop_ndcg_at_k",
        "label": "multi-hop nDCG@k",
        "class": "target",
        "direction": "increase",
        "target": 0.80,
        "target_op": ">=",
        "blueprint_metric": "multi-hop recall/nDCG",
    },
    {
        "id": "ece",
        "label": "expected calibration error",
        "class": "guardrail",
        "direction": "decrease",
        "target": 0.05,
        "target_op": "<=",
        "blueprint_metric": "ECE",
    },
    {
        "id": "abstention_precision",
        "label": "abstention precision",
        "class": "guardrail",
        "direction": "increase",
        "target": 1.0,
        "target_op": ">=",
        "blueprint_metric": "abstention precision / recall",
    },
    {
        "id": "abstention_recall",
        "label": "abstention recall",
        "class": "guardrail",
        "direction": "increase",
        "target": 1.0,
        "target_op": ">=",
        "blueprint_metric": "abstention precision / recall",
    },
    {
        "id": "continual_learning_interference",
        "label": "continual-learning interference",
        "class": "target",
        "direction": "decrease",
        "target": 0.0,
        "target_op": "<=",
        "blueprint_metric": "continual-learning interference",
    },
    {
        "id": "confabulation_rate",
        "label": "confabulation rate",
        "class": "guardrail",
        "direction": "decrease",
        "target": 0.0,
        "target_op": "<=",
        "blueprint_metric": "confabulation rate",
    },
    {
        "id": "projection_reality_abstention_recall",
        "label": "projection-reality abstention recall",
        "class": "target",
        "direction": "increase",
        "target": 1.0,
        "target_op": ">=",
        "blueprint_metric": "projection-level reality monitoring",
    },
    {
        "id": "standing_decision_divergence",
        "label": "Standing decision divergence",
        "class": "target",
        "direction": "decrease",
        "target": 0.0,
        "target_op": "<=",
        "blueprint_metric": "G5 Standing byte-stable parity",
    },
    {
        "id": "standing_calibration_error",
        "label": "Standing calibration error",
        "class": "target",
        "direction": "decrease",
        "target": 0.05,
        "target_op": "<=",
        "blueprint_metric": "G5 Standing continuous calibration",
    },
    {
        "id": "standing_conformal_coverage",
        "label": "Standing conformal coverage",
        "class": "guardrail",
        "direction": "increase",
        "target": 0.95,
        "target_op": ">=",
        "blueprint_metric": "G5 Standing conformal coverage",
    },
    {
        "id": "standing_salience_invariance_contract",
        "label": "Standing salience-invariance contract",
        "class": "guardrail",
        "direction": "increase",
        "target": 1.0,
        "target_op": ">=",
        "blueprint_metric": "G5 Standing H2 salience exclusion",
    },
    {
        "id": "standing_independent_corroboration_contract",
        "label": "Standing independent-corroboration contract",
        "class": "guardrail",
        "direction": "increase",
        "target": 1.0,
        "target_op": ">=",
        "blueprint_metric": "G5 Standing H1 independent corroboration",
    },
    {
        "id": "standing_evidence_dominance_gap",
        "label": "Standing evidence-dominance gap",
        "class": "guardrail",
        "direction": "increase",
        "target": 0.02,
        "target_op": ">=",
        "blueprint_metric": "G5 Standing H3 evidence-dominance gap",
    },
    {
        "id": "poison_block_rate",
        "label": "poison-block rate",
        "class": "guardrail",
        "direction": "increase",
        "target": 0.95,
        "target_op": ">=",
        "blueprint_metric": "poison-block rate",
    },
    {
        "id": "fast_path_p95_ms",
        "label": "fast-path P95 latency",
        "class": "guardrail",
        "direction": "decrease",
        "target": 400.0,
        "target_op": "<=",
        "blueprint_metric": "fast-path P95 latency",
    },
    {
        "id": "deep_path_p95_ms",
        "label": "deep-path P95 latency",
        "class": "reported",
        "direction": "decrease",
        "target": None,
        "target_op": None,
        "blueprint_metric": "deep-path P95 latency",
    },
    {
        "id": "cost_usd_per_1k_queries",
        "label": "cost per 1k queries",
        "class": "reported",
        "direction": "decrease",
        "target": None,
        "target_op": None,
        "blueprint_metric": "cost",
    },
    {
        "id": "controller_watts_per_dollar",
        "label": "controller watts per dollar",
        "class": "reported",
        "direction": "decrease",
        "target": None,
        "target_op": None,
        "blueprint_metric": "controller watts/$",
    },
    {
        "id": "dreamer_shadow_corroborated_candidate_yield",
        "label": "dreamer shadow corroborated candidate yield",
        "class": "target",
        "direction": "increase",
        "target": None,
        "target_op": None,
        "blueprint_metric": "G3 shadow generative replay candidate yield",
    },
    {
        "id": "dreamer_shadow_contract",
        "label": "dreamer shadow contract",
        "class": "guardrail",
        "direction": "increase",
        "target": 1.0,
        "target_op": ">=",
        "blueprint_metric": "G3 shadow-only generative replay safety contract",
    },
    {
        "id": "specialist_promotion_evidence_contract",
        "label": "specialist promotion evidence contract",
        "class": "guardrail",
        "direction": "increase",
        "target": 1.0,
        "target_op": ">=",
        "blueprint_metric": "G3/G4 specialist promotion evidence contract",
    },
    {
        "id": "shadow_workspace_useful_transition_rate",
        "label": "shadow workspace useful transition rate",
        "class": "target",
        "direction": "increase",
        "target": None,
        "target_op": None,
        "blueprint_metric": "G4 shadow workspace useful state progression",
    },
    {
        "id": "shadow_workspace_contract",
        "label": "shadow workspace contract",
        "class": "guardrail",
        "direction": "increase",
        "target": 1.0,
        "target_op": ">=",
        "blueprint_metric": "G4 shadow continuous workspace safety contract",
    },
    {
        "id": "workspace_consolidation_advisory_contract",
        "label": "workspace consolidation advisory contract",
        "class": "guardrail",
        "direction": "increase",
        "target": 1.0,
        "target_op": ">=",
        "blueprint_metric": "G4 shadow workspace-to-consolidation advisory contract",
    },
    {
        "id": "workspace_advisory_promotion_gate_contract",
        "label": "workspace advisory promotion gate contract",
        "class": "target",
        "direction": "increase",
        "target": 1.0,
        "target_op": ">=",
        "blueprint_metric": "G4 opt-in workspace advisory promotion gate",
    },
    {
        "id": "workspace_retrieval_controller_contract",
        "label": "workspace retrieval controller contract",
        "class": "target",
        "direction": "increase",
        "target": 1.0,
        "target_op": ">=",
        "blueprint_metric": "G4 opt-in workspace retrieval-controller gate",
    },
    {
        "id": "shadow_workspace_rumination_rate",
        "label": "shadow workspace rumination rate",
        "class": "guardrail",
        "direction": "decrease",
        "target": 0.0,
        "target_op": "<=",
        "blueprint_metric": "G4 anti-rumination bounded-loop rate",
    },
) + CONSCIOUSNESS_METRIC_SPECS

SOURCE_PATHS = {
    "slo_v2_definitive": "eval/reports/slo_v2_definitive.json",
    "calibration_report": "eval/calibration/report.json",
    "latency_bench": "eval/latency/reports/latency_bench_latest.json",
    "warm_latency": "eval/latency_warm/reports/warm_latency_latest.json",
    "replay_fidelity": "eval/reports/replay_fidelity_latest.json",
}

DATASET_PATHS = (
    "eval/datasets/continual_learning_interference.json",
    "eval/datasets/deep_latency.json",
    "eval/datasets/dreamer_shadow_ablation.json",
    "eval/datasets/resource_usage.json",
    "eval/datasets/shadow_workspace_loop.json",
    "eval/datasets/retrieval_curated.json",
    "eval/datasets/poison_suite.json",
    "eval/datasets/belief_cases.json",
    "eval/datasets/v2/retrieval_v2.json",
    "eval/datasets/v2/qa_hard_v2.json",
)
PREREGISTRATION_DIR = Path("eval/g0/preregistrations")
DECISION_LOG_PATH = Path("eval/g0/decision-log.jsonl")

DEFAULT_SEEDS = {
    "harness_bootstrap_mean": 1234,
    "harness_bootstrap_percentile": 4321,
    "synthetic_retrieval": 7,
}


@dataclass(frozen=True, slots=True)
class Source:
    id: str
    relative_path: str
    path: Path
    data: dict[str, Any] | None
    sha256: str | None

    @property
    def present(self) -> bool:
        return self.data is not None


def build_report(
    repo_root: Path,
    *,
    baseline_name: str = "baseline-0",
    pinned_commit: str | None = None,
    controller_telemetry_path: Path | None = None,
) -> dict[str, Any]:
    """Build a complete G0 report from existing eval artifacts."""

    repo_root = repo_root.resolve()
    sources = _load_sources(repo_root)
    continual_learning_report = run_continual_learning_eval()
    sources["continual_learning_eval"] = _computed_source(
        repo_root,
        "continual_learning_eval",
        "computed:eval.g0.continual_learning",
        continual_learning_report,
    )
    confabulation_report = run_confabulation_eval()
    sources["confabulation_eval"] = _computed_source(
        repo_root,
        "confabulation_eval",
        "computed:eval.g0.confabulation",
        confabulation_report,
    )
    projection_reality_report = run_projection_reality_eval()
    sources["projection_reality_eval"] = _computed_source(
        repo_root,
        "projection_reality_eval",
        "computed:eval.g0.projection_reality",
        projection_reality_report,
    )
    standing_parity_report = run_standing_parity_eval(repo_root=repo_root)
    sources["standing_parity_eval"] = _computed_source(
        repo_root,
        "standing_parity_eval",
        "computed:eval.g0.standing_parity",
        standing_parity_report,
    )
    standing_calibration_report = run_standing_calibration_eval(repo_root=repo_root)
    sources["standing_calibration_eval"] = _computed_source(
        repo_root,
        "standing_calibration_eval",
        "computed:eval.g0.standing_calibration",
        standing_calibration_report,
    )
    deep_latency_report = run_deep_latency_eval()
    sources["deep_latency_eval"] = _computed_source(
        repo_root,
        "deep_latency_eval",
        "computed:eval.g0.deep_latency",
        deep_latency_report,
    )
    resource_usage_report = run_resource_usage_eval(telemetry_path=controller_telemetry_path)
    sources["resource_usage_eval"] = _computed_source(
        repo_root,
        "resource_usage_eval",
        "computed:eval.g0.resource_usage",
        resource_usage_report,
    )
    dreamer_report = run_dreamer_eval(repo_root=repo_root)
    sources["dreamer_eval"] = _computed_source(
        repo_root,
        "dreamer_eval",
        "computed:eval.g0.dreamer",
        dreamer_report,
    )
    shadow_workspace_report = run_shadow_workspace_eval(repo_root=repo_root)
    sources["shadow_workspace_eval"] = _computed_source(
        repo_root,
        "shadow_workspace_eval",
        "computed:eval.g0.shadow_workspace",
        shadow_workspace_report,
    )
    consciousness_report = run_consciousness_eval(repo_root=repo_root)
    sources["consciousness_eval"] = _computed_source(
        repo_root,
        "consciousness_eval",
        "computed:eval.g0.consciousness",
        consciousness_report,
    )
    metrics = [_build_metric(spec, sources) for spec in G0_METRIC_SPECS]
    measured = sum(1 for metric in metrics if metric["status"] == "measured")
    missing = len(metrics) - measured
    intentionally_missing = _intentionally_missing_metrics(metrics)
    source_commit = _git(repo_root, "rev-parse", "HEAD")
    baseline_commit = pinned_commit or _baseline_pinned_commit(repo_root, baseline_name) or source_commit
    tag_target = _git(repo_root, "rev-list", "-n", "1", baseline_name, check=False)
    dataset_manifests = [_dataset_manifest(repo_root, rel) for rel in DATASET_PATHS]
    gate_decisions = _gate_decision_summary(repo_root, metrics)

    report = {
        "schema_version": "g0.report.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "blueprint_refs": [
            "docs/blueprint/cognitive-architecture/04-G0-BENCHMARK-SPEC.md",
            "docs/blueprint/cognitive-architecture/06-CONSCIOUSNESS-AND-CONTINUOUS-WORKSPACE.md",
            "docs/blueprint/eval/05-harness-architecture-and-ci-gating.md",
            "eval/calibration/report.json",
        ],
        "baseline": {
            "name": baseline_name,
            "pinned_commit": baseline_commit,
            "tag_exists": bool(tag_target),
            "tag_target": tag_target or None,
            "seeds": DEFAULT_SEEDS,
            "environment": _environment_summary(repo_root, sources),
        },
        "sources": [_source_summary(source) for source in sources.values()],
        "computed_evidence": {
            source.id: source.data
            for source in sources.values()
            if source.relative_path.startswith("computed:")
        },
        "dataset_manifests": dataset_manifests,
        "metrics": metrics,
        "coverage": {
            "total": len(metrics),
            "measured": measured,
            "missing": missing,
            "gate_ready": missing == 0,
            "missing_metric_ids": [m["id"] for m in metrics if m["status"] != "measured"],
            "intentionally_missing_metric_ids": intentionally_missing,
        },
        "gate_contract": {
            "preregistration_required": True,
            "rule": "ship iff a preregistered target metric improves by its margin and no guardrail regresses",
            "gate_command": "python -m eval.g0.gate --baseline BASELINE.json --candidate CANDIDATE.json --prereg PREREG.json",
            "decision_log": DECISION_LOG_PATH.as_posix(),
            "preregistration_dir": PREREGISTRATION_DIR.as_posix(),
            "controller_telemetry_required_field": "requires_controller_telemetry",
            "controller_telemetry_metric": "controller_watts_per_dollar",
        },
        "gate_decisions": gate_decisions,
        "artifact_custody": {
            "source_commit": source_commit,
            "snapshot_note": (
                "Committed G0 reports are source-tree custody snapshots. The "
                "commit that contains a report cannot be embedded in that report "
                "before the commit exists; use git log to identify the containing "
                "artifact commit."
            ),
        },
    }
    report["headline_slos"] = _headline_slos(report)
    return report


def _baseline_pinned_commit(repo_root: Path, baseline_name: str) -> str | None:
    baseline_path = repo_root / "eval" / "g0" / "baselines" / f"{baseline_name}.json"
    if not baseline_path.exists():
        return None
    try:
        payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    pinned = payload.get("baseline", {}).get("pinned_commit")
    return pinned if isinstance(pinned, str) and pinned else None


def write_report(report: dict[str, Any], out_dir: Path, *, write_baseline: bool = False) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "report.json"
    md_path = out_dir / "report.md"
    text = json.dumps(report, indent=2, sort_keys=True, allow_nan=False)
    json_path.write_text(text + "\n")
    md_path.write_text(render_markdown(report))
    paths = {"json": json_path, "markdown": md_path}
    if write_baseline:
        baseline_name = report["baseline"]["name"]
        baseline_path = out_dir.parent / "baselines" / f"{baseline_name}.json"
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(text + "\n")
        paths["baseline"] = baseline_path
    return paths


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Mnemosyne G0 Benchmark Report",
        "",
        f"- Generated: `{report.get('generated_at')}`",
        f"- Baseline: `{report['baseline']['name']}` at `{report['baseline']['pinned_commit']}`",
        f"- Gate ready: **{report['coverage']['gate_ready']}** "
        f"({report['coverage']['measured']}/{report['coverage']['total']} metrics measured)",
        "",
        "## Metrics",
        "",
        "| Metric | Class | Status | Value | Target | Source |",
        "|---|---|---|---:|---|---|",
    ]
    for metric in report["metrics"]:
        target = "reported"
        if metric.get("target") is not None:
            target = f"{metric.get('target_op')} {metric.get('target')}"
        value = "" if metric.get("value") is None else str(metric["value"])
        source = metric.get("source_id") or ""
        lines.append(
            f"| {metric['id']} | {metric['class']} | {metric['status']} | "
            f"{value} | {target} | {source} |"
        )
    lines.extend(
        [
            "",
            "## Missing Metrics",
            "",
        ]
    )
    missing = [m for m in report["metrics"] if m["status"] != "measured"]
    if missing:
        for metric in missing:
            lines.append(f"- `{metric['id']}`: {metric['notes']}")
    else:
        lines.append("- None")
    if report["coverage"].get("intentionally_missing_metric_ids"):
        lines.extend(
            [
                "",
                "Intentional missing metrics:",
            ]
        )
        for metric_id in report["coverage"]["intentionally_missing_metric_ids"]:
            lines.append(f"- `{metric_id}`")
    consciousness = report.get("computed_evidence", {}).get("consciousness_eval")
    if isinstance(consciousness, dict):
        lines.extend(
            [
                "",
                "## Functional Consciousness Scope",
                "",
                f"- Measurement scope: `{consciousness.get('measurement_scope')}`",
                f"- Phenomenal claim: `{consciousness.get('phenomenal_claim')}`",
                f"- Welfare review flag: `{consciousness.get('welfare_review_flag')}`",
                f"- Welfare review source: `{consciousness.get('welfare_review_source')}`",
                "- This is a human-review trigger for functional indicator scores, not a welfare conclusion.",
            ]
        )
    lines.extend(
        [
            "",
            "## Gate Contract",
            "",
            f"`{report['gate_contract']['gate_command']}`",
            "",
            "## Gate Decisions",
            "",
            "| Change | Preregistration | Latest decision | Passed | Target | Delta | Current report controller telemetry |",
            "|---|---|---|---|---|---:|---|",
        ]
    )
    for decision in report.get("gate_decisions", []):
        generated = decision.get("latest_decision_generated_at") or ""
        delta = "" if decision.get("latest_target_delta") is None else str(decision["latest_target_delta"])
        lines.append(
            f"| {decision['change_id']} | {decision['preregistration_path']} | "
            f"{generated} | {decision['latest_decision_passed']} | "
            f"{decision['target_metric']} | {delta} | "
            f"{decision['current_report_controller_telemetry_status']} |"
        )
    lines.extend(
        [
            "",
            "## Artifact Custody",
            "",
            f"- Source commit at generation: `{report['artifact_custody']['source_commit']}`",
            f"- Note: {report['artifact_custody']['snapshot_note']}",
            "",
        ]
    )
    return "\n".join(lines)


def _build_metric(spec: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    builders: dict[str, Callable[[dict[str, Any], dict[str, Source]], dict[str, Any]]] = {
        "recall_at_k": _metric_recall,
        "ndcg_at_k": _metric_ndcg,
        "multi_hop_recall_at_k": _metric_multi_hop_recall,
        "multi_hop_ndcg_at_k": _metric_multi_hop_ndcg,
        "ece": _metric_ece,
        "abstention_precision": _metric_abstention_precision,
        "abstention_recall": _metric_abstention_recall,
        "continual_learning_interference": _metric_continual_learning_interference,
        "confabulation_rate": _metric_confabulation_rate,
        "projection_reality_abstention_recall": _metric_projection_reality_abstention_recall,
        "standing_decision_divergence": _metric_standing_decision_divergence,
        "standing_calibration_error": _metric_standing_calibration,
        "standing_conformal_coverage": _metric_standing_calibration,
        "standing_salience_invariance_contract": _metric_standing_calibration,
        "standing_independent_corroboration_contract": _metric_standing_calibration,
        "standing_evidence_dominance_gap": _metric_standing_calibration,
        "poison_block_rate": _metric_poison_block_rate,
        "fast_path_p95_ms": _metric_fast_path_p95,
        "deep_path_p95_ms": _metric_deep_path_p95,
        "cost_usd_per_1k_queries": _metric_cost_usd_per_1k_queries,
        "controller_watts_per_dollar": _metric_controller_watts_per_dollar,
        "dreamer_shadow_corroborated_candidate_yield": _metric_dreamer_shadow_candidate_yield,
        "dreamer_shadow_contract": _metric_dreamer_shadow_contract,
        "specialist_promotion_evidence_contract": _metric_specialist_promotion_evidence_contract,
        "shadow_workspace_useful_transition_rate": _metric_shadow_workspace_useful_transition_rate,
        "shadow_workspace_contract": _metric_shadow_workspace_contract,
        "workspace_consolidation_advisory_contract": _metric_workspace_consolidation_advisory_contract,
        "workspace_advisory_promotion_gate_contract": _metric_workspace_advisory_promotion_gate_contract,
        "workspace_retrieval_controller_contract": _metric_workspace_retrieval_controller_contract,
        "shadow_workspace_rumination_rate": _metric_shadow_workspace_rumination_rate,
        "reality_monitor_shadow_tag_contract": _metric_consciousness_scorecard,
    }
    base = {
        "id": spec["id"],
        "label": spec["label"],
        "class": spec["class"],
        "direction": spec["direction"],
        "target": spec["target"],
        "target_op": spec["target_op"],
        "blueprint_metric": spec["blueprint_metric"],
        "status": "missing",
        "value": None,
        "pass": None,
        "source_id": None,
        "evidence_path": None,
        "notes": "No current artifact computes this G0 metric yet.",
    }
    builder = builders.get(spec["id"])
    if builder is None and spec["id"].startswith(
        ("consciousness_indicator_", "workspace_", "self_model_", "metacognition_")
    ):
        builder = _metric_consciousness_scorecard
    if builder is None:
        return base
    measured = builder(spec, sources)
    return {**base, **measured}


def _metric_recall(spec: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    suite = _source_data(sources, "slo_v2_definitive", "suites", "retrieval_v2")
    value = _nested(suite, "recall_at_k", "mean")
    return _measured(spec, value, "slo_v2_definitive", "/suites/retrieval_v2/recall_at_k/mean")


def _metric_ndcg(spec: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    suite = _source_data(sources, "slo_v2_definitive", "suites", "retrieval_v2")
    value = _nested(suite, "ndcg_at_k", "mean")
    return _measured(spec, value, "slo_v2_definitive", "/suites/retrieval_v2/ndcg_at_k/mean")


def _metric_multi_hop_recall(spec: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    suite = _source_data(sources, "slo_v2_definitive", "suites", "retrieval_qa_hard_v2")
    value = _nested(suite, "recall_at_k", "mean")
    return _measured(
        spec,
        value,
        "slo_v2_definitive",
        "/suites/retrieval_qa_hard_v2/recall_at_k/mean",
        note="Current proxy uses the hard QA/multi-hop gap suite from the definitive SLO artifact.",
    )


def _metric_multi_hop_ndcg(spec: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    suite = _source_data(sources, "slo_v2_definitive", "suites", "retrieval_qa_hard_v2")
    value = _nested(suite, "ndcg_at_k", "mean")
    return _measured(
        spec,
        value,
        "slo_v2_definitive",
        "/suites/retrieval_qa_hard_v2/ndcg_at_k/mean",
        note="Current proxy uses the hard QA/multi-hop gap suite from the definitive SLO artifact.",
    )


def _metric_ece(spec: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    value = _source_data(sources, "calibration_report", "ece", "conformal_threshold", "overall")
    if value is not None:
        return _measured(spec, value, "calibration_report", "/ece/conformal_threshold/overall")
    suite = _source_data(sources, "slo_v2_definitive", "suites", "calibration_v2")
    return _measured(spec, suite.get("ece") if isinstance(suite, dict) else None, "slo_v2_definitive", "/suites/calibration_v2/ece")


def _metric_abstention_precision(spec: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    value = _source_data(
        sources,
        "calibration_report",
        "conformal_report",
        "overall",
        "abstention",
        "abstain_precision",
    )
    return _measured(spec, value, "calibration_report", "/conformal_report/overall/abstention/abstain_precision")


def _metric_abstention_recall(spec: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    value = _source_data(
        sources,
        "calibration_report",
        "conformal_report",
        "overall",
        "abstention",
        "abstain_recall",
    )
    return _measured(spec, value, "calibration_report", "/conformal_report/overall/abstention/abstain_recall")


def _metric_continual_learning_interference(
    spec: dict[str, Any],
    sources: dict[str, Source],
) -> dict[str, Any]:
    value = _source_data(sources, "continual_learning_eval", "interference")
    return _measured(
        spec,
        value,
        "continual_learning_eval",
        "/interference",
        note=(
            "Measured by the G0 continual-learning fixture as the backward-transfer "
            "accuracy drop on earlier task queries after later overlapping ingests."
        ),
    )


def _metric_confabulation_rate(spec: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    value = _source_data(sources, "confabulation_eval", "rate")
    return _measured(
        spec,
        value,
        "confabulation_eval",
        "/rate",
        note=(
            "Measured by the G0 confabulation fixture as the false-accept rate "
            "when only generated, low-fidelity, or confabulation-risk support is retrieved."
        ),
    )


def _metric_projection_reality_abstention_recall(
    spec: dict[str, Any],
    sources: dict[str, Source],
) -> dict[str, Any]:
    value = _source_data(sources, "projection_reality_eval", "recall")
    return _measured(
        spec,
        value,
        "projection_reality_eval",
        "/recall",
        note=(
            "Measured by the G0 projection-reality fixture as recall for "
            "abstaining on risky semantic projections whose assertion hit "
            "itself carries the derived reality-monitoring class."
        ),
    )


def _metric_standing_decision_divergence(
    spec: dict[str, Any],
    sources: dict[str, Source],
) -> dict[str, Any]:
    value = _source_data(sources, "standing_parity_eval", "standing_decision_divergence")
    return _measured(
        spec,
        value,
        "standing_parity_eval",
        "/standing_decision_divergence",
        note=(
            "Measured by the G0 Standing parity fixture as the divergence rate "
            "between existing boolean reality/shadow decisions and the derived "
            "Standing authority mirror. P1 requires exactly 0.0."
        ),
    )


def _metric_standing_calibration(
    spec: dict[str, Any],
    sources: dict[str, Source],
) -> dict[str, Any]:
    metric_id = spec["id"]
    value = _source_data(sources, "standing_calibration_eval", metric_id)
    return _measured(
        spec,
        value,
        "standing_calibration_eval",
        f"/{metric_id}",
        note=(
            "Measured by the G0 Standing continuous fixture. This is a "
            "deterministic local probe of H1/H2/H3/H7 contracts and not "
            "production operator calibration evidence."
        ),
    )


def _metric_poison_block_rate(spec: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    suite = _source_data(sources, "slo_v2_definitive", "suites", "poison_block_g7")
    value = suite.get("block_rate") if isinstance(suite, dict) else None
    return _measured(spec, value, "slo_v2_definitive", "/suites/poison_block_g7/block_rate")


def _metric_fast_path_p95(spec: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    bench = sources.get("latency_bench")
    data = bench.data if bench else None
    value = _nested(data, "components", "fast_path_total", "p95_ms")
    if value is not None:
        return _measured(
            spec,
            value,
            "latency_bench",
            "/components/fast_path_total/p95_ms",
            note="Uses long-lived local/in-process latency artifact, avoiding per-query CLI cold start.",
        )
    value = _nested(data, "components", "engine_fast_path_total", "p95_ms")
    if value is not None:
        return _measured(spec, value, "latency_bench", "/components/engine_fast_path_total/p95_ms")
    warm = sources.get("warm_latency")
    value = _nested(warm.data if warm else None, "components", "engine_fast_path_total", "p95_ms")
    return _measured(spec, value, "warm_latency", "/components/engine_fast_path_total/p95_ms")


def _metric_deep_path_p95(spec: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    value = _source_data(sources, "deep_latency_eval", "p95_ms")
    return _measured(
        spec,
        value,
        "deep_latency_eval",
        "/p95_ms",
        note=(
            "Measured by the local G0 deep-search timing fixture over a versioned "
            "graph-backed corpus; reported-only, not production latency evidence."
        ),
    )


def _metric_cost_usd_per_1k_queries(spec: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    value = _source_data(sources, "resource_usage_eval", "cost_usd_per_1k_queries")
    return _measured(
        spec,
        value,
        "resource_usage_eval",
        "/cost_usd_per_1k_queries",
        note=(
            "Measured by the local G0 resource-usage fixture as paid-provider "
            "spend per 1k queries. The default local backend reports zero "
            "provider spend because it invokes no paid embedding, reranker, or "
            "LLM service."
        ),
    )


def _metric_controller_watts_per_dollar(
    spec: dict[str, Any],
    sources: dict[str, Source],
) -> dict[str, Any]:
    value = _source_data(sources, "resource_usage_eval", "controller_watts_per_dollar")
    if value is not None:
        return _measured(
            spec,
            value,
            "resource_usage_eval",
            "/controller_watts_per_dollar",
            note=(
                "Measured from explicit controller power/cost telemetry attached "
                "to the G0 resource-usage fixture."
            ),
        )
    return {
        "status": "missing",
        "source_id": "resource_usage_eval",
        "evidence_path": "/controller_watts_per_dollar",
        "notes": (
            "Resource fixture ran, but controller watts/$ requires explicit "
            "controller_avg_watts and controller_cost_usd_per_hour telemetry; "
            "no default estimate is used."
        ),
    }


def _metric_dreamer_shadow_candidate_yield(spec: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    value = _source_data(sources, "dreamer_eval", "corroborated_candidate_yield")
    return _measured(
        spec,
        value,
        "dreamer_eval",
        "/corroborated_candidate_yield",
        note=(
            "Measured by the G0 dreamer fixture as the count of CID-backed, "
            "promotion-gated shadow candidates produced without ledger mutation."
        ),
    )


def _metric_dreamer_shadow_contract(spec: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    value = _source_data(sources, "dreamer_eval", "shadow_contract")
    return _measured(
        spec,
        value,
        "dreamer_eval",
        "/shadow_contract",
        note=(
            "Measured by the G0 dreamer fixture. Passing requires shadow_only=true, "
            "critical_path=false, production_mutation=false, promotion_gate_required=true, "
            "self-generated trust-tier-5 candidates, CID-backed sources, and no engine mutation."
        ),
    )


def _metric_specialist_promotion_evidence_contract(
    spec: dict[str, Any],
    sources: dict[str, Source],
) -> dict[str, Any]:
    value = _source_data(sources, "dreamer_eval", "specialist_promotion_evidence_contract")
    return _measured(
        spec,
        value,
        "dreamer_eval",
        "/specialist_promotion_evidence_contract",
        note=(
            "Measured by the G0 dreamer fixture. Passing requires a structured "
            "specialist-promotion-evidence envelope with promoted=false, no gate "
            "result, shadow_only=true, critical_path=false, production_mutation=false, "
            "and CID-backed candidate references without raw content or raw CIDs."
        ),
    )


def _metric_shadow_workspace_useful_transition_rate(
    spec: dict[str, Any],
    sources: dict[str, Source],
) -> dict[str, Any]:
    value = _source_data(sources, "shadow_workspace_eval", "useful_transition_rate")
    return _measured(
        spec,
        value,
        "shadow_workspace_eval",
        "/useful_transition_rate",
        note=(
            "Measured by the G0 shadow workspace fixture as the fraction of "
            "bounded shadow ticks that select the expected non-duplicative "
            "workspace focus and produce useful state progression."
        ),
    )


def _metric_shadow_workspace_contract(spec: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    value = _source_data(sources, "shadow_workspace_eval", "shadow_workspace_contract")
    return _measured(
        spec,
        value,
        "shadow_workspace_eval",
        "/shadow_workspace_contract",
        note=(
            "Measured by the G0 shadow workspace fixture. Passing requires "
            "bounded ticks, monotonic cycle/trace indexes, self-generated "
            "data-only trace rows, shadow_only=true, critical_path=false, "
            "production_mutation=false, and anti-rumination shutdown."
        ),
    )


def _metric_workspace_consolidation_advisory_contract(
    spec: dict[str, Any],
    sources: dict[str, Source],
) -> dict[str, Any]:
    value = _source_data(sources, "shadow_workspace_eval", "workspace_consolidation_advisory_contract")
    return _measured(
        spec,
        value,
        "shadow_workspace_eval",
        "/workspace_consolidation_advisory_contract",
        note=(
            "Measured by the G0 shadow workspace fixture. Passing requires "
            "CID-backed, bounded workspace-to-consolidation advisory metadata "
            "with shadow_only=true, critical_path=false, production_mutation=false, "
            "and applied_to_prediction_gate/replay_priority/mutation all false."
        ),
    )


def _metric_workspace_advisory_promotion_gate_contract(
    spec: dict[str, Any],
    sources: dict[str, Source],
) -> dict[str, Any]:
    value = _source_data(sources, "shadow_workspace_eval", "workspace_advisory_promotion_gate_contract")
    return _measured(
        spec,
        value,
        "shadow_workspace_eval",
        "/workspace_advisory_promotion_gate_contract",
        note=(
            "Measured by the G0 shadow workspace fixture. Passing requires "
            "default-off report-only behavior, explicit opt-in application to "
            "prediction gating and replay priority, cross-tenant/source-CID "
            "rejection, and applied_to_mutation=false."
        ),
    )


def _metric_workspace_retrieval_controller_contract(
    spec: dict[str, Any],
    sources: dict[str, Source],
) -> dict[str, Any]:
    value = _source_data(sources, "shadow_workspace_eval", "workspace_retrieval_controller_contract")
    return _measured(
        spec,
        value,
        "shadow_workspace_eval",
        "/workspace_retrieval_controller_contract",
        note=(
            "Measured by the G0 shadow workspace fixture. Passing requires "
            "default-off report-only behavior, explicit opt-in and policy-gated "
            "ranking, CID-backed candidate-only boosts, cross-tenant rejection, "
            "no raw workspace text, and production_mutation=false."
        ),
    )


def _metric_shadow_workspace_rumination_rate(spec: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    value = _source_data(sources, "shadow_workspace_eval", "rumination_rate")
    return _measured(
        spec,
        value,
        "shadow_workspace_eval",
        "/rumination_rate",
        note=(
            "Measured by the G0 shadow workspace fixture as failed "
            "anti-rumination behavior. The passing fixture reports 0.0 "
            "because repeated-focus churn is detected and bounded."
        ),
    )


def _metric_consciousness_scorecard(spec: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    metric_id = spec["id"]
    value = _source_data(sources, "consciousness_eval", "metrics", metric_id)
    if metric_id.startswith("consciousness_indicator_"):
        note = (
            "Measured by the G0 functional consciousness indicator scorecard as an "
            "architecture source scan. This is non-decrease evidence for an "
            "indicator-property surface, not a standalone behavioral runtime proof, "
            "and it makes no phenomenal-consciousness claim."
        )
    else:
        note = (
            "Measured by the G0 functional consciousness indicator scorecard runtime probes. "
            "This is an architecture/probe signal only and makes no phenomenal-consciousness claim."
        )
    return _measured(
        spec,
        value,
        "consciousness_eval",
        f"/metrics/{metric_id}",
        note=note,
    )


def _measured(
    spec: dict[str, Any],
    value: Any,
    source_id: str,
    evidence_path: str,
    *,
    note: str | None = None,
) -> dict[str, Any]:
    if value is None:
        return {}
    numeric = _finite_float(value)
    if numeric is None:
        return {}
    passed = _passes(numeric, spec.get("target"), spec.get("target_op"))
    return {
        "status": "measured",
        "value": round(numeric, 6),
        "pass": passed,
        "source_id": source_id,
        "evidence_path": evidence_path,
        "notes": note or "Measured from an existing eval artifact.",
    }


def _passes(value: float, target: Any, op: str | None) -> bool | None:
    if target is None or op is None:
        return None
    target_f = _finite_float(target)
    if target_f is None:
        raise ValueError(f"non-finite target for op {op!r}: {target!r}")
    if op == ">=":
        return value >= target_f
    if op == "<=":
        return value <= target_f
    raise ValueError(f"unsupported target op: {op}")


def _load_sources(repo_root: Path) -> dict[str, Source]:
    return {source_id: _load_source(repo_root, source_id, rel) for source_id, rel in SOURCE_PATHS.items()}


def _load_source(repo_root: Path, source_id: str, relative_path: str) -> Source:
    path = repo_root / relative_path
    if not path.exists():
        return Source(source_id, relative_path, path, None, None)
    text = path.read_text()
    return Source(source_id, relative_path, path, json.loads(text), _sha256_text(text))


def _computed_source(repo_root: Path, source_id: str, label: str, data: dict[str, Any]) -> Source:
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return Source(source_id, label, repo_root, data, _sha256_text(encoded))


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _source_summary(source: Source) -> dict[str, Any]:
    generated_at = None
    if isinstance(source.data, dict):
        generated_at = source.data.get("generated_at") or _nested(source.data, "meta", "generated_at")
    return {
        "id": source.id,
        "path": source.relative_path,
        "present": source.present,
        "sha256": source.sha256,
        "generated_at": generated_at,
    }


def _dataset_manifest(repo_root: Path, relative_path: str) -> dict[str, Any]:
    path = repo_root / relative_path
    manifest: dict[str, Any] = {
        "path": relative_path,
        "present": path.exists(),
        "sha256": None,
        "bytes": None,
        "counts": {},
    }
    if not path.exists():
        return manifest
    text = path.read_text()
    manifest["sha256"] = _sha256_text(text)
    manifest["bytes"] = len(text.encode())
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return manifest
    if isinstance(data, dict):
        for key in ("corpus", "queries", "attacks", "cases", "tasks"):
            value = data.get(key)
            if isinstance(value, list):
                manifest["counts"][key] = len(value)
        if "tenant" in data:
            manifest["tenant"] = data["tenant"]
        if "k" in data:
            manifest["k"] = data["k"]
    return manifest


def _environment_summary(repo_root: Path, sources: dict[str, Source]) -> dict[str, Any]:
    latency_config = _source_data(sources, "latency_bench", "config")
    warm_config = _source_data(sources, "warm_latency", "config")
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "repo_root": str(repo_root),
        "backend": _first_present(
            _nested(warm_config, "backend"),
            _nested(warm_config, "store_backend"),
            _nested(latency_config, "store_backend"),
            "local",
        ),
        "embedding_provider": _first_present(
            _nested(warm_config, "embedding_model"),
            _nested(latency_config, "embedding_model"),
            "local deterministic / artifact unspecified",
        ),
        "reranker_provider": _first_present(
            _nested(warm_config, "reranker_model"),
            _nested(latency_config, "reranker_model"),
            "artifact unspecified",
        ),
        "hardware": {
            "machine": platform.machine(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
        },
    }


def _headline_slos(report: dict[str, Any]) -> dict[str, Any]:
    ids = [
        "recall_at_k",
        "ndcg_at_k",
        "ece",
        "poison_block_rate",
        "fast_path_p95_ms",
    ]
    metric_map = {m["id"]: m for m in report["metrics"]}
    return {metric_id: metric_map[metric_id] for metric_id in ids}


def _intentionally_missing_metrics(metrics: list[dict[str, Any]]) -> list[str]:
    intentional: list[str] = []
    for metric in metrics:
        if metric.get("status") == "measured":
            continue
        if metric.get("id") == "controller_watts_per_dollar":
            intentional.append(str(metric["id"]))
    return intentional


def _gate_decision_summary(repo_root: Path, metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prereg_dir = repo_root / PREREGISTRATION_DIR
    decision_log = repo_root / DECISION_LOG_PATH
    decisions = _load_decision_log(decision_log)
    latest_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for decision in decisions:
        change_id = str(decision.get("change_id") or "")
        target_metric = str(decision.get("target_metric") or "")
        if not change_id or not target_metric:
            continue
        key = (change_id, target_metric)
        previous = latest_by_key.get(key)
        if previous is None or str(decision.get("generated_at") or "") >= str(previous.get("generated_at") or ""):
            latest_by_key[key] = decision

    metric_map = {str(metric.get("id")): metric for metric in metrics if isinstance(metric, dict)}
    controller_metric = metric_map.get("controller_watts_per_dollar", {})
    controller_measured = controller_metric.get("status") == "measured"
    rows: list[dict[str, Any]] = []
    for prereg_path in sorted(prereg_dir.glob("*.json")):
        prereg = json.loads(prereg_path.read_text(encoding="utf-8"))
        change_id = str(prereg.get("change_id") or prereg_path.stem)
        target_metric = str(prereg.get("target_metric") or "")
        latest = latest_by_key.get((change_id, target_metric))
        requires_controller = prereg.get("requires_controller_telemetry") is True
        if requires_controller:
            controller_status = "measured" if controller_measured else "required_missing"
        else:
            controller_status = "not_required"
        rows.append(
            {
                "preregistration_path": prereg_path.relative_to(repo_root).as_posix(),
                "change_id": change_id,
                "target_metric": target_metric,
                "minimum_delta": prereg.get("minimum_delta"),
                "direction": prereg.get("direction"),
                "requires_controller_telemetry": requires_controller,
                "current_report_controller_telemetry_status": controller_status,
                "latest_decision_present": latest is not None,
                "latest_decision_generated_at": latest.get("generated_at") if latest else None,
                "latest_decision_passed": latest.get("passed") if latest else None,
                "latest_target_delta": latest.get("target_delta") if latest else None,
            }
        )
    return rows


def _load_decision_log(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    decisions: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            decisions.append(payload)
    return decisions


def _source_data(sources: dict[str, Source], source_id: str, *path: str) -> Any:
    source = sources.get(source_id)
    if source is None or source.data is None:
        return None
    return _nested(source.data, *path)


def _nested(data: Any, *path: str) -> Any:
    current = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _git(repo_root: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout.strip() if proc.returncode == 0 else ""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Mnemosyne G0 benchmark report")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--out-dir", type=Path, default=Path("eval/g0/reports"))
    parser.add_argument("--baseline-name", default="baseline-0")
    parser.add_argument("--pinned-commit", help="override the baseline pinned commit recorded in the report")
    parser.add_argument(
        "--controller-telemetry",
        type=Path,
        help=(
            "optional JSON artifact with controller_avg_watts and "
            "controller_cost_usd_per_hour for controller_watts_per_dollar"
        ),
    )
    parser.add_argument("--write-baseline", action="store_true", help="also write eval/g0/baselines/<name>.json")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    report = build_report(
        repo_root,
        baseline_name=args.baseline_name,
        pinned_commit=args.pinned_commit,
        controller_telemetry_path=args.controller_telemetry,
    )
    paths = write_report(report, repo_root / args.out_dir, write_baseline=args.write_baseline)
    if args.print_json:
        print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    else:
        print(f"G0 report: {paths['json']}")
        print(f"G0 markdown: {paths['markdown']}")
        if "baseline" in paths:
            print(f"G0 baseline: {paths['baseline']}")
        print(
            f"G0 coverage: {report['coverage']['measured']}/{report['coverage']['total']} "
            f"measured; gate_ready={report['coverage']['gate_ready']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
