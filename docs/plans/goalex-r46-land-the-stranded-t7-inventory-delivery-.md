# Plan: Land the stranded T7/inventory delivery, then close M03's single missing artifact by admitting its registry suite

## Overview

You are the executor for GoalEx round 46 in the controller worktree
`/Users/admin/.codex/worktrees/9697/Mnemosyne` on branch
`codex/goalex-whole-memory-pilot`. Read `GOAL.md` first — it is authority. You
have no memory of previous rounds; everything you need is below.

**State right now (verified this round).** Canonical `main` = `origin/main` =
`b8673031a80158c49d552a4b3647829d213243bd`, which equals the baseline recorded
in `GOAL.md`, `.planning/STATE.md`, and the lease map — the lapse detector is
green. The controller worktree is clean. The controller branch is **5 commits
ahead of `main` and has never been pushed** (`git ls-remote origin
codex/goalex-whole-memory-pilot` is empty). `gh pr list --state open` is empty:
there are no open PRs and no competing writer on any lease.

**What is already built on the branch and must now be landed.**
- `docs/coordination/2026-08-03-wmbs-module-completeness-inventory.md` (164
  lines) — the Round-0 M01–M20 completeness inventory required by `GOAL.md`.
- `docs/coordination/2026-08-03-wmbs-module-completeness-derivation.md` (345
  lines) — its line-level derivations.
- `tests/test_wmbs_module_inventory.py` (267 lines) — pins the inventory to the
  tree; proven to have teeth by six reverted mutations.
- `eval/public/README.md` (+76 lines) — the `T7`-admitted M02/M04/M05 Stage-A
  development-oracle gap disclosure.
- `tests/test_public_wmbs_stage_a_disclosure.py` (327 lines) — pins it.
- The three lifecycle files recomputed to `Baseline: main@b8673031` with node
  `T7` admitted at the lease map's package DAG table.
- `docs/plans/goalex-r44-*.md` and `docs/plans/goalex-r45-*.md` round records.

`uv run --locked python -m pytest tests/test_wmbs_module_inventory.py
tests/test_public_wmbs_stage_a_disclosure.py tests/test_planning_traceability.py -q`
passes (36 tests) at branch HEAD. Note: bare `python` is not on PATH in this
environment — always use `uv run --locked python …`.

**The substantive increment this round: M03 registry admission.** The
inventory ranks M03 the single cheapest genuine gap in the whole table, and the
tree agrees. Everything M03 needs already exists:
- fixture `eval/public/fixtures/wmbs-m03-valid-time-development.json` (labels
  `module_id: M03`, `admission_state: PROPOSED`, `publishable: false`,
  `headline_eligible: false`, `upstream_comparable: false`, 5 timelines, seeds
  `[11, 23, 37, 53, 71]`);
- scorer inline at `eval/public/scoring.py:156` (`_score_wmbs_m03_valid_time`),
  dispatched for profile `wmbs-m03-valid-time-v1` at `eval/public/scoring.py:37`;
- adapter `run_m03_valid_time_development` at
  `eval/public/adapters/whole_memory_reference.py:138`;
- bundle seeds already declared at `eval/public/bundle.py:44` under the exact
  suite name `wmbs-m03-valid-time-development`;
- tests at `tests/test_public_whole_memory_reference.py:3119`, `:3176`, `:3213`,
  `:3232`.

The only missing artifacts are the `eval/public/registry.json` suite entry and
its two runner keys. This is exactly the defect quarantine **Q2** of
`docs/plans/wmb-m14-procedural-task-utility-implementation-plan.md` records:
the cell is "scorer-backed and unit-tested, and nevertheless unreachable from
`run_public_suite`: no registry entry, no `_ADAPTERS` key, no
`_PROFILE_CONTRACTS` key."

M03 is authorized. It is **not** in the lease map's `U-MODULES` SPEC-UNSTABLE
row (that row covers M02, M04–M09, M11, M14, M16–M19). The owner-landed pilot
plan `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`
names M03 in its scope (line 9) and its target-evidence table (line 68) sets
M03 at `PROPOSED` for full M03 with `INTERNALLY_MEASURED` for the valid-time
slice and full bitemporal transaction-time retained as a hard deferral. This
registration delivers that slice; it advances no admission state and no
progress counter.

**Governance requirement — do not repeat PR #96's defect.** `eval/public/*` is
the Public-harness integration owner's exclusive lease ("One writer; serialize
any package touching one of these paths"). PR #96 merged three modules onto
that lease while the map admitted no writer, which the independent review
flagged as a high finding. So the lease-map node authorizing the M03 work must
**merge before** the M03 code, and the M03 code must go in its own
lease-disjoint branch — never mixed into the controller branch's lifecycle
lease. Serialization is satisfiable: there are no open PRs and no other active
writer.

