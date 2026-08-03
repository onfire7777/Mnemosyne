# Whole-Memory Benchmark Standard — M01–M20 completeness inventory

**Baseline:** recomputed from the tree at `main@b8673031` plus the
`codex/goalex-whole-memory-pilot` controller branch, on 2026-08-03, as Round 0
of the operator's benchmark directive in `GOAL.md`.

**This document is documentation only.** It authorizes **no artifact**: no
module implementation, no fixture, no scorer, no `eval/public/registry.json`
entry, no adapter, no runner routing, no scoring-profile registration, no
protocol change, and no publication or claim upgrade. It records what is
already in the tree and what the cheapest honest next step for each module
would be. Every module in this table remains `PROPOSED` per the standard
(`docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md:609`),
and every registry suite in the tree is `publishable:false` and
`pbpp_headline_eligible:false`. Nothing here moves a progress counter.

Module short names are the standard's own section headers
(`…-whole-memory-benchmark-standard-design.md:615`–`1103`); the capability
mapping is its C01–C24 table (same file, lines 502–525).

## What counts as each column

- **Approved exact plan** — either a per-module plan under `docs/plans/wmb-mNN-…`
  or coverage by the owner-landed pilot plan
  `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`,
  whose scope line 9 names M01, M03, M10, M12, M13, M15, and M20 and whose
  per-module disposition table is at lines 67–73.
- **Fixture** — a committed file under `eval/public/fixtures/`.
- **Scorer** — *any* of: a dedicated `eval/public/wmbs_mNN.py`, an inline
  `_score_wmbs_*` / profile branch in `eval/public/scoring.py`, or module logic
  in `eval/public/adapters/whole_memory_reference.py` / `eval/public/bundle.py`.
  A missing `wmbs_mNN.py` does **not** mean the module has no scorer.
- **Test suite** — a committed file under `tests/` exercising the module.
- **Registry entry** — a key in `eval/public/registry.json`. Registry keys are
  suite names, not module IDs; three admitted suites (`pm-bench-development`,
  `triggerbench-development`, `working-memory-action-development`) carry no
  `wmbs-` prefix but are M12/M13 suites, as `eval/public/README.md:48` and
  `eval/public/README.md:57` state in their own words.

## M01–M20

