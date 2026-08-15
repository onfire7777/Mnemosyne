# WMB M07 — Retention, Rehearsal, and Decay Implementation Contract

Status: `PROPOSED` / **PLANNING ARTIFACT ONLY — NOT CODE-READY.**
This file authorizes no source, fixture, registry, scorer, measurement,
admission-state, publication change, or GitHub PR.

Author lane: M07 retention-rehearsal-decay planning lane.
Verified base: `origin/main@61f55b94a6f878973437d075adfcecf2cb684ae6`.
Written: 2026-08-15.

## 0. What this document is, and what it is not

This is the exact implementation contract `U-MODULES` requires before any M07
code may be admitted: protocol, scorer contract, fixture design, license/custody,
and dependency placement. It is the GOAL.md step-1 artifact. It is **not**
an approval, an admission, a freeze, or a write lease.

It is **not**:

- an approval (GoalEx lifecycle/integration owner approves, not this lane);
- an admission (the lease map admits; this file does not recompute it);
- evidence that any M07 behaviour was measured, executed, or verified;
- a benchmark, ranking, certification, superiority, publication, leaderboard,
  official-suite, result-v2, sandbox, signed-publication, or T5 claim;
- a rewrite of M02, M04, M05, M06, or M14 plans;
- a contract for M04 Stage B or M06 implementation;
- authority to touch PR #115 files, PR #116, PR #117, or any `eval/public/*` path.

### 0.1 This document's own write-lease status

`docs/plans/` is the GoalEx owner's exclusive surface. Until that owner grants
a write slot for this exact path, this document is an **unadmitted draft
occupying a leased path** (same G0 as the M02 plan §0.1). Nothing here claims
its own placement was authorized.

### 0.2 Why this plan is NOT CODE-READY

All of the following are blocking. None is discharged by writing this file.

1. Spec WMBS-D (`…standard-design.md:1394–1398`): build M06–M13 only after
   WMBS-B **and** after each product capability exists through a public
   contract. C09 / CAP-007 is not a public contract on this base. Lease-map
   `P15-S2` is BLOCKED on `P14-B` / `N12`.
2. Spec M07 resource prerequisite (`…standard-design.md:793–794`): a measured
   admission receipt. None exists. No asserted L16 budget.
3. Spec M07 acceptance (`…standard-design.md:788–790`): protected-item
   survival 1.0, zero protected regressions, and storage/cost as a Pareto
   frontier. All other retention thresholds require calibration. No
   preregistration exists. Stage A cannot claim those bounds.
4. G0 / G1 / G2: path not lease-clean; lease map not recomputed; M07 is not
   in the first pilot (`…standard-design.md:798`). Freeze is a later step.
   This file does not freeze itself.

Missing Stage A artifacts are tree state (inventory L55), not a gate. WMBS-D
is an implement sequencing gate, not a reason to refuse this plan file.

**Verdict: NOT CODE-READY.** Do not implement from this file.

## 1. Module scope (copied from the spec, not rewritten)

Per `docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md`
§8 "M07 — Retention, rehearsal, and decay" (lines 776–799) and C09 (line 510):

- **Contract:** universal `ingest`, `retrieve`, and `answer` with a
  harness-owned virtual clock. Timestamped events alone do not prove time
  progression; an adapter must expose or faithfully emulate the clock through
  its public boundary and disclose the method.
- **Data:** seeded months-long virtual timelines with protected facts,
  high/low-utility items, repeated access, spacing schedules, stale facts, and
  storage pressure.
- **Scorer:** protected-item survival, stale-item retention, retrieval quality,
  storage growth, rehearsal cost, and unrelated-item interference.
- **Acceptance:** protected-item survival 1.0, zero protected regressions, and
  storage/cost reported as a Pareto frontier rather than hidden in a quality
  score. All other retention thresholds require calibration.
- **Repeat/replay:** at least five virtual-calendar seeds; no wall-clock
  sleeps.
- **Resource prerequisite:** measured admission receipt; no asserted L16
  budget.
- **External dependencies:** none.
- **Deferral:** reject any design that requires real-month waiting or an
  unbounded corpus; virtual time and bounded event counts are mandatory.
- **Feasibility disposition:** `PROPOSED`; not in the first pilot.
- **Placement:** advanced public outcome and internal lifecycle regression.

The spec's own exclusion is load-bearing: this contract plans a *successor*
development cell and does not reopen the first reference-harness pilot.

C24 (`…standard-design.md:525`) is a mandatory report dimension (storage/cost
Pareto already in the M07 scorer), not a second module and not a score. This
plan does not absorb M06/C08 (consolidation and learning), M08/C10 (reversible
forgetting), M09/C11 (declared-surface erasure), or M02 retrieval. Decay must
not absorb consolidation, and must not be absorbed by it (spec D7 L71).

## 2. Prerequisites (not discharged)