**Adjudication of the three outstanding independent-review findings.** Record
these in the round record with the evidence given; all three are closed by work
already in the tree, so do not reopen or expand them.
1. *[high] `U-MODULES` row vs. the merged M02/M04/M05 modules.* Closed. The row
   at `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md:198`
   now explicitly **excludes** PR #96's development-only oracles and states they
   "authorize no module implementation, protocol, scorer admission, or
   publication claim." The branch's `eval/public/README.md` disclosure makes the
   same statement in the public harness doc under node `T7`. Do **not** revert
   PR #96.
2. *[high] canonical-baseline lapse detector red.* Closed. `git rev-parse main`
   is `b8673031` and all three lifecycle files read `Baseline: main@b8673031`,
   so `GOAL.md`'s equality gate passes. Re-verify it, then record as closed. The
   always-on suite keeps the ancestry + lease-map-coverage form by design —
   `GOAL.md` explains why the equality cannot live in CI.
3. *[medium] M04/M05 fixture events violate `$defs.portable_event`.* Closed on
   `main` by `a3d726f0` plus `tests/test_public_wmbs_portable_event_abi.py`.
   **Verify by running that test file**, and confirm the branch's README
   disclosure documents M04's deliberate load-bearing `source_id` as a departure
   from the ABI rather than a conformance claim. If a residual violation
   survives, report it in the round record — do not expand this round into a
   module fix.

**Hard rules.** Never force-push, never write directly to `main`, never bypass
hooks, never dismiss a review finding without evidence. Do not change any
fixture byte, scorer logic, adapter logic, or schema. Do not move
`progress.percent`, `progress.completed_plans`, or `progress.completed_phases`.
M02/M04/M05 stay `PROPOSED` / `publishable:false` /
`pbpp_headline_eligible:false` and stay unregistered. M03 stays `PROPOSED`; its
registration is a reachability fix, not an evidence or publication upgrade.
`GOAL.md` rule 11: the controller worktree must be clean when you yield —
commit the round's receipts and round record on the controller branch as the
final step, and remove any extra worktree you created.

## Validation Commands

- `test "$(git rev-parse main)" = "$(git rev-parse origin/main)"`
- `uv run --locked python -m pytest tests/test_wmbs_module_inventory.py tests/test_public_wmbs_stage_a_disclosure.py tests/test_planning_traceability.py tests/test_public_wmbs_portable_event_abi.py -q`
- `uv run --locked python -m pytest tests/test_public_eval.py tests/test_public_whole_memory_reference.py -q`
- `uv run --locked python -m pytest -q`
- `uv run --locked ruff check .` and `uv run --locked ruff format --check .`
- `uv run --locked python -c "from eval.public.runner import load_registry; r=load_registry(); print(sorted(k for k in r))"`
- `git status --porcelain --untracked-files=all` (must be empty in the controller worktree at round end)

### Task 1: Complete and land the stranded lifecycle delivery as PR-1

- [ ] In `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`, keep node `T7` and add its delivery statement: the `eval/public/README.md` disclosure and `tests/test_public_wmbs_stage_a_disclosure.py` are delivered by this PR.
- [ ] Add node `T8` to the same package DAG table: a bounded GoalEx lifecycle documentation-and-tests node whose exact lease is `docs/coordination/2026-08-03-wmbs-module-completeness-inventory.md`, `docs/coordination/2026-08-03-wmbs-module-completeness-derivation.md`, `tests/test_wmbs_module_inventory.py`, and the three lifecycle files. State that it admits no source node and no publication claim.
- [ ] Add node `T9` to the same table, `ADMITTED`, as the **public-harness Stage-B M03 registry-admission node**: consumes verified canonical `main` at the PR-1 merge commit; produces the `wmbs-m03-valid-time-development` registry entry, its `_ADAPTERS` and `_PROFILE_CONTRACTS` keys, its README documentation, and its tests; exact lease `eval/public/registry.json`, `eval/public/runner.py`, `eval/public/README.md`, and the new/edited test files under `tests/`; owner: Public-harness integration owner, serialized as sole writer (no open PR, no competing lane). State explicitly that it authorizes **M03 only**, admits no other module, changes no fixture byte, no scorer logic, no schema, and no admission state — M03 stays `PROPOSED` with full bitemporal transaction-time retained as a hard deferral per pilot-plan line 68 — and that it admits no successor node.
- [ ] Update the "Current delivery wave" and concurrency-ceiling paragraphs so they name `T7`, `T8`, and `T9` truthfully instead of asserting zero admitted writers, and update the "Independent external gates (do not block T0-T7)" line accordingly.
- [ ] Update `.planning/STATE.md` and the `GOAL.md` Current Phase paragraph to record the delivered inventory, the delivered `T7` disclosure, and the admission of `T8` and `T9`. Move no progress counter.
- [ ] Tick the now-satisfied checkboxes in `docs/plans/goalex-r45-round-0-of-the-benchmark-directive-publi.md` Task 4 (the README disclosure and its pinning tests exist).
- [ ] Push the controller branch, open PR-1, wait for exact-head CI green, merge normally, then fast-forward local `main` and prove `git rev-parse main` equals `git rev-parse origin/main`.

### Task 2: Cut the M03 lane from the new canonical main

