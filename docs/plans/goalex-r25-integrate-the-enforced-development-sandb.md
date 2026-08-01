# Plan: Integrate the Enforced Development Sandbox

## Overview
PR #84 merged M15 at `main@e0dd41594cec890f598718160f919c13eee1e552`. The coordinator branch is clean at `61181a83`, containing only post-merge GoalEx documentation. The clean sandbox handoff is `/Users/admin/Mnemosyne.codex-wmb-sandbox-core@6e523360`, based on old `main@a95fe4d2`, with five commits from `03adc078` through `6e523360`. Its exact lease is `eval/public/sandbox.py`, `eval/public/sandbox/Dockerfile`, and `tests/test_public_sandbox.py`.

That handoff provides process cleanup, output quotas, external host metering, and fail-closed network isolation, but its own documentation confirms that it never builds or runs OCI, does not enforce read-only fixture/write-only result mounts, and uses an unresolved base-image digest. Integrate it through a fresh Worktrunk branch from current main, then add the smallest real OCI execution path using the installed container runtime—no new runner, dependency, schema change, planning-file edit, or claim upgrade. Keep admission `PROPOSED` unless an authorized host produces the required digest and enforcement receipt. Do not touch the protected benchmark-spec or signed-publication worktrees.

## Validation Commands
- `test "$(git -C /Users/admin/Mnemosyne rev-parse main)" = "$(git -C /Users/admin/Mnemosyne rev-parse origin/main)"`
- `git -C /Users/admin/Mnemosyne.codex-wmb-sandbox-core status --porcelain`
- `git diff --check origin/main...HEAD`
- `PYTHONPATH=src uv run --extra mcp pytest -q tests/test_public_sandbox.py tests/test_public_whole_memory_reference.py`
- `uv run ruff check eval/public/sandbox.py tests/test_public_sandbox.py`
- `git diff --name-only origin/main...HEAD | diff -u - <(printf '%s\n' eval/public/sandbox.py eval/public/sandbox/Dockerfile tests/test_public_sandbox.py)`
- `git status --porcelain`

### Task 1: Re-admit the sandbox handoff on fresh main
- [ ] Fetch `origin`, verify canonical `main` is clean and equals `origin/main`, inventory open PRs, processes, worktrees, dirty paths, and active leases, and stop if any writer intersects the three-file sandbox lease.
- [ ] Refresh the CBM index for the actual fresh integration checkout and inspect the public-harness architecture and sandbox impact before editing.
- [ ] Create one Worktrunk integration branch from current `main`; do not reuse or modify the stale handoff worktree.
- [ ] Review and cherry-pick only sandbox commits `03adc078`, `85ec141c`, `4a3cb065`, `4e445442`, and `6e523360`, resolving conflicts only inside the exact lease.
- [ ] Run the existing sandbox tests and record any failure caused by current-main contract drift before changing behavior.

### Task 2: Replace the documented OCI profile with enforced isolation
- [ ] Add RED tests proving OCI argv includes an immutable image digest, non-root user, read-only root, tmpfs scratch, `--network none`, dropped capabilities, `no-new-privileges`, PID/CPU/memory limits, read-only input mount, and output-only writable mount.
- [ ] Add denial tests proving execution fails closed when the runtime is missing, the image reference is mutable/unresolved, required isolation flags cannot be established, fixture paths escape their admitted roots, or the child writes outside both explicitly writable locations: the result mount and bounded ephemeral tmpfs scratch. Negative probes must target the read-only root, fixture mount, or another forbidden persistent/host path, never `/tmp`.
- [ ] Reuse `run_isolated` and the installed container CLI through validated argv with `shell=False`; add no dependency, second lifecycle, or in-process fallback for the OCI profile.
- [ ] Replace `UNVERIFIED-RESOLVE-BEFORE-BUILD` only with a live-resolved immutable digest. If registry access or an admitted runtime is unavailable, retain `PROPOSED`, record the exact blocker, and do not fabricate build, SBOM, provenance, or enforcement evidence.
- [ ] Preserve existing timeout, descendant cleanup, output-quota, secret-free environment, canonical receipt, and external-meter behavior.

### Task 3: Verify and deliver the bounded candidate
- [ ] Run the focused sandbox/reference tests, Ruff, `git diff --check`, exact lease check, risky-file and secret sweep, and inspect the complete diff for trust-boundary and supply-chain failures.
- [ ] If an admitted OCI runtime exists, build the digest-pinned image, run the harmless no-network smoke and negative network/write-boundary probes, and validate the resulting receipt; otherwise report the host/runtime gate literally.
- [ ] Commit only the three leased files, push normally, and open a PR without touching `GOAL.md`, `.planning/**`, shared schema/runner/registry files, or protected worktrees.
- [ ] Require exact-head CI, CodeRabbit/Greptile findings disposition, zero unresolved review threads, clear mergeability, normal merge, and exact post-merge-main CI before recording the sandbox source slice as delivered.
- [ ] After merge, fast-forward canonical local main, prove it is clean and equals `origin/main`, refresh CBM once, and leave measured admission, result-v2, publication, and claim labels unchanged.
