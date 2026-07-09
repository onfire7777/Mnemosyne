---
phase: 09-performance-and-refactoring-continuation
plan: 05
status: complete-local-gated
completed: 2026-07-09
---

# 09-05 Summary: Postgres Partition Coverage and Tuning Profile

## Outcome

The source-owned part of Phase 09 Task 6 is complete locally. Postgres now
models `embedding_partition='none'` as an explicit no-vector partition with
btree coverage, not dead HNSW coverage, and the dense fallback no longer pulls
`none` rows into the Python embed loop. A conservative Postgres tuning profile
is versioned for a future operator-evidence run.

## Implementation Notes

- `sql/schema.sql` adds:
  - `evidence_embedding_none_btree`.
  - `assertions_embedding_none_btree`.
  - `evidence_null_embedding_fallback_idx` for embeddable legacy null rows.
- `PostgresEngine._ensure_evidence_vector_schema` reconciles the same indexes
  with the existing privilege-tolerant optional-DDL path.
- `PostgresEngine.vector_search` adds
  `AND embedding_partition <> 'none'` to the null-embedding fallback query.
- `infra/postgres/postgresql-perf.conf` records source-owned candidate values
  for the resized production profile without applying them silently.
- `docs/adr/ADR-003-postgres-vector-partition-coverage.md` records the
  no-HNSW decision for `none` rows and the operator-evidence boundary.

## Verification

- `uv run pytest tests/test_nfrs_and_schema.py::test_canonical_schema_partitions_sensitive_vector_indexes tests/test_nfrs_and_schema.py::test_postgres_perf_tuning_file_is_versioned_but_evidence_gated tests/test_postgres_perf_lanes.py::test_vector_schema_fully_present_issues_no_ddl_but_runs_backfills tests/test_postgres_perf_lanes.py::test_vector_schema_creates_btree_none_and_null_fallback_indexes tests/test_postgres_perf_lanes.py::test_vector_schema_missing_index_privilege_denied_warns_only tests/test_postgres_perf_lanes.py::test_postgres_null_embedding_fallback_is_capped_and_observable -q`
  passed.

## Remaining Work

Live Postgres tuning application, before/after benchmark rows,
null-embedding production backfill/alert evidence, halfvec/pgvectorscale, and
the operator-gated runtime flip remain open. This slice does not claim a live
performance improvement.
