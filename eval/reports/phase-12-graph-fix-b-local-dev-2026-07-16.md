# Phase 12 W1 Fix B local development result

Status: **local-engine development iteration — non-headline, non-production evidence**.

This receipt covers only the deterministic local engine on
`eval/datasets/v2/qa_scale_dev_v1.json` and the 16-case development
decomposition matrix. It used no reader model, held-out dataset, protected
`qa_hard_v2` data, production Postgres service, or production evidence path.

## Result

The committed unconsolidated baseline remains reproducible at zero persisted
relations, zero `graph_ppr` contribution, and direct-query Recall@5 proxy 0.5.
The opt-in consolidated Fix B cell produced the following repeat result:

| Metric | Run 1 | Run 2 |
|---|---:|---:|
| 16-case development matrix | 16/16 | 16/16 |
| Persisted relations | 7 | 7 |
| `graph_ppr` channel contribution | 24 | 24 |
| Bridge query `graph_ppr` contribution | 1 | 1 |
| Direct-query Recall@5 proxy | 1.0 | 1.0 |
| Direct-query nDCG@5 proxy | 1.0 | 1.0 |
| `traces.jsonl` SHA-256 | `d0a66266b980585d6ae739bbfff2d2866d11c7bd10e43dd9ba4389166699f9b4` | `d0a66266b980585d6ae739bbfff2d2866d11c7bd10e43dd9ba4389166699f9b4` |

Both bridge documents (`d1`, `d2`) were recovered for `q01`; repeat traces
were byte-identical. Relation provenance maps each graph hit back to its source
evidence CID before scoring.

## Reproduction

Run outside the repository so generated evidence cannot be mistaken for a
committed artifact:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m \
  eval.datasets.v2.run_graph_ppr_postfix --output /tmp/mnemo-fix-b-postfix
```

Fresh samples before local pytest/runner invocations showed 53–57% free memory,
load1 2.09–5.04, and an empty `ollama ps` model table. The Colima production VM
remained stopped by operator decision.

## Evidence boundary

These numbers are development diagnostics only. They do not establish
production Postgres parity, BENCH-005, CAP-003, protected benchmark quality, or
headline performance. Those claims remain blocked on their separately admitted
production-stack work.
