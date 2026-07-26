# Goal: Phase 16 L2 Metric-Family Taxonomy

## Objective

Implement P16-L2-E, the next dependency-ready package after the merged signed
publication gate: extend the validated leaderboard result contract from the
existing retrieval and judged-QA families to the six distinct LEAD-002
dimensions.

This package changes only the result taxonomy. It does not render a new table,
run a benchmark, publish externally, access production, or satisfy Phase 12
evidence, Phase 15 hardware, Register A, reproduction, or launch gates.

## Controlling Sources

- `.planning/STATE.md`
- `.planning/ROADMAP.md`
- `.planning/REQUIREMENTS.md`
- `docs/EXECUTION-PLAN-B-Benchmark-and-Leaderboard.md`
- `docs/governance/CREDIBILITY-MODEL.md`
- `docs/CODEX-HANDOFF-EXECUTION-PROMPT.md`
- `docs/plans/2026-07-25-phase16-result-contract.md`
- `docs/plans/2026-07-26-phase16-signed-publication.md`
- `docs/plans/2026-07-26-phase16-metric-taxonomy.md`

## Exact Lease

- `GOAL.md`
- `leaderboard/validate.py`
- `leaderboard/schema/result-v1.schema.json`
- `tests/test_leaderboard_result_contract.py`
- `docs/plans/2026-07-26-phase16-metric-taxonomy.md`

No other file may change.

## Acceptance Contract

- The result validator accepts exactly these metric families:
  `retrieval`, `judged_qa`, `security`, `calibration`, `performance`, and
  `reproducibility`.
- The existing invariant that one result record contains one metric family is
  preserved.
- Existing judged-QA judge-disclosure validation remains unchanged; adding a
  family does not weaken numeric, confidence-interval, publication, digest, or
  history validation.
- Unknown families and mixed-family records continue to fail closed with stable
  JSON-pointer errors.
- Focused RED regressions precede the minimum shared validator change.
- Focused tests, the full repository suite with the MCP dependency surface,
  full Ruff, diff, exact-lease, secret, and risky-file checks pass.
- Native comprehensive and critical/major review stages clear before delivery.
- Normal branch push, PR, exact-head CI/review, merge, and post-merge main CI
  complete without bypass or dismissal.

## Operating Contract

- Native RalphEx only. Plan, task, review, and monitoring use
  `gpt-5.6-sol:low`; executor is Codex; external review is `none`.
- Hermes and legacy automation remain off and unbound.
- Work only in the Worktrunk checkout
  `/Users/admin/Mnemosyne.codex-phase16-metric-taxonomy` on
  `codex/phase16-metric-taxonomy`.
- Ponytail governs implementation. Apply relevant Superpowers TDD, receiving
  review, debugging, and verification checkpoints and existing GSD state.
- Use CBM first for code discovery, context-mode for retained captures, and
  Gbrain only for coherent committed or merged milestones. Add an ADR only for
  a durable architectural decision.
- Use normal GitHub branch, PR, exact-head CI/review, merge, and post-merge CI.
  Never direct-push main, force-push, bypass hooks/checks, dismiss reviews,
  fabricate evidence, run protected production work, or widen the lease.
- Maximum 12 rounds. Preserve stall, rate-limit, failure, lease-overlap, dirty
  worktree, and merge-conflict guards.

## Tasks

### Task 1: Freeze the six-family contract with RED tests

- [x] Add focused tests for each newly admitted family and for preserved
  unknown/mixed-family rejection.
- [x] Verify the focused test fails against the current two-family validator.
- [x] Commit the RED contract.

### Task 2: Implement the minimum shared validator change

- [x] Extend the existing family allowlist without adding a dependency or a
  parallel validation path.
- [x] Make focused tests green without changing unrelated contracts.
- [x] Commit the implementation.

### Task 3: Review, verify, and deliver

- [x] Run both native review stages and repair only confirmed findings with RED
  regressions for logic defects.
- [x] Run focused tests, full pytest with the MCP extra, full Ruff, diff, lease,
  secret, and risky-file checks.
- [ ] Commit explicit leased paths, push normally, and open or update the PR.
- [ ] Require fresh exact-head CI and both reviewers to clear before normal
  merge; verify post-merge main CI.

### Remaining gates

- Branch push, PR, exact-head CI/review, merge, and post-merge main CI remain
  blocked by unavailable GitHub authentication/network access.
- Completion still requires the CBM refresh, Gbrain sync, and admission of the
  next dependency-ready package listed below.

## Completion

Finish only after normal merge, green post-merge main CI, one CBM refresh, one
Gbrain sync, and admission of the next dependency-ready lease-disjoint package.
