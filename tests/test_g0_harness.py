from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from eval.g0.autonomy_promotion import run_autonomy_promotion_eval
from eval.g0.confabulation import run_confabulation_eval
from eval.g0.consciousness import INDICATORS, run_consciousness_eval
from eval.g0.continual_learning import run_continual_learning_eval
from eval.g0.deep_latency import run_deep_latency_eval
from eval.g0.gate import evaluate_ablation
from eval.g0.resource_usage import run_resource_usage_eval
from eval.g0.runner import G0_METRIC_SPECS, build_report, render_markdown, write_report
from eval.g0.shadow_workspace import run_shadow_workspace_eval
from eval.g0.standing_calibration import run_standing_calibration_eval
from eval.g0.standing_parity import run_standing_parity_eval
from eval.g0.unified_substrate import run_unified_substrate_eval


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTROLLER_TELEMETRY_FIXTURE = REPO_ROOT / "eval/datasets/controller_telemetry_sanitized.json"


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
    assert report["coverage"]["intentionally_missing_metric_ids"] == ["controller_watts_per_dollar"]
    assert report["gate_contract"]["preregistration_dir"] == "eval/g0/preregistrations"
    assert report["gate_contract"]["decision_log"] == "eval/g0/decision-log.jsonl"
    assert report["gate_contract"]["controller_telemetry_required_field"] == "requires_controller_telemetry"
    assert report["artifact_custody"]["source_commit"]
    assert "cannot be embedded" in report["artifact_custody"]["snapshot_note"]
    baseline_payload = json.loads(
        (REPO_ROOT / "eval/g0/baselines/baseline-0.json").read_text(encoding="utf-8")
    )
    assert report["baseline"]["pinned_commit"] == baseline_payload["baseline"]["pinned_commit"]
    assert report["artifact_custody"]["source_commit"] != report["baseline"]["pinned_commit"]
    pinned_override = "f" * 40
    pinned_report = build_report(REPO_ROOT, baseline_name="baseline-0", pinned_commit=pinned_override)
    assert pinned_report["baseline"]["pinned_commit"] == pinned_override
    assert pinned_report["artifact_custody"]["source_commit"] == report["artifact_custody"]["source_commit"]

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
    assert sources["standing_parity_eval"]["present"] is True
    assert sources["standing_parity_eval"]["path"] == "computed:eval.g0.standing_parity"
    assert sources["standing_calibration_eval"]["present"] is True
    assert sources["standing_calibration_eval"]["path"] == "computed:eval.g0.standing_calibration"
    assert sources["autonomy_promotion_eval"]["present"] is True
    assert sources["autonomy_promotion_eval"]["path"] == "computed:eval.g0.autonomy_promotion"
    assert sources["unified_substrate_eval"]["present"] is True
    assert sources["unified_substrate_eval"]["path"] == "computed:eval.g0.unified_substrate"

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
    assert metrics["standing_decision_divergence"]["status"] == "measured"
    assert metrics["standing_decision_divergence"]["value"] == 0.0
    assert metrics["standing_decision_divergence"]["source_id"] == "standing_parity_eval"
    assert metrics["standing_calibration_error"]["status"] == "measured"
    assert metrics["standing_calibration_error"]["value"] <= 0.05
    assert metrics["standing_calibration_error"]["source_id"] == "standing_calibration_eval"
    assert metrics["standing_conformal_coverage"]["value"] >= 0.95
    assert metrics["standing_salience_invariance_contract"]["value"] == 1.0
    assert metrics["standing_independent_corroboration_contract"]["value"] == 1.0
    assert metrics["standing_evidence_dominance_gap"]["value"] >= 0.02
    assert metrics["earned_autonomy_external_expansion"]["status"] == "measured"
    assert metrics["earned_autonomy_external_expansion"]["value"] > 0.0
    assert metrics["earned_autonomy_external_expansion"]["source_id"] == "autonomy_promotion_eval"
    assert metrics["credential_external_only"]["value"] == 1.0
    assert metrics["credential_holdout_validated"]["value"] == 1.0
    assert metrics["credential_provenance_domain_contract"]["value"] == 1.0
    assert metrics["credential_bounded_decay_contract"]["value"] == 1.0
    assert metrics["credential_evidence_dominance_gap"]["value"] >= 0.02
    assert metrics["echo_chamber_uplift"]["value"] == 0.0
    assert metrics["standing_observability_trace_contract"]["value"] == 1.0
    assert metrics["standing_observability_trace_contract"]["source_id"] == "unified_substrate_eval"
    assert metrics["standing_erasure_cascade_contract"]["value"] == 1.0
    assert metrics["standing_erasure_cascade_contract"]["source_id"] == "unified_substrate_eval"
    assert metrics["belief_standing_cascade_contract"]["value"] == 1.0
    assert metrics["belief_standing_cascade_contract"]["source_id"] == "unified_substrate_eval"
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
    assert metrics["always_on_heartbeat_contract"]["status"] == "measured"
    assert metrics["always_on_heartbeat_contract"]["value"] == 1.0
    assert metrics["always_on_heartbeat_contract"]["source_id"] == "shadow_workspace_eval"
    assert metrics["always_on_rumination_rate"]["value"] == 0.0
    assert metrics["heartbeat_compute_bounded_contract"]["value"] == 1.0
    assert metrics["heartbeat_compute_reported_contract"]["value"] == 1.0
    assert metrics["circuit_breaker_contract"]["value"] == 1.0
    assert metrics["workspace_broadcast_as_data_contract"]["value"] == 1.0
    assert metrics["self_generation_budget_rail_contract"]["value"] == 1.0
    assert metrics["answer_grounding_floor_contract"]["value"] == 1.0
    assert metrics["workspace_consolidation_advisory_contract"]["status"] == "measured"
    assert metrics["workspace_consolidation_advisory_contract"]["value"] == 1.0
    assert metrics["workspace_consolidation_advisory_contract"]["source_id"] == "shadow_workspace_eval"
    assert metrics["workspace_advisory_promotion_gate_contract"]["status"] == "measured"
    assert metrics["workspace_advisory_promotion_gate_contract"]["value"] == 1.0
    assert metrics["workspace_advisory_promotion_gate_contract"]["source_id"] == "shadow_workspace_eval"
    assert metrics["workspace_retrieval_controller_contract"]["status"] == "measured"
    assert metrics["workspace_retrieval_controller_contract"]["value"] == 1.0
    assert metrics["workspace_retrieval_controller_contract"]["source_id"] == "shadow_workspace_eval"
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
    assert report["computed_evidence"]["standing_parity_eval"]["standing_decision_divergence"] == 0.0
    assert report["computed_evidence"]["standing_calibration_eval"]["standing_calibration_error"] <= 0.05
    assert report["computed_evidence"]["standing_calibration_eval"]["standing_salience_invariance_contract"] == 1.0
    assert report["computed_evidence"]["autonomy_promotion_eval"]["metrics"]["echo_chamber_uplift"] == 0.0
    assert report["computed_evidence"]["autonomy_promotion_eval"]["passed"] is True
    assert report["computed_evidence"]["unified_substrate_eval"]["metrics"]["standing_erasure_cascade_contract"] == 1.0
    assert report["computed_evidence"]["unified_substrate_eval"]["passed"] is True
    assert report["computed_evidence"]["shadow_workspace_eval"]["shadow_workspace_contract"] == 1.0
    assert report["computed_evidence"]["shadow_workspace_eval"]["always_on_heartbeat_contract"] == 1.0
    assert report["computed_evidence"]["shadow_workspace_eval"]["circuit_breaker_contract"] == 1.0
    assert report["computed_evidence"]["shadow_workspace_eval"]["workspace_broadcast_as_data_contract"] == 1.0
    assert report["computed_evidence"]["shadow_workspace_eval"]["self_generation_budget_rail_contract"] == 1.0
    assert report["computed_evidence"]["shadow_workspace_eval"]["answer_grounding_floor_contract"] == 1.0
    assert (
        report["computed_evidence"]["shadow_workspace_eval"]["workspace_consolidation_advisory_contract"]
        == 1.0
    )
    assert (
        report["computed_evidence"]["shadow_workspace_eval"]["workspace_advisory_promotion_gate_contract"]
        == 1.0
    )
    assert report["computed_evidence"]["shadow_workspace_eval"]["workspace_retrieval_controller_contract"] == 1.0
    projection_rows = report["computed_evidence"]["projection_reality_eval"]["rows"]
    simulated_row = next(row for row in projection_rows if row["case_id"] == "simulated_projection_only")
    assert {
        tag["reality_class"]
        for tag in simulated_row["reality_monitoring"]["shadow_tags"].values()
    } == {"simulated"}
    generated_simulated_row = next(
        row for row in projection_rows if row["case_id"] == "generated_simulated_projection_only"
    )
    assert generated_simulated_row["projection_reality_class"] == "simulated"
    assert {
        tag["reality_class"]
        for tag in generated_simulated_row["reality_monitoring"]["shadow_tags"].values()
    } == {"simulated"}
    decisions = {row["change_id"]: row for row in report["gate_decisions"]}
    assert decisions["g4-workspace-retrieval-controller-gate"]["latest_decision_passed"] is True
    assert decisions["g4-workspace-retrieval-controller-gate"]["latest_target_delta"] == 1.0
    assert (
        decisions["g4-workspace-retrieval-controller-gate"]["current_report_controller_telemetry_status"]
        == "not_required"
    )
    assert decisions["g4-shadow-continuous-workspace-loop"]["requires_controller_telemetry"] is False
    rendered = render_markdown(report)
    assert "## Gate Decisions" in rendered
    assert "## Artifact Custody" in rendered
    assert "## Functional Consciousness Scope" in rendered
    assert "- Phenomenal claim: `False`" in rendered
    assert "- Welfare review flag: `True`" in rendered
    assert "not a welfare conclusion" in rendered
    assert "g4-workspace-retrieval-controller-gate" in rendered

    dataset_paths = {manifest["path"] for manifest in report["dataset_manifests"]}
    assert "eval/datasets/continual_learning_interference.json" in dataset_paths
    assert "eval/datasets/deep_latency.json" in dataset_paths
    assert "eval/datasets/dreamer_shadow_ablation.json" in dataset_paths
    assert "eval/datasets/shadow_workspace_loop.json" in dataset_paths
    assert "eval/datasets/echo_chamber_sleeper_corpus.json" in dataset_paths
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


