# Plan: Verify and Deliver M12/M13 Confirmations

## Overview
Work only in `/Users/admin/Mnemosyne.codex-wmb-action-evidence-confirmations` on branch `codex/wmb-action-evidence-confirmations`. The clean candidate is `d68f55cd419e159b1ba3296428f102134d8ea49c`, based directly on canonical `main@392b1fc173f454893e1b133ff3a727462586a8b0`, with four commits modifying exactly:

- `tests/test_public_pm_bench_triggerbench.py`
- `tests/test_public_working_memory_action_probe.py`

Round 19 already established the lease and integrated the reviewed M12/M13 satellite changes. Do not repeat integration, alter test semantics, or begin M03, M15, M20, result-v2, sandbox, registry, adapter, fixture, recurrence, promotion-policy, or measured-cell work.

Preserve `admission_state=PROPOSED`, `evidence_level=INTERNALLY_MEASURED`, `publishable:false`, `headline_eligible:false`, `independent_reproduction:false`, and `upstream_comparable:false`. No independent review findings were supplied. GitHub was unreachable during round-20 planning; retry live access, but do not infer CI, review, mergeability, or PR state from local Git data.

## Validation Commands
- `test "$(pwd -P)" = "/Users/admin/Mnemosyne.codex-wmb-action-evidence-confirmations" && test "$(git branch --show-current)" = "codex/wmb-action-evidence-confirmations" && test "$(git rev-parse HEAD)" = "d68f55cd419e159b1ba3296428f102134d8ea49c" && test -z "$(git status --porcelain)"`
- `git fetch --prune origin && test "$(git rev-parse main)" = "$(git rev-parse origin/main)" && test "$(git merge-base main HEAD)" = "$(git rev-parse main)"`
- `test "$(git diff --name-only main...HEAD)" = "$(printf '%s\n' tests/test_public_pm_bench_triggerbench.py tests/test_public_working_memory_action_probe.py)"`
- `uv run pytest -q tests/test_public_pm_bench_triggerbench.py tests/test_public_working_memory_action_probe.py`
- `uv run ruff check tests/test_public_pm_bench_triggerbench.py tests/test_public_working_memory_action_probe.py`
- `git diff --check`
- `gh pr checks <PR_NUMBER> --required`
- `git fetch --prune origin && test "$(git rev-parse main)" = "$(git rev-parse origin/main)" && git merge-base --is-ancestor d68f55cd419e159b1ba3296428f102134d8ea49c main`

### Task 1: Prove the exact candidate
- [ ] Reconfirm the clean candidate SHA, exact two-file lease, canonical-main base, and absence of generated files, risky files, secrets, dependency churn, executable payloads, production behavior, or unrelated changes.
- [ ] Use the fresh 46-test focused receipt, Ruff, `git diff --check`, staged Gitleaks, and independent approval on exact candidate content; inspect assertions for honest M12 regularity/late-event/schema-defined-cost-gap disclosures and M13 single-seed/no-capacity-or-promotion-utility-claim limitations.
- [ ] Do not duplicate the repository-wide suite locally. The one authoritative broad suite for candidate `d68f55cd` is required exact-head CI; fail closed if it cannot run or does not pass.
- [ ] Record candidate `d68f55cd419e159b1ba3296428f102134d8ea49c` and prove its cumulative diff represents the reviewed M12 and M13 satellite content without upgrading any evidence or publication label.

### Task 2: Land through exact-head gates
- [ ] Push `codex/wmb-action-evidence-confirmations` normally and open or reuse one PR against `main`; verify its `headRefOid` exactly equals `d68f55cd419e159b1ba3296428f102134d8ea49c`.
- [ ] Require all exact-head tests, Ruff, review findings, security findings, unresolved-current-thread checks, and mergeability gates to finish green. Fix only confirmed issues within the two-file lease; if GitHub remains unavailable or a fix needs wider scope, stop and report the precise blocker.
- [ ] Merge normally only after every exact-head gate clears. Never force-push, bypass hooks, dismiss findings, squash away required reviewed ancestry, or push directly to `main`.
- [ ] Verify exact-merge CI succeeds, safely fast-forward clean canonical `/Users/admin/Mnemosyne` so `main == origin/main`, and prove the merged main contains candidate `d68f55cd`.
- [ ] Refresh CBM once after merge, then record one deduplicated durable Gbrain milestone and update only affected canonical GSD/pilot status with the PR, candidate SHA, merge SHA, exact-head and exact-merge CI runs, test evidence, and unchanged non-publishable boundaries.
