# Plan: Reconcile to main@2091d01c, Deliver the Stranded r42 Record, and Close the Carve-Out at T6

## Overview

You are the executor for round 43 of an autonomous GoalEx loop on the Mnemosyne
repository. You have no memory of prior rounds; everything you need is below.

**Runtime contract**
- Controller worktree: `/Users/admin/.codex/worktrees/9697/Mnemosyne`
- Controller branch: `codex/goalex-whole-memory-pilot`
- Never write directly to `main`. Never force-push. Never bypass hooks.
- Every delivery goes through a normal PR with review, exact-head CI, merge,
  and exact post-merge `main` CI proof.

**Verified current state (already checked this round — do not re-derive):**
- Controller worktree is clean; `main` == `origin/main` == `2091d01c8cea22da49a50bb1f0859d8108102f29`.
- PR #94 ("feat: deliver T5 lifecycle contract", head
  `41b213053dc0084678248e808f68cf61c0ae73c2`) merged at `main@2091d01c` on
  2026-08-02. **Exact-head CI run `30730185494` (all checks SUCCESS);
  post-merge `main` CI run `30730918452` (success).** Use these receipts
  verbatim — do not invent others.
- PR #94 landed the `T5` scope *except* one item: the round-42 record
  `docs/plans/goalex-r42-admit-node-t5-discharge-the-pr-93-carve-.md` exists
  only on the controller branch and is **not** on `main`.
- The controller branch is **behind** `main`: `main` carries a hardened
  `tests/test_planning_traceability.py` (extra
  `test_unit_drift_checkout_fetches_canonical_main_history`, an
  `origin/main` ancestry assertion, and
  `test_stale_alternate_canonical_baseline_claim_fails`) plus
  `.github/workflows/ci.yml` with `fetch-depth: 0` on the `test` job checkout.
  The branch must take `main`'s version of both files wholesale.
- All three lifecycle files still name `main@effc5e03` and still list `T5` as
  `DELIVERING`.
- **No source node is admissible.** `P13-C` (first real weekly `schedule`
  receipt, cron `23 7 * * 1`) is first eligible 2026-08-03; `N12` is lease
  blocked on the protected signed-publication paths; `SBOX` is quarantined;
  `P12-E`/`P13-O`/`P14-R` are operator/evidence blocked; `P16-L` needs human
  approval; `U-MODULES` lack exact plans. Do not admit or start any of them.

**The three lifecycle files (one owner, exact lease):**
- `GOAL.md`
- `.planning/STATE.md`
- `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`

**Contract tests you must keep green** (in `tests/test_planning_traceability.py`
as it exists on `main@2091d01c`):
- `test_canonical_baseline_is_identical_across_the_three_lifecycle_files` —
  the lease map must contain **exactly one** `Baseline: \`main@<40-hex>\`` line;
  `GOAL.md` must contain both `test "$(git rev-parse main)" = "<that 40-hex>"`
  and `git merge-base --is-ancestor <that 40-hex> main`; `GOAL.md` and
  `.planning/STATE.md` must each make at least one canonical-baseline claim and
  **every** such claim must name the matching 8-hex short SHA; every occurrence
  of the literal phrase `current canonical baseline` must be a recognized claim;
  `.planning/STATE.md` must have exactly one `stopped_at:` line and its
  `at \`main@<8-hex>\`;` claim must name the same short SHA; and the SHA must
  exist and be an ancestor of `refs/remotes/origin/main`.
- `test_lease_map_body_names_only_the_header_baseline` — every in-body
  current-baseline claim in the lease map must name the header baseline's short
  SHA.
- `test_unit_drift_checkout_fetches_canonical_main_history` — the `test:` job in
  `.github/workflows/ci.yml` must keep `with:` / `fetch-depth: 0` immediately
  after its `actions/checkout@9c091bb…` step.

Because those tests bind the three files together, **update all three in the
same commit**, using the new baseline `2091d01c8cea22da49a50bb1f0859d8108102f29`
(short `2091d01c`) everywhere.

**Rule 11 (round residue) — unconditional:** the round ends with the controller
worktree clean. `git status --porcelain --untracked-files=all` must be empty and
ignored paths must be byte-identical to their round-start state. Post-merge
receipts and the branch-resident recomputation are part of this round, not
afterthoughts — commit them on the controller branch as the final step.

## Validation Commands

- `cd /Users/admin/.codex/worktrees/9697/Mnemosyne && git status --porcelain --untracked-files=all`
- `git fetch --prune origin && git rev-parse main origin/main`
- `python -m pytest tests/test_planning_traceability.py -q`
- `python -m ruff check .`
- `gh pr checks <PR#> --watch`
- `gh run list --branch main --limit 3 --json databaseId,headSha,conclusion,event`
- The full `## Verification` block at the bottom of `GOAL.md`, run from the
  controller worktree on branch `codex/goalex-whole-memory-pilot`.

