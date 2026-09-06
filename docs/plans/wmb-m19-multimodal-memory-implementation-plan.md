# WMB M19 — Multimodal Memory Implementation Contract

Status: `PROPOSED` / **PLANNING ARTIFACT ONLY — NOT CODE-READY.**
This file authorizes no source, fixture, registry, scorer, measurement,
admission-state, publication change, or GitHub PR beyond this one-file plan.

Author lane: M19 multimodal-memory planning lane.
Verified base: `origin/main@f688c74757365a9d946100687a04288cde12a7fc`.
Written: 2026-08-15.

## 0. What this document is, and what it is not

This is the exact implementation contract `U-MODULES` requires before any M19
code may be admitted: protocol, scorer contract, fixture design, license/custody,
and dependency placement. It is the GOAL.md step-1 artifact. It is **not**
an approval, an admission, a freeze, or a write lease.

It is **not**:

- an approval (GoalEx lifecycle/integration owner approves, not this lane);
- an admission (the lease map admits; this file does not recompute it);
- evidence that any M19 behaviour was measured, executed, or verified;
- a benchmark, ranking, certification, superiority, publication, leaderboard,
  official-suite, result-v2, sandbox, signed-publication, or T5 claim;
- a multimodal-certification, "media certified" label, or a
  certified/governed claim;
