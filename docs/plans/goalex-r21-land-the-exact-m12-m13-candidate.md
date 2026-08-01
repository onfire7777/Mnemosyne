# Plan: Land the Exact M12/M13 Candidate

## Overview
Work only in `/Users/admin/Mnemosyne.codex-wmb-action-evidence-confirmations` on branch `codex/wmb-action-evidence-confirmations`. The clean local and remote candidate is `d68f55cd419e159b1ba3296428f102134d8ea49c`, based directly on canonical `main@392b1fc173f454893e1b133ff3a727462586a8b0`. Its cumulative diff adds exactly `tests/test_public_pm_bench_triggerbench.py` and `tests/test_public_working_memory_action_probe.py`.

Rounds 19–20 completed integration and corrected the delivery contract so required exact-head CI is the single authoritative broad candidate suite. Do not repeat integration, change test semantics, or run another repository-wide suite locally. Preserve `admission_state=PROPOSED`, `evidence_level=INTERNALLY_MEASURED`, `publishable:false`, `headline_eligible:false`, `independent_reproduction:false`, and `upstream_comparable:false`.

M03 remains blocked on excluded authorized write methods in `src/mnemosyne/mcp_tools.py`. Do not begin M03, M15, M20, result-v2, sandbox, registry, adapter, fixture, recurrence, promotion-policy, or measured-cell work during this increment. No independent post-round findings require adjudication.

## Validation Commands
- `test "$(pwd -P)" = "/Users/admin/Mnemosyne.codex-wmb-action-evidence-confirmations" && test "$(git branch --show-current)" = "codex/wmb-action-evidence-confirmations" && test "$(git rev-parse HEAD)" = "d68f55cd419e159b1ba3296428f102134d8ea49c" && test -z "$(git status --porcelain)"`
- `git fetch --prune origin && test "$(git rev-parse origin/codex/wmb-action-evidence-confirmations)" = "d68f55cd419e159b1ba3296428f102134d8ea49c" && test "$(git merge-base main HEAD)" = "$(git rev-parse main)"`
- `test "$(git diff --name-only main...HEAD)" = "$(printf '%s\n' tests/test_public_pm_bench_triggerbench.py tests/test_public_working_memory_action_probe.py)"`
- `gh pr view <PR_NUMBER> --json state,isDraft,headRefOid,baseRefName,mergeable,mergeStateStatus,statusCheckRollup,url`
- `gh pr checks <PR_NUMBER> --required`
- `git fetch --prune origin && test "$(git rev-parse main)" = "$(git rev-parse origin/main)" && git merge-base --is-ancestor d68f55cd419e159b1ba3296428f102134d8ea49c main`

### Task 1: Establish the live delivery gate
- [ ] Restore GitHub connectivity, then open or reuse exactly one PR from `codex/wmb-action-evidence-confirmations` to `main`; verify its `headRefOid` is exactly `d68f55cd419e159b1ba3296428f102134d8ea49c`.
- [ ] Confirm the PR diff contains only the two leased test files and that no unresolved current-head review thread, security finding, required check, or mergeability condition is hidden or pending.
- [ ] If GitHub remains unreachable, the PR head differs, canonical `main` advanced incompatibly, or remediation requires files outside the lease, stop and report the exact blocker instead of widening or rebuilding the candidate.

### Task 2: Merge and record exact evidence
- [ ] Require all exact-head CI, Ruff, required checks, reviews, security findings, current-head threads, and mergeability gates to finish green; make only confirmed two-file fixes, creating a new exact candidate receipt if the SHA changes.
- [ ] Merge normally without force-push, hook bypass, direct-to-main writes, or loss of reviewed ancestry.
- [ ] Require exact post-merge `main` CI to pass, safely fast-forward clean canonical `/Users/admin/Mnemosyne`, and prove `main == origin/main` and contains the delivered candidate.
- [ ] Refresh CBM once after merge and record one deduplicated Gbrain milestone plus the affected canonical GSD/pilot status using the PR number, final candidate SHA, merge SHA, exact-head and exact-merge CI runs, focused-test receipt, and unchanged non-publishable boundaries.
