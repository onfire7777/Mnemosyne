# Plan: Adjudicate, Land, and Reconcile the Rule-11 GOAL.md PR #93

## Overview

You are the executor for round 40 of an autonomous GoalEx loop on the Mnemosyne
repository. You have no memory of prior rounds; everything you need is below.

- Controller worktree: `/Users/admin/.codex/worktrees/9697/Mnemosyne`
- Controller branch: `codex/goalex-whole-memory-pilot` (never write directly to `main`)
- Canonical baseline recorded everywhere on this branch: `main@39cfa67aa7692bf47d5dde5842af3d8ec0736bb0`
- The local controller branch is currently ~10 commits ahead of
  `origin/codex/goalex-whole-memory-pilot` and the worktree is clean.

Authority files (all owned exclusively by the GoalEx lifecycle owner, i.e. this
loop):

- `GOAL.md`
- `.planning/STATE.md`
- `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`
- `docs/plans/`

**The situation.** GitHub PR #93 (`codex/goalmd-round-ends-clean`, author
`onfire7777`, base `main`) is OPEN. Its diff is `GOAL.md` only: +11/-0 visible as
a new Bounded Task-Selection **rule 11** requiring every GoalEx round to end with
a clean controller worktree, plus its escape-hatch and deliberate-park
paragraphs. It changes no benchmark, measurement, admission state, publication
claim, test, workflow, or source code.

Current PR #93 gate state (re-check it yourself, it will have moved):
`mergeable: MERGEABLE`, `mergeStateStatus: BLOCKED`. Passing: Lint (ruff),
Native wheels (macos-14 + ubuntu-latest), Postgres integration, Provider
conformance, CodeRabbit. Pending at last check: `Unit + drift checks`,
`Greptile Review`. `DST / chaos soak` is non-gating and skipped.

**The one open review finding to adjudicate.** Greptile filed a P1 on
`GOAL.md:259-260`: "GoalEx dirty-tree preflight is documented but has no tracked
enforcement" — it observes that `.goalex/bin/goalex-sol` is not tracked in this
repository and no tracked non-documentation source implements a
`git status --porcelain` guard, and asks for a tracked launcher plus a test.

Adjudicate this on evidence, do not reflexively implement it. Relevant evidence
already in the repo: `GOAL.md`'s "Runtime Contract" section already names
`.goalex/bin/goalex-sol` as an *isolated derived launcher* — i.e. deliberately
external, operator-owned runtime tooling that this repository does not vendor —
and rule 11's own wording says "**The external** GoalEx launcher aborts its next
preflight on a dirty tree". `GOAL.md` is a policy document for the loop, not a
specification of repository-tracked behavior, and importing an external launcher
into this repo would be far broader than any approved plan and would add a new
untested surface to a documentation-only PR. The defensible adjudication is
therefore **dismissal with evidence**, not implementation — but you must state
that reasoning in a PR comment rather than silently ignoring the finding. If you
conclude otherwise, do not widen scope: escalate in the round record instead.

**After the merge.** `GOAL.md`'s Verification block pins
`test "$(git rev-parse main)" = "39cfa67aa7692bf47d5dde5842af3d8ec0736bb0"`.
Merging PR #93 advances `main` past that pin, which is exactly the documented
lapse condition for the Authority carve-out: "it lapses the moment any merge
lands on `main` that the branch-resident map does not already record, at which
point the map must be recomputed from current `main` before it is treated as
operative again." So the second half of this round is a branch-resident
recomputation to the new `main`.

**Do not admit a new delivery node** to push that recomputation onto `main`.
`GOAL.md` and the lease map both state that `T4` is the last node the carve-out
admits and that regenerated receipt residue admits no successor node, because
that would make the delivery wave non-terminating. Record the recomputation as
branch-resident and disclose it plainly as lapse-triggered.

Conventions: normal pushes only — never force-push, never bypass hooks, never
dismiss a finding without written evidence, never write directly to `main`.

## Validation Commands

- `cd /Users/admin/.codex/worktrees/9697/Mnemosyne && git status --porcelain` (must be empty at round end)
- `gh pr view 93 --json state,mergedAt,mergeCommit,mergeStateStatus`
- `gh pr checks 93`
- `git fetch --prune origin && git rev-parse main origin/main` (must be equal)
- `python -m pytest tests/test_planning_traceability.py -q`
- `ruff check .`
- The full `GOAL.md` Verification block (run it on this branch after Task 4; it must exit 0)

### Task 1: Refresh state and adjudicate the PR #93 review finding
- [x] `git fetch --prune origin`; confirm you are on `codex/goalex-whole-memory-pilot` in `/Users/admin/.codex/worktrees/9697/Mnemosyne` with a clean worktree.
- [x] Re-read the live state of PR #93: `gh pr view 93 --json state,mergeable,mergeStateStatus,reviewDecision,files` and `gh pr checks 93`.
- [x] Re-confirm the diff is `GOAL.md` only: `git diff --name-only main...origin/codex/goalmd-round-ends-clean` must print exactly `GOAL.md`.
- [x] Read the `Runtime Contract` section of `GOAL.md` and quote the line that declares `.goalex/bin/goalex-sol` an isolated derived launcher.
- [x] Post one adjudication comment on PR #93 with `gh pr comment 93 --body '...'` that: names the Greptile P1 finding; dismisses it with the evidence that the launcher is external operator runtime by existing contract and that rule 11 already says "external"; states that vendoring a launcher and its test into this repo would exceed the approved documentation-only scope of this PR; and confirms the PR changes no benchmark, measurement, admission state, or publication claim.
- [x] Resolve or reply to the Greptile inline comment on `GOAL.md` the same way, so no review thread is left unanswered.