### Task 1: Refresh canonical main and bring the controller branch up to it
- [x] `cd /Users/admin/.codex/worktrees/9697/Mnemosyne`; confirm
      `git branch --show-current` is `codex/goalex-whole-memory-pilot` and
      `git status --porcelain --untracked-files=all` is empty. If it is not
      empty and the dirt is not yours, stop and park per rule 11 instead of
      cleaning it.
- [x] Record the start-of-round ignored-state baseline:
      `git status --porcelain --untracked-files=all --ignored` output saved
      outside the worktree (e.g. `/tmp/goalex-r43-ignored-baseline.txt`).
- [x] `git fetch --prune origin`; fast-forward local `main` to `origin/main`
      and assert both equal `2091d01c8cea22da49a50bb1f0859d8108102f29`.
- [x] Merge `main` into `codex/goalex-whole-memory-pilot` with a normal merge
      commit. For `tests/test_planning_traceability.py`,
      `.github/workflows/ci.yml`, `docs/plans/goalex-r40-*.md`, and
      `docs/plans/goalex-r41-*.md`, resolve by taking **main's** version exactly
      (`git checkout --theirs`-equivalent: the branch is behind, not ahead, on
      these). Keep `docs/plans/goalex-r42-admit-node-t5-discharge-the-pr-93-carve-.md`
      from the branch.
- [x] Verify the reconciliation: `git diff main HEAD --stat` must now list
      **only** `docs/plans/goalex-r42-admit-node-t5-discharge-the-pr-93-carve-.md`.
      If anything else appears, fix the merge resolution before continuing.
      The active r43 execution plan is also branch-resident by necessity; all
      main-owned reconciliation paths match `main` exactly.
- [x] Run `python -m pytest tests/test_planning_traceability.py -q` and confirm
      the current failure(s) are exactly the stale-baseline assertions (the files
      still say `effc5e03` while `origin/main` is `2091d01c`). Do not "fix" them
      yet — Task 2 does that.
      Observed 2026-08-01: all 12 tests pass because the contract currently
      requires the recorded baseline to be an ancestor of `origin/main`, not
      equal to it; Task 2 still owns the lifecycle-file recomputation.

### Task 2: Open an isolated delivery lane and recompute the three lifecycle files to main@2091d01c
- [ ] Create an isolated Worktrunk/worktree lane cut from `main@2091d01c` on a
      new branch (suggested name `codex/goalex-t6-post-pr94-lifecycle-delivery`).
      Do all Task 2 and Task 3 edits there, not in the controller worktree.
- [ ] In `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`:
      set `Baseline:` to `` `main@2091d01c8cea22da49a50bb1f0859d8108102f29` ``;
      bump `Updated:` to `2026-08-02`; add a `- PR #94:` entry to the
      **Merged baseline** list recording the `T5` delivery at `main@2091d01c`
      with exact-head CI `30730185494` and post-merge CI `30730918452`; and
      rewrite every in-body current-baseline claim so it names `main@2091d01c`.
- [ ] Flip the `T5` row to `MERGED` with its factual outcome: merged as PR #94
      at `main@2091d01c`, exact head `41b21305`, exact-head CI `30730185494`,
      post-merge CI `30730918452`; documentation and contract-test only; it
      admitted no source node. State plainly that its delivery **omitted the
      round-42 record from its own `docs/plans/` lease**, which is the
      non-receipt residue this round discharges.
- [ ] Add exactly one new row `T6` — status `DELIVERING` — with: prerequisites
      (verified canonical `main@2091d01c` plus PR #94's receipts, lane cut from
      `main@2091d01c`); produces (the three lifecycle files at
      `Baseline: main@2091d01c` with `T5` as `MERGED`, plus the r42 and r43
      round records); exact lease `GOAL.md`; `.planning/STATE.md`;
      `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`;
      `docs/plans/` — GoalEx owner only; and the explicit statement that `T6`
      admits **no source node** and **no successor node**.
- [ ] Update the **Topological waves** and **Concurrency and integration rules**
      sections: move PR #94 / `T5` into the completed wave, make `T6` the sole
      current writer, and rewrite the carve-out status paragraph to record that
      from `T6` onward **both** the one-block receipt lag *and* the current
      round's own plan record are an accepted standing condition of the
      controller branch that is discharged by branch-resident recomputation and
      **never** by admitting a successor node. Keep the existing statement that
      current safe coding concurrency is zero new implementation writers and
      that the next source admission waits on an external gate (`P13-C` first
      eligible 2026-08-03).
