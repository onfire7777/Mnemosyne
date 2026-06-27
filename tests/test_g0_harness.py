from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from eval.g0.confabulation import run_confabulation_eval
from eval.g0.consciousness import INDICATORS, run_consciousness_eval
from eval.g0.continual_learning import run_continual_learning_eval
from eval.g0.deep_latency import run_deep_latency_eval
from eval.g0.gate import evaluate_ablation
from eval.g0.resource_usage import run_resource_usage_eval
from eval.g0.runner import G0_METRIC_SPECS, build_report
from eval.g0.shadow_workspace import run_shadow_workspace_eval


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
    assert report["coverage"]["missing_metric_ids"] == ["controller_watts_per_dollar"]

    sources = {source["id"]: source for source in report["sources"]}
    assert sources["slo_v2_definitive"]["present"] is True
    assert len(sources["slo_v2_definitive"]["sha256"]) == 64
    assert sources["calibration_report"]["present"] is True
    assert sources["continual_learning_eval"]["present"] is True
    assert sources["continual_learning_eval"]["path"] == "computed:eval.g0.continual_learning"
    assert sources["confabulation_eval"]["present"] is True
    assert sources["confabulation_eval"]["path"] == "computed:eval.g0.confabulation"
    assert sources["deep_latency_eval"]["present"] is True
    assert sources["deep_latency_eval"]["path"] == "computed:eval.g0.deep_latency"
    assert sources["resource_usage_eval"]["present"] is True
    assert sources["resource_usage_eval"]["path"] == "computed:eval.g0.resource_usage"
    assert sources["dreamer_eval"]["present"] is True
    assert sources["dreamer_eval"]["path"] == "computed:eval.g0.dreamer"
    assert sources["shadow_workspace_eval"]["present"] is True
    assert sources["shadow_workspace_eval"]["path"] == "computed:eval.g0.shadow_workspace"
    assert sources["consciousness_eval"]["present"] is True
    assert sources["consciousness_eval"]["path"] == "computed:eval.g0.consciousness"

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
    assert metrics["deep_path_p95_ms"]["status"] == "measured"
    assert metrics["deep_path_p95_ms"]["value"] > 0.0
    assert metrics["deep_path_p95_ms"]["source_id"] == "deep_latency_eval"
    assert metrics["cost_usd_per_1k_queries"]["status"] == "measured"
    assert metrics["cost_usd_per_1k_queries"]["value"] == 0.0
    assert metrics["cost_usd_per_1k_queries"]["source_id"] == "resource_usage_eval"
    assert metrics["controller_watts_per_dollar"]["status"] == "missing"
    assert metrics["controller_watts_per_dollar"]["source_id"] == "resource_usage_eval"
    assert "requires explicit" in metrics["controller_watts_per_dollar"]["notes"]
    assert metrics["dreamer_shadow_corroborated_candidate_yield"]["status"] == "measured"
    assert metrics["dreamer_shadow_corroborated_candidate_yield"]["value"] == 1.0
    assert metrics["dreamer_shadow_corroborated_candidate_yield"]["source_id"] == "dreamer_eval"
    assert metrics["dreamer_shadow_contract"]["status"] == "measured"
    assert metrics["dreamer_shadow_contract"]["value"] == 1.0
    assert metrics["dreamer_shadow_contract"]["source_id"] == "dreamer_eval"
    assert metrics["specialist_promotion_evidence_contract"]["status"] == "measured"
    assert metrics["specialist_promotion_evidence_contract"]["value"] == 1.0
    assert metrics["specialist_promotion_evidence_contract"]["source_id"] == "dreamer_eval"
    assert metrics["shadow_workspace_useful_transition_rate"]["status"] == "measured"
    assert metrics["shadow_workspace_useful_transition_rate"]["value"] == 1.0
    assert metrics["shadow_workspace_useful_transition_rate"]["source_id"] == "shadow_workspace_eval"
    assert metrics["shadow_workspace_contract"]["status"] == "measured"
    assert metrics["shadow_workspace_contract"]["value"] == 1.0
    assert metrics["shadow_workspace_contract"]["source_id"] == "shadow_workspace_eval"
    assert metrics["workspace_consolidation_advisory_contract"]["status"] == "measured"
    assert metrics["workspace_consolidation_advisory_contract"]["value"] == 1.0
    assert metrics["workspace_consolidation_advisory_contract"]["source_id"] == "shadow_workspace_eval"
    assert metrics["workspace_advisory_promotion_gate_contract"]["status"] == "measured"
    assert metrics["workspace_advisory_promotion_gate_contract"]["value"] == 1.0
    assert metrics["workspace_advisory_promotion_gate_contract"]["source_id"] == "shadow_workspace_eval"
    assert metrics["shadow_workspace_rumination_rate"]["status"] == "measured"
    assert metrics["shadow_workspace_rumination_rate"]["value"] == 0.0
    assert metrics["shadow_workspace_rumination_rate"]["source_id"] == "shadow_workspace_eval"
    assert metrics["consciousness_indicator_total"]["status"] == "measured"
    assert metrics["consciousness_indicator_total"]["source_id"] == "consciousness_eval"
    assert metrics["workspace_loop_liveness"]["value"] == 1.0
    assert metrics["self_model_accuracy"]["value"] == 1.0
    assert metrics["metacognition_m_ratio"]["value"] == 1.0
    assert metrics["reality_monitor_shadow_tag_contract"]["value"] == 1.0
    assert report["computed_evidence"]["consciousness_eval"]["dreamer_shadow_contract"]["score"] == 1.0
    assert report["computed_evidence"]["dreamer_eval"]["specialist_promotion_evidence_contract"] == 1.0
    assert report["computed_evidence"]["shadow_workspace_eval"]["shadow_workspace_contract"] == 1.0
    assert (
        report["computed_evidence"]["shadow_workspace_eval"]["workspace_consolidation_advisory_contract"]
        == 1.0
    )
    assert (
        report["computed_evidence"]["shadow_workspace_eval"]["workspace_advisory_promotion_gate_contract"]
        == 1.0
    )

    dataset_paths = {manifest["path"] for manifest in report["dataset_manifests"]}
    assert "eval/datasets/continual_learning_interference.json" in dataset_paths
    assert "eval/datasets/deep_latency.json" in dataset_paths
    assert "eval/datasets/dreamer_shadow_ablation.json" in dataset_paths
    assert "eval/datasets/shadow_workspace_loop.json" in dataset_paths
    assert "eval/datasets/resource_usage.json" in dataset_paths
    assert "eval/datasets/retrieval_curated.json" in dataset_paths
    assert "eval/datasets/poison_suite.json" in dataset_paths


