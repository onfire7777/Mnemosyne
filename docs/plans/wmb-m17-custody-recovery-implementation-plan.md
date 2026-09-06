# WMB M17 — Custody and Recovery Implementation Contract

Status: `PROPOSED` / **PLANNING ARTIFACT ONLY — NOT CODE-READY.**
This file is **planning-only / non-executable design**. It authorizes no
source, fixture, registry, scorer, measurement, admission-state, publication
change, Stage A implement path, or GitHub PR beyond this one-file plan.
ACCEPT of this document does **not** lease or green-light Stage A code.

Author lane: M17 custody-and-recovery planning lane.
Verified base: `origin/main@f688c74757365a9d946100687a04288cde12a7fc`.
Written: 2026-08-15.

## 0. What this document is, and what it is not

This is the exact implementation contract `U-MODULES` requires before any M17
code may be admitted: protocol, scorer contract, fixture design, license/custody,
and dependency placement. It is the GOAL.md step-1 artifact. It is **not**
an approval, an admission, a freeze, or a write lease.

It is **not**:

- an approval (GoalEx lifecycle/integration owner approves, not this lane);
- an admission (the lease map admits; this file does not recompute it);
- evidence that any M17 behaviour was measured, executed, or verified;
- a benchmark, ranking, certification, superiority, publication, leaderboard,
  official-suite, result-v2, sandbox, signed-publication, or T5 claim;
- a production-certification, "recovery certified" label, or a
  certified/governed claim;
- a rewrite of M02, M04, M05, M06, M07, M08, M09, M11, or M14 plans
  (M14 stays `NOT CODE-READY`);
- an M16 plan or an M16 implement (M16 is skipped);
- a contract for M04 Stage B or any other module's implementation;
- authority to touch PR #116, #117, #118, #119, #120, #121, #122, #123, or
  any `eval/public/*` path.

### 0.1 This document's own write-lease status

`docs/plans/` is the GoalEx owner's exclusive surface. Until that owner grants
a write slot for this exact path, this document is an **unadmitted draft
occupying a leased path** (same G0 as the M02 plan §0.1). Nothing here claims
its own placement was authorized.

### 0.2 Why this plan is NOT CODE-READY

All of the following are blocking. None is discharged by writing this file.

1. Spec WMBS-E (`…standard-design.md:1400–1403`): build M16–M19 plus H8/P32
   profiles only after the behavior being claimed and the relevant
   hardware/custody gates are admitted. C19 / RAIL-001 is not an admitted
   public contract on this base.
2. Spec M17 resource prerequisite (`…standard-design.md:1042–1043`): a
   measured local receipt or an admitted P32 recovery receipt for the exact
   claimed surfaces. None exists. Stage A remains **unexecutable** until R1
   is present; this planning file does not authorize a Stage A implement path.
3. Spec M17 acceptance (`…standard-design.md:1038–1041`): zero acknowledged
   loss, zero duplicate externally visible effects, complete audit continuity,
   and an RPO/RTO tier frozen by the standard before the run. A
   submitter-selected target cannot certify itself. No frozen RPO/RTO tier
   or receipt protocol exists on this base. Stage A cannot claim those
   bounds. Passing is operator/internal certification shape, not a
   production-certification opinion.
4. Spec M17 deferral (`…standard-design.md:1047–1049`): production
   certification defers when retained infrastructure, external custody, or
   an independently recorded expected fingerprint is absent. Local results
   cannot close production rows.
5. G0 / G1 / G2: path not lease-clean; lease map not recomputed; M17 is not
   in the first pilot (`…standard-design.md:1050`). Freeze is a later step.
   This file does not freeze itself.
6. P32 recovery certification is `DEFERRED` (`…standard-design.md:1049–1050`).
   PostgreSQL / object-store / PITR requires P32 and pinned service images
   (`…standard-design.md:1044–1045`). This plan does not admit them.

Missing Stage A artifacts are tree state, not a gate. WMBS-E is an implement
sequencing gate, not a reason to refuse this plan file.

