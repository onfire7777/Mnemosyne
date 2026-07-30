# Plan: Close Canonical Truth and Memory Refresh

## Overview
Canonical local `main` and `origin/main` equal `2ba4ed80f48717e92caaa66aeef48d2d331cb0bc`, the normal merge of PR #87. PR #86 previously merged as `661343ce05186e9a7f0f0740d1edef7c23532857`, and the current lifecycle files record its development-only scheduled-regression boundary.

The clean Wiki repository `/Users/admin/Mnemosyne.wiki` is at `46c34287fe064842e72c3f52a9afad0c822b1846`, equals its locally known `origin/master`, and updates exactly `Home.md`, `Roadmap-and-Status.md`, `Calibration-and-Evaluation.md`, and `Development-Guide.md` for `main@2ba4ed80`.

The current dependency/write-lease map permits only T2: one deduplicated CBM refresh and one durable Gbrain milestone after proving PR #87 and Wiki delivery. It explicitly admits zero new implementation writers. Do not modify repository or Wiki files, launch sandbox work, or advance result-v2, Phase 14, Phase 15, official benchmarks, measurements, publication, or launch.

Execution worktree: `/Users/admin/Mnemosyne.codex-goal-state-wiki-reconcile`

## Validation Commands
- `test "$(pwd -P)" = "/Users/admin/Mnemosyne.codex-goal-state-wiki-reconcile" && test "$(git branch --show-current)" = "codex/goal-state-wiki-reconcile" && test -z "$(git status --porcelain)"`
- `test "$(git -C /Users/admin/Mnemosyne rev-parse main)" = "2ba4ed80f48717e92caaa66aeef48d2d331cb0bc" && test "$(git -C /Users/admin/Mnemosyne rev-parse origin/main)" = "2ba4ed80f48717e92caaa66aeef48d2d331cb0bc" && test -z "$(git -C /Users/admin/Mnemosyne status --porcelain)"`
- `gh pr view 87 --json state,headRefOid,mergeCommit,mergeable,reviewDecision,statusCheckRollup`
- `gh run list --branch main --limit 20 --json databaseId,headSha,status,conclusion,workflowName,url`
- `test "$(git -C /Users/admin/Mnemosyne.wiki rev-parse HEAD)" = "$(git -C /Users/admin/Mnemosyne.wiki rev-parse origin/master)" && test -z "$(git -C /Users/admin/Mnemosyne.wiki status --porcelain)"`
- `test "$(git -C /Users/admin/Mnemosyne.wiki show --name-only --format='' 46c34287 | sort)" = "$(printf '%s\n' Calibration-and-Evaluation.md Development-Guide.md Home.md Roadmap-and-Status.md | sort)"`

### Task 1: Prove the T0 and T1 delivery gates
- [x] Refresh GitHub read-only state and prove PR #87 is `MERGED` as exact commit `2ba4ed80f48717e92caaa66aeef48d2d331cb0bc`, with zero unresolved current review threads and a successful required CI run whose `headSha` exactly matches that merge commit.
- [x] If GitHub remains unreachable or exact post-merge CI is absent, pending, or failing, stop with the exact command evidence; do not edit files, rerun broad tests, refresh memory, or admit another package.
- [x] Fetch the Wiki remote read-only, then prove `/Users/admin/Mnemosyne.wiki` is clean, `master == origin/master == 46c34287fe064842e72c3f52a9afad0c822b1846`, and its four changed pages preserve the non-publishable, non-headline, official-evidence-open, and scheduled-event-open boundaries.
- [x] Re-read the dependency/write-lease map from `main@2ba4ed80` and confirm T2 is the only admitted next node and that no source implementation writer is dependency-ready.

### Task 2: Perform the single deduplicated T2 refresh
- [x] Using codebase-memory-mcp, inspect the existing Mnemosyne index, refresh the actual canonical checkout `/Users/admin/Mnemosyne` exactly once if stale, and verify the index reaches ready/current state for `main@2ba4ed80`.
- [x] Search Gbrain for an existing milestone covering PRs #86–#87 and Wiki commit `46c34287`; update that record if present or create exactly one source-grounded milestone if absent—never create a duplicate.
- [x] Record only durable receipts: PR #86 merge and development-only boundary, PR #87 canonical-truth merge and exact post-merge CI, Wiki equality, remaining operator/evidence gates, and the fact that the current map admits no new source package.
- [x] Reconfirm both execution and canonical worktrees remain clean and unchanged; return control to GoalEx without starting quarantined sandbox, result-v2, Phase 14–15, measurement, or publication work.
