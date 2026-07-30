# Plan: Resolve and Close PR #86 Delivery Gates

## Overview
PR #86 adds development-only scheduled public-regression CI using only `.github/workflows/public-regression.yml` and `tests/test_public_regression_workflow.py`. The clean execution checkout is on `codex/phase13-public-regression-ci` at `baf5c1852593885e37eed75da69b02d93e1bff11`, based on `main@90841427da5e8299048cf86d027c451570e479a6`.

Round 31 prepared a broader merge plan but did not produce current proof that PR #86 merged. Avoid repeating speculative sandbox work or modifying source while delivery gates remain unknown. Query the pinned CI run and PR state directly; if GitHub remains unreachable or any substantive gate fails, stop with the exact evidence instead of merging or inventing a repair.

Execution worktree: `/Users/admin/Mnemosyne.codex-phase13-public-regression-ci`

## Validation Commands
- `test "$(pwd -P)" = "/Users/admin/Mnemosyne.codex-phase13-public-regression-ci"`
- `test "$(git branch --show-current)" = "codex/phase13-public-regression-ci"`
- `test -z "$(git status --porcelain)"`
- `test "$(git rev-parse HEAD)" = "baf5c1852593885e37eed75da69b02d93e1bff11"`
- `test "$(git remote get-url origin)" = "https://github.com/onfire7777/Mnemosyne.git"`
- `gh run view 30559003114 --json headSha,status,conclusion,jobs,url`
- `gh pr checks 86 --required`
- `gh pr view 86 --json state,headRefOid,mergeable,mergeStateStatus,reviewDecision,statusCheckRollup,mergeCommit`
- `gh api graphql -f owner=onfire7777 -f name=Mnemosyne -F number=86 -f query='query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){pullRequest(number:$number){reviewThreads(first:100){nodes{isResolved isOutdated}}}}}' --jq '.data.repository.pullRequest.reviewThreads.nodes | [.[] | select((.isResolved|not) and (.isOutdated|not))] | length'`
- `git diff --check 90841427da5e8299048cf86d027c451570e479a6...HEAD`
- `test "$(git diff --name-only 90841427da5e8299048cf86d027c451570e479a6...HEAD | sort)" = "$(printf '%s\n' .github/workflows/public-regression.yml tests/test_public_regression_workflow.py | sort)"`

### Task 1: Establish a terminal exact-head verdict
- [x] Confirm run `30559003114` belongs to head `baf5c1852593885e37eed75da69b02d93e1bff11`; use `gh run watch 30559003114 --exit-status` only if it remains non-terminal.
- [x] Require all required checks to pass, zero current unresolved non-outdated review threads, exact PR head equality, and `MERGEABLE`/clean merge state.
- [x] If GitHub is unreachable after a fresh authentication/status check, or any gate fails, stop and report the exact command and result. Do not edit source, rerun broad CI, merge, or launch another package.
- [x] If PR #86 is already merged, record its merge commit and proceed directly to post-merge verification. Otherwise merge normally without administrator bypass, force, or check waiver.

### Task 2: Verify exact post-merge main
- [ ] Identify the CI run whose `headSha` exactly equals PR #86’s merge commit and require every required job to finish successfully.
- [ ] Fast-forward `/Users/admin/Mnemosyne` only after proving it is clean; verify local `main`, `origin/main`, and the PR merge commit are identical.
- [ ] Confirm PR #86 is `MERGED` and the two scheduled-regression files exist on that exact `main`.
- [ ] Record only the merge SHA, exact-main CI run, review-thread count, and preserved development-only/non-publishable boundary. Do not refresh CBM/Gbrain prematurely, edit canonical planning truth, or admit the quarantined sandbox lane.
