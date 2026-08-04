# Plan: Finish the half-landed baseline recomputation, then close M03 through the inventory coupling

## Overview

You are the executor for GoalEx round 48 in the controller worktree
`/Users/admin/.codex/worktrees/9697/Mnemosyne` on branch
`codex/goalex-whole-memory-pilot`. Read `GOAL.md` first — it is authority. You
have no memory of previous rounds; everything you need is below. Bare `python`
is not on PATH: always use `uv run --locked python …`.

### State verified this round (do not re-derive it)

- Controller worktree **clean**. `main` = `origin/main` = `d7eefb7c`.
  Controller branch local HEAD `e1097b8e`; `origin` has only `cd3bad01`, so the
  last two commits (`d198e046`, `e1097b8e`, both auto-generated watchdog
  preservation commits carrying real lease-map content) are **unpushed**. They
  are correct — keep them; do not rewrite pushed history.
- **Two draft PRs already exist and are already recorded in the lease map.** Do
  not open new ones.
  - **PR #101** ← `codex/goalex-whole-memory-pilot`, head `cd3bad01`, DRAFT,
    MERGEABLE. Title: *fix: recompute the canonical baseline to main@d7eefb7c
    and discharge the PR #99 lapse*.
  - **PR #100** ← `codex/wmb-m03-registry-admission`, head `7df036ef`, DRAFT,
    MERGEABLE, in worktree `/Users/admin/.codex/worktrees/9697/Mnemosyne-m03`
    (clean, one commit ahead of `main`).
- Canonical `main` is **RED**: runs `30810160121` (PR #99 post-merge) and
  `30894938975` (scheduled) both fail on exactly
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  — PR #99 merged after the recorded baseline `main@b8673031` without
  pre-recording itself.
- **Round 47 already did half of Task 1.** On the controller branch the lease
  map `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`
  already carries `Baseline: main@d7eefb7c3595e786851a7d416ba54ea3997a8b6c`
  (line 4), the in-body "recomputed from the new baseline `main@d7eefb7c`"
  claim, and structured bullets for **PR #99** (with its real receipts and the
  honest record that its post-merge run failed), **PR #101**, and **PR #100**
  (both marked pending, no invented run ids). **Do not redo that work.**
- Still missing, which is why the test is red: `GOAL.md` and
  `.planning/STATE.md` still name `main@b8673031`, and lease-map rows `T7`/`T8`
  are still `ADMITTED`.

### What the traceability test requires (read `tests/test_planning_traceability.py:34-68` and `:155-250`)

With `sha = d7eefb7c3595e786851a7d416ba54ea3997a8b6c`, `short = d7eefb7c`:

- The lease map must contain exactly one ``Baseline: `main@<40-hex>` `` line — it
  already does.
- `GOAL.md` must literally contain both
  `test "$(git rev-parse main)" = "d7eefb7c3595e786851a7d416ba54ea3997a8b6c"`
  (currently `b8673031…` at line 634) and
  `git merge-base --is-ancestor d7eefb7c3595e786851a7d416ba54ea3997a8b6c main`
  (add it after the existing `b8673031…` ancestry line at 620; keep that line).