def test_g0_continual_learning_fixture_preserves_earlier_task_accuracy() -> None:
    report = run_continual_learning_eval()

    assert report["schema_version"] == "g0.continual_learning.v1"
    assert "Deterministic local proxy" in report["metric_note"]
    assert report["dataset_path"] == "eval/datasets/continual_learning_interference.json"
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


def test_g0_deep_latency_fixture_records_graph_backed_deep_search() -> None:
    report = run_deep_latency_eval()

    assert report["schema_version"] == "g0.deep_latency.v1"
    assert report["dataset_path"] == "eval/datasets/deep_latency.json"
    assert report["query_count"] >= 3
    assert report["p95_ms"] > 0.0
    assert report["max_ms"] >= report["p50_ms"]
    assert "not production infrastructure evidence" in report["metric_note"]
    assert all(row["graph_hits"] >= 1 for row in report["rows"])


def test_g0_resource_usage_fixture_records_local_provider_cost() -> None:
    report = run_resource_usage_eval()

    assert report["schema_version"] == "g0.resource_usage.v1"
    assert report["query_count"] >= 3
    assert report["external_provider_calls"] == 0
    assert report["cost_usd_per_1k_queries"] == 0.0
    assert report["controller_watts_per_dollar"] is None
    assert report["controller_telemetry_present"] is False
    assert "zero paid-provider spend" in report["metric_note"]
    assert all(row["external_provider_calls"] == 0 for row in report["rows"])


def test_g0_resource_usage_fixture_computes_controller_watts_with_explicit_telemetry(tmp_path: Path) -> None:
    telemetry = tmp_path / "controller-telemetry.json"
    telemetry_text = '{"controller_avg_watts": 12.5, "controller_cost_usd_per_hour": 0.25}\n'
    telemetry.write_text(telemetry_text, encoding="utf-8")

    report = run_resource_usage_eval(telemetry_path=telemetry)

    assert report["controller_telemetry_present"] is True
    assert report["controller_watts_per_dollar"] == 50.0
    assert report["controller_cost_window_hours"] == 1.0
    assert report["controller_cost_usd_for_window"] == 0.25
    assert report["telemetry_sha256"] == hashlib.sha256(telemetry_text.encode()).hexdigest()
    assert report["telemetry_path"] == telemetry.name
    assert report["dataset_path"] == "eval/datasets/resource_usage.json"


