# WMB M20 — Publication Integrity Implementation Contract

Status: `PROPOSED` / **PLANNING ARTIFACT ONLY — NOT CODE-READY.**
This file authorizes no source, fixture, registry, scorer, measurement,
admission-state, publication change, or GitHub PR beyond this one-file plan.

Author lane: M20 publication-integrity planning lane.
Verified base: `origin/main@f688c74757365a9d946100687a04288cde12a7fc`.
Written: 2026-08-15.

## 0. What this document is, and what it is not

This is the **result-v2 / N12 delta** planning artifact for M20 publication
integrity. The owner-landed pilot plan remains M20's approved exact plan; this
file does **not** replace it as greenfield GOAL step-1. It is **not** an
approval, an admission, a freeze, or a write lease.

It is **not**:

- an approval (GoalEx lifecycle/integration owner approves, not this lane);
- an admission (the lease map admits; this file does not recompute it);
- evidence that any M20 behaviour was measured, executed, or verified;
- a benchmark, ranking, certification, superiority, publication, leaderboard,
  official-suite, result-v2 admission, sandbox, signed-publication, or T5
  claim;
- a "publication certified" label or a certified/governed claim;
- a rewrite of M02, M04, M05, M06, M07, M08, M09, M11, M14, M17, M18, or
  M19 plans (M14 stays `NOT CODE-READY`; #124, #125, and #126 are not
  edited);
- an M16 plan or an M16 implement (M16 stays `PROPOSED`; no invent M16);
- a second ledger, a v1-byte reinterpretation, or a history rewrite;
- a contract for M04 Stage B or any other module's implementation;
- authority to touch PR #116, #117, #118, #119, #120, #121, #122, #123,
  #124, #125, #126, or any `eval/public/*` path.

### 0.1 This document's own write-lease status

`docs/plans/` is the GoalEx owner's exclusive surface. Until that owner grants
a write slot for this exact path, this document is an **unadmitted draft
occupying a leased path** (same G0 as the M02 plan §0.1). Nothing here claims
its own placement was authorized.

### 0.2 Why this plan is NOT CODE-READY

All of the following are blocking. None is discharged by writing this file.

1. Spec WMBS-F (`…standard-design.md:1406–1410`): official adapters and
   held-out rounds run only after affected module readiness, PBPP/Register-A
   evidence, and human approval. C22 / GOV-001 / LEAD-001/002/003 is not an
   admitted public-release contract on this base.
2. Spec M20 resource prerequisite (`…standard-design.md:1121–1123`): a
   measured admission receipt. None exists. The 15-minute / 2 GiB RSS /
   1 GiB disk figure is an L16-DEV planning hypothesis, not an asserted
   budget.
3. Spec M20 acceptance (`…standard-design.md:1116–1118`): 100% acceptance of
   valid bundles, 100% rejection of invalid bundles, exact digest replay,
   and no mutation of prior published history. No preregistered bundle set
   or receipt protocol exists on this base. Stage A cannot claim those
   bounds.
4. Spec M20 deferral (`…standard-design.md:1126–1130`): v2 admission requires
   verification of build, config, bundle, and trace-index digests before
   rendering. Mixed v1/v2 rendering remains blocked until schema dispatch
   and cross-version supersession tests pass. Public release also defers
   without human approval and PBPP-complete custody.
5. G0 / G1 / G2: path not lease-clean; lease map not recomputed. Freeze is a
   later step. This file does not freeze itself.
6. Existing v1 substrate has `evidence_level=IMPLEMENTED` but that does
   **not** imply v2 admission (`…standard-design.md:1131–1135`). Historical
   v1 ledger entries remain immutable. This plan does not rewrite them.

Missing Stage A artifacts are tree state, not a gate. WMBS-F is an implement
sequencing gate, not a reason to refuse this plan file.

**Verdict: NOT CODE-READY.** Do not implement from this file.

## 1. Module scope (copied from the spec, not rewritten)

Per `docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md`
§8 "M20 — Publication integrity" (lines 1103–1132) and C22 (line 523):

- **Contract:** reuse `leaderboard/schema/result-v1.schema.json`,
  `leaderboard.validate`, `leaderboard.ledger`, `leaderboard.render`,
  `leaderboard.publish`, and `leaderboard.readiness` without reinterpreting
  signed v1 bytes. A new `result-v2` may add module/disclosure, safety-gate,
  resource, attempt, custody, and complete digest bindings through explicit
  version dispatch.
- **Data:** deterministic valid, tampered, duplicated, truncated, revoked,
  superseded, cyclic, and mismatched-fingerprint bundles.
- **Scorer:** valid acceptance, invalid rejection, exact digest replay,
  non-destructive history, and verifier exit status.
- **Acceptance:** 100% acceptance of valid bundles, 100% rejection of invalid
  bundles, exact digest replay, and no mutation of prior published history.
- **Repeat/replay:** five input orderings, two clean renders, and one
  interrupted publication.
- **Resource prerequisite:** measured admission receipt; 15 minutes, 2 GiB
  RSS, and 1 GiB disk is an L16-DEV planning hypothesis.
