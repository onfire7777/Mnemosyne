# ADR-003: Postgres vector partition coverage and null fallback indexing

**Date:** 2026-07-09
**Status:** Accepted
**Decider:** Performance/refactoring continuation
**Relates to:** `sql/schema.sql`, `src/mnemosyne/postgres_engine.py`, `docs/blueprint/Mnemosyne-Performance-and-Refactoring-Blueprint.md` section 7.4.

## Context

Postgres stores vectors only for rows whose `embedding_partition` is `public`
or `private`. Rows in the `none` partition are deliberately non-embeddable:
write paths set their vector to `NULL`, the schema reconciler clears any legacy
vector that remains, and read paths must not let those rows influence dense
ranking.

The performance blueprint previously described the `none` gap as missing HNSW
coverage. That was imprecise. A `none` HNSW index would index no usable vectors
and would not help the dense fallback path. The concrete waste was that the
fallback query selected `embedding IS NULL` rows, including `none` rows, and
then skipped them after access-policy checks.

## Decision

Keep HNSW indexes only for vector-bearing `public` and `private` partitions.
Cover `none` rows with ordinary btree partial indexes for lifecycle/audit scans.
Exclude `embedding_partition = 'none'` at the SQL boundary for the null
embedding fallback. Add one partial btree index,
`evidence_null_embedding_fallback_idx`, over `(tenant_id, branch,
created_at DESC, cid)` for `embedding IS NULL AND embedding_partition <> 'none'
AND erased = false`.

The Postgres server-tuning profile is versioned in
`infra/postgres/postgresql-perf.conf`, but it is not silently applied by source
changes. Operators must capture before/after evidence before using those values
in the live stack.

## Consequences

- `none` rows stay retrievable through lexical/graph/textual channels but do
  not enter dense fallback candidate generation.
- Legacy `public` or `private` rows with missing vectors remain covered by the
  bounded dense fallback and can still be backfilled.
- Future `halfvec` or `pgvectorscale` work should treat `none` as a
  no-vector partition, not as a third ANN index.
- Live performance claims still require operator evidence; this ADR is a
  source-level indexing and strategy decision only.
