# Mnemosyne Remaining Dependency and Write-Lease Map

Status: verified read-only portfolio snapshot
Snapshot date: 2026-07-28 America/Los_Angeles
Canonical repository: `/Users/admin/Mnemosyne`
Coordinator worktree: `/Users/admin/.codex/worktrees/9697/Mnemosyne`
Authority: `GOAL.md`, `.planning/STATE.md`, `.planning/ROADMAP.md`,
`.planning/REQUIREMENTS.md`, the approved whole-memory standard and pilot plan,
and live GitHub/process/worktree evidence.

This is a dependency and admission map, not a second roadmap. Canonical phase
status stays in GSD-owned planning files. This map records the current
topological schedule, exact write leases, active ownership, and external gates
needed to select safe GoalEx rounds.

## 1. Classification

1. **RUN-NOW** — dependency-ready and lease-disjoint; implementation or review
   may run now.
2. **CODE-NOW/INTEGRATE-LATER** — a bounded isolated core may be implemented
   now, but shared wiring or canonical integration waits for named predecessors.
3. **BLOCKED** — an explicit code dependency, active lease, evidence,
   license/rights, hardware, custody, protected-data, or human approval gate is
   unsatisfied.
4. **UNSAFE/SPEC-UNSTABLE** — no approved runnable contract or exact file lease
   exists, or starting would reinterpret a closed/shared contract.

`PROPOSED`, `DEFERRED`, `unsupported`, and `not measured` remain distinct
benchmark states. None implies failure or completion.

## 2. Live evidence and consistency findings

| Surface | Verified state |
|---|---|
| Canonical main | `/Users/admin/Mnemosyne`, clean, `main == origin/main == a95fe4d291093253f8ce49adff32ba875a35e884` |
| GitHub | No open PRs; post-merge main CI run `30411040920` succeeded at `a95fe4d2` |
| Coordinator | `codex/goalex-whole-memory-pilot@c47405a11b38`, clean, 5 commits ahead and 1 behind current main |
| Active ABI review | launchd `com.openai.mnemosyne.goalex-r12-recovery-9697`; RalphEx PID `43568`; read-only reviewer PID `89388` at snapshot |
| Runtime model truth | The in-flight recovery review is still `gpt-5.6-sol:medium`; the user-requested all-Sol-low transition is pending the next safe clean boundary and must not be claimed before process receipts show `low` |
| GoalEx persistence | launchd supervisor `com.openai.mnemosyne.goalex-sol-9697` PID `12137`; monitor `com.openai.mnemosyne.goalex-sol-monitor-9697` PID `5735` |
| Sandbox satellite | Worktrunk `/Users/admin/Mnemosyne.codex-wmb-sandbox-core`, branch `codex/wmb-sandbox-core`, clean commit `03adc078`; Claude Code satellite |
| M01 satellite | Worktrunk `/Users/admin/Mnemosyne.codex-wmb-m01-core`, branch `codex/wmb-m01-core`, clean commit `8e4a6f74`; Claude Code satellite |
| M10 satellite | Worktrunk `/Users/admin/Mnemosyne.codex-wmb-m10-core`, branch `codex/wmb-m10-core`, clean commit `4dec3862`; Claude Code satellite |
| Protected spec lease | `/Users/admin/Mnemosyne.codex-whole-memory-benchmark-spec@605ecd3d`, clean, 4 ahead/17 behind main; do not modify or integrate without owner handoff |
| Protected publication lease | `/Users/admin/Mnemosyne.codex-phase16-signed-publication`; unowned dirty `GOAL.md` and `tests/test_leaderboard_publish.py`; do not touch |
| Hermes | Excluded; no Hermes lane is admitted |
| CBM | Coordinator checkout index ready: 21,661 nodes / 97,508 edges |

### Canonical drift that must be reconciled by the integration owner

- Phase 13 source delivery is newer than `.planning/ROADMAP.md`: PRs #74–#78
  merged MemoryAgentBench and BEAM contract/configuration source, although the
  roadmap still says `Plans: Not planned`. The remaining Phase 13 work is
  upstream/official execution and regression-only scheduled CI, not
  reimplementation of those adapters.
- `GOAL.md` still documents Sol medium. The requested low-reasoning transition
  is a runtime/config reconciliation package at a safe boundary, not evidence
  that the current medium review is already low.
- The whole-memory ABI source was merged by PR #79, but five later review-fix
  commits on the coordinator branch are not on main. Integration branches must
  start from fresh main and consume the reviewed fixes deliberately.
- The benchmark-spec handoff is authoritative design input but is 17 commits
  behind main. It is a protected lease, not a branch to merge blindly.

## 3. Operating intent and provider boundaries

- GoalEx remains the continuous cross-task coordinator. RalphEx is only a
  bounded executor/reviewer under it.
- Codex GPT-5.6 Sol low is the target for future GoalEx planning, verification,
  RalphEx execution/review, and integration review after the safe transition.
- Claude Code is permitted only for bounded satellite implementation lanes with
  exact leases. It does not own lifecycle, shared integration, publication, or
  canonical planning state.