- **External dependencies:** local signing keys only; public hosting and human
  approval are separate publication acts.
- **Deferral:** v2 admission requires verification of build, config, bundle,
  and trace-index digests before rendering. Mixed v1/v2 rendering remains
  blocked until schema dispatch and cross-version supersession tests pass.
  Public release also defers without human approval and PBPP-complete custody.
- **Feasibility disposition:** v2 `admission_state` is `PROPOSED`; the existing
  v1 substrate has `evidence_level=IMPLEMENTED` but no implied v2 admission.
  Historical v1 ledger entries remain immutable; migration appends a linked v2
  supersession rather than rewriting history.
- **Placement:** mandatory standard infrastructure.

The spec's own exclusion is load-bearing: this contract plans a *successor*
development/v2-delta cell under the already-admitted M20 pilot scope.

C22 is standard infrastructure (GOV-001; LEAD-001/002/003), not a score.
C24 (`…standard-design.md:525`) is a mandatory report dimension, not a
second module. This plan does not absorb M15/C17, M16/C18 (M16 is skipped),
M17/C19, M18/C20, M19/C21, M14/C23, or M02 retrieval. Reuse of the v1
substrate is not v2 admission.

The spec's "no implied v2 admission" sentence is a **claim boundary**, not a
license to flip it. This plan never labels a run "publication certified."

## 2. Prerequisites (not discharged)

| ID | Gate | Owner | Status on `f688c747` |
|---|---|---|---|
| G0 | Write slot for this path, or relocate off `docs/plans/` | GoalEx | Open |
| G1 | Lease map recomputed; M20 admitted with an exact lease | GoalEx | Open. This file does not edit the lease map. |
| G2 | Align with owner-landed pilot plan (M20 is in the first reference-harness pilot) | GoalEx | Open. This file is a v2/N12 delta, not a pilot-exclusion successor. Do not edit the pilots file here. |
| G3 | Public-harness integration slot (Stage B only) | Public-harness | Not reached. |
| R1 | Measured admission receipt (spec L1121). L16-DEV numbers are a hypothesis, not a budget | Operator | Missing — measured-claim gate, not Stage A source. |
| R2 | C22 public-release contract: human approval and PBPP-complete custody (WMBS-F; spec L1129–1130) | Product / publication owner | Open — public-release gate only; not Stage A source. |
| R3 | Schema dispatch and cross-version supersession tests before any mixed v1/v2 render (spec L1126–1129) | Public-harness | **DISCHARGED** by N12/#139 (`leaderboard/validate.py` result-v2 dispatch). Residual: keep mixed-render fail-closed. |
| R4 | Verification of build, config, bundle, and trace-index digests before v2 rendering (spec L1126–1127) | Operator | **DISCHARGED** by N12/#139 (`leaderboard/render.py` four-artifact verify). Do not re-implement. |
| R5 | Explicit version dispatch for any `result-v2` field add (spec L1108–1111) | Standard owner | **DISCHARGED** by N12/#139 for current result-v2 surface. Do not reinterpret signed v1 bytes. |

Technical reuse that a later Stage A may consume, once the gates above close,
is the existing v1 substrate (`leaderboard/schema/result-v1.schema.json`,
`leaderboard.validate`, `leaderboard.ledger`, `leaderboard.render`,
`leaderboard.publish`, `leaderboard.readiness`) without reinterpreting signed
v1 bytes. Replay uses five input orderings, two clean renders, and one
interrupted publication. Migration, if ever admitted, appends a linked v2
supersession; it does not rewrite history.

## 3. Fixture contract (prospective, unadmitted)

When — and only when — a later freeze and write lease exist, Stage A would
add a **new** deterministic development fixture:

- Path (prospective): `eval/public/fixtures/wmbs-m20-publication-integrity-development.json`
- Families the spec names: valid, tampered, duplicated, truncated, revoked,
  superseded, cyclic, mismatched-fingerprint bundles.
- Replay: five input orderings, two clean renders, one interrupted
  publication. Byte-identical under `canonical_json(generate_fixture(seed))`.
- Closed ABI `$defs.portable_event` where the later lease claims conformance.
- Local signing keys only. Public hosting stays a separate act. Mixed
  v1/v2 rendering stays blocked until R3.

This paragraph does not create those files.

## 4. Scorer contract (prospective, unadmitted)

When — and only when — a later freeze and write lease exist, Stage A would
add a **new** stdlib-only oracle:

- Path (prospective): `eval/public/wmbs_m20.py`
- Metrics the spec names: valid acceptance, invalid rejection, exact digest
  replay, non-destructive history, verifier exit status.
- Stage A reports descriptive / finite-corpus-only intervals. It does **not**
  claim 100% valid acceptance, 100% invalid rejection, exact digest replay,
  or non-mutation of published history as an admission bound (that is R1).
- v1 `IMPLEMENTED` is not v2 admission. Missing R2/R3/R4 yields **no public
  release and no v2 admission**, not a pass.
- Anti-gaming (spec L1291): no privileged internal ledger rewrite; gold,
  graders, and expected fingerprints stay outside the SUT. Do not
  reinterpret signed v1 bytes.

This paragraph does not create those files.

