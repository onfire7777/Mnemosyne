# Plan: Commit the OCI Sandbox Contract

## Overview
Continue WMB-P2 without changing program direction. This round was admitted from canonical `main@e0dd41594cec890f598718160f919c13eee1e552`; canonical `main` later advanced through PR #85 to `90841427da5e8299048cf86d027c451570e479a6`. Execute exclusively in the Worktrunk `/Users/admin/Mnemosyne.codex-goalex-r26-sandbox` on branch `codex/goalex-r26-sandbox`.

The lane already re-admits the sandbox subprocess, cleanup, output-quota, network-isolation, receipt, and external-meter contracts. It has no OCI implementation yet. Rounds 25–28 produced plans but no source commit because the executor was launched in the GoalEx coordinator checkout; coordinator commit `7c18ea7b` corrected that mechanical launch path. Do not repeat the previous implementation-plus-delivery scope: this increment ends after one tested source commit in the leased lane.

Modify only `eval/public/sandbox.py` and `tests/test_public_sandbox.py`. Leave `eval/public/sandbox/Dockerfile` unchanged because no live immutable base-image digest is available. Add no dependency, schema, runner, registry, planning, evidence, or claim-label change. Preserve `PROPOSED`, `publishable:false`, and `pbpp_headline_eligible:false`. Live Docker builds, daemon probes, SBOM, provenance, enforcement receipts, delivery-branch creation, PR review, and merge are explicitly deferred.

Execution worktree: `/Users/admin/Mnemosyne.codex-goalex-r26-sandbox`

## Validation Commands
- `test "$(pwd -P)" = "/Users/admin/Mnemosyne.codex-goalex-r26-sandbox" && test "$(git branch --show-current)" = "codex/goalex-r26-sandbox"`
- `test -z "$(git status --porcelain)"`
- `PYTHONPATH=src uv run --extra mcp pytest -q tests/test_public_sandbox.py tests/test_public_whole_memory_reference.py`
- `uv run ruff check eval/public/sandbox.py tests/test_public_sandbox.py`
- `git diff --check HEAD^..HEAD`
- `test "$(git diff --name-only HEAD^..HEAD | sort)" = "$(printf '%s\n' eval/public/sandbox.py tests/test_public_sandbox.py | sort)"`

### Task 1: Implement and commit the fail-closed OCI contract
- [x] Before reading or editing, assert the exact execution worktree, branch, clean state, and `d744b2cbbc73ad270cfc5ce075f375f289b6139b` starting head; stop if any assertion fails.
- [x] Read the existing sandbox module and tests, then reuse `SandboxLimits`, receipt creation, timeout/process-group cleanup, output quotas, environment allowlisting, and external metering instead of creating parallel machinery.
- [x] Add RED tests using monkeypatched runtime discovery and `subprocess.Popen` that reject a missing runtime, non-digest image, nonexistent or non-directory mounts, identical or nested input/output mounts, path escape, and any network-enabled request before process launch.
- [x] Add RED tests proving OCI execution uses an argument array with `shell=False` and includes `name@sha256:<64 lowercase hex>`, non-root user, read-only root, bounded tmpfs, `--network none`, `--cap-drop ALL`, `no-new-privileges`, PID/CPU/memory limits, a read-only fixture mount, and a writable result mount without ambient repository mounts.
- [x] Implement one minimal OCI-specific public entry point. Pre-launch validation must raise `SandboxArgumentError`; missing runtime or setup/execution failure must fail closed and must not claim that isolation was established. Never fall back to ordinary subprocess or in-process execution.
- [x] Bind the immutable image digest into the canonical receipt while preserving `PROPOSED`; do not manufacture build, SBOM, provenance, daemon, mount-enforcement, or network-enforcement evidence.
- [ ] Run the focused tests and Ruff, inspect the complete diff for command injection, path traversal, secret forwarding, mutable-image acceptance, unsafe mount overlap, and fail-open behavior, then commit exactly the two leased files with repository-style commit message `feat(sandbox): add fail-closed OCI execution contract`.
- [ ] Re-run the validation commands against the new commit and stop with the exact failing evidence if the commit, tests, lint, clean state, or two-file lease check is not proven.

Round 29 stopped before these final two checks: review repair produced a scoped
source/test commit, but the combined reference validation was still running and
three shared documentation files remained intentionally uncommitted for the
integration owner.
