# Plan: Sync Controller GOAL.md to Merged Canonical Truth

## Overview
This GoalEx controller worktree at `/Users/admin/.codex/worktrees/9697/Mnemosyne`
(branch `codex/goalex-whole-memory-pilot`) drives the Mnemosyne whole-memory
program. Canonical `main` and `origin/main` both equal
`2ba4ed80f48717e92caaa66aeef48d2d331cb0bc` (the normal merge of PR #87, the T0
canonical-truth package). PR #87 updated `GOAL.md` on `main` under the GoalEx
lifecycle-owner lease; that merged version records PR #86 (`661343ce`) and
carries a verification block that passes against current main (it checks
`main == origin/main` and ancestries of `661343ce…`, `a95fe4d2…`, `baf5c185…`
instead of pinning a now-stale main SHA).

However, the copy of `GOAL.md` on this controller branch is the older
pre-PR-#87 snapshot: it still pins `main == 90841427da5e8299048cf86d027c451570e479a6`,
so the loop's verification exits 1 even though delivery is fully proven.
Previous rounds (e.g. commit `0111fbec docs(goalex): align admission truth
with main`) updated this branch's GOAL.md directly under the same owner lease.

The fix is a byte-exact sync: replace this branch's `GOAL.md` with the merged
canonical version from `main`, prove the diff is empty, run the new
verification block, and commit on this branch only. Do NOT modify any other
file, do not push to or touch `main`, do not open a PR, do not start sandbox,
result-v2, Phase 14-15, measurement, or publication work — the current
dependency/write-lease map (`docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`
on `main`) admits zero new implementation writers.

Execution worktree: `/Users/admin/.codex/worktrees/9697/Mnemosyne`

## Validation Commands
- `test "$(pwd -P)" = "/Users/admin/.codex/worktrees/9697/Mnemosyne" && test "$(git branch --show-current)" = "codex/goalex-whole-memory-pilot"`
- `git fetch --prune origin && test "$(git rev-parse main)" = "$(git rev-parse origin/main)" && test "$(git rev-parse main)" = "2ba4ed80f48717e92caaa66aeef48d2d331cb0bc"`
- `git diff --quiet main -- GOAL.md`
- `bash -c 'set -euo pipefail; cd /Users/admin/.codex/worktrees/9697/Mnemosyne; awk "/^\`\`\`bash$/,/^\`\`\`$/" GOAL.md | sed "1d;\$d" > /tmp/goal-verify.sh; bash /tmp/goal-verify.sh'`
- `test -z "$(git status --porcelain)"`

### Task 1: Prove merged canonical truth before writing
- [ ] In `/Users/admin/.codex/worktrees/9697/Mnemosyne`, confirm the branch is `codex/goalex-whole-memory-pilot` and `git status --porcelain` is empty; stop if dirty.
- [ ] Run `git fetch --prune origin` and prove `main == origin/main == 2ba4ed80f48717e92caaa66aeef48d2d331cb0bc`.
- [ ] Prove ancestry on main: `git merge-base --is-ancestor 661343ce05186e9a7f0f0740d1edef7c23532857 main`, `git merge-base --is-ancestor baf5c1852593885e37eed75da69b02d93e1bff11 main`, and `git merge-base --is-ancestor 90841427da5e8299048cf86d027c451570e479a6 main`.
- [ ] Confirm `git show main:GOAL.md` contains no `test "$(git rev-parse main)" = "9084` line (i.e. the merged version no longer pins a fixed main SHA); stop with evidence if it does.

### Task 2: Byte-exact GOAL.md sync, verify, and commit
- [ ] Overwrite the branch copy with the merged canonical version: `git show main:GOAL.md > GOAL.md`.
- [ ] Prove exact equality: `git diff --quiet main -- GOAL.md` and confirm `git status --porcelain` lists only `GOAL.md` as modified.
- [ ] Extract and run the verification block from the updated GOAL.md (the ```bash fenced block under `## Verification`) and confirm it exits 0.
- [ ] Commit only `GOAL.md` on this branch with message `docs(goalex): sync GOAL.md to merged canonical truth`; make no other changes, no pushes to main, and no PR.
- [ ] Reconfirm the worktree is clean afterward (`git status --porcelain` empty).