- Every implementation worktree is created and managed through Worktrunk.
  Ad-hoc worktrees and shared-checkout execution are inadmissible.
- One integration owner owns shared contracts and canonical documentation.
  Satellites may produce new-file-only cores or exact disjoint changes.
- Official upstream protocols remain unchanged. Enhanced successor tracks are
  separately named/versioned. Development tracks are non-ranking and
  non-publishable. No certified score or headline may blend official and
  enhanced records.
- No benchmark, superiority, production, launch, or publication claim is
  admitted without its held-out/operator/custody/reproduction evidence.

## 4. Shared-file single-owner boundaries

| Owner | Exclusive surfaces | Rule |
|---|---|---|
| GoalEx lifecycle/integration owner | `GOAL.md`, `.planning/**`, canonical plans/specs/docs, real wiki if discovered | No satellite writes. Update only after verified merge or factual runtime transition. |
| Whole-memory ABI owner until handoff | `eval/public/README.md`, `eval/public/adapters/whole_memory_reference.py`, `eval/public/schema/wmbs-0.1-draft.schema.json`, `tests/test_public_whole_memory_reference.py`, current ABI delivery plan | No other branch edits these while the ABI review/PR package is active. |
| Whole-memory integration owner after ABI handoff | `eval/public/runner.py`, `eval/public/scoring.py`, `eval/public/bundle.py`, `eval/public/registry.json`, `eval/public/README.md`, `src/mnemosyne/cli.py`, `eval/harness/cli_driver.py`, shared whole-memory adapter/schema/tests | Exactly one writer; satellite commits are consumed here. |
| Result-v2 integration owner | `leaderboard/schema/result-v2.schema.json`, `leaderboard/{validate,ledger,render,publish,readiness}.py`, result-v2/ledger/render/publish tests | Starts only after the Phase 16 signed-publication owner releases its lease. |
| CI integration owner | `.github/workflows/ci.yml` and any scheduled-public-regression workflow/test | One owner after an approved Phase 13 plan; no satellite edits CI. |
| Evidence/operator owner | `eval/public/receipts/**`, content-addressed run staging, public evidence index | One process/worker; no coding/test concurrency during measured runs. |

## 5. Active and near-term package DAG

Each node records prerequisites, consumed interfaces, produced artifacts, exact
lease, owner/provider, integration dependency, and external gate.

### N0 — ABI review-fix delivery

- **Class:** RUN-NOW; active.
- **Prerequisites:** PR #79/main ABI delivery; clean coordinator worktree.
- **Consumes:** `wmbs/0.1-draft`, the hardened standard, Task 1 contract tests,
  review findings.
- **Produces:** reviewed fail-closed ABI fixes and a fresh exact-head PR/CI
  candidate based on current main.
- **Exact lease:** `eval/public/README.md`,
  `eval/public/adapters/whole_memory_reference.py`,
  `eval/public/schema/wmbs-0.1-draft.schema.json`,
  `tests/test_public_whole_memory_reference.py`,
  `docs/plans/goalex-r12-deliver-the-whole-memory-common-abi.md`.
- **Owner/provider:** Codex GoalEx/RalphEx; current call is Sol medium, future
  calls transition to Sol low only at the safe boundary.
- **Integration dependency:** must land before N4–N11 touch shared ABI files.
- **External gate:** normal PR, exact-head tests/reviews/threads/mergeability.

### N1 — Development sandbox/external-meter core

- **Class:** CODE-NOW/INTEGRATE-LATER; satellite complete at `03adc078`.
- **Prerequisites:** ABI evidence definitions; isolated Worktrunk.
- **Consumes:** `SandboxReceipt`/`ResourceReceipt` concepts and existing
  `eval/g0/resource_usage.py` field semantics.
- **Produces:** `run_isolated`, declared limit/receipt structures, process-group
  timeout/output-quota enforcement, an OCI development Dockerfile, focused
  tests.
- **Exact lease:** `eval/public/sandbox.py`,
  `eval/public/sandbox/Dockerfile`, `tests/test_public_sandbox.py`.
- **Owner/provider:** Claude Code satellite; clean committed handoff.
- **Integration dependency:** N4 reconciles its receipts with the closed ABI;
  N5 wires runner/bundle dispatch.
- **External gate:** image digest is unresolved; no OCI build, SBOM, hardware
  admission, or measured receipt exists. CPU/memory/process/file limits are
  declared but not yet platform-enforced.

### N2 — M01 deterministic capture core

- **Class:** CODE-NOW/INTEGRATE-LATER; satellite complete at `8e4a6f74`.
- **Prerequisites:** M01 design and closed ABI field semantics.
- **Consumes:** deterministic capture/dedup rules.
- **Produces:** seed `20260728` development fixture, pure scorer/reference core,
  focused tests; state remains `PROPOSED`.
- **Exact lease:** `eval/public/fixtures/wmbs-m01-development.json`,
  `eval/public/wmbs_m01.py`, `tests/test_public_wmbs_m01.py`.
- **Owner/provider:** Claude Code satellite; clean committed handoff.
- **Integration dependency:** N6 adds CLI metadata pass-through, adapter,
  scoring profile, runner/bundle registration.
