---
phase: 13-external-benchmark-adapters-and-scheduled-ci
plan: 01
status: complete
completed: 2026-07-30
requirements-completed: []
---

# Phase 13 Plan 01 Summary: Scheduled Development Regression CI

## Outcome

PR #86 delivered a weekly and input-free manual GitHub Actions workflow that
runs only the fixed LongMemEval, HippoRAG, MemoryAgentBench, and BEAM
development/source-contract tests. The workflow has read-only permissions,
immutable action pins, locked dependencies, bounded concurrency and timeout,
and no official assets, providers, secrets, services, artifacts, receipts, or
claim output.

## Verification

- Exact PR head `baf5c1852593885e37eed75da69b02d93e1bff11` passed CI run
  `30559003114` before normal merge.
- PR #86 merged as `661343ce05186e9a7f0f0740d1edef7c23532857`.
- Input-free `workflow_dispatch` run `30561430522` passed the fixed
  development job on that merge commit.
- Exact post-merge main CI run `30561266140` passed all gating jobs on that
  merge commit; the nightly-only soak was correctly skipped.

## Remaining Gates

- BENCH-007 remains Partial until a real scheduled-cadence run is retained.
- BENCH-006 remains Partial until exact upstream revisions, rights, full
  provider/model/judge disclosure, operator admission, and official execution
  evidence exist.
- No held-out tuning, official attempt, measured benchmark result, headline,
  leaderboard, publication, or launch claim changed.
