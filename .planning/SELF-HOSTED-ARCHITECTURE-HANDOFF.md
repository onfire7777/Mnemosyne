# Handoff — Self-Hosted-First Production Architecture (for the Codex/GSD loop)

**Date:** 2026-06-30. **Author:** assistant (out-of-loop session), additive-only, no frozen source touched.

## What landed (new files, safe to ingest)
- `docs/SELF-HOSTED-PRODUCTION-ARCHITECTURE.md` — the full architecture + security spec.
- `.planning/phases/08-self-hosted-first-production/08-CONTEXT.md` + `08-01-PLAN.md` — the GSD phase.
- `.planning/phases/08-self-hosted-first-production/08-HANDOFF-INDEX.md` — the current read-first handoff.
- `.planning/phases/08-self-hosted-first-production/08-SECURITY-FINDINGS.md` — adversarial security findings and pre-capture must-dos.

## Decision in one line
Make a **self-hosted stack the preferred production baseline** (cloud/GPU =
values-only extension for larger providers), **reusing** the existing Tier-B
machinery. This now closes B1-B10 with real retained evidence, including B9 via
ADR-002's amended CPU-parametric path. No gate weakened; §31 rails + §16 SLOs
preserved.

## Ledger status
- **`.planning/ROADMAP.md`** now includes Phase 8 as a subordinate production-evidence phase.
- **`.planning/MILESTONES.md`** now includes the self-hosted-first production milestone.
- **`.planning/STATE.md`** records Phase 8 checkpoints and the 2026-07-07 Tier-B attestation.

## Stale-doc prune result
Completed 2026-07-03: the stale files named below were moved to
`docs/_archive/2026-07-03/` for audit/history only:
`CODEX-RECONCILIATION.md`, `BLUEPRINT-COMPLETION-PLAN.md`,
`STATE-OF-COMPLETION.md`, `TIER-B-LOCAL-REAL-SERVICE-EVIDENCE-2026-06-24.md`,
`INGEST-CONFLICTS.md`, and `REVIEW.md`.

Keep (correctly quarantined): `docs/blueprint/earlier-versions/*`, `.planning/v1.0-MILESTONE-AUDIT.md`,
`.planning/BLUEPRINT-PARITY-MATRIX.md` (already banners historical). Do **not** merge the two ROADMAPs —
`.planning/ROADMAP.md` (machine ledger) and `docs/ROADMAP-TO-100.md` (narrative) are intentionally split.

## Hard correction for future planning (do not regress)
Earlier research proposed a greenfield lean stack (ParadeDB+AGE+Dex+OpenBao+Garage). The adversarial
quality audit + code grep proved that diverges from reality and would
**degrade quality**: the deployed engine is native Postgres FTS + HNSW +
`postgres-recursive-ppr` (SLO-proven), identity is Keycloak, KMS is Vault.
**Keep those.** Do not replace native recursive-PPR with Apache AGE as the
algorithm source; if the active strict audit still requires AGE evidence,
satisfy it as an evidence-compatible sidecar or change the audit by explicit
ADR before claiming parity. Upgrades that *raise* quality:
arctic-embed-l-v2.0 embeddings, a real cross-encoder reranker,
Qwen3-4B/frontier consolidation.
