# Plan: Admit Node T5 — Discharge the PR #93 Carve-Out Lapse and Land the Stranded Test Contract

## Overview

You are the executor for round 42 of an autonomous GoalEx loop on the Mnemosyne
repository. You have no memory of prior rounds; everything you need is below.

**Worktree:** `/Users/admin/.codex/worktrees/9697/Mnemosyne` (controller)
**Controller branch:** `codex/goalex-whole-memory-pilot`
**Canonical baseline:** `main@effc5e039505c09e575ca5e4aeb2b96949676366` (PR #93)
**Python:** use `.venv/bin/python` and `.venv/bin/ruff` (no global `python`).

### Governing rules (from `GOAL.md`)

- Never write directly to `main`, never force-push, never bypass hooks. All work
  lands through a normal PR with review, exact-head CI, merge, and exact
  post-merge `main` CI.
- The scheduling authority is `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`
  as it stands on current `main`, recomputed after every merge.
- Rule 11: the round must end with **no round-owned residue** in the controller
  worktree. Post-merge receipts and canonical-truth reconciliation are part of
  the round — commit them on the controller branch as the final step.
- Documentation/test-contract work must not change any benchmark, measurement,
  admission state, roadmap percentage, or publication claim. M12/M13 stay
  `PROPOSED` / `publishable:false` / `pbpp_headline_eligible:false`.

### What is already true

- Controller branch is clean and one commit ahead of `main` (`047bb1a5`).
- `main` has fully merged into the branch (`643ac865`); no `main` commit is
  absent from the branch.
- Every remaining *source* package in the lease map is dependency-, lease-,
  evidence-, or spec-blocked (`N12` needs the protected signed-publication lease
  released; `P12-E` is operator-gated; `P13-C`'s first real cron event is
  2026-08-03; `SBOX` and `U-MODULES` are quarantined). So no source node is
  admissible — this documentation/test delivery is the highest-value available
  work, not housekeeping displacing product work.

### The exact stranded delta (controller branch vs `main`)

```
.planning/STATE.md                                     (modified)
GOAL.md                                                (modified)
docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md (modified)
docs/plans/goalex-r39-...md -> docs/plans/completed/goalex-r39-...md (renamed)
docs/plans/goalex-r40-adjudicate-land-and-reconcile-the-rule-1.md    (new)
docs/plans/goalex-r41-cut-rule-11-back-to-its-minimal-invarian.md    (new)
tests/test_planning_traceability.py                    (+77 lines, never merged)
```

The +77 lines add `test_canonical_baseline_is_identical_across_the_three_lifecycle_files`,
which pins the lease map's single `Baseline:` line against GOAL.md's and
STATE.md's canonical-baseline claims. It has been branch-resident since round 39
and protects nothing on `main`.

### The defect this round fixes

`047bb1a5` recomputed the map header to `Baseline: main@effc5e03...` and added a
PR #93 merged-baseline bullet, but left the body claiming a different baseline:

- line ~59: "This map is recomputed from the new baseline `main@39cfa67a`"
- line ~172: "T4 ... merged as PR #92 at main@39cfa67a (current baseline)"
- lines ~178, ~223-224: "This map has now been recomputed from the resulting
  main@39cfa67a"; "This revision is the recomputation from `main@39cfa67a`"
- `GOAL.md` Authority: "That residue is this update: `main@39cfa67a`'s copies
  ... The recomputation to `Baseline: main@39cfa67a` ... exists only on the
  controller branch" — describes a residue that PR #93 superseded.
- `GOAL.md` Success Evidence list ends at PR #92; no PR #93 entry.
- `.planning/STATE.md` lines ~80, ~87 carry the same superseded framing.

The existing pinning test cannot catch any of this: it only reads the single
`Baseline:` header line.

### The adjudication to record

`T4`'s "admits no successor node" clause is about a *self-regenerating* one-block
receipt residue. PR #93 was an independent merge from a separate lane
(`codex/goalmd-round-ends-clean`, touching `GOAL.md` and
`tests/test_planning_traceability.py`), so the carve-out's explicit lapse rule
fired. Post-lapse the residue is not receipt-only — it contains an undelivered
test contract and three undelivered round records. Admit exactly one node, `T5`,
to discharge it. This terminates: the trigger is an external merge, not the
residue regenerating itself.

## Validation Commands

- `.venv/bin/python -m pytest tests/test_planning_traceability.py -q`
- `.venv/bin/ruff check tests/test_planning_traceability.py`
- `.venv/bin/ruff format --check tests/test_planning_traceability.py`
- Full GOAL.md verification block (run on the controller branch):
```bash
set -euo pipefail
test "$(pwd -P)" = "/Users/admin/.codex/worktrees/9697/Mnemosyne"
test "$(git branch --show-current)" = "codex/goalex-whole-memory-pilot"
test -z "$(git status --porcelain)"
git fetch --prune origin
test "$(git rev-parse main)" = "$(git rev-parse origin/main)"
git merge-base --is-ancestor effc5e039505c09e575ca5e4aeb2b96949676366 main
```
- `git status --porcelain --untracked-files=all` (must be empty at round end)

### Task 1: Extend the pinning test so a partial map recomputation fails

- [ ] Read `tests/test_planning_traceability.py`, especially the existing
      `test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
      and its `LEASE_BASELINE` / `CANONICAL_CLAIMS` regexes.
- [ ] Add a new test (e.g. `test_lease_map_body_names_only_the_header_baseline`)
      that parses the map's single `Baseline: \`main@<40hex>\`` header line and
      then asserts that every in-body *current-baseline* claim names that same
      SHA prefix. Cover at minimum these claim shapes, matched against
      whitespace-normalized text: "recomputed from the new baseline
      `main@X`", "(current baseline)" in the waves block, and "This revision
      **is** the recomputation from ... `main@X`".
- [ ] Make the test fail-closed: if none of the recognized claim shapes is
      found, the test must fail with a clear message rather than pass vacuously
      (mirror the existing `CANONICAL_CLAIM_PHRASE` count guard).
- [ ] Verify the new test **fails** against the current branch content first
      (it should, because line 59 says `39cfa67a` while the header says
      `effc5e03`), then keep it red until Task 2 makes it green.
- [ ] Do not weaken or delete the existing pinning test.

### Task 2: Fully recompute the three lifecycle files to `main@effc5e03`

- [ ] In `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`:
      rewrite every stale in-body baseline claim (lines ~59, ~172, ~178,
      ~223-224 and any other hit of `39cfa67a` framed as current) so the file
      consistently states it is recomputed from `main@effc5e03` and records
      PR #93's receipt block (`main@effc5e03`, exact-head CI `30718912376`,
      post-merge CI `30719645207`). Keep historical statements about what
      `main@39cfa67a` *held* only where they are explicitly past-tense and
      correct.
