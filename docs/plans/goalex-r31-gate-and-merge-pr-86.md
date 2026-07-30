# Plan: Gate and Merge PR #86

## Overview
PR #86 is the sole admitted delivery lane. It adds development-only scheduled public-regression CI through `.github/workflows/public-regression.yml` and `tests/test_public_regression_workflow.py`. Its clean Worktrunk is at exact source head `baf5c1852593885e37eed75da69b02d93e1bff11`, based on `main@90841427da5e8299048cf86d027c451570e479a6`.

Do not modify source, start the sandbox package, or merge while any required exact-head check is pending or failing. Require zero current unresolved review threads, clear mergeability, normal merge, and successful post-merge-main CI before updating canonical state.

Execution worktree: `/Users/admin/Mnemosyne.codex-phase13-public-regression-ci`

## Validation Commands
- `test "$(pwd -P)" = "/Users/admin/Mnemosyne.codex-phase13-public-regression-ci"`
- `test "$(git branch --show-current)" = "codex/phase13-public-regression-ci"`
- `test -z "$(git status --porcelain)"`
- `test "$(git rev-parse HEAD)" = "baf5c1852593885e37eed75da69b02d93e1bff11"`
- `gh pr checks 86 --required`
- `gh pr view 86 --json state,headRefOid,mergeCommit,mergeable,statusCheckRollup`
- `gh api graphql -f owner=onfire7777 -f name=Mnemosyne -F number=86 -f query='query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){pullRequest(number:$number){reviewThreads(first:100){nodes{isResolved isOutdated}}}}}' --jq '.data.repository.pullRequest.reviewThreads.nodes | [.[] | select((.isResolved|not) and (.isOutdated|not))] | length'`
- `git diff --check 90841427da5e8299048cf86d027c451570e479a6...HEAD`
- `test "$(git diff --name-only 90841427da5e8299048cf86d027c451570e479a6...HEAD | sort)" = "$(printf '%s\n' .github/workflows/public-regression.yml tests/test_public_regression_workflow.py | sort)"`

### Task 1: Clear the exact-head delivery gates
- [ ] Wait for run `30559003114` to reach a terminal state and require every required job to pass; do not restart, duplicate, or bypass the pending Unit + drift checks.
- [ ] Reconfirm PR #86 still points to exact head `baf5c1852593885e37eed75da69b02d93e1bff11`, is mergeable, has successful CodeRabbit and Greptile results, and has zero current unresolved review threads.
- [ ] If any gate fails, diagnose and repair only the two-file PR #86 lease, rerun the affected focused check, push normally, and restart exact-head verification against the new head.
- [ ] When all gates are freshly green, merge PR #86 normally without force, administrator bypass, or hook/check waiver.

### Task 2: Prove post-merge main and record the boundary
- [ ] Capture the merge commit and require the CI workflow triggered for that exact `main` commit to pass every required job.
- [ ] Fast-forward `/Users/admin/Mnemosyne` only if it is clean; prove local `main == origin/main == <merge commit>` and PR #86 is `MERGED`.
- [ ] Refresh the CBM index once against canonical `/Users/admin/Mnemosyne` and record one deduplicated source-grounded Gbrain milestone.
- [ ] Update the GoalEx admission receipt to describe scheduled regression CI as merged while preserving development-only, non-publishable, non-headline-eligible boundaries.
- [ ] Stop after reconciliation and return control to GoalEx for fresh dependency/write-lease admission; do not automatically launch the previously planned OCI sandbox delivery.