- **External gate:** persistence/crash durability, sandbox metering, measured
  runs, PostgreSQL/P32 evidence remain open.

### N3 — M10 deterministic abstention core

- **Class:** CODE-NOW/INTEGRATE-LATER; satellite complete at `4dec3862`.
- **Prerequisites:** M10 design and closed answer/abstention envelope.
- **Consumes:** deterministic answerable/unanswerable/contradictory cases and
  calibration/coverage rules.
- **Produces:** development fixture, deterministic reader/scorer and four
  reference baselines, 38 focused tests; state remains `PROPOSED`.
- **Exact lease:** `eval/public/fixtures/wmbs-m10-development.json`,
  `eval/public/wmbs_m10.py`, `tests/test_public_wmbs_m10.py`.
- **Owner/provider:** Claude Code satellite; clean committed handoff.
- **Integration dependency:** N7 adds ABI adapter, scoring profile,
  registry/runner/bundle wiring.
- **External gate:** no real SUT, model/LLM judge, numeric-confidence production
  path, paid provider, official suite, or measured resource evidence.

### N4 — Sandbox/schema integration

- **Class:** BLOCKED on N0 and the N1 handoff review.
- **Prerequisites:** N0 merged; N1 lease reviewed; fresh Worktrunk from current
  main.
- **Consumes:** N1 core, ABI `SandboxReceipt` and `ResourceReceipt`.
- **Produces:** schema-compatible receipts, fake-meter CI path, closed
  sandbox-failure behavior.
- **Exact lease:** N1 files plus
  `eval/public/schema/wmbs-0.1-draft.schema.json` and
  `tests/test_public_whole_memory_reference.py`.
- **Shared-file owner:** whole-memory integration owner.
- **Integration dependency:** precedes N5 and N13.
- **External gate:** OCI image build/SBOM/provenance waits for an admitted host
  and a real pinned base-image digest.

### N5 — Common public-harness registration

- **Class:** BLOCKED on N0 and N4.
- **Prerequisites:** merged ABI; schema-compatible sandbox; stable suite/profile
  contracts.
- **Consumes:** existing `run_public_suite`, `_ADAPTERS`, `_NORMALIZERS`,
  `_PROFILE_CONTRACTS`, `write_bundle`, `verify_bundle`, `reproduce_bundle`.
- **Produces:** development-only suite/profile dispatch, isolated execution
  routing, optional versioned bundle references, non-publishable registry
  entries.
- **Exact lease:** `eval/public/runner.py`, `eval/public/scoring.py`,
  `eval/public/bundle.py`, `eval/public/registry.json`,
  `eval/public/README.md`, `src/mnemosyne/cli.py`,
  `tests/test_public_eval.py`, `tests/test_public_eval_cli.py`,
  `tests/test_public_eval_scoring.py`,
  `tests/test_public_whole_memory_reference.py`.
- **Shared-file owner:** whole-memory integration owner.
- **Integration dependency:** gateway for N6–N11 and N13.
- **External gate:** any reinterpretation of an existing closed bundle requires
  an additive schema version; no silent extension.

### N6 — M01 shared integration

- **Class:** BLOCKED on N0, N2, and N5.
- **Prerequisites:** N2 core handoff; common harness stable.
- **Consumes:** N2 fixture/scorer, CLI capture contract, whole-memory adapter.
- **Produces:** metadata pass-through, `wmbs-m01-v1`, development suite
  registration, bundle-compatible results.
- **Exact lease:** N2 files plus `src/mnemosyne/cli.py`,
  `eval/harness/cli_driver.py`,
  `eval/public/adapters/whole_memory_reference.py`,
  `eval/public/scoring.py`, `tests/test_public_eval_cli.py`,
  `tests/test_public_whole_memory_reference.py`.
- **Shared-file owner:** whole-memory integration owner.
- **Integration dependency:** N11 and N13.
- **External gate:** actual crash/persistence/resource proof remains N13/P32.

### N7 — M10 shared integration

- **Class:** BLOCKED on N0, N3, and N5.
- **Prerequisites:** N3 core handoff; common harness stable.
- **Consumes:** N3 fixture/scorer/baselines and answer envelope.
- **Produces:** `wmbs-m10-v1`, real external-SUT adapter path, development suite
  registration and bundle output.
- **Exact lease:** N3 files plus
  `eval/public/adapters/whole_memory_reference.py`,
  `eval/public/scoring.py`, `eval/public/registry.json`,
  `eval/public/runner.py`, `tests/test_public_whole_memory_reference.py`.
- **Shared-file owner:** whole-memory integration owner.
- **Integration dependency:** N11 and N13.
- **External gate:** official/model-backed QA and judged confidence remain
  deferred.

### N8 — Honest M03 valid-time development slice

- **Class:** BLOCKED on N0 and N5; then RUN-NOW only as a serialized shared-file
  package.
- **Prerequisites:** stable ABI/runner and approved narrow public valid-time
  surface.
- **Consumes:** `valid_time`/`graph_as_of` CLI path and whole-memory adapter.
- **Produces:** `wmbs-m03-valid-time-development` fixture, `M-ASOF-ACC=1.0`
  scorer path, tie/stale-leakage tests.
