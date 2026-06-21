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

Checkpoint: CLI-first file ingestion now supports signed-provenance JSON, a `c2patool`-style verifier adapter, asset-bound report validation, and scoped JSON trust-policy enforcement; quarantined evidence is hidden from default retrieval. Trust-tier semantics now follow the blueprint scale: `0` direct-user/highest trust through `5` untrusted external. Ingest classification now tags actor/source trust, untrusted imperative content, and simple PII. Ingestion now enqueues persisted consolidation jobs, CLI commands can inspect/enqueue/drain queue jobs, `--queue-backend postgres` provides tenant-scoped durable row leasing with result persistence, and the worker can extract a simple direct-user fact candidate through the promotion gate while refusing data-only untrusted facts. CLI/MCP ingestion now also supports strict runtime processing residency and fail-closed cross-region `source->target` transfer allowlists, with CLI/MCP residency-policy inspection and provider-check reporting. Provider-check now also validates configured command object-key/KMS providers with a key-cycle/shred probe. Local queued handlers now cover calibration, lifecycle sweep, eval suite, and observability snapshot jobs, and CLI `worker-run` now supervises bounded cycles with heartbeat metrics and dead-job failure gating. Promotion gates now use tenant-aware branch/merge/discard calls where available and are live-smoked against Postgres; shared Local/Postgres branch coverage now verifies tenant-scoped branch names, branch merge retrieval, exported merge-log parity, and abandoned TMS justifications and contradictions are pruned with branch-only assertions and dependency-only orphaned justifications; shared evidence coverage now verifies the full evidence envelope including external session identity, immutable duplicate-CID semantics, tombstone replay prevention, stored Postgres evidence pgvector retrieval, and null-embedding legacy fallback; Postgres runtime state now persists MCP/CLI profile and learning state into tenant-scoped runtime rows mirrored to `preferences`, `user_latent`, `trajectories`, `lessons`, and `procedures`; shared graph coverage now verifies expired relations are excluded from default PPR while explicit historical `as_of` traversal still works. Plan 06-01 now includes generated MCP input-schema validation across JSON-RPC and SDK transports, CLI `tools` MCP inputSchema parity, capability-mediated lesson/procedure activation and rollback through CLI/MCP, JWKS cache/rotation support for OIDC exchange, fail-closed OIDC authz policy mapping, redacted `idp-authz-policy-check` validation/audit summaries, fingerprint-acknowledged `idp-authz-policy-rollout-check` diffs with claim-simulation change gates, command-backed session-secret custody for CLI/MCP signing and verification plus provider-check OIDC/JWKS/authz-policy/session-secret preflight, redacted `idp-jwks-live-check` validation for operator-supplied live IdP tokens/JWKS, hosted HTTP TLS/client-certificate enforcement, TLS endpoint certificate-chain checks, TLS rotation-plan validation, official SDK StreamableHTTP local validation, CLI `mcp-http-soak` validation for hosted HTTP health/stateless/read-only loops, CLI `mcp-sse-soak` validation for legacy SSE stream handshakes, and CLI `deployment-soak` orchestration for allowlisted production preflight manifests; it remains open for operator-run production credential/endpoint evidence capture, certificate issuance/renewal execution, and deployed secret distribution. Plan 06-05 now has local worker supervision coverage but remains open for deployed worker process management across consolidation, calibration, lifecycle, eval, and observability jobs. Plan 06-04 now stores media-derived text as searchable evidence plus a graph lineage relation, but remains open for broader multimodal extraction/indexing.

Latest checkpoint: `provider-check --provider-manifest` now gates deployment manifests by hydrating provider flags from JSON, resolving secret fields from environment variables, requiring named checks, and failing closed when a production manifest forbids local retrieval adapters. Local verification collects 300 tests with 261 passing and 39 live-DB skips; the compose Postgres/shared suite passes 63 tests with `MNEMOSYNE_POSTGRES_DSN` set.

Latest checkpoint: Local `export_all()` now matches the shared backup/DSAR shape for calibration sets, entity registry rows, tenant snapshots, and tenant-scoped branch rows while filtering erased evidence from top-level and tenant exports; export-style `to_json()` branch rows can reload into the local engine.

