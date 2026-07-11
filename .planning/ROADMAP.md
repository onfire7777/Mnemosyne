# Roadmap: v2.0 Public Benchmark and Memory Leadership

## Shipped Milestones

- [x] **v1.0 Blueprint-Complete Memory Compiler** — [roadmap](milestones/v1.0-ROADMAP.md), [requirements](milestones/v1.0-REQUIREMENTS.md), [audit](milestones/v1.0-MILESTONE-AUDIT.md).

## v2.0 Phases

- [x] **Phase 10: Public Harness and Neutral Governance Foundation** - Build M1.1 and L0 without publishing a number. (completed 2026-07-10)
- [x] **Phase 11: Deterministic Public Retrieval Tracks** - LongMemEval retrieval plus HippoRAG multi-hop deterministic measurement. (completed 2026-07-11)
- [ ] **Phase 12: Grounded Multi-Hop Answer Synthesis** - Close Plan A S1 under public and private regression gates.
- [ ] **Phase 13: External Benchmark Adapters and Scheduled CI** - MemoryAgentBench, BEAM, and regression-only cadence.
- [ ] **Phase 14: Reproducibility Standard and Independent Reproduction** - M2/M3 publication eligibility.
- [ ] **Phase 15: Security, Calibration, Performance, and Scale Columns** - Plan A S3/S4 measured evidence.
- [ ] **Phase 16: Neutral Leaderboard Build and Launch** - L1-L4 after PBPP and Part I gates.

### Phase 10: Public Harness and Neutral Governance Foundation

**Goal:** Create the isolated public CLI evaluation substrate and neutral
governance source charter that every later benchmark and entrant must use.
**Requirements:** BENCH-001, BENCH-002, BENCH-003, GOV-001, RAIL-001..004
**Depends on:** v1.0, completed M4/PBPP
**Plans:** 2/2 plans complete

Plans:

- [x] 10-01-PLAN.md — Public CLI harness and reproducibility bundle scaffold.
- [x] 10-02-PLAN.md — Neutral governance, permanent COI, and operator firewall.

**Boundary:** Harness and governance source scope are complete. GOV-001 remains
partial until the external board is seated and ratifies the source policy;
Phase 16 owns final activation and launch readiness.

### Phase 11: Deterministic Public Retrieval Tracks

**Goal:** Wire LongMemEval retrieval-recall and HippoRAG multi-hop suites with
deterministic scoring, pinned upstream inputs, confidence intervals, and traces.
**Requirements:** BENCH-004, BENCH-005, RAIL-001..004
**Depends on:** Phase 10
**Plans:** 3/3 plans complete

Plans:

- [x] 11-01-PLAN.md — Generalize immutable asset and multi-metric bundle custody.
- [x] 11-02-PLAN.md — LongMemEval cleaned retrieval-recall track.
- [x] 11-03-PLAN.md — HippoRAG three-dataset retrieval and deterministic scorer.

**Boundary:** Phase 11 completed BENCH-004. BENCH-005 remains partial until
positive graph/PPR participation is demonstrated and Phase 12 supplies
disclosed grounded-reader predictions for real EM/F1.

### Phase 12: Grounded Multi-Hop Answer Synthesis

**Goal:** Add iterative decomposition/retrieval/evidence assembly and a
provenance-grounded reader that reaches the accepted QA target without recall
or safety regression.
**Requirements:** CAP-001, CAP-002, CAP-003, RAIL-001..004
**Depends on:** Phase 11
**Plans:** 3/4 complete

Plans:

- [x] 12-01-PLAN.md — Freeze candidate protocol and complete separate public QA custody.
- [x] 12-02-PLAN.md — Bounded multi-hop/PPR and episode-aware orchestration.
- [x] 12-03-PLAN.md — Grounded Ollama reader and read-only public answer surface.
- [ ] 12-04-PLAN.md — Frozen internal/held-out evidence and no-regression closure.

**Boundary:** Phase 12 does not close from implementation alone. CAP-003 requires
both measured >=0.85 gates; BENCH-005 additionally requires positive,
provenance-linked graph/PPR participation and reader-produced Hippo EM/F1.

### Phase 13: External Benchmark Adapters and Scheduled CI

**Goal:** Add MemoryAgentBench and disclosed-reader BEAM adapters plus scheduled
deterministic regression runs that never tune on test data.
**Requirements:** BENCH-006, BENCH-007, RAIL-001..004
**Depends on:** Phases 10-12
**Plans:** Not planned

### Phase 14: Reproducibility Standard and Independent Reproduction

**Goal:** Freeze the neutral artifact standard and obtain independent
third-party reproduction for at least one headline-eligible result.
**Requirements:** REPRO-001, REPRO-002, RAIL-003, RAIL-004
**Depends on:** Phases 11-13
**Plans:** Not planned

### Phase 15: Security, Calibration, Performance, and Scale Columns

**Goal:** Produce publishable attack-under-defense, public-label calibration,
warm/concurrent latency, 100k-item, and provider-default evidence.
**Requirements:** CAP-004, CAP-005, CAP-006, RAIL-001..004
**Depends on:** Phases 10-14
**Plans:** Not planned

### Phase 16: Neutral Leaderboard Build and Launch

**Goal:** Reuse the public harness as the equal-access submission engine, build
the transparent data/site surfaces, and launch only after governance, PBPP,
Part I, and reproduction gates pass.
**Requirements:** LEAD-001, LEAD-002, LEAD-003, GOV-001, RAIL-003, RAIL-004
**Depends on:** Phases 10-15
**Plans:** Not planned

## Carried Evidence Boundaries

- Real provider default selection and runtime-flip evidence remain measured work.
- Production cache and vector-backfill evidence remain operator-owned.
- Negative/abstention caching and broader wheel adoption remain explicit work,
  never silently converted into public claims.

## Archived v1.0 Phase Index

### Phase 00: Foundations and Contracts (archived v1.0)

### Phase 01: Lossless Memory and Hybrid Retrieval (archived v1.0)

### Phase 02: Belief Core, Graph, and Confidence (archived v1.0)

### Phase 03: Personalization and Consolidation (archived v1.0)

### Phase 04: Procedural and Corrective Learning (archived v1.0)

### Phase 05: Profile-Guided Self-Optimization (archived v1.0)

### Phase 06: Exact Blueprint Runtime Parity (archived v1.0)

### Phase 07: Unified Cognitive Substrate (archived v1.0)

### Phase 08: Self-Hosted-First Production Architecture (archived v1.0)

### Phase 09: Performance and Refactoring Continuation (archived v1.0)

### Phase 09.1: Caller-Context Closure (archived v1.0)

### Phase 09.2: Public Heartbeat Closure (archived v1.0)

### Phase 09.3: Milestone Evidence Closure (archived v1.0)
