# Mnemosyne G0 Benchmark Report

- Generated: `2026-06-27T17:08:36.594722+00:00`
- Baseline: `baseline-0` at `0278d951e392c91dfc2aee2e10180e0d790385e8`
- Gate ready: **False** (45/46 metrics measured)

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
| poison_block_rate | guardrail | measured | 1.0 | >= 0.95 | slo_v2_definitive |
| fast_path_p95_ms | guardrail | measured | 92.1 | <= 400.0 | latency_bench |
| deep_path_p95_ms | reported | measured | 2.392042 | reported | deep_latency_eval |
| cost_usd_per_1k_queries | reported | measured | 0.0 | reported | resource_usage_eval |
| controller_watts_per_dollar | reported | missing |  | reported | resource_usage_eval |
| dreamer_shadow_corroborated_candidate_yield | target | measured | 1.0 | reported | dreamer_eval |
| dreamer_shadow_contract | guardrail | measured | 1.0 | >= 1.0 | dreamer_eval |
| specialist_promotion_evidence_contract | guardrail | measured | 1.0 | >= 1.0 | dreamer_eval |
| shadow_workspace_useful_transition_rate | target | measured | 1.0 | reported | shadow_workspace_eval |
| shadow_workspace_contract | guardrail | measured | 1.0 | >= 1.0 | shadow_workspace_eval |
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

## Artifact Custody

- Source commit at generation: `0278d951e392c91dfc2aee2e10180e0d790385e8`
- Note: Committed G0 reports are source-tree custody snapshots. The commit that contains a report cannot be embedded in that report before the commit exists; use git log to identify the containing artifact commit.
