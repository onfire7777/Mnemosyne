# Roadmap: Mnemosyne Memory

## Overview

This roadmap follows the v2 build blueprint exactly: foundations and contracts first, lossless retrieval second, belief and graph confidence third, personalization and consolidation fourth, procedural learning fifth, and profile-guided self-optimization last. Each phase is independently useful and verified through tests or explicit gap reports.

## Phases

**Phase Numbering:**
- Integer phases match the blueprint's Phase 0 through Phase 5.
- Decimal phases are reserved for urgent insertions if verification discovers missing prerequisites.

- [x] **Phase 0: Foundations and Contracts** - Evidence ledger, branches, isolation, MCP/CLI skeleton, and seed regression suite.
- [x] **Phase 1: Lossless Memory and Hybrid Retrieval** - Bitemporal assertions, provenance, hybrid retrieval, explain, correction, export, and forget.
- [x] **Phase 2: Belief Core, Graph, and Confidence** - Full TMS/AGM, cascade invalidation, graph adapter, conformal calibration, and multi-hypothesis surfacing.
- [x] **Phase 3: Personalization and Consolidation** - Six-category user model, latent advisory profile, warm-loop consolidation, fidelity lifecycle, and anti-degradation guard.
- [x] **Phase 4: Procedural and Corrective Learning** - Trajectory logging, failure attribution, lesson induction, promotion gate, branch promote/rollback, and capability-secured writes.
- [x] **Phase 5: Profile-Guided Self-Optimization** - Shadow-first policy optimization, self-model store, canary branches, diversity tripwire, and optional parametric tier boundaries.
- [ ] **Phase 6: Exact Blueprint Runtime Parity** - Complete production MCP/Postgres/retrieval/security/deployment parity beyond the deterministic local scaffold.

## Phase Details

### Phase 0: Foundations and Contracts
**Goal**: Capture evidence exactly, deduplicate by content address, isolate by tenant/source/trust, expose a stable agent-facing contract, and run a seed regression suite.
**Depends on**: Nothing
**Requirements**: REQ-001, REQ-002, REQ-003, REQ-004, REQ-011
**Success Criteria** (what must be TRUE):
  1. Same evidence ingested twice creates one row keyed by CID.
  2. Evidence can be byte-recalled by CID until explicit erasure.
  3. Branch discard removes candidate memories without touching main.
  4. CLI and MCP facade expose capture, search, deep_search, explain, correct, forget, export.
  5. Seed suite runs in CI-style local command.
**Plans**: 4 plans

Plans:
- [x] 00-01: Initialize Python package, local engine contract, models, and identifiers.
- [x] 00-02: Implement evidence ledger, branch, merge, discard, audit, and persistence.
- [x] 00-03: Implement MCP-compatible facade and CLI skeleton.
- [x] 00-04: Add regression tests for dedup, byte recall, branch rollback, and seed suite.

### Phase 1: Lossless Memory and Hybrid Retrieval
**Goal**: Add bitemporal assertions, supersession, provenance, hybrid retrieval, explainability, correction, export, and transitive forget behavior.
**Depends on**: Phase 0
**Requirements**: REQ-005, REQ-006, REQ-007, REQ-008, REQ-009
**Success Criteria** (what must be TRUE):
  1. Newer contradictory assertions supersede older beliefs without destructive overwrite.
  2. As-of queries return the belief valid at the requested time.
  3. Retrieval fuses lexical, deterministic dense, and graph channels with provenance.
  4. Trust filters block low-trust poisoned memories.
  5. Forget erases evidence content and retracts or trims dependent assertions.
**Plans**: 5 plans

Plans:
- [x] 01-01: Implement assertion model, supersession, contested basics, and as-of queries.
- [x] 01-02: Implement lexical, dense-hash, graph, RRF, MMR, U-curve, and budgeted retrieval.
- [x] 01-03: Implement explain output with channel attribution and invariant rails.
- [x] 01-04: Implement correct, export, and forget with provenance propagation.
- [x] 01-05: Add tests for retrieval, trust filters, abstention, supersession, and erasure.

