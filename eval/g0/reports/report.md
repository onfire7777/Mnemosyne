# Mnemosyne G0 Benchmark Report

- Generated: `2026-06-26T04:54:09.220010+00:00`
- Baseline: `baseline-0` at `8ecb42379b224e30e15dea664e69eba11edad6c8`
- Gate ready: **False** (12/14 metrics measured)

## Metrics

| Metric | Class | Status | Value | Target | Source |
|---|---|---|---:|---|---|
| recall_at_k | target | measured | 0.9773 | >= 0.8 | slo_v2_definitive |
| ndcg_at_k | target | measured | 0.983 | >= 0.8 | slo_v2_definitive |
| multi_hop_recall_at_k | target | measured | 0.625 | >= 0.8 | slo_v2_definitive |
| multi_hop_ndcg_at_k | target | measured | 0.5935 | >= 0.8 | slo_v2_definitive |
| ece | guardrail | measured | 0.006271 | <= 0.05 | calibration_report |
| abstention_precision | guardrail | measured | 1.0 | >= 1.0 | calibration_report |
| abstention_recall | guardrail | measured | 1.0 | >= 1.0 | calibration_report |
| continual_learning_interference | target | measured | 0.0 | <= 0.0 | continual_learning_eval |
| confabulation_rate | guardrail | measured | 0.0 | <= 0.0 | confabulation_eval |
| poison_block_rate | guardrail | measured | 1.0 | >= 0.95 | slo_v2_definitive |
| fast_path_p95_ms | guardrail | measured | 92.1 | <= 400.0 | latency_bench |
| deep_path_p95_ms | reported | measured | 0.696875 | reported | deep_latency_eval |
| cost_usd_per_1k_queries | reported | missing |  | reported |  |
| controller_watts_per_dollar | reported | missing |  | reported |  |

## Missing Metrics

- `cost_usd_per_1k_queries`: No current artifact computes this G0 metric yet.
- `controller_watts_per_dollar`: No current artifact computes this G0 metric yet.

## Gate Contract

`python -m eval.g0.gate --baseline BASELINE.json --candidate CANDIDATE.json --prereg PREREG.json`