## 5. Custody, licence, and claim constraints

- Deterministic local roles: local signing keys only (spec L1124–1125;
  U-MODULES license/custody). Public hosting and human approval are
  separate publication acts. Pin any later dataset at freeze; do not invent
  one here.
- Publication flags stay `false`. No `PILOT-READY-DEV`. No headline.
- No "publication certified," certified, or governed label. v2
  `admission_state` stays `PROPOSED`. Historical v1 entries stay immutable.

## 6. Dependency edges

```text
G0/G1 (R3/R4/R5 schema+digest+v2 dispatch already on tip via N12/#139)
  -> freeze this v2/N12 delta plan against landed leaderboard surfaces
    -> Stage A  descriptive oracle + fixture + tests   [unadmitted; R1/R2 not required]
      -> measured / admitted claims may use R1
      -> public release / hosting requires R2 (WMBS-F human approval + PBPP)
      -> Stage B  public-harness registration          [unadmitted; G3]
```

Do **not** treat R3/R4/R5 as open reinvent gates — consume merged N12
`leaderboard/validate.py` / `render.py`. WMBS-F / R2 still gates public
release. R1 is not a Stage A source blocker. Inventory reconcile is a
separate GoalEx Exact-1. Do not invent M16.

## 7. Exact future write lease (unadmitted)

No path below is writable from this document.

```text
docs/plans/wmb-m20-publication-integrity-implementation-plan.md   (this file only)
```

Prospective Stage A (after freeze + G0/G1; consume landed N12 R3/R4/R5;
R1/R2 are not Stage A source blockers — R2 is public-release), not now:

```text
eval/public/wmbs_m20.py                                                    (new)
eval/public/fixtures/wmbs-m20-publication-integrity-development.json       (new)
tests/test_public_wmbs_m20.py                                              (new)
```

Prospective Stage B is not designed here. Do not invent runner/registry rows.
Do not add a second ledger. Do not rewrite v1 history.

## 8. Claim boundary

| Item | After this file | After a future Stage A | After a future Stage B |
|---|---|---|---|
| v2 `admission_state` | `PROPOSED` | `PROPOSED` | `PROPOSED` |
| v1 substrate | `IMPLEMENTED`; no implied v2 | same | same |
| Mixed v1/v2 render | blocked (fail-closed residual) | blocked | blocked (fail-closed residual; R3 discharge ≠ enable mixed render) |
| Public release | `DEFERRED` (R2) | `DEFERRED` | `DEFERRED` until human approval + PBPP |
| Spec accept/reject / digest / history bounds | `DEFERRED` (R1) | `DEFERRED` | `DEFERRED` until receipt |
| "Publication certified" | never claimed | never claimed | never claimed |
| Recoverable public evidence (spec L1252–1259) | `DEFERRED` until M15+M16+M17+M20 are all admitted | `DEFERRED` | `DEFERRED` |
| Publishable / headline | `false` | `false` | `false` |
| Code lease | none | only if freeze + G1 admit it | G3 |

## 9. Non-goals

- No edit to `GOAL.md`, `.planning/STATE.md`, the lease map, or T8 inventory.
- No edit to M02/M04/M05/M06/M07/M08/M09/M11/M14/M17/M18/M19 plans. M14
  stays `NOT CODE-READY`. No M16 plan. Do not edit #124, #125, or #126.
- No M04-B write. The live #121 eight-file lock (inventory in) stays
  untouched. This file does not write any of those paths.
- No other `eval/public/*` write, including `bundle.py`.
- No second ledger. No v1-byte reinterpretation. No history rewrite.
- No freeze. No implement.

## 10. How to tell this step is done

This step is done when this file exists on GitHub as a one-file PR with
`PROPOSED` / `NOT CODE-READY` and a reviewer can re-check §1 against spec
L1103–1132 without trusting this prose. It is **not** done by flipping Status
or writing any other path.

## 11. Locked public-harness cell (do not write README from this PR)

The block below is the only allowed future `eval/public/README.md` cell for
this module. Place it as a peer of the M02, M03, M07, M08, M09, M11, M17,
M18, and M19 cells, not under the M02/M04/M05 Stage-A oracles heading. This
PR does not write `eval/public/README.md`. Frontend has not filed an M20
cell rec yet; this block is spec-derived only.

Do not add a `uv run --suite` line until a registry row exists.

```markdown
### M20 publication integrity

v2 admission_state is PROPOSED. Existing v1 substrate is IMPLEMENTED and
does not imply v2 admission. All publication flags false. Public release
defers without human approval and PBPP-complete custody. Mixed v1/v2
rendering stays blocked.

Reuse `leaderboard.validate` / `ledger` / `render` / `publish` /
`readiness` without reinterpreting signed v1 bytes. **Deferred acceptance
targets** (not achieved Stage-A/B results; bind only after R1 receipt): 100%
acceptance of valid bundles; 100% rejection of invalid bundles; exact digest
replay; no mutation of prior published history. Five input orderings, two
clean renders, one interrupted publication. Historical v1 entries stay
immutable; a later v2 migration appends a linked supersession.

No registry row exists, so this cell is not runnable.
```