**Verdict: NOT CODE-READY.** Do not implement from this file.

## 1. Module scope (copied from the spec, not rewritten)

Per `docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md`
§8 "M17 — Custody and recovery" (lines 1030–1051) and C19 (line 520):

- **Contract:** advanced `health`/`queue_state`/`snapshot`/
  `restore_snapshot` plus normal operations.
- **Data:** deterministic queue redelivery, partial outage, crash-after-commit,
  object loss, retry, backup, and PITR scenarios.
- **Scorer:** acknowledged loss, duplicate external effects, recovery
  completeness, RPO/RTO, audit continuity, and operator steps.
- **Acceptance:** zero acknowledged loss, zero duplicate externally visible
  effects, complete audit continuity, and an RPO/RTO tier frozen by the
  standard before the run; a submitter-selected target cannot certify itself.
- **Repeat/replay:** three crash points per scenario and two clean restores.
- **Resource prerequisite:** a measured local receipt or an admitted P32
  recovery receipt for the exact claimed surfaces.
- **External dependencies:** PostgreSQL/object-store/PITR requires P32 and
  pinned service images.
- **Deferral:** production certification defers when retained infrastructure,
  external custody, or an independently recorded expected fingerprint is
  absent. Local results cannot close production rows.
- **Feasibility disposition:** `PROPOSED` for local fault injection; P32
  recovery certification is `DEFERRED`. M17 is not in the first pilot.
- **Placement:** operator/internal certification.

The spec's own exclusion is load-bearing: this contract plans a *successor*
development cell and does not reopen the first reference-harness pilot.

C19 is an advanced operational gate (RAIL-001), not a score.
`M-AUDIT-COMPLETE` (`…standard-design.md:598`) stays a rail: every write has
a complete audit record. C24 (`…standard-design.md:525`) is a mandatory
report dimension, not a second module. This plan does not absorb M16/C18
(backend parity; M16 is skipped), M15/C17, M20, M09/C11, M11/C15–C16, or
M02 retrieval. Local fault injection must not be treated as P32 recovery
certification, and must not close a production row.

The spec's "production certification defers" sentence is a **deferral gate**,
not a claim this file may make. This plan never labels a run "recovery
certified."

## 2. Prerequisites (not discharged)

| ID | Gate | Owner | Status on `f688c747` |
|---|---|---|---|
| G0 | Write slot for this path, or relocate off `docs/plans/` | GoalEx | Open |
| G1 | Lease map recomputed; M17 admitted with an exact lease | GoalEx | Open. This file does not edit the lease map. |
| G2 | Pilot-plan exclusion amended, or this file approved as successor | GoalEx | Open. Do not edit the pilots file in this artifact. |
| G3 | Public-harness integration slot (Stage B only) | Public-harness | Not reached. |
| R1 | Measured local or admitted P32 recovery receipt for the exact claimed surfaces (spec L1042–1043) | Operator | Missing — **required before any Stage A implement lease**. Planning ACCEPT alone does not authorize Stage A. |
| R2 | C19 capability exists through an admitted public contract (WMBS-E) | Product | Open. |
| R3 | RPO/RTO tier frozen by the standard before the run. A submitter-selected target cannot certify itself (spec L1038–1041) | Standard owner | Open. |
| R4 | Retained infrastructure, external custody, and an independently recorded expected fingerprint, required to close any production row (spec L1047–1049) | Operator | Open. Local results cannot close production rows. |
| R5 | P32 recovery / PostgreSQL / object-store / PITR | Operator | `DEFERRED`. Requires P32 and pinned service images. Not in this cell. |

Technical reuse that a later Stage A may consume, once the gates above close,
is the closed ABI `wmbs/0.1-draft` and Section 6 `health` / `queue_state` /
`snapshot` / `restore_snapshot` plus normal operations. Replay uses three
crash points per scenario and two clean restores.

## 3. Fixture contract (prospective, unadmitted)

