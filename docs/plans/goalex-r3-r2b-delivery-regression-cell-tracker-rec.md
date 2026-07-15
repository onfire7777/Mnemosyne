# Plan: R2b delivery — regression cell, tracker reconciliation, PR, exact-head CI, merge

## Overview

You are completing the delivery of one finished slice of Mnemosyne v2.0 Phase 12
(Plan 12-04, R2b caller lock integration) in `/Users/admin/Mnemosyne`. The
implementation work is DONE and committed; your job is validation, tracker
reconciliation, and the push→PR→CI→merge→verify chain. Do NOT re-implement,
refactor, or extend the shipped code, and do NOT start R2c/R2d, R3/R4, live
rotation proof, the external `vault-tls/ca.crt` repair, or any knowledge-index
refresh — those are later slices.

State you inherit:
- Branch `codex/r2b-capture-rotator-lock` is checked out, clean, at `61f1e1b`,
  exactly 4 commits ahead of `origin/main@c5cfe03` (never pushed):
  `b6074c9` (validated RED baseline), `7f47389` (capture acquires the shared
  runtime-exclusive lock via `infra/scripts/runtime-exclusive-lock.sh` before
  any side effect), `c17a561` (rotator acquires it and revalidates after
  acquisition, keeping its local `.mcp-client-rotation.lock`), `61f1e1b`
  (contention/release/no-detach contract tests). Net diff: 2 scripts, 2 test
  files, plus `docs/plans/goalex-r2-r2b-resume-validate-red-baseline-and-int.md`
  which records per-task evidence including every hardware-admission sample.
  KEEP that plan file in the PR — it is the round's execution-evidence record
  and future loop rounds read it; do not delete it and do not rewrite branch
  history (the commits are accepted as-is).
