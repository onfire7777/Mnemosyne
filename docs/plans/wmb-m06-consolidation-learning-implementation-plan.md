# WMB M06 — Consolidation and Learning Implementation Contract

Status: `PROPOSED` / **PLANNING ARTIFACT ONLY — NOT CODE-READY.**
This file authorizes no source, fixture, registry, scorer, measurement,
admission-state, publication change, or GitHub PR.

Author lane: M06 consolidation-and-learning planning lane.
Verified base: `origin/main@61f55b94a6f878973437d075adfcecf2cb684ae6`.
Written: 2026-08-15.

## 0. What this document is, and what it is not

This is the exact implementation contract `U-MODULES` requires before any M06
code may be admitted: protocol, scorer contract, fixture design, license/custody,
and dependency placement. It is the GOAL.md step-1 artifact. It is **not**
an approval, an admission, a freeze, or a write lease.

It is **not**:

- an approval (GoalEx lifecycle/integration owner approves, not this lane);
- an admission (the lease map admits; this file does not recompute it);
- evidence that any M06 behaviour was measured, executed, or verified;
- a benchmark, ranking, certification, superiority, publication, leaderboard,
  official-suite, result-v2, sandbox, signed-publication, or T5 claim.
- a rewrite of M02, M04, M05, or M14 plans.
- a contract for M04 Stage B (that plan's Stage B is NOT code-ready).
- authority to touch PR #115 files or any `eval/public/*` path.

### 0.1 This document's own write-lease status

`docs/plans/` is the GoalEx owner's exclusive surface. Until that owner grants
a write slot for this exact path, this document is an **unadmitted draft
occupying a leased path** (same G0 as the M02 plan §0.1). Nothing here claims
its own placement was authorized.

### 0.2 Why this plan is NOT CODE-READY

All of the following are blocking. None is discharged by writing this file.

1. Spec WMBS-D (`…standard-design.md:1394–1398`): build M06–M13 only after
   WMBS-B **and** after each product capability exists through a public
   contract. That capability (C08 / CAP-007/008) is not a public contract on
   this base. Lease-map `P15-S2` is BLOCKED on `P14-B` / `N12`.
2. Spec M06 resource prerequisite (`…standard-design.md:764–765`): a measured
   admission receipt. None exists.
3. Spec M06 acceptance (`…standard-design.md:757–760`): utility-improvement
   CI lower bound above zero, no-degradation LCB at least zero, zero protected
   regressions, and preregistered calibration for harmful-promotion and
   unrelated-task thresholds. No preregistration exists. Stage A cannot claim
   those bounds.
4. G0 / G1 / G2: path not lease-clean; lease map not recomputed; pilot plan
   excludes M06 (`…standard-design.md:771–773`). Freeze is a later step. This
   file does not freeze itself.

Missing Stage A artifacts are tree state (inventory L54), not a gate. WMBS-D
is an implement sequencing gate, not a reason to refuse this plan file.

**Verdict: NOT CODE-READY.** Do not implement from this file.

## 1. Module scope (copied from the spec, not rewritten)

Per `docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md`
§8 "M06 — Consolidation and learning" (lines 748–774) and C08 (line 509):

- **Contract:** universal `ingest`, `retrieve`, and `answer` across episodes;
  no private consolidation API is required.
- **Data:** deterministic repeated, corroborated, contradictory, procedural,
  related-transfer, and unrelated-control episodes.
- **Scorer:** utility delta against no-consolidation/no-memory controls,
  harmful promotion, compounding-error rate, cross-episode transfer, storage,
  and cost.
- **Acceptance:** utility-improvement confidence-interval lower bound above
  zero and canonical no-degradation lower confidence bound at least zero, with
  zero protected regressions. Harmful-promotion and unrelated-task thresholds
  require preregistered calibration.
- **Repeat/replay:** five cycles per case and at least five seeds, with a real
  public no-consolidation control when supported; otherwise use the universal
  no-memory control and disclose the missing ablation.
- **Resource prerequisite:** measured admission receipt; provider-backed
  variants also inherit the declared provider budget.
- **External dependencies:** none for deterministic local roles; official
  MemoryAgentBench/EvoMemBench adapters require pinned upstream data/models.
- **Deferral:** official variants defer when upstream data/scoring cannot be
  reproduced; a no-consolidation comparison defers when it cannot be exercised
  through a public control.
- **Feasibility disposition:** `PROPOSED`; official
  MemoryAgentBench/EvoMemBench variants are `DEFERRED` until pinned. M06 is not
  in the first pilot.
- **Placement:** advanced public outcome plus release non-degradation gate.

The spec's own exclusion is load-bearing: this contract plans a *successor*
development cell and does not reopen the first reference-harness pilot.

C24 (`…standard-design.md:525`) is a mandatory report dimension (storage/cost
already in the M06 scorer), not a second module and not a score. This plan
does not absorb M07/C09 (retention, rehearsal, decay — spec D7 L71, C09 L510),
M14/C23 (procedural task utility), or M02 retrieval/organization.
Consolidation must not absorb decay.

## 2. Prerequisites (not discharged)

| ID | Gate | Owner | Status on `61f55b94` |
|---|---|---|---|
| G0 | Write slot for this path, or relocate off `docs/plans/` | GoalEx | Open |
| G1 | Lease map recomputed; M06 admitted with an exact lease | GoalEx | Open. This file does not edit the lease map. |
| G2 | Pilot-plan exclusion amended, or this file approved as successor | GoalEx | Open. Do not edit the pilots file in this artifact. |
| G3 | Public-harness integration slot (Stage B only) | Public-harness | Not reached. |
| R1 | Measured admission receipt (spec L764) | Operator | Missing. |
| R2 | C08 capability exists through a public contract (WMBS-D) | Product / P15-S2 | Blocked on P14-B / N12. |
| R3 | Preregistered harmful-promotion and unrelated-task thresholds | Operator | Missing. |

Technical reuse that a later Stage A may consume, once the gates above close,
is the closed ABI `wmbs/0.1-draft` and universal `ingest` / `retrieve` /
`answer`. No private consolidation hook is in scope.

## 3. Fixture contract (prospective, unadmitted)

When — and only when — a later freeze and write lease exist, Stage A would
add a **new** deterministic development fixture:

- Path (prospective): `eval/public/fixtures/wmbs-m06-consolidation-development.json`
- Families the spec names: repeated, corroborated, contradictory, procedural,
  related-transfer, unrelated-control.
- Cycles: five per case. Seeds: at least five. Byte-identical under
  `canonical_json(generate_fixture(seed))`.
- Closed ABI `$defs.portable_event` where the later lease claims conformance.
- No official MemoryAgentBench/EvoMemBench bytes in this cell.

This paragraph does not create those files.

## 4. Scorer contract (prospective, unadmitted)

When — and only when — a later freeze and write lease exist, Stage A would
add a **new** stdlib-only oracle:

- Path (prospective): `eval/public/wmbs_m06.py`
- Metrics the spec names: utility delta vs no-consolidation/no-memory,
  harmful promotion, compounding-error rate, cross-episode transfer, storage,
  cost.
- Stage A reports descriptive / finite-corpus-only intervals. It does **not**
  claim the spec's CI-LCB acceptance (that is R1+R3).
- Latency/tokens/calls stay `unsupported` unless a later lease says otherwise.
- No baseline-improvement or non-inferiority field until preregistration.
- Anti-gaming (spec L1291): no private no-consolidation control and no
  privileged internal signal.

This paragraph does not create those files.

## 5. Custody, licence, and claim constraints

- Deterministic local roles: no external dataset, no network, no provider
  (spec L766; U-MODULES license/custody). Pin any later dataset at freeze;
  do not invent one here.
- Official MemoryAgentBench/EvoMemBench: `DEFERRED` until pinned upstream
  data/models/scoring can be reproduced.
- Publication flags stay `false`. No `PILOT-READY-DEV`. No headline.
- M14 shares C08. This plan does not implement or freeze M14.

## 6. Dependency edges

```text
WMBS-B + C08 public contract (R2) + measured receipt (R1) + G0/G1/G2
  -> freeze this plan (GOAL step 2)
    -> Stage A  new oracle + fixture + tests     [unadmitted]
      -> Stage B  public-harness registration    [unadmitted; G3]
```

P15-S2 (CAP-007/008) stays behind P14-B / N12. This file does not open it.
M02 Stage B / PR #115 is a different lease. Do not touch those files.

## 7. Exact future write lease (unadmitted)

No path below is writable from this document.

```text
docs/plans/wmb-m06-consolidation-learning-implementation-plan.md   (this file only)
```

Prospective Stage A (after freeze + G0/G1/G2 + R1/R2/R3), not now:

```text
eval/public/wmbs_m06.py                                         (new)
eval/public/fixtures/wmbs-m06-consolidation-development.json    (new)
tests/test_public_wmbs_m06.py                                   (new)
```

Prospective Stage B is not designed here. Do not invent runner/registry rows.

## 8. Claim boundary

| Item | After this file | After a future Stage A | After a future Stage B |
|---|---|---|---|
| M06 disposition | `PROPOSED` | `PROPOSED` | `PROPOSED` |
| Official MAB/EvoMemBench | `DEFERRED` | `DEFERRED` | `DEFERRED` |
| Spec CI-LCB acceptance | `DEFERRED` (R1/R3) | `DEFERRED` | `DEFERRED` until receipt |
| Publishable / headline | `false` | `false` | `false` |
| Learn without leaking (spec L1253–1259) | `DEFERRED` until M06+M11+M14 are all admitted | `DEFERRED` | `DEFERRED` |
| Code lease | none | only if freeze + G1 admit it | G3 |

## 9. Non-goals

- No edit to `GOAL.md`, `.planning/STATE.md`, the lease map, or T8 inventory.
- No edit to M02/M04/M05/M14 plans.
- No M04 Stage B contract.
- No `eval/public/*` write, including PR #115 files
  (`registry.json`, `runner.py`, `scoring.py`, `adapters/whole_memory_reference.py`,
  `README.md`, `tests/test_public_whole_memory_reference.py`).
- No `bundle.py` write.
- No freeze. No implement. No PR from this artifact.

## 10. How to tell this step is done

This step is done when this file exists as a `PROPOSED` / `NOT CODE-READY`
planning artifact and a reviewer can re-check §1 against spec L748–774
without trusting this prose. It is **not** done by opening a PR, flipping
Status, or writing any other path.
