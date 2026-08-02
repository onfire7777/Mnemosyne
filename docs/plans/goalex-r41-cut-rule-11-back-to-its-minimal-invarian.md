# Plan: Cut Rule 11 Back to Its Minimal Invariant, Land PR #93, and Recompute Branch Truth

Historical round record, abandoned and superseded by PR #93's merge and the
bounded `T5` delivery admitted after that independent merge lapsed the
carve-out. Task 1's planned removal of the ignored-path manifest, secret, and
park-marker apparatus did not land; current `GOAL.md` and the traceability
contract retain it. The unchecked tasks below preserve the historical plan and
evidence; they do not claim completion.

## Overview

You are the executor for round 41 of an autonomous GoalEx loop on the Mnemosyne
repository. You have no memory of prior rounds; everything you need is below.

- Controller worktree: `/Users/admin/.codex/worktrees/9697/Mnemosyne`
- Controller branch: `codex/goalex-whole-memory-pilot` (never write directly to `main`)
- Canonical baseline currently recorded on this branch: `main@39cfa67aa7692bf47d5dde5842af3d8ec0736bb0`
- Worktree is clean; the controller branch is ahead of its remote.

Authority files owned exclusively by this loop: `GOAL.md`, `.planning/STATE.md`,
`docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`, `docs/plans/`.

**The situation.** GitHub PR #93 (`onfire7777/Mnemosyne`, head branch
`codex/goalmd-round-ends-clean`, base `main`, head at last check
`7541d994798188b97fd99e3a8d51ae07e3b81009`) adds Bounded Task-Selection **rule 11**:
every GoalEx round must end with a clean controller worktree. Its purpose is real —
rounds 36, 37 and 39 each left post-merge receipts uncommitted, and the external
`goalex` launcher aborts its next preflight on a dirty tree, so the loop stalled.

Round 40 adjudicated the first review finding (Greptile's "dirty-tree preflight has
no tracked enforcement") as **dismissed with evidence**: `GOAL.md`'s Runtime Contract
already declares `.goalex/bin/goalex-sol` an *isolated derived launcher* — external
operator runtime this repo deliberately does not vendor — so importing a launcher and
its test would far exceed a documentation-only PR. That dismissal is recorded at
PR level and stands; do not revisit it.

**What went wrong since.** Successive review-fix cycles expanded rule 11 from ~11
lines to **+103 lines** in `GOAL.md` plus **+114/-6** in
`tests/test_planning_traceability.py`. The added text now specifies a recursive
manifest of *gitignored* paths (a row per directory *and* per entry beneath it),
per-object-type identity fields, SHA-256 vs keyed digests, a secret-bearing carve-out
enumerating `.gitignore` patterns and `infra/` generated material, an external
lossless copy procedure, and a durable park marker the launcher must honor. Each
cycle's fix produced new P1 findings about that same apparatus (directory-row
payload, directory mode coverage, nested rewrites, secret hash oracle). Nine review
rounds; still `mergeStateStatus: BLOCKED`.

**The adjudication for this round: reduce scope, do not keep patching.** The
ignored-path apparatus cannot serve rule 11's stated purpose. `git status --porcelain`
— the exact condition the launcher preflights on, and the exact condition every
stalled round tripped — **never lists ignored paths**. Verify this yourself before
editing (e.g. in a scratch temp repo: create `.gitignore` with `ig/`, write
`ig/file`, confirm `git status --porcelain` prints nothing). A manifest of ignored
paths therefore cannot change whether the loop stalls, and every open finding is
about that manifest. Removing it resolves the whole class on evidence rather than
one P1 at a time, and keeps the PR documentation-only.

Conventions: normal pushes only — never force-push, never bypass hooks, never dismiss
a finding without written evidence, never write directly to `main`.

## Validation Commands

- `cd /Users/admin/.codex/worktrees/9697/Mnemosyne && git status --porcelain` (must be empty at round end)
- `gh pr view 93 --json state,mergedAt,mergeCommit,mergeStateStatus,files`
- `gh pr checks 93`
- `git fetch --prune origin && git rev-parse main origin/main` (must be equal)
- `python -m pytest tests/test_planning_traceability.py -q`
- `ruff check .`
- The full `GOAL.md` Verification block, run on the controller branch after Task 4 (must exit 0)

