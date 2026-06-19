# Strict Blueprint Parity Audit

**Date:** 2026-06-19  
**Blueprint:** `/Users/admin/Desktop/Mnemosyne/Mnemosyne-v2-Build-Blueprint.md`  
**Status:** gaps remain; exact 1:1 parity is not complete.

## Current Verified Coverage

- Local deterministic engine covers evidence deduplication, byte recall, bitemporal assertions, as-of queries, branch/merge/discard, hybrid local retrieval, provenance-bearing hits, correction, export, forget propagation, capability checks, consolidation gate, learning loop, lifecycle demotion, and shadow self-optimization.
- Runtime surfaces added after strict audit:
  - `src/mnemosyne/mcp_server.py` for stdio JSON-RPC `initialize`, `tools/list`, and `tools/call`.
  - `src/mnemosyne/postgres_engine.py` for core PostgreSQL append/upsert/search/as-of/branch operations against `sql/schema.sql`, including SQL FTS, pgvector assertion search, deterministic evidence dense fallback, and recursive graph/PPR.
  - `src/mnemosyne/retrieval.py` for embedding and reranker adapter boundaries plus local semantic entropy.
  - `src/mnemosyne/storage.py`, `src/mnemosyne/provenance.py`, `src/mnemosyne/ingestion.py`, and `src/mnemosyne/queue.py` for object storage, signed-provenance decisions, multimodal ingestion, and local queue semantics.
  - `src/mnemosyne/prefetch.py` and `src/mnemosyne/parametric.py` for FR-18 and FR-21 local boundaries.
- Verification currently passes with `.venv/bin/python -m compileall -q src tests` and `.venv/bin/python -m pytest -q` returning 82 passing tests plus 4 skipped live-DB tests.
- Fresh-schema Docker/Postgres verification passes with `MNEMOSYNE_POSTGRES_DSN=postgresql://... .venv/bin/python -m pytest -q tests/test_postgres_engine_live.py` returning 4 passing tests against the compose database and verifying tenant RLS, SQL FTS, pgvector assertion search, dense evidence fallback, recursive graph/PPR, branch/discard, tombstone and hard-delete forget modes, export, HTTP-configurable retrieval adapter wiring, CLI `--backend postgres`, CLI file ingestion through the C2PA verifier adapter, and gated consolidation promotion on Postgres.
- Code-review blockers partially remediated after `REVIEW.md`: local graph tenant/branch leak fixed, MCP tool-result envelope added, Postgres public string-ID mapping added, Postgres high-level runtime methods added, and Postgres evidence conflict handling now restores durable fields.
- CLI-first runtime tool coverage added for profile context, graph neighbors, prefetch, trajectory logging, failure attribution, lesson induction/promotion, procedure induction/validation, and parametric proposal/evaluation. MCP dispatch mirrors the same operations.
- CLI backend selection added with `--backend local|postgres`, `--postgres-dsn`, and `MNEMOSYNE_POSTGRES_DSN`; the live smoke verifies capture/assert/relation/preference/search/deep-search/export/branch/discard through the Postgres CLI path.
- Fail-closed capability enforcement added in `MemoryTools` for preference writes, hard-instruction profile writes, and destructive forget operations. CLI and facade tests verify denied low-trust writes and allowed explicit/operator writes.
- Tenant RLS added to `sql/schema.sql` for tenant-owned tables. `PostgresEngine` sets `mnemosyne.tenant_id` before tenant-scoped SQL and requires tenant-scoped branch/merge/discard operations.
- Explicit erasure modes added to local/Postgres forget paths and CLI: `tombstone_recompute` preserves the audit/deletion path while clearing evidence, and `hard_delete_legal` removes the evidence row while propagating derived assertion retraction/trimming.
- HTTP-compatible embedding and reranker adapters added, with CLI/env wiring for Postgres retrieval (`--embedding-provider`, `--embedding-url`, `--reranker-provider`, `--reranker-url`, model, API-key, dimension, and timeout controls). Local deterministic providers remain the default for offline verification.
- CLI-first signed-provenance ingestion added with `ingest --file`, modality/media-type controls, signed-provenance JSON/file inputs, `--c2pa-tool`, trusted issuer mapping, fail-closed verifier errors, and local/Postgres tests. Quarantined evidence is now excluded from default retrieval unless the caller explicitly opts into `include_quarantined`.
- Trust-tier semantics now match the blueprint direction: tier `0` is direct-user/highest trust and tier `5` is untrusted external. Retrieval/write gates, confidence weighting, provenance deltas, model defaults, SQL defaults, CLI defaults, and local/Postgres tests were migrated to that scale.
- Ingest classification now identifies actor/source trust, applies capability/taint tags, detects email/phone/SSN-style PII, raises sensitivity/access policy metadata, marks untrusted imperative content as data-only without instruction authority, and enqueues an ordered persisted local consolidation job after new evidence is appended. The worker now records structured pass results, extracts simple direct-user fact candidates, promotes them only through the gate, and refuses data-only untrusted fact-shaped evidence.
- The local queue now supports drain semantics and typed runtime handlers for consolidation, calibration, lifecycle sweep, eval suite, and observability snapshot jobs, with CLI `queue-enqueue`, `queue-drain`, `queue-snapshot`, and `consolidate-once` surfaces.
- Promotion gates now route branch, merge, and discard through tenant-aware engine calls when available, with live Postgres coverage for gated direct-user fact promotion.

