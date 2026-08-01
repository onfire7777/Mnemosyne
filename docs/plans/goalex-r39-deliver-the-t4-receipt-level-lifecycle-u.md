# Plan: Deliver the T4 Receipt-Level Lifecycle Update Through a Reviewed PR

## Overview

You are the executor for round 39 of an autonomous loop on the Mnemosyne
repository. You implement; you never choose program direction.

Context (you have no memory of prior rounds):

- Worktree: `/Users/admin/.codex/worktrees/9697/Mnemosyne`
- Controller branch: `codex/goalex-whole-memory-pilot` (clean at plan time)
- Canonical `main` == `origin/main` == `e157e0350c503c9cde4aca0eff71d643a4adb200`
- `git rev-list --left-right --count main...HEAD` reports `0 99`: the controller
  branch is 99 commits ahead of `main` and 0 behind.

Last round (r38) delivered node `T3` as PR #91, merged at `main@e157e035`
(exact-head CI `30686224929`, post-merge CI `30687385118`). Because no commit
can describe its own merge, `main`'s copies of `GOAL.md`, `.planning/STATE.md`,
and `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md` still
carry PR #91's pre-merge self-reference (`T3` as `DELIVERING`, "This PR is the
delivery"). The controller branch already contains the recomputed post-merge
text at `Baseline: main@e157e035` with `T3` as `MERGED` plus PR #91's receipt
block — it is simply undelivered.

The lease map's only admitted node from this baseline is `T4` (see its row and
the "Current delivery wave" block): a documentation-only, receipt-level
lifecycle update, exact-lease-disjoint from every public-harness, CI,
result-v2, and evidence lease, admitting no source node. **Do not** start any
benchmark, harness, sandbox, result-v2, workflow, or CI-source work this round.

The undelivered delta versus `main` is exactly (verify it yourself with
`git diff --name-status main...HEAD`):

- `GOAL.md` (M)
- `.planning/STATE.md` (M)
- `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md` (M)
- `docs/plans/goalex-r38-deliver-the-t3-goalex-lifecycle-backlog-.md` renamed to
  `docs/plans/completed/goalex-r38-deliver-the-t3-goalex-lifecycle-backlog-.md`
- plus this round's own new `docs/plans/goalex-r39-*.md` record if the loop
  writes one into the worktree

This is documentation only. It must change no benchmark, measurement, admission
state, publication claim, test, workflow, or source code. M12/M13 must stay
`PROPOSED` / `publishable:false` / `pbpp_headline_eligible:false`.

Hard rules: never write directly to `main`, never force-push, never bypass
hooks, never dismiss review findings. Delivery goes through a normal PR from an
isolated lane branch cut from `main`, with exact-head CI, review clearance,
merge, and a post-merge `main` CI proof. Do NOT touch
`/Users/admin/Mnemosyne.codex-whole-memory-benchmark-spec` or
`/Users/admin/Mnemosyne.codex-phase16-signed-publication`; both are external
leases.

Note on local guards: `git checkout <ref> -- <path>` is refused by the local
`dcg` guard (`core.git:checkout-ref-discard`). Round 38 materialized the delta
with `git show <branch>:<path> > <path>` per file instead; reuse that approach.

## Validation Commands

- `git -C /Users/admin/.codex/worktrees/9697/Mnemosyne fetch --prune origin`
- `git -C /Users/admin/.codex/worktrees/9697/Mnemosyne rev-parse main origin/main`
- `git diff --name-status main...HEAD`
- `git diff main...HEAD -- ':!GOAL.md' ':!.planning/STATE.md' ':!docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md' ':!docs/plans/'` (must be empty — proves the lease is documentation-only)
- `ruff check .`
- `python -m pytest tests/test_planning_traceability.py -q`
- `gh pr checks <PR#> --watch`
- `gh run list --branch main --limit 5`
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
  git merge-base --is-ancestor 061c2e1c13cbf1fd5324361a6ff61f47cd2a6534 main
  git merge-base --is-ancestor e157e0350c503c9cde4aca0eff71d643a4adb200 main
  # Exact canonical baseline; ancestry alone also passes on a moved `main`,
  # which is exactly when the carve-out lapses.
  test "$(git rev-parse main)" = "e157e0350c503c9cde4aca0eff71d643a4adb200"
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

