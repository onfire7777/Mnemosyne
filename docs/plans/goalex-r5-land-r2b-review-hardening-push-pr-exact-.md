# Plan: Land R2b review hardening — push, PR, exact-head CI, merge, reconcile trackers with expired-cert blocker

## Overview

You are landing one finished, review-confirmed hardening slice of Mnemosyne
v2.0 Phase 12 (Plan 12-04) in `/Users/admin/Mnemosyne`. The implementation is
DONE and committed locally; your job is independent verification, landing,
tracker reconciliation, a gated knowledge-refresh attempt, and branch hygiene.
Do NOT re-implement or extend the shipped code, and do NOT start R2c/R2d,
R3/R4, live rotation proof, certificate rotation/issuance, the external
`vault-tls/ca.crt` repair, or Vault operations — those are later slices.

Ground the round per the operating contract: re-read `.planning/STATE.md`,
`.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md`,
`.planning/ACTIVE-GOAL-OPERATING-CONTRACT.md`, the active Phase 12 files, and
`docs/superpowers/plans/2026-07-13-production-mcp-client-cert-rotation.md`
("R2 status" at line ~344, "### R2b" section at line ~710). This slice
advances Phase 12 Plan 12-04 and protects CAP-001/002/003, BENCH-005, and
RAIL-001..004 without closing any measured gate. Use CBM
(codebase-memory-mcp) first for code understanding (architecture, impact of
`main...HEAD`, tracing the two caller entrypoints through
`runtime-exclusive-lock.sh`); if CBM is unavailable, record that literal
blocker and fall back to narrow file reads — never claim the index current.