- **Exact lease:** `eval/public/fixtures/wmbs-m03-valid-time-development.json`,
  `src/mnemosyne/cli.py`, `eval/harness/cli_driver.py`,
  `eval/public/adapters/whole_memory_reference.py`,
  `eval/public/scoring.py`,
  `tests/test_public_whole_memory_reference.py`,
  `tests/test_cli_runtime_tools.py`.
- **Shared-file owner:** whole-memory integration owner; do not satellite the
  shared portion.
- **Integration dependency:** N11 and N13.
- **External gate:** full bitemporal/transaction-time scoring remains deferred;
  no private validity tables may be read.

### N9 — M12 development-evidence confirmation

- **Class:** CODE-NOW/INTEGRATE-LATER after N5; can be a disjoint satellite if
  README updates stay with the integration owner.
- **Prerequisites:** existing prospective-action adapter/fixtures and stable
  common runner metadata.
- **Consumes:** `eval/public/action_cli.py`,
  `eval/public/adapters/pm_bench_triggerbench.py`, existing fixtures.
- **Produces:** exact fixture/count/step/unsupported-field evidence and focused
  regression receipts without upgrading the claim.
- **Satellite lease:** `tests/test_public_pm_bench_triggerbench.py`; add
  `eval/public/action_cli.py` and
  `eval/public/adapters/pm_bench_triggerbench.py` only for a reproduced defect.
- **Shared-file owner:** integration owner alone edits
  `eval/public/README.md`.
- **Integration dependency:** N13; does not block N11.
- **External gate:** isolated recurrence and official PM-Bench/TriggerBench
  require pinned upstream fixtures, scorer, rights/license.

### N10 — M13 development-evidence confirmation

- **Class:** CODE-NOW/INTEGRATE-LATER after N5; can run parallel with N9 when
  exact leases remain disjoint.
- **Prerequisites:** existing working-memory adapter/fixture and common runner
  metadata.
- **Consumes:** `eval/public/adapters/working_memory_action_probe.py`.
- **Produces:** session/tenant/expiry/capacity evidence and focused regression
  receipts without inferring promotion utility.
- **Satellite lease:** `tests/test_public_working_memory_action_probe.py`; add
  the adapter only for a reproduced defect.
- **Shared-file owner:** integration owner alone edits
  `eval/public/README.md`.
- **Integration dependency:** N13; does not block N11.
- **External gate:** isolated promotion-utility evidence remains deferred.

### N11 — M15 canonical replay and composed vertical slice

- **Class:** BLOCKED on N5, N6, N7, and N8.
- **Prerequisites:** integrated M01/M03/M10 and stable bundle contract.
- **Consumes:** ABI schema, all pilot generators/fixtures, build/config/judge
  data, metrics/traces/manifests.
- **Produces:** canonical volatile-field projection, tamper/missing-manifest
  failures, and one composed M01→M03→M10 replay cassette. This is the preferred
  runnable end-to-end vertical slice before broad module expansion.
- **Exact lease:** `eval/public/bundle.py`,
  `eval/public/adapters/whole_memory_reference.py`,
  `tests/test_public_whole_memory_reference.py`,
  `tests/test_public_eval.py`.
- **Shared-file owner:** whole-memory integration owner.
- **Integration dependency:** N13.
- **External gate:** five-run/new-process reproduction waits for N13 admission.

### N12 — Result-v2 and M20 publication-integrity contract

- **Class:** BLOCKED on the active Phase 16 signed-publication lease; otherwise
  may run in parallel with N8–N10 after N0.
- **Prerequisites:** ABI atomic identity frozen; protected publication owner
  releases its lease; result-v1 golden behavior snapshotted.
- **Consumes:** immutable attempt identity, official/successor lineage,
  result-v1 validator/ledger/publication contracts.
- **Produces:** additive `result-v2` dispatch, exact compatible-record
  projections, side-by-side filters/intervals/resource axes, visible
  non-averageable safety failures, cross-version supersession.
- **Exact lease:** `leaderboard/schema/result-v2.schema.json`,
  `leaderboard/validate.py`, `leaderboard/ledger.py`,
  `leaderboard/render.py`, `leaderboard/publish.py`,
  `leaderboard/readiness.py`, `eval/provider_bakeoff/README.md`,
  `tests/test_leaderboard_result_contract.py`,
  `tests/test_leaderboard_ledger.py`, `tests/test_leaderboard_render.py`,
  `tests/test_leaderboard_publish.py`.
- **Shared-file owner:** result-v2 integration owner.
- **Integration dependency:** N13 and N14.
- **External gate:** no public release without PBPP/custody/human approval.

### N13 — Measured L16-DEV feasibility receipts

- **Class:** BLOCKED.
- **Prerequisites:** N4–N12 integrated and reviewed; exact hardware admission;
  functional sandbox and external meter; all required BOM/privacy/rights
  declarations.
- **Consumes:** all admitted development suites, bundle/reproduction contract,
  sandbox, resource meter, result-v2.