When — and only when — a later freeze and write lease exist, Stage A would
add a **new** deterministic development fixture:

- Path (prospective): `eval/public/fixtures/wmbs-m17-custody-recovery-development.json`
- Families the spec names for **local Stage A**: queue redelivery, partial
  outage, crash-after-commit, object loss, retry, backup. **PITR scenarios
  are OUT of Stage A** — they require R5 / P32 and pinned services.
- Freeze residual (NOT CODE-READY): canonical fixture shape — seed/version,
  top-level and per-scenario schemas, scenario cardinalities, crash-point
  placement, and expected post-recovery state/fingerprints — must be frozen
  so two implementers produce byte-identical gold under the same seed, not
  merely self-consistent `canonical_json(generate_fixture(seed))`.
- Replay: three crash points per local scenario and two clean restores.
  Byte-identical under `canonical_json(generate_fixture(seed))` after that
  freeze.
- Closed ABI `$defs.portable_event` where the later lease claims conformance.
- Local fault injection only. P32 / PostgreSQL / object-store / PITR stay
  `DEFERRED` (R5) — do not invent PITR rows in the Stage A fixture.

This paragraph does not create those files.

## 4. Scorer contract (prospective, unadmitted)

When — and only when — a later freeze and write lease exist, Stage A would
add a **new** stdlib-only oracle:

- Path (prospective): `eval/public/wmbs_m17.py`
- Metrics the spec names: acknowledged loss, duplicate external effects,
  recovery completeness, RPO/RTO, audit continuity, operator steps.
- Stage A reports descriptive / finite-corpus-only intervals. It does **not**
  claim zero acknowledged loss, zero duplicate external effects, complete
  audit continuity, or a frozen RPO/RTO tier as an admission bound. A
  submitter-selected target cannot certify itself.
- Freeze residual (keeps NOT CODE-READY): observation/receipt schema,
  denominators, RPO/RTO calculation, audit-continuity rules, malformed-input
  behavior, aggregation, pass semantics, **and canonical metric IDs** for
  each gate (acknowledged loss, duplicate effects, recovery completeness,
  RPO/RTO, operator steps — spec L176–180) must be frozen before Stage A
  implement — prose metric names alone are not a scorer contract. Closed ABI has no
  `health` / `queue_state` / `snapshot` / `restore_snapshot`; Stage A harness
  injection must name how those observations are produced without inventing
  ABI ops here.
- Local results cannot close production rows. Missing retained
  infrastructure, external custody, or an independently recorded expected
  fingerprint yields **no production claim**, not a pass.
- Anti-gaming (spec L1291): no privileged internal recovery signal; gold,
  graders, and expected fingerprints stay outside the SUT.

This paragraph does not create those files.

## 5. Custody, licence, and claim constraints

- Deterministic local roles: no external dataset, no network, no provider
  (spec L1044–1045; U-MODULES license/custody). Pin any later dataset at
  freeze; do not invent one here. P32 / pinned service images stay out
  until R5 is admitted.
- Generated Stage A fixture license: **`CC0-1.0`** (SPDX) for the synthetic
  local fixture — required for U-MODULES rights/BOM metadata.
- Publication flags stay `false`. No `PILOT-READY-DEV`. No headline.
- No "recovery certified," certified, or governed label. Passing, if it
  ever happens, is operator/internal certification shape for local fault
  injection only. Local results cannot close production rows.

## 6. Dependency edges

```text
WMBS-E + C19 public contract (R2) + G0/G1/G2
  -> freeze observation/receipt schema + RPO/RTO definitions (R3 residual)
  -> freeze this plan (GOAL step 2)   [planning-only; no Stage A lease]
    -> measured local / admitted P32 recovery receipt (R1) on frozen schema
    -> Stage A  descriptive oracle + fixture + tests   [unadmitted; R1 required]
      -> Stage B  public-harness registration          [unadmitted; G3]
```

