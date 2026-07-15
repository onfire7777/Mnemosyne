# Plan: R2b landing — exact-head CI green, merge PR #15, verify main, reconcile trackers

## Overview

You are landing one finished slice of Mnemosyne v2.0 Phase 12 (Plan 12-04, R2b
capture+rotator shared runtime-exclusive lock) in `/Users/admin/Mnemosyne`. All
implementation and validation work is DONE and pushed. Do NOT re-implement,
refactor, or extend the shipped code, and do NOT start R2c/R2d, R3/R4, live
rotation proof, the external `vault-tls/ca.crt` repair, or any knowledge-index
(Graphify/CBM/gbrain) refresh — those are later slices.

State you inherit:
- Branch `codex/r2b-capture-rotator-lock` is pushed to origin at head
  `43e6cb4b86ae89146cd3bd553bdd4e83676db695`; `origin/main` is `c5cfe03`.
- PR #15 to `main` is OPEN and MERGEABLE:
  https://github.com/onfire7777/Mnemosyne/pull/15 — its body already carries the
  RED→GREEN evidence, test counts, and hardware-admission samples.
- Exact-head CI run `29437230000` (workflow `.github/workflows/ci.yml`) is
  running on `43e6cb4`. As of plan time: Lint (ruff), Postgres integration,
  Provider conformance, and both Native wheels jobs are green; the nightly DST
  soak is skipped (non-gating); "Unit + drift checks" is IN PROGRESS.
- Failure history you must know: the previous head `9cdc665` failed CI in
  exactly the "Unit + drift checks" job (run `29435562246`). Commit `43e6cb4`
  ("feat: isolate rotator body tests from runtime lock wrapper") was pushed as
  the intended fix. If the job fails again, that isolation fix was insufficient.
