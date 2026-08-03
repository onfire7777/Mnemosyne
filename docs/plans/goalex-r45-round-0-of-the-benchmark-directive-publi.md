# Plan: Round 0 of the benchmark directive — publish the recomputed M01–M20 completeness inventory and deliver the admitted T7 oracle disclosure

## Overview

You are the executor for GoalEx round 45 in the controller worktree
`/Users/admin/.codex/worktrees/9697/Mnemosyne` on branch
`codex/goalex-whole-memory-pilot`. Read `GOAL.md` first — it is authority.
You have no memory of previous rounds; everything you need is below.

**State right now.** Canonical `main` = `origin/main` =
`b8673031a80158c49d552a4b3647829d213243bd`. The controller branch is 5 commits
ahead of `main` and **is not pushed** (`git ls-remote origin
codex/goalex-whole-memory-pilot` is empty). Those commits are round-44 work:
`314b06f7` recomputed the three lifecycle files to `Baseline: main@b8673031`
and admitted lease-map node `T7`; `92a354e7` and `9cd185d8` are operator edits
to `GOAL.md`. The working tree is clean.

**What round 44 left undone.** `T7` is `ADMITTED` at
`docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md:183`. Its
lease is: the M02/M04/M05 Stage-A development gap disclosures in
`eval/public/README.md`, their pinning tests, and the lifecycle files. Only the
lifecycle files were written. The README disclosure and its tests do not exist.
Deliver them in this round.

**The new operator priority (top of `GOAL.md`).** The Whole-Memory Benchmark
Standard specifies modules M01–M20 and most are unimplemented. Round 0 of that
directive is: *"Before choosing module work, produce and commit a
module-by-module completeness table for M01-M20 — for each: does an approved
exact plan exist, a fixture, a scorer, a test suite, a registry entry, and what
is its admission state. Do not trust the counts above; recompute them from the
tree and correct them. That inventory is the backlog and belongs in the
repository."*

**The counts in `GOAL.md` are demonstrably wrong — recompute, do not copy.**
Verified probes:
- `eval/public/wmbs_m01.py`, `wmbs_m02.py`, `wmbs_m04.py`, `wmbs_m05.py`,
  `wmbs_m10.py` exist — but a missing `wmbs_mNN.py` does **not** mean the module
  is absent.
- `eval/public/scoring.py` dispatches profiles `wmbs-m01-v1`,
  `wmbs-m03-valid-time-v1`, `wmbs-m10-v1`; the M03 scorer
  (`_score_wmbs_m03_valid_time`) is implemented **inline in `scoring.py`** with
  no `wmbs_m03.py` file at all.
- `eval/public/fixtures/` holds `wmbs-m01-development.json`,
  `wmbs-m02-retrieval-development.json`,
  `wmbs-m03-valid-time-development.json`, `wmbs-m04-development.json`,
  `wmbs-m05-provenance-development.json`, `wmbs-m10-development.json`.
- `eval/public/registry.json` contains exactly two `wmbs-*` suites:
  `wmbs-m01-development` and `wmbs-m10-development`.
- `eval/public/adapters/whole_memory_reference.py` and `eval/public/bundle.py`
  also reference M03/M12/M13/M15 — search them.
- Per-module plans live in `docs/plans/wmb-m02-…`, `wmb-m04-…`, `wmb-m05-…`,
  `wmb-m14-…`; module authority is
  `docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md`
  (its capability table C01–C24 maps modules) and
  `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`.
- Tests: `tests/test_public_wmbs_m01.py`, `_m02.py`, `_m04.py`, `_m05.py`,
  `_m10.py`, `tests/test_public_wmbs_portable_event_abi.py`; grep `tests/` for
  m03/m12/m13/m15 coverage too.

**Adjudication of the three round-43 review findings (do this, then move on).**
1. *[high] U-MODULES row vs. merged M02/M04/M05.* Already remediated on `main`:
   the row at lease-map line 198 now explicitly **excludes** the development-only
   PR #96 oracles and states they authorize no module implementation, scorer
   admission, or publication claim. Your `eval/public/README.md` disclosure
   completes it by making the same statement in the public harness doc. Record
   this adjudication in the round record; do not revert PR #96.
2. *[high] baseline lapse detector red.* Fixed by branch commits `3c5e2937`
   and `314b06f7`: the three lifecycle files now read `Baseline: main@b8673031`
   and `GOAL.md`'s equality gate passes. Verify, then record as closed.
3. *[medium] M04/M05 events violate `$defs.portable_event`.* Fixed on `main` by
   `a3d726f0` plus `tests/test_public_wmbs_portable_event_abi.py`. **Verify by
   running that test**, and confirm the M04 event no longer carries `source_id`
   and neither module stuffs extra keys into `public_metadata`. If a residual
   violation survives, report it in the round record — do **not** silently
   expand this round into a module fix.

**Hard rules.** Documentation and tests only. Do not change any module
behavior, fixture bytes, `eval/public/registry.json`, adapter, runner routing,
or scoring profile. Do not move `progress.percent`,
`progress.completed_plans`, or `progress.completed_phases`. M02/M04/M05 stay
`PROPOSED` / `publishable:false` / `pbpp_headline_eligible:false`. Never force-push,
never write directly to `main`, never bypass hooks. End the round with a clean
worktree (`GOAL.md` rule 11): commit everything the round touched on the
controller branch as the final step.

