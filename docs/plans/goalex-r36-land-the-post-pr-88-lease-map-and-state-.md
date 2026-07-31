# Plan: Land the Post-PR-#88 Lease-Map and STATE Reconciliation

## Overview
This is the Mnemosyne whole-memory benchmark program (GoalEx round 36). You are
the executor; implement exactly this plan and nothing more.

Verified current truth (checked at plan time):
- Canonical repo: `/Users/admin/Mnemosyne`; `main == origin/main ==
  4a891042c25d3a21d7ac4ecfe81a31b43d372370` (merge of PR #88).
- Post-merge `CI` `push` run at that exact SHA: `30659705054`, success.
- No open PRs. No branch named `codex/lease-map-post-pr88` exists.
- The GoalEx controller worktree `/Users/admin/.codex/worktrees/9697/Mnemosyne`
  (branch `codex/goalex-whole-memory-pilot`) is clean and must stay clean; it is
  NOT the place to build the PR branch.

Two GoalEx-owned lifecycle files are stale versus that reality and are the whole
scope of this round:

1. `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md` —
   still `Updated: 2026-07-30`, `Baseline: main@661343ce...`, T0 row `ACTIVE`,
   T1/T2 `BLOCKED`, and its merged-baseline list stops at PR #86. In reality:
   - T0 merged as PR #87 (`main@2ba4ed80`, post-merge CI `30566984814`).
   - T1 wiki reconciliation landed as wiki commit
     `46c34287fe064842e72c3f52a9afad0c822b1846`.
   - T2's single deduplicated CBM/Gbrain refresh completed 2026-07-30 (Gbrain
     milestone `milestones/mnemosyne-pr86-pr87-wiki-canonical-delivery-2026-07-30`).
   - PR #88 (public-regression README documentation + hardened workflow contract
     test + one cert-rotator test fix) merged as `main@4a891042`, post-merge CI
     `30659705054`.
2. `.planning/STATE.md` — frontmatter `last_updated`/`last_activity` stop at
   2026-07-30 and `stopped_at` still pins Phase 13 to `main@661343ce`.

A previous attempt at this same reconciliation stalled because it also tried to
do a CBM re-index and a Gbrain milestone update. Do NOT do any memory-tool work
this round; it is explicitly deferred.

