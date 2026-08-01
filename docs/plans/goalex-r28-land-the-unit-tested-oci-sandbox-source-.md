# Plan: Land the Unit-Tested OCI Sandbox Source Slice

## Overview
Continue WMB-P2 from the existing isolated Worktrunk checkout `/Users/admin/Mnemosyne.codex-goalex-r26-sandbox`, branch `codex/goalex-r26-sandbox`, currently at `d744b2cbbc73ad270cfc5ce075f375f289b6139b`. Canonical `main` and `origin/main` remain `e0dd41594cec890f598718160f919c13eee1e552`.

The lane already contains the five re-admitted sandbox commits. They implement `run_isolated`, subprocess cleanup, output quotas, external metering, and fail-closed network isolation, but explicitly do not execute OCI or enforce mount/resource boundaries. Rounds 25–27 repeatedly planned the full implementation-plus-runtime-evidence workflow without producing an implementation commit. This round must use a different boundary: implement and deliver only the deterministic, unit-testable OCI command/execution contract. Live image resolution, build, SBOM, provenance, daemon probes, and admission receipts remain separate operator gates and must not block this source slice.

The exact source lease is:

- `eval/public/sandbox.py`
- `eval/public/sandbox/Dockerfile`
- `tests/test_public_sandbox.py`

Do not change the Dockerfile’s unresolved base-image placeholder without a live immutable digest. Do not touch GoalEx plans, `.planning/**`, `GOAL.md`, schemas, runners, registries, evidence artifacts, or protected worktrees. Preserve `PROPOSED`, `publishable:false`, and `pbpp_headline_eligible:false`.

## Validation Commands
- `test "$(pwd -P)" = "/Users/admin/Mnemosyne.codex-goalex-r26-sandbox" && test "$(git branch --show-current)" = "codex/goalex-r26-sandbox"`
- `PYTHONPATH=src uv run --extra mcp pytest -q tests/test_public_sandbox.py tests/test_public_whole_memory_reference.py`
- `uv run ruff check eval/public/sandbox.py tests/test_public_sandbox.py`
- `git diff --check origin/main...HEAD`
- `git diff --name-only e0dd41594cec890f598718160f919c13eee1e552...HEAD`
- `git status --porcelain`

### Task 1: Implement the fail-closed OCI execution contract
- [ ] Assert the exact r26 checkout and branch before reading or editing; stop if either differs or if the three leased paths contain uncommitted changes.
- [ ] Add RED unit tests, using a monkeypatched runtime lookup and `subprocess.Popen`, proving the OCI path rejects a missing runtime, a non-digest image reference, nonexistent/non-directory mounts, identical or nested input/output paths, and any request to allow network access before launching a process.
- [ ] Add RED argv tests proving the launched command uses an argument array with `shell=False` and includes the immutable `name@sha256:<64 lowercase hex>` image, non-root user, read-only root, bounded tmpfs, `--network none`, `--cap-drop ALL`, `no-new-privileges`, PID/CPU/memory limits, read-only input mount, writable output mount, and no repository or ambient host-directory mount.
- [ ] Extend the existing sandbox module with one OCI-specific public entry point that reuses `SandboxLimits`, receipt construction, timeout/process-group cleanup, output quota, environment allowlist, and external metering. Do not weaken or silently redirect the existing subprocess entry point, add a dependency, invoke a shell, or provide a non-OCI fallback when OCI execution is requested.
- [ ] Ensure OCI receipts bind the immutable image digest and remain `PROPOSED`. Pre-launch validation failures must raise `SandboxArgumentError`; runtime/setup failures must return a failed receipt without claiming that network, mounts, or limits were established.
- [ ] Run the focused tests and Ruff, review the complete leased diff for path traversal, command injection, secret forwarding, mutable-image, and fail-open behavior, then commit only the sandbox source and test files. Leave the Dockerfile unchanged unless a real digest was independently resolved.

### Task 2: Create an exact-lease delivery branch and submit it
- [ ] Create a fresh Worktrunk delivery branch from current `origin/main`, then cherry-pick the five re-admitted sandbox commits and the new OCI implementation commit only; exclude `c44522ad` and every GoalEx plan/coordinator commit.
- [ ] Run all validation commands in the delivery checkout and prove the diff contains exactly `eval/public/sandbox.py`, `eval/public/sandbox/Dockerfile`, and `tests/test_public_sandbox.py`; perform the secret, risky-file, immutable-image, shell-invocation, and trust-boundary checks.
- [ ] Do not attempt or require a Docker build for this source slice. Record unavailable daemon, registry digest, SBOM, provenance, and live enforcement receipts as operator gates; do not fabricate them or upgrade admission.
- [ ] Push normally and open a PR. Require exact-head CI, CodeRabbit/Greptile findings disposition, zero unresolved review threads, and clear mergeability before normal merge.
- [ ] After merge, require exact post-merge-main CI, fast-forward canonical local `main`, prove it is clean and equals `origin/main`, refresh CBM once, and record one deduplicated source-grounded Gbrain milestone.
