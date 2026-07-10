---
phase: 09-performance-and-refactoring-continuation
plan: 08
status: complete-local-gated
completed: 2026-07-09
---

# 09-08 Summary: Postgres Vector Backfill Readiness

## Outcome

The source-owned vector backfill readiness slice is complete locally.
`ops-report` can now include a read-only, redacted Postgres backfill plan that
turns the NULL-vector hygiene counts into actionable candidate metadata without
running a backfill or disclosing raw memory content.

## Implementation Notes

- `PostgresEngine.vector_backfill_plan()` reuses the hygiene snapshot for
  backlog counts, then samples oldest embeddable NULL-vector rows from evidence
  and assertions for the requested tenant and branch.
- Evidence samples report row id, content SHA-256, source type, trust tier,
  sensitivity, and embedding partition.
- Assertion samples report row id, statement SHA-256 over
  `subject/predicate/object/scope`, status, trust tier, sensitivity, and
  embedding partition.
- `build_ops_report()` nests the plan under
  `postgres_vector_hygiene.backfill_plan` when a Postgres engine exposes the
  probe, and reports probe errors without failing the whole ops report.
- The static ops dashboard now shows backfill backlog, sampled count, and
  truncation state.

## Verification

- `uv run ruff check src/mnemosyne/postgres_engine.py src/mnemosyne/observability.py tests/test_postgres_perf_lanes.py tests/test_runtime_parity_extensions.py`
  passed.
- `uv run pytest tests/test_postgres_perf_lanes.py::test_postgres_vector_backfill_plan_samples_redacted_backlog tests/test_runtime_parity_extensions.py::test_ops_report_can_gate_postgres_vector_hygiene tests/test_runtime_parity_extensions.py::test_ops_dashboard_renderer_escapes_snapshot_values -q`
  passed.

## Remaining Work

This slice is an operator-evidence bridge only. It does not execute or retain a
production backfill, apply live Postgres tuning, ship halfvec/pgvectorscale,
flip provider defaults, or capture before/after runtime evidence. Those remain
Phase 09 evidence-gated tasks.