def test_g0_standing_parity_fixture_reports_zero_decision_divergence() -> None:
    report = run_standing_parity_eval(repo_root=REPO_ROOT)

    assert report["schema_version"] == "g0.standing_parity.v1"
    assert report["metric"] == "standing_decision_divergence"
    assert report["standing_decision_divergence"] == 0.0
    assert report["divergence_count"] == 0
    assert report["passed"] is True
    assert all(row["zero_divergence"] for row in report["retrieval_rows"])
    assert all(row["zero_divergence"] for row in report["consolidation_rows"])


def test_g0_standing_calibration_fixture_reports_continuous_contracts() -> None:
    report = run_standing_calibration_eval(repo_root=REPO_ROOT)

    assert report["schema_version"] == "g0.standing_calibration.v1"
    assert report["standing_calibration_error"] <= 0.05
    assert report["standing_conformal_coverage"] >= 0.95
    assert report["standing_false_accept_rate"] == 0.0
    assert report["standing_salience_invariance_contract"] == 1.0
    assert report["standing_independent_corroboration_contract"] == 1.0
    assert report["standing_evidence_dominance_gap"] >= 0.02
    assert report["passed"] is True


def test_g0_autonomy_promotion_fixture_reports_earned_autonomy_contracts() -> None:
    report = run_autonomy_promotion_eval(repo_root=REPO_ROOT)
    metrics = report["metrics"]

    assert report["schema_version"] == "g0.autonomy_promotion.v1"
    assert metrics["earned_autonomy_external_expansion"] > 0.0
    assert metrics["credential_external_only"] == 1.0
    assert metrics["credential_holdout_validated"] == 1.0
    assert metrics["credential_provenance_domain_contract"] == 1.0
    assert metrics["credential_bounded_decay_contract"] == 1.0
    assert metrics["credential_evidence_dominance_gap"] >= 0.02
    assert metrics["echo_chamber_uplift"] == 0.0
    assert report["passed"] is True