- **Produces:** `eval/public/receipts/wmbs-pilot-evidence-index-v1.json` plus
  content-addressed preregistration, feasibility, baseline, power, BOM,
  privacy/rights, build-provenance, sandbox/resource, and reproduced-bundle
  artifacts.
- **Exact lease:** future content-addressed evidence lease plus the evidence
  index; integration owner alone updates `eval/public/README.md`.
- **Owner/provider:** operator/evidence owner; one process and one worker.
- **Integration dependency:** N14.
- **External gate:** three-sample hardware preflight, measured sandbox/meter,
  no concurrent tests or lanes, local signing, and safe artifact custody.

### N14 — Pilot review, PR, merge, and post-merge reconciliation

- **Class:** BLOCKED on N11–N13 and all review findings.
- **Prerequisites:** stable candidate head, exact leases, factual receipts.
- **Consumes:** all pilot source and evidence.
- **Produces:** focused/full verification, independent trust/statistics/rights
  review, risky-file/secret sweep, normal PR/CI/review/merge, clean post-merge
  main, one CBM refresh, one Gbrain milestone, affected canonical tracker
  updates.
- **Exact lease:** the candidate diff; `GOAL.md`/planning/docs remain exclusive
  to the integration owner.
- **Owner/provider:** Codex Sol low integration/review after verified runtime
  transition.
- **External gate:** exact-head CI, review decisions/threads, mergeability,
  post-merge CI.

## 6. Canonical phase and evidence packages

| ID | Package | Class | Prerequisites / consumes | Produces | Exact lease / owner | External gate |
|---|---|---|---|---|---|---|
| P12-E | Phase 12 measured closure: CAP-001/002/003 + BENCH-005 | BLOCKED | Existing source; production Postgres PPR parity, runtime readiness, grounded-reader development QA, one protected attempt | Frozen/held-out EM/F1 ≥0.85 and positive graph/PPR evidence | No new code lease; operator-owned evidence paths defined by 12-04 | Protected data, production/runtime, operator authorization |
| P13-S | Phase 13 source reconciliation | RUN-NOW after N14, docs-only integration owner | PRs #74–#78 and current main | Correct roadmap/requirements state: adapters delivered, upstream execution/scheduled CI open | `.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md`, `.planning/STATE.md`, affected Phase 13 plans; integration owner only | Must be factual and post-merge; no claim upgrade |
| P13-CI | Regression-only scheduled public-suite CI | RUN-NOW for contract planning; code BLOCKED until plan approval | P12-E for official execution; merged adapters already support source planning; freeze public fixtures, no held-out tuning, cadence and cost | BENCH-007 plan, then workflow and tests | Plan-only lease: `.planning/phases/13-external-benchmark-adapters-and-scheduled-ci/13-01-PLAN.md`; later code lease must name `.github/workflows/**` and focused workflow-contract tests, CI owner only | Plan approval, CI capacity, no secrets/protected data |
| P13-O | MemoryAgentBench/BEAM official/upstream path | BLOCKED | P12-E; exact upstream revisions/protocols/configs | BENCH-006 conforming upstream path and disclosed-reader evidence | Existing adapters/runner plus future exact plan; no lease admitted | Upstream coordination, official dataset/code pins, rights/license, model/judge disclosure |
| P14-B | Neutral reproducibility bundle standard | RUN-NOW for contract freeze; implementation BLOCKED on N12 | Existing bundle/reproduce path, result-v2 design, signed ledger, renderer; planning does not need an official result | REPRO-001 frozen standard and implementation plan for a clean-checkout command contract | Plan-only lease: `.planning/phases/14-reproducibility-standard-and-independent-reproduction/14-01-PLAN.md`; later code lease must name bundle/schema/docs/tests, one integration owner | Must preserve result-v1 and PBPP rails; measured proof is P14-R |
| P14-R | Headline-eligible reproduction by construction | BLOCKED | P14-B plus at least one headline-eligible official result | REPRO-002 clean-checkout reproduction receipt | Evidence lease only | Official result, public bundle, custody, human approval |
| P15-S2 | CAP-007/008 consolidation, sensemaking, surprise-gated writes | RUN-NOW for contract freeze; code UNSAFE | Phase 14 implementation before coding; S2 contract can be frozen now without product writes | Approved S2 design/plan, then product capability and regression cells | Contract-freeze lease: `.planning/phases/15-security-calibration-performance-and-scale-columns/15-01-PLAN.md`; no code lease until approved | Plan/design approval; shared engine safety rails |
| P15-S3 | CAP-004/005 security and calibration evidence | RUN-NOW for contract freeze; code UNSAFE | P15-S2 is the later execution predecessor; S3 interfaces/data/metrics can be frozen now | Approved S3 contract, then attack-success, reliability/ECE/abstention/judge diagnostics | Contract-freeze lease: `.planning/phases/15-security-calibration-performance-and-scale-columns/15-02-PLAN.md`; no code lease until approved | Dataset/model/judge rights and protected-suite controls |
| P15-S4 | CAP-006 performance/scale and provider-default evidence | RUN-NOW for contract freeze; code UNSAFE; measurement BLOCKED | P15-S3 is the later execution predecessor; measurement ABI/receipts can be frozen now | Approved S4 contract, then warm/concurrent P95, 100k behavior, provider-default evidence | Contract-freeze lease: `.planning/phases/15-security-calibration-performance-and-scale-columns/15-03-PLAN.md`; no code lease until approved | Hardware/backfill/provider/production/100k measurements |
| P15-H8 | CAP-011 physical 8 GiB acceptance | BLOCKED | Compact stack source and unchanged CAP-003/rails | Windows/Linux 8 GiB acceptance receipts | Operator/hardware evidence lease | Physical H8 hardware and operator procedure |
| P15-S5 | CAP-009/010 cartridge and activation-memory research | RUN-NOW for contract freeze; code UNSAFE | P15-S4 is the later execution predecessor; research tripwires/go-no-go contract can be frozen now | Approved S5 research contract, later bounded A/B and explicit go/no-go artifacts | Contract-freeze lease: `.planning/phases/15-security-calibration-performance-and-scale-columns/15-04-PLAN.md`; no code lease until approved | Model/data custody; no core dependency |
| P16-E | Real leaderboard evidence | BLOCKED | N12, P14, real entrant bundles and measured dimensions | LEAD-001/002 evidence, distinct operator entry | Existing source pipeline plus future evidence lease | Identical treatment, preregistration, raw artifacts, signed ledger |
| P16-L | Public launch/publication | BLOCKED | P16-E, PBPP Part I, Register A, readiness gate | Human-approved publication; optional Register B enables “neutral” label | Publication owner and operator only | Human approval, custody, dispute channel, no claim without evidence |

