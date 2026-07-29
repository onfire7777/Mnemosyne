# Plan: Freeze the Whole-Memory Closed ABI

## Overview
Implement only Task 1 of `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`: the `wmbs/0.1-draft` closed ABI, fail-closed standard-library validator, frozen result-v2 schema, compatibility fixtures, and M15 canonical projection.

Work from `/Users/admin/.codex/worktrees/9697/Mnemosyne` on `codex/goalex-whole-memory-pilot`. The branch is clean at `4e7da149`, based on `main@489e1361`, and already contains the exact owner handoff. Round 9’s prospective-memory work is complete and must not be repeated. The historical overlapping result-contract lease at `5764f6b9` is already an ancestor of `main`; the dirty signed-publication worktree remains externally owned and must not be touched.

The exact implementation lease is limited to:

- `eval/public/schema/wmbs-0.1-draft.schema.json`
- `eval/public/adapters/whole_memory_reference.py`
- `leaderboard/schema/result-v2.schema.json`
- `tests/test_public_whole_memory_reference.py`
- `tests/test_leaderboard_result_contract.py`
- `tests/test_leaderboard_ledger.py`

Reuse existing canonical-JSON, result-v1, and ledger conventions. Add no dependency, runner, scoring path, database call, model call, benchmark execution, publication behavior, or aggregate result. Treat specification §7.3 as a dated cutoff receipt; current `GOAL.md` is the higher-precedence live authority. The latest independent review supplied no findings.

## Validation Commands
- `set -euo pipefail; test "$(pwd -P)" = "/Users/admin/.codex/worktrees/9697/Mnemosyne"; test "$(git branch --show-current)" = "codex/goalex-whole-memory-pilot"; test -z "$(git status --porcelain)"`
- `git fetch --prune origin && git merge-base --is-ancestor origin/main HEAD`
- `gh pr list --repo onfire7777/Mnemosyne --state open --json number,title,headRefName,headRefOid,mergeStateStatus,reviewDecision,statusCheckRollup`
- `PYTHONPATH=src uv run --extra mcp pytest -q tests/test_public_whole_memory_reference.py tests/test_leaderboard_result_contract.py tests/test_leaderboard_ledger.py`
- `uv run ruff check eval/public/adapters/whole_memory_reference.py tests/test_public_whole_memory_reference.py tests/test_leaderboard_result_contract.py tests/test_leaderboard_ledger.py`
- `git diff --check && test -z "$(git diff --name-only | rg -v '^(eval/public/schema/wmbs-0.1-draft\.schema\.json|eval/public/adapters/whole_memory_reference\.py|leaderboard/schema/result-v2\.schema\.json|tests/test_public_whole_memory_reference\.py|tests/test_leaderboard_result_contract\.py|tests/test_leaderboard_ledger\.py)$')"`

### Task 1: Refresh authority and establish the exact lease
- [ ] Fetch current `origin/main`, inspect open PRs/checks and every overlapping worktree, and stop if a live writer owns any leased path. If `origin/main` advanced, merge it normally into this branch only after confirming no contract conflict; never rebase a published branch or force-push.
- [ ] Read the governing specification §§0, 3–7, 9.5, 13, and 16 plus implementation-plan Task 1. Compare them with current result-v1 validation and ledger behavior; stop as `DEFERRED-CONFLICT` if any request, response, digest, or supersession meaning is ambiguous.
- [ ] Run the existing result-contract and ledger tests before editing, and record the result-v1 schema digest plus representative canonical ledger bytes as the compatibility baseline.

### Task 2: Freeze RED contract and compatibility fixtures
- [ ] Create `tests/test_public_whole_memory_reference.py` with golden objects for all six operations, every response/error envelope, all six evidence artifacts, and all fourteen feasibility fields.
- [ ] Cover required and unknown fields, closed enums, bounded strings/arrays, finite numbers, UTC deadlines, sequence monotonicity, duplicate request and idempotency behavior, canonical mapping-order independence, and stale-deadline rejection.
- [ ] Freeze the M15 volatile-field exclusion and canonical projection in golden vectors. Add result-v2 valid/invalid fixtures proving atomic attempts exclude aggregates, official records require complete fidelity pins, successor records require parent/difference manifests, development records remain non-publishable, and certified projections cannot blend official and enhanced tracks.
- [ ] Extend the result-contract and ledger tests with immutable result-v1 snapshots and append-only cross-version fixture semantics, without modifying `leaderboard/validate.py` or `leaderboard/ledger.py`. Run the focused test and confirm RED is caused only by the missing new schema/adapter.

### Task 3: Implement the minimum closed ABI
- [ ] Add the compound `wmbs/0.1-draft` JSON Schema with `additionalProperties:false` at every object boundary, exact operation/envelope definitions, digest formats, evidence cross-references, bounds, and closed enums.
- [ ] Add the minimal standard-library validator and canonicalizer in `whole_memory_reference.py`. Validate protocol shape and stateful request ordering/idempotency only; do not call Mnemosyne, execute entrant content, score data, or perform network/database/model work.
- [ ] Add `result-v2.schema.json` as an additive contract while leaving result-v1 untouched. Close atomic identity, track lineage, admission/evidence labels, division, resource/custody disclosures, safety outcomes, four existing digest meanings, and non-publishable development semantics.
- [ ] Run focused tests and Ruff to green, then record SHA-256 digests for the ABI schema, result-v2 schema, and canonical golden vectors.

### Task 4: Verify and land the bounded increment
- [ ] Run the focused validation commands, planning/config-drift tests, full applicable pytest suite at one worker after the repository hardware preflight, Ruff, diff check, exact-lease check, risky-file scan, and changed-file secret scan. Run no benchmark or protected/operator workload.
- [ ] Inspect the complete diff and verify result-v1 behavior and ledger bytes are unchanged, all invalid fixtures fail closed, and no persistent skip or non-strict expected failure hides unfinished contract behavior.
- [ ] Commit only the six leased paths, push normally, open a PR against `main`, and wait for exact-head CI, review decision, review threads, mergeability, and security findings to clear. Never dismiss findings or bypass hooks.
- [ ] After normal merge, fast-forward the clean canonical `/Users/admin/Mnemosyne` checkout to `origin/main`, prove exact SHA equality and post-merge CI, refresh CBM once, and record one deduplicated source-grounded Gbrain milestone. Do not touch the signed-publication or benchmark-owner worktrees.
