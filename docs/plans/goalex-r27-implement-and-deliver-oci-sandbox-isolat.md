# Plan: Implement and Deliver OCI Sandbox Isolation

## Overview
Continue the whole-memory pilot’s WMB-P2 sandbox increment without changing program direction. Canonical `main == origin/main == e0dd41594cec890f598718160f919c13eee1e552`, while the clean implementation lane is `/Users/admin/Mnemosyne.codex-goalex-r26-sandbox` on `codex/goalex-r26-sandbox@d744b2cbbc73ad270cfc5ce075f375f289b6139b`. That lane already re-admits the five reviewed sandbox handoff commits and its focused pre-change tests reported no current-main contract drift.

The implementation lease is exactly `eval/public/sandbox.py`, `eval/public/sandbox/Dockerfile`, and `tests/test_public_sandbox.py`. Reuse the existing `run_isolated`, cleanup, output-quota, environment, receipt, and external-meter contracts. Add no dependency, fallback executor, runner, schema, registry, planning-state change, or claim upgrade. Preserve `PROPOSED`, `publishable:false`, and `pbpp_headline_eligible:false`.

The current implementation branch also carries `docs/plans/goalex-r26-deliver-the-enforced-development-sandbox.md` in its ancestry, so it cannot itself satisfy the exact three-file PR lease. Implement and verify there, then create a clean Worktrunk delivery lane from current `origin/main` and cherry-pick only the sandbox source commits. Do not rewrite or destructively alter the existing branch. Docker daemon, registry, immutable-image, SBOM, provenance, and enforcement-receipt gaps are operator gates: report them literally rather than fabricating evidence.

## Validation Commands
- `test "$(pwd -P)" = "/Users/admin/Mnemosyne.codex-goalex-r26-sandbox" && test "$(git branch --show-current)" = "codex/goalex-r26-sandbox"`
- `PYTHONPATH=src uv run --extra mcp pytest -q tests/test_public_sandbox.py tests/test_public_whole_memory_reference.py`
- `uv run ruff check eval/public/sandbox.py tests/test_public_sandbox.py`
- `git diff --check origin/main...HEAD`
- `diff -u <(git diff --name-only origin/main...HEAD | sort) <(printf '%s\n' eval/public/sandbox.py eval/public/sandbox/Dockerfile tests/test_public_sandbox.py | sort)`
- `git status --porcelain`

### Task 1: Implement the minimum enforced OCI execution path
- [ ] Before reading, testing, or editing, assert that the working directory and branch exactly match the existing r26 Worktrunk lane; stop rather than modifying the GoalEx coordinator checkout or stale sandbox handoff.
- [ ] Add failing tests proving validated `shell=False` container argv requires an immutable digest, non-root user, read-only root filesystem, bounded tmpfs scratch, `--network none`, all capabilities dropped, `no-new-privileges`, PID/CPU/memory limits, a read-only fixture mount, and a result-only writable persistent mount.
- [ ] Add denial tests for a missing runtime, mutable image reference, fixture/output path escape, missing isolation flags, network access, and writes to the root filesystem or fixture mount; do not treat `/tmp` as forbidden because bounded tmpfs scratch is intentionally writable.
- [ ] Implement the smallest OCI path by extending the existing sandbox contracts and invoking the installed container CLI with an argument array and no shell. Fail closed instead of falling back to in-process or ordinary subprocess execution when OCI isolation was requested.
- [ ] Preserve timeout, descendant cleanup, stdout/stderr quota, secret-free environment, canonical receipt, and external-meter behavior; keep the Dockerfile base unresolved unless a live registry lookup returns its immutable digest.
- [ ] Run the focused tests and Ruff, inspect the complete three-file source diff for trust-boundary and supply-chain failures, and commit only the leased sandbox files.

### Task 2: Produce and gate an exact-lease delivery candidate
- [ ] Create a fresh Worktrunk delivery branch from current `origin/main`; cherry-pick the five re-admitted sandbox source commits plus the new OCI implementation commit, excluding every GoalEx plan or coordinator commit.
- [ ] Run the validation commands in the clean delivery lane and require the exact-name diff to contain only the three leased sandbox files; perform risky-file, secret, immutable-image, path-boundary, and shell-invocation checks.
- [ ] If an admitted Docker daemon and immutable image are available, build and run harmless probes proving network denial, read-only root and fixture mounts, result-only persistent writes, bounded tmpfs, resource limits, and receipt validation. Otherwise record the exact unavailable gate and leave admission and evidence labels unchanged.
- [ ] Push normally and open a PR. Require exact-head CI, CodeRabbit/Greptile disposition, zero unresolved review threads, and clear mergeability; do not merge or claim delivery without those live gates.
- [ ] After normal merge, require exact post-merge-main CI, fast-forward canonical local `main`, prove it is clean and equals `origin/main`, refresh CBM once, and record one deduplicated source-grounded Gbrain milestone.
