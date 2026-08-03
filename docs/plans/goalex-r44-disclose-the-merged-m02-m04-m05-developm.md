# Plan: Disclose the merged M02/M04/M05 development oracles in the public README and recompute the canonical baseline to `main@b8673031`

## Overview

You are the executor for one bounded GoalEx round in the controller worktree
`/Users/admin/.codex/worktrees/9697/Mnemosyne` on branch
`codex/goalex-whole-memory-pilot`. You have no memory of prior rounds; this
plan is self-contained. Never write directly to `main`, never force-push, never
bypass hooks.

**Context.** `GOAL.md`'s operator directive (2026-08-03) orders round selection:
(1) approved-plan implementable work, (2) **documentation an already-merged plan
requires but never received**, (3) bookkeeping. This round is category 2 plus the
round's own mandatory bookkeeping.

PR #96 (`main@088e2f31`) merged three development-only evaluation oracles —
`eval/public/wmbs_m02.py`, `wmbs_m04.py`, `wmbs_m05.py`, their three fixtures
under `eval/public/fixtures/`, and `tests/test_public_wmbs_m0{2,4,5}.py` — plus
four plans under `docs/plans/wmb-m0*-*.md`. It shipped **no** `eval/public/README.md`
disclosure. That README currently documents M12, M13, M01, M10, and M15 only, so
canonical `main` carries three undisclosed development modules.

The precedent to copy exactly is PR #90's M12/M13 gap disclosure: prose in
`eval/public/README.md` plus a pinning test that asserts the README's claims
against the *committed fixture and module facts* (see
`tests/test_public_working_memory_action_probe.py::test_public_readme_records_development_evidence_gaps`
and `tests/test_public_pm_bench_triggerbench.py::test_public_readme_m12_gap_disclosure_matches_committed_fixtures`).

**Hard scope limit.** This is documentation and tests only. It is **not** Stage B.
Do **not** add a `eval/public/registry.json` entry, an adapter, runner routing, a
`_PROFILE_CONTRACTS` row, or a scoring-profile registration for M02/M04/M05.
Do not change any module's behavior, any fixture byte, any admission state
(`PROPOSED` stays `PROPOSED`), `publishable`, or `pbpp_headline_eligible`.
Do not move `.planning/STATE.md` `progress.completed_plans`,
`completed_phases`, or `percent` — Stage B for these modules stays blocked, so
no plan completes here.

