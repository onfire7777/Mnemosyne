# Phase 12 local graph-PPR dead-graph baseline

This report records the deterministic pre-fix graph baseline on development and
synthetic data only. It does not use MuSiQue, 2WikiMultiHopQA, HotpotQA,
`qa_hard_v2`, a protected reader, a model, PostgreSQL, or a live service.

## Scope and engine custody

- Source commit: `7bca39e250f6227298cf3f0b1950fdd9d59905b3`
- Dataset: `eval/datasets/v2/qa_scale_dev_v1.json` (`24` questions)
- Decomposition matrix: `eval/datasets/v2/qa_decomposition_dev_v1.json`
- Capture surface: public `capture-batch` through `MnemoCLI.capture_batch`
- Retrieval surface: public `eval-query-batch` through
  `MnemoCLI.eval_query_batch`
- Actual engine: `LocalMemoryEngine` via the default `backend="local"`; no
  `--graph-retrieval-command` was supplied
- Scorer: the existing `_retrieval_score` implementation in
  `eval/datasets/v2/run_grounded_qa_v2.py`

The versioned matrix contains 15 question-only cases. Its existing companion
authorized-evidence deferral case is the sixteenth case; all 16 passed. The
matrix tests decomposition behavior and is reported separately from the
24-question retrieval metrics.

## Measured baseline

| Measurement | Run 1 | Run 2 |
|---|---:|---:|
| Captured corpus rows | 2 | 2 |
| Queries | 24 | 24 |
| Persisted relations | 0 | 0 |
| `graph_ppr` channel contribution | 0 | 0 |
| Recall@5 | 0.5 | 0.5 |
| nDCG@5 | 0.6131471927654584 | 0.6131471927654584 |
| `traces.jsonl` SHA-256 | `1a16bb0d00dc106e59c3eafd3942d4a9eded08a1f56c07a59f02605361925437` | `1a16bb0d00dc106e59c3eafd3942d4a9eded08a1f56c07a59f02605361925437` |

The two `traces.jsonl` files are byte-identical. The current lexical/dense path
retrieves one of the two relevant documents, producing Recall@5 `0.5`; the
missing bridge document leaves graph-specific bridge participation at `0`.
Round 7 must flip this baseline to relations greater than zero, at least one
positive `graph_ppr` contribution on the bridge query, and Recall@5 `1.0`.

## Reproduction

Run from the repository root with a new external output path:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m eval.datasets.v2.run_graph_ppr_baseline \
  --output /tmp/mnemosyne-phase12-graph-baseline-20260715
cmp \
  /tmp/mnemosyne-phase12-graph-baseline-20260715/run-1/traces.jsonl \
  /tmp/mnemosyne-phase12-graph-baseline-20260715/run-2/traces.jsonl
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  tests/test_phase12_graph_baseline.py tests/test_extractive_decomposer.py
```

The runner refuses to overwrite an existing output directory. Each run retains
its local store, capture/query JSONL inputs, `metrics.json`, and `traces.jsonl`;
the output root also contains `summary.json`.

## PBPP honesty item

Every measured explanation disclosed `graph_backend` as
`postgres-recursive-ppr`, while the evaluator actually ran the local engine.
This is a presentation/backend-provenance mismatch, not evidence of a
PostgreSQL run. The round-7 fix slice must reconcile the disclosure with the
engine actually selected.

## Boundary encountered

The full `run_grounded_qa_v2.py` answer stage was attempted once and stopped
fail-closed because grounded answer role commands are not configured. No role
command, model, service, or admission-gated resource was substituted. The
baseline therefore measures the harness's public capture and retrieval path and
uses its exact retrieval scorer; it makes no QA EM/F1 claim.