Latest checkpoint: `mneme-mcp --self-test` now provides a secret-redacted local deployment preflight for MCP initialize/list/schema/auth/session/read-only-call behavior. `mneme-mcp --http` now serves a hosted HTTP JSON-RPC endpoint with `/healthz`, `/mcp`, bearer/session-header binding, optional TLS and client-certificate enforcement, body-size limits, malformed/non-object/unsupported-method rejection, auth/session/schema coverage, locked facade access, and stateless restart durability tests. `mneme-mcp --sdk-streamable-http` now serves the official MCP SDK StreamableHTTP ASGI surface and local runtime tests verify SDK-client initialize/list/call behavior over that transport. CLI `mcp-http-soak` now validates hosted HTTP health/stateless/read-only loops without exposing bearer/session tokens, CLI `mcp-sse-soak` validates legacy SSE stream handshakes with secret-redacted event previews, CLI `idp-jwks-live-check` validates operator-supplied live IdP tokens/JWKS without minting or printing a Mnemosyne session, CLI `deployment-soak` runs allowlisted production preflight manifests, and CLI `tls-rotation-plan-check` validates certificate swap windows before deployment. This is still not full hosted parity; operator-run production credential/endpoint evidence capture, certificate issuance/renewal execution, and deployed secret distribution remain open. CLI `provider-check` now also rejects command KMS providers that claim `shred_key` success while still reporting or returning the post-shred key.

Latest checkpoint: CLI `session-exchange` and hosted HTTP `/session/exchange` now validate OIDC/JWKS IdP tokens and mint bounded Mnemosyne signed-session tokens for the existing CLI/MCP authorization path. Tests cover issuer/audience/tenant/role/trust validation, RS256 and ES256 signatures, unsafe JWKS metadata rejection, bounded JWKS loading, cache TTL refresh, refresh-on-unknown-`kid` rotation, tampering, secret redaction, CLI failure modes, authz policy mapping from allowed IdP clients and exact/contains claim rules, fail-closed policy misses, no raw-claim fallback when policy mode is configured, hosted `/healthz` policy presence reporting, fingerprinted authz policy rollout diffs with acknowledged current/candidate fingerprints and simulation-change gates, and use of the exchanged session on the hosted MCP surface. Hosted HTTP now also supports TLS and client-certificate enforcement, the official SDK StreamableHTTP adapter is locally validated, CLI `mcp-http-soak` covers local hosted stateless/read-only soak behavior, and CLI `idp-jwks-live-check` now validates live JWKS/token compatibility without emitting the source IdP token or minted Mnemosyne sessions. This reduces the production auth gap but does not close it; operator-run validation against actual production credentials/endpoints, certificate issuance/renewal execution, and deployed secret distribution remain open.

Latest checkpoint: CLI `worker-run` now provides bounded worker supervision over runtime queue handlers with per-cycle heartbeats, persisted local queue progress, metrics output, idle exit controls, kind filtering, and fail-on-dead exit behavior. Tests cover multi-cycle calibration and observability jobs plus dead-job failure gating. This reduces the worker operations gap but does not close deployed process supervision, orchestration, restart policy, or production worker observability validation.

Latest checkpoint: CLI `tls-cert-check` now validates live TLS endpoint CA chains, hostname matching, TLS version floors, and certificate expiry thresholds. Tests cover a generated CA/server certificate against the real hosted TLS HTTP server plus fail-closed expiry threshold enforcement. This reduces the production certificate-chain/root validation gap but does not close certificate issuance, renewal execution, or deployed secret distribution.

Latest checkpoint: CLI `mcp-sse-soak` now validates legacy MCP SSE stream handshakes with bounded `text/event-stream` reads, expected `endpoint` event detection, endpoint-data presence, bearer/session header forwarding, and secret-redacted event previews. Tests cover a real local SSE endpoint plus fail-closed rejection when the hosted JSON-RPC HTTP server is probed as legacy SSE.

Latest checkpoint: CLI `idp-jwks-live-check` now provides a redacted live IdP/JWKS preflight that reuses the same verifier as `session-exchange` but never mints or prints a Mnemosyne session token. Reports include JWKS source/key count, token algorithm, hashed `kid`, redacted user hash, role, trust tier, policy presence, and fail-closed verification errors. Tests cover a local JWKS URL and invalid-token failure without leaking the IdP token, raw user id, session id, or raw `kid`.

Latest checkpoint: CLI `deployment-soak` now runs allowlisted deployment preflight manifests through shell-free subprocesses for `provider-check`, `idp-jwks-live-check`, `idp-authz-policy-rollout-check`, `tls-cert-check`, `tls-rotation-plan-check`, `mcp-http-soak`, `mcp-streamable-http-soak`, `mcp-sse-soak`, `worker-run`, and `ops-report`. It supports a narrow non-secret `global_args` allowlist for runtime placement flags that must precede child commands, parses child JSON reports, omits command arguments, reports required/optional failures, and fails closed on required check failures, timeouts, non-JSON output, disallowed commands, or disallowed global args. `ops-report` now emits a top-level tripwire `ok` gate, including dashboard mode. Tests cover real local hosted JSON-RPC HTTP, official SDK StreamableHTTP, and legacy SSE manifests without leaking configured tokens, IdP authz rollout orchestration, TLS rotation-plan orchestration, worker-run global queue placement, ops dashboard generation, disallowed secret global args, and disallowed-command rejection.

