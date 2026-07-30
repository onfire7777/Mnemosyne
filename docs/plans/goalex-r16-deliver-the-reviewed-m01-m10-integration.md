# Plan: Deliver the Reviewed M01/M10 Integration

## Overview
Continue only in `/Users/admin/Mnemosyne.codex-wmb-pilot-integration` on branch `codex/wmb-pilot-integration`. Current candidate head is `c9e7884e4263cdeedeaf2fe5b30f9796226082b3`, 12 commits ahead of `origin/main@28805ccf54f99f098a5abc23fe6f1155400d0f22`, with a clean worktree and exactly these 13 leased files: `eval/public/{README.md,bundle.py,registry.json,runner.py,scoring.py,wmbs_m01.py,wmbs_m10.py}`, `eval/public/adapters/whole_memory_reference.py`, two development fixtures, and three focused tests.

Round 15 already completed contract review and focused verification. Two unchanged-head full-suite attempts encountered only out-of-lease certificate-rotator timeouts also reproducible on canonical main; do not repeat another local full suite. Use exact-head GitHub CI as the authoritative uncontended full-suite gate. Preserve `PILOT-READY-DEV`/`PROPOSED`, `publishable:false`, and `pbpp_headline_eligible:false`. Do not touch M03, result-v2, publication/ledger code, sandbox enforcement, external benchmarks, protected worktrees, or measured claims. There are no independent review findings to adjudicate.

## Validation Commands
- `test "$(pwd -P)" = "/Users/admin/Mnemosyne.codex-wmb-pilot-integration" && test "$(git branch --show-current)" = "codex/wmb-pilot-integration" && test "$(git rev-parse HEAD)" = "c9e7884e4263cdeedeaf2fe5b30f9796226082b3"`
- `git fetch --prune origin && test "$(git merge-base origin/main HEAD)" = "$(git rev-parse origin/main)" && test -z "$(git status --porcelain)"`
- `test "$(git diff --name-only origin/main...HEAD | wc -l | tr -d ' ')" = "13" && git diff --check origin/main...HEAD`
- `PYTHONPATH=src uv run --extra mcp pytest -q tests/test_public_wmbs_m01.py tests/test_public_wmbs_m10.py tests/test_public_eval.py tests/test_public_whole_memory_reference.py`
- `uv run ruff check eval/public tests/test_public_wmbs_m01.py tests/test_public_wmbs_m10.py tests/test_public_eval.py`
- `gh pr checks <PR_NUMBER> --required`
- `gh pr view <PR_NUMBER> --json headRefOid,mergeable,mergeStateStatus,reviewDecision,statusCheckRollup`
- `test "$(git -C /Users/admin/Mnemosyne rev-parse main)" = "$(git -C /Users/admin/Mnemosyne rev-parse origin/main)"`

### Task 1: Close the candidate-head delivery gates
- [ ] Inspect `origin/main...c9e7884e` for generated artifacts, credentials or high-entropy secrets, risky files, dependency/lockfile churn, duplicated lifecycle code, and any path outside the 13-file lease; fix only a confirmed in-lease defect and rerun the focused tests, Ruff, and diff check if the head changes.
- [ ] Push the exact candidate normally and open or update one PR targeting `main`; record its number and require `headRefOid` to equal the pushed SHA.
- [ ] Verify all required exact-head checks are green, the PR is mergeable, required review is satisfied, and no unresolved exact-head review or security thread remains. Fix confirmed findings only; if GitHub remains unavailable or any gate is pending/failing, leave the PR open and record the precise blocker.
- [ ] Merge normally only after every exact-head gate clears; never force-push, bypass hooks, dismiss findings, or push directly to `main`.

### Task 2: Prove the merge and advance canonical authority
- [ ] After merge, safely fast-forward `/Users/admin/Mnemosyne` and prove its clean `main` equals `origin/main`, contains `c9e7884e`, and has green exact-merge CI.
- [ ] Refresh the CBM index for `/Users/admin/Mnemosyne` once and verify its indexed revision matches the merged main head; report any unavailable graph tooling literally.
- [ ] Update only affected canonical GSD/GoalEx status and the existing pilot plan with the merged PR, source head, merge head, exact-merge CI run, focused test count, and retained non-publishable labels.
- [ ] Record one deduplicated, source-grounded Gbrain milestone, then identify M03 valid-time integration as the next dependency-ready slice without implementing it in this round.