- [ ] In `GOAL.md`: add `git merge-base --is-ancestor 2091d01c8cea22da49a50bb1f0859d8108102f29 main`
      to the ancestry list in the `## Verification` block and change the pin line
      to `test "$(git rev-parse main)" = "2091d01c8cea22da49a50bb1f0859d8108102f29"`.
      Update the `## Authority`, `## Current Phase`, and `## Success Evidence`
      prose to record PR #94 as merged with its two run IDs, `T5` as discharged,
      and `T6` as the single bounded node now delivering. Ensure every occurrence
      of the phrase `current canonical baseline` names `main@2091d01c`.
- [ ] In `.planning/STATE.md`: update the single `stopped_at:` line so its
      `at \`main@2091d01c\`;` claim names the new baseline and its narrative
      cites PR #94 as merged with green post-merge CI, and update the
      `current canonical baseline is \`main@2091d01c\`` sentence with the PR #94
      exact-head and post-merge run IDs. Keep the Phase 12 operator-gate,
      Phase 14-15 dependency-gate, and Phase 16 launch-gate language intact —
      no admission state, benchmark, measurement, or publication claim changes.
- [ ] Run `python -m pytest tests/test_planning_traceability.py -q` and
      `python -m ruff check .` in the lane; both must pass before Task 3.

### Task 3: Deliver the stranded r42 record and the r43 record through a reviewed PR
- [ ] Copy `docs/plans/goalex-r42-admit-node-t5-discharge-the-pr-93-carve-.md`
      from the controller branch into the lane unchanged — it is a historical
      record of the round as planned, so do not rewrite its task boxes.
- [ ] Write this plan into the lane as
      `docs/plans/goalex-r43-reconcile-to-main-2091d01c-deliver-the-.md`
      (same format as the sibling `docs/plans/goalex-r*.md` files).
- [ ] Commit the whole Task 2 + Task 3 delta as one coherent set of commits with
      conventional-commit messages, push the lane branch normally, and open a PR
      against `main` describing it as documentation-only: it moves no benchmark,
      measurement, admission state, or publication claim, and admits no source
      node.
- [ ] Drive the PR to green: resolve every review thread and CI failure at the
      exact PR head. Self-repair routine transport/CI/lint issues; do not
      dismiss findings. Record the exact-head CI run ID.
- [ ] Merge the PR normally (no force-push, no direct write to `main`). Record
      the merge commit SHA. Then poll
      `gh run list --branch main --limit 3 --json databaseId,headSha,conclusion,event`
      until the `push` run whose `headSha` equals that merge commit reports
      `success`; record that post-merge run ID. Do not claim completion on a
      pending or failed run.

### Task 4: Reconcile the controller branch to the new main and end the round with zero residue
- [ ] Back in `/Users/admin/.codex/worktrees/9697/Mnemosyne`:
      `git fetch --prune origin`, fast-forward local `main` to `origin/main`,
      and assert `git rev-parse main` equals `git rev-parse origin/main` equals
      the Task 3 merge commit.
- [ ] Merge `main` into `codex/goalex-whole-memory-pilot`. Confirm
      `git diff main HEAD --stat` is now empty apart from what Task 4 is about
      to add.
- [ ] Apply the branch-resident recomputation for the accepted one-block lag —
      this is the step round 42 skipped and it is what leaves verification
      passing. In all three lifecycle files, set the baseline to the **new**
      merge commit SHA (the Task 3 merge commit, full 40-hex in the lease map
      `Baseline:` line and in `GOAL.md`'s pin and ancestry lines, short 8-hex in
      every prose claim and in `stopped_at:`), flip `T6` to `MERGED` with its PR
      number, exact-head CI run ID, and post-merge CI run ID, and record in the
      lease map that this recomputation is `T6`'s own standing-condition residue
      which admits no successor and no source node.
- [ ] Re-run `python -m pytest tests/test_planning_traceability.py -q` and
      `python -m ruff check .` on the controller branch; both must pass.
- [ ] Commit that recomputation on `codex/goalex-whole-memory-pilot` as the
      round's final commit.
- [ ] Run the full `## Verification` block from `GOAL.md` verbatim in the
      controller worktree and confirm it exits 0 — in particular
      `test -z "$(git status --porcelain)"` and the pin equality against the new
      `main`.
- [ ] Confirm zero residue: `git status --porcelain --untracked-files=all` is
      empty, and `git status --porcelain --untracked-files=all --ignored` matches
      the Task 1 baseline exactly. Delete the temporary baseline file you wrote
      outside the worktree. If any round-owned change cannot be committed,
      preserve it losslessly outside the worktree, restore the tracked paths to
      `HEAD`, remove only the untracked files this round created, and record the
      external path and blocker in a summary outside the controller worktree.