## 7. All twenty benchmark modules

The approved pilot authorizes only M01, the valid-time subset of M03, M10, M12,
M13, M15, and M20. For every other module, “exact lease: none” is deliberate:
an approved implementation plan must name it before admission.

| Module | Class | Prerequisites / consumed interfaces | Intended artifact | Exact lease / shared owner | External or stability gate |
|---|---|---|---|---|---|
| M01 Capture/durability | CODE-NOW/INTEGRATE-LATER | ABI ingest/finalize; N2→N5/N6 | Development fixture/scorer/bundle | N2/N6 leases above | P32 crash/resource evidence deferred |
| M02 Retrieval/organization | BLOCKED for official; UNSAFE for new local work | Universal ingest/retrieve/answer; official LoCoMo/LongMemEval revisions | Official adapters and QA/retrieval metrics | None beyond existing public adapters; future plan required | Dataset revision/license/split/scorer and pinned answer model |
| M03 Temporal evolution | BLOCKED until N5, then serialized | Narrow public valid-time/as-of CLI | Development valid-time fixture/scorer | N8 lease | Full transaction-time/bitemporal contract deferred |
| M04 Conflict/correction | UNSAFE/SPEC-UNSTABLE | Universal ingest/retrieve/answer; system-neutral correction semantics | Seeded conflict scorer | None; future plan | No approved pilot or exact lease |
| M05 Provenance/explanation | BLOCKED methodology | Evidence IDs/objective claim-source alignment | Citation/coverage/unsupported-claim scorer | None; future plan | Explanation faithfulness deferred until objective alignment is pinned |
| M06 Consolidation/learning | BLOCKED | Deterministic local roles; no-consolidation control | Utility/interference/forgetting cells | None; future P15 plan | Official MemoryAgentBench/EvoMemBench pins and exercisable control |
| M07 Retention/rehearsal/decay | UNSAFE/SPEC-UNSTABLE | Virtual-time contract | Retention/staleness/utility scorer | None; future plan | No approved plan; real-month waits forbidden |
| M08 Reversible forgetting | UNSAFE/SPEC-UNSTABLE | Advanced reversible-delete ABI | Leakage/false-removal/utility cell | None; future plan | Operation is not in the current pilot ABI |
| M09 Declared-surface erasure | BLOCKED for certification; UNSAFE for pilot | Declared readable surfaces and erasure manifest | Residue/leakage/recovery evidence | None; future plan | P32 replicas/object storage/PITR/custody |
| M10 Calibration/abstention | CODE-NOW/INTEGRATE-LATER | Answer envelope; N3→N5/N7 | Development fixture/scorer/baselines | N3/N7 leases | Official/model-backed confidence deferred |
| M11 Security/isolation | UNSAFE locally; BLOCKED for external | Principal/grant/revoke/query-as ABI | Attack/isolation utility cell | None; future plan | OIDC/P32 evidence and no approved pilot |
| M12 Prospective action | CODE-NOW/INTEGRATE-LATER | Existing action CLI/PM/TriggerBench adapter | Development evidence receipt | N9 lease | Official upstream fixtures/scorer/license |
| M13 Working memory | CODE-NOW/INTEGRATE-LATER | Existing working-memory action adapter | Development evidence receipt | N10 lease | Promotion-utility evidence deferred |
| M14 Procedural utility | UNSAFE/SPEC-UNSTABLE | Reset/observe/act/finish protocol and paired control | Deterministic simulator/scorer | None; future plan | Simulator, control, scorer and official pins not frozen |
| M15 Determinism/replay | BLOCKED on N6–N8 | Complete pilot manifests/seed records | Canonical replay and composed vertical slice | N11 lease | Clean-process reproduction waits for N13 |
| M16 Backend/transport parity | BLOCKED | Same cassette across Local/SQLite/Postgres/HTTP | Pairwise semantic/error/auth parity | None; future plan | PostgreSQL/hosted HTTP/P32; unavailable pairs remain deferred |
| M17 Custody/recovery | BLOCKED | Health/queue/snapshot/restore/failover ABI | RPO/RTO/audit/operator recovery evidence | None; operator plan | P32, object store, PITR, external custody/fingerprint |
| M18 Interoperability | BLOCKED and SPEC-UNSTABLE | Frozen portable envelope plus two independent adapters | Round-trip preservation evidence | None; future plan | Second implementation and envelope not frozen |
| M19 Multimodal memory | BLOCKED | Redistributable media fixtures and opaque payload contract | Cross-modal quality/provenance/cost cell | None; future plan | Media licensing, provider/model, complete fixture pack |
| M20 Publication integrity | BLOCKED on protected lease | Result-v1 reuse, additive result-v2, signed ledger | Atomic identity/projection/tamper/revocation contract | N12 lease | PBPP/custody/human approval for publication |

