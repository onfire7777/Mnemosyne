# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-19)

**Core value:** Build a memory compiler with lossless evidence, typed projections, safe retrieval, branchable updates, and gated self-improvement.
**Current focus:** Strict blueprint parity gap closure

## Current Position

Phase: Strict parity continuation after Phase 5 scaffold
Plan: Exact blueprint parity audit and runtime gap closure
Status: In progress; exact 1:1 blueprint parity is not complete.
Last activity: 2026-06-20 — Added CLI-first runtime coverage, selectable CLI Postgres backend support, Postgres retrieval parity for SQL FTS/pgvector/graph, shared local/Postgres engine contract coverage, durable Postgres queue leasing/drain support, fail-closed capability enforcement, Postgres tenant RLS, explicit erasure modes, HTTP-compatible embedding/reranker provider adapters, strict HTTP provider response validation, fail-closed CLI `provider-check` health probes for embedding/reranker/media-extractor contracts, CLI file ingestion through a C2PA verifier adapter with asset hash binding, scoped JSON trust-policy enforcement, provenance validity/trust/binding capability tags, AES-GCM encrypted local object storage with JSON key management and legal hard-delete key shredding, configurable fail-closed ingestion data-residency enforcement, MCP object-store encryption/residency config parity, transitive source-to-derived evidence erasure for media extraction outputs plus assertion/preference/relation projection recompute, blueprint-correct trust-tier semantics, deterministic ingest classification, persisted local queue-backed consolidation jobs from ingestion, gated deterministic fact extraction for direct-user evidence, persisted protected regression gate cases, local queued calibration/lifecycle/eval/observability job handlers, tenant-aware promotion gates for Postgres, blueprint-facing CLI/MCP ABI aliases, signature-derived MCP tool schemas, optional MCP tools/call auth, optional official MCP Python SDK stdio mode with schema validation and auth-token enforcement, expanded live Postgres shared-contract coverage for bitemporal supersession, tenant isolation, branch merge retrieval, metadata-derived OCR/transcript/caption indexing for externalized object evidence, an async `media_extract` provider job that appends derived media text without mutating source evidence, fail-closed write-path authorization for fact/relation/proposal/supersession/correction writes, explicit branch/promotion/discard authorization through `MemoryTools` and CLI, a CLI `ops-report` JSON snapshot with durable retrieval-channel, p95 latency, gate promotion/rollback, and contradiction-backlog tripwire metrics, static HTML `ops-report --dashboard-html` export with retrieval/calibration/learning/gate sections and renderer/CLI smoke coverage, deterministic consolidation entity resolution plus summarizer/lesson-distiller/skill-inducer role outputs persisted through runtime learning state, a local isolated parametric artifact sidecar with CLI/MCP rollback metadata, TOOL_SPEC-allowlisted MCP dispatch with JSON-RPC argument validation, and local stateless MCP mode that rebuilds engine/tools per call from durable state. The test suite now has 133 passing tests and 20 skipped live-DB tests locally with the optional MCP SDK extra installed; a fresh-schema DSN-backed live Postgres run passes 30 engine/CLI/consolidation/shared-contract smokes. Strict audit remains open for exact production parity.

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
- [Parity]: `tests/test_shared_engine_contract.py` now runs the same evidence retrieval/export, branch/discard, and bitemporal `as_of` contracts against `LocalMemoryEngine` and `PostgresEngine`; this also fixed Postgres branch creation for previously unseen tenants.
- [Security]: `MemoryTools` now enforces `SecurityPolicy` for preference writes, hard-instruction profile writes, and destructive forget operations; CLI denials are covered by tests.
- [Security]: Fact, relation, proposal, supersession, and correction writes now route through `MemoryTools` capability checks; CLI `assert`/`relation` no longer bypass the facade.
- [Security]: Branch creation, confirmation, merge, and discard now require explicit role/source-trust context through `MemoryTools` and CLI; branch promotion requires operator/consolidator authority.
- [MCP]: `mneme-mcp --sdk` can now run the same tool facade through the official Python MCP SDK when the optional `mcp` extra is installed; SDK handler tests cover tool listing, schema validation, auth-token denial, capture, and search.
- [Consolidation]: Default local passes now resolve deterministic entity keys and execute summarizer, lesson_distiller, and skill_inducer roles for fact candidates; lessons/procedures persist through runtime learning state and are visible in `ops-report`.
- [Queue]: CLI `queue-enqueue`, `queue-drain`, `queue-snapshot`, and ingestion enqueueing can now use `--queue-backend postgres` with tenant-scoped `FOR UPDATE SKIP LOCKED` leasing and durable result persistence.
- [Gate]: CLI `gate-case-add/list` persists protected regression cases in runtime state; consolidation workers load them and fail closed when a protected case regresses.
- [Observability]: CLI `ops-report` now exports dashboard-ready counts, queue state, learning diversity, proxy-vs-true gap, and tripwire status for a tenant; `--dashboard-html` writes a static dashboard artifact with memory, queue, retrieval, calibration, learning, gate/eval, and bounded JSON sections.
- [Storage]: `sql/schema.sql` now enables and forces tenant RLS on tenant-owned tables, and `PostgresEngine` sets `mnemosyne.tenant_id` before tenant-scoped SQL.
- [Privacy]: Local and Postgres forget paths now accept `tombstone_recompute` or `hard_delete_legal`; CLI exposes `--erasure-mode`; encrypted local object storage supports AES-GCM per-object keys and legal hard-delete crypto-shreds the object key after successful forget; CLI and MCP ingestion enforce configured data residency labels and record residency in evidence access policy; forget now erases media-derived evidence and retracts/strips assertions/preferences/relations that depended on source or derived evidence.
- [Retrieval]: CLI/Postgres can now use local or HTTP-compatible embedding and reranker providers via flags/env while keeping deterministic local defaults; HTTP providers now fail closed on malformed responses and `provider-check` exits nonzero on broken contracts.
- [Provenance]: CLI `ingest` now accepts `--file`, modality/media type, signed-provenance JSON, a `--c2pa-tool` adapter, and `--provenance-trust-policy`; C2PA reports must bind to the exact asset by SHA-256/path before they can raise trust, scoped policies can match trusted tenant/source/modality context and quarantine valid-but-untrusted manifests when no rule or issuer matches, provenance validity/trust/binding capability tags propagate through evidence, and quarantined evidence is hidden from default retrieval unless `include_quarantined` is explicitly set.
- [Security]: Trust-tier semantics now follow the blueprint scale: `0` direct-user/highest trust through `5` untrusted external; retrieval/write gates, provenance deltas, SQL defaults, and CLI defaults were migrated.
- [Ingestion]: The hot path now classifies actor/source trust, adds capability/taint tags, detects simple PII, raises sensitivity/access-policy metadata, marks untrusted imperatives as data-only, indexes metadata-derived OCR/transcript/caption/alt/description text for externalized object evidence, and queues async media extraction when non-text payloads lack derived text.

### Pending Todos

- Finish exact blueprint parity, starting with expanding the live PostgresEngine smoke into a full shared contract suite, hardening CLI/MCP schemas, and adding official MCP SDK/server integration tests.
- Validate production embedding/reranker deployments behind the HTTP-compatible adapter boundary; add ParadeDB/BM25 where needed and AGE/specialist graph adapters where needed.
- Add production auth/session identity, deployment-grade authorization integration, production KMS-backed key management, production C2PA certificate-chain/root validation, native image/audio embedding providers, production extractor deployment validation, cross-region residency controls, worker supervision/deployment operations, and deployment observability.

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
