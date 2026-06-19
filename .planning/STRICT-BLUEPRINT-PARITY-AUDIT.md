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
- Verification currently passes with `.venv/bin/python -m compileall -q src tests` and `.venv/bin/python -m pytest -q` returning 63 passing tests plus 2 skipped live-DB tests.
- Live Docker/Postgres verification passes with `MNEMOSYNE_POSTGRES_DSN=postgresql://... .venv/bin/python -m pytest -q tests/test_postgres_engine_live.py` returning 2 passing tests against the compose database and verifying SQL FTS, pgvector assertion search, dense evidence fallback, recursive graph/PPR, branch/discard, forget, export, and CLI `--backend postgres`.
- Code-review blockers partially remediated after `REVIEW.md`: local graph tenant/branch leak fixed, MCP tool-result envelope added, Postgres public string-ID mapping added, Postgres high-level runtime methods added, and Postgres evidence conflict handling now restores durable fields.
- CLI-first runtime tool coverage added for profile context, graph neighbors, prefetch, trajectory logging, failure attribution, lesson induction/promotion, procedure induction/validation, and parametric proposal/evaluation. MCP dispatch mirrors the same operations.
- CLI backend selection added with `--backend local|postgres`, `--postgres-dsn`, and `MNEMOSYNE_POSTGRES_DSN`; the live smoke verifies capture/assert/relation/preference/search/deep-search/export/branch/discard through the Postgres CLI path.
- Fail-closed capability enforcement added in `MemoryTools` for preference writes, hard-instruction profile writes, and destructive forget operations. CLI and facade tests verify denied low-trust writes and allowed explicit/operator writes.

## Remaining Exact-Parity Gaps

| Area | Status | Required For 1:1 Blueprint Parity |
|---|---|---|
| Production Postgres retrieval | Partial | SQL FTS, pgvector assertion retrieval, deterministic evidence dense fallback, recursive graph/PPR, and live DB smoke are implemented. Remaining work: production embedding provider, ParadeDB BM25 where needed, AGE/specialist graph adapters where needed, external cross-encoder rerank, and full shared parity suite. |
| Tenant isolation and auth | Partial | Capability checks now protect preference, hard-instruction profile, and destructive forget writes. Remaining work: MCP/API auth, RLS or equivalent enforcement, complete write-path coverage, and production identity/session handling. |
| CLI/MCP runtime coverage | Partial | CLI-first coverage now exists for profile, graph, trajectory, lesson, procedure, prefetch, parametric flows, and local/Postgres backend selection; remaining work is official MCP SDK/server compliance, richer schemas, and server-backed stateless mode. |
| Consolidation role pipeline | Partial | Add queue-backed idle/server worker orchestration, extraction/summarization roles, entity resolution, incremental recompute, and protected-suite gate persistence. |
| Signed provenance | Partial | Replace deterministic digest verifier with real C2PA verifier integration and trust-policy mapping. |
| Multimodal retrieval | Partial | Add image/audio embedding/extraction and retrieval over externalized object payloads. |
| Privacy and erasure | Partial | Implement legal hard-delete/crypto-shred policy, derived-index recompute, data residency enforcement, and live erasure integration tests. |
| Observability dashboards | Partial | Export metrics for dashboards and add deployment smoke checks for retrieval channels, calibration, promotion/rollback, contradiction backlog, and diversity/proxy tripwires. |
| Parametric tier | Partial | Implement isolated LoRA/test-time-training artifact handling or a production-backed equivalent with shadow evaluation and rollback. |
| Live parity suite | Partial | Engine and CLI live Postgres smokes now pass in Docker; expand to the full shared contract suite with optional production adapters enabled. |

## Supersession Note

The earlier `.planning/v1.0-MILESTONE-AUDIT.md` remains useful as evidence that the local deterministic scaffold passed its original milestone suite. It is not sufficient evidence for the user's current exact 1:1 blueprint parity objective.

## Next Required Implementation Slice

1. Expand the live Docker/Postgres smoke into a full shared contract suite.
2. Wire production embedding and cross-encoder providers behind the existing Postgres retrieval adapter boundary.
3. Harden CLI/MCP schemas and add official MCP SDK/server integration tests.
4. Add auth/RLS and tenant-scoped branch enforcement before making any production multi-tenant claim.
