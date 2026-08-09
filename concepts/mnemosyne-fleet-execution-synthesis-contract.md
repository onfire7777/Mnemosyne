---
type: concept
title: Mnemosyne fleet execution and synthesis contract
date: '2026-07-22T00:00:00.000Z'
tags:
  - hermes
  - mnemosyne
  - orchestration
  - rfx
---

# Mnemosyne fleet execution and synthesis contract

Mnemosyne uses a 100-persona Hermes capacity pool to maximize substantive parallel work while preserving dependency, custody, and integration correctness.

## Durable decisions

- The fleet contains 15 planners, 45 executors, 30 reviewers, and 10 captains. Persona SOUL files define model-free roles and specializations; rfx is the sole model authority.
- The active control plane resolves plan, task, review, all four roles, fallback, auxiliary, and delegation paths to openai-codex/gpt-5.6-sol with low reasoning effort.
- Admit every genuinely ready task whose dependency parents are complete, exact write leases are disjoint, isolated worktree exists, and live host admission passes. Do not impose arbitrary lower concurrency.
- Roster size is not live utilization. Never claim 100 substantive active workers without task, process, heartbeat, diff, and commit evidence.
- Independent lanes remain isolated through implementation and review. They converge in a dedicated synthesis/integration worktree where cross-lane bugs are fixed and the applicable integration gate is run.
- Delivery is one coherent merge request after exact-head CI is green. Do not force dependencies, overlap leases, bypass operator gates, or merge protected branches directly.

## System ownership

- Hermes owns task lifecycle, dependencies, assignment, worktrees, leases, and retries.
- RalphEx owns bounded plan, implementation, and independent-review iterations inside a claimed lane.
- GSD owns persistent project lifecycle and continuation state.
- CBM owns the repository knowledge graph and architecture decision record.
- gbrain owns durable project knowledge and indexed repository documents.

## Current verified checkpoint

On 2026-07-22, main matched origin/main at 0669c606 with green CI. The board showed 87 done, 11 todo, 1 running, 7 blocked, 0 ready, and 0 triage. W2 D5B PostgreSQL deletion custody was the only dependency-safe running lane; its first task committed nine intentional RED characterization tests as e59a0ec before entering production implementation. Operator-gated cards remain closed.

## Related

- [[Mnemosyne — Execution Plan A: The Memory System]]
- [[Mnemosyne — World-Best Memory Platform: Full-Capability, No-Trade-Off Design]]
