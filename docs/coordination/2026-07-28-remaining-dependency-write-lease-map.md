# Remaining Dependency and Write-Lease Map

Updated: 2026-08-01
Baseline: `main@effc5e039505c09e575ca5e4aeb2b96949676366`

This is the checkout-resident admission map for the remaining Mnemosyne v2.0
benchmark program. It supersedes the runtime snapshot in the original
`a7221348` version while preserving that map's dependency, exact-lease,
single-owner, and concurrency rules. `GOAL.md`, `.planning/ROADMAP.md`,
`.planning/REQUIREMENTS.md`, `.planning/STATE.md`, and the named approved plans
remain the lifecycle authorities; this map does not create another roadmap.

## Merged baseline

The following packages are complete source history, not runnable work:

- PRs #79-#80: closed common ABI and review hardening.
- PR #81: M01 capture and M10 abstention development pilots.
- PR #82: M12 prospective-action and M13 working-memory confirmations.
- PR #83: M03 valid-time development slice.
- PR #84: M15 canonical replay and the composed M01-M03-M10 vertical slice.
- PR #85: Phase 13-15 contract freeze.
- PR #86: bounded weekly/manual development regression source.
- PR #87: canonical truth reconciliation of the GOAL/GSD lifecycle files
  (`main@2ba4ed80`, post-merge CI `30566984814`).
- PR #88: public-regression README documentation and workflow contract-test
  hardening (`main@4a891042`, post-merge CI `30659705054`).
- PR #89: this map and `.planning/STATE.md` recomputed after PR #88
  (`main@a8e9444c`, post-merge CI `30672194635`). Documentation only: it moved
  no package status, so the rows below are unchanged by it.
- PR #90: the previously stranded M12/M13 development gap disclosures in
  `eval/public/README.md`, their two pinning test suites, a cert-rotator
  lock-timeout flake fix, and the pilots-plan delivery checkpoints
  (`main@061c2e1c`, exact-head CI `30679262270`, post-merge CI `30680201900`).
  Development-source documentation and tests only: it moved no package status,
  changed no benchmark, measurement, admission state, or publication claim, and
  left `eval/public/registry.json`, the fixtures, and all adapter/scoring code
  untouched. M12/M13 remain `PROPOSED` / `publishable:false` /
  `pbpp_headline_eligible:false`, so the rows below are unchanged by it.
- PR #91: the GoalEx lifecycle delivery of the previously stranded controller
  delta — the three lifecycle files, the pilots-plan PR #90 checkpoint, and the
  26 round records (`main@e157e035`, exact-head CI `30686224929`, post-merge CI
  `30687385118`). Documentation only: it moved no package status, changed no
  benchmark, measurement, admission state, or publication claim, and touched no
  source, test, or workflow path. This is node `T3`, now `MERGED`; the rows
  below are unchanged by it except for `T3`'s own state.
- PR #92: the receipt-level lifecycle update discharging `T3`'s residue — the
  three lifecycle files at `Baseline: main@e157e035` plus the round-38 and
  round-39 records (`main@39cfa67a`, exact-head CI `30693874030`, post-merge CI
  `30694818231`). Documentation only: it moved no package status, changed no
  benchmark, measurement, admission state, or publication claim, and touched no
  source, test, or workflow path. This is node `T4`, now `MERGED`; the rows
  below are unchanged by it except for `T4`'s own state.
- PR #93: fail-closed GoalEx round-cleanup and ignored-state custody contract,
  including behavioral traceability (`main@effc5e03`, exact-head CI
  `30718912376`, post-merge CI `30719645207`). It changed no benchmark source,
  measurement, admission state, roadmap percentage, or publication claim.

