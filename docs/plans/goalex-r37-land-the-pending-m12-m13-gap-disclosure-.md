# Plan: Land the Pending M12/M13 Gap-Disclosure Delivery Stranded on the Controller Branch

## Overview

Repository: `/Users/admin/.codex/worktrees/9697/Mnemosyne` (worktree of the Mnemosyne repo),
controller branch `codex/goalex-whole-memory-pilot`. Canonical `main` is
`a8e9444ca54633707e88263ce3e0307c5731fc9d` (merged PR #89, post-merge CI `30672194635`).

Authority (do not create a second roadmap): `.planning/STATE.md`,
`.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md`, and the committed lease map
`docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md` **as it stands on
current main**. Under that map, `eval/public/README.md` and `tests/test_public_*` belong to
the **public-harness integration owner**; the pilots plan doc belongs to the **GoalEx
lifecycle owner**. Current admitted coding concurrency is zero other writers, so this single
serialized lane owns both surfaces for the duration of this round. Never write directly to
`main`, never force-push, never bypass hooks, never dismiss review findings.

**The problem this round fixes.** Rounds 19–36 left committed work on the controller branch
that was never delivered through a PR. `git diff --stat main..HEAD` shows these non-plan,
non-lifecycle files differ from `main`:

- `eval/public/README.md` (+15): M12 fixture-size / recurrence / lateness gap disclosures and
  M13 seed / capacity / no-promotion-control gap disclosures.
- `tests/test_public_pm_bench_triggerbench.py` (+57): tests pinning the M12 disclosures.
- `tests/test_public_working_memory_action_probe.py` (+48): tests pinning the M13 disclosures.
- `tests/test_production_mcp_client_cert_rotator.py` (+13/-3): replaces hard-coded 10s/15s
  waits in `test_rotator_holds_process_lock_for_entire_invocation` with
  `ROTATOR_LOCK_TEST_TIMEOUT_SECONDS = 120` and a 3× child deadline (flake fix).
- `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md` (+177/-…):
  M01/M10, M12/M13 and M15 delivery checkpoints and the Task 5/7/8 checkbox closures. The
  branch copy of this file itself says the Task 7/8 work "are not on main and are still
  pending PR delivery".

`GOAL.md`, `.planning/STATE.md`, and the lease map also differ from `main`, but only because
the controller branch already recorded PR #89's *post-merge* receipts (`main@a8e9444c`,
CI `30672194635`) that could not exist inside PR #89 itself. **Those three lifecycle files are
OUT OF SCOPE for this round's PR** — they are updated on the controller branch in Task 4 and
land in a later round, so this PR stays a single coherent public-harness delivery.

Honest-labelling constraints still apply: nothing here promotes a module, changes a
measurement, or creates a benchmark/publication/headline claim. M12/M13 remain `PROPOSED`,
`publishable:false`, `pbpp_headline_eligible:false`. Do not fabricate CI run IDs, review
results, or evidence — every receipt recorded must be one you actually observed.

## Validation Commands

- `git -C /Users/admin/.codex/worktrees/9697/Mnemosyne fetch --prune origin`
- `git -C /Users/admin/.codex/worktrees/9697/Mnemosyne diff --stat main..HEAD -- eval/ tests/ docs/superpowers/`
- `PYTHONPATH=src uv run --extra mcp pytest -q tests/test_public_pm_bench_triggerbench.py tests/test_public_working_memory_action_probe.py`
- `PYTHONPATH=src uv run --extra mcp pytest -q tests/test_production_mcp_client_cert_rotator.py -k lock`
- `uv run ruff check eval/public tests/test_public_pm_bench_triggerbench.py tests/test_public_working_memory_action_probe.py tests/test_production_mcp_client_cert_rotator.py`
- `git diff --check`
- `gh pr view <N> --json mergeable,mergeStateStatus,reviewDecision,statusCheckRollup`
- Final gate (must exit 0 in the controller worktree):
  ```bash
  set -euo pipefail
  test "$(pwd -P)" = "/Users/admin/.codex/worktrees/9697/Mnemosyne"
  test "$(git branch --show-current)" = "codex/goalex-whole-memory-pilot"
  test -z "$(git status --porcelain)"
  git fetch --prune origin
  test "$(git rev-parse main)" = "$(git rev-parse origin/main)"
  git merge-base --is-ancestor 661343ce05186e9a7f0f0740d1edef7c23532857 main
  git merge-base --is-ancestor a95fe4d291093253f8ce49adff32ba875a35e884 main
  git merge-base --is-ancestor baf5c1852593885e37eed75da69b02d93e1bff11 main
  test -f .planning/STATE.md
  test -f .planning/ROADMAP.md
  test -f .planning/REQUIREMENTS.md
  test -f docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md
  test -f docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md
  ```

