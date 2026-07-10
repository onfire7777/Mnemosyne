---
phase: 10-public-harness-and-neutral-governance-foundation
plan: 01
status: complete
completed: 2026-07-10
requirements-completed:
  - BENCH-001
  - BENCH-002
  - BENCH-003
---

# Phase 10 Plan 01 Summary: Public Harness and Bundle Custody

## Outcome

`mneme eval-public` now runs the pinned, CC0 development smoke suite through
the public CLI subprocess seam, writes a canonical custody bundle, verifies it,
and reproduces it into a fresh destination with byte-identical benchmark,
trace, and metric artifacts.

## Integrity and Truth Boundaries

- The fixture is pinned to the real immutable commit `1f4d6a4` and a canonical
  SHA-256 digest.
- Registry metadata is the verifier trust anchor; jointly changing bundle data,
  its embedded digest, and its internal manifest no longer passes.
- Benchmark-owned question IDs, gold references, corpus IDs, metric family,
  metric label, Wilson interval, and recomputed result must match every trace.
- Adapter dispatch is explicit and allowlisted.
- Reproduction removes incomplete output on any failure and rejects canonical
  drift.
- The smoke suite permanently records `publishable=false`,
  `pbpp_headline_eligible=false`, and
  `independent_external_reproduction=false`.

## Verification

- Public/governance focused suite: 18 passed.
- CLI create -> verify -> reproduce -> verify passed with byte-identical core
  artifacts.
- Full repository suite: 1,881 passed, 139 skipped, 191 deselected.
- Ruff and `git diff --check` passed.
- Independent implementation review: 99/100 before the final cleanup edge;
  the remaining destination-cleanup edge was then closed and regression-tested.

