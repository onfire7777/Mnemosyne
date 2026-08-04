# Plan: Restore canonical main to green, then land the M03 registry admission (T9)

## Overview

You are the executor for GoalEx round 47 in the controller worktree
`/Users/admin/.codex/worktrees/9697/Mnemosyne` on branch
`codex/goalex-whole-memory-pilot`. Read `GOAL.md` first — it is authority. You
have no memory of previous rounds; everything you need is below. Bare `python`
is not on PATH: always use `uv run --locked python …`.

### State verified this round

- Controller worktree is **clean**. `main` = `origin/main` =
  `d7eefb7c3595e786851a7d416ba54ea3997a8b6c`. The controller branch is 2 commits
  ahead of `main` (`c322c3a5`, `6123958c` — round-46 plan-file checkbox ticks).
- `gh pr list --state open` is **empty**. No competing writer on any lease.
- Round 46 landed PR #99 (merge `d7eefb7c`, exact head `2375aba5`, exact-head CI
  `30808291831` green): the Round-0 M01–M20 inventory, its derivations,
  `tests/test_wmbs_module_inventory.py`, the `T7` M02/M04/M05 Stage-A disclosure
  in `eval/public/README.md`, `tests/test_public_wmbs_stage_a_disclosure.py`, and
  lease-map nodes `T8` and `T9` as `ADMITTED`.

### Problem 1 — canonical `main` is RED

`gh run view 30894938975 --log-failed` shows one failure and nothing else:

```
FAILED tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files
AssertionError: these PRs merged into origin/main after the recorded baseline
`main@b8673031` but appear nowhere in 2026-07-28-remaining-dependency-write-lease-map.md:
PR #99 — recompute the canonical baseline and record their receipts before admitting further work
1 failed, 4687 passed, 151 skipped, 191 deselected
```

PR #99's own post-merge run `30810160121` failed identically. This is the
by-design lapse the round-46 record predicted; nobody discharged it.

**How the test works** (read `tests/test_planning_traceability.py:34-68` and
`:155-292` before editing anything):
- `LEASE_BASELINE = ^Baseline: `main@([0-9a-f]{40})`$` — the lease map must have
  exactly **one** such line; it defines the baseline SHA.
- `GOAL.md` must literally contain both
  `test "$(git rev-parse main)" = "<40-hex>"` and
  `git merge-base --is-ancestor <40-hex> main`.
- `GOAL.md` and `.planning/STATE.md` must each make **exactly one**
  canonical-baseline claim naming the new 8-char short SHA, in one of two
  recognised phrasings: ``…`main@<short>` … which is the current canonical
  baseline`` or ``current canonical baseline is `main@<short>` ``. Every
  occurrence of the phrase `current canonical baseline` must be one of those
  matches — a reworded claim fails.
- `.planning/STATE.md` needs exactly one `stopped_at: "…"` line whose text
  matches ``at `main@<short>`;`` exactly once.
