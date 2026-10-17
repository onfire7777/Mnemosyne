---
phase: 11-deterministic-public-retrieval-tracks
plan: 02
status: complete
completed: 2026-07-11
requirements-completed:
  - BENCH-004
---

# Phase 11 Plan 02 Summary: LongMemEval Retrieval Recall

## Outcome

The full pinned cleaned LongMemEval track ran 500 eligible questions with
per-question session/turn labels and no LLM scorer. Recall@5 is `0.2806` and
nDCG@5 is `0.2967188496001503`, each with fixed-seed bootstrap intervals.

## Custody

- Source and reproduced manifest SHA-256:
  `01e621fc245a951c5761ccc08be96e688d83b7a080d13499f5f9ef8426e48208`.
- External report SHA-256:
  `432cf16a755ca70bb5bc764a7e7cde30cde362675b395247e9c5f8b332689676`.
- Traces and metrics are byte-identical across reproduction.
- Four secret-shaped source substrings were deterministically redacted during
  normalization; raw pins and normalized digest remain bound.
- The result is non-publishable, non-headline, and not independent external
  reproduction.
