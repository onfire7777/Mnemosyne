# Plan: Reconcile Lease Map and STATE to Post-PR-#88 Main

## Overview
This is the Mnemosyne whole-memory program (GoalEx round 35). Canonical
`main == origin/main == 4a891042c25d3a21d7ac4ecfe81a31b43d372370`, the normal
merge of PR #88 (small docs/test hardening: `README.md`,
`tests/test_public_regression_workflow.py`,
`tests/test_production_mcp_client_cert_rotator.py`). Post-merge main CI run
`30659705054` passed at that exact SHA.

Two GoalEx-owned lifecycle files are now stale and must be recomputed from
current main, per GOAL.md's authority rules:

1. `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`
   still says `Baseline: main@661343ce...`, lists T0 as `ACTIVE` ("Canonical
   truth PR after PR #86"), and lists T1/T2 as BLOCKED — but T0 merged as
   PR #87 (`main@2ba4ed80`, post-merge CI `30566984814`), T1 wiki
   reconciliation landed as wiki commit `46c34287fe064842e72c3f52a9afad0c822b1846`,
   and T2's single deduplicated CBM/Gbrain refresh completed on 2026-07-30
   (Gbrain milestone `milestones/mnemosyne-pr86-pr87-wiki-canonical-delivery-2026-07-30`,
   CBM ready at 22,658 nodes / 102,396 edges). PR #88 is also absent from the
   merged baseline list.
2. `.planning/STATE.md` `last_activity`/`Last activity` stop at 2026-07-30
   and do not record PR #88.

Hard constraints:
- These files are under the exclusive GoalEx lifecycle-owner lease; no other
  repo file may change. Never write directly to `main`; deliver via a normal
  branch + PR + review/CI + merge.
- `tests/test_planning_traceability.py::test_phase_13_truth_lease_names_existing_authoritative_files`
  requires the map's T0 row to keep starting with `| T0 |`, to keep the
  backticked paths `.planning/phases/13-external-benchmark-adapters-and-scheduled-ci/13-01-PLAN.md`
  and `...13-01-SUMMARY.md`, and to NOT contain `13-source-adapter-parity`.
  Change only its status word (e.g. `ACTIVE` → `MERGED`) and receipt text.
- Do NOT admit, start, or imply any new implementation package: result-v2
  (N12), sandbox (SBOX), Phase 14/15, official benchmarks, measurements,
  publication, and launch all stay blocked exactly as currently written. The
  map must continue to state that current safe coding concurrency is zero new
  implementation writers.
- P13-C: the merged `public-regression.yml` cron is `23 7 * * 1` (Mondays
  07:23 UTC); only the manual run `30561430522` exists. Record in the map that
  the first eligible real `schedule` event is 2026-08-03 and that manual
  dispatch is not a substitute. Do not fabricate a receipt.
- No wiki edits this round: PR #88 changed no benchmark boundary, claim, or
  status the wiki pages assert, so a wiki commit would be churn; note this
  explicitly in the map's T1 receipt line instead.

Work from a fresh isolated worktree created from clean `origin/main` (e.g.
`git -C /Users/admin/Mnemosyne worktree add /Users/admin/Mnemosyne.codex-lease-map-post-pr88 -b codex/lease-map-post-pr88 origin/main`).
The GoalEx controller worktree `/Users/admin/.codex/worktrees/9697/Mnemosyne`
must not be used for the PR branch and must stay clean.

## Validation Commands
- `git -C /Users/admin/Mnemosyne fetch --prune origin && test "$(git -C /Users/admin/Mnemosyne rev-parse origin/main)" != ""`
- `cd <execution-worktree> && python -m pytest tests/test_planning_traceability.py tests/test_public_regression_workflow.py -q`
- `cd <execution-worktree> && ruff check .`
- `git -C <execution-worktree> diff --name-only origin/main | sort` (must be exactly `.planning/STATE.md` and `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`)
- `gh pr view <new-pr> --json state,mergeable,reviewDecision,statusCheckRollup`

### Task 1: Verify current truth and open an isolated lane
- [ ] Fetch origin in `/Users/admin/Mnemosyne`; prove `main == origin/main == 4a891042c25d3a21d7ac4ecfe81a31b43d372370`, worktree clean, and no open PRs (`gh pr list --state open`).
- [ ] Prove post-merge CI: `gh run list --branch main --limit 5` shows a successful `CI` `push` run `30659705054` at head SHA `4a891042...`; stop with evidence if absent or failing.
- [ ] Create the fresh worktree/branch `codex/lease-map-post-pr88` from `origin/main`; confirm it is clean and no other writer holds the GoalEx lease surfaces (no dirty `.planning/` or `docs/coordination/` anywhere).

### Task 2: Recompute the dependency/write-lease map
- [ ] In `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`: update the `Updated:` date to 2026-07-31 and `Baseline:` to `main@4a891042c25d3a21d7ac4ecfe81a31b43d372370`.
- [ ] Add PR #87 (canonical truth, `main@2ba4ed80`, post-merge CI `30566984814`) and PR #88 (public-regression documentation and contract-test hardening, `main@4a891042`, post-merge CI `30659705054`) to the "Merged baseline" list.
- [ ] Rewrite the T0 row status from `ACTIVE` to `MERGED` with its PR #87 receipts, preserving the exact backticked `13-01-PLAN.md`/`13-01-SUMMARY.md` paths and the `| T0 |` prefix; mark T1 complete (wiki commit `46c34287fe064842e72c3f52a9afad0c822b1846`; PR #88 required no further wiki change) and T2 complete (single deduplicated refresh of 2026-07-30, Gbrain milestone `milestones/mnemosyne-pr86-pr87-wiki-canonical-delivery-2026-07-30`).
- [ ] Update the P13-C row/receipt to record: cron `23 7 * * 1`, only manual run `30561430522` exists, first eligible real schedule event 2026-08-03, manual dispatch is not a substitute. Update the "Topological waves" text so the current delivery wave shows T0–T2 complete and no admitted source node; keep every other row (P12-E, P13-O, SBOX, N12, P14-*, P15-*, P16-L, U-MODULES) blocked verbatim and keep the zero-new-implementation-writers statement.

### Task 3: Reconcile .planning/STATE.md
- [ ] Update frontmatter `last_updated`/`last_activity` to 2026-07-31 and extend the "Last activity" narrative with: PR #88 merged as `main@4a891042` (README public-regression documentation plus hardened workflow contract test and one cert-rotator test fix), post-merge CI run `30659705054` passed; first real scheduled-cadence receipt still open (next eligible 2026-08-03); no benchmark, measurement, or publication claim changed.
- [ ] Make no other STATE.md content change; do not touch ROADMAP, REQUIREMENTS, phase plans, or wiki.

### Task 4: Focused tests, PR, merge, and post-merge proof
- [ ] Run `python -m pytest tests/test_planning_traceability.py tests/test_public_regression_workflow.py -q` and `ruff check .` in the execution worktree; all must pass. Confirm the diff touches exactly the two leased files.
- [ ] Commit, push the branch, and open a normal PR titled `docs(coordination): recompute lease map and state after PR #88`; body must state it is a GoalEx-lease truth reconciliation admitting no new implementation package.
- [ ] Wait for exact-head CI success and review/mergeability clearance, resolve any review threads, then merge normally (no force-push, no direct main writes).
- [ ] After merge: fast-forward canonical `/Users/admin/Mnemosyne` main, prove `main == origin/main` equals the new merge commit with a successful post-merge `push` CI run at that exact SHA, and remove the temporary execution worktree.

### Task 5: Single deduplicated memory refresh
- [ ] Using codebase-memory-mcp, refresh the canonical `/Users/admin/Mnemosyne` index exactly once for the new main head and confirm it reports ready.
- [ ] Update (do not duplicate) the existing Gbrain milestone `milestones/mnemosyne-pr86-pr87-wiki-canonical-delivery-2026-07-30` — or extend it with one entry — recording PR #88's merge SHA, post-merge CI run `30659705054`, this reconciliation PR's merge, and the still-open P13-C/official-benchmark/operator gates; create nothing else and end with all worktrees clean.
