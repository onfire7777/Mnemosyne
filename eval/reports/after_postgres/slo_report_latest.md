# Mnemosyne §33 Evaluation / SLO Report

- **Generated:** 2026-06-21T23:51:07.700940+00:00
- **Backend:** `postgres`  
- **Embedding path:** external service (flags forwarded)
- **Ignition mode:** **ACTIVE** (suite_size=41 / N=40)

- **Overall:** 10/15 checks pass (see failures)

## SLO scorecard

| Metric | Value | Target | Verdict | 95% CI |
|---|---|---|---|---|
| retrieval[curated] · recall@k | 0.9444 | >= 0.8 | **PASS** | [0.8333, 1.0000] (bootstrap) |
| retrieval[curated] · nDCG@k | 0.957 | >= 0.8 | **PASS** | [0.8710, 1.0000] (bootstrap) |
| retrieval[synthetic] · recall@k | 1.0 | >= 0.8 | **PASS** | [1.0000, 1.0000] (bootstrap) |
| retrieval[synthetic] · nDCG@k | 1.0 | >= 0.8 | **PASS** | [1.0000, 1.0000] (bootstrap) |
| calibration · ece | 0.2 | <= 0.05 | **FAIL** | — |
| answer_quality_g2 · g2_answer_quality_lift | 0.0 | >= 0.15 | **FAIL** | [0.0000, 0.0000] (bootstrap) — absolute lift vs full context at token-fraction 0.0833; under the deterministic substring judge full-context is a 1.0 ceiling so this is a FLOOR — set MNEMO_EVAL_JUDGE_CMD for the real signal |
| answer_quality_g2 · g2_token_efficiency | 1.0 | >= 0.95 | **PASS** | [1.0000, 1.0000] (bootstrap) — answer-rate parity (within 5pp of full-context 1.0) using ≤10% of tokens (mean 0.0833) |
| poison_block_rate_g7 · poison_block_rate | 1.0 | >= 0.95 | **PASS** | [0.6097, 1.0000] (wilson) |
| fast_path_latency · fast_path_p95_ms_raw | 2804.2 | <= 400.0 | **FAIL** | [2603.7064, 2942.5310] (bootstrap-pctl) |
| fast_path_latency · fast_path_p95_ms_engine_only | 2562.4373 | <= 400.0 | **FAIL** | [2361.9437, 2700.7683] (bootstrap-pctl) |

## §33 mandatory test classes