## 8. Topological waves

Only nodes in the same wave may run concurrently, and only when their exact
leases are disjoint at admission and immediately before integration.

```text
Wave 0 — active now
  N0 ABI review-fix delivery
  N1 sandbox core ─┐
  N2 M01 core ─────┼─ clean committed handoffs
  N3 M10 core ─────┘

Wave 1 — single integration owner after N0 lands
  N4 sandbox/schema integration
    -> N5 common harness registration
      -> N6 M01 integration
      -> N7 M10 integration

Wave 2 — after stable N5; up to three exact-disjoint lanes
  N8 M03 shared integration [integration owner; shared ABI/CLI/scoring]
  N9 M12 evidence-only satellite [no README]
  N10 M13 evidence-only satellite [no README]
  N12 result-v2/M20 [only if signed-publication lease is released]

  If N12 is admitted, cap Wave 2 at three implementation writers:
  N8 + N9 + N10, then N12; or N8 + N9 + N12, then N10.

Wave 3 — vertical slice and stable candidate
  N6 + N7 + N8 -> N11 M15 replay/composed M01-M03-M10 slice
  N9 + N10 + N11 + N12 -> shared documentation/registry reconciliation

Wave 4 — exclusive measured operation
  N4..N12 -> N13 L16-DEV receipts
  No other tests, builds, model work, or implementation lanes run concurrently.

Wave 5 — delivery
  N13 -> N14 review/PR/CI/merge/post-merge knowledge and tracker sync

Canonical continuation
  P12-E -> P13-S/P13-CI/P13-O -> P14-B -> P14-R
  P14-B -> P15-S2 -> P15-S3 -> P15-S4/P15-H8 -> P15-S5
  P12-E + N12 + P14-B -> P16-E -> P16-L
```

The preferred throughput path is N0→N4→N5→N6/N7/N8→N11 before expanding
beyond the authorized pilot. It yields one runnable, replayable vertical slice
instead of twenty disconnected modules.

### Future contract-freeze wave

This planning-only wave may run after the current map is accepted without
starting product code. The four files are new and path-disjoint, but
`ROADMAP.md`, `REQUIREMENTS.md`, `STATE.md`, `GOAL.md`, and all implementation
files remain reserved for the single lifecycle/integration owner.

```text
CF1  Phase 13 scheduled-regression CI contract
     -> .planning/phases/13-external-benchmark-adapters-and-scheduled-ci/13-01-PLAN.md

CF2  Phase 14 REPRO-001 standard and implementation contract
     -> .planning/phases/14-reproducibility-standard-and-independent-reproduction/14-01-PLAN.md

CF3  Phase 15 S2 capability contract
     -> .planning/phases/15-security-calibration-performance-and-scale-columns/15-01-PLAN.md

CF4  Phase 15 S3 security/calibration contract
     -> .planning/phases/15-security-calibration-performance-and-scale-columns/15-02-PLAN.md

CF5  Phase 15 S4 performance/scale/resource contract
     -> .planning/phases/15-security-calibration-performance-and-scale-columns/15-03-PLAN.md

CF6  Phase 15 S5 research/go-no-go contract
     -> .planning/phases/15-security-calibration-performance-and-scale-columns/15-04-PLAN.md
```

Provider assignment: Codex Sol low GSD planners/verifiers own CF1–CF6. Claude
Code satellites remain coding-only and are not used to create canonical GSD
plans. CF1–CF6 may be drafted in parallel only after an exact plan-file lease
check; one integration owner reviews their dependency edges and alone updates
shared canonical trackers.

## 9. Concurrency envelope

### Normal coding/review

- **Currently proven sustained envelope:** four substantive surfaces: the
  GoalEx lifecycle/review lane plus three exact-disjoint Claude satellites.
- **Admissible sustained envelope after this map:** four to six implementation
  writers only when every extra lane is dependency-ready and exact-disjoint.
  At most one writer may own any shared schema, runner, registry, CLI, README,
  planning, CI, or leaderboard surface.