| Module | Capability / short name | Approved exact plan | Fixture | Scorer | Test suite | Registry entry | Admission state | Cheapest next step (GOAL.md ladder) |
|---|---|---|---|---|---|---|---|---|
| M01 | C01/C02 — Capture and durability | yes — pilot plan `…harness-pilots.md:67` | yes — `eval/public/fixtures/wmbs-m01-development.json` | yes — `eval/public/wmbs_m01.py`; profile `wmbs-m01-v1` at `eval/public/scoring.py:35`, `_score_wmbs_m01` at `scoring.py:94`; adapter at `adapters/whole_memory_reference.py:95` | yes — `tests/test_public_wmbs_m01.py` | yes — `wmbs-m01-development` at `eval/public/registry.json:215` | `PROPOSED`; `PILOT-READY-DEV` for Local only; `publishable:false`, `pbpp_headline_eligible:false` | Landed end to end. Step 4 residue only: widen beyond Local/SQLite when an approved plan admits it |
| M02 | C01/C03/C07 — Retrieval and organization | yes — `docs/plans/wmb-m02-retrieval-organization-implementation-plan.md` | yes — `eval/public/fixtures/wmbs-m02-retrieval-development.json` | yes (Stage A only) — `eval/public/wmbs_m02.py`; **no** profile branch in `scoring.py` | yes — `tests/test_public_wmbs_m02.py` | **no** | `PROPOSED`; development-only PR #96 oracle; `publishable:false`, `pbpp_headline_eligible:false` | Step 4 (Stage B): scoring-profile + registry + adapter registration. Blocked on the public-harness integration owner's lease; disclosed as a gap in `eval/public/README.md` under lease-map node `T7` |
| M03 | C04 — Temporal evolution | yes — pilot plan `…harness-pilots.md:68` | yes — `eval/public/fixtures/wmbs-m03-valid-time-development.json` | yes, **inline, with no `wmbs_m03.py` file** — profile `wmbs-m03-valid-time-v1` at `eval/public/scoring.py:37`, `_score_wmbs_m03_valid_time` at `scoring.py:156`; adapter `run_m03_valid_time_development` at `adapters/whole_memory_reference.py:138`; seeds at `eval/public/bundle.py:44` | yes — `tests/test_public_whole_memory_reference.py:3119`, `:3176`, `:3213`, `:3232` | **no** | `PROPOSED` for full M03; valid-time slice `INTERNALLY_MEASURED` | Step 4 (Stage B): the single missing artifact is a `registry.json` suite entry. Cheapest remaining gap in the whole table. Blocked on the public-harness integration owner's lease |
| M04 | C05 — Conflict and correction | yes — `docs/plans/wmb-m04-conflict-correction-implementation-plan.md` | yes — `eval/public/fixtures/wmbs-m04-development.json` | yes (Stage A only) — `eval/public/wmbs_m04.py`; **no** profile branch in `scoring.py`; no adapter | yes — `tests/test_public_wmbs_m04.py`; ABI conformance in `tests/test_public_wmbs_portable_event_abi.py` | **no** | `PROPOSED`; development-only PR #96 oracle; `publishable:false`, `pbpp_headline_eligible:false` | Step 4 (Stage B): profile + registry + adapter. Blocked on the public-harness lease; disclosed under `T7` |
| M05 | C06 — Provenance and explanation | yes — `docs/plans/wmb-m05-provenance-explanation-implementation-plan.md` | yes — `eval/public/fixtures/wmbs-m05-provenance-development.json` | yes (Stage A only) — `eval/public/wmbs_m05.py`; **no** profile branch in `scoring.py`; no adapter | yes — `tests/test_public_wmbs_m05.py`; ABI conformance in `tests/test_public_wmbs_portable_event_abi.py` | **no** | `PROPOSED`; development-only PR #96 oracle; quarantines Q1–Q12 recorded in the module docstring; `publishable:false` | Step 4 (Stage B): profile + registry + adapter, and discharge of the Q1/Q3/Q4 ABI quarantines. Blocked on the public-harness lease; disclosed under `T7` |
| M06 | C08 — Consolidation and learning | **no** | **no** | **no** | **no** | **no** | `PROPOSED`; not in the first pilot (`…standard-design.md:771`) | Step 1: author the exact implementation plan. Always permitted |
| M07 | C09 — Retention, rehearsal, and decay | **no** | **no** | **no** | **no** | **no** | `PROPOSED`; not in the first pilot (`…standard-design.md:798`) | Step 1: author the exact implementation plan |
| M08 | C10 — Reversible forgetting | **no** | **no** | **no** | **no** | **no** | `PROPOSED` for adapters exposing the hook, else `UNSUPPORTED-BY-SYSTEM` (`…standard-design.md:818`) | Step 1: author the exact implementation plan |
| M09 | C11 — Declared-surface erasure conformance | **no** | **no** | **no** | **no** | **no** | `PROPOSED` for Local/SQLite declared surfaces (`…standard-design.md:846`) | Step 1: author the exact implementation plan |
| M10 | C12 — Calibration and abstention | yes — pilot plan `…harness-pilots.md:69` | yes — `eval/public/fixtures/wmbs-m10-development.json` | yes — `eval/public/wmbs_m10.py`; profile `wmbs-m10-v1` at `eval/public/scoring.py:39`, `_score_wmbs_m10` at `scoring.py:281`; adapter at `adapters/whole_memory_reference.py:119` | yes — `tests/test_public_wmbs_m10.py` | yes — `wmbs-m10-development` at `eval/public/registry.json:234` | `PROPOSED`; `PILOT-READY-DEV` for the deterministic reader; `publishable:false`, `pbpp_headline_eligible:false` | Landed end to end. Step 4 residue only: model-backed/judged QA and numeric confidence remain out of scope |
| M11 | C15/C16 — Security and isolation | **no** | **no** | **no** | **no** | **no** | `PROPOSED` for internal local-principal scope (`…standard-design.md:899`) | Step 1: author the exact implementation plan. Highest-leverage greenfield: CAP-004 and RAIL-001/004 depend on it |
| M12 | C13 — Prospective action | yes — pilot plan `…harness-pilots.md:70` | yes — `eval/public/fixtures/pm-bench-development.json` and `eval/public/fixtures/triggerbench-development.json` | yes, **inline** — profiles `pm-bench-action-v1` / `triggerbench-action-v1`, dispatch at `eval/public/scoring.py:344`; no `wmbs_m12.py` | yes — `tests/test_public_pm_bench_triggerbench.py` | yes — `pm-bench-development` at `eval/public/registry.json:134` and `triggerbench-development` at `:150` | `PROPOSED`; `INTERNALLY_MEASURED` development smoke; both suites `publishable:false`, `pbpp_headline_eligible:false` | Landed end to end at development scale. Step 1 for the disclosed gaps: recurrence plumbing, lateness magnitude, calibrated baseline (`eval/public/README.md:48`) |
| M13 | C14 — Working memory | yes — pilot plan `…harness-pilots.md:71` | yes — `eval/public/fixtures/working-memory-action-development.json` | yes, **inline** — profile `working-memory-action-v1` at `eval/public/scoring.py:43`; no `wmbs_m13.py` | yes — `tests/test_public_working_memory_action_probe.py` | yes — `working-memory-action-development` at `eval/public/registry.json:166` | `PROPOSED`; `INTERNALLY_MEASURED` development smoke; `publishable:false`, `pbpp_headline_eligible:false` | Landed end to end at development scale. Step 1 for the disclosed gaps: capacity parameter and promotion control (`eval/public/README.md:57`) |
| M14 | C07/C08/C23 — Procedural task utility | yes — `docs/plans/wmb-m14-procedural-task-utility-implementation-plan.md` | **no** | **no** | **no** | **no** | `PROPOSED`; deferred until the portable-event ABI plus one pilot exist (`…standard-design.md:449`) | Step 2/3: the plan exists, so freeze it and implement fixture + scorer test-first. Cheapest module with a plan but no artifact |
| M15 | C02/C17 — Determinism and replay | yes — pilot plan `…harness-pilots.md:72` | **no dedicated fixture — by design**: composes the M01/M03/M10 fixtures (`eval/public/bundle.py:43`–`45`) | yes, **inline** — `run_m15_composed_development` at `adapters/whole_memory_reference.py:254`; M15 projection and digest at `eval/public/bundle.py:94` and `:158`; no `wmbs_m15.py` | yes — `tests/test_public_whole_memory_reference.py:2208`, `:2228` | **no — by design**: M15 is a cross-run property, not a suite | `PROPOSED`; `PILOT-READY-DEV` for admitted pilot payloads | Landed as a run property. No registry step exists to take; step 4 residue is coverage of any future payload |
| M16 | C18/C20 — Backend and transport parity | **no** | **no** | **no** | **no** | **no** | `PROPOSED` for Local/SQLite/local MCP (`…standard-design.md:1026`) | Step 1: author the exact implementation plan. CAP-011 and RAIL-001 depend on it |
| M17 | C19 — Custody and recovery | **no** | **no** | **no** | **no** | **no** | `PROPOSED` for local fault injection (`…standard-design.md:1049`) | Step 1: author the exact implementation plan |
| M18 | C20 — Interoperability | **no** | **no** | **no** | **no** | **no** | `PROPOSED` for internal single-system scope (`…standard-design.md:1071`) | Step 1: author the exact implementation plan |
| M19 | C21 — Multimodal memory | **no** | **no** | **no** | **no** | **no** | `PROPOSED`; C21 is *currently deferred* (`…standard-design.md:523`) | None. Deferred by the standard; do not start until C21 is undeferred |
| M20 | C06/C17/C22 — Publication integrity | yes — pilot plan `…harness-pilots.md:73` | **no** | **no benchmark scorer**; substrate implementation exists under `leaderboard/`: `validate.py`, `ledger.py`, `render.py`, `publish.py`, `readiness.py` | yes, of the substrate — `tests/test_leaderboard_result_contract.py`, `_ledger.py`, `_render.py`, `_publish.py`, `_readiness.py`, `_governance_policy.py` | **no** | v2 `admission_state` is `PROPOSED`; the v1 substrate is `evidence_level=IMPLEMENTED` with **no implied v2 admission** (`…standard-design.md:1127`); pilot disposition `CONTRACT-READY` | Step 1 for the v2 delta only. The v1 substrate is landed and lease-blocked behind result-v2 node `N12`; do **not** treat M20 as greenfield |

