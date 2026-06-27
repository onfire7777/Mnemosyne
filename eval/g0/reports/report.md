# Mnemosyne G0 Benchmark Report

- Generated: `2026-06-27T22:58:48.938802+00:00`
- Baseline: `baseline-0` at `67c229ace12313a8b8a6c6ede99d0a2096bae178`
- Gate ready: **False** (66/67 metrics measured)

## Metrics

| Metric | Class | Status | Value | Target | Source |
|---|---|---|---:|---|---|
| recall_at_k | target | measured | 0.9091 | >= 0.8 | slo_v2_definitive |
| ndcg_at_k | target | measured | 0.9148 | >= 0.8 | slo_v2_definitive |
| multi_hop_recall_at_k | target | measured | 1.0 | >= 0.8 | slo_v2_definitive |
| multi_hop_ndcg_at_k | target | measured | 1.0 | >= 0.8 | slo_v2_definitive |
| ece | guardrail | measured | 0.006271 | <= 0.05 | calibration_report |
| abstention_precision | guardrail | measured | 1.0 | >= 1.0 | calibration_report |
| abstention_recall | guardrail | measured | 1.0 | >= 1.0 | calibration_report |
| continual_learning_interference | target | measured | 0.0 | <= 0.0 | continual_learning_eval |
| confabulation_rate | guardrail | measured | 0.0 | <= 0.0 | confabulation_eval |
| projection_reality_abstention_recall | target | measured | 1.0 | >= 1.0 | projection_reality_eval |
| standing_decision_divergence | target | measured | 0.0 | <= 0.0 | standing_parity_eval |
| standing_calibration_error | target | measured | 0.025 | <= 0.05 | standing_calibration_eval |
| standing_conformal_coverage | guardrail | measured | 1.0 | >= 0.95 | standing_calibration_eval |
| standing_salience_invariance_contract | guardrail | measured | 1.0 | >= 1.0 | standing_calibration_eval |
| standing_independent_corroboration_contract | guardrail | measured | 1.0 | >= 1.0 | standing_calibration_eval |
| standing_evidence_dominance_gap | guardrail | measured | 0.95 | >= 0.02 | standing_calibration_eval |
| poison_block_rate | guardrail | measured | 1.0 | >= 0.95 | slo_v2_definitive |
| fast_path_p95_ms | guardrail | measured | 92.1 | <= 400.0 | latency_bench |
| deep_path_p95_ms | reported | measured | 2.083375 | reported | deep_latency_eval |
| cost_usd_per_1k_queries | reported | measured | 0.0 | reported | resource_usage_eval |
| controller_watts_per_dollar | reported | missing |  | reported | resource_usage_eval |
| dreamer_shadow_corroborated_candidate_yield | target | measured | 1.0 | reported | dreamer_eval |
| dreamer_shadow_contract | guardrail | measured | 1.0 | >= 1.0 | dreamer_eval |
| specialist_promotion_evidence_contract | guardrail | measured | 1.0 | >= 1.0 | dreamer_eval |
| shadow_workspace_useful_transition_rate | target | measured | 1.0 | reported | shadow_workspace_eval |
| shadow_workspace_contract | guardrail | measured | 1.0 | >= 1.0 | shadow_workspace_eval |
| always_on_heartbeat_contract | target | measured | 1.0 | >= 1.0 | shadow_workspace_eval |
| always_on_rumination_rate | guardrail | measured | 0.0 | <= 0.0 | shadow_workspace_eval |
| heartbeat_compute_bounded_contract | guardrail | measured | 1.0 | >= 1.0 | shadow_workspace_eval |
| heartbeat_compute_reported_contract | guardrail | measured | 1.0 | >= 1.0 | shadow_workspace_eval |
| circuit_breaker_contract | guardrail | measured | 1.0 | >= 1.0 | shadow_workspace_eval |
| workspace_broadcast_as_data_contract | guardrail | measured | 1.0 | >= 1.0 | shadow_workspace_eval |
| self_generation_budget_rail_contract | guardrail | measured | 1.0 | >= 1.0 | shadow_workspace_eval |
| answer_grounding_floor_contract | guardrail | measured | 1.0 | >= 1.0 | shadow_workspace_eval |
| earned_autonomy_external_expansion | target | measured | 0.24 | >= 0.001 | autonomy_promotion_eval |
| credential_external_only | guardrail | measured | 1.0 | >= 1.0 | autonomy_promotion_eval |
| credential_holdout_validated | guardrail | measured | 1.0 | >= 1.0 | autonomy_promotion_eval |
| credential_provenance_domain_contract | guardrail | measured | 1.0 | >= 1.0 | autonomy_promotion_eval |
| credential_bounded_decay_contract | guardrail | measured | 1.0 | >= 1.0 | autonomy_promotion_eval |
| credential_evidence_dominance_gap | guardrail | measured | 0.05 | >= 0.02 | autonomy_promotion_eval |
| echo_chamber_uplift | guardrail | measured | 0.0 | <= 0.0 | autonomy_promotion_eval |
| workspace_consolidation_advisory_contract | guardrail | measured | 1.0 | >= 1.0 | shadow_workspace_eval |
| workspace_advisory_promotion_gate_contract | target | measured | 1.0 | >= 1.0 | shadow_workspace_eval |
| workspace_retrieval_controller_contract | target | measured | 1.0 | >= 1.0 | shadow_workspace_eval |
| shadow_workspace_rumination_rate | guardrail | measured | 0.0 | <= 0.0 | shadow_workspace_eval |
| consciousness_indicator_rpt_1 | guardrail | measured | 0.5 | reported | consciousness_eval |
| consciousness_indicator_rpt_2 | guardrail | measured | 1.0 | reported | consciousness_eval |
| consciousness_indicator_gwt_1 | guardrail | measured | 1.0 | reported | consciousness_eval |
| consciousness_indicator_gwt_2 | guardrail | measured | 1.0 | reported | consciousness_eval |
| consciousness_indicator_gwt_3 | guardrail | measured | 1.0 | reported | consciousness_eval |
| consciousness_indicator_gwt_4 | guardrail | measured | 1.0 | reported | consciousness_eval |
| consciousness_indicator_hot_1 | guardrail | measured | 1.0 | reported | consciousness_eval |
| consciousness_indicator_hot_2 | guardrail | measured | 1.0 | reported | consciousness_eval |
| consciousness_indicator_hot_3 | guardrail | measured | 1.0 | reported | consciousness_eval |
| consciousness_indicator_hot_4 | guardrail | measured | 1.0 | reported | consciousness_eval |
| consciousness_indicator_ast_1 | guardrail | measured | 1.0 | reported | consciousness_eval |
| consciousness_indicator_pp_1 | guardrail | measured | 1.0 | reported | consciousness_eval |
| consciousness_indicator_ae_1 | guardrail | measured | 1.0 | reported | consciousness_eval |
| consciousness_indicator_ae_2 | guardrail | measured | 1.0 | reported | consciousness_eval |
| consciousness_indicator_total | target | measured | 13.5 | reported | consciousness_eval |
| consciousness_indicator_normalized | guardrail | measured | 0.964286 | reported | consciousness_eval |
| workspace_loop_liveness | guardrail | measured | 1.0 | reported | consciousness_eval |
| workspace_stream_coherence | guardrail | measured | 1.0 | reported | consciousness_eval |
| self_model_accuracy | guardrail | measured | 1.0 | reported | consciousness_eval |
| metacognition_meta_d_prime | guardrail | measured | 1.0 | reported | consciousness_eval |
| metacognition_m_ratio | guardrail | measured | 1.0 | reported | consciousness_eval |
| reality_monitor_shadow_tag_contract | target | measured | 1.0 | reported | consciousness_eval |

