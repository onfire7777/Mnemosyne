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
  fails on this branch, diagnose the root cause first. Fix only confirmed
  test-environment coupling (inherited fds, process start-time fingerprints,
  HOME/TMPDIR, CI process semantics) as a test-isolation change. If CI instead
  reveals a behavior defect, follow Task 1's regression-first path and make
  the smallest production fix. NEVER weaken an assertion, validator, or
  shipped script behavior.
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
- [x] On branch `codex/r2b-code-review-fixes` at `20dc6b4` with a clean tree, confirm the inherited state: `main@6dded5f` == `origin/main`, exactly two commits ahead, no remote branch, no existing PR (`gh pr list --head codex/r2b-code-review-fixes`). If `origin/main` has moved, integrate without force-push or history rewrite before proceeding. Verified after `git fetch --prune`: the two implementation commits end at `20dc6b4`; current `HEAD` is one additional Goalex plan-only commit `c39fe40`, so the branch is three total commits ahead without implementation drift.
- [x] Run the static gate: `git diff --check`, `.venv/bin/ruff check --quiet .`, `ruff format --check` on the three test files, `bash -n` and `shellcheck` on the three shell scripts.
- [x] Inspect `git diff origin/main...HEAD` in full and run the secret/risky-file sweep (credentials, certificate material, Vault data, binaries, external paths). Verify against the slice success criteria: both callers acquire before any side effect; reentry requires genuine coordinator ownership; forged/copied environment proof fails closed without mutation; the rotator-local lock remains separate from the shared contract; `staged_only` behavior and every validator unchanged. You may run this as two parallel read-only review lanes (trust-boundary/security and correctness/tests), keeping all git and edit ownership in the controller. Review found no actionable correctness, security, secret, binary, external-path, validator, or scope-drift issue.
- [x] Take a fresh hardware-admission sample (protocol above, record values + UTC timestamps), then run the focused lock/preflight/rotator suites, the §31/§33 cells (`test_parity_learning.py`, `test_learning_and_attack_suite.py`, `test_g0_harness.py`), and the planning/config pair. All must pass with zero failures. If any behavior defect is found, add a failing regression FIRST, apply the smallest correct fix (Ponytail order, no new dependency) as a small conventional commit, and re-run the affected cells. If anything would require weakening a rail, validator, or assertion — STOP and record the finding in `.planning/STATE.md` instead of pushing. Samples: `2026-07-15T20:29:34Z` failed only because one Ollama model was resident; after the required 300-second wait, `2026-07-15T20:34:43Z` passed at 53% free/load1 1.76/zero models/20 healthy containers. Explicit-status rerun admitted at `2026-07-15T20:47:26Z` (51%/2.83/zero/20) passed 446 focused tests; `2026-07-15T21:00:04Z` (50%/3.45/zero/20) passed 91 §31/§33 tests; `2026-07-15T21:00:22Z` (49%/2.83/zero/20) passed 34 planning/config tests.

### Task 2: Push, open the code PR, exact-head CI green, merge, verify
- [x] Push `codex/r2b-code-review-fixes` to origin (no force). Open one PR to `main` titled `fix(r2b-review): harden runtime-lock reentry against forgeable sentinel` whose body carries: the confirmed review finding (forgeable env sentinel), the `--verify-child` ownership-proof mechanism, RED/GREEN and focused test counts from Task 1, static/ShellCheck results, the admission sample(s), the secret-sweep result, explicit confirmation that no validator or staged-only boundary changed, the still-open follow-ups (R2c/R2d, R3/R4, live rotation proof, `vault-tls/ca.crt` repair), and the explicit note that full-suite admission is blocked by the production MCP client certificate expiry `2026-07-14T23:52:36Z` (recorded, not bypassed). Pushed without force and opened PR #17 with the required title, evidence, boundaries, open follow-ups, and expired-certificate blocker.
- [x] If the repo's review tooling (e.g. CodeRabbit terminal review or a configured security review) is available, run it on the pushed PR head and adjudicate every actionable finding — fix with small commits after root-cause diagnosis; never weaken assertions or bypass hooks. Terminal CodeRabbit returned four findings: three were accepted (position-independent inherited-owner reads, bounded caller-source assertions, and behavior-regression-aware CI guidance) and landed in `e5ffa1c`; the request to rewrite the published branch was dispositioned because it conflicted with the authoritative Goalex receipt workflow and no-history-rewrite boundary. The new `os.pread` regression and corrected source-boundary cell passed 3/3; static/Ruff/Bash/ShellCheck stayed green. GitHub CodeRabbit completed green on the final head.
- [x] Wait for exact-head CI on the pushed SHA (`gh pr checks`, `gh run list --commit <sha>`). All gating jobs must be green on that exact SHA — never reuse a stale-head run; the nightly DST/chaos soak skip is expected and acceptable. If "Unit + drift checks" fails, pull `--log-failed`, reproduce locally under a fresh admission sample, and diagnose before editing. Fix confirmed test-environment coupling only as test isolation (see Overview precedent `43e6cb4`); handle a real behavior defect through Task 1's regression-first path. Push any minimal fix and wait for green on the new exact head. Record the root cause. Final exact head `e5ffa1c76bc392660731a02f9831405299fe385b` passed run `29452661004`; all gating jobs and CodeRabbit were green, with only the expected non-gating DST/chaos soak skipped. No CI failure path triggered.
- [x] Only on green exact-head CI: `gh pr merge <n> --merge` (normal merge commit). Record the merge SHA. `git fetch origin`; verify the merge commit is on `origin/main` and that `git diff <branch-head> origin/main -- <the three scripts and three test files>` is empty. Fast-forward local `main`, re-run the static gate plus (after a fresh admission sample) the planning/config pair there, and watch the post-merge main CI run to green. Record both run ids. PR #17 merged normally as `5a6ce1921c1537b6090cf40600581f9fe956fe1f`; the six-file diff from `e5ffa1c` to `origin/main` was empty and local `main` fast-forwarded cleanly. Post-merge static/Ruff/Bash/ShellCheck passed; the `2026-07-15T21:54:14Z` sample passed at 52% free memory/load1 3.00/zero Ollama models/20 healthy containers, and planning/config passed 34/34. Main run `29453529951` completed green on `5a6ce19`. During the earlier local combined validation, operator and blackbox-exporter start times changed externally at `2026-07-15T21:25Z`; no Docker mutation command was issued by this task, both remained healthy with restart count zero, and the observation was not misreported as unchanged uptime.

