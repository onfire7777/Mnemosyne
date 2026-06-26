from __future__ import annotations

from pathlib import Path

from eval.g0.gate import evaluate_ablation
from eval.g0.runner import G0_METRIC_SPECS, build_report


REPO_ROOT = Path(__file__).resolve().parents[1]


def _report(metrics: list[dict]) -> dict:
    return {"metrics": metrics}


def _metric(metric_id: str, value: float, *, cls: str, direction: str) -> dict:
    return {
        "id": metric_id,
        "class": cls,
        "direction": direction,
        "status": "measured",
        "value": value,
    }


def test_g0_report_emits_every_spec_metric_and_source_hashes() -> None:
    report = build_report(REPO_ROOT, baseline_name="baseline-0")
    expected_ids = {spec["id"] for spec in G0_METRIC_SPECS}
    observed_ids = {metric["id"] for metric in report["metrics"]}

    assert observed_ids == expected_ids
    assert report["schema_version"] == "g0.report.v1"
    assert report["coverage"]["total"] == len(expected_ids)
    assert report["coverage"]["measured"] > 0
    assert report["coverage"]["missing"] > 0
    assert report["coverage"]["gate_ready"] is False

    sources = {source["id"]: source for source in report["sources"]}
    assert sources["slo_v2_definitive"]["present"] is True
    assert len(sources["slo_v2_definitive"]["sha256"]) == 64
    assert sources["calibration_report"]["present"] is True

    metrics = {metric["id"]: metric for metric in report["metrics"]}
    assert metrics["recall_at_k"]["status"] == "measured"
    assert metrics["recall_at_k"]["source_id"] == "slo_v2_definitive"
    assert metrics["ece"]["status"] == "measured"
    assert metrics["ece"]["source_id"] == "calibration_report"
    assert metrics["poison_block_rate"]["status"] == "measured"
    assert metrics["continual_learning_interference"]["status"] == "missing"
    assert metrics["confabulation_rate"]["status"] == "missing"

    dataset_paths = {manifest["path"] for manifest in report["dataset_manifests"]}
    assert "eval/datasets/retrieval_curated.json" in dataset_paths
    assert "eval/datasets/poison_suite.json" in dataset_paths


def test_ablation_gate_passes_preregistered_target_with_stable_guardrails() -> None:
    baseline = _report(
        [
            _metric("recall_at_k", 0.80, cls="target", direction="increase"),
            _metric("ece", 0.010, cls="guardrail", direction="decrease"),
            _metric("poison_block_rate", 1.0, cls="guardrail", direction="increase"),
        ]
    )
    candidate = _report(
        [
            _metric("recall_at_k", 0.835, cls="target", direction="increase"),
            _metric("ece", 0.012, cls="guardrail", direction="decrease"),
            _metric("poison_block_rate", 1.0, cls="guardrail", direction="increase"),
        ]
    )

    decision = evaluate_ablation(
        baseline,
        candidate,
        {
            "change_id": "g1-retrieval-test",
            "target_metric": "recall_at_k",
            "minimum_delta": 0.02,
            "guardrail_tolerances": {"ece": 0.005},
        },
    )

    assert decision.passed is True
    assert decision.target_delta is not None
    assert decision.target_delta > 0.03
    assert all(result["passed"] for result in decision.guardrail_results)


def test_ablation_gate_fails_guardrail_regression_and_missing_metrics() -> None:
    baseline = _report(
        [
            _metric("recall_at_k", 0.80, cls="target", direction="increase"),
            _metric("ece", 0.010, cls="guardrail", direction="decrease"),
            _metric("confabulation_rate", 0.0, cls="guardrail", direction="decrease"),
        ]
    )
    candidate = _report(
        [
            _metric("recall_at_k", 0.84, cls="target", direction="increase"),
            _metric("ece", 0.050, cls="guardrail", direction="decrease"),
        ]
    )

    decision = evaluate_ablation(
        baseline,
        candidate,
        {
            "change_id": "unsafe-retrieval-test",
            "target_metric": "recall_at_k",
            "minimum_delta": 0.01,
        },
    )

    assert decision.passed is False
    assert any("ece" in reason for reason in decision.reasons)
    assert any("confabulation_rate" in reason for reason in decision.reasons)
