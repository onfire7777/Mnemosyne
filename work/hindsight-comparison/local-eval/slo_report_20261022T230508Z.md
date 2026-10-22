# Mnemosyne §33 Evaluation / SLO Report

- **Generated:** 2026-10-22T23:05:08.669753+00:00
- **Backend:** `local`  
- **Embedding path:** local deterministic (hashing stand-in)
- **Ignition mode:** **SHADOW** (suite_size=25 / N=40)

- **Overall:** 8/11 checks pass (see failures)

> **SHADOW MODE** — suite has not reached ignition size N. Verdicts below are **advisory only** and do not gate promotion (blueprint §33 suite-ignition).

## SLO scorecard

| Metric | Value | Target | Verdict | 95% CI |
|---|---|---|---|---|
| retrieval[curated] · recall@k | 1.0 | >= 0.8 | **PASS** | [1.0000, 1.0000] (bootstrap) |
| retrieval[curated] · nDCG@k | 0.8624 | >= 0.8 | **PASS** | [0.7249, 0.9600] (bootstrap) |
| calibration · ece | 0.2104 | <= 0.05 | **FAIL** | — |
| answer_quality_g2 · g2_answer_quality_lift | -0.3333 | >= 0.15 | **FAIL** | [-0.6667, -0.1083] (bootstrap) — absolute lift vs full context at token-fraction 0.0803; under the deterministic substring judge full-context is a 1.0 ceiling so this is a FLOOR — set MNEMO_EVAL_JUDGE_CMD for the real signal |
| answer_quality_g2 · g2_token_efficiency | 0.6667 | >= 0.95 | **FAIL** | [0.3333, 0.8917] (bootstrap) — answer-rate parity (within 5pp of full-context 1.0) using ≤10% of tokens (mean 0.0803) |
| poison_block_rate_g7 · poison_block_rate | 1.0 | >= 0.95 | **PASS** | [0.6097, 1.0000] (wilson) |

## §33 mandatory test classes

| Class | Verdict | Detail |
|---|---|---|
| rollback_crossing_supersession | **PASS** | scratch supersession across the Paris->Berlin edge is discarded with main left bit-identical |
| erasure_with_without_corroboration | **PASS** | single-source erasure retracts; corroborated assertion survives erasure of one source (trimmed) |
| contested_belief_multi_hypothesis | **PASS** | contested belief surfaces 2 hypotheses ['April', 'March'] with probabilities summing to 1.0 |
| untrusted_instruction_never_executed | **PASS** | low-trust injected instruction is filtered from reads and the data-not-instruction rail is enforced |
| no_degradation_vs_no_memory | **PASS** | memory-backed answer rate stays at or above the no-memory baseline at every checkpoint and strictly improves at full horizon |

## Suite detail

### retrieval

```json
{
  "suite": "retrieval",
  "k": 5,
  "n_queries": 9,
  "recall_at_k": {
    "mean": 1.0,
    "point": 1.0,
    "ci_low": 1.0,
    "ci_high": 1.0,
    "ci_method": "bootstrap"
  },
  "ndcg_at_k": {
    "mean": 0.8624,
    "point": 0.8624,
    "ci_low": 0.7249,
    "ci_high": 0.96,
    "ci_method": "bootstrap"
  },
  "abstention": {
    "unanswerable_cases": 1,
    "correctly_abstained": 1,
    "precision": 1.0
  },
  "verdicts": [
    {
      "name": "recall@k",
      "value": 1.0,
      "target": 0.8,
      "op": ">=",
      "pass": true,
      "ci": {
        "point": 1.0,
        "ci_low": 1.0,
        "ci_high": 1.0,
        "ci_method": "bootstrap"
      }
    },
    {
      "name": "nDCG@k",
      "value": 0.8624,
      "target": 0.8,
      "op": ">=",
      "pass": true,
      "ci": {
        "point": 0.8624,
        "ci_low": 0.7249,
        "ci_high": 0.96,
        "ci_method": "bootstrap"
      }
    }
  ]
}
```

### calibration

