# WMB M18 — Interoperability Implementation Contract

Status: `PROPOSED` / **PLANNING ARTIFACT ONLY — NOT CODE-READY.**
This file authorizes no source, fixture, registry, scorer, measurement,
admission-state, publication change, or GitHub PR beyond this one-file plan.

Author lane: M18 interoperability planning lane.
Verified base: `origin/main@f688c74757365a9d946100687a04288cde12a7fc`.
Written: 2026-08-15.

## 0. What this document is, and what it is not

This is the exact implementation contract `U-MODULES` requires before any M18
code may be admitted: protocol, scorer contract, fixture design, license/custody,
and dependency placement. It is the GOAL.md step-1 artifact. It is **not**
an approval, an admission, a freeze, or a write lease.

It is **not**:

- an approval (GoalEx lifecycle/integration owner approves, not this lane);
- an admission (the lease map admits; this file does not recompute it);
- evidence that any M18 behaviour was measured, executed, or verified;
- a benchmark, ranking, certification, superiority, publication, leaderboard,
  official-suite, result-v2, sandbox, signed-publication, or T5 claim;
- a public-interoperability certification, "interop certified" label, or a
  certified/governed claim;
- a rewrite of M02, M04, M05, M06, M07, M08, M09, M11, M14, or M17 plans
  (M14 stays `NOT CODE-READY`; #124 is not edited);
- an M16 plan or an M16 implement (M16 stays `PROPOSED` under the governing
  standard for Local/SQLite/local-MCP; this lane does not invent M16);
- a contract for M04 Stage B or any other module's implementation;
- authority to touch PR #116, #117, #118, #119, #120, #121, #122, #123,
  #124, or any `eval/public/*` path.

### 0.1 This document's own write-lease status

`docs/plans/` is the GoalEx owner's exclusive surface. Until that owner grants
a write slot for this exact path, this document is an **unadmitted draft
occupying a leased path** (same G0 as the M02 plan §0.1). Nothing here claims
its own placement was authorized.

### 0.2 Why this plan is NOT CODE-READY

All of the following are blocking. None is discharged by writing this file.

1. Spec WMBS-E (`…standard-design.md:1400–1403`): build M16–M19 plus H8/P32
   profiles only after the behavior being claimed and the relevant
   hardware/custody gates are admitted. C20 / BENCH-001/006 is not an
   admitted public contract on this base.
2. Spec M18 resource prerequisite (`…standard-design.md:1065–1066`): measured
   receipts from at least two independent implementations — required for a
   **public interoperability claim only**, not for descriptive Stage A /
   internal single-system round-trip. None exist yet.
3. Spec M18 acceptance (`…standard-design.md:1060–1062`): 100% preservation
   of required fields and 100% rejection of unknown critical fields.
   Semantic delta remains diagnostic until an equivalence margin is
   calibrated and powered. No frozen envelope, calibrated margin, or receipt
   protocol exists on this base. Stage A cannot claim those bounds. Passing
   a single-system round-trip is an internal result, not a public
   certification.
4. Spec M18 deferral (`…standard-design.md:1069–1071`): public
   interoperability certification defers until a second adapter exists.
   Single-system round-trip remains an internal result.
5. G0 / G1 / G2: path not lease-clean; lease map not recomputed; M18 is not
   in the first pilot (`…standard-design.md:1074`). Freeze is a later step.
   This file does not freeze itself.
6. Public certification is `DEFERRED` until a frozen envelope and a second
   independently implemented adapter exist (`…standard-design.md:1067–1068,
   1072–1074`). This plan does not invent either.

Missing Stage A artifacts are tree state, not a gate. WMBS-E is an implement
sequencing gate, not a reason to refuse this plan file.

**Verdict: NOT CODE-READY.** Do not implement from this file.

## 1. Module scope (copied from the spec, not rewritten)

Per `docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md`
§8 "M18 — Interoperability" (lines 1053–1075) and C20 (line 521):

- **Contract:** advanced export/import with a versioned portable envelope;
  transport conformance uses public adapter schemas.
- **Data:** deterministic evidence, corrections, provenance, deletions,
  intentions, and unsupported-extension cases.
- **Scorer:** required-field preservation, semantic query delta before/after
  migration, rejection of unknown critical fields, and loss disclosure.
- **Acceptance:** 100% preservation of required fields and 100% rejection of
  unknown critical fields. Semantic delta remains diagnostic until an
  equivalence margin is calibrated and powered.
- **Repeat/replay:** three export orderings and two round trips.
- **Resource prerequisite:** measured receipts from at least two independent
  implementations for a public interoperability claim.
- **External dependencies:** at least two independently implemented adapters
  are required for public certification.
- **Deferral:** public interoperability certification defers until a second
  adapter exists; single-system round-trip remains an internal result.
- **Feasibility disposition:** `PROPOSED` for internal single-system
  round-trip; public certification is `DEFERRED` until a frozen envelope and
  second adapter exist. M18 is not in the first pilot.
- **Placement:** advanced public certification.

The spec's own exclusion is load-bearing: this contract plans a *successor*
development cell and does not reopen the first reference-harness pilot.

C20 is scoped conformance shared with M16 (BENCH-001/006; RAIL-001). This
plan does not absorb M16/C18 (backend/transport parity — M16 remains
  `PROPOSED` elsewhere; no invent M16 here), M17/C19,
M15/C17, M20, or M02 retrieval. A single-system round-trip must not be
treated as public interoperability certification.

The spec's "public interoperability certification defers" sentence is a
**deferral gate**, not a claim this file may make. This plan never labels a
run "interop certified."

## 2. Prerequisites (not discharged)

| ID | Gate | Owner | Status on `f688c747` |
|---|---|---|---|
| G0 | Write slot for this path, or relocate off `docs/plans/` | GoalEx | Open |
| G1 | Lease map recomputed; M18 admitted with an exact lease | GoalEx | Open. This file does not edit the lease map. |
| G2 | Pilot-plan exclusion amended, or this file approved as successor | GoalEx | Open. Do not edit the pilots file in this artifact. |
| G3 | Public-harness integration slot (Stage B only) | Public-harness | Not reached. |
| R1 | Measured receipts from at least two independent implementations (spec L1065–1066) | Operator | Missing — public-claim gate only, not Stage A source. |
| R2 | C20 capability exists through an admitted public contract (WMBS-E) | Product | Open. Shared with M16; M16 stays `PROPOSED` elsewhere and is not absorbed or invented here. |
| R3 | Equivalence margin calibrated and powered before semantic delta leaves diagnostic (spec L1060–1062) | Standard owner | Open. |
| R4 | Frozen versioned portable envelope | Standard owner | Open. |
| R5 | Second independently implemented adapter (spec L1067–1071) | Product | Open. Public certification requires **R1+R5** together; R5 alone is insufficient. |

Technical reuse that a later Stage A may consume, once the gates above close,
is the closed ABI `wmbs/0.1-draft` and Section 6 `export` / `import` with a
versioned portable envelope. Transport conformance uses public adapter
schemas. Replay uses three export orderings and two round trips.

## 3. Fixture contract (prospective, unadmitted)

When — and only when — a later freeze and write lease exist, Stage A would
add a **new** deterministic development fixture:

- Path (prospective): `eval/public/fixtures/wmbs-m18-interoperability-development.json`
- Families the spec names: evidence, corrections, provenance, deletions,
  intentions, unsupported-extension cases.
- Replay: three export orderings and two round trips. Byte-identical under
  `canonical_json(generate_fixture(seed))`.
- Closed ABI `$defs.portable_event` where the later lease claims conformance.
- Internal single-system round-trip only. A second adapter and public
  certification stay `DEFERRED`.
- Freeze residual (NOT CODE-READY): case schema, fixed seeds/cases, the three
  precise export orderings, round-trip transitions, and gold observations must
  be frozen before Stage A implement — family names alone are not a fixture
  design.

This paragraph does not create those files.

## 4. Scorer contract (prospective, unadmitted)

When — and only when — a later freeze and write lease exist, Stage A would
add a **new** stdlib-only oracle:

- Path (prospective): `eval/public/wmbs_m18.py`
- Metrics the spec names: required-field preservation, semantic query delta
  before/after migration, rejection of unknown critical fields, loss
  disclosure.
- Stage A reports descriptive / finite-corpus-only intervals. It does **not**
  claim 100% required-field preservation or 100% unknown-critical rejection
  as an admission bound. Semantic delta stays diagnostic until R3.
- Freeze residual (NOT CODE-READY): which envelope fields count, denominators,
  malformed-input behavior, aggregation, and pass semantics must be frozen
  before Stage A implement — metric names alone are not a scorer contract.
- Wire freeze residual (NOT CODE-READY): concrete export/import request,
  response, receipt, envelope-version, and error/idempotency schemas must be
  frozen before Stage A or a second adapter — do not invent them here.
- A single-system round-trip is an internal result. Missing a second
  independently implemented adapter yields **no public interoperability
  claim**, not a pass.
- Anti-gaming (spec L1291): no privileged internal envelope signal; gold,
  graders, and expected fingerprints stay outside the SUT.

This paragraph does not create those files.

## 5. Custody, licence, and claim constraints

- Deterministic local roles: no external dataset, no network, no provider
  (U-MODULES license/custody). A second adapter stays out until R5 is admitted.
- Generated Stage A fixture license: `CC0-1.0` (synthetic; same pin as
  M02/M05/M08). Pin any later non-synthetic dataset at freeze; do not invent
  one here.
- Publication flags stay `false`. No `PILOT-READY-DEV`. No headline.
- No "interop certified," certified, or governed label. Passing, if it ever
  happens, is an internal single-system round-trip only. Public
  certification stays `DEFERRED`.

## 6. Dependency edges

```text
WMBS-E + C20 public contract (R2) + G0/G1/G2 + frozen envelope (R4)
  -> freeze this plan (GOAL step 2)
    -> Stage A  descriptive oracle + fixture + tests   [unadmitted; R1 not required]
      -> public interoperability claim / certification requires R1 receipts + R5 second adapter
      -> Stage B  public-harness registration          [unadmitted; G3]
```

R4 (frozen versioned portable envelope / export-import wire schemas) is a
**Stage A prerequisite** so fixtures and oracle have a stable wire format.
R1 (two independent measured receipts) gates **public interoperability
claims only** — not descriptive Stage A. Public certification stays behind
R5. Do not invent M16. Do not write GOAL.md, STATE.md, or the lease-map.

## 7. Exact future write lease (unadmitted)

No path below is writable from this document.

```text
docs/plans/wmb-m18-interoperability-implementation-plan.md   (this file only)
```

Prospective Stage A (after freeze + G0/G1/G2 + R2 + R4 frozen envelope;
R1 gates public claims only), not now:

```text
eval/public/wmbs_m18.py                                              (new)
eval/public/fixtures/wmbs-m18-interoperability-development.json      (new)
tests/test_public_wmbs_m18.py                                        (new)
```

Prospective Stage B is not designed here. Do not invent runner/registry rows.

## 8. Claim boundary

| Item | After this file | After a future Stage A | After a future Stage B |
|---|---|---|---|
| M18 single-system round-trip | `PROPOSED` | `PROPOSED` | `PROPOSED` |
| Public interoperability certification | `DEFERRED` | `DEFERRED` | `DEFERRED` until R1+R5 |
| Spec required-field / unknown-critical bounds | `DEFERRED` (R1/R4) | `DEFERRED` | `DEFERRED` until receipt |
| Semantic delta as admission | `DEFERRED` (R3) | `DEFERRED` | `DEFERRED` until calibrated |
| "Interop certified" | never claimed | never claimed | never claimed |
| Recoverable public evidence (spec L1252–1259) | `DEFERRED` until M15+M16+M17+M20 are all admitted | `DEFERRED` | `DEFERRED` |
| Publishable / headline | `false` | `false` | `false` |
| Code lease | none | only if freeze + G1 admit it | G3 |

## 9. Non-goals

- No edit to `GOAL.md`, `.planning/STATE.md`, the lease map, or T8 inventory.
- No edit to M02/M04/M05/M06/M07/M08/M09/M11/M14/M17 plans. M14 stays
  `NOT CODE-READY`. No M16 plan. Do not edit #124.
- No M04-B write. The live #121 eight-file lock (inventory in) stays
  untouched. This file does not write any of those paths.
- No other `eval/public/*` write, including `bundle.py`.
- No freeze. No implement.

## 10. How to tell this step is done

This step is done when this file exists on GitHub as a one-file PR with
`PROPOSED` / `NOT CODE-READY` and a reviewer can re-check §1 against spec
L1053–1075 without trusting this prose. It is **not** done by flipping Status
or writing any other path.

## 11. Locked public-harness cell (do not write README from this PR)

The block below is the only allowed future `eval/public/README.md` cell for
this module. Place it as a peer of the M02, M03, M07, M08, M09, M11, and
M17 cells, not under the M02/M04/M05 Stage-A oracles heading. This PR does
not write `eval/public/README.md`. Frontend has not filed an M18 cell rec
yet; this block is spec-derived only.

Do not add a `uv run --suite` line until a registry row exists.

```markdown
### M18 interoperability

PROPOSED for internal single-system round-trip. Public certification is
DEFERRED until a frozen envelope and a second independently implemented
adapter exist. All publication flags false. A single-system round-trip is
an internal result, not a public interoperability claim.

`export` / `import` with a versioned portable envelope. Transport
conformance uses public adapter schemas. 100% preservation of required
fields. 100% rejection of unknown critical fields. Semantic delta remains
diagnostic until an equivalence margin is calibrated and powered. Three
export orderings and two round trips.

No registry row exists, so this cell is not runnable.
```