Hard constraints:
- Change exactly two files. No other repo file, no wiki commit (PR #88 changed no
  benchmark boundary, claim, or status any wiki page asserts — record that fact
  in the map's T1 receipt instead of editing the wiki).
- Never write directly to `main`; never force-push; never bypass hooks.
- `tests/test_planning_traceability.py::test_phase_13_truth_lease_names_existing_authoritative_files`
  requires the map's T0 row to keep starting with `| T0 |`, to keep the exact
  backticked paths
  `.planning/phases/13-external-benchmark-adapters-and-scheduled-ci/13-01-PLAN.md`
  and `...13-01-SUMMARY.md`, and to NOT contain `13-source-adapter-parity`.
  Change only that row's status word and receipt text.
- Admit no new implementation package. result-v2 (N12), SBOX, P12-E, P13-O,
  Phase 14/15, P16-L, U-MODULES stay blocked verbatim, and the map must keep
  stating that current safe coding concurrency is **zero new implementation
  writers**.
- P13-C stays an open external gate: `public-regression.yml` cron is
  `23 7 * * 1` (Mondays 07:23 UTC); only manual dispatch `30561430522` exists;
  the first eligible real `schedule` event is 2026-08-03; manual dispatch is not
  a substitute. Do not fabricate a receipt. (Note: `30619319380` is the separate
  `CI` workflow's schedule run and is NOT a P13-C receipt.)

## Validation Commands
- `git -C /Users/admin/Mnemosyne fetch --prune origin && git -C /Users/admin/Mnemosyne rev-parse origin/main`
- `python -m pytest tests/test_planning_traceability.py tests/test_public_regression_workflow.py -q` (in the execution checkout)
- `ruff check .` (in the execution checkout)
- `git diff --name-only origin/main | sort` (must print exactly `.planning/STATE.md` and `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`)
- `gh pr view <pr> --json state,mergeable,reviewDecision,statusCheckRollup`

### Task 1: Open an isolated execution lane
- [ ] `git -C /Users/admin/Mnemosyne fetch --prune origin`; confirm `main == origin/main == 4a891042c25d3a21d7ac4ecfe81a31b43d372370`, `git -C /Users/admin/Mnemosyne status --porcelain` is empty, and `gh pr list --state open` is empty.
- [ ] Preferred lane: `git -C /Users/admin/Mnemosyne worktree add /Users/admin/Mnemosyne.codex-lease-map-r36 -b codex/lease-map-post-pr88 origin/main`. If (and only if) worktree creation is unavailable in this environment, fall back to working in `/Users/admin/Mnemosyne` itself via `git -C /Users/admin/Mnemosyne checkout -b codex/lease-map-post-pr88 origin/main`, and restore it to `main` in Task 3.
- [ ] Confirm the execution checkout is clean and that no other checkout has dirty `.planning/` or `docs/coordination/` files (`git -C <each relevant worktree> status --porcelain`); if another writer holds those surfaces, stop and report instead of overwriting.

### Task 2: Recompute the two leased files and prove them locally
- [ ] In `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`: set `Updated: 2026-07-31` and `Baseline: main@4a891042c25d3a21d7ac4ecfe81a31b43d372370`; append to the "Merged baseline" list PR #87 (canonical truth, `main@2ba4ed80`, post-merge CI `30566984814`) and PR #88 (public-regression documentation and contract-test hardening, `main@4a891042`, post-merge CI `30659705054`).
- [ ] Rewrite the T0 row status `ACTIVE` → `MERGED` with its PR #87 receipts (preserving the `| T0 |` prefix and both exact backticked `13-01-PLAN.md`/`13-01-SUMMARY.md` paths); mark T1 complete (wiki commit `46c34287fe064842e72c3f52a9afad0c822b1846`; PR #88 required no further wiki change) and T2 complete (single deduplicated refresh of 2026-07-30, Gbrain milestone `milestones/mnemosyne-pr86-pr87-wiki-canonical-delivery-2026-07-30`).
- [ ] Update the P13-C row/receipt with: cron `23 7 * * 1`, only manual run `30561430522` exists, first eligible real `schedule` event 2026-08-03, manual dispatch is not a substitute. Update the "Topological waves" text so T0–T2 read complete with no admitted source node; leave every other row and the zero-new-implementation-writers statement verbatim.
- [ ] In `.planning/STATE.md`: set `last_updated: "2026-07-31T<UTC now>Z"` and `last_activity: 2026-07-31`; update `stopped_at` so Phase 13's merged source contracts and scheduled development CI reference `main@4a891042` instead of `main@661343ce`, keeping the rest of that sentence's meaning; extend the "Last activity" narrative with PR #88's merge SHA, post-merge CI `30659705054`, the still-open first scheduled-cadence receipt (next eligible 2026-08-03), and the fact that no benchmark, measurement, or publication claim changed. Change nothing else in STATE.md and do not touch ROADMAP, REQUIREMENTS, phase plans, or the wiki.
- [ ] Run `python -m pytest tests/test_planning_traceability.py tests/test_public_regression_workflow.py -q` and `ruff check .`; both must pass. Run `git diff --name-only origin/main | sort` and confirm it lists exactly the two leased files.

### Task 3: Ship through the normal PR gates and prove post-merge main
- [ ] Commit (`docs(coordination): recompute lease map and state after PR #88`), push the branch, and open a normal PR whose body states this is a GoalEx-lease truth reconciliation that admits no new implementation package and claims no benchmark, measurement, or publication evidence.
- [ ] Wait for exact-head CI success and review/mergeability clearance; resolve any review threads by fixing the finding (no dismissals), then merge normally.
- [ ] After merge: fast-forward `/Users/admin/Mnemosyne` to `main`, prove `main == origin/main` equals the new merge commit, and confirm a successful post-merge `CI` `push` run at that exact SHA via `gh run list --branch main --limit 5`.
- [ ] Clean up: remove `/Users/admin/Mnemosyne.codex-lease-map-r36` (or, in the fallback lane, return `/Users/admin/Mnemosyne` to `main`); end with every worktree clean. Do NOT run any CBM re-index or Gbrain update this round — record in your final report that the deduplicated memory refresh for this reconciliation is deferred to the next round.
