# Plan: R2b resume — validate RED baseline and integrate the shared runtime lock (retry-gated)

## Overview

You are resuming one slice of Mnemosyne v2.0 Phase 12 (Plan 12-04) in
`/Users/admin/Mnemosyne`. The authoritative spec is
`docs/superpowers/plans/2026-07-13-production-mcp-client-cert-rotation.md` —
read its "Shared runtime lock contract", "Hardware admission", and
"### R2b — Capture and rotator integration" sections before writing code.
`.planning/STATE.md` records the live checkpoint (see its "R2b RED checkpoint
(2026-07-15)" entry near the end).

State you inherit from the previous round:
- R2a is DONE and merged (`main@79f6b58`): `infra/scripts/runtime-exclusive-lock.sh`
  is the accepted fail-closed shared lock coordinator (interface:
  `runtime-exclusive-lock.sh OPERATION -- /absolute/command [args...]`;
  `MNEMO_CUSTODY_DIR/locks` must be mode `0700`; ownership is published at
  `locks/runtime-exclusive/owner.json` with a mode-0600 owner token). It is
  covered by 55 tests in `tests/test_runtime_exclusive_lock.py`. Do NOT redo,
  refactor, or weaken it or any existing test assertion.
- The previous round wrote RED scaffolding but was gate-blocked before pytest
  ever ran. Commit `4502d42` (on branch
  `goalex-r1-r2b-integrate-the-shared-runtime-exclusi`) added two UNVALIDATED
  tests to `tests/test_runtime_exclusive_lock.py`:
  `test_capture_acquires_runtime_lock_before_first_side_effect` and
  `test_rotator_acquires_runtime_lock_before_first_side_effect`, plus a
  `_write_python_lock_probe` fixture that shims `python3`/`MNEMOSYNE_PYTHON` to
  log `locked`/`unlocked` depending on whether `owner.json` exists at first
  side effect. These tests have NEVER been executed — they may fail for the
  wrong reason (e.g. probe log never created because the script exits before
  its first side effect in the sandbox). Validating and, if needed, repairing
  them is part of this round.
- Neither `infra/scripts/capture-production-evidence.sh` (1998 lines) nor
  `infra/scripts/rotate-production-mcp-client-cert.sh` (3696 lines) currently
  references `runtime-exclusive-lock.sh` (verified by grep). The rotator's
  local `.mcp-client-rotation.lock` and the capture output-root lock are
  additional controls: keep both, and never conflate the local rotator lock
  with the shared contract.
- `main` and `origin/main` are at `c5cfe03`. The goalex loop branch carries
  plan/checkpoint commits (`ba84316`, `4f885fd`, `4c20ba5`, `4502d42`) that
  must NOT go into the PR; only the test scaffolding file content is reused.

Hardware admission protocol for THIS round (this is the changed approach —
the last round aborted on one transient spike):
- Before EACH pytest invocation, take a fresh targeted host sample: free
  memory ≥35%, 1-minute load ≤10, no resident Ollama model (`ollama ps`), and
  `docker ps` showing only the existing infra stack with no mutation.
- If a sample fails, do not abort immediately: wait 300 seconds and re-sample,
  up to 3 total samples per pytest attempt. Record every sample (pass or fail,
  with measured values and timestamps) in your result note. Only if all 3 fail,
  record the block with the measured values in `.planning/STATE.md`, commit
  that checkpoint, and stop.

Hard boundaries (never cross): no live Docker/Compose/Colima mutation, no real
certificate issuance/rotation, no touching the external secrets directory or
`vault-tls/ca.crt` (its repair is a separate gated operation), no Vault
operations, no model runs, no protected attempts, no publication. All tests
run against sandbox fixture dirs (override `MNEMO_CUSTODY_DIR` etc., fake
docker/openssl/python commands — follow existing patterns in
`tests/test_runtime_exclusive_lock.py` and
`tests/test_production_evidence_preflight.py`). §31 rails (39) and §33 test
classes (7) stay green and unweakened. Small conventional commits; never merge
red or on a stale head.

## Validation Commands
- `git diff --check`
- `.venv/bin/ruff check --quiet .`
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_planning_traceability.py tests/test_config_drift.py`
- `bash -n infra/scripts/capture-production-evidence.sh infra/scripts/rotate-production-mcp-client-cert.sh`
- `shellcheck infra/scripts/capture-production-evidence.sh infra/scripts/rotate-production-mcp-client-cert.sh`
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_runtime_exclusive_lock.py tests/test_production_evidence_preflight.py -k 'capture or rotator or runtime_lock'`

### Task 1: Delivery branch and RED validation under the retry-gated admission
- [x] Confirm a clean tree; fetch and confirm `origin/main` is still `c5cfe03` (if it moved, rebase your understanding on the new head — do not assume). Create `codex/r2b-capture-rotator-lock` off `origin/main`.
- [x] Bring the RED scaffolding onto the branch with `git checkout 4502d42 -- tests/test_runtime_exclusive_lock.py` (take ONLY the test file; do not cherry-pick the commit, which also carries loop-branch STATE.md bookkeeping).
- [x] Run the retry-gated hardware admission protocol (up to 3 samples, 300 s apart); record every measured sample. If admitted, run the focused pytest selection and confirm BOTH new tests fail specifically because the first side effect happens without shared-lock ownership (probe log's first line is `unlocked`) — not because of harness errors such as a missing probe log, wrong flag, or script usage failure. Repair the fixtures if they fail for the wrong reason (e.g. verify `--preflight-only` and `MNEMOSYNE_PYTHON`/`PATH` shims actually drive each script to its first side effect in the sandbox).
- [x] Confirm the 55 pre-existing lock tests still pass in the same run, then commit the validated RED baseline as one conventional commit (e.g. `test(infra): prove capture and rotator mutate before shared lock`).

Task 1 evidence (2026-07-15): `origin/main=c5cfe03`. Admission samples (UTC):
`16:17:55` 36% free/load1 4.92; `16:18:48` 41%/3.58; `16:19:00`
41%/3.97; `16:19:07` 42%/3.74; `16:19:13` 42%/3.60. Every sample
had zero resident Ollama models and the unchanged 20-container infra stack.
Both new tests failed at the intended first-side-effect assertion with probe
value `unlocked`; the dedicated lock-file run reported 2 failed, 55 passed.

### Task 2: GREEN — capture entrypoint acquires the shared lock before any side effect
- [x] Following the plan doc's R2b section, wire `infra/scripts/capture-production-evidence.sh` to acquire the shared runtime-exclusive lock via `runtime-exclusive-lock.sh` with a distinct operation name before ANY side effect, hold it through completion, and release only on the owner path; keep the existing capture output-root lock unchanged.
- [x] Under the retry-gated admission, run the focused selection and confirm the capture RED test flips green with no existing test weakened; `bash -n` and `shellcheck` on the script must pass.

Task 2 result (2026-07-15): `capture-production-evidence.sh` now re-executes
under operation `capture-production-evidence` before argument validation or its
first Python invocation. The existing output-root lock remains unchanged. The
production-evidence tests now provision a private mode-`0700` custody/locks
tree so the shared coordinator remains fail-closed outside its production
contract. Admission samples passed at `2026-07-15T16:22:49Z` (46% free,
load1 8.01), `2026-07-15T16:24:13Z` (44% free, load1 5.43), and
`2026-07-15T16:25:29Z` (43% free, load1 5.12); every sample had zero resident
Ollama models and the unchanged 20-container `infra` stack. The Task 2 focused
selection passed 80 tests with the still-RED rotator test excluded. Bash syntax,
ShellCheck, Ruff check/format, diff hygiene, and all 34 planning/config tests
passed.

### Task 3: GREEN — rotator acquires the shared lock and revalidates after acquisition
- [x] Wire `infra/scripts/rotate-production-mcp-client-cert.sh` the same way (distinct operation name), keeping the local `.mcp-client-rotation.lock`, and make it revalidate the current certificate pair and recompute its renewal decision AFTER shared-lock acquisition.
- [x] Under the retry-gated admission, run the focused selection and confirm the rotator RED test flips green; `bash -n` and `shellcheck` must pass.

Task 3 evidence (2026-07-15): the rotator re-executes under operation
`rotate-production-mcp-client-cert` before its local lock, pair validation, and
renewal calculation; the shared-lock sentinel remains set through the local-lock
re-exec and is cleared afterward. Samples at 16:30:44Z, 16:32:29Z, 16:33:02Z,
16:33:31Z, and 16:34:47Z recorded 42%, 42%, 41%, 40%, and 42% free memory,
load1 5.54, 5.43, 6.12, 6.06, and 6.48, no resident Ollama model, and the
unchanged 20-container `infra` stack. The complete focused selection exited 0,
including the formerly RED rotator test. Bash syntax, ShellCheck, Ruff, diff
hygiene, and all 34 planning/config tests passed.

### Task 4: Contention, release, and no-detach contract tests
- [x] Extend the focused tests to prove, for both callers: acquisition precedes every side effect; contention with a concurrent shared-lock holder fails closed without any sandbox mutation; release occurs on success and on handled signals; and the synchronous-completion / no-`setsid`-`setpgid`-daemonize / no-session-change / no-uid-transition contract holds (mirror the existing R2a test patterns).
- [x] Under the retry-gated admission, run the full focused selection plus `ruff format --check` on touched test files; commit the GREEN work as small conventional commits.

Task 4 evidence (2026-07-15): both integrations now have focused contention,
synchronous-lifetime, handled-signal cleanup, process-session/uid, and static
no-detach/source-boundary coverage. Admission samples passed at 16:38:08Z
(39% free after correcting the macOS metric, load1 6.53), 16:39Z (42%, 7.31),
16:39Z (41%, 6.57), and 16:40Z (39%, 7.89); every valid sample had zero
resident Ollama models and the unchanged 20-container `infra` stack. The
focused caller subset passed 15 tests, the complete focused selection passed
93 tests, and all 34 planning/config tests passed. Ruff check/format, Bash
syntax, ShellCheck, and diff hygiene were green.

### Task 5: Regression cell, trackers, and exact-head CI delivery
- [ ] Run all Validation Commands above plus the GOAL.md hygiene gate; inspect the complete diff and run a secret/risky-file sweep before staging anything further.
- [ ] Update `.planning/STATE.md` (new checkpoint superseding the "R2b RED checkpoint (2026-07-15)" entry, named evidence artifacts, every recorded hardware sample) and the R2b status line in `docs/superpowers/plans/2026-07-13-production-mcp-client-cert-rotation.md`; leave R2c/R2d, R3/R4, live proof, the Vault `ca.crt` repair, and the hardware-admitted Graphify/CBM/gbrain refresh explicitly open.
- [ ] Push the branch, open one PR titled for the R2b slice with the evidence summary (including the admission samples) in the body; require exact-head CI green on the pushed SHA, merge only on green, then verify the merged SHA locally and record it in `.planning/STATE.md`.
