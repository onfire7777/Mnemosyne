# Strict Blueprint Parity Audit

**Date:** 2026-06-19  
**Blueprint:** `/Users/admin/Desktop/Mnemosyne/Mnemosyne-v2-Build-Blueprint.md`  
**Status:** gaps remain; exact 1:1 parity is not complete.

## Current Verified Coverage

- Local deterministic engine covers evidence deduplication, byte recall, bitemporal assertions, as-of queries, branch/merge/discard, hybrid local retrieval, provenance-bearing hits, correction, export, forget propagation, capability checks, consolidation gate, learning loop, lifecycle demotion, and shadow self-optimization.
- Runtime surfaces added after strict audit:
  - `src/mnemosyne/mcp_server.py` for stdio JSON-RPC `initialize`, `tools/list`, and `tools/call`.
  - `src/mnemosyne/postgres_engine.py` for core PostgreSQL append/upsert/search/as-of/branch stubs against `sql/schema.sql`.
  - `src/mnemosyne/retrieval.py` for embedding and reranker adapter boundaries plus local semantic entropy.
  - `src/mnemosyne/storage.py`, `src/mnemosyne/provenance.py`, `src/mnemosyne/ingestion.py`, and `src/mnemosyne/queue.py` for object storage, signed-provenance decisions, multimodal ingestion, and local queue semantics.
  - `src/mnemosyne/prefetch.py` and `src/mnemosyne/parametric.py` for FR-18 and FR-21 local boundaries.
- Verification currently passes with `.venv/bin/python -m compileall -q src tests` and `.venv/bin/python -m pytest -q` returning 54 passing tests plus 1 skipped live-DB test.
- Live Docker/Postgres verification passes with `MNEMOSYNE_POSTGRES_DSN=postgresql://... .venv/bin/python -m pytest -q tests/test_postgres_engine_live.py` returning 1 passing test against the compose database.
- Code-review blockers partially remediated after `REVIEW.md`: local graph tenant/branch leak fixed, MCP tool-result envelope added, Postgres public string-ID mapping added, Postgres high-level runtime methods added, and Postgres evidence conflict handling now restores durable fields.

## Remaining Exact-Parity Gaps

| Area | Status | Required For 1:1 Blueprint Parity |
|---|---|---|
| Production Postgres retrieval | Partial | Wire real pgvector embeddings, Postgres FTS/ParadeDB BM25, AGE/recursive graph retrieval, cross-encoder rerank, and live DB-backed parity tests. |
| Tenant isolation and auth | Partial | Add MCP/API auth, tenant-scoped branch APIs, RLS or equivalent enforcement, and capability checks on every write path. |
| Official MCP compatibility | Partial | Replace the minimal stdio shim with fully typed MCP SDK/server compliance, richer tool schemas, server-backed stateless mode, and integration tests against an MCP client. |
| Consolidation role pipeline | Partial | Add queue-backed idle/server worker orchestration, extraction/summarization roles, entity resolution, incremental recompute, and protected-suite gate persistence. |
| Signed provenance | Partial | Replace deterministic digest verifier with real C2PA verifier integration and trust-policy mapping. |
| Multimodal retrieval | Partial | Add image/audio embedding/extraction and retrieval over externalized object payloads. |
| Privacy and erasure | Partial | Implement legal hard-delete/crypto-shred policy, derived-index recompute, data residency enforcement, and live erasure integration tests. |
| Observability dashboards | Partial | Export metrics for dashboards and add deployment smoke checks for retrieval channels, calibration, promotion/rollback, contradiction backlog, and diversity/proxy tripwires. |
| Parametric tier | Partial | Implement isolated LoRA/test-time-training artifact handling or a production-backed equivalent with shadow evaluation and rollback. |
| Live parity suite | Partial | One live PostgresEngine smoke now passes in Docker; expand to the full shared contract suite with optional production adapters enabled. |

## Supersession Note

The earlier `.planning/v1.0-MILESTONE-AUDIT.md` remains useful as evidence that the local deterministic scaffold passed its original milestone suite. It is not sufficient evidence for the user's current exact 1:1 blueprint parity objective.

## Next Required Implementation Slice

1. Expand the live Docker/Postgres smoke into a full shared contract suite.
2. Replace Postgres fallback retrieval with real SQL vector/lexical paths and explicit graph adapter hooks.
3. Complete MCP/CLI coverage for graph, trajectory, lesson, procedure, and parametric operations.
4. Add auth/RLS and tenant-scoped branch enforcement before making any production multi-tenant claim.