- [ ] After PR-1 merges, refresh `origin`, confirm `main` equals clean `origin/main`, and confirm `gh pr list --state open` shows nothing touching `eval/public/`.
- [ ] Create an isolated lane: `git worktree add /Users/admin/.codex/worktrees/9697/Mnemosyne-m03 -b codex/wmb-m03-registry-admission main`. Do all M03 work there; touch nothing in the controller worktree until Task 5.
- [ ] Confirm in that lane that node `T9` is present and `ADMITTED` in the lease map on `main`, and that `eval/public/bundle.py:44` already declares the seeds `(11, 23, 37, 53, 71)` for suite name `wmbs-m03-valid-time-development`.

### Task 3: Register the M03 valid-time suite, test-first

- [ ] Write the failing tests first, in the file that matches existing precedent (extend `tests/test_public_whole_memory_reference.py` and/or add a focused new test module): assert `load_registry()` returns a `wmbs-m03-valid-time-development` entry; assert its `dataset_sha256` equals the digest recomputed from the committed fixture using the same canonicalization the runner applies to fixture-based suites; assert `runner._ADAPTERS` resolves its adapter key to `whole_memory_reference.run_m03_valid_time_development`; assert `runner._PROFILE_CONTRACTS` carries its scoring profile bound to the same `(family, interval_method)` pair the entry declares; assert the honest labels (`admission_state: PROPOSED`, `publishable: false`, `pbpp_headline_eligible: false`, `headline_eligible: false`, `upstream_comparable: false`, `independent_external_reproduction: false`, `split_role: development`). Run them and confirm they fail for the right reason.
- [ ] Add the `wmbs-m03-valid-time-development` entry to `eval/public/registry.json`, deriving the exact required key set from the validators in `eval/public/runner.py` (`load_registry` and the `_validate_*` helpers) and from the `wmbs-m01-development` / `pm-bench-development` precedent. Use `adapter: "wmbs-m03-valid-time-reference"`, `scoring_profile: "wmbs-m03-valid-time-v1"`, `family: "whole-memory-development"`, `interval_method: "descriptive"`, `fixture: "fixtures/wmbs-m03-valid-time-development.json"`. Do **not** set `system_seam` — this cell runs through the public CLI subprocess seam, unlike M01/M10's `harness-owned-reference-core`. Compute `dataset_sha256` rather than guessing it, and set `revision` to the 40-hex commit that last modified the fixture (`git log -1 --format=%H -- eval/public/fixtures/wmbs-m03-valid-time-development.json`).
- [ ] Add `"wmbs-m03-valid-time-reference": whole_memory_reference.run_m03_valid_time_development` to `_ADAPTERS` and `"wmbs-m03-valid-time-v1": ("whole-memory-development", "descriptive")` to `_PROFILE_CONTRACTS` in `eval/public/runner.py`, matching the surrounding style.
- [ ] Document the suite in `eval/public/README.md` next to the existing M01/M10 invocations, with its honest labels and the retained deferral: full bitemporal transaction-time query semantics stay deferred, the fixture itself declares `transaction_time.supported: false`, and the cell is development-only and not publishable or comparable.
- [ ] Run the new tests plus `tests/test_public_eval.py`, `tests/test_public_whole_memory_reference.py`, then the full suite and Ruff. Fix only what this change breaks.

### Task 4: Land the M03 registration as PR-2

- [ ] Commit in the lane with a message naming node `T9` as the authorizing lease. Push the lane branch and open PR-2 describing exactly what it registers, what it does not claim, and that M03's admission state is unchanged.
- [ ] Clear review threads, get exact-head CI green, merge normally, then fast-forward local `main` and prove it equals clean `origin/main`.
- [ ] If any genuine blocker prevents the registration from landing — a validator that rejects the entry, a digest that cannot be reconciled without editing fixture bytes, or a CI failure rooted outside this change — stop, revert the lane cleanly, and record the exact blocker and its evidence in the round record. Do not edit fixtures, scorers, or the schema to force it through, and do not substitute a different module.

### Task 5: Record receipts and end the controller worktree clean

- [ ] Remove the M03 worktree (`git worktree remove /Users/admin/.codex/worktrees/9697/Mnemosyne-m03`) and confirm `git worktree list` shows only the expected entries.
- [ ] On the controller branch, write the round record `docs/plans/goalex-r46-<slug>.md` containing: the three review-finding adjudications with their evidence; the PR-1 and PR-2 receipts (merge SHA, exact head, exact-head CI run id, post-merge CI run id for each); and a short note that the M14 plan's own verdict is **NOT CODE-READY** with irreducible blockers B1–B4, which contradicts the inventory's ranking of M14 as the cheapest plan-having module — surfaced, not edited, per `GOAL.md`.
- [ ] Update the lease map, `.planning/STATE.md`, and `GOAL.md` with both PRs' receipts and mark `T7`, `T8`, and `T9` `MERGED`, recomputing the baseline to the new canonical `main`. Move no progress counter.
- [ ] Commit all of the above on the controller branch as the round's final step and confirm `git status --porcelain --untracked-files=all --ignored` shows nothing beyond the permitted ignored baseline before yielding.