def test_g0_unified_substrate_fixture_reports_cascade_contracts() -> None:
    report = run_unified_substrate_eval()
    metrics = report["metrics"]

    assert report["schema_version"] == "g0.unified_substrate.v1"
    assert metrics["standing_observability_trace_contract"] == 1.0
    assert metrics["standing_erasure_cascade_contract"] == 1.0
    assert metrics["belief_standing_cascade_contract"] == 1.0
    assert report["standing_cascade"]["h8_cascade_to_self_derivations"] is True
    assert report["belief_cascade"]["standing_recomputed_on_read"] is True
    assert report["passed"] is True


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
    assert report["welfare_review_flag"] is True
    assert report["welfare_review_source"] == "Long_Sebo_et_al_2024_Taking_AI_Welfare_Seriously"
    assert report["indicator_count"] == 14
    assert len(report["indicators"]) == len(INDICATORS)
    assert {row["id"] for row in report["indicators"]} == {spec.id for spec in INDICATORS}
    assert all(row["score_label"] in {"0", "partial", "1"} for row in report["indicators"])
    assert report["metrics"]["consciousness_indicator_total"] == report["total_score"]
    assert report["metrics"]["workspace_loop_liveness"] == 1.0
    assert report["metrics"]["workspace_stream_coherence"] == 1.0
    assert report["continuity"]["service_enabled"] is True
    assert report["continuity"]["service_running"] is True
    assert report["continuity"]["proto_self_history_count"] == report["continuity"]["metacognitive_rows"]
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
    assert report["always_on_heartbeat_contract"] == 1.0
    assert report["always_on_rumination_rate"] == 0.0
    assert report["heartbeat_compute_bounded_contract"] == 1.0
    assert report["heartbeat_compute_reported_contract"] == 1.0
    assert report["circuit_breaker_contract"] == 1.0
    assert report["workspace_broadcast_as_data_contract"] == 1.0
    assert report["self_generation_budget_rail_contract"] == 1.0
    assert report["answer_grounding_floor_contract"] == 1.0
    assert report["workspace_consolidation_advisory_contract"] == 1.0
    assert report["workspace_advisory_promotion_gate_contract"] == 1.0
    assert report["workspace_retrieval_controller_contract"] == 1.0
    assert report["rumination_rate"] == 0.0
    assert report["workspace"]["shadow_only"] is True
    assert report["workspace"]["critical_path"] is False
    assert report["workspace"]["production_mutation"] is False
    assert report["workspace"]["promotion_gate_required"] is True
    assert report["workspace"]["service"]["enabled"] is True
    assert report["workspace"]["service"]["running"] is True
    assert report["workspace"]["service"]["tick_count"] == report["workspace"]["service"]["proto_self_history_count"]
    assert report["workspace"]["service"]["tick_count"] == report["workspace"]["service"]["metacognitive_rows"]
    assert report["workspace"]["cycle_consistency"]["score"] == 1.0
    heartbeat = report["heartbeat_probe"]["heartbeat_safety"]
    assert heartbeat["schema_version"] == "always-on-heartbeat-safety.v1"
    assert heartbeat["engaged_ticks"] >= 1
    assert heartbeat["idle_ticks"] >= 1
    assert heartbeat["compute_bounded"] is True
    assert heartbeat["compute_reported"] is True
    assert heartbeat["used_for_control_flow"] is False
    advisory = report["workspace_consolidation_advisory"]
    assert advisory["shadow_only"] is True
    assert advisory["critical_path"] is False
    assert advisory["production_mutation"] is False
    assert advisory["applied_to_prediction_gate"] is False
    assert advisory["applied_to_replay_priority"] is False
    assert advisory["applied_to_mutation"] is False
    assert advisory["items"]
    assert all(item["cid"] in advisory["replay_scores"] for item in advisory["items"])
    retrieval_probe = report["workspace_retrieval_controller_probe"]
    assert retrieval_probe["valid_no_opt_in"]["status"] == "report_only"
    assert retrieval_probe["valid_apply"]["status"] == "applied"
    assert retrieval_probe["valid_apply"]["critical_path"] is True
    assert retrieval_probe["valid_apply"]["production_mutation"] is False
    assert retrieval_probe["invalid_apply"]["status"] == "rejected"
    assert all(retrieval_probe["checks"].values())
    assert all(report["circuit_breaker_probe"]["checks"].values())
    assert report["circuit_breaker_probe"]["heartbeat_safety"]["circuit_breaker_tripped"] is True
    assert all(report["workspace_broadcast_as_data_probe"]["checks"].values())
    assert all(report["self_generation_budget_probe"]["checks"].values())
    assert report["self_generation_budget_probe"]["deferred_budget"]["deferred"] is True
    assert all(report["answer_grounding_floor_probe"]["checks"].values())
    assert report["answer_grounding_floor_probe"]["active_case"]["abstain"] is True
    assert report["rumination_probe"]["stopped_reason"] == "anti_rumination_repeated_focus_exit"
    assert all(report["checks"].values())
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


