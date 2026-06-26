# Mnemosyne G0 Benchmark Report

- Generated: `2026-06-26T04:24:42.458431+00:00`
- Baseline: `baseline-0` at `a488464cac8d63fb27704eac7c28fd3108163562`
- Gate ready: **False** (10/14 metrics measured)

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
| continual_learning_interference | target | missing |  | <= 0.0 |  |
| confabulation_rate | guardrail | measured | 0.0 | <= 0.0 | confabulation_eval |
| poison_block_rate | guardrail | measured | 1.0 | >= 0.95 | slo_v2_definitive |
| fast_path_p95_ms | guardrail | measured | 92.1 | <= 400.0 | latency_bench |
| deep_path_p95_ms | reported | missing |  | reported |  |
| cost_usd_per_1k_queries | reported | missing |  | reported |  |
| controller_watts_per_dollar | reported | missing |  | reported |  |

## Missing Metrics

- `continual_learning_interference`: No current artifact computes this G0 metric yet.
- `deep_path_p95_ms`: No current artifact computes this G0 metric yet.
- `cost_usd_per_1k_queries`: No current artifact computes this G0 metric yet.
- `controller_watts_per_dollar`: No current artifact computes this G0 metric yet.

## Gate Contract

`python -m eval.g0.gate --baseline BASELINE.json --candidate CANDIDATE.json --prereg PREREG.json`