## Corrections to the recorded counts

Each figure below is quoted from `GOAL.md`'s Current Priority section
("Measured at `main@b8673031`"). The operator's directive text is left intact;
these are the recomputation's corrections, as the directive itself instructs
("Do not trust the counts above; recompute them from the tree and correct
them").

1. **"implemented (`eval/public/wmbs_*.py`): M01, M02, M04, M05, M10 — 5 of
   20" undercounts by four.** The filename glob is not the implementation
   surface. M03's scorer is implemented inline in `eval/public/scoring.py:156`
   with no `wmbs_m03.py` file at all; M12's is dispatched inline at
   `scoring.py:344`; M13's at `scoring.py:43`; M15's lives in
   `adapters/whole_memory_reference.py:254` plus `bundle.py:94`/`:158`.
   **Scorer-bearing modules are M01, M02, M03, M04, M05, M10, M12, M13, M15 —
   9 of 20.**

2. **"registry-admitted: M01, M10 — 2 of 20" undercounts by two.** The count
   evidently grepped the `wmbs-` prefix. `eval/public/registry.json` also
   admits `pm-bench-development` (`:134`) and `triggerbench-development`
   (`:150`), which are M12 suites, and `working-memory-action-development`
   (`:166`), which is an M13 suite — `eval/public/README.md:48` and `:57` name
   them as M12 and M13 fixtures in the repository's own words.
   **Registry-admitted modules are M01, M10, M12, M13 — 4 of 20.** All five
   suites remain `publishable:false` and `pbpp_headline_eligible:false`.

3. **"per-module implementation plans: M02, M04, M05, M14 — 4 of 20" is
   correct only for `docs/plans/wmb-m*`.** The owner-landed pilot plan
   `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`
   is an approved exact plan and covers M01, M03, M10, M12, M13, M15, and M20
   (its line 9, with per-module dispositions at lines 67–73).
   **Modules with an approved exact plan of any kind are M01–M05, M10, M12,
   M13, M14, M15, M20 — 11 of 20.**

4. **"no plan and no module: M06, M07, M08, M09, M11, M16, M17, M18, M19,
   M20 — 10" wrongly includes M20.** M20 has an approved plan (pilot plan
   line 73, disposition `CONTRACT-READY`) and a landed v1 substrate under
   `leaderboard/` with six committed test files. Its open work is the
   result-v2 delta, which is lease-blocked behind node `N12`, not greenfield
   module authoring. **True no-plan-and-no-artifact modules are M06, M07, M08,
   M09, M11, M16, M17, M18, M19 — 9 of 20.**