- a rewrite of M02, M04, M05, M06, M07, M08, M09, M11, M14, M17, or M18
  plans (M14 stays `NOT CODE-READY`; #124 and #125 are not edited);
- an M16 plan or an M16 implement (M16 is skipped);
- a contract for M04 Stage B or any other module's implementation;
- authority to touch PR #116, #117, #118, #119, #120, #121, #122, #123,
  #124, #125, or any `eval/public/*` path.

### 0.1 This document's own write-lease status

`docs/plans/` is the GoalEx owner's exclusive surface. Until that owner grants
a write slot for this exact path, this document is an **unadmitted draft
occupying a leased path** (same G0 as the M02 plan §0.1). Nothing here claims
its own placement was authorized.

### 0.2 Why this plan is NOT CODE-READY

All of the following are blocking. None is discharged by writing this file.

1. Spec WMBS-E (`…standard-design.md:1400–1403`): build M16–M19 plus H8/P32
   profiles only after the behavior being claimed and the relevant
   hardware/custody gates are admitted. C21 is a future requirement and is
   currently deferred (`…standard-design.md:522`).
2. Spec M19 feasibility (`…standard-design.md:1098–1101`): `DEFERRED` because
   no complete redistributable fixture-rights manifest and portable media
   contract have been admitted. Text-only systems are
   `UNSUPPORTED-BY-SYSTEM`. M19 is not in the first pilot.
3. Spec M19 resource prerequisite (`…standard-design.md:1092–1093`): a
   measured receipt for an admitted profile. None exists. No local
   generative model is assumed.
4. Spec M19 acceptance (`…standard-design.md:1086–1089`): public comparison
   has no quality-based admission floor; improvement claims require a
   positive paired confidence-interval lower bound; provenance and erasure
   claims inherit M05/M09 gates unchanged. No preregistered paired-CI
   protocol exists on this base. Stage A cannot claim those bounds.
5. Spec M19 deferral (`…standard-design.md:1096–1098`): official multimodal
   variants defer when media licensing, download stability, or model cost is
   not fixed. Text-only systems are `unsupported`, not failed.
6. G0 / G1 / G2: path not lease-clean; lease map not recomputed; M19 is not
   in the first pilot. Freeze is a later step. This file does not freeze
   itself.
7. Official EMemBench or provider-backed media extraction is eligible only
   after pinned data/model and rights contracts (`…standard-design.md:1094–1095`).
   None are pinned. Raw host paths and entrant-controlled fetch URLs are
   forbidden (`…standard-design.md:1078–1079`).

Missing Stage A artifacts are tree state, not a gate. WMBS-E and the
`DEFERRED` disposition are implement sequencing gates, not a reason to
refuse this plan file.

**Verdict: NOT CODE-READY.** Do not implement from this file.

## 1. Module scope (copied from the spec, not rewritten)

Per `docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md`
§8 "M19 — Multimodal memory" (lines 1076–1102) and C21 (line 522):

- **Contract:** universal `ingest`, `retrieve`, and `answer` with an opaque,
  digest-bound `modality_handle`; raw host paths and entrant-controlled fetch
  URLs are forbidden. Evidence and deletion hooks are optional extensions.
- **Data:** small redistributable text/image/audio/video fixtures with
  cross-modal questions, provenance, distractors, and deletion canaries.
- **Scorer:** answer/evidence quality, cross-modal linkage, provenance,
  modality-specific leakage, latency, and storage.
- **Acceptance:** public comparison has no quality-based admission floor;
  improvement claims require a positive paired confidence-interval lower bound,
  while provenance and erasure claims inherit M05/M09 gates unchanged.
- **Repeat/replay:** at least five seeds; media files and derived
  representations are digest-pinned.
- **Resource prerequisite:** measured receipt for an admitted profile; no local
  generative model is assumed.
- **External dependencies:** official EMemBench or provider-backed media
  extraction is eligible only after pinned data/model and rights contracts.
- **Deferral:** official multimodal variants defer when media licensing,
  download stability, or model cost is not fixed. Text-only systems are
  `unsupported`, not failed.
- **Feasibility disposition:** `DEFERRED` because no complete redistributable
  fixture-rights manifest and portable media contract have been admitted.
  Text-only systems are `UNSUPPORTED-BY-SYSTEM`. M19 is not in the first
  pilot.
- **Placement:** advanced public capability.

The spec's own exclusion is load-bearing: this contract plans a *successor*
development cell and does not reopen the first reference-harness pilot.

C21 is an advanced outcome and a future requirement, currently deferred.
C24 (`…standard-design.md:525`) is a mandatory report dimension, not a
second module. This plan does not absorb M05/C06, M09/C11, M16/C18 (M16 is
skipped), M17/C19, M18/C20, M14/C23, or M02 retrieval. Provenance and
erasure claims inherit M05/M09 gates; they are not re-specified here.

The spec's `DEFERRED` disposition is a **sequencing fact**, not a claim this
file may flip. This plan never labels a run "media certified."

## 2. Prerequisites (not discharged)

| ID | Gate | Owner | Status on `f688c747` |
|---|---|---|---|
| G0 | Write slot for this path, or relocate off `docs/plans/` | GoalEx | Open |
| G1 | Lease map recomputed; M19 admitted with an exact lease | GoalEx | Open. This file does not edit the lease map. |
| G2 | Pilot-plan exclusion amended, or this file approved as successor | GoalEx | Open. Do not edit the pilots file in this artifact. |
| G3 | Public-harness integration slot (Stage B only) | Public-harness | Not reached. |
| R1 | Measured receipt for an admitted profile (spec L1092–1093) | Operator | Missing — measured-claim gate, not Stage A source. |
| R2 | C21 admitted as more than a deferred future requirement (WMBS-E) | Product | Open. Currently deferred. |
| R3 | Complete redistributable fixture-rights manifest and portable media contract (spec L1098–1100) | Standard owner | Missing. This is why the module is `DEFERRED`. |
| R4 | Media licensing, download stability, and model cost fixed before any official multimodal variant (spec L1096–1097) | Operator | Open. |
| R5 | Pinned data/model and rights contracts before EMemBench or provider-backed extraction (spec L1094–1095) | Operator | Open. |

Technical reuse that a later Stage A may consume, once the gates above close,
is the closed ABI `wmbs/0.1-draft` and universal `ingest` / `retrieve` /
`answer` with an opaque, digest-bound `modality_handle`. Raw host paths and
entrant-controlled fetch URLs stay forbidden. Evidence and deletion hooks
are optional extensions. Replay uses at least five seeds; media files and
derived representations are digest-pinned.

## 3. Fixture contract (prospective, unadmitted)

When — and only when — a later freeze and write lease exist, Stage A would
add a **new** deterministic development fixture:

- Path (prospective): `eval/public/fixtures/wmbs-m19-multimodal-development.json`
- Families the spec names: small redistributable text/image/audio/video
  fixtures, cross-modal questions, provenance, distractors, deletion
  canaries.
- Replay: at least five seeds. Media files and derived representations
  digest-pinned. Byte-identical under `canonical_json(generate_fixture(seed))`.
- Media events require non-null `modality_handle` values that resolve, via a
  harness-owned mechanism, to digest-pinned fixture bytes (not captions or
  metadata alone). Absent/null handles are not Stage A conforming for
  image/audio/video cases.
- Closed ABI `$defs.portable_event` where the later lease claims conformance.
- No raw host paths. No entrant-controlled fetch URLs. Text-only systems
  stay `unsupported`, not failed. Official multimodal variants stay
  `DEFERRED` until R3+R4.

This paragraph does not create those files.

## 4. Scorer contract (prospective, unadmitted)

When — and only when — a later freeze and write lease exist, Stage A would
add a **new** stdlib-only oracle:

- Path (prospective): `eval/public/wmbs_m19.py`
- Metrics the spec names: answer/evidence quality, cross-modal linkage,
  provenance, modality-specific leakage, latency, storage.
- Stage A reports descriptive / finite-corpus-only intervals. It does **not**
  invent a quality-based admission floor. Improvement claims stay unclaimed
  until a positive paired confidence-interval lower bound exists.
- Provenance remains an M19 Stage A scored metric (spec L1083–1087). M05/M09
  contracts may be reused for shared fields, but provenance is not dropped
  from the M19 scorer.
- Freeze residual (NOT CODE-READY): trace/input shape, matching rules,
  denominators, per-modality aggregation, leakage calculation, validation
  failures, and latency/storage measurement posture must be frozen before
  Stage A implement — metric names alone are not a scorer contract.
- Text-only systems emit `unsupported`, never a fail. Missing R3 yields
  **no multimodal claim**, not a pass.
- Anti-gaming (spec L1267 + L1291): gold and graders stay outside the SUT; no
  privileged internal media decode; no host-path or entrant-controlled
  fetch-URL shortcut (M19-specific).

This paragraph does not create those files.

## 5. Custody, licence, and claim constraints

- Deterministic local roles: no external dataset, no network, no provider
  until R5 (spec L1094–1095; U-MODULES license/custody). Pin any later
  dataset and rights contract at freeze; do not invent one here.
- Publication flags stay `false`. No `PILOT-READY-DEV`. No headline.
- No "media certified," certified, or governed label. The module
  disposition stays `DEFERRED` until R3. Text-only remains
  `UNSUPPORTED-BY-SYSTEM`.

## 6. Dependency edges

```text
WMBS-E + C21 no longer deferred (R2) + fixture-rights + portable media (R3)
+ G0/G1/G2
  -> freeze this plan (GOAL step 2)
    -> Stage A  descriptive oracle + fixture + tests   [unadmitted; R1 not required]
      -> measured / admitted claims require R1 receipt
      -> Stage B  public-harness registration          [unadmitted; G3]
```

R1 gates measured/admitted claims, not descriptive Stage A. Official
multimodal variants stay behind R4/R5. Inventory reconcile after merge is a
separate GoalEx Exact-1 — not this PR. Do not invent M16. Do not write
GOAL.md, STATE.md, or the lease-map.

## 7. Exact future write lease (unadmitted)

No path below is writable from this document.

```text
docs/plans/wmb-m19-multimodal-memory-implementation-plan.md   (this file only)
```

Prospective Stage A (after freeze + G0/G1/G2 + R2/R3; R1 gates measured
claims only), not now:

```text
eval/public/wmbs_m19.py                                          (new)
eval/public/fixtures/wmbs-m19-multimodal-development.json        (new)
tests/test_public_wmbs_m19.py                                    (new)
```

Prospective Stage B is not designed here. Do not invent runner/registry rows.

## 8. Claim boundary

| Item | After this file | After a future Stage A | After a future Stage B |
|---|---|---|---|
| M19 module disposition | `DEFERRED` | `DEFERRED` until R3 | `DEFERRED` until R3 |
| Text-only systems | `UNSUPPORTED-BY-SYSTEM` | same | same |
| Official multimodal variant | `DEFERRED` (R4/R5) | `DEFERRED` | `DEFERRED` until R4/R5 |
| Quality-based admission floor | none | none | none |
| Improvement claim (paired CI) | `DEFERRED` | `DEFERRED` | `DEFERRED` until powered |
| Provenance / erasure | inherit M05/M09; not re-specified | same | same |
| "Media certified" | never claimed | never claimed | never claimed |
| Publishable / headline | `false` | `false` | `false` |
| Code lease | none | only if freeze + G1 admit it | G3 |

## 9. Non-goals

- No edit to `GOAL.md`, `.planning/STATE.md`, the lease map, or T8 inventory.
- No edit to M02/M04/M05/M06/M07/M08/M09/M11/M14/M17/M18 plans. M14 stays
  `NOT CODE-READY`. No M16 plan. Do not edit #124 or #125.
- No M04-B write. The live #121 eight-file lock (inventory in) stays
  untouched. This file does not write any of those paths.
- No other `eval/public/*` write, including `bundle.py`.
- No freeze. No implement.

## 10. How to tell this step is done

This step is done when this file exists on GitHub as a one-file PR with
`PROPOSED` / `NOT CODE-READY` and a reviewer can re-check §1 against spec
L1076–1102 without trusting this prose. It is **not** done by flipping Status
or writing any other path.

## 11. Locked public-harness cell (do not write README from this PR)

The block below is the only allowed future `eval/public/README.md` cell for
this module. Place it as a peer of the M02, M03, M07, M08, M09, M11, M17,
and M18 cells, not under the M02/M04/M05 Stage-A oracles heading. This PR
does not write `eval/public/README.md`. Frontend has not filed an M19 cell
rec yet; this block is spec-derived only.

Do not add a `uv run --suite` line until a registry row exists.

```markdown
### M19 multimodal memory

DEFERRED: no complete redistributable fixture-rights manifest and portable
media contract have been admitted. Text-only systems are
UNSUPPORTED-BY-SYSTEM, not failed. All publication flags false. Public
comparison has no quality-based admission floor.

`ingest` / `retrieve` / `answer` with an opaque, digest-bound
`modality_handle`. Raw host paths and entrant-controlled fetch URLs are
forbidden. Evidence and deletion hooks are optional. At least five seeds.
Media files and derived representations digest-pinned. Provenance and
erasure inherit M05/M09. Official multimodal variants defer until media
licensing, download stability, and model cost are fixed.

No registry row exists, so this cell is not runnable.
```
