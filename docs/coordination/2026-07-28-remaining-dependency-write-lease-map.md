# Remaining Dependency and Write-Lease Map

Updated: 2026-07-30
Baseline: `main@661343ce05186e9a7f0f0740d1edef7c23532857`

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

These receipts do not prove an official benchmark, measured sandbox, hardware
profile, publishable result, leaderboard activation, or launch.

## Shared-file owners

| Owner | Exclusive surfaces | Admission rule |
|---|---|---|
| GoalEx lifecycle/integration owner | `GOAL.md`, `.planning/**`, canonical specs/docs, this map, and the real GitHub Wiki | One writer. Update only from verified merged reality. |
| Public-harness integration owner | `eval/public/{runner,scoring,bundle}.py`, `eval/public/registry.json`, `eval/public/README.md`, shared whole-memory adapter/schema/tests, `src/mnemosyne/cli.py`, `eval/harness/cli_driver.py` | One writer; serialize any package touching one of these paths. |
| Result-v2 integration owner | `leaderboard/schema/result-v2.schema.json`, `leaderboard/{validate,ledger,render,publish,readiness}.py`, result-v2/ledger/render/publish tests | No admission until the protected signed-publication paths are released on current main. |
| CI integration owner | `.github/workflows/**` and workflow-contract tests | One writer; one exact-head authoritative full suite. |
| Evidence/operator owner | `eval/public/receipts/**`, content-addressed run staging, official-result and public-evidence indexes | One process and one worker; no concurrent coding or broad tests during measured runs. |

Any dirty path, active writer, open PR, or branch-ancestry overlap with an
exact lease serializes the affected packages.

## Remaining package DAG

Each row records prerequisites and consumed interfaces, produced artifacts,
exact lease, shared owner/integration edge, and external gate.

| ID | Class | Package and prerequisites / consumes | Produces | Exact write lease and owner | Integration dependency / external gate |
|---|---|---|---|---|---|
| T0 | ACTIVE | Canonical truth PR after PR #86; consumes exact-head CI `30559003114`, merge `661343ce`, manual run `30561430522`, and post-merge CI `30561266140` | Truthful GOAL/GSD lifecycle state and this current map | `GOAL.md`; `.planning/{STATE,ROADMAP,REQUIREMENTS}.md`; Phase 13 `13-01-{PLAN,SUMMARY}.md`; this file. GoalEx owner only | Normal PR #87 CI/review/merge/post-merge proof |
| T1 | BLOCKED on T0 | GitHub Wiki reconciliation; consumes verified canonical main | Current Home, status, evaluation, and development pages with no v2 claim upgrade | `/Users/admin/Mnemosyne.wiki/{Home,Roadmap-and-Status,Calibration-and-Evaluation,Development-Guide}.md`; wiki owner only | T0 merged and local/remote wiki master clean/equal |
| T2 | BLOCKED on T0/T1 | Deduplicated knowledge refresh; consumes final canonical and wiki source | One current CBM graph and one Gbrain milestone | No product/source lease | Run once only if T0/T1 source changed; do not duplicate the refresh already completed at `90841427` |
| P12-E | EXTERNAL/OPERATOR BLOCKED | Phase 12 measured closure; consumes existing 12-04 source, production Postgres PPR parity, runtime readiness, grounded-reader QA, protected attempt | Frozen/held-out EM/F1 and positive graph/PPR evidence | No new code lease; operator evidence paths in Phase 12 plan 12-04 | Protected data, production/runtime, operator authorization |
| P13-C | EXTERNAL EVENT | First real weekly cron receipt; consumes merged fixed workflow | Retained scheduled-cadence receipt for BENCH-007 | No code lease | A real `schedule` event must occur; manual dispatch is not a substitute |
| P13-O | EXTERNAL/PLAN BLOCKED | Official MemoryAgentBench and BEAM; consumes P12-E plus pinned upstream revisions/protocols | BENCH-006 conforming upstream evidence | No admitted lease; a future exact plan must name every source/evidence path | Rights/license, provider/model/judge disclosure, capacity, operator admission |
| SBOX | QUARANTINED | Development sandbox/external-meter candidate; consumes the common ABI and local reviewed sandbox commits | Only development-source isolation receipts until enforcement is proven | Current local source/test lease: `eval/public/sandbox.py`, `eval/public/sandbox/Dockerfile`, `tests/test_public_sandbox.py`; public-harness owner for any later shared integration | No push/PR/merge until immutable image, daemon probe, filesystem/network/write-boundary enforcement, SBOM, provenance, and resource receipts exist |
| N12 | LEASE BLOCKED | Additive result-v2 and M20 publication-integrity dispatch; consumes result-v1, signed ledger, renderer/publisher/readiness, official/enhanced lineage, atomic attempt identities | Compatible result-v2 projections, visible safety failures, cross-version supersession | `leaderboard/schema/result-v2.schema.json`; `leaderboard/{validate,ledger,render,publish,readiness}.py`; `eval/provider_bakeoff/README.md`; `tests/test_leaderboard_{result_contract,ledger,render,publish}.py`; result-v2 owner only | Protected signed-publication patch/paths must be released on current main; result-v1 bytes and behavior remain immutable |
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
Current delivery wave
  T0 PR #87 canonical truth
    -> T1 GitHub Wiki reconciliation
      -> T2 one deduplicated CBM/Gbrain refresh

Independent external gates (do not block T0-T2)
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
  spec-blocked. T0 is the single shared-owner writer; read-only reviews may run
  beside it.
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
