---
phase: 11-deterministic-public-retrieval-tracks
status: passed-with-requirement-boundary
verified: 2026-07-11
requirements-complete:
  - BENCH-004
requirements-partial:
  - BENCH-005
requirements-continuous:
  - RAIL-001
  - RAIL-002
  - RAIL-003
  - RAIL-004
---

# Phase 11 Verification

## Result

**PASSED for Phase 11 retrieval scope.** The generalized custody layer,
LongMemEval retrieval track, and three HippoRAG retrieval tracks are complete.
BENCH-005 remains partial because graph/PPR participation measured zero and
Phase 12 has not yet produced real disclosed-reader EM/F1.

## Evidence

- Focused public-evaluation gate: 61 tests passed.
- Full locked repository gate passed at the Phase 11 evidence head with only
  expected environment-gated skips.
- Source and reproduced bundles verified for LongMemEval, MuSiQue, 2Wiki, and
  HotpotQA; traces and metrics matched byte-for-byte for all four.
- All four external JSON reports verified against committed Markdown notes.
- Ruff, secret scanning, dependency/lock review, planning consistency, and
  `git diff --check` are required again on the final closure diff.
- Independent review found no implementation blocker and required the explicit
  graph-zero, baseline-context, and requirement-boundary projection now guarded
  by `tests/test_public_requirement_truth.py`.

## Report Digests

| Suite | External report SHA-256 |
|---|---|
| LongMemEval | `432cf16a755ca70bb5bc764a7e7cde30cde362675b395247e9c5f8b332689676` |
| MuSiQue | `85e063aa81fed06e2f1c8e36b8311207fc18912357f3fdbf73e1e6243e6eda76` |
| 2Wiki | `7856c425c913d61db62caefc3af033c53d76ed406b27a4ebc190dd9f88951abe` |
| HotpotQA | `d4b55046b114b8d7241a794392f375c152f11700a42fef454315b149636ade34` |

## Publication Boundary

All results remain non-publishable, non-headline, and not independently
reproduced by a third party. Phase 14 owns independent reproduction. RAIL-001
through RAIL-004 remain continuous gates rather than one-time completions.

## Exact-SHA CI External Blocker

GitHub Actions is externally blocked before checkout by account billing or
spending-limit enforcement. This is not a code failure and is not recorded as
a passing CI run; exact-SHA CI must be replayed after the account is restored.
