---
type: concept
title: Mnemosyne PR 88 CI follow-ups and controller reconciliation
date: '2026-07-31T00:00:00.000Z'
status: delivered-development-only
tags:
  - canonical-truth
  - development-only
  - mnemosyne
---

# Mnemosyne PR 88 CI follow-ups and controller reconciliation

PR #88 merged as `main@4a891042`. It recovered post-merge follow-up work to PR #86 that had been written but left uncommitted in the CI-integration worktree when the autonomous loop was stopped, rather than rewriting it. Post-merge `main` check-runs at the exact merge commit `4a891042` all completed successfully: Unit + drift checks, Postgres integration, Lint (ruff), Native wheels (macos-14), Native wheels (ubuntu-latest), and Provider conformance. The DST / chaos soak job is non-gating and skipped.

Content is documentation plus test hardening only; no shipped-code behaviour changed. `README.md` now documents `.github/workflows/public-regression.yml`, its Monday 07:23 UTC cron and manual dispatch, and states explicitly that it is a bounded development regression that performs no official or held-out evaluation, produces no evidence or leaderboard receipts, and authorizes no publication. `tests/test_public_regression_workflow.py` gained a broadened top-level-key parser and a layout-independent `_mapping_items()` mapping comparison. `tests/test_production_mcp_client_cert_rotator.py` raised its rotator subprocess timeout from 15s to 60s; the full 289-test file passed locally with the new value.

Review was not bypassed. CodeRabbit raised two valid findings and both were fixed in `81117589`: the documented 07:23 UTC schedule was not enforced by any assertion, so the cron minute/hour is now pinned to `["23", "7"]` alongside the existing Monday check; and the `concurrency` assertion had been comparing raw block lines, which pinned YAML key order and a trailing blank line that are not an intentional contract. Both review threads were answered with evidence and resolved, leaving the pull request `CLEAN` with zero unresolved threads before merge.

The GoalEx controller branch `codex/goalex-whole-memory-pilot` had drifted 30 commits behind canonical `main`, so the worktree the loop's planner reads carried a stale `.planning/STATE.md` from the PR #84 era. `main` was merged into the controller branch at `4a9b839e`. Three files conflicted and were resolved at hunk level so cleanly merged branch-only content survived: `.planning/STATE.md` and `GOAL.md` took the canonical `main` side of every conflicted hunk, and `tests/test_production_mcp_client_cert_rotator.py` took `main`'s landed 60s timeout. `GOAL.md` retained its branch-only active-scheduling-policy paragraph. The branch is now zero commits behind `main`, clean, pushed, and its `GOAL.md` verification block exits 0.

Repository hygiene reached a clean baseline. The only worktree still carrying uncommitted changes is `codex/phase16-signed-publication`, which is an explicit external lease that must not be touched. The quarantined SBOX sandbox work on `codex/goalex-r26-sandbox` was committed locally at `f5b2da6e` purely to protect it from accidental loss, and remains unpushed with no pull request, consistent with its QUARANTINED status in the dependency and write-lease map.

Remaining gates are unchanged by this delivery. The first real scheduled-cadence receipt for the public-regression workflow is still open; its cron fires Mondays at 07:23 UTC and only a retained real `schedule` event proves the scheduled-cadence part of `BENCH-007`. Phase 12 measured closure remains operator and protected-evidence blocked. Official MemoryAgentBench and BEAM evidence remains operator and admission blocked. Result-v2 remains lease blocked behind the protected signed-publication paths. Phase 14 reproduction evidence and Phase 15 work remain dependency and evidence blocked. Publication and launch remain human and evidence gated. The dependency and write-lease map still admits zero new implementation writers.

A separate observation recorded during this work: post-merge check evidence for the older merge commit `eeb8765e` (PR #70, signed publication) exists and is green across all required jobs, retrievable through the commit check-runs endpoint even though the workflow-run listing for that commit returns empty.

## Sources

- GitHub pull request #88 merge, review, and check-run records for `onfire7777/Mnemosyne`
- `/Users/admin/Mnemosyne` at `main@4a891042`
- `/Users/admin/.codex/worktrees/9697/Mnemosyne` at `4a9b839e`
- `/Users/admin/Mnemosyne/docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`
- `/Users/admin/Mnemosyne/.github/workflows/public-regression.yml`
