# Remaining Dependency and Write-Lease Map

Updated: 2026-08-03
Baseline: `main@b8673031a80158c49d552a4b3647829d213243bd`

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
- PR #94: the `T5` lifecycle delivery (`main@2091d01c`, exact head
  `41b21305`, exact-head CI `30730185494`, post-merge CI `30730918452`).
  Documentation, contract-test, and CI configuration only: it admitted no
  source node. Its own
  `docs/plans/` lease omitted the round-42 record, which is the non-receipt
  residue discharged by `T6`.
- PR #95: the `T6` lifecycle delivery (`main@42abaab7`, exact head
  `d7c0938f`, exact-head CI `30737466988`, post-merge CI `30738303497`).
  Documentation only: it delivered the r42 and r43 round records, admitted no
  source node, and changed no benchmark, measurement, admission state, or
  publication claim.
- PR #96: the independently delivered development-only M02/M04/M05 evaluation
  oracles (`main@088e2f31`, exact head `1050749a`, CI `30744318093`). This
  advanced canonical `main` outside the GoalEx lifecycle-node sequence without
  changing publication eligibility.
- PR #97: the round-43 review adjudication and controller
  reconciliation. It records PR #96 above, recomputes
  the canonical baseline to `main@088e2f31`, makes M05's source events conform
  to the frozen `portable_event` ABI, and replaces the traceability test's
  ancestry assertion with the unrecorded-merge detector this row satisfies.
  It admits no source node and changes no benchmark, measurement, admission
  state, or publication claim. It is recorded here before merge because the
  detector requires every PR merged after the baseline to appear in this map,
  and — by the terminal canonical-state property — no commit can carry its own
  merge receipts, which is equally why no exact head is claimed for it here:
  the commit recording one would change it. **The GoalEx loop is paused at this
  PR, not retired**: it is stopped with its blocking condition cleared, and a
  later round may resume and recompute this map. Its receipts, verifiable only
  from a later commit and recorded here now: merge `71e492b4`, exact head
  `13c05d65`, exact-head CI `30774834604`, post-merge CI `30775783472`.
- PR #98: documentation-only correction of PR #97's overstated claim that the
  loop was retired, restoring it to paused. It admits no source node and
  changes no benchmark, measurement, admission state, or publication claim.
  Recorded here before merge for the same reason as PR #97: the detector
  requires every PR merged after the baseline to appear in this map. Its
  receipts, likewise recorded only now: merge `b8673031`, exact head
  `b49b0b35`, exact-head CI `30787319275`, post-merge CI `30788531829`.

