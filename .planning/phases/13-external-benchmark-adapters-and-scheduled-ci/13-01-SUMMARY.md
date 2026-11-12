---
phase: 13-external-benchmark-adapters-and-scheduled-ci
plan: 01
status: complete
completed: 2026-07-30
requirements-completed: [BENCH-007]
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

- Exact PR head `8d64afd8fb344f45ddd4c0adde2fcef2140f8365` passed CI run
  `30559003114` before normal merge.
- PR #86 merged as `60b8273175aca2cbdec36364d307075c6c0f7f1a`.
- Input-free `workflow_dispatch` run `30561430522` passed the fixed
  development job on that merge commit.
- Exact post-merge main CI run `30561266140` passed all gating jobs on that
  merge commit; the nightly-only soak was correctly skipped.
- Cadence evidence added on 2026-09-05: real `schedule` run `30807305055`
  succeeded on `2c6a63f12291eb938b2d284c938298fc035d6105`, started
  `2026-08-03T10:52:57Z`. Job `91665545558` and its fixed public-contract test
  step succeeded. Authenticated GitHub run/job metadata is retained in
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  Together with the merged source, this closes BENCH-007; the original source
  completion date above is preserved.

## Remaining Gates

- BENCH-006 remains Partial until exact upstream revisions, rights, full
  provider/model/judge disclosure, operator admission, and official execution
  evidence exist.
- No held-out tuning, official attempt, measured benchmark result, headline,
  leaderboard, publication, or launch claim changed.