### Task 3: Post-merge tracker reconciliation PR recording the merge and the expired-cert blocker
- [x] From verified merged `main`, create branch `codex/r2b-review-reconciliation`. In `.planning/STATE.md`: refresh frontmatter `stopped_at`/`last_updated`; add a "Latest checkpoint" entry naming the actual review-hardening merge SHA, PR number, exact-head and post-merge CI run ids, and review dispositions; and record the named blocker — production MCP client certificate expired `2026-07-14T23:52:36Z`, failing the fail-closed TLS preflight sample and blocking full-suite/index/model/live/protected admission (Graphify/CBM/gbrain refresh, candidate-v19 chain, live rotation/no-op proof) until the pair is rotated under the live-mutation admission runbook; certificate rotation was NOT performed. Add a matching bullet under "Operator Next Steps". Recorded PR #17 merge `5a6ce1921c1537b6090cf40600581f9fe956fe1f`, exact-head run `29452661004`, post-merge run `29453529951`, and the review dispositions without performing certificate rotation.
- [x] In `docs/superpowers/plans/2026-07-13-production-mcp-client-cert-rotation.md`: update the "R2 status" line (~344) and "### R2b" section (~710) to record the post-merge review hardening (forgeable sentinel replaced by `--verify-child` coordinator-ownership re-validation) with its actual merged SHA and PR, superseding any stale PR #15-only wording. Touch no validator or gate command. Updated both status surfaces for PR #17 and merge `5a6ce1921c1537b6090cf40600581f9fe956fe1f`; validator and gate commands are unchanged.
- [x] Check `.planning/ROADMAP.md` and `.planning/REQUIREMENTS.md`: keep Plan 12-04 open at its current recorded progress; keep CAP-001/002/003 and BENCH-005 at their current partial state and RAIL-001..004 continuous — do not close or silently advance any row, and do not reopen the closed v1.0/Tier-B audits. Keep R2c/R2d, R3/R4, rollback terminal receipts, live rotation/no-op proof, the separate atomic `vault-tls/ca.crt` repair, candidate-v19 custody/exact-scale/protected chain, and Graphify/CBM/gbrain freshness explicitly open; the last accepted merge-bound knowledge receipt remains PR #12. Verified unchanged; neither tracker required an edit.
- [x] Re-run `git diff --check`, Ruff, and (after a fresh admission sample) the planning/config tests; stage only the named tracker/plan files; commit as one `docs(planning): reconcile R2b review hardening` commit; push (no force); open the PR with receipts in the body; wait for exact-head CI green; merge normally; verify `origin/main`; fast-forward local `main`; confirm the post-merge main run is green. Record post-merge-only facts (this PR's own merge SHA) in the PR body/comment, not in a repo file that would self-attest. Local validation passed after the `2026-07-15T22:12:52Z` admission sample (49% free/load1 2.22/zero models/20 healthy containers): diff check and Ruff passed, three files were formatted, and planning/config passed 34/34. Delivery receipts are recorded only in the PR body/comment.

### Task 4: Attempt the admission-gated knowledge refresh on final main — or record the gate
- [x] On the final merged `main`, run the complete fail-closed three-sample hardware/TLS/Vault/service/topology preflight per `.planning/runbooks/HARDWARE-WORKLOAD-PREFLIGHT.md` before ANY full-suite, Graphify, CBM-reindex, or gbrain operation. Re-check the recorded expired-certificate state read-only; do not rotate, reissue, or weaken anything. Receipt: on `main@f50cec0`, the unchanged TLS validator passed an externally refreshed leaf expiring `2026-07-16T21:18:25Z`; samples at `2026-07-15T22:59:07Z`, `22:59:24Z`, and `22:59:40Z` recorded 53%/55%/55% free memory and load1/load5 1.66/1.97, 1.85/2.00, and 1.82/1.99, with zero resident models, Colima 6 CPU/12 GiB, one reachable 20-service `infra` project, stable API/stream zero-restart identities, and initialized/unsealed Vault. No certificate/runtime mutation occurred.
- [x] If admitted (unlikely while the certificate is expired): run the full suite, Graphify refresh, CBM change-detection/reindex, and gbrain sync/doctor serially against the exact final SHA; require CBM CURRENT and gbrain `cycle_freshness` OK; record non-secret receipts as a comment on the reconciliation PR. Not admitted: skipped all gated operations because sample 1 was 53% free against the 55% floor.
- [x] If any admission check fails (expected: the TLS sample fails on the expired cert): perform NONE of the gated operations. Verify the failed check, samples (values + UTC timestamps), owner, required remediation, and next safe action are recorded in `.planning/STATE.md` — if Task 3 already captured them accurately, confirm and note that in the result note; if anything is missing, add it via one minimal `docs(planning)` PR following the same exact-head-CI-green merge discipline. Leave the freshness rows explicitly open; never create a self-receipt loop. Recorded the current memory-floor failure, superseding leaf state, host-operator ownership, remediation, next safe action, and explicitly open freshness rows; no full-suite/Graphify/CBM/gbrain operation ran.

### Task 5: Branch hygiene and final receipts
- [x] Clean up fully-landed branches only after verifying supersession: confirm the two unpushed commits on local `codex/r2b-capture-rotator-lock` (`0826154`, `b9e0c15`) touch only `.planning/STATE.md` and `docs/plans/goalex-r4-r2b-landing-exact-head-ci-green-merge-pr.md` receipts whose facts are already recorded on merged `main` (diff them against main's copies). Then delete local branches `codex/r2b-capture-rotator-lock`, `codex/r2b-main-reconciliation`, `codex/r2b-code-review-fixes`, `codex/r2b-review-reconciliation`, and the merged remote branches (`git push origin --delete` for `codex/r2b-capture-rotator-lock`, `codex/r2b-main-reconciliation`, and the two branches merged this round). If any unpushed commit contains facts NOT on main, keep that branch and record it in `.planning/STATE.md` instead of deleting. Supersession review confirmed `b9e0c15`'s plan is present and completed on main, but `0826154` uniquely records three failed hardware samples; local `codex/r2b-capture-rotator-lock` was therefore preserved at `0826154` and recorded in `.planning/STATE.md`. Deleted the other three listed local branches and all four fully merged remote branches without force. A later Task 4 gate-record delivery used PR #19 from `codex/r2b-review-refresh-gate`; review re-verified that its head `edd0b609daae7c194337c72e7212896dbf512d30` is an ancestor of `main`, then deleted that lingering local and remote branch without force.
- [x] Finish with a clean tree and `main == origin/main`. In your final result note record: the review-hardening merge SHA and PR number, exact-head and post-merge CI run ids for both PRs, the reconciliation merge SHA, the admission-gate outcome from Task 4 (refresh receipts, or the exact failed check and samples), the branch cleanup performed, the recorded expired-certificate blocker, explicit confirmation that no live/protected/public/Vault/CA/`ca.crt` action occurred and no §31/§33 assertion was weakened, and a literal handoff that R2c/R2d — not already-completed R2b work — is the next source-owned slice. Do NOT begin R2c/R2d or any other slice this round. Final receipts: review hardening merged through PR #17 as `5a6ce1921c1537b6090cf40600581f9fe956fe1f`, with exact-head run `29452661004` and post-merge run `29453529951`; reconciliation PR #18 exact-head run `29454727897` merged as `f50cec0ddc65e81c0f819376bcb3224eb6328618`, with post-merge run `29455686269`; Task 4 gate-record PR #19 exact-head run `29457365502` merged head `edd0b609daae7c194337c72e7212896dbf512d30` as `702ca8643f0953a62dfdebea80c28b442470fdfa`, and final `main@435fb5351e5f8bef85b4fd5b26bc2e1690aa6388` passed run `29459840111`. Task 4 rejected refresh admission because samples at `2026-07-15T22:59:07Z`, `22:59:24Z`, and `22:59:40Z` were 53%/55%/55% free memory against the all-three-at-55% floor (load1/load5 1.66/1.97, 1.85/2.00, 1.82/1.99); no full-suite/Graphify/CBM/gbrain refresh ran. The historical certificate-expiry blocker at `2026-07-14T23:52:36Z` remains recorded; the later read-only preflight observed an externally refreshed leaf expiring `2026-07-16T21:18:25Z`. Branch cleanup followed the preserved-local-branch exception above and deleted the fully landed PR #19 branch locally and remotely. No live/protected/public/Vault/CA/`ca.crt` action occurred and no §31/§33 assertion was weakened. R2c/R2d — not already-completed R2b work — is the next source-owned slice.
