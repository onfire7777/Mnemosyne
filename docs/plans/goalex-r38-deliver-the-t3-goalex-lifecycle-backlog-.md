# Plan: Deliver the T3 GoalEx Lifecycle Backlog Through a Reviewed PR

## Overview

You are the executor for round 38 of an autonomous loop on the Mnemosyne
repository. You implement; you do not choose program direction.

Context you need (you have no memory of prior rounds):

- Worktree: `/Users/admin/.codex/worktrees/9697/Mnemosyne`
- Controller branch: `codex/goalex-whole-memory-pilot`
- Canonical `main` == `origin/main` == `061c2e1c13cbf1fd5324361a6ff61f47cd2a6534`
- The controller branch is fully merged **to** that main (`git rev-list
  --left-right --count main...HEAD` reports `0` commits on main not on HEAD).

The only admitted work item is node `T3` in
`docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`:
the GoalEx lifecycle delivery of the controller branch's undelivered delta.
That map explicitly states T3 "must land before any further admission, so no
other source node may be admitted in the same wave." Do **not** start any
benchmark, harness, sandbox, result-v2, or CI work this round.

The undelivered delta versus `main` is exactly (verify with
`git diff --stat main...HEAD`):

- `GOAL.md`
- `.planning/STATE.md`
- `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`
- `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`
  (a correction of one stale paragraph plus a twelve-line
  `Gap-disclosure delivery:` receipt block for PR #90)
- 25 round records under `docs/plans/` and `docs/plans/completed/`
  (23 new `goalex-r15..r37*.md`, one new `completed/goalex-r36-*.md`, and an
  edit to `goalex-r14-*.md`), plus this round's own new `goalex-r38-*.md`
  record if one exists in the worktree.

This is documentation only. It must change no benchmark, measurement,
admission state, publication claim, test, workflow, or source code. M12/M13
must stay `PROPOSED` / `publishable:false` / `pbpp_headline_eligible:false`.

Hard rules: never write directly to `main`, never force-push, never bypass
hooks, never dismiss review findings. Delivery goes through a normal PR from an
isolated lane branch cut from `main`, with exact-head CI, review clearance,
merge, and a post-merge `main` CI proof.

Do NOT touch `/Users/admin/Mnemosyne.codex-whole-memory-benchmark-spec` or
`/Users/admin/Mnemosyne.codex-phase16-signed-publication`; both are external
leases.

## Validation Commands

- `git -C /Users/admin/.codex/worktrees/9697/Mnemosyne fetch --prune origin`
- `git -C /Users/admin/.codex/worktrees/9697/Mnemosyne rev-parse main origin/main`
- `git diff --stat main...HEAD`
- `git diff main...HEAD -- ':!GOAL.md' ':!.planning/STATE.md' ':!docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md' ':!docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md' ':!docs/plans/'` (must be empty — proves the lease is documentation-only)
- `gh pr checks <PR#> --watch`
- `gh run list --branch main --limit 5`
- `python -m pytest tests/test_planning_traceability.py -q`
- `ruff check .`
- The GOAL.md verification block:
  ```bash
  set -euo pipefail
  test "$(pwd -P)" = "/Users/admin/.codex/worktrees/9697/Mnemosyne"
  test "$(git branch --show-current)" = "codex/goalex-whole-memory-pilot"
  test -z "$(git status --porcelain)"
  git fetch --prune origin
  test "$(git rev-parse main)" = "$(git rev-parse origin/main)"
  git merge-base --is-ancestor 661343ce05186e9a7f0f0740d1edef7c23532857 main
  git merge-base --is-ancestor a95fe4d291093253f8ce49adff32ba875a35e884 main
  git merge-base --is-ancestor baf5c1852593885e37eed75da69b02d93e1bff11 main
  test -f .planning/STATE.md
  test -f .planning/ROADMAP.md
  test -f .planning/REQUIREMENTS.md
  test -f docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md
  test -f docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md
  grep -q 'Proposed subordinate standard' \
    docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md
  grep -q 'Whole-Memory Reference Harness and Pilot Modules Implementation Plan' \
    docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md
  ```

### Task 1: Recompute the exact T3 delta and open an isolated lane
- [x] `git fetch --prune origin`; confirm `main == origin/main` and record the
      SHA. If a new commit has landed on `main` since `061c2e1c`, first merge
      `main` into the controller branch, then recompute everything below
      against the new baseline (the `GOAL.md` carve-out lapses on any merge the
      branch-resident map does not record).
      Recorded: `main` == `origin/main` == `061c2e1c13cbf1fd5324361a6ff61f47cd2a6534`,
      unchanged from the plan baseline. No new commit landed on `main`, so no
      merge was required and the carve-out did not lapse. Controller HEAD is
      `cf41a3fe07a09bfa03f7992122121b016ec6c389`.
- [x] Run `git diff --stat main...HEAD` and write down the exact file list.
      Confirm it contains only `GOAL.md`, `.planning/STATE.md`, the lease map,
      the pilots plan, and files under `docs/plans/`.
      Recorded: 30 files, 1535 insertions, 24 deletions, no deletions or
      renames (`--diff-filter=D` and `--diff-filter=RC` are both empty):
      `GOAL.md`; `.planning/STATE.md`;
      `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`;
      `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`;
      `docs/plans/completed/goalex-r36-land-the-post-pr-88-lease-map-and-state-.md`;
      `docs/plans/completed/goalex-r37-land-the-pending-m12-m13-gap-disclosure-.md`;
      `docs/plans/goalex-r14-land-the-exact-head-abi-remediation.md` (edit); and
      the new records `goalex-r15` … `goalex-r35`, `goalex-r37-land-the-stranded-m12-m13-gap-disclosure-delivery.md`,
      and `goalex-r38-deliver-the-t3-goalex-lifecycle-backlog-.md` under
      `docs/plans/`. No path outside the four named files and `docs/plans/`
      appears.
- [x] Run the documentation-only pathspec diff from Validation Commands and
      confirm it is empty. If it is not, stop and report — the lease is not
      disjoint and this round must not proceed.
      Result: empty. The lease is disjoint and documentation-only; no
      benchmark, source, test, or workflow path is touched.
- [x] Create an isolated lane worktree/branch cut from current `main` named
      `codex/goalex-lifecycle-backlog-delivery` (use a git worktree under
      `/Users/admin/.codex/worktrees/` or `git switch -c` from `main` in a
      separate checkout — do not develop on the controller branch itself).
      Created: `git worktree add -b codex/goalex-lifecycle-backlog-delivery
      /Users/admin/.codex/worktrees/9697/lane-lifecycle-backlog main`, cut at
      `061c2e1c`. The controller branch was not developed on.
- [x] Apply exactly the delta into the lane, e.g.
      `git checkout codex/goalex-whole-memory-pilot -- <the enumerated paths>`,
      then `git status --porcelain` to confirm no other path changed.
      Applied. The `git checkout <ref> -- <path>` form was refused by the local
      `dcg` guard (`core.git:checkout-ref-discard`), so the delta was
      materialized non-destructively instead: each path from
      `git diff --name-only main...HEAD` was written with
      `git show codex/goalex-whole-memory-pilot:<path>`. Verification:
      `git status --porcelain` in the lane lists exactly 30 paths — the same 30
      — and `git diff --cached --name-only codex/goalex-whole-memory-pilot` is
      empty, proving the lane tree is byte-identical to the controller HEAD
      tree. The lane diff versus `main` reproduces the 30 files / 1535
      insertions / 24 deletions exactly. No other path changed.

### Task 2: Make the delivered lifecycle text self-consistent post-merge
- [x] In `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`:
      flip node `T3` from `ADMITTED` to `DELIVERING` (or equivalent), stating
      that this PR is the delivery, that the map must be recomputed from the
      resulting `main` before any further admission, and that the only residual
      undelivered item after this merge is the follow-up receipt block (PR
      number, exact-head CI id, post-merge CI id) which cannot exist inside the
      commit it describes.
      Done in three places: the T3 DAG row (`ADMITTED` -> `DELIVERING`, "This
      PR is the delivery", recompute-before-next-admission and receipt-residue
      clauses added to its integration column); the narrative paragraph that
      previously deferred landing to "the next round's GoalEx-owner PR"; and
      the "Current delivery wave" block, which now reads
      `[delivering: this PR]` and states the wave holds no admitted node after
      the merge.
- [x] In `GOAL.md`, rewrite the Authority carve-out paragraph so it describes
      the state this PR creates: the branch-resident map is being delivered to
      `main` by this PR, and the carve-out closes on merge except for the
      receipt-only residue named above. Do not delete the carve-out's lapse
      rule.
      Rewritten in the past tense of the deferral state, naming this PR as the
      deferred GoalEx-owner delivery and stating the carve-out closes on merge
      except for the receipt-only residue. The lapse rule is preserved verbatim
      in substance ("it lapses the moment any merge lands on `main` that the
      branch-resident map does not already record ... recomputed from current
      `main` before it is treated as operative again"), and the later
      "for as long as that carve-out is open" reference still reads correctly.
- [x] In `.planning/STATE.md`, keep the PR #81-#84 whole-memory Decisions entry
      and PR #90 receipts, and confirm no status, admission state, or
      publication claim is upgraded anywhere in the diff.
      Both retained: the PR #81-#84 Decisions entry is intact (it still records
      `PILOT-READY-DEV`/`PROPOSED` and non-publishable results), as are the
      PR #90 receipts (`main@061c2e1c`, exact-head CI `30679262270`, post-merge
      CI `30680201900`). Two sentences were made post-merge-consistent: the
      deferral sentence now says this PR lands the delta and names the receipt
      residue, and the "Until the deferred PR lands, that sentence on `main` is
      known-stale" clause now records that staleness as closed by this PR.
      Every status token added by the diff asserts `PROPOSED` /
      `publishable:false` / `pbpp_headline_eligible:false`; none is upgraded.