- The authoritative spec is
  `docs/superpowers/plans/2026-07-13-production-mcp-client-cert-rotation.md`
  (see "R2 status" ~line 342, R2b-integration list ~line 381, and "### R2b —
  Capture and rotator integration" ~line 705). `.planning/STATE.md` currently
  has NO R2b checkpoint — its latest entries still say "R2b–R2d remain open".
- Prior evidence (recorded in the plan file above): RED tests failed at the
  intended first-side-effect assertion; the full focused selection now passes
  93 tests; Ruff check/format, `bash -n`, ShellCheck, `git diff --check`, and
  all 34 planning/config tests were green on the final head.

Hardware admission protocol (before EACH pytest invocation): take a fresh host
sample — free memory ≥35%, 1-minute load ≤10, zero resident Ollama models
(`ollama ps`), `docker ps` showing only the existing ~20-container infra stack
with no mutation. If a sample fails, wait 300 s and re-sample, up to 3 samples
per attempt; record every sample (values + UTC timestamps). If all 3 fail,
record the block in `.planning/STATE.md`, commit that checkpoint, and stop.

Hard boundaries: no live Docker/Compose/Colima mutation, no real certificate
issuance/rotation, no Vault operations, no touching the external secrets
directory or `vault-tls/ca.crt`, no model runs, no protected attempts, no
publication, no force-push, no history rewrite of the four delivery commits.
Never merge red or on a stale head. §31 rails (39) and §33 classes (7) must
stay green and unweakened.

## Validation Commands
- `git diff --check`
- `.venv/bin/ruff check --quiet .`
- `.venv/bin/ruff format --check tests/test_runtime_exclusive_lock.py tests/test_production_evidence_preflight.py`
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_planning_traceability.py tests/test_config_drift.py`
- `bash -n infra/scripts/capture-production-evidence.sh infra/scripts/rotate-production-mcp-client-cert.sh`
- `shellcheck infra/scripts/capture-production-evidence.sh infra/scripts/rotate-production-mcp-client-cert.sh`
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_runtime_exclusive_lock.py tests/test_production_evidence_preflight.py -k 'capture or rotator or runtime_lock'`

### Task 1: Head confirmation and full regression cell
- [x] Confirm a clean tree and head `61f1e1b`; `git fetch origin` and confirm `origin/main` is still `c5cfe03`. If main moved, rebase this never-pushed branch onto the new `origin/main` (this is not a shared-history rewrite), resolve conflicts minimally, and treat the rebased head as the delivery head for everything below.
- [x] Under the retry-gated admission (fresh sample per pytest run, all samples recorded), run every Validation Command above and confirm exit 0, including the full focused selection (expect ~93 passed).
- [x] In the same admitted window, re-run the §31 invariant-rail and §33 test-class selections exactly as the R2a delivery ran them (the invocations are recorded in the R2a checkpoint material in `.planning/STATE.md` and the gate-command blocks of `docs/superpowers/plans/2026-07-13-production-mcp-client-cert-rotation.md`; rails live in files such as `tests/test_parity_learning.py` and `tests/test_learning_and_attack_suite.py`, the §33 harness in `tests/test_g0_harness.py`). Require 39/39 and 7/7 green with no assertion weakened.
- [x] Inspect the complete `git diff main...HEAD` and run a secret/risky-file sweep over every changed file (no keys, tokens, DSNs, external secret paths, or unexpected binary/dotfiles). Record the results; do not push if anything fails.

Task 1 evidence (2026-07-15): the clean live delivery head was `677b579`
because the round-3 plan commit follows the accepted four delivery commits;
`origin/main` remained `c5cfe03`, so no rebase was needed. Static validation
passed: `git diff --check`, Ruff check/format, `bash -n`, and ShellCheck. Fresh
admission samples passed at `17:03:49Z` (44% free, load1 6.17), `17:03:50Z`
(44%, 6.17), `17:04:58Z` (43%, 4.38), and `17:05:00Z` (44%, 4.27), each
with zero resident Ollama models and the unchanged 20-container `infra` stack.
Planning/config passed 34 tests, §31 passed 39/39, and §33 passed 7/7. The
first 93-test focused run had one isolated rotator SIGINT cleanup timeout; the
exact node passed after a fresh `17:05:15Z` admission (43%, 3.69), and the
complete 93-test selection passed after a fresh `17:05:16Z` admission (44%,
3.69), again with zero models and the same stack. Full `main...HEAD` review
found only the intended two scripts, two test files, and two plan records.
Changed-file type/name scans found no binary, dotfile, credential file, key,
token, credential-bearing DSN, or external secret content; the only
`vault-tls/ca.crt` additions are explicit non-action boundary notes. Gitleaks
scanned all five branch commits and reported no leaks.

### Task 2: Tracker reconciliation committed on the branch
- [ ] Update `.planning/STATE.md`: refresh the frontmatter `stopped_at`/`last_updated`, update the "Current Position" status line, and add a new "Latest checkpoint (2026-07-15)" stating R2b capture+rotator shared-lock integration is implemented and proven on this branch (name the evidence: validated RED baseline, 93-test focused selection, §31 39/39, §33 7/7, planning/config 34/34, ShellCheck/`bash -n`/Ruff green, all hardware-admission samples with values, and the plan file `docs/plans/goalex-r2-r2b-resume-validate-red-baseline-and-int.md` as the per-task record). Follow the R2a pattern: state that the PR body owns the exact-head and post-merge CI receipt, and list explicitly open items — R2c/R2d, R3/R4, live rotation/no-op proof, the separate `vault-tls/ca.crt` atomic repair, candidate-v19 external custody chain, and the hardware-admitted Graphify/CBM/gbrain refresh.
- [ ] Update `docs/superpowers/plans/2026-07-13-production-mcp-client-cert-rotation.md`: revise the "R2 status" line (~342), the R2b caller list note (~123/~381), and the "### R2b" section (~705) to record R2b as integrated with tests on this delivery branch (merging via this PR), with R2c/R2d and live proof explicitly open. Do not touch any validator or gate command.
- [ ] Run `git diff --check` plus the planning traceability tests (`tests/test_planning_traceability.py`, `tests/test_config_drift.py`) again to prove the tracker edits don't break traceability, then commit both files as one `docs(planning): record R2b caller lock delivery` commit.

### Task 3: Push and PR with exact-head CI
- [ ] Push `codex/r2b-capture-rotator-lock` to origin (no force). Open ONE PR to `main` titled for the R2b slice (e.g. "feat(infra): R2b — capture and rotator acquire the shared runtime-exclusive lock"). The body must summarize: the RED→GREEN evidence, test counts (93 focused, 39/39 rails, 7/7 classes, 34 planning/config), every hardware-admission sample, the boundaries NOT crossed (no live mutation, no cert issuance, no Vault, no `ca.crt` touch), the explicitly open follow-ups (R2c/R2d, R3/R4, live proof, `ca.crt` repair, knowledge refresh), and a note that `docs/plans/goalex-r2-*.md` is the round's execution-evidence record. Do not include any secret or external path contents.
- [ ] Watch CI (`.github/workflows/ci.yml`) for the exact pushed head SHA via `gh pr checks` / `gh run list --commit <sha>`; require all gating jobs green ON THAT SHA. If red, diagnose and fix with a new small commit, push, and wait for green on the new exact head — never merge red or reuse a stale-head run.

### Task 4: Merge, verify, and record
- [ ] Merge the PR only after exact-head CI is green (normal merge; no force, no history rewrite). Then `git fetch origin` and verify locally: the merge commit is on `origin/main`, `git log origin/main` contains the delivery content, and `git diff origin/main -- infra/scripts/capture-production-evidence.sh infra/scripts/rotate-production-mcp-client-cert.sh tests/test_runtime_exclusive_lock.py tests/test_production_evidence_preflight.py` against the branch head is empty.
- [ ] Check out or fast-forward local `main` to the merged SHA and run the GOAL.md hygiene gate there (`git diff --check`, ruff, planning/config pytest) to confirm the merged state is green.
- [ ] Record in your final result note: the merged main SHA, the PR number, the exact-head CI run id(s), and confirmation that no live/protected/public/Vault action occurred. Do NOT begin R2c/R2d or any other slice this round.