def test_g0_report_measures_controller_watts_with_committed_fixture() -> None:
    report = build_report(
        REPO_ROOT,
        baseline_name="baseline-0",
        controller_telemetry_path=CONTROLLER_TELEMETRY_FIXTURE,
    )
    metrics = {metric["id"]: metric for metric in report["metrics"]}
    computed = report["computed_evidence"]["resource_usage_eval"]

    assert report["coverage"]["missing"] == 0
    assert report["coverage"]["gate_ready"] is True
    assert metrics["controller_watts_per_dollar"]["status"] == "measured"
    assert metrics["controller_watts_per_dollar"]["value"] == 50.0
    assert computed["controller_telemetry_present"] is True
    assert computed["telemetry_path"] == CONTROLLER_TELEMETRY_FIXTURE.name
    assert computed["telemetry_sha256"] == hashlib.sha256(
        CONTROLLER_TELEMETRY_FIXTURE.read_bytes()
    ).hexdigest()


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


def test_ablation_gate_can_enforce_absolute_target_pass() -> None:
    baseline = _report(
        [
            {
                **_metric("standing_calibration_error", 0.09, cls="target", direction="decrease"),
                "pass": False,
            }
        ]
    )
    candidate = _report(
        [
            {
                **_metric("standing_calibration_error", 0.08, cls="target", direction="decrease"),
                "pass": False,
            }
        ]
    )

    decision = evaluate_ablation(
        baseline,
        candidate,
        {
            "change_id": "absolute-target-test",
            "target_metric": "standing_calibration_error",
            "direction": "decrease",
            "minimum_delta": 0.0,
            "enforce_target": True,
        },
    )

    assert decision.passed is False
    assert any("absolute report target" in reason for reason in decision.reasons)