5. **"M03, M12, M13, M15 are candidates [for fixture-without-scorer-or-plan]
   — verify in the inventory": verified false for all four.** M03, M12, and
   M13 each already have a scorer (inline) *and* an approved plan; M12 and M13
   are additionally registry-admitted. M15 has an adapter and a bundle
   projection and needs no fixture or registry entry by design. The one true
   fixture-and-scorer-without-registry module is **M03**, whose sole missing
   artifact is a `registry.json` entry.

6. **Consequent framing correction.** "only five are implemented" understates
   the built surface. Counting a module as *end-to-end landed* when it has a
   plan, a fixture (or a by-design exemption), a scorer, tests, and a registry
   entry (or a by-design exemption), the landed set is **M01, M10, M12, M13,
   M15 — 5 of 20** — the same headline number, but a different membership:
   M02, M04, and M05 are *not* landed (Stage A only, no registration), while
   M12, M13, and M15 are.

## Highest-value next gaps

Ranked per the directive's stated preference — modules that already have a
fixture or a partial scorer rank above greenfield ones, and completing one
module end to end ranks above starting several.

1. **M03 — one artifact from complete.** Fixture, inline scorer, scoring
   profile, adapter, and four test functions all exist; only the
   `registry.json` suite entry is missing. This is the smallest honest
   increment in the table. It is a Stage-B registration and therefore sits on
   the public-harness integration owner's exclusive lease
   (`docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`,
   Shared-file owners table); it needs that lease, not a new plan.
2. **M02, M04, M05 — Stage A complete, Stage B unregistered.** Each has an
   approved per-module plan, a fixture, a pure scorer, and a test suite. Each
   needs a scoring-profile branch, an adapter, and a registry entry, all on the
   public-harness lease. M05 additionally carries the Q1/Q3/Q4 ABI quarantines
   named in its module docstring, so it is the most expensive of the three.
   Until Stage B lands, all three remain development-only oracles that
   authorize no module-implementation, protocol, or publication claim — the
   `U-MODULES` row and the `T7` disclosure both say so.
3. **M14 — plan exists, no artifact.** The only module with an approved
   per-module plan and nothing built. Steps 2–3 of the ladder (freeze, then
   implement fixture and scorer test-first against the frozen closed ABI) are
   ordinary ungated source work needing no operator authorization. This is the
   highest-value item that is *not* lease-blocked.
4. **M12 and M13 — landed, with disclosed development gaps.** Not new-module
   work: their remaining items are recurrence plumbing, lateness magnitude, a
   calibrated baseline (M12), and a capacity parameter plus promotion control
   (M13), each already disclosed in `eval/public/README.md`. Each needs step 1
   for its specific gap, not a whole module plan.
5. **M11, then M16 — highest-leverage greenfield.** Both are pure step 1
   (author the exact plan), always permitted. M11 carries CAP-004 and
   RAIL-001/004; M16 carries CAP-011, RAIL-001, and C18/C20 parity, on which
   several later phases depend.
6. **M06, M07, M08, M09, M17, M18 — remaining greenfield.** Step 1 each; no
   ordering advantage among them from the tree.
7. **M20 — lease-blocked, not greenfield.** The v2 delta waits on node `N12`
   and the protected signed-publication paths; do not open it as module work.
8. **M19 — do not start.** C21 is deferred by the standard
   (`…standard-design.md:523`).