State you inherit (verified):
- `main` = `origin/main` = `6dded5f` (R2b landed via PR #15 merge `13d1513`,
  reconciled via PR #16 merge `6dded5f`). Working tree clean.
- Local branch `codex/r2b-code-review-fixes` is 2 commits ahead of main, has
  NO remote branch and therefore NO PR:
  - `c22fb58` — small receipts edit to
    `docs/plans/goalex-r4-r2b-landing-exact-head-ci-green-merge-pr.md`.
  - `20dc6b4` — "checkpoint(r2b-review): harden runtime-lock reentry against
    forgeable sentinel". An independent post-merge review confirmed callers
    trusted a plain env sentinel to detect they were already running under
    the runtime-exclusive lock, which a hostile/buggy environment could
    forge. The fix adds a `--verify-child` mode to
    `infra/scripts/runtime-exclusive-lock.sh`: the wrapper passes an
    inherited owner fd plus `MNEMO_RUNTIME_LOCK_ACTIVE/OWNER_FD/OPERATION/
    OWNER_PID/OWNER_TOKEN` to children, and verification re-validates the
    inherited fd against an independently opened owner file (same lock
    identity, lock actually held, operation/token/pid/uid metadata match,
    process start-time fingerprint match) before honoring reentry. Callers
    `infra/scripts/capture-production-evidence.sh` and
    `infra/scripts/rotate-production-mcp-client-cert.sh` invoke
    `--verify-child` instead of trusting the sentinel. Contract tests were
    extended in `tests/test_runtime_exclusive_lock.py`,
    `tests/test_production_mcp_client_cert_rotator.py`, and
    `tests/test_production_evidence_preflight.py`, covering forged and
    copied ownership proof. This strengthens (never weakens) the R2 lock
    contract; the rotator-local lock stays distinct from the shared
    contract, and ordinary production stays `staged_only`.
- The checkpoint commit body records a NEW NAMED BLOCKER not yet in the
  trackers: the production MCP client certificate expired
  `2026-07-14T23:52:36Z`. The fail-closed TLS preflight sample therefore
  fails, blocking ALL full-suite/index/model/live/protected admission
  (Graphify/CBM-reindex/gbrain refresh, candidate-v19 chain, live
  rotation/no-op proof) until the pair is rotated under the live-mutation
  admission runbook. Rotating that certificate is a live CA/consumer
  mutation outside this slice's authorized scope — record the blocker, never
  attempt the rotation.
- The independent post-round findings list for this round is empty; nothing
  requires dismissal. The earlier confirmed sentinel finding is already
  fixed in `20dc6b4` but unshipped.
- CI failure history: the "Unit + drift checks" job previously failed on
  lock tests due to test-environment coupling, fixed by isolating rotator
  body tests from the runtime lock wrapper (commit `43e6cb4`). If that job
  fails on this branch, the cause is almost certainly similar coupling in
  the new `--verify-child` tests (inherited fds, process start-time
  fingerprints, HOME/TMPDIR, CI process semantics) — fix ONLY test
  isolation/environment issues with a small conventional commit after
  root-cause diagnosis; NEVER weaken an assertion, validator, or shipped
  script behavior.
- Landing pattern (follow the R2a/R2b precedent exactly): code PR first,
  merged on green exact-head CI; then a separate small `docs(planning)`
  reconciliation PR from fresh main. Never pre-record a future PR number,
  CI run, or merge SHA in a repo file — a file must not self-attest to its
  own future merge; record actual receipts only after they exist, and use
  the reconciliation PR body/comments for anything only knowable post-merge.

Hardware admission protocol (before EACH local pytest invocation), per
`.planning/runbooks/HARDWARE-WORKLOAD-PREFLIGHT.md`: take a fresh host
sample — free memory ≥35%, 1-minute load ≤10, zero resident Ollama models
(`ollama ps`), `docker ps` showing only the existing ~20-container infra
stack with no mutation. If a sample fails, wait 300 s and re-sample, up to 3
samples per attempt; record every sample (values + UTC timestamps). If all 3
fail, record the block in `.planning/STATE.md`, commit that checkpoint, and
stop. Full-suite/Graphify/CBM/gbrain operations additionally require the
complete fail-closed three-sample hardware/TLS/Vault/service/topology
admission — one good host sample admits nothing.

Hard boundaries: never merge red or on a stale head; no force-push; no
shared-history rewrite; no live Docker/Compose/Colima mutation; no
certificate issuance or rotation; no Vault operations; no touching the
external secrets directory or `vault-tls/ca.crt`; no model runs, protected
attempts, or publication. All 39 §31 rails and 7 §33 test classes must stay
green and unweakened at every commit.

## Validation Commands
- `git status --short --branch && git rev-parse HEAD origin/main`
- `git diff --check`
- `.venv/bin/ruff check --quiet .`
- `.venv/bin/ruff format --check tests/test_runtime_exclusive_lock.py tests/test_production_evidence_preflight.py tests/test_production_mcp_client_cert_rotator.py`
- `bash -n infra/scripts/runtime-exclusive-lock.sh infra/scripts/capture-production-evidence.sh infra/scripts/rotate-production-mcp-client-cert.sh`
- `shellcheck infra/scripts/runtime-exclusive-lock.sh infra/scripts/capture-production-evidence.sh infra/scripts/rotate-production-mcp-client-cert.sh` (skip only if shellcheck is unavailable; `bash -n` already covers syntax)
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_runtime_exclusive_lock.py tests/test_production_evidence_preflight.py tests/test_production_mcp_client_cert_rotator.py`
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_parity_learning.py tests/test_learning_and_attack_suite.py tests/test_g0_harness.py`
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_planning_traceability.py tests/test_config_drift.py` (expect 34 passed)
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q` — ONLY after the complete three-sample strong admission passes
- `gh run list --commit "$(git rev-parse HEAD)" --json databaseId,status,conclusion,headSha,workflowName`
- `gh pr checks <pr-number>`

### Task 1: Independently re-verify the committed fix at the checkpoint head
- [ ] On branch `codex/r2b-code-review-fixes` at `20dc6b4` with a clean tree, confirm the inherited state: `main@6dded5f` == `origin/main`, exactly two commits ahead, no remote branch, no existing PR (`gh pr list --head codex/r2b-code-review-fixes`). If `origin/main` has moved, integrate without force-push or history rewrite before proceeding.
- [ ] Run the static gate: `git diff --check`, `.venv/bin/ruff check --quiet .`, `ruff format --check` on the three test files, `bash -n` and `shellcheck` on the three shell scripts.
- [ ] Inspect `git diff origin/main...HEAD` in full and run the secret/risky-file sweep (credentials, certificate material, Vault data, binaries, external paths). Verify against the slice success criteria: both callers acquire before any side effect; reentry requires genuine coordinator ownership; forged/copied environment proof fails closed without mutation; the rotator-local lock remains separate from the shared contract; `staged_only` behavior and every validator unchanged. You may run this as two parallel read-only review lanes (trust-boundary/security and correctness/tests), keeping all git and edit ownership in the controller.
- [ ] Take a fresh hardware-admission sample (protocol above, record values + UTC timestamps), then run the focused lock/preflight/rotator suites, the §31/§33 cells (`test_parity_learning.py`, `test_learning_and_attack_suite.py`, `test_g0_harness.py`), and the planning/config pair. All must pass with zero failures. If any behavior defect is found, add a failing regression FIRST, apply the smallest correct fix (Ponytail order, no new dependency) as a small conventional commit, and re-run the affected cells. If anything would require weakening a rail, validator, or assertion — STOP and record the finding in `.planning/STATE.md` instead of pushing.

### Task 2: Push, open the code PR, exact-head CI green, merge, verify
- [ ] Push `codex/r2b-code-review-fixes` to origin (no force). Open one PR to `main` titled `fix(r2b-review): harden runtime-lock reentry against forgeable sentinel` whose body carries: the confirmed review finding (forgeable env sentinel), the `--verify-child` ownership-proof mechanism, RED/GREEN and focused test counts from Task 1, static/ShellCheck results, the admission sample(s), the secret-sweep result, explicit confirmation that no validator or staged-only boundary changed, the still-open follow-ups (R2c/R2d, R3/R4, live rotation proof, `vault-tls/ca.crt` repair), and the explicit note that full-suite admission is blocked by the production MCP client certificate expiry `2026-07-14T23:52:36Z` (recorded, not bypassed).
- [ ] If the repo's review tooling (e.g. CodeRabbit terminal review or a configured security review) is available, run it on the pushed PR head and adjudicate every actionable finding — fix with small commits after root-cause diagnosis; never weaken assertions or bypass hooks.
- [ ] Wait for exact-head CI on the pushed SHA (`gh pr checks`, `gh run list --commit <sha>`). All gating jobs must be green on that exact SHA — never reuse a stale-head run; the nightly DST/chaos soak skip is expected and acceptable. If "Unit + drift checks" fails, pull `--log-failed`, reproduce locally under a fresh admission sample, fix ONLY test isolation/environment coupling (see Overview precedent `43e6cb4`) with a new small commit, push, and wait for green on the new exact head. Record the root cause.
- [ ] Only on green exact-head CI: `gh pr merge <n> --merge` (normal merge commit). Record the merge SHA. `git fetch origin`; verify the merge commit is on `origin/main` and that `git diff <branch-head> origin/main -- <the three scripts and three test files>` is empty. Fast-forward local `main`, re-run the static gate plus (after a fresh admission sample) the planning/config pair there, and watch the post-merge main CI run to green. Record both run ids.

### Task 3: Post-merge tracker reconciliation PR recording the merge and the expired-cert blocker
- [ ] From verified merged `main`, create branch `codex/r2b-review-reconciliation`. In `.planning/STATE.md`: refresh frontmatter `stopped_at`/`last_updated`; add a "Latest checkpoint" entry naming the actual review-hardening merge SHA, PR number, exact-head and post-merge CI run ids, and review dispositions; and record the named blocker — production MCP client certificate expired `2026-07-14T23:52:36Z`, failing the fail-closed TLS preflight sample and blocking full-suite/index/model/live/protected admission (Graphify/CBM/gbrain refresh, candidate-v19 chain, live rotation/no-op proof) until the pair is rotated under the live-mutation admission runbook; certificate rotation was NOT performed. Add a matching bullet under "Operator Next Steps".
- [ ] In `docs/superpowers/plans/2026-07-13-production-mcp-client-cert-rotation.md`: update the "R2 status" line (~344) and "### R2b" section (~710) to record the post-merge review hardening (forgeable sentinel replaced by `--verify-child` coordinator-ownership re-validation) with its actual merged SHA and PR, superseding any stale PR #15-only wording. Touch no validator or gate command.
- [ ] Check `.planning/ROADMAP.md` and `.planning/REQUIREMENTS.md`: keep Plan 12-04 open at its current recorded progress; keep CAP-001/002/003 and BENCH-005 at their current partial state and RAIL-001..004 continuous — do not close or silently advance any row, and do not reopen the closed v1.0/Tier-B audits. Keep R2c/R2d, R3/R4, rollback terminal receipts, live rotation/no-op proof, the separate atomic `vault-tls/ca.crt` repair, candidate-v19 custody/exact-scale/protected chain, and Graphify/CBM/gbrain freshness explicitly open; the last accepted merge-bound knowledge receipt remains PR #12.
- [ ] Re-run `git diff --check`, Ruff, and (after a fresh admission sample) the planning/config tests; stage only the named tracker/plan files; commit as one `docs(planning): reconcile R2b review hardening` commit; push (no force); open the PR with receipts in the body; wait for exact-head CI green; merge normally; verify `origin/main`; fast-forward local `main`; confirm the post-merge main run is green. Record post-merge-only facts (this PR's own merge SHA) in the PR body/comment, not in a repo file that would self-attest.

### Task 4: Attempt the admission-gated knowledge refresh on final main — or record the gate
- [ ] On the final merged `main`, run the complete fail-closed three-sample hardware/TLS/Vault/service/topology preflight per `.planning/runbooks/HARDWARE-WORKLOAD-PREFLIGHT.md` before ANY full-suite, Graphify, CBM-reindex, or gbrain operation. Re-check the recorded expired-certificate state read-only; do not rotate, reissue, or weaken anything.
- [ ] If admitted (unlikely while the certificate is expired): run the full suite, Graphify refresh, CBM change-detection/reindex, and gbrain sync/doctor serially against the exact final SHA; require CBM CURRENT and gbrain `cycle_freshness` OK; record non-secret receipts as a comment on the reconciliation PR.
- [ ] If any admission check fails (expected: the TLS sample fails on the expired cert): perform NONE of the gated operations. Verify the failed check, samples (values + UTC timestamps), owner, required remediation, and next safe action are recorded in `.planning/STATE.md` — if Task 3 already captured them accurately, confirm and note that in the result note; if anything is missing, add it via one minimal `docs(planning)` PR following the same exact-head-CI-green merge discipline. Leave the freshness rows explicitly open; never create a self-receipt loop.

### Task 5: Branch hygiene and final receipts
- [ ] Clean up fully-landed branches only after verifying supersession: confirm the two unpushed commits on local `codex/r2b-capture-rotator-lock` (`0826154`, `b9e0c15`) touch only `.planning/STATE.md` and `docs/plans/goalex-r4-r2b-landing-exact-head-ci-green-merge-pr.md` receipts whose facts are already recorded on merged `main` (diff them against main's copies). Then delete local branches `codex/r2b-capture-rotator-lock`, `codex/r2b-main-reconciliation`, `codex/r2b-code-review-fixes`, `codex/r2b-review-reconciliation`, and the merged remote branches (`git push origin --delete` for `codex/r2b-capture-rotator-lock`, `codex/r2b-main-reconciliation`, and the two branches merged this round). If any unpushed commit contains facts NOT on main, keep that branch and record it in `.planning/STATE.md` instead of deleting.
- [ ] Finish with a clean tree and `main == origin/main`. In your final result note record: the review-hardening merge SHA and PR number, exact-head and post-merge CI run ids for both PRs, the reconciliation merge SHA, the admission-gate outcome from Task 4 (refresh receipts, or the exact failed check and samples), the branch cleanup performed, the recorded expired-certificate blocker, explicit confirmation that no live/protected/public/Vault/CA/`ca.crt` action occurred and no §31/§33 assertion was weakened, and a literal handoff that R2c/R2d — not already-completed R2b work — is the next source-owned slice. Do NOT begin R2c/R2d or any other slice this round.