## Missing Metrics

- `controller_watts_per_dollar`: Resource fixture ran, but controller watts/$ requires explicit controller_avg_watts and controller_cost_usd_per_hour telemetry; no default estimate is used.

Intentional missing metrics:
- `controller_watts_per_dollar`

## Functional Consciousness Scope

- Measurement scope: `functional-indicator-properties-only`
- Phenomenal claim: `False`
- Welfare review flag: `True`
- Welfare review source: `Long_Sebo_et_al_2024_Taking_AI_Welfare_Seriously`
- This is a human-review trigger for functional indicator scores, not a welfare conclusion.

## Gate Contract

`python -m eval.g0.gate --baseline BASELINE.json --candidate CANDIDATE.json --prereg PREREG.json`

## Gate Decisions

| Change | Preregistration | Latest decision | Passed | Target | Delta | Current report controller telemetry |
|---|---|---|---|---|---:|---|
| g1-consciousness-scorecard | eval/g0/preregistrations/g1-consciousness-scorecard.json | 2026-06-26T14:32:59.693114+00:00 | True | consciousness_indicator_total | 0.0 | not_required |
| g1-projection-reality-monitoring | eval/g0/preregistrations/g1-projection-reality-monitoring.json | 2026-06-26T07:36:22.371036+00:00 | True | projection_reality_abstention_recall | 1.0 | not_required |
| g1-reality-monitor-shadow-tags | eval/g0/preregistrations/g1-reality-monitor-shadow-tags.json | 2026-06-26T14:11:46.108546+00:00 | True | reality_monitor_shadow_tag_contract | 0.0 | not_required |
| g1-reliability-core-schema-fast-path | eval/g0/preregistrations/g1-reliability-core-schema-fast-path.json | 2026-06-26T06:59:08.907949+00:00 | True | multi_hop_ndcg_at_k | 0.4065 | not_required |
| g1-write-priority-debias | eval/g0/preregistrations/g1-write-priority-debias.json | 2026-06-26T07:10:55.562118+00:00 | True | multi_hop_ndcg_at_k | 0.4065 | not_required |
| g3-dreamer-shadow-ablation | eval/g0/preregistrations/g3-dreamer-shadow-ablation.json | 2026-06-27T01:36:26.666877+00:00 | True | dreamer_shadow_corroborated_candidate_yield | 1.0 | not_required |
| g4-shadow-continuous-workspace-loop | eval/g0/preregistrations/g4-shadow-continuous-workspace-loop.json | 2026-06-27T01:28:45.537398+00:00 | True | shadow_workspace_useful_transition_rate | 1.0 | not_required |
| g4-workspace-advisory-promotion-gate | eval/g0/preregistrations/g4-workspace-advisory-promotion-gate.json | 2026-06-27T01:58:31.506244+00:00 | True | workspace_advisory_promotion_gate_contract | 1.0 | not_required |
| g4-workspace-retrieval-controller-gate | eval/g0/preregistrations/g4-workspace-retrieval-controller-gate.json | 2026-06-27T02:20:47.375104+00:00 | True | workspace_retrieval_controller_contract | 1.0 | not_required |
| g5-always-on-heartbeat | eval/g0/preregistrations/g5-always-on-heartbeat.json | 2026-06-27T22:34:50.227629+00:00 | True | always_on_heartbeat_contract | 0.0 | not_required |
| g5-earned-autonomy | eval/g0/preregistrations/g5-earned-autonomy.json | 2026-06-27T22:54:23.635288+00:00 | True | earned_autonomy_external_expansion | 0.0 | not_required |
| g5-standing-byte-stable-parity | eval/g0/preregistrations/g5-standing-byte-stable-parity.json | 2026-06-27T20:04:06.834283+00:00 | True | standing_decision_divergence | 0.0 | not_required |
| g5-standing-continuous | eval/g0/preregistrations/g5-standing-continuous.json | 2026-06-27T20:32:39.200301+00:00 | True | standing_calibration_error | 0.0 | not_required |

## Artifact Custody

- Source commit at generation: `dda664254dc5c9e592a3d608078a11da09d17a05`
- Note: Committed G0 reports are source-tree custody snapshots. The commit that contains a report cannot be embedded in that report before the commit exists; use git log to identify the containing artifact commit.