- [ ] Add a `T5` row to the **Remaining package DAG** with class `DELIVERING`,
      prerequisites (verified canonical `main@effc5e03` and PR #93's post-merge
      receipts; lane cut from `main@effc5e03`), produces (the three lifecycle
      files at `Baseline: main@effc5e03`, the pinning tests, and the r39/r40/r41
      round records on `main`), exact lease (`GOAL.md`; `.planning/STATE.md`;
      this map; `docs/plans/`; `tests/test_planning_traceability.py`, GoalEx
      owner only), and the gate note that it admits **no source node**.
- [ ] Update the **Topological waves** and **Concurrency and integration rules**
      sections: record that PR #93's merge lapsed the carve-out, that the
      residue at that point was no longer receipt-only (an undelivered test
      contract plus three undelivered round records), and that exactly one node
      `T5` is admitted to discharge it. State plainly why this terminates.
- [ ] In `GOAL.md`: rewrite the Authority carve-out paragraph to the post-PR-#93
      truth and state that **this PR is the `T5` delivery**; add PR #93 and the
      `T5` delivery to the Current Phase narrative; add a PR #93 entry to the
      **Success Evidence** merged-receipts list. Leave the Verification block's
      `effc5e03` pin and ancestry line as they are for now (Task 5 updates them
      post-merge).