## Validation Commands
- `git status --porcelain --untracked-files=all` (must be empty at round end)
- `python -m pytest tests/test_public_wmbs_portable_event_abi.py tests/test_public_wmbs_m01.py tests/test_public_wmbs_m02.py tests/test_public_wmbs_m04.py tests/test_public_wmbs_m05.py tests/test_public_wmbs_m10.py tests/test_planning_traceability.py -q`
- `python -m pytest tests/test_wmbs_module_inventory.py -q`
- `python -m pytest -q` (one authoritative full suite on the stable PR head)
- `ruff check .` and `ruff format --check .`
- `test "$(git rev-parse main)" = "b8673031a80158c49d552a4b3647829d213243bd"` before the merge; after merge, re-run `GOAL.md`'s Verification block against the new baseline.

### Task 1: Recompute the M01–M20 facts from the tree
- [x] For each module M01…M20, search the tree for: a fixture under `eval/public/fixtures/`, a scorer (either `eval/public/wmbs_mNN.py` **or** an inline `_score_wmbs_*` branch in `eval/public/scoring.py` **or** logic in `eval/public/adapters/whole_memory_reference.py` / `eval/public/bundle.py`), a test suite under `tests/`, a `registry.json` entry, and an approved exact implementation plan under `docs/plans/` or `docs/superpowers/plans/`.
- [x] For each module record its admission state from the lease map and registry (`publishable`, `pbpp_headline_eligible`, `PROPOSED` vs admitted), and the module's short name from the standard's capability table.
- [x] Write down the derivation for every non-obvious cell (file path + line) so the inventory is auditable and the test in Task 3 can check it.
- [x] Explicitly note where the counts in `GOAL.md`'s Current Priority section are wrong (at minimum M03's inline scorer) — these corrections go into the inventory document, not into a rewrite of the operator's directive text.

### Task 2: Commit the inventory document
- [ ] Create `docs/coordination/2026-08-03-wmbs-module-completeness-inventory.md` with a header stating it is recomputed from the tree at `main@b8673031` plus this branch, that it is documentation only, and that it authorizes no artifact.
- [ ] Include one row per module M01–M20 with columns: module, capability/short name, approved exact plan, fixture, scorer, test suite, registry entry, admission state, and the cheapest next step per `GOAL.md`'s ladder (plan → freeze → implement → land).
- [ ] Add a short "Corrections to the recorded counts" section listing each figure in `GOAL.md`'s Current Priority that the recomputation contradicts, with evidence.
- [ ] Add a "Highest-value next gaps" section ranking modules that already have a fixture or partial scorer above greenfield ones, per the directive's preference.

### Task 3: Pin the inventory with a test
- [ ] Add `tests/test_wmbs_module_inventory.py` that parses the inventory table and asserts each claimed fixture path, scorer symbol/profile, test file, and registry key actually exists (and each "no" cell actually does not), so the inventory cannot silently drift from the tree.
- [ ] Assert the table covers exactly M01–M20 with no duplicates or gaps.
- [ ] Run the test; make it fail first against a deliberately wrong cell to prove it has teeth, then correct the cell.

### Task 4: Deliver the admitted T7 disclosure
- [ ] Add a gap-disclosure section to `eval/public/README.md` for the PR #96 M02/M04/M05 development oracles, following the wording and structure of the existing M12/M13 gap disclosures in that file.
- [ ] State plainly: development-only; no `registry.json` entry, adapter, runner routing, or scoring-profile registration; `publishable:false`; `pbpp_headline_eligible:false`; Stage B blocked on the public-harness integration owner's lease; they authorize no module-implementation, protocol, or publication claim.
- [ ] Add pinning tests (mirroring the existing M12/M13 pinning-test pattern under `tests/`) that fail if the disclosure text or those honest labels are removed or if a `wmbs-m02/m04/m05` registry entry appears without the disclosure being updated.

### Task 5: Record, land, and end clean
- [ ] Amend `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md` to mark `T7` delivered and to admit one new bounded documentation-and-tests node `T8` whose exact lease is the inventory document, `tests/test_wmbs_module_inventory.py`, and the lifecycle files; state that `T8` admits no source node, no Stage-B integration, and no successor node.
- [ ] Update `.planning/STATE.md` and the `GOAL.md` Current Phase paragraph to reflect the delivered inventory and disclosure. Move no progress counter.
- [ ] Write the round record `docs/plans/goalex-r45-<slug>.md` containing the three review-finding adjudications with their evidence.
- [ ] Push the branch, open a PR, get exact-head CI green, merge normally (no force-push, no direct write to `main`), then fast-forward local `main`, prove it equals clean `origin/main`, and append the merge SHA, exact head, exact-head CI run id, and post-merge CI run id to the lease-map `T7`/`T8` rows, `GOAL.md`, and `.planning/STATE.md` as the round's final commit.
- [ ] Confirm `git status --porcelain --untracked-files=all --ignored` shows nothing beyond the permitted ignored baseline before yielding.