This map is recomputed from the new baseline `main@effc5e03`, which the
controller branch has fully merged into it — no commit on `main` is absent from
the controller branch. **The GoalEx lifecycle backlog is delivered except for
its own merge receipts.** PR #91
landed the whole stranded delta on `main`: the three lifecycle files (`GOAL.md`,
`.planning/STATE.md`, and this map) recording PR #90's post-merge receipts on
top of earlier lifecycle content that had itself never been delivered, including
the PR #81-#84 whole-memory Decisions entry in `.planning/STATE.md`; the
pilots-plan PR #90 checkpoint; and the 26 round records touched since round 14
without being delivered through a PR — 23 new `docs/plans/goalex-r15..r38*.md`
files, the two new `docs/plans/completed/goalex-r36-*.md` and
`docs/plans/completed/goalex-r37-*.md` files, and the edit to
`docs/plans/goalex-r14-*.md` (whose original text was already on `main`). Node
`T3` below, which carried that delivery, is now `MERGED`. The GoalEx lifecycle
lease and the public-harness lease stayed unmixed: PR #91 touched nothing
outside the GoalEx lifecycle surfaces. This revision **is** the recomputation
from the resulting `main@e157e035` that the delivery required before any further
admission, and it records the receipt residue that could not exist inside the
commit it describes: PR #91, exact-head CI `30686224929`, merge SHA
`e157e035`, post-merge `main` CI `30687385118`. That recomputation was
**branch-resident only** until node `T4` delivered it as PR #92: this revision
is therefore also the recomputation from the resulting
`main@39cfa67aa7692bf47d5dde5842af3d8ec0736bb0`, and it records `T4`'s own
receipt residue — PR #92, exact-head CI `30693874030`, merge SHA `39cfa67a`,
post-merge `main` CI `30694818231`. `T4` carried exactly that receipt-level
update to the three lifecycle files plus the round-38 record and the round-39
record, and nothing else; it was documentation only and admitted no source node.
PR #93 then merged independently from the `codex/goalmd-round-ends-clean` lane
at `main@effc5e03` (exact-head CI `30718912376`, post-merge CI `30719645207`).
That external merge lapsed the branch-resident carve-out. At lapse, the residue
was no longer receipt-only: it included the undelivered baseline-pinning test
contract and the r39, r40, and r41 round records. Exactly one node, `T5`, is
therefore admitted to discharge that bounded residue. **This PR is the `T5`
delivery.** It admits no source node. This terminates because the trigger was an
independent external merge, not a receipt residue regenerating itself. The
plan-doc backlog is disclosed here rather than left to accumulate silently.
That pilots-plan checkpoint is a correction, not an addition: PR #90 shipped
`docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`
without updating its earlier paragraph, so canonical `main@061c2e1c` still
stated that the M12/M13 gap-disclosure paragraphs and their pinning tests
"are not on main and are still pending PR delivery" — a claim that same
commit falsified. That sentence was known-stale on `main` from PR #90 until
PR #91 replaced it; Tasks 7 and 8 are closed on `main` by PR #90.
Fifteen of those records (r17, r19-r21, r23-r31, r34, r35) still carry
unchecked task boxes: those boxes record the plan as written at the time and
are not a delivery signal, because each round's merged receipts are recorded in
this map and in `.planning/STATE.md` rather than back-filled into the round
record.

These receipts do not prove an official benchmark, measured sandbox, hardware
profile, publishable result, leaderboard activation, or launch.

## Shared-file owners

Every surface below is an exact repository-relative path. A trailing `/`
leases every descendant of that directory; no glob or brace expansion is
implied. `wiki:` paths name exact files in the separate Mnemosyne Wiki
repository.

| Owner | Exclusive surfaces | Admission rule |
|---|---|---|
| GoalEx lifecycle/integration owner | `GOAL.md`; `.planning/`; `docs/plans/`; `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`; `docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md`; `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`; `wiki:Home.md`; `wiki:Roadmap-and-Status.md`; `wiki:Calibration-and-Evaluation.md`; `wiki:Development-Guide.md` | One writer. Update only from verified merged reality. |
| Public-harness integration owner | `eval/public/runner.py`; `eval/public/scoring.py`; `eval/public/bundle.py`; `eval/public/registry.json`; `eval/public/README.md`; `eval/public/adapters/whole_memory_reference.py`; `eval/public/schema/wmbs-0.1-draft.schema.json`; `tests/test_public_whole_memory_reference.py`; `src/mnemosyne/cli.py`; `eval/harness/cli_driver.py` | One writer; serialize any package touching one of these paths. |
| Result-v2 integration owner | `leaderboard/schema/result-v2.schema.json`; `leaderboard/validate.py`; `leaderboard/ledger.py`; `leaderboard/render.py`; `leaderboard/publish.py`; `leaderboard/readiness.py`; `tests/test_leaderboard_result_contract.py`; `tests/test_leaderboard_ledger.py`; `tests/test_leaderboard_render.py`; `tests/test_leaderboard_publish.py`; `tests/test_leaderboard_readiness.py` | No admission until the protected signed-publication paths are released on current main. |
| CI integration owner | `.github/workflows/`; `tests/test_public_regression_workflow.py` | One writer; one exact-head authoritative full suite. |
| Evidence/operator owner | `eval/public/receipts/` | One process and one worker; no concurrent coding or broad tests during measured runs. Future run-staging and evidence-index paths remain unleased until an approved plan names their exact repository-relative paths. |