- Precedent to follow for reconciliation: the R2a slice merged its code PR
  (#13), then landed a separate small `docs(planning)` reconciliation PR (#14,
  branch `codex/r2a-main-reconciliation`, commit "docs(planning): reconcile R2a
  main delivery"). R2b follows the same pattern.
- Trackers: `.planning/STATE.md` "Latest checkpoint (2026-07-15)" says the
  delivery PR body owns the exact-head and post-merge CI receipts; after merge,
  the trackers must be reconciled to the actual merged SHA.
- Authoritative spec: `docs/superpowers/plans/2026-07-13-production-mcp-client-cert-rotation.md`
  (R2 status ~line 342, R2b section ~line 705). Prior round records:
  `docs/plans/goalex-r2-r2b-resume-validate-red-baseline-and-int.md` and
  `docs/plans/goalex-r3-r2b-delivery-regression-cell-tracker-rec.md`.

Hardware admission protocol (before EACH local pytest invocation): take a fresh
host sample — free memory ≥35%, 1-minute load ≤10, zero resident Ollama models
(`ollama ps`), `docker ps` showing only the existing ~20-container infra stack
with no mutation. If a sample fails, wait 300 s and re-sample, up to 3 samples
per attempt; record every sample (values + UTC timestamps). If all 3 fail,
record the block in `.planning/STATE.md`, commit that checkpoint, and stop.

Hard boundaries: never merge red or on a stale head; no force-push; no history
rewrite; no live Docker/Compose/Colima mutation; no certificate issuance or
rotation; no Vault operations; no touching the external secrets directory or
`vault-tls/ca.crt`; no model runs, protected attempts, or publication. §31
rails (39) and §33 classes (7) must stay green and unweakened — if a CI fix
would weaken any validator or rail assertion, stop and record the blocker
instead.

## Validation Commands
- `git diff --check`
- `.venv/bin/ruff check --quiet .`
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_planning_traceability.py tests/test_config_drift.py`
- `gh pr checks 15`
- `gh run list --commit <head-sha> --json databaseId,status,conclusion,workflowName`

### Task 1: Exact-head CI green on PR #15
- [x] Confirm PR #15's head is still `43e6cb4` and check run `29437230000` (`gh run view 29437230000` / `gh pr checks 15`). Poll until it completes; all gating jobs must be green ON THAT EXACT SHA (the "DST / chaos soak (nightly, non-gating)" skip is expected and acceptable). Verified `43e6cb4b86ae89146cd3bd553bdd4e83676db695`: all gating jobs passed; the non-gating DST/chaos soak skipped as expected.
- [x] If "Unit + drift checks" fails again: pull the failing log (`gh run view <run-id> --log-failed`), reproduce locally under a fresh hardware-admission sample with the exact failing pytest selection, and diagnose. The prior failure was in this job and `43e6cb4` isolated rotator body tests from the runtime lock wrapper — look for residual test-environment coupling (shared lock file paths, HOME/TMPDIR assumptions, CI-only process semantics) in `tests/test_runtime_exclusive_lock.py` and `tests/test_production_evidence_preflight.py`. Fix ONLY test isolation/environment issues with a new small conventional commit — never weaken an assertion, validator, or shipped script behavior. Push (no force) and wait for green on the new exact head. Record the root cause. (Not triggered: Unit + drift checks passed.)
- [x] If any other job fails or CI infrastructure blocks (e.g. billing), record the exact run id, job, and error in `.planning/STATE.md` as a named blocker, commit that checkpoint to the branch, and stop this task chain. (Not triggered: all gating jobs completed successfully.)

### Task 2: Merge PR #15 and verify the merged main state
- [x] Only after all gating checks are green on the exact current head: merge PR #15 with a normal merge commit (`gh pr merge 15 --merge`; no squash-rewrite of the accepted history, no force). Record the merge commit SHA. Merged PR #15 normally as `13d15138a431ecbd4ca2a919cbf05b87a7a9004b` after all gates passed on exact head `43e6cb4b86ae89146cd3bd553bdd4e83676db695`.
- [x] `git fetch origin` and verify: the merge commit is on `origin/main`; `git diff <branch-head> origin/main -- infra/scripts/capture-production-evidence.sh infra/scripts/rotate-production-mcp-client-cert.sh tests/test_runtime_exclusive_lock.py tests/test_production_evidence_preflight.py` is empty; the two goalex plan files are present on `origin/main`. Verified `origin/main@13d1513`, an empty four-file diff from `43e6cb4`, and both R2/R3 Goalex plan files in the `origin/main` tree.
- [x] Fast-forward local `main` to the merged SHA, and on `main` run the hygiene gate: `git diff --check`, `.venv/bin/ruff check --quiet .`, and (after a fresh admission sample) `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_planning_traceability.py tests/test_config_drift.py` (expect 34 passed). Local `main` fast-forwarded to `13d1513`; diff and ruff checks passed, the `2026-07-15T18:06:04Z` sample passed at 36% free memory/load1 5.23 with zero Ollama models and the unchanged 20-container infra stack, and 34/34 tests passed.
- [x] Watch the post-merge CI run on `main` for the merge commit (`gh run list --branch main --limit 3`); require all gating jobs green. Record the post-merge run id. Run `29439142225` completed successfully on merge SHA `13d15138a431ecbd4ca2a919cbf05b87a7a9004b`; all gating jobs passed and the non-gating DST/chaos soak skipped as expected.

### Task 3: Tracker reconciliation PR to main (R2a pattern)
- [x] From the merged `main`, create branch `codex/r2b-main-reconciliation`. Update `.planning/STATE.md`: refresh frontmatter `stopped_at`/`last_updated`, update the "Current Position" status line to say R2b is MERGED to `main@<merged-SHA>` via PR #15, and add a "Latest checkpoint" entry naming: merged SHA, PR #15, exact-head CI run id on `43e6cb4` (or the final green head), post-merge main run id, and the still-open items (R2c/R2d, R3/R4, live rotation/no-op proof, separate atomic `vault-tls/ca.crt` repair, candidate-v19 external custody chain, hardware-admitted Graphify/CBM/gbrain refresh; last accepted merge-bound knowledge receipt remains PR #12).
- [x] Update `docs/superpowers/plans/2026-07-13-production-mcp-client-cert-rotation.md`: revise the "R2 status" line (~342), the R2b caller-list notes (~123/~381), and the "### R2b" section (~705) to record R2b as merged on `main@<merged-SHA>` with R2c/R2d and live proof explicitly open. Do not touch any validator or gate command.
- [x] Re-run `git diff --check` and (after a fresh admission sample) the planning traceability tests to prove the tracker edits stay green, then commit both files as one `docs(planning): reconcile R2b main delivery` commit and push the branch (no force). Validation passed after the `2026-07-15T18:22:23Z` sample at 39% free memory/load1 6.04 with zero resident Ollama models and the unchanged 20-container infra stack; Ruff and 34/34 planning/config tests passed.

### Task 4: Land the reconciliation and record final receipts
- [ ] Open one PR to `main` titled "docs(planning): reconcile R2b main delivery" whose body names the R2b merged SHA, PR #15, and both CI run ids. Wait for exact-head CI green on the reconciliation head, then merge normally; never merge red or on a stale head.
- [ ] Verify the reconciliation merge landed on `origin/main`, fast-forward local `main`, and re-run the hygiene gate there (fresh admission sample before pytest).
- [ ] In your final result note record: the R2b merged main SHA, PR #15, exact-head run id(s), post-merge run id, the reconciliation PR number and its merged SHA, and explicit confirmation that no live/protected/public/Vault/`ca.crt` action occurred and no §31/§33 assertion was weakened. Do NOT begin R2c/R2d or any other slice this round.
