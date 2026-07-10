---
phase: 09-performance-and-refactoring-continuation
plan: 09
status: complete-local-gated
completed: 2026-07-09
---

# 09-09 Summary: Guarded Postgres Vector Backfill Apply

## Outcome

The source-owned vector backfill execution path is complete locally. Operators
now have an explicit, bounded `vector-backfill-apply` command that can apply one
Postgres batch after `--confirm-apply`, while retaining only redacted row ids and
content/statement hashes.

## Implementation Notes

- `PostgresEngine.upsert_assertion()` now embeds both `public` and `private`
  assertion partitions; only `none` remains intentionally NULL.
- `PostgresEngine.vector_backfill_apply()` samples embeddable NULL-vector
  evidence and assertion rows, applies a bounded batch, audits assertion
  embedding updates, and returns before/after hygiene snapshots.
- Evidence backfill reuses the existing `set_evidence_embedding()` write/audit
  path.
- Assertion backfill updates only rows still NULL and still embeddable.
- CLI `vector-backfill-apply` requires `--confirm-apply`, accepts tenant,
  branch, limit, and actor, and refuses non-Postgres engines.

## Verification

- `uv run pytest tests/test_postgres_perf_lanes.py::test_postgres_upsert_assertion_embeds_private_partition tests/test_postgres_perf_lanes.py::test_postgres_vector_backfill_apply_updates_assertions_with_redacted_report tests/test_cli_runtime_tools.py::test_cli_vector_backfill_apply_requires_explicit_confirmation tests/test_cli_runtime_tools.py::test_cli_vector_backfill_apply_emits_redacted_report -q`
  passed.
- `uv run ruff check src/mnemosyne/postgres_engine.py src/mnemosyne/cli.py tests/test_postgres_perf_lanes.py tests/test_cli_runtime_tools.py`
  passed.

## Remaining Work

This is still not production proof. Retained operator output from the real
production `vector-backfill-apply`, followed by a clean
`ops-report --require-clean-vector-hygiene`, is required before the live
backfill evidence item can be closed. Provider bake-off/default selection,
halfvec/pgvectorscale, tuning application, and before/after runtime evidence
remain separate Phase 09 tasks.