This map is recomputed from the new baseline `main@b8673031`, which the
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
contract and the r39, r40, and r41 round records. Node `T5` discharged that
bounded residue as PR #94 at `main@2091d01c`, with exact-head CI `30730185494`
and post-merge CI `30730918452`; it admitted no source node. Its delivery
omitted the r42 record from its own `docs/plans/` lease. `T6` discharged that
non-receipt residue together with the r43 record as PR #95 at `main@42abaab7`,
with exact head `d7c0938f`, exact-head CI `30737466988`, and post-merge CI
`30738303497`; it admitted no source node and no successor node. This
branch-resident recomputation is `T6`'s own standing-condition residue. It
admits no successor node and no source node. The plan-doc backlog is disclosed
here rather than left to accumulate silently.
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
| T4 | MERGED | Receipt-level lifecycle update discharging `T3`'s residue; consumed verified canonical `main@e157e035` and PR #91's post-merge receipts, delivered from a lane cut from `main@e157e035` | This map at `Baseline: main@e157e035` with `T3` as `MERGED`, the matching `GOAL.md` and `.planning/STATE.md` receipt text, the updated round-38 record (whose original text PR #91 already landed on `main`), and the round-39 record, delivered on `main`, plus the branch-resident receipt recomputation below | `GOAL.md`; `.planning/STATE.md`; `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`; `docs/plans/`. GoalEx owner only | Complete: merged as PR #92 at `main@39cfa67a` with exact-head CI `30693874030` and post-merge CI `30694818231`. Documentation only; exact-lease-disjoint from every public-harness, CI, result-v2, and evidence lease, and it admitted no source node. This map is recomputed here from that `main`, and the receipt block PR #92 could not contain is recorded above. That recomputation is `T4`'s own receipt residue, generated for the same structural reason `T3`'s was: no commit describes its own merge, so `main`'s copy of this map always lags by exactly one receipt block. That residual lag is an accepted standing condition and admits **no successor node** and **no source node**; `T4` is the last node this carve-out admits |
| T5 | MERGED | Bounded GoalEx lifecycle delivery after PR #93's independent merge lapsed the branch-resident carve-out; consumed verified canonical `main@effc5e03`, PR #93 exact-head CI `30718912376` and post-merge CI `30719645207`, and a lane cut from `main@effc5e03` | The three lifecycle files, both baseline-pinning tests, and the r39/r40/r41 round records delivered by PR #94 | `GOAL.md`; `.planning/STATE.md`; `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`; `docs/plans/`; `tests/test_planning_traceability.py`; `.github/workflows/ci.yml`. GoalEx owner with CI integration shared-owner serialization | Complete: merged as PR #94 at `main@2091d01c`, exact head `41b21305`, exact-head CI `30730185494`, post-merge CI `30730918452`. Documentation, contract-test, and CI configuration only; it admitted no source node. Its delivery omitted the round-42 record from its own `docs/plans/` lease, the non-receipt residue discharged by `T6` |
| T6 | MERGED | Verified canonical `main@2091d01c` plus PR #94 exact-head CI `30730185494` and post-merge CI `30730918452`; lane cut from `main@2091d01c` | The three lifecycle files at `Baseline: main@2091d01c` with `T5` as `MERGED`, plus the r42 and r43 round records | `GOAL.md`; `.planning/STATE.md`; `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`; `docs/plans/`. GoalEx owner only | Complete: merged as PR #95 at `main@42abaab7`, exact head `d7c0938f`, exact-head CI `30737466988`, post-merge CI `30738303497`. Documentation only; it admitted no source node and no successor node. This branch-resident recomputation is `T6`'s own accepted standing-condition residue and admits no successor or source node |
| T7 | ADMITTED | Bounded documentation-and-tests node disclosing PR #96's development-only M02/M04/M05 evaluation oracles; consumed verified canonical `main@b8673031` plus PR #97 (merge `71e492b4`, exact-head CI `30774834604`, post-merge CI `30775783472`) and PR #98 (merge `b8673031`, exact-head CI `30787319275`, post-merge CI `30788531829`) receipts | The M02/M04/M05 Stage-A development gap disclosures in `eval/public/README.md`, their pinning tests, and the three lifecycle files recomputed to `Baseline: main@b8673031` | `eval/public/README.md`; the new/edited pinning test file(s) under `tests/`; `GOAL.md`; `.planning/STATE.md`; `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`; `docs/plans/`. GoalEx owner only | Documentation and tests only. It admits **no source node**, **no Stage-B integration**, and **no successor node**: no `eval/public/registry.json` entry, adapter, runner routing, profile contract, or scoring-profile registration is authorized, no module behavior or fixture byte changes, M02/M04/M05 stay `PROPOSED` / `publishable:false` / `pbpp_headline_eligible:false`, and no progress counter moves. Stage B for all three remains blocked on the public-harness integration owner's lease. **Delivery statement:** the `eval/public/README.md` M02/M04/M05 Stage-A development-oracle gap disclosure and its pinning suite `tests/test_public_wmbs_stage_a_disclosure.py` are delivered by PR-1 of GoalEx round 46 |
| T8 | ADMITTED | Bounded GoalEx lifecycle documentation-and-tests node landing the stranded Round-0 M01-M20 completeness inventory; consumes verified canonical `main@b8673031` and the same PR #97/#98 receipts `T7` consumes | The M01-M20 module completeness inventory, its line-level derivations, the drift test that pins the inventory to the tree, and the three lifecycle files recomputed to `Baseline: main@b8673031` | Exactly `docs/coordination/2026-08-03-wmbs-module-completeness-inventory.md`; `docs/coordination/2026-08-03-wmbs-module-completeness-derivation.md`; `tests/test_wmbs_module_inventory.py`; `GOAL.md`; `.planning/STATE.md`; `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`; `docs/plans/`. GoalEx owner only | Documentation and tests only. It admits **no source node** and **no publication claim**: no module implementation, protocol, scorer, adapter, registry entry, fixture byte, schema, or admission state changes, and no progress counter moves. Lease-disjoint from every public-harness source path |
| T9 | ADMITTED | Public-harness Stage-B M03 registry-admission node; consumes verified canonical `main` at the PR-1 merge commit | The `wmbs-m03-valid-time-development` entry in `eval/public/registry.json`, its `_ADAPTERS` and `_PROFILE_CONTRACTS` keys in `eval/public/runner.py`, its `eval/public/README.md` documentation, and its tests | Exactly `eval/public/registry.json`; `eval/public/runner.py`; `eval/public/README.md`; the new/edited test files under `tests/`. Public-harness integration owner, serialized as **sole writer** (no open PR and no competing lane at this baseline) | Authorizes **M03 only**. It admits no other module, changes no fixture byte, no scorer logic, and no schema, and it advances **no admission state**: M03 stays `PROPOSED` / `publishable:false` / `pbpp_headline_eligible:false`, with full bitemporal transaction-time query semantics retained as a hard deferral per `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md` line 68. Reachability fix only; it admits **no successor node** |
| T1 | COMPLETE | GitHub Wiki reconciliation; consumed verified canonical main | Current Home, status, evaluation, and development pages with no v2 claim upgrade | `wiki:Home.md`; `wiki:Roadmap-and-Status.md`; `wiki:Calibration-and-Evaluation.md`; `wiki:Development-Guide.md`. Wiki owner only | Complete: wiki commit `46c34287fe064842e72c3f52a9afad0c822b1846`; PR #88 changed no benchmark boundary, claim, or status any wiki page asserts, so it required no further wiki change |
| T2 | COMPLETE | Deduplicated knowledge refresh; consumed final canonical and wiki source | One current CBM graph and one Gbrain milestone | No product/source lease | Complete: single deduplicated refresh of 2026-07-30, Gbrain milestone `milestones/mnemosyne-pr86-pr87-wiki-canonical-delivery-2026-07-30`; the earlier refresh at `90841427` was not duplicated |
| P12-E | EXTERNAL/OPERATOR BLOCKED | Phase 12 measured closure; consumes existing 12-04 source, production Postgres PPR parity, runtime readiness, grounded-reader QA, protected attempt | Frozen/held-out EM/F1 and positive graph/PPR evidence | No new code lease; operator evidence paths in Phase 12 plan 12-04 | Protected data, production/runtime, operator authorization |
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
| U-MODULES | SPEC UNSTABLE | Module implementation for M02, M04-M09, M11, M14, M16-M19 — **excluding** the development-only M02/M04/M05 evaluation oracles already delivered by PR #96 | No artifact authorized | No lease | Each needs an approved exact plan, protocol, scorer, license/custody, and dependency placement before code. PR #96's oracles are development-only: they authorize no module implementation, protocol, scorer admission, or publication claim, so these IDs remain SPEC UNSTABLE for module work |

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
  PR #93 independently merged at main@effc5e03 (the merge that lapsed the branch-resident carve-out), lapsing the
  branch-resident carve-out.
  T5 lifecycle delivery merged as PR #94 at main@2091d01c
  and admitted no source node.
  T6 lifecycle delivery merged as PR #95 at main@42abaab7
  and admitted no source node or successor node. Its branch-resident
  recomputation is T6's own accepted standing-condition residue.

Current delivery wave
  Through PR #96 this wave's recorded status was: No GoalEx lifecycle or source
  node is admitted. PR #96 independently merged
  development-only M02/M04/M05 evaluation oracles; no writer for them remains
  active, and their publication eligibility is unchanged. That status is now
  superseded by three admitted nodes, and the "no admitted writer" wording no
  longer holds:
    T7 documentation-and-tests: discloses those three oracles in
    eval/public/README.md and pins the disclosure with tests. It admits no
    source node, no Stage-B integration, and no successor node, and it leaves
    every module's admission state, publication eligibility, and the registry
    untouched.
    T8 documentation-and-tests: lands the stranded Round-0 M01-M20 completeness
    inventory, its derivations, and its drift test. It admits no source node and
    no publication claim.
    T9 public-harness Stage-B integration: registers the existing, already
    scorer-backed and unit-tested M03 valid-time development cell so it is
    reachable from run_public_suite. It is a reachability fix for M03 only. It
    changes no fixture byte, no scorer, no schema, and no admission state, and
    it admits no successor node.
  T7 and T8 share the GoalEx owner and are lease-disjoint from T9; T9 runs
  serialized as the sole writer on the eval/public/* lease, after T7+T8 merge.

Independent external gates (do not block T0-T9)
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

- Current safe coding concurrency is **zero new module-implementation
  writers**: every remaining source package is dependency-, lease-, evidence-,
  or spec-blocked. That claim is scoped to *module-implementation* writers. It
  is unaffected by `T7` and `T8`, whose exact leases contain no module, adapter,
  registry, protocol, scorer, or fixture path, and it is unaffected by `T9`,
  which registers an already-merged, already-tested cell and implements no
  module. `T6` is merged; three writers are admitted at this baseline — `T7` and
  `T8` (documentation-and-tests, GoalEx owner, mutually lease-disjoint, landing
  together as PR-1) and `T9` (public-harness integration owner, sole writer on
  `eval/public/*`, landing as PR-2 only after PR-1 merges). `T9` is serialized:
  no other PR is open and no other lane touches `eval/public/*`. This
  serialization is the explicit remedy for PR #96's defect, where three modules
  merged onto that lease while this map admitted no writer for it. Otherwise
  only read-only reviews may run.
- **`GOAL.md` Authority carve-out status: standing controller condition from
  `T6` onward.** Both the one-block receipt lag and the current round's own plan
  record are accepted standing conditions of the controller branch. They are
  discharged only by branch-resident recomputation, never by admitting a
  successor node. `T6` admits no successor node and no source node.
- **Next dependency-ready candidates: `T9`, then external gate `P13-C`, and no
  new source node.** `T9` is dependency-ready the moment PR-1 merges, and it is
  a bounded reachability fix, not a source node: it admits no module
  implementation. Beyond it, `P13-C` is first eligible 2026-08-03. The Phase 12
  evidence path remains `P12-E`: exact candidate/runtime manifest and resolved model digest, repeated
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
