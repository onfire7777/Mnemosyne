# Mnemosyne G0 Benchmark Report

- Generated: `2026-06-26T08:22:16.307356+00:00`
- Baseline: `baseline-0` at `e64491a0d290411f4e55abb75cd5a8fabdcde6a6`
- Gate ready: **False** (14/15 metrics measured)

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
| deep_path_p95_ms | reported | measured | 0.417917 | reported | deep_latency_eval |
| cost_usd_per_1k_queries | reported | measured | 0.0 | reported | resource_usage_eval |
| controller_watts_per_dollar | reported | missing |  | reported | resource_usage_eval |

## Missing Metrics

- `controller_watts_per_dollar`: Resource fixture ran, but controller watts/$ requires explicit controller_avg_watts and controller_cost_usd_per_hour telemetry; no default estimate is used.

## Gate Contract

`python -m eval.g0.gate --baseline BASELINE.json --candidate CANDIDATE.json --prereg PREREG.json`
