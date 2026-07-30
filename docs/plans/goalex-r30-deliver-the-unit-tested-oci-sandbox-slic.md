# Plan: Deliver the Unit-Tested OCI Sandbox Slice

## Overview
Canonical `main == origin/main == 90841427da5e8299048cf86d027c451570e479a6` after PR #85. The sandbox source is absent from main. Round 29 produced two OCI commits, `7d9fa768` and review repair `2177eba1`, atop five re-admitted sandbox commits. The source lane `/Users/admin/Mnemosyne.codex-goalex-r26-sandbox` is now dirty in `README.md`, `eval/public/README.md`, and `docs/plans/goalex-r26-deliver-the-enforced-development-sandbox.md`; preserve those files untouched.

Use the clean, finished PR #85 Worktrunk below. Its tree equals current main. Create a new delivery branch there from `origin/main`, then cherry-pick only `fece293d`, `97c838d1`, `c51be44a`, `ee4a4363`, `8feca9e6`, `7d9fa768`, and `2177eba1`. Do not cherry-pick GoalEx plan commits or `d744b2cb`. The exact lease is `eval/public/sandbox.py`, `eval/public/sandbox/Dockerfile`, and `tests/test_public_sandbox.py`. Preserve `PROPOSED`, non-publishable status, and all daemon, immutable-base-image, SBOM, provenance, measured-receipt, and publication gates.

Execution worktree: `/Users/admin/Mnemosyne.codex-planning-wave-13-15-contracts`

## Validation Commands
- `test "$(pwd -P)" = "/Users/admin/Mnemosyne.codex-planning-wave-13-15-contracts"`
- `test -z "$(git status --porcelain)"`
- `test "$(git rev-parse origin/main)" = "90841427da5e8299048cf86d027c451570e479a6"`
- `PYTHONPATH=src uv run --extra mcp pytest -q tests/test_public_sandbox.py tests/test_public_whole_memory_reference.py`
- `uv run ruff check eval/public/sandbox.py tests/test_public_sandbox.py`
- `git diff --check origin/main...HEAD`
- `test "$(git diff --name-only origin/main...HEAD | sort)" = "$(printf '%s\n' eval/public/sandbox.py eval/public/sandbox/Dockerfile tests/test_public_sandbox.py | sort)"`
- `test -z "$(git status --porcelain)"`

### Task 1: Build the exact-lease delivery candidate
- [ ] Assert the execution worktree is clean and its current tree equals `origin/main`; stop if either condition fails or another live writer intersects the three leased paths.
- [ ] Create branch `codex/wmb-sandbox-oci-delivery` from `origin/main`.
- [ ] Cherry-pick, in order, `fece293d`, `97c838d1`, `c51be44a`, `ee4a4363`, `8feca9e6`, `7d9fa768`, and `2177eba1`; resolve conflicts only within the exact three-file lease.
- [ ] Run the focused tests, Ruff, diff check, exact-lease check, and inspect the complete diff for shell injection, mount traversal/overlap, secret forwarding, mutable-image acceptance, cleanup failure, metering failure, and fail-open behavior.
- [ ] Confirm the original r26 sandbox lane still contains its three uncommitted documentation changes unchanged.

### Task 2: Submit and gate the sandbox source
- [ ] Push the delivery branch normally and open a PR describing this as unit-tested development sandbox source only.
- [ ] Require exact-head CI, clear mergeability, resolved review threads, and disposition of CodeRabbit, Greptile, and security findings; do not waive failures or claim runtime enforcement evidence.
- [ ] Merge normally only after all required exact-head gates pass, then require exact post-merge-main CI.
- [ ] Fast-forward canonical local main, prove it is clean and equals `origin/main`, refresh CBM once, and record one deduplicated source-grounded milestone.
- [ ] Leave Docker build/probes, immutable base resolution, SBOM, provenance, measured enforcement receipts, result-v2, admission promotion, and publication explicitly blocked.
