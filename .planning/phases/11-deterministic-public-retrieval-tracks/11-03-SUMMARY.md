---
phase: 11-deterministic-public-retrieval-tracks
plan: 03
status: complete
completed: 2026-07-11
requirements-partial:
  - BENCH-005
---

# Phase 11 Plan 03 Summary: HippoRAG Multi-Hop Retrieval

## Outcome

All three pinned 1,000-query retrieval tracks ran, verified, reproduced, and
produced manifest-bound reports. MuSiQue Recall@2/@5 is
`0.08083333333333333`/`0.10416666666666667`, 2Wiki is
`0.17525`/`0.23725`, and HotpotQA is `0.319`/`0.374`.

## Truth Boundary

Graph participation was observed in `0/1000` traces for every track and each
`graph_ppr` channel sum is zero. No QA reader or judge ran; EM/F1 keys are
absent. This completes the Phase 11 retrieval work but does not complete
BENCH-005. Positive graph/PPR participation and real disclosed-reader EM/F1
remain required.

The canonical metrics, upstream baseline context, graph-zero disclosure, and
publication boundary are recorded in `eval/reports/phase-11-evidence.md`.