| ID | Gate | Owner | Status on `61f55b94` |
|---|---|---|---|
| G0 | Write slot for this path, or relocate off `docs/plans/` | GoalEx | Open |
| G1 | Lease map recomputed; M07 admitted with an exact lease | GoalEx | Open. This file does not edit the lease map. |
| G2 | Pilot-plan exclusion amended, or this file approved as successor | GoalEx | Open. Do not edit the pilots file in this artifact. |
| G3 | Public-harness integration slot (Stage B only) | Public-harness | Not reached. |
| R1 | Measured admission receipt (spec L793) | Operator | Missing. |
| R2 | C09 capability exists through a public contract (WMBS-D) | Product / P15-S2 | Blocked on P14-B / N12. |
| R3 | Calibrated non-survival retention thresholds (spec L790) | Operator | Missing. |

Technical reuse that a later Stage A may consume, once the gates above close,
is the closed ABI `wmbs/0.1-draft`, universal `ingest` / `retrieve` /
`answer`, and a harness-owned virtual clock kept **outside the SUT** (spec
L1267). Timestamped events alone are not a clock.

## 3. Fixture contract (prospective, unadmitted)

When — and only when — a later freeze and write lease exist, Stage A would
add a **new** deterministic development fixture:

- Path (prospective): `eval/public/fixtures/wmbs-m07-retention-development.json`
- Families the spec names: protected facts, high/low-utility items, repeated
  access, spacing schedules, stale facts, storage pressure.
- Seeds: at least five virtual-calendar seeds. No wall-clock sleeps. Bounded
  event counts. Byte-identical under `canonical_json(generate_fixture(seed))`.
- Closed ABI `$defs.portable_event` where the later lease claims conformance.
- Reject real-month waiting and unbounded corpora.

This paragraph does not create those files.

## 4. Scorer contract (prospective, unadmitted)

When — and only when — a later freeze and write lease exist, Stage A would
add a **new** stdlib-only oracle:

- Path (prospective): `eval/public/wmbs_m07.py`
- Metrics the spec names: protected-item survival, stale-item retention,
  retrieval quality, storage growth, rehearsal cost, unrelated-item
  interference.
- Stage A reports descriptive / finite-corpus-only intervals. It does **not**
  claim protected-item survival 1.0 or the Pareto frontier as an admission
  bound (that is R1+R3).
- Storage/cost stay a reported frontier, never folded into a quality score.
- Anti-gaming (spec L1267, L1291): virtual clock, gold, and graders stay
  outside the SUT; no privileged internal decay signal.

This paragraph does not create those files.

## 5. Custody, licence, and claim constraints

- Deterministic local roles: no external dataset, no network, no provider
  (spec L795; U-MODULES license/custody). Pin any later dataset at freeze;
  do not invent one here.
- Publication flags stay `false`. No `PILOT-READY-DEV`. No headline.
- M06 shares D7 with this module. This plan does not implement or freeze M06.

## 6. Dependency edges

```text
WMBS-B + C09 public contract (R2) + measured receipt (R1) + G0/G1/G2
  -> freeze this plan (GOAL step 2)
    -> Stage A  new oracle + fixture + tests     [unadmitted]
      -> Stage B  public-harness registration    [unadmitted; G3]
```

P15-S2 (CAP-007/008) stays behind P14-B / N12. This file does not open it.
M02 Stage B / PR #115 and M06 plan / PR #116 are different leases. Do not
touch those files. Do not write GOAL.md, STATE.md, or the lease-map (#117).

## 7. Exact future write lease (unadmitted)

No path below is writable from this document.

```text
docs/plans/wmb-m07-retention-rehearsal-decay-implementation-plan.md   (this file only)
```

Prospective Stage A (after freeze + G0/G1/G2 + R1/R2/R3), not now:

```text
eval/public/wmbs_m07.py                                      (new)
eval/public/fixtures/wmbs-m07-retention-development.json     (new)
tests/test_public_wmbs_m07.py                                (new)
```

Prospective Stage B is not designed here. Do not invent runner/registry rows.

## 8. Claim boundary

| Item | After this file | After a future Stage A | After a future Stage B |
|---|---|---|---|
| M07 disposition | `PROPOSED` | `PROPOSED` | `PROPOSED` |
| Spec survival 1.0 / Pareto admission | `DEFERRED` (R1/R3) | `DEFERRED` | `DEFERRED` until receipt |
| Retain, forget, erase (spec L1252–1259) | `DEFERRED` until M07+M08+M09 are all admitted | `DEFERRED` | `DEFERRED` |
| Publishable / headline | `false` | `false` | `false` |
| Code lease | none | only if freeze + G1 admit it | G3 |

## 9. Non-goals

- No edit to `GOAL.md`, `.planning/STATE.md`, the lease map, or T8 inventory.
- No edit to M02/M04/M05/M06/M14 plans.
- No M04 Stage B contract. No M06 implement.
- No `eval/public/*` write, including PR #115 files
  (`registry.json`, `runner.py`, `scoring.py`, `adapters/whole_memory_reference.py`,
  `README.md`, `tests/test_public_whole_memory_reference.py`,
  `tests/test_public_wmbs_stage_a_disclosure.py`, the wmbs inventory).
- No `bundle.py` write.
- No freeze. No implement.

## 10. How to tell this step is done

This step is done when this file exists on GitHub as a one-file PR with
`PROPOSED` / `NOT CODE-READY` and a reviewer can re-check §1 against spec
L776–799 without trusting this prose. It is **not** done by flipping Status
or writing any other path.