Latest checkpoint: Local and Postgres audit logs now expose source and trust-tier provenance for write paths. The audit contract records `actor`, `source`, `trust_tier`, `capability_tags`, and structured `diff` metadata for evidence appends, assertion upserts, preference writes, learning-store writes, and forget/delete operations. Postgres uses the existing audit columns for tier/tags and normalizes source on export from the audit diff. Shared local/Postgres contract coverage verifies the new audit shape.

Latest checkpoint: The consolidation replayer now implements blueprint-style priority replay using `importance*novelty*surprise*reward`. It accepts per-evidence factors from evidence metadata or payload replay-score overrides, orders the evidence stream before extraction/summarization, and emits per-CID score details in the replayer pass result. This replaces one label-only portion of the consolidation loop with concrete behavior while leaving fuller gist refresh, forgetter demotion, embedder, and user-model update work open.

Latest checkpoint: Consolidation `user_model_updater` now updates the latent user profile from prioritized evidence and extracted candidates, using the existing deterministic embedding and `UserModel` storage path. Runtime job handlers and CLI worker persistence now save user-model state alongside learning state. Fuller dual-model policy learning and production personalization validation remain open.

Latest checkpoint: CLI `mcp-streamable-http-soak` now validates the official MCP SDK StreamableHTTP transport with health transport checks plus repeated SDK `initialize`, `tools/list`, and read-only `tools/call` loops. The command supports bearer/session headers for deployed gateways, injects auth only into the read-only call contract when needed, redacts configured token values from output, and is allowlisted for `deployment-soak`.

Latest checkpoint: CLI `tls-rotation-plan-check` now validates current/candidate certificate files before a rotation by checking SAN hostname coverage on both certs, current/candidate validity windows, overlap days, optional issuer continuity, and hashed serial reporting. Tests cover generated current/candidate certificates, overlap and hostname success, and fail-closed candidate validity thresholds. This reduces the certificate lifecycle gap but does not issue, renew, distribute, or reload production certificate material.

Latest checkpoint: Media extraction jobs now add an explicit `media-derived-text` relation from the source asset evidence CID to the derived text evidence CID, with both CIDs as provenance. Local CLI and live Postgres tests verify the relation is exported, the derived text stays searchable, and forgetting the source asset erases derived evidence and expires the lineage relation. This moves Plan 06-04 toward a single associative substrate for multimodal projections, while broader multimodal extractor coverage remains open.

Latest checkpoint: CLI `provider-check` now validates command-backed session-secret custody from flags or a manifest `session_secret` provider block. The check loads the shell-free `get_session_secret` adapter, validates secret/keyring active-key semantics, proves a signed-session round trip, reports only redacted shape metadata, and fails closed on bad rotation state without leaking key material. This reduces the deployed secret-distribution gap but does not close production secret-manager rotation evidence capture.

Latest checkpoint: Live Postgres CLI coverage now exercises HTTP-compatible retrieval providers end to end. A local fake embedding provider captures through `--embedding-provider http`, persists provider-generated 1024-dim pgvector evidence embeddings, and is verified directly in Postgres under tenant RLS; `search`/`explain` report `http-embedding` and `http-reranker` adapter metadata; the HTTP reranker controls final hit ordering; and malformed zero-vector provider output exits nonzero without silently falling back to local hashing or inserting evidence. This reduces Plan 06-03 provider parity risk but does not close validation against real Qwen3/Gemini/Voyage/Cohere deployments or calibration datasets.

Latest checkpoint: Command-backed raw-media embeddings now participate in actual ingestion and retrieval, not only provider checks. `IngestionPipeline` can attach a media vector to externalized image/audio/video evidence without changing content-addressed object identity; LocalMemoryEngine uses stored media vectors for dense retrieval before OCR/transcript extraction; PostgresEngine writes the vector into `evidence.embedding` and exposes safe media-embedding metadata in hits; and live CLI/Postgres coverage verifies command media embedding storage plus raw image retrieval without derived text. This reduces Plan 06-04 multimodal retrieval risk but does not close real production extractor/embedder deployment validation.

Latest checkpoint: Parametric protected-suite orchestration now uses persisted runtime gate cases before falling back to synthetic smoke cases. CLI/MCP parametric evaluation reports protected-suite source, IDs, and tier counts; rollback persists the same suite snapshot, records rollback protected-case metrics, and sends protected cases to command-backed rollback providers. CLI `provider-check` now validates that rollback suite contract and reports the protected-suite snapshot. Focused parametric CLI/MCP/provider-check tests plus the full affected runtime/CLI test files pass. This reduces the local protected-suite and rollback-orchestration gap while deployed trainer, immutable-rail service, and production rollback validation remain open.