**Why the baseline work is also in scope.** `git rev-parse main` is now
`b8673031` (PRs #97 and #98 merged), while `GOAL.md`, `.planning/STATE.md`, and
`docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md` all still
record `Baseline: main@088e2f31`. GOAL.md's Verification block asserts equality
with `088e2f31…` and therefore fails; its own comment defines that failure as a
lapse requiring recomputation from the new `main` before further admission.

**Detector note (important).** `tests/test_planning_traceability.py` fails if any
PR merged into `main` after the recorded baseline is absent from the lease map,
and it requires a *structured* entry of the form `- PR #N:` — bare prose
mentioning `PR #N` does not satisfy it. Because no commit can carry its own merge
receipt, you must record **this round's own PR number** in the lease map *before*
merging it, exactly as the existing `- PR #97:` and `- PR #98:` entries were.

**Round-43 findings — already adjudicated, do not redo.** Finding 1 (unauthorized
`U-MODULES` writers) is closed by the narrowed `U-MODULES` row at lease-map line
~193, which excludes PR #96's development-only oracles and states they authorize
no module implementation, protocol, scorer admission, or publication claim.
Finding 3 (M05/M04 `portable_event` ABI) is closed by commits `a3d726f0` and
`13c05d65` plus `tests/test_public_wmbs_portable_event_abi.py`, which validates
M01/M05 against the committed schema and pins M04's documented weaker
vocabulary contract (its load-bearing `source_id`). Finding 2 is the baseline
lapse this plan's Task 1 discharges.

## Validation Commands

- `uv run --locked python -m pytest tests/test_public_wmbs_m02.py tests/test_public_wmbs_m04.py tests/test_public_wmbs_m05.py tests/test_public_wmbs_portable_event_abi.py -q`
- `uv run --locked python -m pytest tests/test_planning_traceability.py -q`
- `uv run --locked python -m pytest tests/test_public_pm_bench_triggerbench.py tests/test_public_working_memory_action_probe.py -q`
- `uv run --locked ruff check .` and `uv run --locked ruff format --check .`
- One authoritative full `uv run --locked python -m pytest -q` on the stable exact PR head
- `git status --porcelain --untracked-files=all --ignored` must show no round-owned residue at the end of the round
- The `GOAL.md` Verification block, re-run verbatim after Task 1's edit, must exit 0 once `main` equals the recorded baseline

### Task 1: Recompute the canonical baseline to `main@b8673031` and admit one bounded documentation node

- [ ] Confirm the starting state: `pwd -P` is the controller worktree, branch is `codex/goalex-whole-memory-pilot`, `git status --porcelain` is empty, `git fetch --prune origin` succeeds, and `git rev-parse main` equals `git rev-parse origin/main` equals `b8673031a80158c49d552a4b3647829d213243bd`. If `main` has advanced further, use that SHA everywhere below instead and record every intervening PR.
- [ ] In `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`: update the `Baseline:` header to the full 40-hex `main` SHA, update `Updated:`, and confirm the merged-baseline list already carries structured `- PR #97:` and `- PR #98:` entries (it does). Add each entry's post-merge receipt SHA/CI run only where you can verify it with `gh run list`/`gh pr view`; never invent a run ID.
- [ ] In the same map, admit exactly one bounded node for this round — name it `T7` — in the "Current delivery wave", stating: documentation and tests only; its exact lease is `eval/public/README.md`, the new/edited pinning test file(s), `GOAL.md`, `.planning/STATE.md`, this map, and `docs/plans/`; it admits **no** source node, no Stage-B integration, and no successor node. Leave the `U-MODULES` row's substance unchanged, and keep "zero new implementation writers" accurate by scoping it explicitly to implementation writers.
- [ ] In `GOAL.md`: update the Authority/Current Phase narrative to record PRs #96, #97, and #98 with their merge SHAs and the receipts you can verify, then update the Verification block — set the exact-baseline equality `test "$(git rev-parse main)" = "b8673031a80158c49d552a4b3647829d213243bd"` and add `git merge-base --is-ancestor b8673031… main`. Do not remove existing ancestry assertions.
- [ ] In `.planning/STATE.md`: update `stopped_at`, `last_updated`, `last_activity`, and the narrative to the new baseline and to PRs #96–#98. **Leave `progress.completed_plans`, `completed_phases`, and `percent` exactly as they are.**
- [ ] Run the `GOAL.md` Verification block verbatim and confirm it exits 0.

### Task 2: Write the M02/M04/M05 development gap disclosures in `eval/public/README.md`

- [ ] Read the existing M12/M13 disclosure paragraphs in `eval/public/README.md` (the "The M12 fixtures are deliberately small…" and "The M13 working-memory fixture…" paragraphs) and match their voice, honesty level, and structure.
- [ ] Derive every number and claim you write **from the committed source**, not from this plan: read `eval/public/wmbs_m02.py`, `wmbs_m04.py`, `wmbs_m05.py` and their fixtures in `eval/public/fixtures/`. Relevant module-level facts include `MODULE_ID`, `ADMISSION_STATE`, `FIXTURE_ID`, `DEFAULT_SEED`/`SEEDS`, `LICENSE`, M02's `CORPUS_SIZE`/`QUESTIONS_PER_FAMILY`/`QUERY_FAMILIES`, M04's `SEEDS`/`PERMUTATIONS`/`SOURCE_CLASSES`, and M05's `SEEDS`/`SLICE_IDS`/`RETRIEVAL_STAGE_IDS`/`FINITE_CORPUS_DISCLOSURE`/`INTEGRATION_DEPENDENCIES`.
- [ ] Add a new subsection under the whole-memory ABI section disclosing, per module: that each is a **Stage-A development oracle that runs no system and observes no SUT**, so a green run evidences generator/scorer determinism and nothing about any SUT; that each is **unregistered** — no registry entry, adapter, runner routing, or scoring profile — so it produces no bundle and no benchmark result; that `ADMISSION_STATE` is `PROPOSED` with `publishable:false` and `pbpp_headline_eligible:false`; and that latency, tokens, calls, and storage are `unsupported`.
- [ ] Add the module-specific gaps honestly: M02's deferred corpus scale versus the spec's 2,000-event corpus and its finite fixture size; M04's `unsupported` numeric calibration and its documented departure from the closed `portable_event` ABI (the load-bearing `source_id` keying `gold.ablation_objects`, which is a shape-vocabulary reuse and never a conformance claim); M05's **one-hop** claim→source grounding only, its unsigned content-addressed source manifest, and its unresolved integration dependencies as listed in `INTEGRATION_DEPENDENCIES`.
- [ ] State plainly that Stage B — harness integration for all three — is **not delivered** and remains gated on the public-harness integration owner's lease and the quarantines named in the plans under `docs/plans/wmb-m0*-implementation-plan.md`.
- [ ] Make no publication, comparability, ranking, superiority, or upstream-equivalence claim anywhere in the new text.

### Task 3: Pin the disclosures with tests that fail if the README and the committed facts diverge

- [ ] Add a test module (e.g. `tests/test_public_wmbs_stage_a_disclosure.py`) — or extend `tests/test_public_wmbs_m0{2,4,5}.py` if that reads more naturally alongside their existing style — that reads `eval/public/README.md` and asserts the disclosure against **computed** values imported from the modules and loaded from the committed fixtures, not against transcribed literals. A test that only greps for a hardcoded sentence is insufficient; the point is that changing a fixture or module constant must turn the test red.
- [ ] Cover at minimum, per module: the disclosed seed(s)/case counts/corpus size actually match the committed fixture; the README names the module's `ADMISSION_STATE`; the README states the module is unregistered and assert that truth independently by checking each `FIXTURE_ID`/profile is absent from `eval/public/registry.json`; and the README records the `unsupported` metric classes.
- [ ] Add a guard asserting the three modules are absent from `eval/public/registry.json`, so a future Stage-B registration cannot land while the README still calls them unregistered.
- [ ] Run the focused validation commands until green, then `ruff check`/`ruff format --check`.

### Task 4: Land the round through a normal PR and reconcile canonical truth

- [ ] Commit on `codex/goalex-whole-memory-pilot` in logical commits, push normally (never force), and open a PR against `main` describing it as documentation-and-tests only: it admits no source node, delivers no Stage B, and moves no benchmark, measurement, admission state, publication claim, or progress counter.
- [ ] **Before merging**, add the structured `- PR #<this PR>:` entry to the lease map's merged-baseline list (mirroring the `- PR #97:`/`- PR #98:` entries, including the note that no exact head or receipt is claimed because no commit can carry its own merge), commit, and push — otherwise `tests/test_planning_traceability.py` fails the detector.
- [ ] Run one authoritative full `uv run --locked python -m pytest -q` on the stable exact PR head; record the exact-head CI run ID. Resolve every review thread and CI failure by fixing the root cause — never by weakening a validator or dismissing a finding.
- [ ] After merge: fast-forward local `main`, prove it equals clean `origin/main`, capture the merge SHA and post-merge `main` CI run ID, and record those receipts in `GOAL.md`, `.planning/STATE.md`, and the lease map on the controller branch.
- [ ] Write the round record `docs/plans/goalex-r44-<slug>.md` capturing the selection rationale (category 2 under the operator directive), the round-43 findings adjudication summarized in the Overview above, what was delivered, and what remains gated. Move any now-completed round record into `docs/plans/completed/` per existing convention.
- [ ] Finish with rule 11: commit every round-owned change on the controller branch and confirm `git status --porcelain --untracked-files=all --ignored` shows no round-owned residue beyond the pre-existing ignored baseline. Do not modify or remove any ignored path.
