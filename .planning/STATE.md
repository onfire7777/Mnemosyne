# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-19)

**Core value:** Build a memory compiler with lossless evidence, typed projections, safe retrieval, branchable updates, and gated self-improvement.
**Current focus:** GitHub project initialization

## Current Position

Phase: 5 of 5 (Profile-Guided Self-Optimization)
Plan: 05-05 of 5 in current phase
Status: Milestone complete, GitHub initialization pending
Last activity: 2026-06-19 — Audit passed and v1.0 milestone archive records were created.

Progress: [██████████] 100%

## Performance Metrics

**Velocity:**
- Total plans completed: 12
- Average duration: not yet measured
- Total execution time: current autonomous session in progress

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 0 | 4 complete | 4 | pending |
| 1 | 5 complete | 5 | pending |
| 2 | 5 complete | 5 | pending |
| 3 | 5 complete | 5 | pending |
| 4 | 5 complete | 5 | pending |
| 5 | 5 complete | 5 | pending |

## Accumulated Context

### Decisions

- [Phase 0]: V2 blueprint is controlling; v1 is lineage only.
- [Phase 0]: Build moved to `/Users/admin/Projects/Mnemosyne` because `/Users/admin/Desktop/Mnemosyne` is write-blocked.
- [Phase 0]: Local deterministic engine is used for fast verification; `sql/schema.sql` preserves the production PostgreSQL contract.
- [Phase 1]: Retrieval currently uses deterministic hashing embeddings and lexical scoring for local tests; production adapters remain required.
- [Phase 2]: Graph/PPR remains behind the engine contract; a benchmark harness now exists for backend profiling.
- [Phase 2]: Justification DAG, cascade invalidation, operation classification, contested hypotheses, and conformal calibration are implemented locally.
- [Phase 3]: Six-category user model, scope-matched context assembly, latent advisory profile, rehearsal schedule, and anti-degradation guard are implemented locally.
- [Phase 4]: Trajectory logging, failure attribution, lesson/procedure induction, gate promotion, replay scoring, and permanent poisoning cases are implemented locally.
- [Phase 5]: Self-model store, outcome windows, policy variant proposal, tripwire checks, and canary policy gate are implemented locally.
- [NFR]: Local latency benchmark, schema coverage, privacy classification, metrics registry, and Docker compose config are implemented.
- [Phase 5]: Self-optimization remains shadow-first and constrained by immutable rails.

### Pending Todos

- Create GitHub remote after repository verification and initial commit.

### Blockers/Concerns

- Git repository and GitHub remote still need to be initialized.
- Original documentation folder on Desktop is read-only to this process; project build lives in `/Users/admin/Projects/Mnemosyne`.
- Docker/Postgres parity was verified live after launching Docker Desktop and recreating the schema volume.
- Legal hard-delete semantics need operator policy beyond the local tombstone behavior.

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Production storage | Docker Postgres extension parity | Open | Phase 0 |
| Calibration | Conformal threshold calibration | Open | Phase 2 |
| Security | MINJA and AgentPoison permanent suite | Open | Phase 4 |

## Session Continuity

Last session: 2026-06-19 13:47 America/Los_Angeles
Stopped at: Autonomous build in progress after 16 passing tests.
