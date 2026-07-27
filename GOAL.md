# Goal: Phase 13 BEAM Reader and Judge Configuration Contract

## Objective

Implement `P13-BEAM-B`, the next dependency-ready BENCH-006 source package:
extend the existing BEAM disclosure adapter with a deterministic, fail-closed
reader-and-judge configuration contract that reuses the public harness QA
metadata conventions.

This package prepares production source only. It must not download or run BEAM,
invoke a reader or judge, invent measurements, publish a claim, access protected
Phase 12 production evidence, or perform Phase 15 hardware proof.

## Verified Baseline

`main@2834834a` includes the merged P13-BEAM-A disclosure envelope. Exact
post-merge main CI run `30232339515` succeeded. CBM was refreshed to 21,074
nodes and 96,260 edges, and Gbrain source `mnemosyne-code` synced this milestone
once.

## Controlling Sources

- `.planning/ROADMAP.md` — Phase 13
- `.planning/REQUIREMENTS.md` — BENCH-006 and RAIL-001..004
- `.planning/STATE.md`
- `docs/EXECUTION-PLAN-B-Benchmark-and-Leaderboard.md` — M1.5 and PBPP
- `docs/superpowers/plans/2026-07-15-W4-neutral-adapter-suite-plan.md` — Phase 3
- `eval/public/runner.py` and existing QA bundle metadata conventions

## Exact Lease

- `GOAL.md`
- `eval/public/adapters/beam.py`
- `tests/test_public_beam.py`
- `docs/plans/2026-07-26-phase13-beam-adapter.md`

No other tracked path may change. `GOAL.md` and the round plan may update their
own task and verification state.

## Acceptance Contract

- Reuse the existing public QA reader/judge/config metadata conventions; do not
  invent a parallel bundle schema or duplicate shared validation.
- Bind a fully disclosed reader model/config, judge model/prompt, and exact
  content digests into one deterministic source-only BEAM contract.
- Reject missing, extra, ambiguous, boolean, non-finite, unpinned, or
  non-canonical metadata through the existing BEAM-specific error boundary.
- Detach all returned nested values and canonicalize nested mapping order.
- Require no filesystem, network, dataset, model, judge, CLI, production, or
  hardware access.
- Add focused RED tests first, observe the intended failures, then implement the
  smallest standard-library/shared-flow change.
- Run native all-Sol-low review, focused tests, unrestricted MCP-extra full
  pytest, full Ruff, diff, exact-lease, risky-file, and secret checks.
- Use the normal branch → PR → exact-head CI/reviews → normal merge flow.

## Operating Contract

- Native RalphEx only: plan/task/review `gpt-5.6-sol:low`, Codex executor,
  external review none, workspace-write, at most 12 iterations.
- Work only in this Worktrunk checkout and exact lease.
- Hermes dispatch remains zero; no fleet or legacy automation binding.
- Apply Ponytail, TDD, receiving-review, systematic-debugging, and
  verification-before-completion where triggered.
- Use CBM first for code structure, context-mode for large output, and Gbrain
  only after a coherent merged milestone.
- Never direct-push main, force-push, bypass hooks/checks, dismiss reviews,
  fabricate evidence, or run protected production/hardware gates.

## Tasks

### Task 1: Freeze the source-only configuration behavior

- [x] Inspect the existing QA reader/judge/config shared conventions and record
  the smallest reusable interface in the round plan.
- [x] Add focused RED tests for canonical valid metadata and fail-closed inputs.
- [x] Commit only the RED contract and accurate task receipt. The supervisor
  repaired the linked-worktree Git metadata boundary after 13 expected
  missing-feature failures, 23 existing passing tests, and clean focused Ruff.

### Task 2: Implement the minimum shared-flow extension

- [x] Add the smallest dependency-free BEAM reader/judge configuration builder.
- [x] Make focused tests green without I/O or execution.
- [x] Commit only the implementation and accurate task receipt. Focused
  verification passed 36 tests and clean Ruff without dataset, model, judge,
  filesystem, or network execution.

### Task 3: Review and deliver

- [x] Complete native review and repair only reproduced in-lease findings.
  Five independent passes found and repaired mutable model pins, nested boolean
  metadata, direct validation coverage gaps, and stale task documentation.
- [ ] Complete authoritative local verification and safety gates. Focused
  pytest passes 52 tests and full Ruff passes. Unrestricted full pytest remains
  blocked by the workspace sandbox denying `/bin/ps`; the sandboxed remainder
  also reports unrelated production/runtime test failures.
- [ ] Push, open/update the PR, clear exact-head CI and both reviewers, and
  merge normally.
- [ ] Verify exact post-merge main CI, then refresh CBM/Gbrain once.

## Completion

Finish only after normal merge and exact post-merge main CI. This package does
not complete BENCH-006; BEAM execution, measured results, and publication remain
separate protected work.
