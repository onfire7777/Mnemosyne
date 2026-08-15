# WMB M08 — Reversible Forgetting Implementation Contract

Status: `PROPOSED` / **PLANNING ARTIFACT ONLY — NOT CODE-READY.**
This file authorizes no source, fixture, registry, scorer, measurement,
admission-state, publication change, or GitHub PR.

Author lane: M08 reversible-forgetting planning lane.
Verified base: `origin/main@61f55b94a6f878973437d075adfcecf2cb684ae6`.
Written: 2026-08-15.

## 0. What this document is, and what it is not

This is the exact implementation contract `U-MODULES` requires before any M08
code may be admitted: protocol, scorer contract, fixture design, license/custody,
and dependency placement. It is the GOAL.md step-1 artifact. It is **not**
an approval, an admission, a freeze, or a write lease.

It is **not**:

- an approval (GoalEx lifecycle/integration owner approves, not this lane);
- an admission (the lease map admits; this file does not recompute it);
- evidence that any M08 behaviour was measured, executed, or verified;
- a benchmark, ranking, certification, superiority, publication, leaderboard,
  official-suite, result-v2, sandbox, signed-publication, or T5 claim;
- a rewrite of M02, M04, M05, M06, M07, or M14 plans;
- a contract for M04 Stage B, M06 implement, or M07 implement;
- authority to touch PR #115, #116, #117, #118, or any `eval/public/*` path.

### 0.1 This document's own write-lease status

`docs/plans/` is the GoalEx owner's exclusive surface. Until that owner grants
a write slot for this exact path, this document is an **unadmitted draft
occupying a leased path** (same G0 as the M02 plan §0.1). Nothing here claims
its own placement was authorized.

### 0.2 Why this plan is NOT CODE-READY

All of the following are blocking. None is discharged by writing this file.

1. Spec WMBS-D (`…standard-design.md:1394–1398`): build M06–M13 only after
   WMBS-B **and** after each product capability exists through a public
   contract. C10 is not a public contract on this base.
2. Spec M08 resource prerequisite (`…standard-design.md:814`): a measured
   admission receipt. None exists.
3. Spec M08 acceptance (`…standard-design.md:809–811`): zero exact-canary
   leakage, semantic leakage at most 1%, unrelated utility loss at most 0.5
   percentage points, and 100% restore correctness when restore is claimed.
   No preregistered canary set or restore-claim protocol exists on this base.
4. G0 / G1 / G2: path not lease-clean; lease map not recomputed; M08 is not
   in the first pilot (`…standard-design.md:819`). Freeze is a later step.
   This file does not freeze itself.
5. Systems without a reversible-delete operation are `UNSUPPORTED-BY-SYSTEM`
   (`…standard-design.md:816–817`). They are not scored zero. No public
   reversible-delete hook is admitted on this base.

Missing Stage A artifacts are tree state (inventory L56), not a gate. WMBS-D
is an implement sequencing gate, not a reason to refuse this plan file.

**Verdict: NOT CODE-READY.** Do not implement from this file.

## 1. Module scope (copied from the spec, not rewritten)

Per `docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md`
§8 "M08 — Reversible forgetting" (lines 801–820) and C10 (line 511):

- **Contract:** Section 6 `delete(selector, mode=reversible)` plus
  `retrieve`/`answer`; adapters may expose `restore(delete_receipt)`.
- **Data:** deterministic selective-forget cases followed by exact, paraphrase,
  multi-hop, re-ingestion, unrelated-control, and optional restore probes.
- **Scorer:** direct and semantic leakage, false removal, unrelated utility
  loss, restore correctness, and re-ingestion contamination.
- **Acceptance:** zero exact-canary leakage, semantic leakage at most 1%,
  unrelated utility loss at most 0.5 percentage points, and 100% restore
  correctness when restore is claimed.
- **Repeat/replay:** at least five seeds, two delete/re-ingest cycles, and
  canonical canary digests.
- **Resource prerequisite:** measured admission receipt.
- **External dependencies:** none.
- **Deferral:** systems without a reversible-delete operation are
  `unsupported`; they are not scored zero.
- **Feasibility disposition:** `PROPOSED` for adapters exposing the hook;
  otherwise `UNSUPPORTED-BY-SYSTEM`. M08 is not in the first pilot.
- **Placement:** advanced public capability.

The spec's own exclusion is load-bearing: this contract plans a *successor*
development cell and does not reopen the first reference-harness pilot.

C24 (`…standard-design.md:525`) is a mandatory report dimension, not a second
module and not a score. This plan does not absorb M07/C09 (retention, rehearsal,
decay), M09/C11 (declared-surface erasure), M06/C08 (consolidation), or M02
retrieval. Reversible forgetting must not be treated as declared-surface
erasure, and must not absorb decay.

## 2. Prerequisites (not discharged)