## Remaining Exact-Parity Gaps

| Area | Status | Required For 1:1 Blueprint Parity |
|---|---|---|
| Production Postgres retrieval | Partial | SQL FTS, pgvector assertion retrieval, deterministic evidence dense fallback, recursive graph/PPR, HTTP-compatible embedding/reranker adapters, and live DB smoke are implemented. Remaining work: validate provider deployments, add ParadeDB BM25 where needed, AGE/specialist graph adapters where needed, and full shared parity suite. |
| Tenant isolation and auth | Partial | Capability checks now protect preference, hard-instruction profile, and destructive forget writes; Postgres tenant RLS is implemented and live-smoked; MCP `tools/call` has opt-in token enforcement. Trust-tier direction now matches the blueprint scale. Remaining work: complete write-path coverage, production identity/session handling, and deployment-grade auth integration. |
| CLI/MCP runtime coverage | Partial | CLI-first coverage now exists for profile, graph, trajectory, lesson, procedure, prefetch, parametric flows, local/Postgres backend selection, and blueprint-facing ABI aliases; MCP tools now expose signature-derived JSON schemas and runtime JSON-RPC tests. Remaining work is official MCP SDK/server compliance and server-backed stateless production mode. |
| Consolidation role pipeline | Partial | Ingest now queues ordered persisted local consolidation pass payloads; the CLI can inspect/enqueue/drain local jobs; the worker records structured pass results and can promote a simple direct-user fact candidate through the gate while refusing data-only untrusted facts; local handlers exist for calibration, lifecycle, eval, and observability jobs. Remaining work includes production PGMQ/Redis-style idle/server worker orchestration, richer extraction/summarization roles, entity resolution, incremental recompute, and protected-suite gate persistence. |
| Signed provenance | Partial | CLI and ingestion can invoke a `c2patool`-style verifier, map trusted issuers, fail closed on verifier errors, and hide quarantined evidence from default retrieval. Remaining work: production certificate-chain/trust-policy validation, report-to-asset binding assurance, and full capability/taint propagation from provenance decisions. |
| Multimodal retrieval | Partial | Add image/audio embedding/extraction and retrieval over externalized object payloads. |
| Privacy and erasure | Partial | Tombstone recompute and legal hard-delete modes now exist locally and in Postgres with live CLI coverage. Remaining work: crypto-shred/key-management policy, broader derived-index recompute, and data residency enforcement. |
| Observability dashboards | Partial | Export metrics for dashboards and add deployment smoke checks for retrieval channels, calibration, promotion/rollback, contradiction backlog, and diversity/proxy tripwires. |
| Parametric tier | Partial | Implement isolated LoRA/test-time-training artifact handling or a production-backed equivalent with shadow evaluation and rollback. |
| Live parity suite | Partial | Engine and CLI live Postgres smokes now pass in Docker; the live suite now covers bitemporal supersession, tenant isolation, branch merge retrieval, C2PA ingest, CLI backend use, and gated consolidation. Remaining work: expand to the full shared contract suite with optional production adapters enabled. |

## Supersession Note

The earlier `.planning/v1.0-MILESTONE-AUDIT.md` remains useful as evidence that the local deterministic scaffold passed its original milestone suite. It is not sufficient evidence for the user's current exact 1:1 blueprint parity objective.

## Next Required Implementation Slice

1. Continue expanding the live Docker/Postgres smoke into the full shared contract suite.
2. Wire production embedding and cross-encoder providers behind the existing Postgres retrieval adapter boundary.
3. Add official MCP SDK/server integration tests and production stateless-server mode.
4. Complete write-path auth coverage and production identity/session handling before making any production multi-tenant claim.
