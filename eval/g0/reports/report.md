# Mnemosyne G0 Benchmark Report

- Generated: `2026-06-27T00:32:19.574103+00:00`
- Baseline: `baseline-0` at `96dd7f83d5e3bf73a1a5d2fc40e946ccb8d33393`
- Gate ready: **False** (41/42 metrics measured)

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
| deep_path_p95_ms | reported | measured | 1.862666 | reported | deep_latency_eval |
| cost_usd_per_1k_queries | reported | measured | 0.0 | reported | resource_usage_eval |
| controller_watts_per_dollar | reported | missing |  | reported | resource_usage_eval |
| dreamer_shadow_corroborated_candidate_yield | target | measured | 1.0 | reported | dreamer_eval |
| dreamer_shadow_contract | guardrail | measured | 1.0 | >= 1.0 | dreamer_eval |
| shadow_workspace_useful_transition_rate | target | measured | 1.0 | reported | shadow_workspace_eval |
| shadow_workspace_contract | guardrail | measured | 1.0 | >= 1.0 | shadow_workspace_eval |
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

## Gate Contract

`python -m eval.g0.gate --baseline BASELINE.json --candidate CANDIDATE.json --prereg PREREG.json`
