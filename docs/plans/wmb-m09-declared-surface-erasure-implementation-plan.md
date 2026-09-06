# WMB M09 — Declared-Surface Erasure Implementation Contract

Status: `PROPOSED` / **PLANNING ARTIFACT ONLY — NOT CODE-READY.**
This file authorizes no source, fixture, registry, scorer, measurement,
admission-state, publication change, or GitHub PR beyond this one-file plan.

Author lane: M09 declared-surface-erasure planning lane.
Verified base: `origin/main@f688c74757365a9d946100687a04288cde12a7fc`.
Written: 2026-08-15.

## 0. What this document is, and what it is not

This is the exact implementation contract `U-MODULES` requires before any M09
code may be admitted: protocol, scorer contract, fixture design, license/custody,
and dependency placement. It is the GOAL.md step-1 artifact. It is **not**
an approval, an admission, a freeze, or a write lease.

It is **not**:

- an approval (GoalEx lifecycle/integration owner approves, not this lane);
- an admission (the lease map admits; this file does not recompute it);
- evidence that any M09 behaviour was measured, executed, or verified;
- a benchmark, ranking, certification, superiority, publication, leaderboard,
  official-suite, result-v2, sandbox, signed-publication, or T5 claim;
- a legal-compliance opinion, an "erasure certified" label, or a
  certified/governed claim;
- a rewrite of M02, M04, M05, M06, M07, M08, or M14 plans;
- a contract for M04 Stage B or any other module's implementation;
- authority to touch PR #116, #117, #118, #119, #120, #121, or any
  `eval/public/*` path.

### 0.1 This document's own write-lease status

`docs/plans/` is the GoalEx owner's exclusive surface. Until that owner grants
a write slot for this exact path, this document is an **unadmitted draft
occupying a leased path** (same G0 as the M02 plan §0.1). Nothing here claims
its own placement was authorized.

### 0.2 Why this plan is NOT CODE-READY

**Source-readiness blockers** (must clear before descriptive Stage A). None
is discharged by writing this file.

1. Spec WMBS-D (`…standard-design.md:1394–1398`): build M06–M13 only after
   WMBS-B **and** after each product capability exists through a public
   contract. C11 / RAIL-001 is not a public contract on this base (same as R2).
2. G0 / G1 / G2: path not lease-clean; lease map not recomputed; M09 is not
   in the first pilot (`…standard-design.md:847–848`). Freeze is a later step.
   This file does not freeze itself. CoS ACCEPT of this one-file plan is the
   GoalEx write-slot grant for this Exact 1 path only; it does not recompute
   the lease-map or inventory.
3. Spec M09 deferral (`…standard-design.md:843–845`): no erasure claim if any
   declared readable surface cannot be probed, backup scope is undisclosed,
   or identity authorization cannot be exercised. Unsupported systems receive
   no erasure claim. An unprobeable surface is not a pass.

**Measured / admitted-claim gates** (not Stage A source blockers). R1 and
acceptance bounds do **not** refuse descriptive Stage A.

- R1 — Spec M09 resource prerequisite (`…standard-design.md:839–840`): measured
  local or P32 receipt for the exact declared surfaces. Gates measured/admitted
  claims only; Stage A oracle/fixture/tests create the inputs that later earn
  that receipt.
- Spec M09 acceptance (`…standard-design.md:832–836`): zero recoverable
  residue, zero unrelated mutation, 100% valid signed receipts, zero
  attributable semantic leakage where gold ties the leaked fact to the erased
  subject. Gates scored-run acceptance evidence only (independent of R1).

**Deferred surfaces (not Stage A):** P32 replicas, object storage, and full
PITR (`…standard-design.md:846–847`).

Missing Stage A artifacts are tree state, not a gate. WMBS-D is an implement
sequencing gate, not a reason to refuse this plan file. Inventory reconcile
after this plan merges is a separate GoalEx Exact-1 on the completeness
inventory — not this PR.

**Verdict: NOT CODE-READY.** Do not implement from this file until the
**source-readiness blockers** above clear. Do not treat R1 or acceptance
bounds as Stage A source blockers.

## 1. Module scope (copied from the spec, not rewritten)

Per `docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md`
§8 "M09 — Declared-surface erasure conformance" (lines 822–849) and C11
(line 512):

- **Contract:** Section 6 `delete(selector, mode=declared_surface_erasure)`,
  `retrieve`/`answer`, and declared `snapshot`/`restore_snapshot` surfaces.
- **Data:** deterministic identity-linked evidence, derivatives, indexes,
  caches, intentions, working state, unrelated tenant controls, and restore
  probes.
- **Scorer:** direct residue, semantic leakage, false deletion, unrelated
  mutation, completion SLA, and signed receipt validity.