- `_unrecorded_merged_prs` runs `git log --merges` over
  `<baseline>..refs/remotes/origin/main` and requires every PR number found to
  have a **structured** lease-map bullet matching `^\s*[-*] PR #(\d+)[:,]`.
  Incidental prose does not count. The existing merged-baseline list at
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md:18-88`
  is that list; PR #98's own bullet is at line 88.

**Consequence you must design around:** a PR that lands after the baseline it
records makes `main` red unless the lease map already carries that PR's own
bullet. PR #98 stayed green by pre-recording itself; PR #99 did not and turned
`main` red. Both PRs this round must therefore be pre-recorded **before** either
merges, which is why Task 1 opens both PRs first to reserve their numbers.

Current baseline SHA occurrences to update (historical receipt mentions of
`b8673031` stay as they are — only the *claims* move):
`GOAL.md:620`, `GOAL.md:634`, and the single claim sentence near `GOAL.md:228`;
`.planning/STATE.md:6` (`stopped_at`) and `:352`; lease map line `4`.

### Problem 2 — the M03 registration (node `T9`) is built but uncommitted

Worktree `/Users/admin/.codex/worktrees/9697/Mnemosyne-m03`, branch
`codex/wmb-m03-registry-admission`, at `d7eefb7c`, carries **uncommitted**
round-owned work. Do **not** discard it — it is correct and verified:

- `eval/public/registry.json` — the `wmbs-m03-valid-time-development` entry
  (`dataset_sha256 04c8e8a8…`, `revision fb1d814b…`, `PROPOSED`,
  `publishable:false`, `pbpp_headline_eligible:false`, `headline_eligible:false`,
  `upstream_comparable:false`, `independent_external_reproduction:false`,
  `split_role: development`, `track_kind: DEVELOPMENT`, no `system_seam`).
- `eval/public/runner.py` — `wmbs-m03-valid-time-reference` in `_ADAPTERS` and
  `wmbs-m03-valid-time-v1: ("whole-memory-development", "descriptive")` in
  `_PROFILE_CONTRACTS`.
- `eval/public/bundle.py` — the `allowed_profile` label, plus M03's scored
  denominator (see the disclosure requirement below).
- `eval/public/README.md` (+24 lines) — honest labels and the retained
  bitemporal transaction-time deferral.
- `tests/test_public_wmbs_m03_registry_admission.py` (234 lines, untracked).

Verified by me in that lane: `uv run --locked python -m pytest
tests/test_public_wmbs_m03_registry_admission.py -q` → **22 passed**;
`uv run --locked ruff check eval/public/ tests/test_public_wmbs_m03_registry_admission.py`
→ clean. I did **not** complete a full-suite run; that is Task 2's gate.

**The `bundle.py` denominator change must be disclosed, not hidden.** `T9`'s
lease (lease map line 185) covers `eval/public/bundle.py`, but its enumerated
artifact list names only the `allowed_profile` label. The uncommitted diff also
restructures `verify_bundle`'s trace/metric-count check and adds an M03 branch
to `_scoring_labels`. That work is **necessary and correct**: M03's scorer
returns `total = history_total` = 60 as-of history queries
(`eval/public/scoring.py:274`) against 25 traces (5 timelines × 5 seeds), so the
global `measured["total"] != len(traces)` rule rejects M03 outright. The diff
does not weaken that invariant — it replaces it, for M03 only, with an exact pin
to `len(seeds) × Σ len(timeline["history"])`, and is byte-for-byte
behaviour-preserving for every other profile. Keep it, and **surface** the gap
between `T9`'s enumerated artifacts and what the reachability fix actually
requires in both the PR body and the round record. Per `GOAL.md`, surface — do
not edit the approved node text to match.

### Review-finding adjudications to record (from `.goalex/round-43-review-opus.md`)

1. *[high] `U-MODULES` row vs. merged M02/M04/M05.* **Closed.** The lease-map row
   now excludes PR #96's development-only oracles, and PR #99 landed the `T7`
   disclosure in `eval/public/README.md` plus its pinning suite. Do not revert
   PR #96.
2. *[high] baseline lapse detector red.* **Re-opened and open right now** — this
   is Task 1. It closes when `main` is green again.
3. *[medium] M04/M05 fixture events violate `$defs.portable_event`.* **Closed**
   on `main` by `a3d726f0` plus `tests/test_public_wmbs_portable_event_abi.py`,
   which I ran at controller HEAD: **7 passed**.

### Hard rules

Never force-push, never write to `main` directly, never bypass hooks, never
dismiss a finding without evidence. Change no fixture byte, no scorer logic, no
schema. Move no `progress.percent`, `progress.completed_plans`, or
`progress.completed_phases`. M03 stays `PROPOSED` — this is reachability only.
M02/M04/M05 stay unregistered. To bring the lane up to date use `git merge main`
inside the lane, never a rebase of a pushed branch. `GOAL.md` rule 11: the
controller worktree must be clean when you yield.

## Validation Commands

- `test "$(git rev-parse main)" = "$(git rev-parse origin/main)"`
- `uv run --locked python -m pytest tests/test_planning_traceability.py -q`
- `uv run --locked python -m pytest tests/test_public_wmbs_m03_registry_admission.py tests/test_public_eval.py tests/test_public_whole_memory_reference.py -q`
- `uv run --locked python -m pytest -q`
- `uv run --locked ruff check .`
- `uv run --locked python -c "from eval.public.runner import load_registry; print(sorted(load_registry()))"`
- `gh run list --branch main --limit 3`
- `git status --porcelain --untracked-files=all --ignored` (controller worktree, at round end)

### Task 1: Recompute the canonical baseline and land it as PR-A, unblocking main

- [ ] Confirm the starting state: controller worktree clean, `main` = `origin/main` = `d7eefb7c3595e786851a7d416ba54ea3997a8b6c`, `gh pr list --state open` empty. Reproduce the red test locally with `uv run --locked python -m pytest tests/test_planning_traceability.py -q` and paste the failure into the round record.
- [ ] Reserve both PR numbers before writing any receipt text. In the lane worktree, commit the existing M03 work (Task 2 step 1) and push `codex/wmb-m03-registry-admission`; open it as a **draft** PR and note its number as `N_B`. Push the controller branch and open PR-A; note its number as `N_A`. Do not merge anything yet.
- [ ] In `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`: set line 4 to ``Baseline: `main@d7eefb7c3595e786851a7d416ba54ea3997a8b6c` ``; append to the merged-baseline bullet list (after PR #98's bullet at line 88) a `- PR #99: …` bullet carrying its real receipts (merge `d7eefb7c`, exact head `2375aba5`, exact-head CI `30808291831`; post-merge CI `30810160121` **failed** on the baseline lapse detector, which this PR discharges — record that honestly), a `- PR #N_A: …` bullet describing this recomputation, and a `- PR #N_B: …` bullet describing the reserved `T9` M03 registry admission. Mark `N_A` and `N_B` as pending with no CI numbers — **never invent a run id or merge SHA that does not exist yet**.
- [ ] Mark nodes `T7` and `T8` `MERGED` in the package DAG table with PR #99's receipts. Leave `T9` `ADMITTED`. Update the "Current delivery wave" and concurrency-ceiling paragraphs to name the true state.
- [ ] Update `GOAL.md`: line 620's `git merge-base --is-ancestor …` and line 634's `test "$(git rev-parse main)" = "…"` to the 40-hex `d7eefb7c3595e786851a7d416ba54ea3997a8b6c` (keeping the existing `b8673031…` ancestry line and adding the new one), and move the single canonical-baseline **claim** to `main@d7eefb7c` in one of the two recognised phrasings. Update `.planning/STATE.md` line 6 `stopped_at` and its one claim sentence the same way. Verify with `uv run --locked python -m pytest tests/test_planning_traceability.py -q` that GOAL.md and STATE.md each make exactly one claim.
- [ ] Push PR-A, get exact-head CI green, merge normally, fast-forward local `main`, and prove `git rev-parse main` equals `git rev-parse origin/main`. Then confirm the post-merge `main` CI run passes — this is the receipt that `main` is green again.

