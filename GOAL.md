# Goal: Phase 16 L4 Launch-Readiness Gate

## Objective

Implement P16-L4-A, the next dependency-ready production-code package after the
merged metric-family taxonomy: a deterministic, fail-closed launch-readiness
validator for the existing LEAD-003 gates.

This package codifies evidence admission only. It must not run benchmarks,
publish externally, access production, fabricate gate evidence, satisfy the
protected Phase 12 attempt, or claim Phase 15 hardware proof.

## Controlling Sources

- `.planning/ROADMAP.md`
- `.planning/STATE.md`
- `.planning/REQUIREMENTS.md`
- `docs/EXECUTION-PLAN-B-Benchmark-and-Leaderboard.md` §2
- `docs/governance/BOARD-STATUS.md`
- `docs/plans/2026-07-25-phase16-result-contract.md`
- `docs/plans/2026-07-25-phase16-run-ledger.md`
- `docs/plans/2026-07-26-phase16-static-renderer.md`
- `docs/plans/2026-07-26-phase16-signed-publication.md`
- `docs/plans/2026-07-26-phase16-metric-taxonomy.md`

## Exact Lease

- `GOAL.md`
- `leaderboard/readiness.py`
- `tests/test_leaderboard_readiness.py`
- `docs/plans/2026-07-26-phase16-launch-readiness.md`

No other tracked path may change. `GOAL.md` and the round plan may update their
own task and verification state. RalphEx must not archive or rename `GOAL.md`
before GitHub delivery and post-merge verification are complete.

## Acceptance Contract

- Accept one canonical JSON readiness record containing explicit PBPP,
  Part-I-results, Register-A, identical-treatment, and operator-entry-label
  evidence.
- Return ready only when every gate is explicitly satisfied and each evidence
  reference is a non-empty string.
- Fail closed for missing, false, non-boolean, unknown, malformed, or duplicate
  fields; never infer readiness from filenames, environment, network, or prior
  runs.
- Require the Mnemosyne entrant label to be exactly `operator-entry`.
- Emit deterministic, sorted JSON with the readiness boolean and blocked gate
  names; no timestamps, host data, secrets, or mutable external state.
- Provide a small module CLI that reads one UTF-8 JSON file, returns 0 when
  ready, 1 when valid-but-blocked, and 2 for invalid input.
- Focused tests cover ready, each blocked gate, missing/unknown/mistyped fields,
  empty evidence, operator-label mismatch, malformed/duplicate-key JSON, and
  deterministic output.

## Operating Contract

- Native RalphEx only: plan/task/review/monitor use `gpt-5.6-sol:low`,
  executor Codex, external review none, maximum 12 rounds.
- Work only in `/Users/admin/Mnemosyne.codex-phase16-launch-readiness` on
  `codex/phase16-launch-readiness`.
- Hermes dispatch remains 0; no Hermes fleet or legacy automation may bind.
- Use CBM first for code reasoning, Gbrain for durable project knowledge, and
  context-mode for command/log/document captures.
- Apply Ponytail universally. Reuse stdlib JSON and existing validation/CLI
  patterns; add no dependency or speculative abstraction.
- Follow RED -> GREEN -> REFACTOR for behavior changes, then native review,
  focused tests, unrestricted MCP-extra full pytest, Ruff, diff, lease,
  secret, and risky-file checks.
- Deliver only through branch push, PR, exact-head CI and review, normal merge,
  and post-merge main verification. No direct-main, force, hook/check bypass,
  review dismissal, or fabricated evidence.
- Reconcile code, GitHub, canonical docs, planning state, CBM, and Gbrain only
  when evidence changes. ADRs are only for durable architectural decisions.

## Tasks

### Task 1: Freeze the launch-readiness contract

- [x] Add focused RED tests for canonical ready/blocked/invalid behavior and
  deterministic CLI output.
- [x] Commit the RED contract.

### Task 2: Implement the minimum shared gate

- [x] Add the stdlib-only validator and CLI in the leased module.
- [x] Make focused tests green without reading protected or external state.
- [x] Commit the implementation.

### Task 3: Review, verify, and deliver

- [ ] Run both native review stages and repair confirmed findings with focused
  regressions (the first review produced the current uncommitted repairs; the
  follow-up critical/major review remains).
- [x] Run focused tests, unrestricted full pytest with the MCP extra, full
  Ruff, diff, exact-lease, secret, and risky-file checks.
- [ ] Commit explicit leased paths, push normally, and open/update the PR
  (the pre-review branch is already pushed).
- [ ] Require fresh exact-head CI and both reviewers to clear before normal
  merge; verify post-merge main CI.

### Remaining gates

- Run the follow-up critical/major native review.
- Commit and push the review fixes, then open or update the PR.
- Require exact-head CI and both reviewers, merge normally, and verify
  post-merge main CI.

## Completion

Finish only after normal merge, green post-merge main CI, one CBM refresh, one
Gbrain sync, and admission of the next dependency-ready lease-disjoint package.
