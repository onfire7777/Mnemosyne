from __future__ import annotations

from pathlib import Path

from eval.g0.confabulation import run_confabulation_eval
from eval.g0.continual_learning import run_continual_learning_eval
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
    assert sources["continual_learning_eval"]["present"] is True
    assert sources["continual_learning_eval"]["path"] == "computed:eval.g0.continual_learning"
    assert sources["confabulation_eval"]["present"] is True
    assert sources["confabulation_eval"]["path"] == "computed:eval.g0.confabulation"

    metrics = {metric["id"]: metric for metric in report["metrics"]}
    assert metrics["recall_at_k"]["status"] == "measured"
    assert metrics["recall_at_k"]["source_id"] == "slo_v2_definitive"
    assert metrics["ece"]["status"] == "measured"
    assert metrics["ece"]["source_id"] == "calibration_report"
    assert metrics["poison_block_rate"]["status"] == "measured"
    assert metrics["continual_learning_interference"]["status"] == "measured"
    assert metrics["continual_learning_interference"]["value"] == 0.0
    assert metrics["continual_learning_interference"]["source_id"] == "continual_learning_eval"
    assert metrics["confabulation_rate"]["status"] == "measured"
    assert metrics["confabulation_rate"]["value"] == 0.0
    assert metrics["confabulation_rate"]["source_id"] == "confabulation_eval"
    assert metrics["deep_path_p95_ms"]["status"] == "missing"

    dataset_paths = {manifest["path"] for manifest in report["dataset_manifests"]}
    assert "eval/datasets/continual_learning_interference.json" in dataset_paths
    assert "eval/datasets/retrieval_curated.json" in dataset_paths
    assert "eval/datasets/poison_suite.json" in dataset_paths


def test_g0_continual_learning_fixture_preserves_earlier_task_accuracy() -> None:
    report = run_continual_learning_eval()

    assert report["schema_version"] == "g0.continual_learning.v1"
    assert "Deterministic local proxy" in report["metric_note"]
    assert report["total_cases"] >= 3
    assert report["before_accuracy"] == 1.0
    assert report["after_accuracy"] == 1.0
    assert report["interference"] == 0.0
    assert report["passed"] is True
    assert all(row["before"]["correct"] is True for row in report["rows"])
    assert all(row["after"]["correct"] is True for row in report["rows"])
    assert all(row["regressed"] is False for row in report["rows"])


def test_g0_confabulation_fixture_fails_closed_on_risky_support() -> None:
    report = run_confabulation_eval()

    assert report["schema_version"] == "g0.confabulation.v1"
    assert "Deterministic local proxy" in report["metric_note"]
    assert report["total_cases"] >= 3
    assert report["false_accepts"] == 0
    assert report["rate"] == 0.0
    assert report["passed"] is True
    assert all(row["abstained"] is True for row in report["rows"])
    assert all(row["gist_support_applied"] is True for row in report["rows"])


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