**Task 1 record (round 40).** Live state at head `22f7dcfe`: `state OPEN`,
`mergeable MERGEABLE`, `mergeStateStatus BLOCKED`, `reviewDecision
CHANGES_REQUESTED`; diff is `GOAL.md` only (+21/-0). All gating checks pass
except `Unit + drift checks`, still pending. Evidence gathered for the
adjudication: `git ls-files | grep -i goalex` returns 40 paths, every one a
document under `docs/plans/` or `.planning/` — no launcher source — and
`git grep -l "status --porcelain"` hits only markdown. Runtime Contract quote
used: "GoalEx planner/verifier: isolated derived launcher `.goalex/bin/goalex-sol`
using `gpt-5.6-sol:low`." The plan's target Greptile P1 ("no tracked
enforcement", comment `3696117548`) was already answered inline and its thread
is resolved and outdated; the dismissal is now also recorded at PR level in
[comment 5152550705](https://github.com/onfire7777/Mnemosyne/pull/93#issuecomment-5152550705).

**Scope note — the plan's "one open review finding" is stale.** Three *later*
threads on the current head are unresolved, and they are text defects in rule 11
itself rather than questions about external tooling, so each was adjudicated on
its own merits and **accepted**, not dismissed:

- Greptile P1 `3696167619` — rule 3 (preserve unowned dirty work) contradicts
  rule 11's unconditional whole-tree clean invariant. Replied `r3696179014`.
- Codex P2 `3696167066` — round-owned *untracked* files survive a restore
  scoped to tracked paths, so the tree stays dirty. Replied `r3696179107`.
- CodeRabbit `3696163764` — the uncommittable-change fallback names only
  receipts, not every round-owned change. Replied `r3696179209`.

All three rewrite the same rule 11 paragraph and will be fixed as one
documentation-only edit on `codex/goalmd-round-ends-clean` under Task 2's
"fix it with the smallest change, push normally" checkbox. No review thread is
left unanswered. `pytest tests/test_planning_traceability.py` (7 passed) and
`ruff check .` both green.

### Task 2: Drive PR #93 to green and merge it normally
- [ ] Poll `gh pr checks 93` until `Unit + drift checks` and `Greptile Review` reach a terminal state. If a check fails for a transport/flake reason, re-run it (`gh run rerun <run-id> --failed`) rather than changing the PR.
- [ ] If a check fails for a real reason attributable to the `GOAL.md` diff, fix it on `codex/goalmd-round-ends-clean` with the smallest change, push normally (no force), and re-poll.
- [ ] Record the exact-head CI run id for the final PR head commit before merging.
- [ ] When `mergeStateStatus` is no longer `BLOCKED` and all gating checks pass, merge with `gh pr merge 93 --merge` (never squash-force, never admin-bypass).
- [ ] Capture and write down: the merge commit SHA on `main`, the exact-head CI run id, and — after the merge push CI starts — the post-merge `main` CI run id. Wait for the post-merge run to complete and record its conclusion.

### Task 3: Fast-forward canonical main and prove it
- [ ] `git fetch --prune origin`, then fast-forward local `main` to `origin/main` without checking out the controller branch away permanently (e.g. `git fetch origin main:main`).
- [ ] Prove `git rev-parse main` equals `git rev-parse origin/main` and equals the PR #93 merge SHA.
- [ ] Merge the new `main` into `codex/goalex-whole-memory-pilot` with a normal merge so no commit on `main` is absent from the controller branch, and resolve any `GOAL.md` conflict by keeping both rule 11 (from `main`) and this branch's lifecycle text.

### Task 4: Recompute the branch-resident lifecycle truth from the new main
- [ ] In `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`: update `Updated:` and `Baseline:` to the new `main` SHA; add a "Merged baseline" bullet for PR #93 recording the merge SHA, exact-head CI run id, and post-merge CI run id, and stating it is documentation-only, moved no package status, and touched no source/test/workflow path; state explicitly that this merge lapsed the Authority carve-out, that this revision is the required recomputation from current `main`, that PR #93 was an owner-authored writer on the GoalEx lifecycle lease rather than an admitted source node, and that **no successor or source node is admitted** by it.
- [ ] In `GOAL.md`: update the Authority and Current Phase narrative to record PR #93 and its receipts and the lapse-and-recomputation; keep the standing one-block-residue framing rather than inventing a new delivery node.
- [ ] In `GOAL.md`'s Verification block: add `git merge-base --is-ancestor <PR#93 merge SHA> main` alongside the existing ancestry checks and update the exact-baseline equality `test "$(git rev-parse main)" = "..."` to the new `main` SHA so the block still exits 0 on this branch.
- [ ] In `.planning/STATE.md`: record the PR #93 merge with the same receipts, in the existing style, changing no task status, admission state, or publication claim.
- [ ] Run `python -m pytest tests/test_planning_traceability.py -q` and `ruff check .`; both must pass.
- [ ] Run the full `GOAL.md` Verification block verbatim on this branch; it must exit 0.

### Task 5: Close the round with a clean controller worktree
- [ ] Write the round record `docs/plans/goalex-r40-adjudicate-land-and-reconcile-pr-93.md` summarizing: the adjudication of the Greptile P1, the PR #93 receipts (merge SHA, exact-head CI, post-merge CI), the carve-out lapse and branch-resident recomputation, and the explicit statement that no new source or delivery node was admitted.
- [ ] Commit every change from Tasks 3-5 on `codex/goalex-whole-memory-pilot` as the round's final step, honoring newly merged rule 11.
- [ ] Push the controller branch normally: `git push origin codex/goalex-whole-memory-pilot` (no force).
- [ ] Confirm `git status --porcelain` prints nothing before yielding.