### Phase 2: Belief Core, Graph, and Confidence
**Goal**: Replace baseline supersession with full TMS/AGM semantics, justification DAG cascade invalidation, temporal graph adapters, calibrated confidence, conformal abstention, and multi-hypothesis belief packets.
**Depends on**: Phase 1
**Requirements**: REQ-013, REQ-014, REQ-009
**Success Criteria** (what must be TRUE):
  1. Belief operations classify ADD, UPDATE, SUPERSEDE, and NOOP with justifications.
  2. Cascade invalidation recomputes dependent beliefs through the justification DAG.
  3. Contested beliefs surface alternatives with probabilities instead of a forced answer.
  4. Temporal graph retrieval supports cached fast path and live deep path behind the engine contract.
  5. Calibration thresholds are learned from eval cases and drive abstention decisions.
**Plans**: 5 plans

Plans:
- [x] 02-01: Add deterministic local security, lifecycle, gate, graph, and confidence scaffolding.
- [x] 02-02: Implement full justification DAG storage and cascade invalidation.
- [x] 02-03: Implement calibrated confidence datasets and conformal threshold updates.
- [x] 02-04: Add graph adapter path and PPR latency benchmark harness.
- [x] 02-05: Add contradiction-conformance and multi-hypothesis test suite.

### Phase 3: Personalization and Consolidation
**Goal**: Implement the dual user model, warm-loop consolidation, fidelity-tiered forgetting, spaced rehearsal, and long-horizon anti-degradation guard.
**Depends on**: Phase 2
**Requirements**: REQ-012, REQ-015, REQ-016
**Success Criteria** (what must be TRUE):
  1. Six typed user-model categories include scope, confidence, validity, exceptions, and override path.
  2. Explicit instructions outrank inferred preferences and latent profile signals.
  3. Consolidation emits candidates through a write-authorized consolidator role.
  4. Fidelity demotion preserves pointers and triggers abstention on sole gist support.
  5. Long-horizon no-degradation metric prevents consolidated memory from dropping below baseline.
**Plans**: 5 plans

Plans:
- [x] 03-01: Add explicit preference precedence and fidelity lifecycle primitives.
- [x] 03-02: Add deterministic consolidation worker through promotion gate.
- [x] 03-03: Implement six-category model and scope-matching context assembly.
- [x] 03-04: Implement consolidation role pipeline and incremental recompute guard.
- [x] 03-05: Implement spaced rehearsal and anti-degradation metrics.

### Phase 4: Procedural and Corrective Learning
**Goal**: Capture trajectories, attribute failures, induce lessons and procedures, validate candidates with protected regression and counterfactual replay, and promote or roll back branches safely.
**Depends on**: Phase 3
**Requirements**: REQ-017, REQ-010, REQ-011
**Success Criteria** (what must be TRUE):
  1. Trajectories record task, steps, outcome, reward, and memory version.
  2. Failure attribution creates candidate lessons without direct promotion.
  3. Promotion gate scopes regression by relevance and blocks protected-case regressions.
  4. Counterfactual replay runs on canary branches before activation.
  5. Capability mediation prevents untrusted data from reaching preference, policy, or destructive sinks.
**Plans**: 5 plans

Plans:
- [x] 04-01: Add promotion gate, protected cases, rollback, and capability checks.
- [x] 04-02: Implement trajectory store and failure-attribution checklist.
- [x] 04-03: Implement lesson and procedure induction.
- [x] 04-04: Implement counterfactual replay harness.
- [x] 04-05: Add MINJA and AgentPoison protected test tier.

### Phase 5: Profile-Guided Self-Optimization
**Goal**: Learn safe policy variants for routing, activation, thresholds, cadence, and fidelity demotion in shadow mode, promote only through gates, and maintain a self-model with diversity and proxy-divergence tripwires.
**Depends on**: Phase 4
**Requirements**: REQ-018, REQ-011, NFR-005
**Success Criteria** (what must be TRUE):
  1. Policy variants are constrained to immutable rails.
  2. Shadow-mode outcomes are logged before any active promotion.
  3. Candidate policy improves measured outcomes without protected regressions.
  4. Self-model records effectiveness by metric and policy version.
  5. Diversity and proxy-vs-true divergence tripwires auto-rollback bad variants.
**Plans**: 5 plans

Plans:
- [x] 05-01: Add shadow policy variant evaluator and invariant-rail checks.
- [x] 05-02: Implement self-model persistence and outcome windows.
- [x] 05-03: Implement bandit-style policy proposal.
- [x] 05-04: Implement diversity and proxy-divergence monitoring.
- [x] 05-05: Add canary policy promotion and rollback tests.

