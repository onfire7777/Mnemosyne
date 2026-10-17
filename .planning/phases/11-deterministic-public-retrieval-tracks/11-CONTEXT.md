---
phase: 11-deterministic-public-retrieval-tracks
status: planned
created: 2026-07-10
---

# Phase 11 Context

Phase 11 wires the first real public retrieval datasets into the Phase 10
custody harness. The primary tracks are LongMemEval cleaned retrieval recall
and the HippoRAG 2 sampled MuSiQue, 2WikiMultiHopQA, and HotpotQA corpora.

The system boundary remains the public `mneme` CLI subprocess seam. Full public
datasets stay out of git and enter through immutable revision plus SHA-256
custody. Tiny schema-faithful fixtures are permitted for tests but are always
development-only and non-publishable.

HippoRAG Recall@2/@5 is deterministic. EM/F1 scoring is deterministic once a
prediction exists, but prediction generation is not. Phase 11 therefore ships
the scorer and retrieval evidence; Phase 12 supplies disclosed grounded-reader
predictions before BENCH-005 can become complete.

GitHub Actions exact-SHA verification is currently externally blocked because
GitHub rejected every job before checkout for account billing/spending-limit
reasons (run 29128327918, retried once). Local gates continue; the CI gate stays
open and must be replayed after billing is restored.

