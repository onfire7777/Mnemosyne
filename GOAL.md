# Goal: Phase 16 L2 Signed Publication Gate

## Objective

Implement P16-L2-D, the first dependency-ready package after the merged result
contract, signed run ledger, and static renderer: a fail-closed publication
entrypoint that renders only active successful results from a verified signed
ledger.

This package advances LEAD-002's signed-data pipeline. It does not run a
benchmark, access production, publish externally, or satisfy Phase 12 evidence,
Phase 15 hardware, governance, reproduction, or launch gates.

## Controlling Sources

- `.planning/STATE.md`
- `.planning/ROADMAP.md`
- `.planning/REQUIREMENTS.md`
- `docs/EXECUTION-PLAN-B-Benchmark-and-Leaderboard.md`
- `docs/governance/CREDIBILITY-MODEL.md`
- `docs/CODEX-HANDOFF-EXECUTION-PROMPT.md`
- `docs/plans/2026-07-25-phase16-result-contract.md`
- `docs/plans/2026-07-25-phase16-run-ledger.md`
- `docs/plans/2026-07-26-phase16-static-renderer.md`
- `docs/plans/2026-07-26-phase16-signed-publication.md`

## Exact Lease

- `GOAL.md`
- `leaderboard/publish.py`
- `tests/test_leaderboard_publish.py`
- `docs/plans/2026-07-26-phase16-signed-publication.md`

No other file may change.

## Acceptance Contract

1. Reuse `leaderboard.ledger.verify_ledger` and
   `leaderboard.render.render_site`; add no dependency or second schema.
2. Accept a signed ledger, its public key, existing public trace JSONL, and a
   destination directory.
3. Fail closed before publication if ledger verification fails.
4. Select only successful ledger entries that remain active after
   supersession; reject duplicate active result records and a verified ledger
   with no active successful result.
5. Render the embedded result records through the existing atomic renderer.
6. Never treat failed, aborted, discarded, recorded-absence, pending, or
   superseded outcomes as publishable results.
7. Provide a deterministic CLI with concise errors and no traceback for
   expected invalid input.
8. Prove the contract with focused RED/GREEN tests, then run the full repository
   suite with the declared MCP extra, full Ruff, diff/lease, secret, and risky
   file checks.

## Operating Contract

- Native RalphEx only. Plan, task, review, and monitoring use
  `gpt-5.6-sol:low`; executor is Codex; external review is `none`.
- Hermes and legacy automation remain off and unbound.
- Work only in the Worktrunk checkout
  `/Users/admin/Mnemosyne.codex-phase16-signed-publication` on
  `codex/phase16-signed-publication`.
- Ponytail governs implementation. Apply relevant Superpowers TDD, review,
  debugging, and verification checkpoints and existing GSD state.
- Use CBM first for code discovery, context-mode for retained captures, and
  Gbrain only for coherent committed or merged milestones. Add an ADR only for
  a durable architecture decision.
- Use normal GitHub branch, PR, exact-head CI/review, merge, and post-merge CI.
  Never direct-push main, force-push, bypass hooks/checks, dismiss reviews,
  fabricate evidence, run protected production work, or widen the lease.
- Maximum 12 rounds. Preserve stall, rate-limit, failure, lease-overlap, dirty
  worktree, and merge-conflict guards.

## Tasks

### Task 1: Freeze the signed-publication contract with RED tests

- [x] Add focused tests proving ledger verification, active-success selection,
  supersession behavior, fail-closed invalid input, and CLI behavior.
- [x] Verify the focused test fails because `leaderboard.publish` is absent.
- [x] Commit the RED contract.

### Task 2: Implement the minimum publication entrypoint

- [x] Add `leaderboard/publish.py` by composing the existing verifier and
  renderer.
- [x] Make focused tests green without changing existing contracts.
- [x] Commit the implementation.

### Task 3: Review, verify, and deliver

- [x] Run both native review stages and repair only confirmed findings with RED
  regressions for logic defects.
- [x] Run focused tests, full pytest with the MCP extra, full Ruff, diff, lease,
  secret, and risky-file checks.
- [x] Commit explicit leased paths, push normally, and open or update the PR.
- [x] Require fresh exact-head CI and both reviewers to clear before normal
  merge; verify post-merge main CI.

## Completion

Finish only after normal merge, green post-merge main CI, one CBM refresh, one
Gbrain sync, and admission of the next dependency-ready lease-disjoint package.
