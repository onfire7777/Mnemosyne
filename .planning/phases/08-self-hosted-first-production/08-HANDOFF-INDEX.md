# Phase 08 — Master Handoff Index (read this first)

**For:** the autonomous Codex/GSD loop (and any agent picking this up cold). **Date:** 2026-06-30.
**Status:** complete planning + architecture + additive infra scaffold delivered by an out-of-loop
session. Live bring-up + evidence capture remain. **Defers to:** the blueprint, live repo evidence, the
strict-audit ledger, and the ACTIVE-GOAL-OPERATING-CONTRACT source-of-truth order.

## One-paragraph context
Goal: make the **self-hosted stack the preferred `production` profile** (cloud/GPU = values-only
extension), reusing the existing Tier-B machinery, hardened to be genuinely secure — and reach a
*trustworthy* completion. The self-hosted no-GPU profile honestly closes **B1–B8 + B10 (9/10)** on real
evidence. **B9/FR-21 (GPU LoRA) is NOT satisfiable no-GPU and does NOT reach strict v1.0 100% by
declaration** — it needs real GPU evidence via the `cloud` profile or an explicit ADR. No gate weakened;
§31 rails + §16 SLOs preserved.

## Complete artifact inventory (everything this work produced)
| Artifact | Purpose |
|---|---|
| `docs/SELF-HOSTED-PRODUCTION-ARCHITECTURE.md` | Full architecture + security spec + per-row mapping + no-compromise levers |
| `.planning/phases/08-self-hosted-first-production/08-CONTEXT.md` | Why this phase; reconciled decisions; guardrails |
| `…/08-01-PLAN.md` | Executable task groups 8.1–8.6 + success criteria |
| `…/08-SECURITY-FINDINGS.md` | **Full** security capture: 2 headline findings, 16 must-dos, 11 residual risks, layered controls |
| `…/08-HANDOFF-INDEX.md` | This index |
| `.planning/SELF-HOSTED-ARCHITECTURE-HANDOFF.md` | Recommended ledger snippets + prune list |
| `infra/docker-compose.prod.yml` | Hardened 11-service stack; Caddy sole ingress; privilege-split app |
| `infra/profiles/{self-hosted,cloud}.env` + `README.md` | Values-only two-profile model |
| `infra/caddy/Caddyfile` | Sole ingress; step-ca ACME; security headers |
| `infra/postgres/roles.sql` | Least-privilege roles under FORCE RLS |
| `infra/prod/{bootstrap.sh,README.md}` | Turnkey first-run + run guide |

## Authoritative decisions (do NOT regress)
- **KEEP native Postgres 16** (FTS + pgvector HNSW + `postgres-recursive-ppr`) — SLO-proven 0.977/0.983. No external vector DB (fractures the store).
- **Do NOT adopt Apache AGE** as the PPR algorithm source (no built-in PageRank; native recursive-PPR is superior). AGE only as evidence-compatible sidecar if the strict audit insists, via ADR.
- **KEEP Keycloak 25.0** (OIDC) + **Vault 1.17 transit** (KMS) — already wired. OpenBao optional drop-in.
- **Lexical:** native FTS by default; ParadeDB `pg_search` (in-Postgres) only if the strict audit demands a distinct BM25 backend.
- **Upgrades (raise quality, in-envelope):** embeddings → `snowflake-arctic-embed-l-v2.0` (1024-dim) **behind a measured CPU P95 gate** (the latency claim is unverified — bench on the target host); reranker → real cross-encoder via `HttpReranker`, bake off `bge-reranker-v2-m3` vs `gte-reranker-modernbert-base`; consolidation roles → `Qwen3-4B` default + command-backed frontier as the quality ceiling.
- **Two profiles** differ by VALUES only; `forbid_local:true` in both; no gate weakened anywhere.
- **B9/strict-100%:** cloud/GPU evidence or explicit ADR — never "DEFERRED-BY-DESIGN" under the current v1.0 contract.

## Provenance (so the depth is traceable)
6 parallel architecture research streams (retrieval, model-serving, identity/secrets/TLS,
object-store/obs/proxy, profile design, docs/GSD audit) + a 15-agent adversarial **security** workflow +
a 15-agent **quality** audit (each finding red-teamed/challenged) + direct code-grep verification that
corrected an earlier "phantom stack" (ParadeDB/AGE/Dex/OpenBao) back to the deployed reality.

## Ordered action checklist for the loop
1. **Maintain the ledger**: Phase 8 is recorded in `.planning/ROADMAP.md`, `.planning/MILESTONES.md`, and `.planning/STATE.md`; keep those entries subordinate to `.planning/ACTIVE-GOAL-OPERATING-CONTRACT.md` and do not mark any Tier-B row Done without retained production evidence.
2. **Prune stale docs** (archive, don't delete): done 2026-07-03. The named stale files now live under `docs/_archive/2026-07-03/` for audit/history only. (Keep the two ROADMAPs split.)
3. **Implement the 16 security must-dos** (`08-SECURITY-FINDINGS.md`) — start with #9 (policy-as-code CI) and #2/#3 (fail-closed auth + RLS roles). These are prerequisites to a *trustworthy* capture.
4. **Execute Phase 8.1–8.6** (`08-01-PLAN.md`): profiles + prod compose → models/retrieval wiring → identity/secrets/TLS → object-store/obs → security → capture.
5. **Capture B1–B8 + B10** via `infra/PRODUCTION-EVIDENCE.md` (render → preflight → capture → verify → release-audit); flip each row Partial→Done on **real** evidence.
6. **B9/FR-21:** route to the `cloud` profile for real GPU evidence, OR leave Partial pending an explicit ADR. Do not fake it.
7. **Tier C:** re-prove the 6 §16 SLOs on the real path; record a real LongMemEval R@5; update the README badge for the official profile.

## Open operator decisions
- Consolidation default: local `Qwen3-4B` (purity) vs command-backed frontier (quality) — one env value.
- Lexical: native FTS vs add ParadeDB `pg_search` — decide after the strict audit confirms the non-local lexical requirement.
- Object store: SeaweedFS (native SSE) vs MinIO (broader S3, needs KES).

## Status & honesty boundary
The infra is a **complete coherent scaffold**, not battle-tested: first `bootstrap.sh` + `up` needs a
validation pass (Vault init/unseal ordering, Keycloak realm, step-ca trust, image digest pins). Do not
mark anything Done until its `*-ops-check` passes on real infra — consistent with §38 "measure before
claiming."

## Coordination
Additive `infra/` + docs/planning only; **no frozen source** (`models.py`/`engine.py`/`runtime_state.py`/
`jobs.py`/`queue.py`/`observability.py`/`pyproject.toml`/`uv.lock`); **never `git add -A`** (stage explicit
paths); only the Sync lane touches `origin/main`; full suite green every merge. Touch `src/` only where a
real capture failure proves a defect, behind a forcing-function test.
