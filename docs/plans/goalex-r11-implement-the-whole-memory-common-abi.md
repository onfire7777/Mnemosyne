# Plan: Implement the Whole-Memory Common ABI

## Overview
Work only in `/Users/admin/.codex/worktrees/9697/Mnemosyne` on `codex/goalex-whole-memory-pilot`. Current verified HEAD is `87279bbd09d38fccba9826530e9dc8f08c79102e`, the tree is clean, and the Goal verification passes. Round 10 added `docs/plans/goalex-r10-freeze-the-whole-memory-closed-abi.md` but implemented none of its ABI files.

Implement the dependency-first portion of WMB-P1 from `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`, governed by specification §§0, 4, 6.2, 6.5, 13, and 14. The exact lease for this round is:

- `eval/public/schema/wmbs-0.1-draft.schema.json`
- `eval/public/adapters/whole_memory_reference.py`
- `tests/test_public_whole_memory_reference.py`

Use Python 3.12 standard library only. Reuse canonical JSON conventions from `eval/public/adapters/beam.py` and `eval/public/bundle.py`. Do not call Mnemosyne, execute entrant content, score fixtures, access network/database/models, run benchmarks, or modify result-v1. Do not create result-v2 or modify leaderboard code in this increment; those remain mandatory before any module cell begins. The signed-publication worktree is externally owned and dirty; do not touch it. No independent review findings were supplied.

## Validation Commands
- `set -euo pipefail; test "$(pwd -P)" = "/Users/admin/.codex/worktrees/9697/Mnemosyne"; test "$(git branch --show-current)" = "codex/goalex-whole-memory-pilot"; test -z "$(git status --porcelain)"`
- `git fetch --prune origin && git merge-base --is-ancestor origin/main HEAD`
- `gh pr list --repo onfire7777/Mnemosyne --state open --json number,title,headRefName,headRefOid,mergeStateStatus,reviewDecision,statusCheckRollup`
- `uv run --locked python -m pytest tests/test_public_whole_memory_reference.py -q`
- `uv run --locked ruff check eval/public/adapters/whole_memory_reference.py tests/test_public_whole_memory_reference.py`
- `uv run --locked python -m pytest`
- `git diff --check && test -z "$(git diff --name-only | rg -v '^(eval/public/schema/wmbs-0.1-draft\.schema\.json|eval/public/adapters/whole_memory_reference\.py|tests/test_public_whole_memory_reference\.py)$')"`

### Task 1: Revalidate authority and lease
- [ ] Fetch current `origin/main`, inspect open PRs and worktree changes for the three leased paths, and stop if another live writer owns one. Never consume changes from the benchmark-owner or signed-publication worktrees.
- [ ] Compare specification §§4 and 6.2 with implementation-plan Task 1. Freeze the state machine as negotiate → create_run → ingest/retrieve/answer → finalize; identical idempotent replays do not advance state, conflicting reuse fails `CONFLICT`, non-replay sequence regression fails `ORDER_VIOLATION`, and finalized runs reject further requests.
- [ ] If a controlling source contradicts those semantics or does not permit a deterministic volatile-field projection, stop with `DEFERRED-CONFLICT` and record the exact conflicting passages instead of inventing behavior.

### Task 2: Freeze the contract in failing tests
- [ ] Create golden request and response objects for `negotiate`, `create_run`, `ingest`, `retrieve`, `answer`, and `finalize`, including the closed `ErrorEnvelope` and all nine authorized error codes.
- [ ] Add table-driven rejection tests for missing and extra fields, booleans used as numbers, non-finite numbers, whitespace-only or oversized strings, oversized arrays, malformed digests, non-UTC or stale deadlines, duplicate request IDs, conflicting idempotency keys, sequence regression, invalid operation order, and post-finalize requests.
- [ ] Add complete valid and invalid fixtures for `FeasibilityRecord`, `BaselineManifest`, `PowerPlan`, `SoftwareDataBOM`, `SandboxReceipt`, and `ResourceReceipt`, covering all fourteen feasibility categories and digest-bound cross-references.
- [ ] Freeze canonical JSON mapping-order independence and the M15 volatile-field exclusion/projection with golden byte vectors and SHA-256 expectations.
- [ ] Run the focused test and confirm RED arises only because the schema and adapter implementation are missing.

### Task 3: Implement the minimum fail-closed ABI
- [ ] Add the compound draft-2020-12 schema with protocol ID `wmbs/0.1-draft`, closed enums, explicit bounds, digest formats, and `additionalProperties:false` at every object boundary.
- [ ] Implement a small standard-library validator/canonicalizer that recognizes only the frozen schema definitions, rejects booleans and non-finite JSON values, normalizes only canonical RFC3339 UTC timestamps, and returns stable protocol errors.
- [ ] Implement the minimal in-memory validation state needed for ordering, terminal finalization, request-ID uniqueness, identical idempotent replay, conflicting-key rejection, and deadline enforcement. Add no runner, generic schema framework, persistence, or entrant invocation.
- [ ] Make every golden and rejection fixture pass, then record the schema and golden-vector SHA-256 digests in deterministic test assertions.

### Task 4: Verify and deliver the bounded increment
- [ ] Run the focused test, Ruff, full single-worker test suite, diff check, exact-lease check, risky-file scan, and changed-file secret scan. Confirm no persistent skip or expected failure hides contract behavior.
- [ ] Inspect the complete diff for trust-boundary failures: unbounded input, permissive unknown fields, unsafe timestamps, mutable replay state, swallowed validation errors, network/process access, or evidence-language upgrades.
- [ ] Commit only the three leased paths, push normally, and open a PR against `main`. Require exact-head CI, review decision, review-thread clearance, mergeability, and security findings to clear; never bypass hooks or dismiss findings.
- [ ] After merge, prove clean `origin/main` equality and post-merge CI, refresh CBM once, and leave result-v2/ledger freeze as the next dependency-ready WMB-P1 increment. Do not begin module pilots.