- **Acceptance:** zero recoverable residue on every declared surface, zero
  unrelated mutation, 100% valid signed receipts, and zero attributable
  semantic leakage where the gold can objectively tie the leaked fact to the
  erased subject. Passing is technical conformance for declared surfaces, not
  a legal-compliance opinion.
- **Repeat/replay:** three delete-operation IDs, retry after each injected
  crash boundary, and one restore pass for every declared readable snapshot.
- **Resource prerequisite:** measured local or P32 receipt for the exact
  declared surfaces.
- **External dependencies:** Docker/P32 only for production replicas, object
  storage, and full PITR.
- **Deferral:** no erasure certification if any declared readable surface
  cannot be probed, backup scope is undisclosed, or identity authorization
  cannot be exercised. Unsupported systems receive no erasure claim.
- **Feasibility disposition:** `PROPOSED` for Local/SQLite declared surfaces;
  P32 replicas/object storage/PITR are `DEFERRED`. M09 is not in the first
  pilot.
- **Placement:** mandatory pass/fail gate for legal-erasure claims.

The spec's own exclusion is load-bearing: this contract plans a *successor*
development cell and does not reopen the first reference-harness pilot.

C11 (`…standard-design.md:512`) is a mandatory gate for erasure claims and is
explicitly **not** legal compliance. `M-ERASURE` (`…standard-design.md:599`)
is the rail: recoverable residue on declared evaluated surfaces is zero.
C24 (`…standard-design.md:525`) is a mandatory report dimension, not a second
module and not a score. This plan does not absorb M07/C09 (retention,
rehearsal, decay), M08/C10 (reversible forgetting), M06/C08 (consolidation),
or M02 retrieval. Declared-surface erasure must not be treated as reversible
forgetting, and must not absorb decay.

The spec's "no erasure certification" sentence is a **deferral gate**, not a
claim this file may make. This plan never labels a run "erasure certified."

## 2. Prerequisites (not discharged)

| ID | Gate | Owner | Status on `f688c747` |
|---|---|---|---|
| G0 | Write slot for this path, or relocate off `docs/plans/` | GoalEx | Open |
| G1 | Lease map recomputed; M09 admitted with an exact lease | GoalEx | Open. This file does not edit the lease map. |
| G2 | Pilot-plan exclusion amended, or this file approved as successor | GoalEx | Open. Do not edit the pilots file in this artifact. |
| G3 | Public-harness integration slot (Stage B only) | Public-harness | Not reached. |
| R1 | Measured local or P32 receipt for the exact declared surfaces (spec L839–840) | Operator | Missing — measured-claim gate, not Stage A source. |
| R2 | C11 capability exists through a public contract (WMBS-D) | Product | Open. |
| R3 | Every declared readable surface is probeable; backup scope disclosed; identity authorization exercisable. Else no erasure claim (spec L843–845) | Public-harness | Open. An unprobeable surface is not a pass. |
| R4 | P32 / object storage / PITR surfaces | Operator | `DEFERRED`. Not in this cell. |

Technical reuse that a later Stage A may consume, once the gates above close,
is the closed ABI `wmbs/0.1-draft` and Section 6
`delete(selector, mode=declared_surface_erasure)` plus `retrieve`/`answer`
and declared `snapshot`/`restore_snapshot` surfaces. Crash-retry replay uses
three delete-operation IDs and retries after each injected crash boundary.

## 3. Fixture contract (prospective, unadmitted)

When — and only when — a later freeze and write lease exist, Stage A would
add a **new** deterministic development fixture:

- Path (prospective): `eval/public/fixtures/wmbs-m09-declared-surface-erasure-development.json`
- Families the spec names: identity-linked evidence, derivatives, indexes,
  caches, intentions, working state, unrelated tenant controls, restore
  probes.
- Same-tenant survivors required: for a selector that targets one
  subject/source within a tenant, the fixture must include non-selected
  same-tenant records as gold survivors so whole-tenant wipe cannot pass
  false-deletion scoring.
- Replay: three delete-operation IDs; retry after each injected crash
  boundary; one restore pass for every declared readable snapshot.
  Byte-identical under `canonical_json(generate_fixture(seed))`.
- Closed ABI `$defs.portable_event` where the later lease claims conformance.
- Local/SQLite declared surfaces only. P32 / object / PITR stay `DEFERRED`.

This paragraph does not create those files.

## 4. Scorer contract (prospective, unadmitted)

When — and only when — a later freeze and write lease exist, Stage A would
add a **new** stdlib-only oracle:

- Path (prospective): `eval/public/wmbs_m09.py`
- Metrics the spec names: direct residue, semantic leakage, false deletion,
  unrelated mutation, completion SLA, signed receipt validity.
- Stage A reports descriptive / finite-corpus-only intervals. It does **not**
  claim zero residue, zero unrelated mutation, 100% receipt validity, or zero
  attributable semantic leakage as an admission bound (that is R1 + scored
  acceptance; R1 does not discharge acceptance evidence alone).