def test_g0_consciousness_scorecard_reports_indicator_properties() -> None:
    report = run_consciousness_eval(repo_root=REPO_ROOT)

    assert report["schema_version"] == "g0.consciousness_scorecard.v1"
    assert report["phenomenal_claim"] is False
    assert report["indicator_count"] == 14
    assert len(report["indicators"]) == len(INDICATORS)
    assert {row["id"] for row in report["indicators"]} == {spec.id for spec in INDICATORS}
    assert all(row["score_label"] in {"0", "partial", "1"} for row in report["indicators"])
    assert report["metrics"]["consciousness_indicator_total"] == report["total_score"]
    assert report["metrics"]["workspace_loop_liveness"] == 1.0
    assert report["metrics"]["workspace_stream_coherence"] == 1.0
    assert report["metrics"]["self_model_accuracy"] == 1.0
    assert report["metrics"]["metacognition_meta_d_prime"] == 1.0
    assert report["metrics"]["metacognition_m_ratio"] == 1.0
    assert report["metrics"]["reality_monitor_shadow_tag_contract"] == 1.0
    assert report["metrics"]["dreamer_shadow_contract"] == 1.0
    shadow_contract = report["reality_monitor_shadow_tag_contract"]
    assert shadow_contract["score"] == 1.0
    assert all(shadow_contract["checks"].values())
    assert shadow_contract["local"]["abstained"] is False
    assert shadow_contract["local"]["critical_path"] is True
    assert shadow_contract["local"]["abstention_gate"]["critical_path"] is True
    assert shadow_contract["local"]["shadow_tags_critical_path"] is False
    assert shadow_contract["postgres"]["critical_path"] is True
    assert shadow_contract["postgres"]["abstention_gate"]["critical_path"] is True
    assert shadow_contract["postgres"]["shadow_tags_critical_path"] is False
    dreamer_contract = report["dreamer_shadow_contract"]
    assert dreamer_contract["score"] == 1.0
    assert all(dreamer_contract["checks"].values())
    assert dreamer_contract["workspace"]["shadow_only"] is True
    assert dreamer_contract["workspace"]["critical_path"] is False
    assert dreamer_contract["workspace"]["production_mutation"] is False
    assert dreamer_contract["dreamer"]["name"] == "dreamer.shadow"
    assert dreamer_contract["dreamer"]["critical_path"] is False
    assert dreamer_contract["dreamer"]["critical_path_allowed"] is False
    assert dreamer_contract["dreamer"]["output_summary"]["promotion_gate_required"] is True
    promotion = dreamer_contract["dreamer"]["output_summary"]["promotion_evidence"]
    assert promotion["schema_version"] == "specialist-promotion-evidence.v1"
    assert promotion["promoted"] is False
    assert promotion["gate_result"] is None
    assert promotion["cid_backed_candidate_count"] == promotion["candidate_count"]


def test_g0_shadow_workspace_fixture_reports_bounded_stream_contract() -> None:
    report = run_shadow_workspace_eval(repo_root=REPO_ROOT)

    assert report["schema_version"] == "g0.shadow_workspace_loop.v1"
    assert report["useful_transition_rate"] == 1.0
    assert report["shadow_workspace_contract"] == 1.0
    assert report["workspace_consolidation_advisory_contract"] == 1.0
    assert report["workspace_advisory_promotion_gate_contract"] == 1.0
    assert report["rumination_rate"] == 0.0
    assert report["workspace"]["shadow_only"] is True
    assert report["workspace"]["critical_path"] is False
    assert report["workspace"]["production_mutation"] is False
    assert report["workspace"]["promotion_gate_required"] is True
    assert report["workspace"]["cycle_consistency"]["score"] == 1.0
    advisory = report["workspace_consolidation_advisory"]
    assert advisory["shadow_only"] is True
    assert advisory["critical_path"] is False
    assert advisory["production_mutation"] is False
    assert advisory["applied_to_prediction_gate"] is False
    assert advisory["applied_to_replay_priority"] is False
    assert advisory["applied_to_mutation"] is False
    assert advisory["items"]
    assert all(item["cid"] in advisory["replay_scores"] for item in advisory["items"])
    assert report["rumination_probe"]["stopped_reason"] == "anti_rumination_repeated_focus_exit"
    assert all("phenomenal" not in str(row).lower() for row in report["workspace"]["trace"])