Latest checkpoint: Ops dashboard packaging now writes a local deployment bundle. `ops-report --dashboard-package-dir` emits `ops-dashboard.html`, `ops-report.json`, and `manifest.json`; the manifest records tenant, ok state, report counts, tripwires, and package file names. Deployment-soak coverage verifies the package output through an allowlisted `ops-report` check. This reduces the observability packaging gap while hosted dashboard deployment and production operations remain open.

Latest checkpoint: Deployment-soak can now preserve operator-run validation evidence. `deployment-soak --evidence-dir` writes `deployment-soak-report.json`, per-check JSON files under `checks/`, and a manifest that records source manifest, ok state, summary, and check file paths without storing raw command lines. The ops dashboard soak test verifies the evidence bundle alongside dashboard packaging. This strengthens production validation handoff while real hosted endpoint runs remain open.

Latest checkpoint: Consolidation now supports command-backed entity resolution. A configured command resolver receives tenant-scoped candidate payloads after extraction, must return explicit candidate-to-entity mappings, and fails closed on malformed, missing, duplicate, or unknown mappings; successful promotions persist resolver-provided entity keys into the entity registry. CLI runtime workers, `ingest --run-consolidation-once`, provider manifests, and `provider-check` can configure and validate the resolver boundary. Focused CLI tests cover runtime consolidation, manifest-backed provider checks, and malformed resolver failure. This reduces the richer production entity-resolution gap while real deployed resolver validation, incremental recompute, and richer model-backed extraction remain open.

Latest checkpoint: Runtime jobs now support affected-subgraph projection recompute. `projection_recompute` accepts changed evidence CIDs, expands through derived evidence/provenance edges, reports the affected assertion/preference/relation/entity projection IDs, and can queue consolidation only for surviving affected evidence. CLI `projection-recompute-enqueue` and `projection-recompute-once` expose the job, and `deployment-soak` can run the bounded once command as an allowlisted preflight. Focused CLI/runtime tests cover direct fact projection impact and media-derived evidence dependency expansion. This reduces the incremental recompute gap while broader production IVM/differential recompute remains open.

Latest checkpoint: Consolidation now supports command-backed candidate extraction and evidence summarization providers. The extractor contract accepts tenant/payload/evidence JSON and returns strict candidate rows; the summarizer contract accepts tenant/evidence JSON and returns a non-empty summary. Runtime workers, `ingest --run-consolidation-once`, provider manifests, and `provider-check` can configure both providers, and malformed provider output fails closed. Focused CLI tests cover model-style extraction of non-deterministic evidence, command summarizer pass details, manifest-backed provider checks, and bad-provider failure modes. This reduces the richer model-backed extraction/summarization gap while real deployed model/provider validation remains open.

Latest checkpoint: Protected regression suites now have a deployment check surface. `gate-suite-check` reports persisted suite shape, tier counts, protected-case IDs, and a stable fingerprint; it can include full cases for review/export and fails closed on insufficient protected cases or mismatched expected fingerprints. The command is allowlisted for `deployment-soak`, and CLI tests cover successful fingerprint acknowledgement plus mismatch failure. This reduces deployment-grade protected-suite management risk while production release-artifact validation remains open.

Latest checkpoint: Live Postgres parity coverage now exercises command-backed consolidation providers. A new live test runs `PostgresEngine` with command candidate extraction and command summarization, gates a non-deterministic evidence note through protected regression checks, and verifies exported assertions/entities reflect the provider-produced candidate. This broadens production adapter parity coverage when `MNEMOSYNE_POSTGRES_DSN` is configured.

Latest checkpoint: Live Postgres command-backed consolidation parity now includes entity resolution in the same provider path. The live test wires command candidate extraction, command entity resolution, and command summarization into `ConsolidationWorker`, then verifies protected promotion, resolver pass metadata, and the resolver-supplied entity canonical persisted in Postgres. This reduces the command-resolver adapter gap while real hosted resolver/model deployments still require operator-run evidence.

Latest checkpoint: Provider manifest deployment gates now include explicit lexical/graph retrieval backend validation. `provider-check` emits a `retrieval_backends` check with backend names plus local-fallback flags, and `forbid_local` rejects local lexical or graph backends alongside local embedding/reranker providers. Tests cover a production-style `paradedb-bm25` + `apache-age` manifest and fail-closed `local-bm25-lite` + `local-ppr` fallback rejection. This tightens Plan 06-03 production retrieval adapter handoff without requiring local ParadeDB/AGE deployment.

Latest checkpoint: DSN-backed full-suite verification uncovered and fixed an explicit-empty Postgres DSN edge case. CLI backend, runtime-state, and Postgres queue loading now use the parser-selected DSN directly, so `--postgres-dsn ""` fails even when `MNEMOSYNE_POSTGRES_DSN` is set. Focused CLI coverage sets an env DSN to lock the behavior, and the full suite passes against the local compose pgvector container.
