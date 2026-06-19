# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-19)

**Core value:** Build a memory compiler with lossless evidence, typed projections, safe retrieval, branchable updates, and gated self-improvement.
**Current focus:** Strict blueprint parity gap closure

## Current Position

Phase: Strict parity continuation after Phase 5 scaffold
Plan: Exact blueprint parity audit and runtime gap closure
Status: In progress; exact 1:1 blueprint parity is not complete.
Last activity: 2026-06-19 — Added CLI-first runtime coverage plus selectable CLI Postgres backend support, Postgres retrieval parity for SQL FTS, pgvector assertion search, deterministic evidence dense fallback, and recursive graph/PPR. The test suite now has 60 passing tests and 2 skipped live-DB tests; the DSN-backed live Postgres engine and CLI smokes pass separately. Strict audit remains open for exact production parity.

Progress: [███████░░░] local scaffold verified; production parity gaps remain

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
- [Runtime]: CLI now supports `--backend local|postgres` plus `--postgres-dsn`/`MNEMOSYNE_POSTGRES_DSN`; live tests verify the Postgres backend through real CLI commands.

### Pending Todos

- Finish exact blueprint parity, starting with expanding the live PostgresEngine smoke into a full shared contract suite, hardening CLI/MCP schemas, and adding official MCP SDK/server integration tests.
- Replace deterministic Postgres retrieval fallbacks with production embedding providers, ParadeDB/BM25 where needed, AGE/specialist graph adapters where needed, and cross-encoder reranker integrations.
- Add production auth/RLS, tenant-scoped branch APIs, C2PA verifier integration, multimodal extraction, and deployment observability.

### Blockers/Concerns

- Exact 1:1 blueprint parity is not yet achieved; `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md` is the controlling status artifact.
- Original documentation folder on Desktop is read-only to this process; project build lives in `/Users/admin/Projects/Mnemosyne`.
- Docker/Postgres parity was verified live after launching Docker Desktop and recreating the schema volume.
- Legal hard-delete semantics need operator policy beyond the local tombstone behavior.

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Production storage | Full PostgresEngine parity beyond schema initialization | Open | Strict parity audit |
| Retrieval | Production embedding/BM25/graph/reranker adapters beyond deterministic Postgres pgvector/FTS/PPR | Partial | Strict parity audit |
| Security | Auth/RLS, C2PA verifier, and expanded protected suite | Open | Strict parity audit |
| Runtime | Full MCP protocol compatibility and complete tool surface | Open | Strict parity audit |

## Session Continuity

Last session: 2026-06-19 13:47 America/Los_Angeles
Stopped at: Autonomous build in progress after 16 passing tests.
