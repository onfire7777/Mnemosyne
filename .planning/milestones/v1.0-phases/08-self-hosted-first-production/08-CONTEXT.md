# Phase 08 — Self-Hosted-First Production Architecture (CONTEXT)

**Created:** 2026-06-30. **Status:** production-attested on 2026-07-07 by
`capture-bc10`; retained as the Phase 8 planning context.
**Architecture spec:** [`docs/SELF-HOSTED-PRODUCTION-ARCHITECTURE.md`](../../../docs/SELF-HOSTED-PRODUCTION-ARCHITECTURE.md).
**Relationship to Phase 06:** this phase *reuses* the Phase-06 Tier-B machinery (`infra/` providers
stack, `production_parity.py`, `*-ops-check`/`release-audit`, custody packets). It does **not** fork a
new evidence path; it makes the **self-hosted stack the official `production` profile** and hardens it.

## Why this phase exists

The preferred deployment target is **self-hosted / local-first** (no GPU, runs
lean on a ~16 GB box). The original planning assumption was that B9 would need
a cloud/GPU extension; ADR-002's amended CPU-parametric path superseded that
assumption, and the retained `capture-bc10` evidence closed B1-B10 without
weakening gates. No gate is weakened; the seven §31 rails and six §16 SLOs are
preserved on the real path.

## Reconciled architecture decisions (audited; do NOT regress to the phantom stack)

- **Retrieval: KEEP native Postgres 16** (FTS + pgvector HNSW + `postgres-recursive-ppr`). SLO-proven
  (recall 0.977 / nDCG 0.983). Do **not** swap in an external vector DB (fractures the unified store).
- **Graph: keep native recursive-PPR.** Do not replace the SLO-proven path with
  Apache AGE as the algorithm source. If a future audit demands AGE as a
  deployed graph surface, satisfy it as evidence-compatible sidecar or change
  the audit through an explicit ADR.
- **Lexical: native FTS by default**; add ParadeDB `pg_search` **only if** the strict audit requires a
  distinct BM25 backend (stays in-Postgres — no fracture).
- **Identity: KEEP Keycloak 25.0**; **KMS: KEEP Vault 1.17 transit** (OpenBao optional drop-in). Both
  already wired in `infra/docker-compose.providers.yml`.
- **Embeddings: upgrade to `snowflake-arctic-embed-l-v2.0`** (1024-dim) via TEI/Infinity →
  `HttpEmbeddingProvider`; gate behind a **measured CPU P95** check.
- **Reranker:** real cross-encoder via `HttpReranker` — bake off `bge-reranker-v2-m3` vs
  `gte-reranker-modernbert-base` on the gold set.
- **Consolidation roles: default `Qwen3-4B` (llama.cpp)**; command-backed frontier model as the
  documented no-compromise option.
- **B9 / FR-21 (parametric): resolved for self-hosted.** ADR-002's amended
  CPU-parametric path is the accepted Tier-B evidence route; B9 is Done only
  because `capture-bc10` passed the unchanged production release-audit and
  offline custody gates.

## Constraints / guardrails

No GPU for the self-hosted baseline; lean ~16 GB; preserve all gates + §31
rails + §16 SLOs; never `git add -A`; respect the lock table (frozen
`models.py`/`engine.py`/etc.). This phase does not override the Tier-B
completion standard; it records the self-hosted path that later passed through
`capture-bc10`.