### Task 1: Recompute the baseline and open one isolated lane for the stranded delta
- [x] From the controller worktree, run `git fetch --prune origin`, confirm the tree is clean, and confirm `main == origin/main` (expected `a8e9444c…`). Record the exact SHA. — verified clean; `main` = `origin/main` = `a8e9444ca54633707e88263ce3e0307c5731fc9d`.
- [x] Confirm no other writer holds the lease: `gh pr list --state open` must show no PR touching `eval/public/README.md`, `tests/test_public_*`, or the pilots plan; check for other worktrees with `git worktree list` and reject the round if another lane is dirty on these paths. — `gh pr list --state open` returned `[]` (zero open PRs); scanned all 35 registered worktrees with `git status --porcelain` limited to the five leased paths and none is dirty.
- [x] Capture the exact stranded delta: `git diff main..HEAD -- eval/public/README.md tests/test_public_pm_bench_triggerbench.py tests/test_public_working_memory_action_probe.py tests/test_production_mcp_client_cert_rotator.py docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md > /tmp/round37-delta.patch` and confirm it is non-empty and touches exactly those five files. — patch is 512 lines, `diff --git` headers name exactly those five files, `--stat` shows 274 insertions / 36 deletions.
- [x] Create an isolated lane worktree/branch from then-current clean `origin/main` (e.g. branch `codex/m12-m13-gap-disclosure-delivery`). Do NOT branch from the controller branch, and do not consume anything from `/Users/admin/Mnemosyne.codex-whole-memory-benchmark-spec` or `/Users/admin/Mnemosyne.codex-phase16-signed-publication`. — lane worktree `/Users/admin/Mnemosyne.codex-m12-m13-gap-disclosure-delivery` on branch `codex/m12-m13-gap-disclosure-delivery`, HEAD `a8e9444ca54633707e88263ce3e0307c5731fc9d` (branched from `origin/main`, not the controller branch), tree clean.

