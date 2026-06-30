# Phase 08 — Self-Hosted-First Production Architecture (CONTEXT)

**Created:** 2026-06-30. **Status:** proposed and subordinate to the active
Tier-B production-evidence contract.
**Architecture spec:** [`docs/SELF-HOSTED-PRODUCTION-ARCHITECTURE.md`](../../../docs/SELF-HOSTED-PRODUCTION-ARCHITECTURE.md).
**Relationship to Phase 06:** this phase *reuses* the Phase-06 Tier-B machinery (`infra/` providers
stack, `production_parity.py`, `*-ops-check`/`release-audit`, custody packets). It does **not** fork a
new evidence path; it makes the **self-hosted stack the official `production` profile** and hardens it.

## Why this phase exists

The preferred deployment target is **self-hosted / local-first** (no GPU, runs
lean on a ~16 GB box), but the active strict-parity contract still requires B9
operator evidence before 100%. Reaching a trustworthy release therefore means:
(1) completing + hardening the already-wired self-hosted provider stack for the
rows it can honestly satisfy, (2) using a values-only cloud/GPU extension for
B9 or an explicit future ADR if the audit changes, and (3) preserving
fail-closed production defaults. No gate is weakened; the seven §31 rails and
six §16 SLOs are preserved on the real path.

## Reconciled architecture decisions (audited; do NOT regress to the phantom stack)

- **Retrieval: KEEP native Postgres 16** (FTS + pgvector HNSW + `postgres-recursive-ppr`). SLO-proven
  (recall 0.977 / nDCG 0.983). Do **not** swap in an external vector DB (fractures the unified store).
- **Graph: keep native recursive-PPR.** Do not replace the SLO-proven path with
  Apache AGE as the algorithm source. If the strict row still requires AGE as a
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
- **B9 / FR-21 (parametric, GPU): still required for strict 100%.** The no-GPU
  self-hosted profile cannot satisfy it by declaration. Use the cloud/GPU
  values-only profile for evidence, or leave B9 Partial until an explicit ADR
  changes the strict audit.

## Constraints / guardrails

No GPU for the self-hosted baseline; lean ~16 GB; preserve all gates + §31
rails + §16 SLOs; never `git add -A`; respect the lock table (frozen
`models.py`/`engine.py`/etc.); this phase is docs/planning + additive `infra/`
only unless a real capture failure proves a source defect. It does not override
the active Tier-B completion standard.
