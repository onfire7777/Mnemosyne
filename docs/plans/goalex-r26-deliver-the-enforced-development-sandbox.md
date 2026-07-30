# Plan: Deliver the Enforced Development Sandbox

## Overview
The authoritative repository state is clean at `main == origin/main == e0dd41594cec890f598718160f919c13eee1e552`, where PR #84 delivered M15. The GoalEx branch is clean at `4035cf05` and contains 35 coordinator/documentation commits beyond main; none implements the sandbox.

The clean sandbox handoff is `/Users/admin/Mnemosyne.codex-wmb-sandbox-core@6e523360`, five commits ahead and 80 commits behind current main. Its lease is exactly `eval/public/sandbox.py`, `eval/public/sandbox/Dockerfile`, and `tests/test_public_sandbox.py`. Commits `03adc078`, `85ec141c`, `4a3cb065`, `4e445442`, and `6e523360` provide subprocess isolation, descendant cleanup, output quotas, external metering, and fail-closed network checks, but do not execute OCI or enforce mount/write boundaries.

Execute this increment from a fresh Worktrunk branch based on current `origin/main`. Do not edit the GoalEx branch, stale sandbox worktree, `.planning/**`, shared runner/schema/registry files, or protected benchmark-spec and signed-publication worktrees. Preserve `PROPOSED`, `publishable:false`, and `pbpp_headline_eligible:false`. Docker CLI 29.5.2 is installed, but the verifier could not access its daemon; lack of runtime access blocks enforcement receipts, not unit-tested source work.

## Validation Commands
- `test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)"`
- `git diff --check origin/main...HEAD`
- `PYTHONPATH=src uv run --extra mcp pytest -q tests/test_public_sandbox.py tests/test_public_whole_memory_reference.py`
- `uv run ruff check eval/public/sandbox.py tests/test_public_sandbox.py`
- `diff -u <(git diff --name-only origin/main...HEAD | sort) <(printf '%s\n' eval/public/sandbox.py eval/public/sandbox/Dockerfile tests/test_public_sandbox.py | sort)`
- `git status --porcelain`

### Task 1: Re-admit the sandbox handoff on current main
- [x] Fetch `origin`; verify canonical main is clean and current; refresh open PR, process, worktree, dirty-path, and lease inventories; stop if another writer intersects the three leased paths.
- [x] Refresh CBM for the fresh checkout and inspect sandbox/public-harness impact. If CBM remains unavailable, record that blocker and limit inspection to the three leased files and their imported contracts.
- [x] Create a fresh Worktrunk branch from `origin/main`; do not modify or merge from the stale sandbox worktree.
- [x] Cherry-pick, in order, `03adc078`, `85ec141c`, `4a3cb065`, `4e445442`, and `6e523360`; resolve conflicts only within the exact lease.
- [x] Run the focused sandbox tests before further edits and record any current-main contract drift. No current-main contract drift was observed.

### Task 2: Add the minimum real OCI isolation path
- [ ] Add failing tests for validated `shell=False` container argv containing an immutable image digest, non-root user, read-only root filesystem, bounded tmpfs scratch, `--network none`, dropped capabilities, `no-new-privileges`, PID/CPU/memory limits, read-only fixture mount, and result-only writable persistent mount.
- [ ] Add denial tests for missing runtime, mutable image reference, fixture/output path escape, omitted isolation flags, network access, and writes to the root filesystem or fixture mount. Do not use `/tmp` as a forbidden-write probe because bounded tmpfs scratch is intentionally writable.
- [ ] Reuse the handoff’s `run_isolated`, receipt, cleanup, quota, environment, and external-meter logic. Invoke the installed container CLI with an argument array and no shell; add no dependency, fallback executor, runner, schema, or registry.
- [ ] Keep the Dockerfile base unresolved unless a live registry lookup supplies an immutable digest. Never fabricate an image digest, SBOM, provenance, enforcement receipt, or admission upgrade.
- [ ] Run the focused tests and Ruff until the source candidate is stable.

### Task 3: Verify and submit the bounded source candidate
- [ ] Run all validation commands, inspect the complete diff, and perform risky-file, secret, trust-boundary, supply-chain, and exact-lease checks.
- [ ] If Docker daemon access is available, build the digest-pinned image and run harmless probes proving no network, read-only root and fixture mounts, result-only persistent writes, bounded tmpfs, resource limits, and receipt validation. Otherwise record Docker daemon access as the explicit operator blocker.
- [ ] Commit and push only the three leased files, then open a normal PR. Do not update `GOAL.md`, planning state, shared harness surfaces, evidence receipts, or claim labels.
- [ ] Require exact-head CI, CodeRabbit/Greptile disposition, zero unresolved review threads, and clear mergeability. Merge normally only after those gates pass, then require exact post-merge-main CI.
- [ ] After merge, fast-forward canonical local main, prove it is clean and equals `origin/main`, refresh CBM once, and record one deduplicated Gbrain milestone. Leave measured runs, result-v2, publication, and admission promotion blocked.