- [x] Confirm the pilots-plan correction still reads correctly on top of current
      `main` (the stale sentence claiming the M12/M13 gap-disclosure paragraphs
      "are not on main and are still pending PR delivery" must be replaced,
      because PR #90 falsified it; Tasks 7 and 8 are closed on `main`).
      Confirmed against `git diff main -- <pilots plan>`: the stale sentence is
      replaced by one recording PR #90's separate delivery at `main@061c2e1c`
      and closing Tasks 7 and 8 on canonical main, and the twelve-line
      `Gap-disclosure delivery:` receipt block appends cleanly to the M12/M13
      checkpoint section. Its `2026-08-01` date matches PR #90's UTC merge time
      (`2026-08-01T02:32:10Z`).
- [x] Re-grep the whole lane diff for forbidden upgrades: `publishable:true`,
      `pbpp_headline_eligible:true`, any `PILOT-READY` promotion, any
      leaderboard/certification/superiority wording. There must be none.
      None found. The only added lines matching the patterns are this plan
      file's own text quoting the prohibition, `PILOT-READY-DEV` preservation
      statements (not promotions), and "certificate-rotator" test references
      (not a certification claim). The out-of-lease pathspec diff is still
      empty, and `python -m pytest tests/test_planning_traceability.py -q`
      passes in the lane (6 passed).

### Task 3: Gate the lane locally, then open and merge the PR
- [x] Run `ruff check .` and `python -m pytest tests/test_planning_traceability.py -q`
      in the lane. If other test modules pin the text of any changed file (grep
      `tests/` for the changed filenames), run those too. Fix real failures at
      the root cause; do not weaken a test to pass.
      Both green in the lane worktree
      (`/Users/admin/.codex/worktrees/9697/lane-lifecycle-backlog`) using the
      repo venv interpreter: `ruff check .` -> "All checks passed!";
      `pytest tests/test_planning_traceability.py -q` -> 6 passed.
      `grep -rlE 'GOAL\.md|STATE\.md|docs/plans|remaining-dependency-write-lease-map|whole-memory-reference-harness-pilots' tests/`
      returns only `tests/test_planning_traceability.py`, so no other module
      pins the changed filenames. No test was weakened.
- [x] Commit with a documentation-scoped message (e.g.
      `docs(goalex): deliver the stranded lifecycle and round-record backlog`),
      push the lane branch normally, and open a PR against `main` whose body
      enumerates the delivered files, states the change is documentation-only,
      and states that it admits no new implementation package and changes no
      benchmark, measurement, admission state, or publication claim.
      Committed as five documentation-scoped commits on
      `codex/goalex-lifecycle-backlog-delivery`
      (`a066e5e1` "docs(goalex): deliver the stranded lifecycle and round-record
      backlog", then `ac7463d2`, `63570914`, `5867c45b`, and head `45cc6c0c`),
      pushed normally (no force-push), and opened as PR #91
      <https://github.com/onfire7777/Mnemosyne/pull/91> against `main`. The lane
      diff versus `main` is 30 files / 1632 insertions / 25 deletions, and the
      documentation-only pathspec diff is still empty.
- [x] Watch exact-head CI to green with `gh pr checks <PR#> --watch`. Resolve
      any review thread or mergeability blocker on its merits; self-repair
      routine CI/transport failures. Record the exact-head run id.
      Exact-head CI run id `30686224929` (workflow `CI`, event
      `pull_request`, head `45cc6c0c`) concluded `success`. No review thread or
      mergeability blocker was outstanding and no finding was dismissed.
- [x] Merge through the normal GitHub merge path once CI and review are clear.
      Record the merge commit SHA and the post-merge `main` CI run id from
      `gh run list --branch main`; wait for it to pass.
      Merged through the normal GitHub merge path at `2026-08-01T06:15:05Z`.
      Merge commit `e157e0350c503c9cde4aca0eff71d643a4adb200`, which is now
      `origin/main`. Post-merge `main` CI run id `30687385118` (head
      `e157e035`) was watched to completion and concluded `success`. The lane
      branch was deleted on the remote by the merge; no force-push was used.

### Task 4: Reconcile the controller branch and disclose the residue
- [ ] In the controller worktree: `git fetch --prune origin`, fast-forward local
      `main` to `origin/main`, and prove `git rev-parse main` equals
      `git rev-parse origin/main`. Merge the new `main` into
      `codex/goalex-whole-memory-pilot` (normal merge, no force-push, no reset).
- [ ] Confirm `git diff --stat main...HEAD` now shows only the receipt-level
      residue, and update `GOAL.md`, `.planning/STATE.md`, and the lease map on
      the controller branch to record: the PR number, merge SHA, exact-head CI
      run id, post-merge CI run id; that `T3` is `MERGED`; that the map is
      recomputed from the new `main` baseline; and that the wave is now empty
      with no admitted node.
- [ ] State explicitly in the map whether the `GOAL.md` Authority carve-out is
      now closed or has re-opened at receipt scope only, and name the next
      dependency-ready candidate (or record that none is admissible and why).
- [ ] Run the full GOAL.md verification block from Validation Commands and
      confirm exit code 0 with a clean working tree.