### Task 1: Recompute the exact T4 delta and open an isolated lane

- [x] `git fetch --prune origin`; confirm `main == origin/main` and record the
      SHA. If any commit has landed on `main` since `e157e035`, the GOAL.md
      carve-out lapses: first merge `main` into the controller branch, then
      recompute the lease map from the new `main` before continuing.
- [x] Run `git diff --name-status main...HEAD` and record the exact file list.
      It must contain only `GOAL.md`, `.planning/STATE.md`,
      `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`,
      and paths under `docs/plans/`. If anything else appears, stop and report.
- [x] Run the documentation-only pathspec diff from Validation Commands and
      confirm it is empty. If it is not, stop — the lease is not disjoint.
- [x] Create an isolated lane worktree/branch cut from current `main`, e.g.
      `git worktree add -b codex/goalex-t4-receipt-delivery
      /Users/admin/.codex/worktrees/9697/lane-t4-receipt main`. Do not develop
      on the controller branch itself.
- [x] Materialize exactly the delta in the lane: for each path from
      `git diff --name-only main...HEAD`, write
      `git show codex/goalex-whole-memory-pilot:<path> > <path>` (creating
      parent dirs as needed), and `git rm` the old
      `docs/plans/goalex-r38-deliver-the-t3-goalex-lifecycle-backlog-.md`
      location so the rename is reproduced. Then prove the lane tree matches:
      `git add -A && git diff --cached --name-only codex/goalex-whole-memory-pilot`
      must be empty, and `git status --porcelain` must list only the enumerated
      paths.

### Task 2: Make the delivered T4 text self-consistent post-merge

- [x] In `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`,
      flip node `T4` from `ADMITTED` to `DELIVERING` (or equivalent) in its DAG
      row, the narrative paragraph, and the "Current delivery wave" block:
      state that this PR is the T4 delivery, that the map must be recomputed
      from the resulting `main` before any further admission, and that the only
      residual item after this merge is the one-block receipt (PR number,
      exact-head CI id, post-merge CI id) that cannot exist inside the commit it
      describes. Preserve the map's existing statement that this residual lag is
      an accepted standing condition admitting **no successor node** and that
      `T4` is the last node the carve-out admits.
- [x] In `GOAL.md`, rewrite the Authority carve-out and Current Phase text so
      they describe the state this PR creates (this PR is the `T4` delivery;
      after merge the carve-out is discharged down to the accepted one-block
      standing residue). Preserve the lapse rule verbatim in substance and
      preserve the statement that `T4`'s residue admits no successor node.
- [x] In `.planning/STATE.md`, make the matching receipt text post-merge
      consistent, keeping the PR #81-#84 whole-memory Decisions entry and the
      PR #90/#91 receipts intact. Confirm no status, admission state, or
      publication claim is upgraded anywhere in the diff.
- [x] Re-grep the whole lane diff for forbidden upgrades: `publishable:true`,
      `pbpp_headline_eligible:true`, any `PILOT-READY` promotion, and any
      leaderboard/certification/superiority wording. There must be none beyond
      text that quotes the prohibition itself.
- [x] Re-run the documentation-only pathspec diff against the lane to confirm it
      is still empty.

### Task 3: Gate the lane locally

- [x] In the lane worktree, run `ruff check .` and
      `python -m pytest tests/test_planning_traceability.py -q` with the repo
      venv interpreter. Grep `tests/` for the changed filenames and run any
      other module that pins their text. Fix real failures at the root cause;
      never weaken a test to pass.
