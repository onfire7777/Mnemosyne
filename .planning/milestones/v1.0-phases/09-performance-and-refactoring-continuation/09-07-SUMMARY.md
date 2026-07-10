---
phase: 09-performance-and-refactoring-continuation
plan: 07
status: complete-local-gated
completed: 2026-07-09
---

# 09-07 Summary: Postgres Vector Hygiene Ops Gate

## Outcome

The source-owned vector hygiene gate is complete locally. `ops-report` now
surfaces a Postgres vector hygiene snapshot when the engine supports it, and
operators can opt into `--require-clean-vector-hygiene` to fail reports with
embeddable NULL vectors or illegal vectors in the non-embeddable `none`
partition across evidence and assertions.

## Implementation Notes

- `PostgresEngine.vector_hygiene_snapshot()` performs a read-only tenant/branch
  scoped count of embeddable NULL vectors, illegal `none`-partition vectors,
  stored vectors, `none` rows, and live rows across evidence and assertions.
- `build_ops_report()` always includes `postgres_vector_hygiene` and keeps the
  existing default tripwire behavior unchanged.
- `--require-clean-vector-hygiene` requires a real available probe and a clean
  snapshot before `tripwires.passed` can be true.
- The static ops dashboard now includes a Postgres Vector Hygiene section.

## Verification

- `uv run ruff check src/mnemosyne/postgres_engine.py src/mnemosyne/observability.py src/mnemosyne/cli.py tests/test_postgres_perf_lanes.py tests/test_runtime_parity_extensions.py`
  passed.
- `uv run pytest tests/test_postgres_perf_lanes.py::test_postgres_vector_hygiene_snapshot_counts_null_vector_backlog tests/test_runtime_parity_extensions.py::test_ops_report_can_gate_postgres_vector_hygiene tests/test_runtime_parity_extensions.py::test_ops_dashboard_renderer_escapes_snapshot_values -q`
  passed.

## Remaining Work

This slice does not execute a production backfill, apply live Postgres tuning,
ship halfvec/pgvectorscale, flip provider defaults, or capture before/after
operator runtime evidence. Those remain Phase 09 evidence-gated tasks.