| ID | Gate | Owner | Status on `61f55b94` |
|---|---|---|---|
| G0 | Write slot for this path, or relocate off `docs/plans/` | GoalEx | Open |
| G1 | Lease map recomputed; M08 admitted with an exact lease | GoalEx | Open. This file does not edit the lease map. |
| G2 | Pilot-plan exclusion amended, or this file approved as successor | GoalEx | Open. Do not edit the pilots file in this artifact. |
| G3 | Public-harness integration slot (Stage B only) | Public-harness | Not reached. |
| R1 | Measured admission receipt (spec L814) | Operator | Missing. |
| R2 | C10 capability exists through a public contract (WMBS-D) | Product | Open. |
| R3 | Public reversible-delete hook, or an explicit `UNSUPPORTED-BY-SYSTEM` path | Public-harness | Open. |

Technical reuse that a later Stage A may consume, once the gates above close,
is the closed ABI `wmbs/0.1-draft` and Section 6 `delete(selector,
mode=reversible)` plus `retrieve`/`answer`. Optional `restore(delete_receipt)`
is claimed only when the adapter exposes it.

## 3. Fixture contract (prospective, unadmitted)

When — and only when — a later freeze and write lease exist, Stage A would
add a **new** deterministic development fixture:

- Path (prospective): `eval/public/fixtures/wmbs-m08-reversible-forgetting-development.json`
- Families the spec names: exact, paraphrase, multi-hop, re-ingestion,
  unrelated-control, optional restore probes.
- Seeds: at least five. Two delete/re-ingest cycles. Canonical canary digests.
  Byte-identical under `canonical_json(generate_fixture(seed))`.
- Closed ABI `$defs.portable_event` where the later lease claims conformance.

This paragraph does not create those files.

## 4. Scorer contract (prospective, unadmitted)

When — and only when — a later freeze and write lease exist, Stage A would
add a **new** stdlib-only oracle:

- Path (prospective): `eval/public/wmbs_m08.py`
- Metrics the spec names: direct leakage, semantic leakage, false removal,
  unrelated utility loss, restore correctness, re-ingestion contamination.
- Stage A reports descriptive / finite-corpus-only intervals. It does **not**
  claim the 0 / 1% / 0.5pp / 100% acceptance bounds (that is R1).
- Adapters without the hook emit `unsupported`, never a zero.
- Anti-gaming (spec L1291): no privileged internal undelete signal; canaries
  stay outside the SUT.

This paragraph does not create those files.

## 5. Custody, licence, and claim constraints

- Deterministic local roles: no external dataset, no network, no provider
  (spec L815; U-MODULES license/custody). Pin any later dataset at freeze;
  do not invent one here.
- Publication flags stay `false`. No `PILOT-READY-DEV`. No headline.

## 6. Dependency edges

```text
WMBS-B + C10 public contract (R2) + measured receipt (R1) + G0/G1/G2
  -> freeze this plan (GOAL step 2)
    -> Stage A  new oracle + fixture + tests     [unadmitted]
      -> Stage B  public-harness registration    [unadmitted; G3]
```

Do not touch PR #115 files, #116, #117, or #118. Do not write GOAL.md,
STATE.md, or the lease-map.

## 7. Exact future write lease (unadmitted)

No path below is writable from this document.

```text
docs/plans/wmb-m08-reversible-forgetting-implementation-plan.md   (this file only)
```

Prospective Stage A (after freeze + G0/G1/G2 + R1/R2/R3), not now:

```text
eval/public/wmbs_m08.py                                                 (new)
eval/public/fixtures/wmbs-m08-reversible-forgetting-development.json    (new)
tests/test_public_wmbs_m08.py                                           (new)
```

Prospective Stage B is not designed here. Do not invent runner/registry rows.

## 8. Claim boundary

| Item | After this file | After a future Stage A | After a future Stage B |
|---|---|---|---|
| M08 disposition | `PROPOSED` or `UNSUPPORTED-BY-SYSTEM` | same | same |
| Spec leakage / restore bounds | `DEFERRED` (R1) | `DEFERRED` | `DEFERRED` until receipt |
| Retain, forget, erase (spec L1252–1259) | `DEFERRED` until M07+M08+M09 are all admitted | `DEFERRED` | `DEFERRED` |
| Publishable / headline | `false` | `false` | `false` |
| Code lease | none | only if freeze + G1 admit it | G3 |

## 9. Non-goals

- No edit to `GOAL.md`, `.planning/STATE.md`, the lease map, or T8 inventory.
- No edit to M02/M04/M05/M06/M07/M14 plans.
- No `eval/public/*` write, including PR #115 files
  (`registry.json`, `runner.py`, `scoring.py`, `adapters/whole_memory_reference.py`,
  `README.md`, `tests/test_public_whole_memory_reference.py`,
  `tests/test_public_wmbs_stage_a_disclosure.py`, the wmbs inventory).
- No `bundle.py` write.
- No freeze. No implement.

## 10. How to tell this step is done

This step is done when this file exists on GitHub as a one-file PR with
`PROPOSED` / `NOT CODE-READY` and a reviewer can re-check §1 against spec
L801–820 without trusting this prose. It is **not** done by flipping Status
or writing any other path.
