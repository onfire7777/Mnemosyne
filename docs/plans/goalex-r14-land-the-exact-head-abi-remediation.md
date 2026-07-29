# Plan: Land the Exact-Head ABI Remediation

## Overview

Work only in `/Users/admin/.codex/worktrees/9697/Mnemosyne` on `codex/goalex-whole-memory-pilot`. PR #79 already merged the closed ABI at `main@a95fe4d291093253f8ce49adff32ba875a35e884`. Rounds 12–13 and subsequent review commits produced the bounded post-merge remediation now ending at `eb1e15be6b35b41f64b6b9b0b76663218b5313fb`.

Do not start result-v2, execute benchmark cells, alter result-v1/leaderboard behavior, consume external worktrees, add dependencies, or rewrite branch history. At plan creation, the current checkout was clean and its remote branch pointed to the same head, but live GitHub state could not be queried because `api.github.com` was unreachable. Reconcile the PR and exact-head gates live, address only confirmed remediation findings, then merge normally and prove post-merge `main`. No independent post-round findings were supplied.

## Validation Commands

- `set -euo pipefail; test "$(pwd -P)" = "/Users/admin/.codex/worktrees/9697/Mnemosyne"; test "$(git branch --show-current)" = "codex/goalex-whole-memory-pilot"; test -z "$(git status --porcelain)"; git fetch --prune origin; test "$(git rev-parse HEAD)" = "$(git rev-parse origin/codex/goalex-whole-memory-pilot)"; git merge-base --is-ancestor a95fe4d291093253f8ce49adff32ba875a35e884 HEAD`
- `gh pr list --repo onfire7777/Mnemosyne --state open --head codex/goalex-whole-memory-pilot --json number,url,headRefOid,mergeStateStatus,reviewDecision,statusCheckRollup`
- `git diff --check origin/main...HEAD && uv run ruff check eval/public/adapters/whole_memory_reference.py tests/test_public_whole_memory_reference.py tests/test_runtime_exclusive_lock.py`
- `PYTHONPATH=src uv run --extra mcp pytest -q tests/test_public_whole_memory_reference.py tests/test_runtime_exclusive_lock.py`
- `uv run --locked python -m pytest`
- `git diff --name-only origin/main...HEAD | rg -v '^(GOAL\.md|README\.md|docs/plans/goalex-r12-deliver-the-whole-memory-common-abi\.md|docs/plans/goalex-r13-deliver-the-post-merge-abi-remediation\.md|docs/plans/goalex-r14-land-the-exact-head-abi-remediation\.md|docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots\.md|eval/public/README\.md|eval/public/schema/wmbs-0\.1-draft\.schema\.json|eval/public/adapters/whole_memory_reference\.py|infra/scripts/runtime-exclusive-lock\.sh|tests/test_public_whole_memory_reference\.py|tests/test_runtime_exclusive_lock\.py)$' | test "$(wc -l | tr -d ' ')" = 0`

### Task 1: Reconcile the immutable delivery head

- [x] Fetch current refs and inspect the branch PR, checks, reviews, unresolved threads, mergeability, worktrees, dirty states, and active GoalEx/RalphEx/test processes. Stop on an overlapping writer or unexpected path.
- [x] Pin delivery to the current remote head SHA. If GitHub reports a different PR head, reconcile by normal push or by inspecting the newer remote content; never force-push, rebase the published branch, or widen the lease silently.
- [x] Create one PR against `main` only if none exists. Otherwise update the existing PR description with the exact lease, focused/full verification receipts, unchanged result-v1 boundary, and explicit result-v2 deferral.

Task 1 receipt: refs were fetched and PR #80 matched the published remediation
head `eb1e15be6b35b41f64b6b9b0b76663218b5313fb`. The PR targets `main`, is
mergeable, has no unresolved review threads, and the latest CodeRabbit review
approved that exact head. These GitHub facts were captured live during Task 1
on 2026-07-29 after API access recovered; its temporary blocked state was the
still-running unit check. Every registered worktree and active
GoalEx/RalphEx/test process was inspected. Active benchmark and
signed-publication writers use disjoint worktrees and paths, so no overlapping
writer or unexpected lease path was found. The existing PR description was
refreshed after the normal task commit and push to identify the new immutable
head, the exact twelve-path lease, the focused and full-suite receipts, the
unchanged result-v1 boundary, and the explicit result-v2 deferral.

### Task 2: Clear exact-head gates

- [x] Run diff hygiene, exact-lease validation, focused Ruff/tests, the applicable full suite, risky-file inspection, and a changed-file secret scan on the exact pushed SHA.
- [x] Inspect every current review, security, CI, and unresolved-thread finding. Reproduce confirmed findings before making the smallest root-cause fix with a focused regression test; dismiss false positives only with code-and-test evidence.
- [x] Push any fixes normally, capture the new immutable head SHA, and restart the gate check. Do not merge until all required checks have completed successfully for that exact SHA and review/thread/mergeability gates are clear.

### Task 3: Merge and prove post-merge state

- [x] Merge the cleared PR normally without bypassing protections, then identify the resulting merge SHA and verify the remediation head is its ancestor.
- [x] Safely fast-forward the clean canonical `/Users/admin/Mnemosyne` checkout, proving local `main` equals clean `origin/main`. Do not touch the benchmark-spec or signed-publication worktrees.
- [x] Require the post-merge CI run on the exact merge SHA to finish green. Refresh CBM once and record one deduplicated, source-grounded Gbrain milestone.
- [x] Reassess the authoritative pilot plan only after this proof. If no new blocker or lease exists, leave result-v2 compatibility and ledger support as the next dependency-ready increment without implementing it in this round.

Task 3 receipt: PR #80 merged normally as
`28805ccf54f99f098a5abc23fe6f1155400d0f22`; remediation head
`0d42f9436397a04e12ceaa3bdbd60d925e2640e9` is its ancestor. Canonical
`/Users/admin/Mnemosyne` was cleanly fast-forwarded so local `main` equals
`origin/main` at the merge SHA, without touching the benchmark-spec or
signed-publication worktrees. Exact-merge CI run `30484986865` completed green
across all required jobs. CBM was refreshed once after proof, and Gbrain
milestone `milestones/whole-memory-abi-remediation-merged` was recorded after a
deduplication search. Reassessment found no new blocker or overlapping lease;
result-v2 compatibility fixtures and local ledger support remain the next
dependency-ready increment, and neither was implemented in this round.
