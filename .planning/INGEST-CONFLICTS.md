# Ingest Conflicts

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
| Dense retrieval | Real embedding model | Deterministic hashing vector | Hashing vector locally; adapter remains required for production quality |
| Graph | AGE or specialist graph | Local relation PPR | Local relation PPR for contract tests; production adapter later |

## Unresolved Blockers

- PostgreSQL extension compatibility and production DDL execution are not yet verified.
- Full conformal calibration and protected-suite thresholds are not yet implemented.
- Full six-category user model and latent advisory profile are not yet implemented.
- Full procedural learning and counterfactual replay are not yet implemented.
- Full self-model store and diversity/proxy-divergence tripwires are not yet implemented.

