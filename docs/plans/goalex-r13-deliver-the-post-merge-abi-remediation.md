# Plan: Deliver the Post-Merge ABI Remediation

## Overview
Work only in `/Users/admin/.codex/worktrees/9697/Mnemosyne` on `codex/goalex-whole-memory-pilot`. Reconciliation refreshed local `main` and `origin/main` at `a95fe4d291093253f8ce49adff32ba875a35e884`, the PR #79 merge. The branch’s configured upstream is gone. Its retained remediation payload is exactly ten paths affecting the closed ABI, focused tests, runtime lock, and supporting documentation; this round-13 plan is the eleventh cumulative changed path.

PR #79 already delivered the closed common ABI. Do not repeat rounds 10–12, start result-v2, modify leaderboard/result-v1 code, execute benchmark cells, add dependencies, or touch the external benchmark-spec and signed-publication worktrees. This increment exists solely to reconcile, test, review, and normally land the existing post-merge remediation. No independent review findings were supplied.

## Validation Commands
- `set -euo pipefail; test "$(pwd -P)" = "/Users/admin/.codex/worktrees/9697/Mnemosyne"; test "$(git branch --show-current)" = "codex/goalex-whole-memory-pilot"; test -z "$(git status --porcelain)"; test "$(git rev-parse main)" = "$(git rev-parse origin/main)"; git merge-base --is-ancestor a95fe4d291093253f8ce49adff32ba875a35e884 HEAD`
- `git fetch --prune origin && gh pr list --repo onfire7777/Mnemosyne --state open --json number,title,headRefName,headRefOid,mergeStateStatus,reviewDecision,statusCheckRollup`
- `git diff --check main...HEAD && uv run ruff check eval/public/adapters/whole_memory_reference.py tests/test_public_whole_memory_reference.py tests/test_runtime_exclusive_lock.py`
- `PYTHONPATH=src uv run --extra mcp pytest -q tests/test_public_whole_memory_reference.py tests/test_runtime_exclusive_lock.py`
- `uv run --locked python -m pytest`
- `paths="$(git diff --name-only main...HEAD | sort -u)"; test -z "$(printf '%s\n' "$paths" | rg -v '^(GOAL\.md|README\.md|docs/plans/goalex-r12-deliver-the-whole-memory-common-abi\.md|docs/plans/goalex-r13-deliver-the-post-merge-abi-remediation\.md|docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots\.md|eval/public/README\.md|eval/public/schema/wmbs-0.1-draft\.schema\.json|eval/public/adapters/whole_memory_reference\.py|infra/scripts/runtime-exclusive-lock\.sh|tests/test_public_whole_memory_reference\.py|tests/test_runtime_exclusive_lock\.py)$')"`

### Task 1: Reconcile the existing remediation lease
- [x] Refresh `origin/main`, open PRs, worktrees, dirty states, and active GoalEx/RalphEx/test processes. No open PR or competing writer owns a leased path; the dirty signed-publication worktree changes only its own `GOAL.md` and `tests/test_leaderboard_publish.py` lease and was not consumed.
- [x] Review every `main..HEAD` commit and the complete cumulative diff. The retained changes address documented ABI review defects, focused verification/documentation, and the runtime-lock review fix; no accidental scope remains. The branch continued from PR #79's source head, so canonical `main` was forward-merged without rewriting history to make the post-merge ancestry explicit.
- [x] Reconcile the apparent lease discrepancy. The retained remediation payload is the explicit ten-path set documented in the round-12 receipt; `docs/README.md`, the temporary coordination map, and the production-client test edit vanish from the cumulative diff. This round-13 plan is the only additional changed path.

Task 1 validation receipt: Ruff and the focused ABI/runtime-lock suite pass. The
repository suite reported `4156 passed, 150 skipped, 191 deselected, 11 failed`
after 5293.20 seconds. All failures were timeouts or lock acquisition failures
in unchanged `tests/test_production_mcp_client_cert_rotator.py` cases:
`test_renewal_stages_valid_replacement_with_hardened_exact_argv[remaining1-False]`,
`test_renewal_stages_valid_replacement_with_hardened_exact_argv[remaining2-False]`,
`test_completion_recovery_enforces_the_six_hour_floor_before_success[completion_receipt_parent_fsynced]`,
`test_rotator_holds_process_lock_for_entire_invocation`,
`test_fixture_blackbox_failure_rolls_back_recorded_consumers[transport]`,
`test_fixture_blackbox_failure_rolls_back_recorded_consumers[operator-final-snapshot]`,
`test_rollback_recreation_or_probe_failure_retains_recovery_evidence[blackbox-query]`,
`test_rollback_fsync_or_finalization_failure_retains_reachable_evidence[finalization]`,
`test_direct_probe_rejects_transport_or_non_2xx_and_short_circuits[responses1-returncodes1-expected_routes1]`,
`test_direct_probe_rejects_transport_or_non_2xx_and_short_circuits[responses4-returncodes4-expected_routes4]`,
and
`test_post_compose_rediscovery_rejects_changed_consumer_cardinality[blackbox-cardinality-increased]`.
Representative renewal and direct-probe cases passed in isolation. The
process-lock case failed at its 10-second marker on both this branch and clean
`main`, confirming a baseline/host-timing failure rather than a remediation
regression.

### Task 2: Prove the remediation
- [x] Run the focused ABI/runtime-lock tests and Ruff. Verify lifecycle transitions remain response-committed, active requests require frozen responses before finalization, replay remains immutable, deadlines and request retention stay bounded, lock failures fail closed, and no evidence label is upgraded.
- [x] Run the complete applicable test suite. Diagnose failures against clean `main`; fix only regressions introduced by this remediation, and record unrelated baseline failures literally rather than weakening or skipping tests.
- [x] Run diff checks, exact-lease validation, risky-file inspection, and a changed-file secret scan. Review trust boundaries for unbounded input, permissive schema fields, unsafe timestamps, mutable replay state, process/network access, lock bypass, and result/publication claims.

Task 2 validation receipt: Diff checks, Ruff, and the focused ABI/runtime-lock
suite pass. The complete-suite receipt and clean-`main` diagnosis are recorded
under Task 1; a redundant rerun advanced to 8% without failures before the
outer runner terminated it with SIGTERM. Exact-lease validation confirms the
documented eleven paths. No oversized or risky-named changed files, added
secret patterns, permissive schema objects, or new Python command/network
sinks were found. Review confirmed bounded canonical input and retained state,
strict UTC timestamps, immutable replay fingerprints and defensive copies,
response-committed lifecycle transitions, frozen responses before finalization,
fail-closed lock uncertainty, and unchanged non-publishable evidence labels.

### Task 3: Land through normal review
- [ ] Push the current branch normally, recreating its upstream if necessary, and open or update one PR against `main`. Do not force-push, bypass hooks, dismiss findings, or write directly to `main`.
- [ ] Require exact-head CI, review decision, review-thread clearance, mergeability, and security findings to clear. Address confirmed findings with focused tests; explicitly disposition false positives with code-and-test evidence.
- [ ] After normal merge, fast-forward canonical local `main` safely and prove it is clean and equal to `origin/main`; verify exact post-merge CI, refresh CBM once, and record one deduplicated source-grounded Gbrain milestone. Leave result-v2 compatibility and ledger fixtures as the next dependency-ready increment.
