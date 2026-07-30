# Plan: Deliver the Revised M12/M13 Head

## Overview
Work only in `/Users/admin/Mnemosyne.codex-wmb-action-evidence-confirmations` on branch `codex/wmb-action-evidence-confirmations`. The clean local and tracked remote head is now `a3ca8108c22de350810dc3f574931a0d85810ed5`, based directly on canonical `main@392b1fc173f454893e1b133ff3a727462586a8b0`. Its cumulative diff modifies exactly:

- `tests/test_public_pm_bench_triggerbench.py`
- `tests/test_public_working_memory_action_probe.py`

Round 21 targeted stale head `d68f55cd419e159b1ba3296428f102134d8ea49c`. A subsequent bounded remediation commit, `a3ca8108`, corrected the M12 test description so it accurately states that `MnemoCLI.run` is mocked and subprocess transport is not exercised. Do not reset to the old head, repeat integration, change test semantics, or run a repository-wide suite locally. Required exact-head CI is the single authoritative broad candidate suite.

Preserve `admission_state=PROPOSED`, `evidence_level=INTERNALLY_MEASURED`, `publishable:false`, `headline_eligible:false`, `independent_reproduction:false`, and `upstream_comparable:false`. M03 remains blocked on authorized write methods excluded from its lease. Do not begin M03, M15, M20, result-v2, sandbox, registry, adapter, recurrence, promotion-policy, or measured-cell work in this increment.

## Validation Commands
- `test "$(pwd -P)" = "/Users/admin/Mnemosyne.codex-wmb-action-evidence-confirmations" && test "$(git branch --show-current)" = "codex/wmb-action-evidence-confirmations" && test "$(git rev-parse HEAD)" = "a3ca8108c22de350810dc3f574931a0d85810ed5" && test -z "$(git status --porcelain)"`
- `git fetch --prune origin && test "$(git rev-parse origin/codex/wmb-action-evidence-confirmations)" = "a3ca8108c22de350810dc3f574931a0d85810ed5" && test "$(git merge-base main HEAD)" = "$(git rev-parse main)"`
- `test "$(git diff --name-only main...HEAD)" = "$(printf '%s\n' tests/test_public_pm_bench_triggerbench.py tests/test_public_working_memory_action_probe.py)"`
- `uv run pytest -q tests/test_public_pm_bench_triggerbench.py tests/test_public_working_memory_action_probe.py`
- `uv run ruff check tests/test_public_pm_bench_triggerbench.py tests/test_public_working_memory_action_probe.py && git diff --check`
- `gh pr view <PR_NUMBER> --json state,isDraft,headRefOid,baseRefName,mergeable,mergeStateStatus,statusCheckRollup,url`
- `gh pr checks <PR_NUMBER> --required`
- `git fetch --prune origin && test "$(git rev-parse main)" = "$(git rev-parse origin/main)" && git merge-base --is-ancestor a3ca8108c22de350810dc3f574931a0d85810ed5 main`

### Task 1: Re-establish the revised exact-head gate
- [x] Restore GitHub connectivity and open or reuse exactly one PR from `codex/wmb-action-evidence-confirmations` to `main`; verify `headRefOid` is exactly `a3ca8108c22de350810dc3f574931a0d85810ed5`, not round 21’s superseded `d68f55cd`.
- [x] Verify the PR cumulative diff contains only the two leased test files and the latest commit truthfully describes the mocked `MnemoCLI.run` seam without claiming subprocess coverage.
- [x] Run only the two focused test files, focused Ruff, and `git diff --check`; do not duplicate the repository-wide suite locally.
- [x] Inspect all current-head reviews, unresolved threads, security findings, required checks, and mergeability conditions. If GitHub remains unreachable, canonical `main` advanced incompatibly, or remediation needs files outside the lease, stop with the exact blocker.

### Task 2: Merge and prove the revised candidate
- [ ] Require every exact-head check and review gate to finish green for `a3ca8108`; if a confirmed two-file fix changes the SHA, restart exact-head verification against the new SHA.
- [ ] Merge normally without force-push, hook bypass, direct-to-main writes, or loss of reviewed ancestry.
- [ ] Require exact post-merge `main` CI to pass, safely fast-forward clean canonical `/Users/admin/Mnemosyne`, and prove `main == origin/main` and contains `a3ca8108`.
- [ ] Refresh CBM once after merge and record one deduplicated Gbrain milestone plus affected canonical GSD/pilot status using the PR, final candidate SHA, merge SHA, exact-head and exact-merge CI runs, focused-test receipt, and unchanged non-publishable boundaries.