### Task 2: Apply and prove the delivery in the lane
- [x] Apply `/tmp/round37-delta.patch` in the lane. If any hunk conflicts with current `main`, resolve by re-deriving the intent from the controller-branch file content — never weaken a test or delete a disclosure to make it apply. — `git apply --3way` applied all five files cleanly with zero conflicts; no hunk required re-derivation, no test weakened, no disclosure dropped.
- [x] Re-read the applied README paragraphs and confirm every claim is true of the committed fixtures on current `main` (M12: seed `7`, one case / five tasks / seven steps for `pm-bench-development`; seed `7`, twenty one-step cases, no calibrated baseline for `triggerbench-development`; M13: seed `94125`, six cases, no capacity parameter, no promotion control). Correct any statement that the fixtures do not actually support, and fix the pinning test to match reality rather than the other way round. — read the fixtures directly: `pm-bench-development` seed `7`, 1 case, 5 tasks, 7 steps; `triggerbench-development` seed `7`, 20 cases each with exactly 1 step and no `baseline`-bearing key at any nesting depth; `working-memory-action-development` seed `94125`, 6 cases (one per declared item category), `operating_point == {"policy": "highest-task-relevance-then-item-id", "positive_threshold": 0.75}` with no capacity parameter and no `arm`/`control`/`condition` key at any depth. Recurrence exists only as task `regularity` metadata; `late` is a plain count in the adapter with no magnitude/cost field. Every README claim held — no correction needed.
- [x] Confirm the delta introduces no admission-state, publishability, headline, comparability, or measurement change: M12/M13 stay `PROPOSED` / `publishable:false` / `pbpp_headline_eligible:false`. — the delta touches only the README, three test files and the pilots plan; `eval/public/registry.json`, the fixtures and all adapter/scoring code are untouched, and both fixtures still carry `publishable:false` / `headline_eligible:false`. Every status line added to the pilots plan restates `PROPOSED` / non-publishable / non-headline-eligible.
- [x] Run the focused suites and Ruff from the Validation Commands, plus `git diff --check`. All must pass. For the cert-rotator lock test, confirm it passes with the new timeouts and does not merely skip. — 48 passed for the two public suites; 6 passed for `-k lock` with no skips reported under `-rs`; `test_rotator_holds_process_lock_for_entire_invocation` run alone reports `1 passed, 288 deselected in 26.87s` (a real pass, not a skip). `ruff check` → "All checks passed!"; `git diff --check` and `git diff --cached --check` both clean.
- [x] Commit with a descriptive message scoped to this delivery (no "fix: address code review findings" placeholders). — lane commit `7b5b9c03` "docs(eval): land M12/M13 development gap disclosures with pinning tests", body enumerating each disclosed M12/M13 gap, the cert-rotator lock-timeout root cause, and the no-status-change statement.

### Task 3: Deliver through a normal reviewed PR
- [ ] Push the lane branch and open a PR against `main`. The body must state: this lands the previously stranded M12/M13 gap-disclosure documentation and its pinning tests plus a cert-rotator lock-timeout flake fix; it changes no benchmark, measurement, admission state, or publication claim; it is development-source only.
- [ ] Wait for exact-head CI on the final PR head. If a required job fails, diagnose the root cause and fix it in the lane (smallest tested change); re-push and re-verify on the new exact head. Do not merge on a stale head.
- [ ] Address every review finding (CodeRabbit/Greptile/human) on its merits — fix or reply with concrete evidence. Never dismiss a finding silently.
- [ ] When exact-head CI is green, reviews are cleared, and `gh pr view` reports mergeable, merge normally (no force-push, no direct write to `main`). Record the PR number and merge commit SHA.

### Task 4: Prove post-merge main and reconcile controller truth
- [ ] Fast-forward the controller worktree's local `main` to clean `origin/main` and prove `git rev-parse main == git rev-parse origin/main`; record the new SHA.
- [ ] Watch the exact post-merge `main` CI run for that merge commit and record its real run ID and conclusion. If it fails, diagnose and repair before claiming anything.
- [ ] On the controller branch, update `.planning/STATE.md`, `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md` (merged-baseline list, `Baseline:` line, topological-waves note), and `GOAL.md` to record the new PR number, merge SHA, and real post-merge CI run ID — stating plainly that this delivery is development-source documentation/tests only and moved no package status, and that the map is now recomputed from the new main. State explicitly that landing these three lifecycle files on `main` is deferred to the next round's GoalEx-owner PR so leases stay unmixed.
- [ ] Write `docs/plans/goalex-r37-land-the-stranded-m12-m13-gap-disclosure-delivery.md` recording what was delivered, the exact receipts (PR number, merge SHA, exact-head CI run, post-merge CI run), and the remaining open gates (P13-C first real scheduled receipt on/after 2026-08-03, P12-E operator measurement, P13-O official upstream, N12 protected result-v2 lease, SBOX quarantine). Commit the controller branch clean.
- [ ] Re-run the final gate script from Validation Commands and confirm exit code 0.
