# Plan: Deliver the Post-Merge ABI Remediation

## Overview
Work only in `/Users/admin/.codex/worktrees/9697/Mnemosyne` on `codex/goalex-whole-memory-pilot`. Current local HEAD is `f2865b509dcb1db473b768d5e524b3ab665ab985`; local `main` and `origin/main` are both `a95fe4d291093253f8ce49adff32ba875a35e884`, the PR #79 merge. The working tree is clean, but the branch’s configured upstream is gone and `main..HEAD` contains 18 remediation commits affecting the closed ABI, focused tests, runtime lock, and supporting documentation.

PR #79 already delivered the closed common ABI. Do not repeat rounds 10–12, start result-v2, modify leaderboard/result-v1 code, execute benchmark cells, add dependencies, or touch the external benchmark-spec and signed-publication worktrees. This increment exists solely to reconcile, test, review, and normally land the existing post-merge remediation. No independent review findings were supplied.

## Validation Commands
- `set -euo pipefail; test "$(pwd -P)" = "/Users/admin/.codex/worktrees/9697/Mnemosyne"; test "$(git branch --show-current)" = "codex/goalex-whole-memory-pilot"; test -z "$(git status --porcelain)"; test "$(git rev-parse main)" = "$(git rev-parse origin/main)"; git merge-base --is-ancestor a95fe4d291093253f8ce49adff32ba875a35e884 HEAD`
- `git fetch --prune origin && gh pr list --repo onfire7777/Mnemosyne --state open --json number,title,headRefName,headRefOid,mergeStateStatus,reviewDecision,statusCheckRollup`
- `git diff --check main...HEAD && uv run ruff check eval/public/adapters/whole_memory_reference.py tests/test_public_whole_memory_reference.py tests/test_runtime_exclusive_lock.py`
- `PYTHONPATH=src uv run --extra mcp pytest -q tests/test_public_whole_memory_reference.py tests/test_runtime_exclusive_lock.py`
- `uv run --locked python -m pytest`
- `paths="$(git diff --name-only main...HEAD | sort -u)"; test -z "$(printf '%s\n' "$paths" | rg -v '^(GOAL\.md|README\.md|docs/README\.md|docs/plans/goalex-r12-deliver-the-whole-memory-common-abi\.md|docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots\.md|eval/public/README\.md|eval/public/schema/wmbs-0.1-draft\.schema\.json|eval/public/adapters/whole_memory_reference\.py|infra/scripts/runtime-exclusive-lock\.sh|tests/test_public_whole_memory_reference\.py|tests/test_runtime_exclusive_lock\.py)$')"`

### Task 1: Reconcile the existing remediation lease
- [ ] Refresh `origin/main`, open PRs, worktrees, dirty states, and active GoalEx/RalphEx/test processes. Stop as `DEFERRED-CONFLICT` if another writer or open PR owns any leased path; do not consume external uncommitted work.
- [ ] Review every `main..HEAD` commit and the complete cumulative diff. Remove accidental scope only through safe forward commits—never reset, rewrite, or discard unowned work—and confirm every retained change addresses a documented ABI review defect or its focused verification/documentation.
- [ ] Reconcile the apparent lease discrepancy: the receipt permits `docs/README.md`, but the current diff instead contains only the ten reported paths; ensure the final changed-path set is explicit and contains no vanished coordination artifact or unrelated work.

### Task 2: Prove the remediation
- [ ] Run the focused ABI/runtime-lock tests and Ruff. Verify lifecycle transitions remain response-committed, active requests require frozen responses before finalization, replay remains immutable, deadlines and request retention stay bounded, lock failures fail closed, and no evidence label is upgraded.
- [ ] Run the complete applicable test suite. Diagnose failures against clean `main`; fix only regressions introduced by this remediation, and record unrelated baseline failures literally rather than weakening or skipping tests.
- [ ] Run diff checks, exact-lease validation, risky-file inspection, and a changed-file secret scan. Review trust boundaries for unbounded input, permissive schema fields, unsafe timestamps, mutable replay state, process/network access, lock bypass, and result/publication claims.

### Task 3: Land through normal review
- [ ] Push the current branch normally, recreating its upstream if necessary, and open or update one PR against `main`. Do not force-push, bypass hooks, dismiss findings, or write directly to `main`.
- [ ] Require exact-head CI, review decision, review-thread clearance, mergeability, and security findings to clear. Address confirmed findings with focused tests; explicitly disposition false positives with code-and-test evidence.
- [ ] After normal merge, fast-forward canonical local `main` safely and prove it is clean and equal to `origin/main`; verify exact post-merge CI, refresh CBM once, and record one deduplicated source-grounded Gbrain milestone. Leave result-v2 compatibility and ledger fixtures as the next dependency-ready increment.
