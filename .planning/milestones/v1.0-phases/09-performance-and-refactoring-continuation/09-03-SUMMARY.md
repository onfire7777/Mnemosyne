---
phase: 09-performance-and-refactoring-continuation
plan: 03
status: complete-local-gated
completed: 2026-07-08
---

# 09-03 Summary: Postgres Hot Query Preparation

## Outcome

Hot Postgres FTS and pgvector retrieval SELECTs now request immediate Psycopg
server-side preparation on pooled connections. The slice is parity-safe: query
text, parameters, tenant filtering, scoring, and rollback semantics are
unchanged.

## Implementation Notes

- `PostgresEngine` now has a `MNEMOSYNE_PG_PREPARE_HOT_QUERIES` kill switch.
- When enabled, hot FTS and pgvector retrieval SELECTs pass `prepare=True` to
  Psycopg so pooled connections can reuse server-side plans immediately.
- Tenant and HNSW `set_config(..., true)` statements remain unprepared and
  explicitly ordered before vector SELECTs.
- `CONFIG-DRIFT-CHECKS.md` registers the operator kill switch and the
  performance blueprint marks hot retrieval preparation as landed.

## Verification

- `uv run pytest -q tests/test_postgres_perf_lanes.py`
- `uv run ruff check src/mnemosyne/postgres_engine.py tests/test_postgres_perf_lanes.py`