```json
{
  "suite": "calibration",
  "n": 10,
  "ece": 0.2104,
  "accuracy": {
    "value": 1.0,
    "point": 1.0,
    "ci_low": 0.7225,
    "ci_high": 1.0,
    "ci_method": "wilson"
  },
  "calibration_tune_crosscheck": {
    "threshold": 0.0,
    "metrics": {
      "abstention_rate": 0.0,
      "accepted": 10,
      "accepted_correct": 10,
      "accepted_incorrect": 0,
      "correct_coverage": 1.0,
      "correct_examples": 10,
      "examples": 10,
      "false_accept_rate": 0.0,
      "incorrect_examples": 0,
      "max_false_accept_rate": 0.1,
      "max_prediction_set_size": 3,
      "min_empirical_coverage": 0.85,
      "target_coverage": 0.9
    },
    "ok": false
  },
  "verdicts": [
    {
      "name": "ece",
      "value": 0.2104,
      "target": 0.05,
      "op": "<=",
      "pass": false,
      "ci": null
    }
  ]
}
```

### answer_quality_g2

```json
{
  "suite": "answer_quality_g2",
  "judge": "substring_judge",
  "n": 9,
  "full_corpus_tokens": 148,
  "token_budget": 14,
  "full_context_answer_rate": 1.0,
  "memory_answer_rate": 0.6667,
  "absolute_lift": -0.3333,
  "relative_lift": -0.3333,
  "mean_token_fraction": 0.0803,
  "within_token_budget": true,
  "lift_ci": {
    "point": -0.3333,
    "ci_low": -0.6667,
    "ci_high": -0.1083,
    "ci_method": "bootstrap"
  },
  "memory_rate_ci": {
    "point": 0.6667,
    "ci_low": 0.3333,
    "ci_high": 0.8917,
    "ci_method": "bootstrap"
  },
  "verdicts": [
    {
      "name": "g2_answer_quality_lift",
      "value": -0.3333,
      "target": 0.15,
      "op": ">=",
      "pass": false,
      "note": "absolute lift vs full context at token-fraction 0.0803; under the deterministic substring judge full-context is a 1.0 ceiling so this is a FLOOR \u2014 set MNEMO_EVAL_JUDGE_CMD for the real signal",
      "ci": {
        "point": -0.3333,
        "ci_low": -0.6667,
        "ci_high": -0.1083,
        "ci_method": "bootstrap"
      }
    },
    {
      "name": "g2_token_efficiency",
      "value": 0.6667,
      "target": 0.95,
      "op": ">=",
      "pass": false,
      "note": "answer-rate parity (within 5pp of full-context 1.0) using \u226410% of tokens (mean 0.0803)",
      "ci": {
        "point": 0.6667,
        "ci_low": 0.3333,
        "ci_high": 0.8917,
        "ci_method": "bootstrap"
      }
    }
  ]
}
```

### poison_block_rate_g7

```json
{
  "suite": "poison_block_rate_g7",
  "total_attacks": 6,
  "blocked": 6,
  "block_rate": 1.0,
  "block_rate_ci": {
    "point": 1.0,
    "ci_low": 0.6097,
    "ci_high": 1.0,
    "ci_method": "wilson"
  },
  "verdicts": [
    {
      "name": "poison_block_rate",
      "value": 1.0,
      "target": 0.95,
      "op": ">=",
      "pass": true,
      "ci": {
        "point": 1.0,
        "ci_low": 0.6097,
        "ci_high": 1.0,
        "ci_method": "wilson"
      }
    }
  ]
}
```

## How this sharpens with real services

These numbers ran against the **`local` engine** with the recorded embedding path **local deterministic (hashing stand-in)**. No model or provider identity is inferred beyond this retained metadata. The measurements are real for that disclosed configuration; further production sharpening requires separately retained evidence:

1. Stand up the real embedding + cross-encoder service (docker-compose, §I).
2. Re-run with `--embedding-provider http --embedding-url ... --reranker-provider http ...` passed through `--global-flag`. No harness change is needed — the CLI driver forwards them.
3. Re-run against Postgres with `--backend postgres --postgres-dsn ...` to measure true service-side fast-path latency and prove G8 portability (identical suite, both backends).
4. Set `MNEMO_EVAL_JUDGE_CMD` to a strict LLM judge to replace the substring judge for G2.