def test_g0_report_measures_controller_watts_with_explicit_telemetry(tmp_path: Path) -> None:
    telemetry = tmp_path / "controller-telemetry.json"
    telemetry.write_text(
        '{"controller_avg_watts": 12.5, "controller_cost_usd_per_hour": 0.25}\n',
        encoding="utf-8",
    )

    report = build_report(REPO_ROOT, baseline_name="baseline-0", controller_telemetry_path=telemetry)
    metrics = {metric["id"]: metric for metric in report["metrics"]}
    computed = report["computed_evidence"]["resource_usage_eval"]

    assert report["coverage"]["missing"] == 0
    assert report["coverage"]["gate_ready"] is True
    assert report["coverage"]["missing_metric_ids"] == []
    assert metrics["controller_watts_per_dollar"]["status"] == "measured"
    assert metrics["controller_watts_per_dollar"]["value"] == 50.0
    assert computed["controller_telemetry_present"] is True
    assert computed["telemetry_sha256"] == hashlib.sha256(telemetry.read_bytes()).hexdigest()


def test_g0_runner_cli_accepts_controller_telemetry(tmp_path: Path) -> None:
    telemetry = tmp_path / "controller-telemetry.json"
    out_dir = tmp_path / "g0-report"
    telemetry.write_text(
        '{"controller_avg_watts": 12.5, "controller_cost_usd_per_hour": 0.25}\n',
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "eval.g0.runner",
            "--repo-root",
            str(REPO_ROOT),
            "--out-dir",
            str(out_dir),
            "--controller-telemetry",
            str(telemetry),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))

    assert f"G0 coverage: {len(G0_METRIC_SPECS)}/{len(G0_METRIC_SPECS)} measured; gate_ready=True" in result.stdout
    assert report["coverage"]["gate_ready"] is True
    assert report["computed_evidence"]["resource_usage_eval"]["controller_watts_per_dollar"] == 50.0


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


def test_ablation_gate_fails_unknown_guardrail_direction() -> None:
    baseline = _report(
        [
            _metric("recall_at_k", 0.80, cls="target", direction="increase"),
            _metric("custom_guardrail", 0.50, cls="guardrail", direction="sideways"),
        ]
    )
    candidate = _report(
        [
            _metric("recall_at_k", 0.83, cls="target", direction="increase"),
            _metric("custom_guardrail", 0.50, cls="guardrail", direction="sideways"),
        ]
    )

    decision = evaluate_ablation(
        baseline,
        candidate,
        {
            "change_id": "invalid-guardrail-direction-test",
            "target_metric": "recall_at_k",
            "minimum_delta": 0.02,
        },
    )

    assert decision.passed is False
    assert any("unsupported direction" in reason for reason in decision.reasons)


def test_committed_g0_preregistrations_have_passing_decisions() -> None:
    def target_delta_satisfies(direction: str, target_delta: float, minimum_delta: float) -> bool:
        if direction == "increase":
            return target_delta >= minimum_delta
        if direction == "decrease":
            return target_delta <= -minimum_delta
        return False

    decision_log = REPO_ROOT / "eval/g0/decision-log.jsonl"
    decisions = [
        json.loads(line)
        for line in decision_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    passed_by_change: dict[str, list[dict]] = {}
    for decision in decisions:
        if decision.get("passed") is True:
            passed_by_change.setdefault(str(decision.get("change_id")), []).append(decision)

    for prereg_path in sorted((REPO_ROOT / "eval/g0/preregistrations").glob("*.json")):
        prereg = json.loads(prereg_path.read_text(encoding="utf-8"))
        change_id = str(prereg["change_id"])
        target_metric = str(prereg["target_metric"])
        minimum_delta = float(prereg.get("minimum_delta", 0.0))
        matching = [
            decision
            for decision in passed_by_change.get(change_id, [])
            if decision.get("target_metric") == target_metric
            and target_delta_satisfies(
                str(prereg.get("direction", "increase")),
                float(decision.get("target_delta") or 0.0),
                minimum_delta,
            )
        ]
        assert matching, f"{prereg_path.name} has no passing decision-log entry"


def test_current_g0_candidate_replays_preregistrations_without_regression() -> None:
    baseline = json.loads((REPO_ROOT / "eval/g0/baselines/baseline-0.json").read_text(encoding="utf-8"))
    candidate = build_report(REPO_ROOT, baseline_name="candidate-current")

    for prereg_path in sorted((REPO_ROOT / "eval/g0/preregistrations").glob("*.json")):
        prereg = json.loads(prereg_path.read_text(encoding="utf-8"))
        non_regression_prereg = {**prereg, "minimum_delta": 0.0}
        decision = evaluate_ablation(baseline, candidate, non_regression_prereg)
        assert decision.passed, f"{prereg_path.name} regressed current G0 candidate: {decision.reasons}"