Per M17 resource prerequisite (spec L1042–1043), Stage A stays **unexecutable**
until R1 is present. This planning file never authorizes a Stage A implement
path. P32 recovery stays behind R5. Do not write GOAL.md, STATE.md, or the
lease-map. Do not invent M16.

## 7. Exact future write lease (unadmitted)

No path below is writable from this document.

```text
docs/plans/wmb-m17-custody-recovery-implementation-plan.md   (this file only)
```

Prospective Stage A (after freeze + G0/G1/G2 + R2 + receipt-schema freeze **and R1**), not now — unleased by this plan:

```text
eval/public/wmbs_m17.py                                              (new)
eval/public/fixtures/wmbs-m17-custody-recovery-development.json      (new)
tests/test_public_wmbs_m17.py                                        (new)
```

Prospective Stage B is not designed here. Do not invent runner/registry rows.

## 8. Claim boundary

| Item | After this file | After a future Stage A | After a future Stage B |
|---|---|---|---|
| M17 local fault-injection disposition | `PROPOSED` | `PROPOSED` | `PROPOSED` |
| P32 recovery certification | `DEFERRED` | `DEFERRED` | `DEFERRED` until R5 |
| Production row | cannot close | cannot close | cannot close until R4 |
| Spec loss / duplicate / audit / RPO-RTO bounds | `DEFERRED` (R1/R3) | `DEFERRED` | `DEFERRED` until receipt |
| "Recovery certified" | never claimed | never claimed | never claimed |
| Authorized future action (spec L1252–1259) | `DEFERRED` until M11+M12+M17 are all admitted | `DEFERRED` | `DEFERRED` |
| Recoverable public evidence (spec L1252–1259) | `DEFERRED` until M15+M16+M17+M20 are all admitted | `DEFERRED` | `DEFERRED` |
| Publishable / headline | `false` | `false` | `false` |
| Code lease | none | only if freeze + G1 admit it | G3 |

## 9. Non-goals

- No edit to `GOAL.md`, `.planning/STATE.md`, the lease map, or T8 inventory.
- No edit to M02/M04/M05/M06/M07/M08/M09/M11/M14 plans. M14 stays
  `NOT CODE-READY`. No M16 plan.
- No M04-B write. The live M04-B seven files on PR #121 stay untouched:
  `eval/public/README.md`,
  `eval/public/adapters/whole_memory_reference.py`,
  `eval/public/registry.json`,
  `eval/public/runner.py`,
  `eval/public/scoring.py`,
  `tests/test_public_whole_memory_reference.py`,
  `tests/test_public_wmbs_stage_a_disclosure.py`.
- No other `eval/public/*` write, including `bundle.py`.
- No freeze. No implement.

## 10. How to tell this step is done

This step is done when this file exists on GitHub as a one-file PR with
`PROPOSED` / `NOT CODE-READY` and a reviewer can re-check §1 against spec
L1030–1051 without trusting this prose. It is **not** done by flipping Status
or writing any other path.

## 11. Locked public-harness cell (do not write README from this PR)

The block below is the only allowed future `eval/public/README.md` cell for
this module. Place it as a peer of the M02, M03, M07, M08, M09, and M11
cells, not under the M02/M04/M05 Stage-A oracles heading. This PR does not
write `eval/public/README.md`. Frontend has not filed an M17 cell rec yet;
this block is spec-derived only.

Do not add a `uv run --suite` line until a registry row exists.

```markdown
### M17 custody and recovery

PROPOSED for local fault injection. P32 recovery certification is DEFERRED.
All publication flags false. Passing is operator/internal certification
shape, not a production-certification opinion. Local results cannot close
production rows.

`health` / `queue_state` / `snapshot` / `restore_snapshot` plus normal
operations. Zero acknowledged loss. Zero duplicate externally visible
effects. Complete audit continuity. RPO/RTO tier frozen by the standard
before the run; a submitter-selected target cannot certify itself. Three
crash points per scenario and two clean restores.

No registry row exists, so this cell is not runnable.
```