- [ ] In `.planning/STATE.md`: fix lines ~80 and ~87 and the "Latest checkpoint"
      paragraph so every canonical-baseline claim names `main@effc5e03`; keep
      `stopped_at` naming `main@effc5e03` exactly once.
- [ ] Change no benchmark, measurement, admission state, roadmap percentage, or
      publication claim. Touch no `eval/`, `leaderboard/`, `src/`, or
      `.github/workflows/` path.
- [ ] Run all four validation commands; both pinning tests must now pass.
- [ ] Commit on the controller branch.

### Task 3: Deliver `T5` through an isolated reviewed PR

- [ ] Create an isolated worktree lane branched from `main@effc5e03` (e.g.
      `codex/goalex-t5-carveout-lapse-delivery`). Do not work in the controller
      worktree for the PR itself.
- [ ] Apply exactly the stranded delta into that lane: the three reconciled
      lifecycle files, `tests/test_planning_traceability.py` (both pinning
      tests), the r39 move into `docs/plans/completed/`, and the new
      `docs/plans/goalex-r40-*.md` and `docs/plans/goalex-r41-*.md` records.
      Nothing else — verify with `git diff --stat main` that no path outside the
      declared `T5` lease appears.
- [ ] Run the full authoritative test suite once on the stable exact PR head,
      plus `ruff check` and `ruff format --check`.
- [ ] Push normally (never force), open the PR describing it as
      documentation-and-test-contract only, request review, and clear every
      review thread and mergeability check.
- [ ] Confirm exact-head CI is green on the PR head SHA, then merge.
- [ ] Record the merge SHA, exact-head CI run id, and post-merge `main` CI run
      id; confirm the post-merge `main` CI run on the exact merge commit passes.

### Task 4: Fast-forward and prove canonical `main`

- [ ] In the controller worktree: `git fetch --prune origin`, fast-forward local
      `main`, and prove `git rev-parse main` equals `git rev-parse origin/main`.
- [ ] Merge the new `origin/main` into the controller branch (normal merge, no
      rebase, no force) so no `main` commit is absent from the branch.
- [ ] Confirm the delivered content is on `main`: the two pinning tests exist in
      `main:tests/test_planning_traceability.py`, and
      `docs/plans/completed/goalex-r39-*.md`, `docs/plans/goalex-r40-*.md`, and
      `docs/plans/goalex-r41-*.md` all resolve under `main:`.

### Task 5: Reconcile the one-block receipt residue and end clean

- [ ] Recompute the lease map from the new `main`: set the `Baseline:` header
      and every in-body current-baseline claim to the new merge SHA, mark `T5`
      as `MERGED`, and record `T5`'s receipt block (PR number, merge SHA,
      exact-head CI id, post-merge CI id). State that this recomputation is
      `T5`'s own accepted one-block receipt residue, which admits no successor
      node and no source node.
- [ ] Update `GOAL.md` to match: Authority paragraph, Current Phase, Success
      Evidence entry for the `T5` PR, and the Verification block — replace the
      `test "$(git rev-parse main)" = "effc5e03..."` pin with the new full merge
      SHA and add a `git merge-base --is-ancestor <new SHA> main` line.
- [ ] Update `.planning/STATE.md` (`stopped_at`, `last_updated`, and the
      canonical-baseline claims) to the new SHA.
- [ ] Write the round-42 record under `docs/plans/` describing the carve-out
      lapse adjudication and the `T5` delivery, and move any completed round
      plan into `docs/plans/completed/` per existing convention.
- [ ] Re-run all four validation commands; both pinning tests must pass against
      the new SHA.
- [ ] Commit everything on the controller branch as the round's final step, then
      confirm `git status --porcelain --untracked-files=all` is empty so the
      launcher's next preflight finds a clean tree.