- Signed receipt validity (Local/SQLite): bind to the existing fail-closed
  Ed25519 contract in `docs/ENGINE-CONTRACT.md` via
  `verify_signed_deletion_manifest`. **Trust root is harness-owned** — Stage A
  pins a fixture/harness public key; entrant-supplied `public_key_path` alone
  is not sufficient (an entrant must not mint a keypair and self-attest). Do
  not invent a parallel receipt crypto path.
- An unprobeable declared readable surface, undisclosed backup scope, or
  unexercisable identity authorization yields **no erasure claim**, not a
  pass and not a zero-as-failure substitute.
- Anti-gaming (spec L1291): no privileged internal wipe signal; gold,
  graders, and canaries stay outside the SUT.

This paragraph does not create those files.

## 5. Custody, licence, and claim constraints

- Deterministic local roles: no external dataset, no network, no provider
  (spec L841–842; U-MODULES license/custody). Pin any later dataset at freeze;
  do not invent one here. Docker/P32 stays out until R4 is admitted.
- Publication flags stay `false`. No `PILOT-READY-DEV`. No headline.
- No "erasure certified," certified, or governed label. Passing, if it ever
  happens, is technical conformance for declared surfaces only.

## 6. Dependency edges

```text
WMBS-B + C11 public contract (R2) + G0/G1/G2 + R3 (probeable surfaces /
disclosed backup scope / exercisable identity auth, or explicit no-claim path)
  -> freeze this plan (GOAL step 2)
    -> Stage A  descriptive oracle + fixture + tests   [unadmitted; R1 not required]
      -> measured / admitted claims require R1 receipt
      -> Stage B  public-harness registration          [unadmitted; G3]
```

R1 gates measured/admitted profile claims, not creation of the Stage A
oracle/fixture/tests that produce receipt inputs. Spec §4.2 allows
`CONTRACT-READY` before a measured receipt.

P32 / object / PITR stay behind R4. Do not touch PR #116, #117, #118, #119,
#120, or #121. Do not write GOAL.md, STATE.md, or the lease-map.

## 7. Exact future write lease (unadmitted)

No path below is writable from this document.

```text
docs/plans/wmb-m09-declared-surface-erasure-implementation-plan.md   (this file only)
```

Prospective Stage A (after freeze + G0/G1/G2 + R2 + R3; R1 gates measured
claims only), not now:

```text
eval/public/wmbs_m09.py                                                      (new)
eval/public/fixtures/wmbs-m09-declared-surface-erasure-development.json       (new)
tests/test_public_wmbs_m09.py                                                 (new)
```

Prospective Stage B is not designed here. Do not invent runner/registry rows.

## 8. Claim boundary

| Item | After this file | After a future Stage A | After a future Stage B |
|---|---|---|---|
| M09 Local/SQLite disposition | `PROPOSED` | `PROPOSED` | `PROPOSED` |
| P32 / object / PITR | `DEFERRED` | `DEFERRED` | `DEFERRED` until R4 |
| Spec residue / mutation / receipt bounds | `DEFERRED` (R1/R3) | `DEFERRED` | `DEFERRED` until receipt |
| Legal-compliance / "erasure certified" | never claimed | never claimed | never claimed |
| Retain, forget, erase (spec L1252–1259) | `DEFERRED` until M07+M08+M09 are all admitted | `DEFERRED` | `DEFERRED` |
| Publishable / headline | `false` | `false` | `false` |
| Code lease | none | only if freeze + G1 admit it | G3 |

## 9. Non-goals

- No edit to `GOAL.md`, `.planning/STATE.md`, the lease map, or T8 inventory.
- No edit to M02/M04/M05/M06/M07/M08/M14 plans.
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
L822–849 without trusting this prose. It is **not** done by flipping Status
or writing any other path.

## 11. Locked public-harness cell (do not write README from this PR)

The block below is the only allowed future `eval/public/README.md` cell for
this module. Place it as a peer of the M02, M03, M07, and M08 cells, not
under the M02/M04/M05 Stage-A oracles heading. This PR does not write
`eval/public/README.md`.

Do not add a `uv run --suite` line until a registry row exists.

```markdown
### M09 declared-surface erasure

PROPOSED for Local/SQLite declared surfaces. P32 replicas, object storage,
and PITR are DEFERRED. All publication flags false. Passing is technical
conformance for declared surfaces, not a legal-compliance opinion.

`delete(selector, mode=declared_surface_erasure)`. Zero recoverable residue
on every declared surface. Zero unrelated mutation. 100% valid signed
receipts. Crash-retry replay: three delete-operation IDs, retry after each
injected crash boundary, one restore pass for every declared readable
snapshot. No pass on an unprobeable surface.

No registry row exists, so this cell is not runnable.
```