### Phase 6: Exact Blueprint Runtime Parity
**Goal**: Convert the verified local scaffold into exact 1:1 blueprint parity across runtime protocols, production storage/retrieval, security, deployment, multimodal ingestion, prefetch, and parametric-tier boundaries.
**Depends on**: Phase 5
**Requirements**: FR-3, FR-7, FR-9, FR-12, FR-18, FR-19, FR-20, FR-21, all production NFRs
**Success Criteria** (what must be TRUE):
  1. The same contract suite passes against LocalMemoryEngine and PostgresEngine in Docker.
  2. MCP exposes the full blueprint tool surface with auth/capability enforcement and typed schemas.
  3. Postgres retrieval uses real vector, lexical/BM25, graph, rerank, provenance, and budget paths instead of local fallbacks.
  4. Ingestion verifies signed provenance, externalizes multimodal payloads, and indexes derived text safely.
  5. Queue-backed workers run consolidation, embedding, calibration, eval, and lifecycle demotion off the hot path.
  6. Production privacy/security rails cover tenant isolation, erasure recompute, C2PA trust, poisoning protection, and auditability.
**Plans**: 6 plans

Plans:
- [ ] 06-01: Complete MCP/CLI runtime tool surface and auth/capability enforcement.
- [ ] 06-02: Add live PostgresEngine contract tests and tenant-scoped branch semantics.
- [ ] 06-03: Replace retrieval fallbacks with real pgvector, lexical/BM25, graph, and reranker adapters.
- [ ] 06-04: Complete ingestion, object storage, C2PA, multimodal extraction, and safe quarantine flow.
- [ ] 06-05: Wire queue-backed consolidation, calibration, lifecycle, eval, and observability jobs.
- [ ] 06-06: Validate exact parity with local and production deployment smoke suites.

Checkpoint: CLI-first file ingestion now supports signed-provenance JSON, a `c2patool`-style verifier adapter, asset-bound report validation, and scoped JSON trust-policy enforcement; quarantined evidence is hidden from default retrieval. Trust-tier semantics now follow the blueprint scale: `0` direct-user/highest trust through `5` untrusted external. Ingest classification now tags actor/source trust, untrusted imperative content, and simple PII. Ingestion now enqueues persisted consolidation jobs, CLI commands can inspect/enqueue/drain queue jobs, `--queue-backend postgres` provides tenant-scoped durable row leasing with result persistence, and the worker can extract a simple direct-user fact candidate through the promotion gate while refusing data-only untrusted facts. CLI/MCP ingestion now also supports strict runtime processing residency and fail-closed cross-region `source->target` transfer allowlists, with CLI/MCP residency-policy inspection and provider-check reporting. Provider-check now also validates configured command object-key/KMS providers with a key-cycle/shred probe. Local queued handlers now cover calibration, lifecycle sweep, eval suite, and observability snapshot jobs. Promotion gates now use tenant-aware branch/merge/discard calls where available and are live-smoked against Postgres; shared Local/Postgres branch coverage now verifies tenant-scoped branch names, branch merge retrieval, exported merge-log parity, and abandoned TMS justifications and contradictions are pruned with branch-only assertions and dependency-only orphaned justifications; shared evidence coverage now verifies the full evidence envelope including external session identity, immutable duplicate-CID semantics, tombstone replay prevention, stored Postgres evidence pgvector retrieval, and null-embedding legacy fallback; Postgres runtime state now persists MCP/CLI profile and learning state into tenant-scoped runtime rows mirrored to `preferences`, `user_latent`, `trajectories`, `lessons`, and `procedures`; shared graph coverage now verifies expired relations are excluded from default PPR while explicit historical `as_of` traversal still works. Plan 06-01 now includes generated MCP input-schema validation across JSON-RPC and SDK transports, CLI `tools` MCP inputSchema parity, and capability-mediated lesson/procedure activation and rollback through CLI/MCP; it remains open for hosted MCP deployment validation, production auth/session issuance, and broader stateless soak testing. Plan 06-04 remains open for production certificate-chain/root validation and derived multimodal extraction/indexing; Plan 06-05 remains open for hosted worker supervision/deployment operations across consolidation, calibration, lifecycle, eval, and observability jobs.

Latest checkpoint: `provider-check --provider-manifest` now gates deployment manifests by hydrating provider flags from JSON, resolving secret fields from environment variables, requiring named checks, and failing closed when a production manifest forbids local retrieval adapters. Local verification collects 226 tests with 201 passing and 25 live-DB skips; the compose Postgres/shared suite passes 63 tests with `MNEMOSYNE_POSTGRES_DSN` set.