- [x] Commit the lane with a clear message (documentation-only receipt-level
      lifecycle update discharging the `T3` residue, carried by lease-map node
      `T4`). Do not force-push and do not bypass hooks.

### Task 4: Open, gate, and merge the PR; prove post-merge main

- [x] Push the lane branch normally and open a PR against `main` whose body
      states: documentation only, lease-map node `T4`, admits no source node,
      changes no benchmark/measurement/admission/publication claim, and names
      PR #91's receipts (`main@e157e035`, exact-head CI `30686224929`,
      post-merge CI `30687385118`) as the consumed baseline.
- [x] Watch exact-head CI with `gh pr checks <PR#> --watch` until green; resolve
      any review threads or mergeability blockers normally (never dismiss
      findings). Record the exact-head CI run id.
- [x] Merge through the normal PR flow, then record the merge commit SHA and
      watch the post-merge `main` CI run (`gh run list --branch main --limit 5`)
      until it is green. Record its run id.

**Task 4 receipts.** PR #92 (`codex/goalex-t4-receipt-delivery`). Exact-head CI
`30693874030` (green on the final head `16a05e83`; the first head `cc1ede82` was
green as `30692939187` before the review fixes). Merge commit
`39cfa67aa7692bf47d5dde5842af3d8ec0736bb0`. Post-merge `main` CI `30694818231`
(success). Four review threads were raised and all four resolved on their merits,
none dismissed:

- Markdown blank lines around fences/headings in this record — fixed in
  `16a05e83`; `git diff --ignore-blank-lines` on the file is empty.
- Ancestry-only baseline check in `GOAL.md` — accepted. `merge-base
  --is-ancestor` also passes when `main` carries later, unrecorded merges, which
  is exactly the condition under which the carve-out lapses, so ancestry could
  not distinguish an operative baseline from a lapsed one. `bbf05b99` adds an
  exact equality assertion against the recorded canonical baseline, making the
  verification block itself the lapse detector; the prior ancestry assertions are
  preserved. Recorded as a baseline that Task 5 advances rather than a frozen
  literal.
- The same ancestry-only check in this plan record's quoted copy of the block —
  mirrored in `16a05e83`.
- "T4 asserts a non-canonical baseline", claiming `main` resolved to
  `2ba4ed80`. Verifiably incorrect and answered with evidence on the thread:
  `2ba4ed80` is PR #87's merge commit and an *ancestor* of `main`, 14 commits
  behind it, while `main` and `origin/main` both resolved to `e157e035` exactly
  as asserted. The reading came from a checkout predating PRs #88-#91, and the
  concern is inverted relative to the risk — a stale ancestor cannot stale the
  delta; a newer `main` could, and that case now fails loudly.

### Task 5: Reconcile the controller branch and record the residue

- [ ] In the controller worktree, `git fetch --prune origin` and fast-forward
      local `main` to `origin/main`; prove `git rev-parse main` equals
      `git rev-parse origin/main` and that the new merge commit is an ancestor
      of `main`. Merge `main` into `codex/goalex-whole-memory-pilot` normally.
- [ ] Recompute the lease map from the new `main`: set `Baseline:` to the new
      merge SHA, flip `T4` to `MERGED` with its receipt block (PR number,
      exact-head CI id, post-merge CI id), and record that this recomputation
      is the accepted one-block standing residue which admits **no** successor
      node and **no** source node. Update `GOAL.md` and `.planning/STATE.md` to
      the matching post-merge text (including the new SHA in the GOAL.md
      verification block's `merge-base --is-ancestor` assertions).
- [ ] Commit that reconciliation on the controller branch and confirm
      `git status --porcelain` is empty and the GOAL.md verification block
      exits 0. Report in the round summary: the PR number, merge SHA,
      exact-head CI id, post-merge CI id, and the explicit statement that the
      map admits no source node at the new baseline, so the next source
      admission waits on an external gate opening.