### Task 1: Reduce rule 11 on the PR branch to its minimal invariant
- [ ] Check out `codex/goalmd-round-ends-clean` in an isolated worktree (do not disturb the controller worktree); confirm its diff against `main` touches only `GOAL.md` and `tests/test_planning_traceability.py`.
- [ ] Empirically confirm in a scratch temp repo that `git status --porcelain` reports nothing for a gitignored file, and record the exact commands and output for use as evidence in Task 2.
- [ ] Rewrite rule 11 in `GOAL.md` to at most ~20 lines, keeping exactly four claims: (a) a round ends with no round-owned residue — tracked or untracked — in the controller worktree, and post-merge receipts, canonical-truth reconciliation, and plan-checkbox closure are the round's own final commit, not afterthoughts; (b) unowned dirty work predating the round is rule 3's, checked at round start — if present, park with an explicit owner handoff recorded outside the controller worktree rather than starting the round; (c) any round-owned change that genuinely cannot be committed is preserved losslessly outside the controller worktree (a patch or archive carrying deletions, renames, modes, symlinks, and binary content), then cleared from **both index and worktree** for the paths the round owns, with the blocker named in the round's closing summary; (d) a deliberate park is subject to the same invariant.
- [ ] Delete the entire gitignored-path apparatus: the recursive manifest, per-type identity fields, SHA-256/keyed-digest text, the secret-bearing carve-out and its `.gitignore`/`infra/` enumeration, the external lossless copy of ignored contents, and the durable park marker. Replace it with a single explicit scoping sentence stating that gitignored paths are out of rule 11's scope because `git status --porcelain` does not report them and so they cannot cause the preflight stall this rule exists to prevent, and that no round may deliberately modify or remove one.
- [ ] Trim `tests/test_planning_traceability.py` so its rule-11 assertions pin only the reduced text; delete every assertion that pins removed manifest/secret/park-marker wording. Run `python -m pytest tests/test_planning_traceability.py -q` and `ruff check .`; both must pass.
- [ ] Commit and push normally to `codex/goalmd-round-ends-clean` (no force).

### Task 2: Adjudicate the open review threads on the reduction
- [ ] List the currently unresolved review threads on PR #93 (`gh api graphql` over `reviewThreads`, filtering `isResolved:false`).
- [ ] Post one PR-level comment (`gh pr comment 93`) stating the scope reduction: quote the empirical `git status --porcelain` evidence from Task 1, state that every open finding (directory manifest rows, directory mode coverage, nested rewrites, secret hash oracles, park-marker durability) is about text now removed, and that the removal resolves them on evidence rather than by re-specification.
- [ ] Reply to each remaining unresolved thread pointing at that comment, so no thread is left unanswered. Do not resolve a thread you have not answered.
- [ ] If a **new** finding lands on the reduced text, apply at most one further fix cycle, and only if the finding is a defect in the four retained claims. Any finding that would re-introduce ignored-path, hashing, or secret-handling specification is dismissed in-thread with the same evidence — do not re-expand the rule.

### Task 3: Drive PR #93 to green and merge it normally
- [ ] Poll `gh pr checks 93` until every gating check reaches a terminal state (`DST / chaos soak` is non-gating and skips). Re-run transport/flake failures with `gh run rerun <run-id> --failed` rather than changing the PR.
- [ ] Record the exact-head CI run id for the final PR head commit before merging.
- [ ] When `mergeStateStatus` is no longer `BLOCKED` and all gating checks pass, merge with `gh pr merge 93 --merge` (never squash-force, never admin-bypass).
- [ ] Record the merge commit SHA on `main`, the exact-head CI run id, and — after waiting for it to finish — the post-merge `main` CI run id and its conclusion.

### Task 4: Fast-forward canonical main and recompute branch-resident truth
- [ ] `git fetch --prune origin`; fast-forward local `main` (e.g. `git fetch origin main:main`) and prove `git rev-parse main` equals `git rev-parse origin/main` and equals the PR #93 merge SHA.
- [ ] Merge the new `main` into `codex/goalex-whole-memory-pilot` with a normal merge; resolve any `GOAL.md` or `tests/test_planning_traceability.py` conflict by keeping rule 11 as merged on `main` **and** this branch's lifecycle text and existing test content.
- [ ] In `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`: update `Updated:` and `Baseline:` to the new `main` SHA; add a "Merged baseline" bullet for PR #93 with the merge SHA, exact-head CI run id, and post-merge CI run id, stating it is documentation-only, moved no package status, and changed no benchmark, measurement, admission state, or publication claim; state that this merge lapsed the Authority carve-out, that this revision is the required recomputation from current `main`, that PR #93 was an owner-authored writer on the GoalEx lifecycle lease rather than an admitted source node, and that **no successor or source node is admitted**.
- [ ] In `GOAL.md`: update the Authority and Current Phase narrative to record PR #93, its receipts, and the lapse-and-recomputation, keeping the standing one-block-residue framing rather than inventing a new delivery node. In the Verification block, add `git merge-base --is-ancestor <PR#93 merge SHA> main` and update the exact-baseline equality to the new `main` SHA.
- [ ] In `.planning/STATE.md`: record the PR #93 merge with the same receipts in the existing style, changing no task status, admission state, or publication claim.
- [ ] Run `python -m pytest tests/test_planning_traceability.py -q`, `ruff check .`, and the full `GOAL.md` Verification block verbatim on this branch; all must pass and the block must exit 0.

### Task 5: Close the round with a clean controller worktree
- [ ] Write the round record `docs/plans/goalex-r41-reduce-rule-11-land-pr-93.md` covering: the scope-reduction adjudication and its `git status --porcelain` evidence, the PR #93 receipts (merge SHA, exact-head CI, post-merge CI), the carve-out lapse and branch-resident recomputation, and the explicit statement that no new source or delivery node was admitted.
- [ ] Commit every change from Tasks 4–5 on `codex/goalex-whole-memory-pilot` as the round's final step, honoring the newly merged rule 11.
- [ ] Push the controller branch normally: `git push origin codex/goalex-whole-memory-pilot` (no force).
- [ ] Confirm `git status --porcelain` prints nothing before yielding.
