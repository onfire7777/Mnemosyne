# Ingest Conflicts

> Historical snapshot from 2026-06-21. Retained for lineage only; do not use as
> the active completion checklist. Current status lives in
> `docs/ROADMAP-TO-100.md`, `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md`, and
> `docs/superpowers/plans/2026-07-01-native-acceleration-program.md`.

## Auto-Resolved

| Conflict | Resolution |
|----------|------------|
| V1 design versus v2 blueprint | V2 controls. V1 is used only for lineage because README states it is superseded. |
| Graph required by FR-3 versus graph/PPR marked Phase 2 and open latency risk | Keep graph interface and local deterministic channel now; require production PPR benchmark before fast-path use. |
| Lossless evidence versus forget/erasure | Treat lossless guarantee as scoped to non-erased evidence; forget tombstones verbatim content and propagates provenance changes. |
| Self-improvement requirement versus safety risk | Keep policy learning shadow-first and promote only through protected regression and branch rollback. |

## Competing Variants

| Area | Variant A | Variant B | Current Choice |
|------|-----------|-----------|----------------|
| Local store | Embedded Postgres/PGlite | Deterministic JSON-backed local engine | JSON-backed engine for immediate verification; Postgres schema remains canonical |
| Dense retrieval | Real embedding model | Deterministic hashing vector + provider gate | Hashing vector remains the local deterministic baseline; `provider-check`, `hosted-llm-check`, and `release-audit` now gate production provider evidence. |
| Graph | AGE or specialist graph | Local relation PPR + backend manifest gate | Local relation PPR covers deterministic contract tests; production manifests must name non-local graph backends before release evidence is accepted. |

## Remaining Operator Evidence

- Real production provider, graph-backend, and credential/endpoint evidence must still be captured through `deployment-soak` and `release-audit` before any production claim is accepted.
- PostgreSQL extension compatibility is verified in the compose/live suite; production DDL execution still requires operator-run evidence against the target deployment.
- Conformal calibration and protected-suite thresholds are implemented and gated through `calibration-tune`, `gate-suite-check`, and `release-audit`; production datasets still need operator-supplied evidence.
- The six-category user model, latent advisory profile, procedural learning, rollback, self-model store, contextual bandit selection, and proxy-divergence tripwires are implemented locally and in Postgres-backed paths; release evidence is now gated by `policy-ops-check` and related production profiles.