def test_ablation_gate_rejects_duplicate_metric_ids() -> None:
    baseline = _report(
        [
            _metric("recall_at_k", 0.80, cls="target", direction="increase"),
            _metric("recall_at_k", 0.81, cls="target", direction="increase"),
        ]
    )
    candidate = _report(
        [_metric("recall_at_k", 0.84, cls="target", direction="increase")]
    )

    with pytest.raises(ValueError, match="baseline contains duplicate metric id 'recall_at_k'"):
        evaluate_ablation(
            baseline,
            candidate,
            {
                "change_id": "duplicate-metric-test",
                "target_metric": "recall_at_k",
                "minimum_delta": 0.01,
            },
        )


def test_ablation_gate_rejects_missing_metric_ids() -> None:
    baseline = _report(
        [_metric("recall_at_k", 0.80, cls="target", direction="increase")]
    )
    candidate = _report(
        [{"class": "target", "direction": "increase", "status": "measured", "value": 0.84}]
    )

    with pytest.raises(ValueError, match=r"candidate metrics\[0\] has missing id"):
        evaluate_ablation(
            baseline,
            candidate,
            {
                "change_id": "missing-metric-id-test",
                "target_metric": "recall_at_k",
                "minimum_delta": 0.01,
            },
        )


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


def test_ablation_gate_requires_controller_telemetry_when_preregistered() -> None:
    missing_controller = {
        **_metric(
            "controller_watts_per_dollar",
            0.0,
            cls="reported",
            direction="decrease",
        ),
        "status": "missing",
        "value": None,
    }
    baseline = _report(
        [
            _metric("workspace_loop_liveness", 1.0, cls="target", direction="increase"),
            missing_controller,
        ]
    )
    candidate = _report(
        [
            _metric("workspace_loop_liveness", 1.1, cls="target", direction="increase"),
            missing_controller,
        ]
    )

    decision = evaluate_ablation(
        baseline,
        candidate,
        {
            "change_id": "future-promoted-workspace-loop",
            "target_metric": "workspace_loop_liveness",
            "direction": "increase",
            "minimum_delta": 0.01,
            "requires_controller_telemetry": True,
        },
    )

    assert decision.passed is False
    assert any("requires_controller_telemetry is true" in reason for reason in decision.reasons)

    measured_without_value = {
        **missing_controller,
        "status": "measured",
        "value": None,
    }
    bogus = evaluate_ablation(
        _report([_metric("workspace_loop_liveness", 1.0, cls="target", direction="increase"), measured_without_value]),
        _report([_metric("workspace_loop_liveness", 1.1, cls="target", direction="increase"), measured_without_value]),
        {
            "change_id": "future-promoted-workspace-loop",
            "target_metric": "workspace_loop_liveness",
            "direction": "increase",
            "minimum_delta": 0.01,
            "requires_controller_telemetry": True,
        },
    )

    assert bogus.passed is False
    assert any("numeric values" in reason for reason in bogus.reasons)

    for bad_value in ("NaN", float("nan"), "Infinity", float("inf"), "-Infinity", float("-inf")):
        non_finite = {
            **missing_controller,
            "status": "measured",
            "value": bad_value,
        }
        non_finite_decision = evaluate_ablation(
            _report(
                [
                    _metric("workspace_loop_liveness", 1.0, cls="target", direction="increase"),
                    non_finite,
                ]
            ),
            _report(
                [
                    _metric("workspace_loop_liveness", 1.1, cls="target", direction="increase"),
                    non_finite,
                ]
            ),
            {
                "change_id": "future-promoted-workspace-loop",
                "target_metric": "workspace_loop_liveness",
                "direction": "increase",
                "minimum_delta": 0.01,
                "requires_controller_telemetry": True,
            },
        )

        assert non_finite_decision.passed is False
        assert any("numeric values" in reason for reason in non_finite_decision.reasons)


def test_g0_report_writer_rejects_non_finite_json(tmp_path: Path) -> None:
    report = build_report(REPO_ROOT, baseline_name="baseline-0")
    report["metrics"][0]["value"] = float("nan")

    with pytest.raises(ValueError, match="Out of range float values"):
        write_report(report, tmp_path)


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
