# Roadmap: v2.0 Public Benchmark and Memory Leadership

## Shipped Milestones

- [x] **v1.0 Blueprint-Complete Memory Compiler** — [roadmap](milestones/v1.0-ROADMAP.md), [requirements](milestones/v1.0-REQUIREMENTS.md), [audit](milestones/v1.0-MILESTONE-AUDIT.md).

## v2.0 Phases

- [x] **Phase 10: Public Harness and Neutral Governance Foundation** - Build M1.1 and L0 without publishing a number. (completed 2026-07-10)
- [x] **Phase 11: Deterministic Public Retrieval Tracks** - LongMemEval retrieval plus HippoRAG multi-hop deterministic measurement. (completed 2026-07-11)
- [ ] **Phase 12: Grounded Multi-Hop Answer Synthesis** - Close Plan A S1 under public and private regression gates.
- [ ] **Phase 13: External Benchmark Adapters and Scheduled CI** - MemoryAgentBench, BEAM, and regression-only cadence.
- [ ] **Phase 14: Reproducibility Standard and Independent Reproduction** - M2/M3 publication eligibility.
- [ ] **Phase 15: Memory Capability and Evidence Closure** - Plan A S2-S5 capability, security, calibration, performance, scale, and research closure.
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
provenance-linked graph/PPR participation and reader-produced Hippo EM/F1. W1
now has a deterministic local development proof (PRs #23, #26, and #28), but
production parity on `postgres-recursive-ppr`, runtime readiness, grounded-reader
development QA, and the single protected attempt remain open under 12-04.

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

### Phase 15: Memory Capability and Evidence Closure

**Goal:** Execute Plan A in dependency order after S1: multi-timescale and
sleep consolidation, freshness/expiry, global map-reduce sensemaking,
surprise-gated writes, security/calibration evidence, performance/scale
closure, the cartridge A/B, and the activation-memory go/no-go research note.
It also closes the physical 8 GiB compact grounded-QA path without weakening
the shared quality or custody gates.
**Requirements:** CAP-004..010, CAP-012, CAP-013, RAIL-001..004
**Depends on:** Phases 10-14
**Plans:** Not planned

**Required plan order:** S2 capability upgrades; S3 security/calibration; S4
performance/scale; S5 research closure. S5 remains non-gating for public launch
except that its promised research artifact must exist before Plan A is complete.

**Boundary:** The W3 prospective-memory and working-memory planes (CAP-012,
CAP-013) landed early and are merged across Local/Postgres/Sqlite via PR #39
(`main@0784340`); both requirement rows are Complete in `.planning/REQUIREMENTS.md`
and test-pinned by `tests/test_planning_traceability.py`. The same merge landed
the W2 D5 signed deletion manifest and the W3 I0R signed-session public-action
evaluator, whose PM-Bench/TriggerBench/Working-Memory suites are development-split
and `publishable:false` — they add no public or headline benchmark result. The
remaining Phase 15 items (CAP-004..010) stay planned, and the W1/W4/W5 GATEs
remain operator-gated; none of that gated or adapter work is claimed complete.

### Phase 16: Open Leaderboard Build and Launch

**Goal:** Reuse the public harness as the equal-access submission engine, build
the transparent data/site surfaces, and launch once the source-owned Register A
gates hold.
**Requirements:** LEAD-001, LEAD-002, LEAD-003, GOV-001, RAIL-003, RAIL-004
**Depends on:** Phases 10-12. The site and data pipeline no longer wait on full
Phase 15 capability closure — see Sequencing below.
**Plans:** Not planned

**Revised v0.2.0.** Launch is gated on Register A of
`docs/governance/BOARD-STATUS.md` — pre-registration, an append-only signed run
ledger, reproducibility by construction, an open stack, a populated adversarial
self-report, and a public dispute channel — all of which the operator can
produce. Board seating, a legal steward, funding, external ratification, and a
multi-owner archive moved to Register B as an optional upgrade that would permit
the *neutral* label. Rationale: `docs/governance/CREDIBILITY-MODEL.md`.

**Sequencing.** The leaderboard surface may be built and published against
whatever tracks genuinely exist, filling in as capabilities land. A dimension is
rendered only once measured; nothing is claimed ahead of evidence. This removes
the previous dead end in which the site waited on eight unplanned CAP
requirements while those requirements had no delivery date.

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