Any dirty path, active writer, open PR, or branch-ancestry overlap with an
exact lease serializes the affected packages.

## Remaining package DAG

Each row records prerequisites and consumed interfaces, produced artifacts,
exact lease, shared owner/integration edge, and external gate.

| ID | Class | Package and prerequisites / consumes | Produces | Exact write lease and owner | Integration dependency / external gate |
|---|---|---|---|---|---|
| T0 | MERGED | Canonical truth PR after PR #86; consumed exact-head CI `30559003114`, merge `661343ce`, manual run `30561430522`, and post-merge CI `30561266140` | Truthful GOAL/GSD lifecycle state and this current map | `GOAL.md`; `.planning/STATE.md`; `.planning/ROADMAP.md`; `.planning/REQUIREMENTS.md`; `.planning/phases/13-external-benchmark-adapters-and-scheduled-ci/13-01-PLAN.md`; `.planning/phases/13-external-benchmark-adapters-and-scheduled-ci/13-01-SUMMARY.md`; `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`; `tests/test_planning_traceability.py`. GoalEx owner only | Complete: merged as PR #87 at `main@2ba4ed80` with post-merge CI `30566984814` |
| T3 | MERGED | GoalEx lifecycle delivery of the previously undelivered controller delta; consumed verified canonical `main@061c2e1c` and PR #90's post-merge receipts, delivered from a lane cut from `main@061c2e1c` | The three lifecycle files, the pilots-plan PR #90 checkpoint, and the 26 round records delivered on `main`, reducing the `GOAL.md` Authority carve-out to receipt scope | `GOAL.md`; `.planning/STATE.md`; `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`; `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`; `docs/plans/`. GoalEx owner only | Complete: merged as PR #91 at `main@e157e035` with exact-head CI `30686224929` and post-merge CI `30687385118`. Documentation only; it was disjoint from every public-harness, CI, and result-v2 lease and admitted no new implementation package. This map is recomputed from that `main` and the receipt block it could not contain is recorded here; that recomputation was branch-resident, so `T3`'s residual undelivered item was exactly the receipt-level lifecycle update carried by node `T4`, now `MERGED` as PR #92 |
| T4 | MERGED | Receipt-level lifecycle update discharging `T3`'s residue; consumed verified canonical `main@e157e035` and PR #91's post-merge receipts, delivered from a lane cut from `main@e157e035` | This map at `Baseline: main@e157e035` with `T3` as `MERGED`, the matching `GOAL.md` and `.planning/STATE.md` receipt text, the updated round-38 record (whose original text PR #91 already landed on `main`), and the round-39 record, delivered on `main`, plus the branch-resident receipt recomputation below and the `test_canonical_baseline_is_identical_across_the_three_lifecycle_files` pinning test that binds the three files to one baseline | `GOAL.md`; `.planning/STATE.md`; `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`; `docs/plans/`; `tests/test_planning_traceability.py`. GoalEx owner only | Complete: merged as PR #92 at `main@39cfa67a` with exact-head CI `30693874030` and post-merge CI `30694818231`. Documentation only; exact-lease-disjoint from every public-harness, CI, result-v2, and evidence lease, and it admitted no source node. This map is recomputed here from that `main`, and the receipt block PR #92 could not contain is recorded above. That recomputation is `T4`'s own receipt residue, generated for the same structural reason `T3`'s was: no commit describes its own merge, so `main`'s copy of this map always lags by exactly one receipt block. That residual lag is an accepted standing condition and admits **no successor node** and **no source node**; `T4` is the last node this carve-out admits |
| T5 | DELIVERING | Bounded GoalEx lifecycle delivery after PR #93's independent merge lapsed the branch-resident carve-out; consumes verified canonical `main@effc5e03`, PR #93 exact-head CI `30718912376` and post-merge CI `30719645207`, and a lane cut from `main@effc5e03` | The three lifecycle files at `Baseline: main@effc5e03`, both baseline-pinning tests, and the r39/r40/r41 round records delivered on `main` | `GOAL.md`; `.planning/STATE.md`; `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`; `docs/plans/`; `tests/test_planning_traceability.py`. GoalEx owner only | This PR is the `T5` delivery. It discharges the non-receipt-only residue created when PR #93 lapsed the carve-out and admits **no source node** |
| T1 | COMPLETE | GitHub Wiki reconciliation; consumed verified canonical main | Current Home, status, evaluation, and development pages with no v2 claim upgrade | `wiki:Home.md`; `wiki:Roadmap-and-Status.md`; `wiki:Calibration-and-Evaluation.md`; `wiki:Development-Guide.md`. Wiki owner only | Complete: wiki commit `46c34287fe064842e72c3f52a9afad0c822b1846`; PR #88 changed no benchmark boundary, claim, or status any wiki page asserts, so it required no further wiki change |
| T2 | COMPLETE | Deduplicated knowledge refresh; consumed final canonical and wiki source | One current CBM graph and one Gbrain milestone | No product/source lease | Complete: single deduplicated refresh of 2026-07-30, Gbrain milestone `milestones/mnemosyne-pr86-pr87-wiki-canonical-delivery-2026-07-30`; the earlier refresh at `90841427` was not duplicated |
| P12-E | PREPARED / OPERATOR GATED | Phase 12 measured closure; local candidate-readiness software is present (126 focused tests) and runtime regression coverage is green (311 focused tests), but consumes exact `main@effc5e03`, resolved model digest, production Postgres/PPR parity, runtime readiness, grounded-reader development QA, then the protected attempt | Frozen/held-out EM/F1 and positive graph/PPR evidence | No new code lease; serial evidence/custody paths in Phase 12 plan 12-04 | Host admission (>=55% free memory and load gates), canonical external mTLS inputs, exact external candidate/runtime manifest, protected-data custody and operator authorization |
| P13-C | EXTERNAL EVENT | First real weekly cron receipt; consumes merged fixed workflow, whose cron is `23 7 * * 1` (Mondays 07:23 UTC) | Retained scheduled-cadence receipt for BENCH-007 | No code lease | Still open: only the manual dispatch `30561430522` exists; the first eligible real `schedule` event is 2026-08-03; manual dispatch is not a substitute |
| P13-O | EXTERNAL/PLAN BLOCKED | Official MemoryAgentBench and BEAM; consumes P12-E plus pinned upstream revisions/protocols | BENCH-006 conforming upstream evidence | No admitted lease; a future exact plan must name every source/evidence path | Rights/license, provider/model/judge disclosure, capacity, operator admission |
| SBOX | QUARANTINED | Development sandbox/external-meter candidate; consumes the common ABI and local reviewed sandbox commits | Only development-source isolation receipts until enforcement is proven | Current local source/test lease: `eval/public/sandbox.py`, `eval/public/sandbox/Dockerfile`, `tests/test_public_sandbox.py`; public-harness owner for any later shared integration | No push/PR/merge until immutable image, daemon probe, filesystem/network/write-boundary enforcement, SBOM, provenance, and resource receipts exist |
| N12 | LEASE BLOCKED | Additive result-v2 and M20 publication-integrity dispatch; consumes result-v1, signed ledger, renderer/publisher/readiness, official/enhanced lineage, atomic attempt identities | Compatible result-v2 projections, visible safety failures, cross-version supersession | `leaderboard/schema/result-v2.schema.json`; `leaderboard/validate.py`; `leaderboard/ledger.py`; `leaderboard/render.py`; `leaderboard/publish.py`; `leaderboard/readiness.py`; `eval/provider_bakeoff/README.md`; `tests/test_leaderboard_result_contract.py`; `tests/test_leaderboard_ledger.py`; `tests/test_leaderboard_render.py`; `tests/test_leaderboard_publish.py`; result-v2 owner only | Protected signed-publication patch/paths must be released on current main; result-v1 bytes and behavior remain immutable |
| P14-B | BLOCKED on N12 | REPRO-001 implementation; consumes N12, existing bundle/reproduce lifecycle, M15 replay, signed ledger, static renderer | Neutral reproducibility-bundle v1 schema and one clean-checkout reproduction command | Exactly `eval/public/schema/reproducibility-bundle-v1.schema.json`, `eval/public/bundle.py`, `eval/public/README.md`, `tests/test_public_reproducibility.py`; one integration owner | N12 merged, protected lease released, result-v1 golden compatibility green |
| P14-R | EVIDENCE BLOCKED | REPRO-002; consumes P14-B and a headline-eligible official result | Clean-checkout reproduction receipt | Evidence-only future lease | Official result, public bundle, custody, disclosed judge, human approval |
| P15-S2 | BLOCKED on P14-B | CAP-007/008 capability work; consumes Phase 14 and existing consolidation/queue/retrieval rails | Cadence tiers, bounded sleep consolidation, global sensemaking, surprise-gated writes | Exact `files_modified` list in `15-01-PLAN.md`; shared lifecycle files excluded | Phase 14 implementation and fresh Worktrunk lease check |
| P15-S3 | BLOCKED on P15-S2 | CAP-004/005 security and calibration development evidence | Separate attack-family hard failures and calibration/abstention diagnostics | Stage A new-file lease, then serialized Stage B integration lease in `15-02-PLAN.md` | Dataset/model/judge rights and protected-suite controls remain external |
| P15-S4 | BLOCKED on P15-S3 | CAP-006/011 performance, scale, provider, and 8 GiB closure | Warm/concurrent, provider, 100k, compact-host receipts kept separate | Task-specific exact leases in `15-03-PLAN.md`; one measurement owner | Real 100k/production backfill and physical Windows/Linux 8 GiB evidence are operator/resource gated |
| P15-S5 | BLOCKED on P15-S4 | CAP-009/010 research closure | Cartridge A/B, reduced activation-memory diagnostics, explicit go/no-go | Task-specific exact leases in `15-04-PLAN.md`; no product write path | Model/tool/license/hardware/custody admission; research never grants authority |
| P16-L | HUMAN/EVIDENCE BLOCKED | Open leaderboard launch; consumes N12, P14-R, PBPP, custody, and accepted official evidence | Public activation only after all launch gates; optional Register B/neutral review enables only the `neutral` label | No admitted source lease | Human approval, evidence sufficiency, custody, rollback and publication gates |
| U-MODULES | SPEC UNSTABLE | M02, M04-M09, M11, M14, M16-M19 | No artifact authorized | No lease | Each needs an approved exact plan, protocol, scorer, license/custody, and dependency placement before code |

## Topological waves

Only dependency-ready and exact-lease-disjoint nodes may share a wave.

```text
Prior delivery wave (complete)
  T0 PR #87 canonical truth            [merged main@2ba4ed80]
    -> T1 GitHub Wiki reconciliation   [wiki 46c34287]
      -> T2 one deduplicated CBM/Gbrain refresh [done 2026-07-30]
  PR #88 documentation/contract-test hardening merged at main@4a891042
  and admitted no new implementation package.
  PR #89 recomputed this map and STATE at main@a8e9444c
  and admitted no new implementation package.
  PR #90 landed the stranded M12/M13 development gap disclosures, their
  pinning tests, and a cert-rotator lock-timeout flake fix at main@061c2e1c
  and admitted no new implementation package.
  T3 GoalEx lifecycle backlog delivery merged as PR #91 at main@e157e035
  and admitted no new implementation package.
  T4 receipt-level lifecycle update merged as PR #92 at main@39cfa67a
  and admitted no new implementation package.
  PR #93 independently merged at main@effc5e03 (current baseline), lapsing the
  branch-resident carve-out.

Current delivery wave
  T5 [DELIVERING] discharges the bounded residue after PR #93's external merge
  lapsed the carve-out. The residue is not receipt-only: it contains an
  undelivered test contract plus the r39/r40/r41 round records. Exactly one T5
  node is admitted, and it admits no source node. This terminates because the
  trigger was an independent external merge, not a self-regenerating receipt
  residue. Every source package remains dependency-, lease-, evidence-, or
  spec-blocked.

Independent external gates (do not block T0-T5)
  P12-E operator measurement
  P13-C real scheduled event
  P13-O official upstream admission

Future source wave (currently no node is admitted)
  release protected result-v2 lease
    -> N12 result-v2/M20
      -> P14-B REPRO-001 implementation
        -> P15-S2
          -> P15-S3
            -> P15-S4
              -> P15-S5

Future evidence/launch wave
  P12-E + P13-O + N12 + P14-B
    -> P14-R
      -> P16-L

Quarantine
  SBOX stays outside every wave until real enforcement receipts exist.
  U-MODULES stay outside every wave until exact plans exist.
```

## Concurrency and integration rules

- Current safe coding concurrency is **zero new implementation writers**:
  every remaining source package is dependency-, lease-, evidence-, or
  spec-blocked. `T5` is the sole GoalEx lifecycle writer, bounded to its exact
  lease; only read-only reviews may run alongside it.
- **`GOAL.md` Authority carve-out status: lapsed by PR #93 and bounded to
  `T5`.** PR #93 was an independent external merge, so it lapsed the operative
  branch-resident map. The resulting residue included an undelivered test
  contract and three undelivered round records, not merely a regenerated
  receipt block. Exactly one node, `T5`, is admitted to discharge it. This
  terminates because the lapse trigger was external; `T5` does not admit a
  successor for its own receipt residue.
- **Next dependency-ready candidate: Phase 12 evidence preparation, and no source node.** `T5`
  admits no source node. The serial next path is
  `P12-E`: exact candidate/runtime manifest and resolved model digest, repeated
  synthetic plus 24-case `qa_scale_dev_v1`, then one protected `qa_hard_v2`
  attempt, and only after that held-out LongMemEval/Hippo evidence. Host,
  mTLS, custody, and operator gates remain fail-closed. `N12` is lease blocked (the protected
  signed-publication paths are not released on current `main`) and gates
  `P14-B` and the whole `P15-*` chain behind it; `SBOX` is quarantined until
  real enforcement receipts exist; `U-MODULES` lack approved exact plans;
  `P12-E`, `P13-O`, and `P14-R` are operator/evidence blocked; and `P16-L`
  needs human approval. The one genuinely pending item is the external event
  `P13-C` — the first real weekly `schedule` receipt, first eligible
  2026-08-03 — which is an external gate, not an admissible writer. The next
  source admission therefore waits on an external gate opening, and this map
  must be recomputed from then-current `main` at that time.
- After N12 becomes genuinely admissible, sustain at most **4-6** useful
  exact-disjoint writers and burst to **7-8** only for short read-only review,
  focused-test, or plan-contract work. These are ceilings, never targets.
- Shared schemas, runner, registry, CLI, README, planning, CI, leaderboard, and
  wiki surfaces always have one integration owner.
- Rebase or recreate every future Worktrunk lane from then-current clean
  `origin/main` before admission. Recheck writers, dirty paths, open PRs, exact
  leases, and ancestry immediately before merge; serialize on any conflict.
- Satellites run focused tests. One authoritative full suite runs once on each
  stable exact PR head. Required reviews/threads/mergeability and exact
  post-merge-main CI must be fresh before the next integration edge opens.
- Measured benchmark or hardware work is always one process, one worker, one
  suite; no coding, broad test, or other measured lane runs concurrently.
- Official-upstream, enhanced-successor, exploratory, and development records
  remain separately identified and are never blended into one certified score,
  rank, interval, or headline.