### Task 2: Land the M03 registry admission (node T9) as PR-B

- [ ] In `/Users/admin/.codex/worktrees/9697/Mnemosyne-m03`, commit the four modified files plus the untracked `tests/test_public_wmbs_m03_registry_admission.py` with a message naming node `T9` as the authorizing lease. (If Task 1's reservation step already committed and pushed this, skip to the merge-forward step.) Do not alter the diff's substance.
- [ ] After PR-A merges, bring the lane up to date with `git merge main` inside the lane — **not** a rebase — resolving nothing but genuine conflicts, and push.
- [ ] In the lane, run `uv run --locked python -m pytest tests/test_public_wmbs_m03_registry_admission.py tests/test_public_eval.py tests/test_public_whole_memory_reference.py -q`, then the full suite `uv run --locked python -m pytest -q`, then `uv run --locked ruff check .`. Fix only what this change breaks. Confirm `load_registry()` now lists `wmbs-m03-valid-time-development`.
- [ ] Mark PR-B ready for review. Its body must state exactly what it registers, that M03's admission state is unchanged and full bitemporal transaction-time stays a hard deferral, and — explicitly — that the `eval/public/bundle.py` scored-denominator handling is within `T9`'s exact lease path but beyond the artifacts `T9`'s row enumerates, with the `total`=60 vs 25-trace evidence and the fact that non-M03 profiles are unaffected.
- [ ] Clear review threads, get exact-head CI green, merge normally, fast-forward local `main`, prove it equals clean `origin/main`, and confirm the post-merge `main` CI run.
- [ ] If a genuine blocker prevents landing — a validator rejecting the entry, a digest irreconcilable without editing fixture bytes, or a CI failure rooted outside this change — stop, leave the lane branch intact, and record the exact blocker and evidence in the round record. Do not edit fixtures, scorers, or the schema to force it through, and do not substitute a different module.

### Task 3: Record receipts and end the controller worktree clean

- [ ] Remove the M03 worktree (`git worktree remove /Users/admin/.codex/worktrees/9697/Mnemosyne-m03`) and confirm `git worktree list` shows only `/Users/admin/Mnemosyne` and the controller worktree.
- [ ] Tick the now-satisfied Task 3/4 checkboxes in `docs/plans/goalex-r46-land-the-stranded-t7-inventory-delivery-.md` and write the round record `docs/plans/goalex-r47-<slug>.md` containing: the red-`main` diagnosis with run ids `30810160121` and `30894938975`; the three review adjudications above; both PRs' receipts (merge SHA, exact head, exact-head CI run id, post-merge CI run id); the `bundle.py` scope disclosure; and the standing note that `docs/plans/wmb-m14-procedural-task-utility-implementation-plan.md` self-declares `PLANNING ARTIFACT ONLY — NOT CODE-READY`, which the inventory's ranking of M14 as the cheapest plan-having module does not reflect — surfaced, not edited.
- [ ] On the controller branch, update the lease map, `.planning/STATE.md`, and `GOAL.md` with both PRs' real post-merge receipts and mark `T9` `MERGED`. Move no progress counter. Note explicitly that the recorded baseline `main@d7eefb7c` is now one merge behind by the accepted terminal-receipt property, so the next round recomputes it — and that both PRs pre-recorded themselves so `main` is green, not red, in the meantime.
- [ ] Commit all of the above on the controller branch as the round's final step and confirm `git status --porcelain --untracked-files=all --ignored` shows nothing beyond the permitted ignored baseline before yielding.