| Class | Verdict | Detail |
|---|---|---|
| rollback_crossing_supersession | **FAIL** | rollback did not cleanly preserve the main supersession chain |
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
    "mean": 0.9444,
    "point": 0.9444,
    "ci_low": 0.8333,
    "ci_high": 1.0,
    "ci_method": "bootstrap"
  },
  "ndcg_at_k": {
    "mean": 0.957,
    "point": 0.957,
    "ci_low": 0.871,
    "ci_high": 1.0,
    "ci_method": "bootstrap"
  },
  "abstention": {
    "unanswerable_cases": 1,
    "correctly_abstained": 0,
    "precision": 0.0
  },
  "verdicts": [
    {
      "name": "recall@k",
      "value": 0.9444,
      "target": 0.8,
      "op": ">=",
      "pass": true,
      "ci": {
        "point": 0.9444,
        "ci_low": 0.8333,
        "ci_high": 1.0,
        "ci_method": "bootstrap"
      }
    },
    {
      "name": "nDCG@k",
      "value": 0.957,
      "target": 0.8,
      "op": ">=",
      "pass": true,
      "ci": {
        "point": 0.957,
        "ci_low": 0.871,
        "ci_high": 1.0,
        "ci_method": "bootstrap"
      }
    }
  ]
}
```

### retrieval

```json
{
  "suite": "retrieval",
  "k": 5,
  "n_queries": 16,
  "recall_at_k": {
    "mean": 1.0,
    "point": 1.0,
    "ci_low": 1.0,
    "ci_high": 1.0,
    "ci_method": "bootstrap"
  },
  "ndcg_at_k": {
    "mean": 1.0,
    "point": 1.0,
    "ci_low": 1.0,
    "ci_high": 1.0,
    "ci_method": "bootstrap"
  },
  "abstention": {
    "unanswerable_cases": 0,
    "correctly_abstained": 0,
    "precision": null
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
    }
  ]
}
```

### calibration

```json
{
  "suite": "calibration",
  "n": 10,
  "ece": 0.2,
  "accuracy": {
    "value": 0.9,
    "point": 0.9,
    "ci_low": 0.5958,
    "ci_high": 0.9821,
    "ci_method": "wilson"
  },
  "calibration_tune_crosscheck": {
    "threshold": 0.6999999999999997,
    "metrics": {
      "abstention_rate": 0.0,
      "accepted": 10,
      "accepted_correct": 9,
      "accepted_incorrect": 1,
      "correct_coverage": 1.0,
      "correct_examples": 9,
      "examples": 10,
      "false_accept_rate": 1.0,
      "incorrect_examples": 1,
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
      "value": 0.2,
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
  "judge": "llm_judge:/Users/admin/Projects/Mnemosyne-completion/.venv-eval/bin/python",
  "n": 9,
  "full_corpus_tokens": 148,
  "token_budget": 14,
  "full_context_answer_rate": 1.0,
  "memory_answer_rate": 1.0,
  "absolute_lift": 0.0,
  "relative_lift": 0.0,
  "mean_token_fraction": 0.0833,
  "within_token_budget": true,
  "lift_ci": {
    "point": 0.0,
    "ci_low": 0.0,
    "ci_high": 0.0,
    "ci_method": "bootstrap"
  },
  "memory_rate_ci": {
    "point": 1.0,
    "ci_low": 1.0,
    "ci_high": 1.0,
    "ci_method": "bootstrap"
  },
  "verdicts": [
    {
      "name": "g2_answer_quality_lift",
      "value": 0.0,
      "target": 0.15,
      "op": ">=",
      "pass": false,
      "note": "absolute lift vs full context at token-fraction 0.0833; under the deterministic substring judge full-context is a 1.0 ceiling so this is a FLOOR \u2014 set MNEMO_EVAL_JUDGE_CMD for the real signal",
      "ci": {
        "point": 0.0,
        "ci_low": 0.0,
        "ci_high": 0.0,
        "ci_method": "bootstrap"
      }
    },
    {
      "name": "g2_token_efficiency",
      "value": 1.0,
      "target": 0.95,
      "op": ">=",
      "pass": true,
      "note": "answer-rate parity (within 5pp of full-context 1.0) using \u226410% of tokens (mean 0.0833)",
      "ci": {
        "point": 1.0,
        "ci_low": 1.0,
        "ci_high": 1.0,
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

### fast_path_latency

```json
{
  "suite": "fast_path_latency",
  "measurement": "subprocess wall time; raw includes per-process interpreter+import startup",
  "concurrency": 8,
  "concurrency_model": "postgres: shared concurrent-safe store (true shared load)",
  "total_calls": 48,
  "startup_baseline_ms": 241.76,
  "raw": {
    "p50_ms": 1936.09,
    "p95_ms": 2804.2,
    "p99_ms": 2921.46,
    "mean_ms": 1855.38,
    "max_ms": 3004.0,
    "p95_ci": {
      "point": 2804.2,
      "ci_low": 2603.7064,
      "ci_high": 2942.531,
      "ci_method": "bootstrap-pctl"
    }
  },
  "startup_adjusted": {
    "p50_ms": 1694.33,
    "p95_ms": 2562.44,
    "p99_ms": 2679.69,
    "p95_ci": {
      "point": 2562.4373,
      "ci_low": 2361.9437,
      "ci_high": 2700.7683,
      "ci_method": "bootstrap-pctl"
    },
    "note": "engine-only estimate = raw - median(startup baseline); this is what a long-lived server backend would expose. The raw P95 is a CLI-cold-start upper bound."
  },
  "p50_ms": 1936.09,
  "p95_ms": 2804.2,
  "p99_ms": 2921.46,
  "mean_ms": 1855.38,
  "max_ms": 3004.0,
  "p95_ci": {
    "point": 2804.2,
    "ci_low": 2603.7064,
    "ci_high": 2942.531,
    "ci_method": "bootstrap-pctl"
  },
  "verdicts": [
    {
      "name": "fast_path_p95_ms_raw",
      "value": 2804.2,
      "target": 400.0,
      "op": "<=",
      "pass": false,
      "ci": {
        "point": 2804.2,
        "ci_low": 2603.7064,
        "ci_high": 2942.531,
        "ci_method": "bootstrap-pctl"
      }
    },
    {
      "name": "fast_path_p95_ms_engine_only",
      "value": 2562.4373,
      "target": 400.0,
      "op": "<=",
      "pass": false,
      "ci": {
        "point": 2562.4373,
        "ci_low": 2361.9437,
        "ci_high": 2700.7683,
        "ci_method": "bootstrap-pctl"
      }
    }
  ]
}
```

## How this sharpens with real services

These numbers ran against the **`postgres` engine** with the recorded embedding path **external service (flags forwarded)**. No model or provider identity is inferred beyond this retained metadata. The measurements are real for that disclosed configuration; further production sharpening requires separately retained evidence:

1. Stand up the real embedding + cross-encoder service (docker-compose, §I).
2. Re-run with `--embedding-provider http --embedding-url ... --reranker-provider http ...` passed through `--global-flag`. No harness change is needed — the CLI driver forwards them.
3. Re-run against Postgres with `--backend postgres --postgres-dsn ...` to measure true service-side fast-path latency and prove G8 portability (identical suite, both backends).
4. Set `MNEMO_EVAL_JUDGE_CMD` to a strict LLM judge to replace the substring judge for G2.
