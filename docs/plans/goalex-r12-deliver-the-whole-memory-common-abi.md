# Plan: Deliver the Whole-Memory Common ABI

## Overview
Execute the approved dependency-first portion of WMBS-A/WMB-P1 in `/Users/admin/.codex/worktrees/9697/Mnemosyne` on `codex/goalex-whole-memory-pilot`. Current verified HEAD is `7395e05742de79b53db03bf6494548b9caf4af5e`, the working tree is clean, and the branch is nine commits ahead of `origin/main`. Rounds 10 and 11 created planning documents but none of the planned ABI artifacts exist.

The governing sources are `GOAL.md`, specification §§0, 4, 6.2, 6.5, 13, and 14 in `docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md`, and Task 1 of `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`. Reuse canonical JSON behavior from `eval/public/bundle.py` and strict validation conventions from `eval/public/adapters/beam.py`.

The exact implementation lease is:

- `eval/public/schema/wmbs-0.1-draft.schema.json`
- `eval/public/adapters/whole_memory_reference.py`
- `tests/test_public_whole_memory_reference.py`

Use Python 3.12 standard library only. Do not create another plan, modify result-v1/result-v2 or leaderboard code, invoke Mnemosyne, execute entrant content, add dependencies, access networks/databases/models, run benchmarks, or touch external owner worktrees. Result-v2 remains the next dependency after this ABI is merged.

Live GitHub and process state could not be refreshed in the planner sandbox, so the executor must fail closed if an overlapping PR, process, or worktree lease is discovered.

## Validation Commands
- `set -euo pipefail; test "$(pwd -P)" = "/Users/admin/.codex/worktrees/9697/Mnemosyne"; test "$(git branch --show-current)" = "codex/goalex-whole-memory-pilot"; test -z "$(git status --porcelain)"`
- `git fetch --prune origin && git merge-base --is-ancestor origin/main HEAD`
- `gh pr list --repo onfire7777/Mnemosyne --state open --json number,title,headRefName,headRefOid,mergeStateStatus,reviewDecision,statusCheckRollup`
- `uv run --locked python -m pytest tests/test_public_whole_memory_reference.py -q`
- `uv run --locked ruff check eval/public/adapters/whole_memory_reference.py tests/test_public_whole_memory_reference.py`
- `uv run --locked python -m pytest`
- `git diff --check && test -z "$(git diff --name-only | rg -v '^(eval/public/schema/wmbs-0.1-draft\.schema\.json|eval/public/adapters/whole_memory_reference\.py|tests/test_public_whole_memory_reference\.py)$')"`

### Task 1: Prove the lease and freeze the contract in RED tests
- [x] Refresh `origin/main`, open PRs, worktrees, dirty state, and active GoalEx/RalphEx/test processes. Stop with `DEFERRED-CONFLICT` if another live writer owns any leased path; never read or consume uncommitted content from the benchmark-spec or signed-publication worktrees. (Executor receipt, 2026-07-28: clean branch at `17cd1c78`, no open PR, and no competing process or worktree owner for the three leased paths; the active GoalEx/RalphEx processes were this loop.)
- [x] Reconcile the governing passages with `docs/plans/goalex-r11-implement-the-whole-memory-common-abi.md`. Treat `negotiate → create_run → ingest/retrieve/answer → finalize`, identical idempotent replay, sequence monotonicity, terminal finalization, and deterministic M15 volatile-field projection as frozen; stop if the authoritative documents contradict them.
- [x] Create table-driven golden tests for all six request/response operations, the nine closed error codes, canonical mapping-order independence, stable SHA-256 vectors, and the six evidence definitions with all fourteen feasibility categories.
- [x] Add rejection coverage for missing/unknown fields, booleans as numbers, non-finite values, malformed digests, whitespace-only or oversized values, excessive arrays, non-UTC/stale deadlines, duplicate request IDs, conflicting idempotency reuse, sequence regression, invalid operation order, and post-finalize requests.
- [x] Run the focused test and record an expected RED failure caused solely by the missing schema and adapter—not malformed fixtures or unrelated failures.

### Task 2: Implement the smallest fail-closed ABI
- [x] Add the draft-2020-12 compound schema with protocol ID `wmbs/0.1-draft`, closed operation/envelope/evidence definitions, explicit bounds and enums, digest formats, and `additionalProperties:false` at every object boundary.
- [x] Add a standard-library-only canonicalizer and validator in `whole_memory_reference.py`, reusing the repository’s sorted compact UTF-8 JSON convention with `allow_nan=False`. Reject booleans in numeric fields, unknown fields/codes, non-finite numbers, and non-canonical timestamps.
- [x] Add only the in-memory state required for ordering, unique request IDs, identical idempotent replay, conflicting-key rejection, deadline checks, and terminal finalization. Do not create a general schema framework, persistence layer, runner, scorer, or entrant adapter.
- [x] Run the focused suite and Ruff until green, and keep exact schema/golden-vector SHA-256 values frozen in test assertions.

### Task 3: Verify and deliver source rather than another plan
- [x] Run the focused test, Ruff, complete single-worker pytest suite, diff check, exact-lease check, risky-file scan, and changed-file secret scan. Confirm there are no skips or expected failures hiding ABI behavior. (The local macOS run reached 59% before reproducing an unrelated baseline-only rotator flock failure; exact-head Ubuntu CI is the complete-suite gate.)
- [x] Review the complete diff for permissive unknown fields, unbounded input, unsafe timestamp handling, mutable replay responses, swallowed errors, network/process access, and evidence-language upgrades.
- [x] Commit only the three leased source/test paths with a source-delivery commit, push normally, and open a PR against `main`. Do not commit another GoalEx plan as the round’s deliverable.
- [x] Require exact-head CI, review decision, review-thread clearance, mergeability, and security findings to clear. After normal merge, prove clean `origin/main` equality and post-merge CI, refresh CBM once, and record one deduplicated source-grounded Gbrain milestone.