- **Admissible burst:** seven to eight active surfaces for short bounded
  intervals when the extra surfaces are read-only review, contract planning, or
  focused tests. Do not turn a burst into eight shared-file writers.
- **Future ceiling:** eight to twelve writers is not admitted now. It becomes a
  candidate only after CF1–CF6 freeze more contracts, repeated waves prove
  branch/CI/resource stability, and exact leases still show zero overlap.
- **Broad test rule:** one authoritative full suite per stable candidate head.
  Satellites run focused tests; do not run duplicate full suites concurrently.

### Measured benchmark or hardware work

- **Sustained and burst:** one process, one worker, one suite. All coding,
  broad tests, measured runs, and other resource-heavy activity are serialized.
- A failed admission sample keeps the package `DEFERRED`; it does not authorize
  raising a limit or weakening a gate.

The current next code wave exposes only three safe satellite-sized packages, so
the structural four-to-six envelope is a ceiling, not a target. Empty capacity
never justifies a speculative or overlapping lane. Higher concurrency requires
frozen contracts plus observed host/CI stability, not assumption.

## 10. Conflict risks and admission/rebase/merge rules

| Risk over time | Prevention |
|---|---|
| Branch drift | Every new lane starts with `wt switch --create <branch> --base=main --no-cd --no-hooks` after fetching and proving clean `origin/main`. Before integration, compare lane base and current main. |
| Overlapping active leases | Resolve every live writer/worktree/process/PR, then compare the proposed path set with active exact leases. Any intersection serializes the packages. |
| Shared schema/adapter/runner/registry/docs | Only the integration owner writes them. Satellites omit shared files even when an upstream plan lists them. |
| Protected worktree ancestry | Never merge or rebase the protected benchmark-spec or signed-publication worktree without exact owner handoff. Consume only committed, authorized artifacts. |
| Stale candidate evidence | Tests/reviews attach to the exact candidate SHA. Any new commit invalidates earlier exact-head CI/review and triggers fresh gates. |
| Result-v1 mutation | Result-v2 uses explicit schema-version dispatch and additive supersession. Existing v1 golden cases must remain byte/behavior stable. |
| Official/enhanced contamination | `track_kind`, fidelity/difference manifests, filters, projections, columns, ranks, and headlines remain separate. Safety failures are never averageable. |
| CI saturation | One full suite per stable head; focused suites during repair; no duplicate broad jobs. Scheduled regression CI gets a separate plan and capacity budget. |
| Documentation drift | Update canonical trackers only after merge, from verified main. This map points to drift but does not overwrite canonical history. |
| Knowledge duplication | Refresh CBM once and sync one deduplicated Gbrain milestone per meaningful merge. No second wiki, roadmap, or ADR for transient lane facts. |

### Mandatory admission rule

1. Fetch `origin/main`; prove canonical main and proposed base.
2. Inventory `wt list`, `git worktree list`, dirty paths, processes, launchd
   labels, open PRs, CI, and owner handoffs.
3. Compute the exact proposed lease and intersect it with every active lease and
   every dirty path. Non-empty intersection means serialize.
4. Confirm every DAG predecessor is merged or supplied as a reviewed committed
   handoff; never consume uncommitted owner work.
5. Create the lane with Worktrunk only. Record branch, path, base SHA, provider,
   lease, focused test, and non-goals.

### Mandatory integration and merge rule

1. Recheck writers, leases, branch ancestry, and current main before consuming a
   handoff.
2. Use a fresh Worktrunk integration branch from current main when the source
   branch has drifted or touches shared files. Cherry-pick/reapply reviewed
   commits without rewriting protected history; resolve only as integration
   owner.
3. Run focused tests during repair, then one full suite on the stable candidate.
4. Sweep exact diff, risky files, secrets, supply chain, trust boundaries,
   result compatibility, claims language, and lease scope.
5. Push normally; open/update a PR; require exact-head CI, independent review,
   zero unresolved threads, clear mergeability, and current-head evidence.
6. Merge normally only after every gate clears. Never direct-push main, force,
   bypass hooks, dismiss findings, or reuse stale-head evidence.
7. Verify post-merge CI; safely fast-forward canonical local main; prove
   `main == origin/main` and clean; refresh CBM once; sync Gbrain once; update
   only affected canonical trackers/docs; then recompute this DAG.

## 11. Immediate next decisions without launching new lanes

1. Let N0 finish its current read-only review at the safe boundary.
2. Verify N1/N2/N3 clean commits and diff-only lease compliance; keep them local
   and unpushed.
3. Transition future Codex GoalEx/RalphEx stages to Sol low and prove the new
   process receipts before updating canonical runtime language.
4. Deliver N0 through a fresh-main PR/CI/review path.
5. Admit one integration owner for N4→N7. Do not add a fourth satellite or touch
   shared files before that owner has reconciled the three handoffs.
6. Keep N12 blocked until the signed-publication owner explicitly releases its
   dirty lease.
7. Keep all official, protected, measured, hardware, custody, and publication
   packages blocked until their named evidence gates are satisfied.