- `GOAL.md` and `.planning/STATE.md` must each make **exactly one**
  canonical-baseline claim naming `main@d7eefb7c`, in one of two recognised
  forms: ``…`main@d7eefb7c` … which is the current canonical baseline`` or
  ``current canonical baseline is `main@d7eefb7c` ``. **Gotcha:** the first
  regex is `` `main@([0-9a-f]{8})`(?:(?!main@)[^.])*?which is the current
  canonical baseline`` — it matches across whitespace-normalized text but
  **cannot cross a `.` character or another `main@`**. So no period and no other
  `main@` may sit between the SHA and the phrase. Every occurrence of the bare
  phrase `current canonical baseline` in each file must be one of those matches,
  so move the claim rather than adding a second one. Today's single occurrences
  are `GOAL.md:228-229` (inside the PR #98 sentence) and `.planning/STATE.md:352`.
- `.planning/STATE.md` needs exactly one `stopped_at: "…"` line, and inside it
  the substring ``at `main@d7eefb7c`;`` exactly once (note the required
  trailing semicolon). Line 6 currently says ``at `main@b8673031`;``.
- `_unrecorded_merged_prs` requires every PR merged into `origin/main` after the
  baseline to have a structured lease-map bullet matching `^\s*[-*] PR #(\d+)[:,]`.
  #99, #100, #101 are already recorded, so both PRs this round stay green when
  they land after the baseline they record.

### The new finding this round must handle

PR #100's CI run `30943834723` failed with **two** tests, not one. Only the
`Unit + drift checks` job failed; Lint, Provider conformance, Postgres, and both
native-wheel jobs passed (`2 failed, 4708 passed, 151 skipped`).

1. the baseline lapse above — inherited from `main`, fixed by PR #101 plus a
   `git merge main` in the lane;
2. `tests/test_wmbs_module_inventory.py::test_registry_cells_match_registry_json`
   — `M03: registry cell says no, but registry.json has
   {'wmbs-m03-valid-time-development'}`.

PR #99 landed a drift test that pins
`docs/coordination/2026-08-03-wmbs-module-completeness-inventory.md` to the tree.
Registering M03 therefore **requires** editing that inventory in the same
commit — the registry entry and the inventory row must move atomically or the
test fails in one direction or the other. That path is in node `T8`'s lease, and
`T9`'s row at lease-map line 213 explicitly asserts "It does not overlap `T8`'s
`tests/test_wmbs_module_inventory.py`". Per `GOAL.md`, **surface that
contradiction; do not edit `T9`'s row text to widen it.** The precedent for one
serialized writer holding two leases is `T7`+`T8` landing as a single PR, and
GoalEx owns both leases here with no competing writer (no other open PRs).

Concrete inventory edits required (`docs/coordination/2026-08-03-wmbs-module-completeness-inventory.md`;
helpers are at `tests/test_wmbs_module_inventory.py:20-113`, counts test at `:455`):

- **M03 row (line 51), `registry` cell:** currently `**no**`. A cell is "absent"
  iff it starts with `**no`. Replace with a `yes` cell citing the suite name in
  backticks so it matches `` `([a-z0-9-]+-development)` `` — i.e.
  `` `wmbs-m03-valid-time-development` `` — and cite only paths/line numbers that
  really exist (`test_every_referenced_path_exists_with_the_claimed_line`
  validates every backticked path and `:line` in the row).
- **M03 row, `next_step` cell:** rewrite from "the missing artifacts are …" to
  the delivered state.
- **The five bolded `N of 20` counts** are re-derived by
  `test_correction_counts_match_the_table` in the fixed order
  `[scorer_bearing, registry_admitted, planned, greenfield, landed]`, and the
  file must contain **exactly five**. Registering M03 changes two of them:
  correction item 2 (line ~94) `M01, M10, M12, M13 — 4 of 20` → must become
  `M01, M03, M10, M12, M13 — **5 of 20.**`, and correction item 6 (line ~129)
  `M01, M10, M12, M13, M15 — 5 of 20` → `M01, M03, M10, M12, M13, M15 — **6 of
  20.**`. Item 6's clause "the same headline number" becomes false — reword it
  honestly.
- **Correction item 5** (line ~118) states M03's "sole missing artifact is a
  `registry.json` entry" — update to record it as delivered.
- **"Highest-value next gaps" item 1** (line ~140) ranks M03 as the cheapest
  remaining gap. It is no longer a gap: remove or rewrite it and renumber the
  list, keeping items 2-6 intact.
- `docs/coordination/2026-08-03-wmbs-module-completeness-derivation.md` is a
  dated Round-0 derivation snapshot and is **not** test-pinned. Do not rewrite
  its history; if you touch it at all, add only a dated one-line note that
  PR #100 superseded its §2 registry count.

### Review-finding adjudications (from `.goalex/round-43-review-opus.md`) — verified by me at controller HEAD

1. *[high] `U-MODULES` row vs merged M02/M04/M05.* **Closed.** Lease-map line 228
   now excludes PR #96's development-only oracles, and PR #99 landed the `T7`
   disclosure plus `tests/test_public_wmbs_stage_a_disclosure.py`. Do not revert
   PR #96.
2. *[high] baseline lapse detector red.* **Open — this is Task 1.**
3. *[medium] M04/M05 fixture events violate `$defs.portable_event`.* **Closed** on
   `main` by `a3d726f0` plus `tests/test_public_wmbs_portable_event_abi.py`,
   both present at HEAD.

Restate all three in the round record with this evidence.

### Hard rules

Never force-push, never write to `main` directly, never bypass hooks, never
dismiss a finding without evidence. Change no fixture byte, no scorer logic, no
schema. Move no `progress.percent`, `progress.completed_plans`, or
`progress.completed_phases`. M03 stays `PROPOSED` / `publishable:false` /
`pbpp_headline_eligible:false`; full bitemporal transaction-time stays a hard
deferral. Bring the lane up to date with `git merge main` inside the lane, never
a rebase of a pushed branch. Never invent a merge SHA or CI run id that does not
exist yet. `GOAL.md` rule 11: the controller worktree must be clean when you
yield. Each CI cycle takes ~25 minutes — land PR #101 first, because it alone
turns `main` green.

## Validation Commands

- `test "$(git rev-parse main)" = "$(git rev-parse origin/main)"`
- `uv run --locked python -m pytest tests/test_planning_traceability.py tests/test_wmbs_module_inventory.py -q`
- `uv run --locked python -m pytest tests/test_public_wmbs_m03_registry_admission.py tests/test_public_eval.py tests/test_public_whole_memory_reference.py -q`
- `uv run --locked python -m pytest -q`
- `uv run --locked ruff check .`
- `uv run --locked python -c "from eval.public.runner import load_registry; print(sorted(load_registry()))"`
- `gh run list --branch main --limit 3`
- `git status --porcelain --untracked-files=all --ignored`

### Task 1: Finish the baseline recomputation and land PR #101, turning `main` green

- [x] Confirm the start state: controller worktree clean, `main` = `origin/main` = `d7eefb7c`, `gh pr list --state open` shows exactly #100 and #101 as drafts. Reproduce the failure with `uv run --locked python -m pytest tests/test_planning_traceability.py -q` and paste it into the round record.
- [x] Edit `GOAL.md`: change line 634's lapse detector to the 40-hex `d7eefb7c3595e786851a7d416ba54ea3997a8b6c`; add a `git merge-base --is-ancestor d7eefb7c3595e786851a7d416ba54ea3997a8b6c main` line after the existing `b8673031…` ancestry line at 620, keeping that line; and move the single canonical-baseline claim off the PR #98 sentence at 228-229 onto a new sentence recording PR #99 (merge `d7eefb7c`, exact head `2375aba5`, exact-head CI `30808291831`, post-merge run `30810160121` failed the lapse detector) in one of the two recognised phrasings, obeying the no-period / no-second-`main@` constraint above. Leave every historical `b8673031` receipt mention untouched.
- [x] Edit `.planning/STATE.md`: line 6 `stopped_at` so it contains ``at `main@d7eefb7c`;`` exactly once and no other ``at main@…;``, and line 352 so its `current canonical baseline is …` claim names `main@d7eefb7c` with PR #99's receipts.
- [x] In the lease map, mark rows `T7` and `T8` `MERGED` with PR #99's receipts (merge `d7eefb7c`, exact head `2375aba5`, exact-head CI `30808291831`). Leave `T9` `ADMITTED`. Update the "Current delivery wave" and concurrency-ceiling paragraphs to the true state. Do not change the `Baseline:` line or the #99/#100/#101 bullets — they are already correct.
- [ ] Run `uv run --locked python -m pytest tests/test_planning_traceability.py tests/test_wmbs_module_inventory.py -q` and `uv run --locked ruff check .` until clean, commit on the controller branch, push (this updates PR #101 from `cd3bad01`), mark PR #101 ready for review, clear any review threads, get exact-head CI green, and merge normally.
- [ ] Fast-forward local `main`, prove `git rev-parse main` = `git rev-parse origin/main`, and record PR #101's merge SHA, exact head, exact-head CI run id, and post-merge `main` CI run id. The post-merge run passing is the receipt that `main` is green again.

### Task 2: Close the M03 inventory coupling in the lane and get PR #100 green

- [ ] In `/Users/admin/.codex/worktrees/9697/Mnemosyne-m03`, run `git merge main` (never rebase) to pick up PR #101, resolving only genuine conflicts.
- [ ] Apply the inventory edits enumerated in the Overview to `docs/coordination/2026-08-03-wmbs-module-completeness-inventory.md`: the M03 `registry` and `next_step` cells, correction items 2, 5, and 6 with their two changed bolded counts, and the "Highest-value next gaps" item 1 plus renumbering. Keep exactly five `N of 20` bolded counts in their fixed order. Change nothing about M02/M04/M05, M12/M13, or M14.
- [ ] Run in the lane, in order: `uv run --locked python -m pytest tests/test_wmbs_module_inventory.py tests/test_planning_traceability.py -q`, then `uv run --locked python -m pytest tests/test_public_wmbs_m03_registry_admission.py tests/test_public_eval.py tests/test_public_whole_memory_reference.py -q`, then the full `uv run --locked python -m pytest -q`, then `uv run --locked ruff check .`. Fix only what this change breaks. Confirm `load_registry()` now lists `wmbs-m03-valid-time-development`.
- [ ] Commit and push. Do not alter the substance of the existing `7df036ef` diff to `registry.json`, `runner.py`, `bundle.py`, or `README.md`.
- [ ] If a genuine blocker appears — a validator rejecting the entry, a digest irreconcilable without editing fixture bytes, or a failure rooted outside this change — stop, leave the lane branch and PR intact, and record the exact blocker and evidence in the round record. Do not edit fixtures, scorers, or the schema to force it through, and do not substitute a different module.

### Task 3: Land PR #100 with both scope overruns disclosed

- [ ] Rewrite PR #100's body to state exactly what it registers; that M03's admission state is unchanged and full bitemporal transaction-time remains a hard deferral; and **two explicit disclosures**: (a) the `eval/public/bundle.py` scored-denominator handling is inside `T9`'s exact lease path but beyond the artifacts `T9`'s row enumerates — M03's scorer returns `total = history_total` = 60 as-of history queries (`eval/public/scoring.py:274`) against 25 traces (5 timelines × 5 seeds), so the global `measured["total"] != len(traces)` rule would reject M03 outright; the diff replaces that rule for M03 only with an exact pin to `len(seeds) × Σ len(timeline["history"])` and is byte-for-byte behaviour-preserving for every other profile; and (b) this PR writes `docs/coordination/2026-08-03-wmbs-module-completeness-inventory.md`, a path in `T8`'s lease, because PR #99's drift test couples the M03 inventory row to `registry.json` and the two cannot move in separate commits — contradicting `T9`'s row line claiming no overlap with `T8`. Surface the contradiction; do not edit `T9`'s row.
- [ ] Mark PR #100 ready for review, clear review threads, get exact-head CI green (`Unit + drift checks` must pass — it is the only job that failed on `30943834723`), merge normally, fast-forward local `main`, prove it equals clean `origin/main`, and confirm the post-merge `main` CI run passes.

### Task 4: Record receipts and end the controller worktree clean

- [ ] Remove the lane worktree (`git worktree remove /Users/admin/.codex/worktrees/9697/Mnemosyne-m03`) and confirm `git worktree list` shows only `/Users/admin/Mnemosyne` and the controller worktree.
- [ ] Tick the satisfied checkboxes in `docs/plans/goalex-r47-restore-canonical-main-to-green-then-lan.md` and write the round record `docs/plans/goalex-r48-<slug>.md` containing: the red-`main` diagnosis with run ids `30810160121`, `30894938975`, `30943914083`, `30943834723`; the three review adjudications above with their evidence; both PRs' receipts (merge SHA, exact head, exact-head CI, post-merge CI); both scope disclosures from Task 3; and the standing note that round 47 was cut short by the watchdog after reserving both PR numbers, with `d198e046`/`e1097b8e` as the preserved lease-map content.
- [ ] On the controller branch, update the lease map, `.planning/STATE.md`, and `GOAL.md` with both PRs' real post-merge receipts and mark `T9` `MERGED`. Move no progress counter. State explicitly that the recorded baseline `main@d7eefb7c` is now two merges behind by the accepted terminal-receipt property, that both PRs pre-recorded themselves so `main` is green rather than red, and that the next round recomputes the baseline from then-current `main`.
- [ ] Commit all of the above on the controller branch as the round's final step and confirm `git status --porcelain --untracked-files=all --ignored` shows nothing beyond the permitted ignored baseline before yielding.
