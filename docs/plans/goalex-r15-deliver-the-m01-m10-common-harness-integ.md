# Plan: Deliver the M01/M10 Common-Harness Integration

## Overview
Continue the whole-memory pilot from the existing isolated integration worktree `/Users/admin/Mnemosyne.codex-wmb-pilot-integration` on branch `codex/wmb-pilot-integration`. Canonical `main` and `origin/main` are currently `28805ccf54f99f098a5abc23fe6f1155400d0f22`; the integration head `b6522cc0` is 11 commits ahead and combines the reviewed M01 capture core, M10 deterministic abstention core, and existing public-runner registration.

The leased surface is limited to the 13 files already changed between `main...codex/wmb-pilot-integration`: `eval/public/{README.md,bundle.py,registry.json,runner.py,scoring.py,wmbs_m01.py,wmbs_m10.py}`, `eval/public/adapters/whole_memory_reference.py`, the two development fixtures, and the three focused test files. Preserve `PILOT-READY-DEV`/`PROPOSED`, `publishable:false`, and `pbpp_headline_eligible:false`. Do not touch result-v2, ledger/publication code, M03, sandbox enforcement, external benchmarks, measured claims, or protected owner worktrees.

Previous rounds completed the closed ABI and remediation through PRs #79 and #80. This round must review and deliver the already-developed M01/M10 integration, not recreate either core or repeat ABI work. There are no independent post-round findings to adjudicate.

## Validation Commands
- `test "$(pwd -P)" = "/Users/admin/Mnemosyne.codex-wmb-pilot-integration" && test "$(git branch --show-current)" = "codex/wmb-pilot-integration"`
- `git fetch --prune origin && test "$(git merge-base origin/main HEAD)" = "$(git rev-parse origin/main)"`
- `git diff --name-status origin/main...HEAD`
- `PYTHONPATH=src uv run --extra mcp pytest -q tests/test_public_wmbs_m01.py tests/test_public_wmbs_m10.py tests/test_public_eval.py tests/test_public_whole_memory_reference.py`
- `uv run ruff check eval/public tests/test_public_wmbs_m01.py tests/test_public_wmbs_m10.py tests/test_public_eval.py`
- `PYTHONPATH=src uv run --extra mcp pytest -q`
- `git diff --check origin/main...HEAD`
- `git status --short`

### Task 1: Reconcile the isolated integration lease
- [x] Refresh `origin/main`, confirm the integration branch is based on exact current main, and inspect every changed/untracked file; stop if main advanced incompatibly, the worktree is dirty with unowned changes, or another writer owns any leased file.
- [x] Confirm the diff remains restricted to the 13 M01/M10 common-harness files. Exclude result-v2, ledger/publication, M03, sandbox, CLI metadata widening, and external-owner worktrees.
- [x] Compare the integration against the authoritative plan interfaces: reuse the existing public runner, scorer, bundle lifecycle, registry, and closed ABI without creating a second runner or weakening existing bundle verification.

### Task 2: Review and harden the integrated contracts
- [ ] Trace M01 fixture loading, duplicate handling, capture gating, canonical replay, and score computation end to end; fix only confirmed shared-path defects and retain development-only claims.
- [ ] Trace M10 fixture custody, calibration/scored split separation, deterministic reader behavior, abstention/useful-coverage gates, optional-confidence handling, and baseline disclosures end to end; fix only confirmed defects.
- [ ] Verify runner registration produces independent M01 and M10 manifests, rejects unknown profiles, binds fixture/scorer digests, and cannot mark either suite publishable or PBPP-headline-eligible.
- [ ] Review trust boundaries and failure paths: reject malformed or incomplete fixtures, digest mismatches, split overlap, missing manifest-owned artifacts, non-finite scores, and attempted claim escalation.

### Task 3: Prove the exact integration head
- [ ] Run the focused M01, M10, public-runner, and closed-ABI tests plus Ruff and `git diff --check`; diagnose and fix failures at their shared root cause.
- [ ] Run the applicable full pytest suite without launching official benchmarks, providers, containers, models, or measured pilot cells.
- [ ] Inspect the final diff for accidental generated output, secrets, risky files, dependency/lockfile churn, duplicated lifecycle code, and changes outside the lease.
- [ ] Record exact commands, passing counts, head SHA, development labels, and explicit deferrals; do not convert unit-contract evidence into admitted or measured benchmark evidence.

### Task 4: Deliver through normal review gates
- [ ] Commit only necessary remediation, push normally, and open or update the integration PR targeting `main`; never force-push, bypass hooks, or write directly to main.
- [ ] Require exact-head CI, mergeability, security/review clearance, and zero unresolved exact-head review threads. Fix confirmed findings and rerun affected checks.
- [ ] Merge only after all required exact-head gates are green; otherwise leave the PR open with the precise failing gate and next safe action.
- [ ] After merge, prove clean canonical `main == origin/main`, verify exact-merge CI, refresh CBM once, update only affected canonical GSD/GoalEx status, and leave M03 valid-time integration as the next dependency-ready slice. Do not start it in this round.
