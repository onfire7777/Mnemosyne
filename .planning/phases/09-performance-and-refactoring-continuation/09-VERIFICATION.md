---
phase: 09-performance-and-refactoring-continuation
status: passed
verified: 2026-07-09
scope: plan-09-09
---

# Phase 09 Verification

Latest verified slice: Phase 09 Plan 09. The source-owned guarded Postgres
vector backfill apply path is locally verified: private assertion partitions
are embedded on write, `vector-backfill-apply` refuses mutation without
`--confirm-apply`, and bounded apply reports omit raw evidence/assertion text.

Previous verified slice: Phase 09 Plan 08. The source-owned Postgres vector
backfill readiness probe is locally verified: `ops-report` can include a
read-only, redacted backfill plan with evidence/assertion backlog counts,
sampled candidate ids and hashes, and dashboard metrics, without raw content or
row mutation.

Earlier verified slice: Phase 09 Plan 07. The source-owned Postgres vector
hygiene ops gate is locally verified: `ops-report` includes a read-only vector
hygiene snapshot when a Postgres engine is present, and
`--require-clean-vector-hygiene` fails the report unless the probe is available
and clean across evidence and assertion vector tables.

Earlier verified slice: Phase 09 Plan 06. The source-owned stateless MCP
warm-bundle slice is locally verified: repeated same-scope stateless calls reuse
the warmed tool bundle, cross-tenant calls build a separate bundle, and local
durable store changes still invalidate a warmed reader before the next call.

Earlier verified slice: Phase 09 Plan 05. The source-owned Postgres partition
coverage/tuning-profile slice is locally verified: `none` is modeled as a
no-vector partition with btree coverage, the dense fallback excludes `none`
before Python embedding, and the Postgres tuning profile is versioned without a
silent runtime flip.

Earlier verified slice: Phase 09 Plan 04 provider conformance. The shared
provider fixture gates the Python embedding service, Python HTTP adapters, and
Rust `mneme-providers` sidecar in CI. This does not flip provider defaults or
claim provider bake-off evidence.

## Automated Checks

- `uv run pytest tests/test_postgres_perf_lanes.py::test_postgres_upsert_assertion_embeds_private_partition tests/test_postgres_perf_lanes.py::test_postgres_vector_backfill_apply_updates_assertions_with_redacted_report tests/test_cli_runtime_tools.py::test_cli_vector_backfill_apply_requires_explicit_confirmation tests/test_cli_runtime_tools.py::test_cli_vector_backfill_apply_emits_redacted_report -q`
  passed.
- `uv run ruff check src/mnemosyne/postgres_engine.py src/mnemosyne/cli.py tests/test_postgres_perf_lanes.py tests/test_cli_runtime_tools.py`
  passed.
- `uv run pytest tests/test_postgres_perf_lanes.py::test_postgres_vector_backfill_plan_samples_redacted_backlog tests/test_runtime_parity_extensions.py::test_ops_report_can_gate_postgres_vector_hygiene tests/test_runtime_parity_extensions.py::test_ops_dashboard_renderer_escapes_snapshot_values -q`
  passed.
- `uv run ruff check src/mnemosyne/postgres_engine.py src/mnemosyne/observability.py tests/test_postgres_perf_lanes.py tests/test_runtime_parity_extensions.py`
  passed.
- `uv run pytest -q tests/test_provider_contract.py tests/test_provider_batching.py tests/test_parity_retrieval.py tests/test_runtime_surfaces.py::test_http_embedding_and_reranker_adapters_use_json_provider_contract`
  passed.
- `uv run pytest tests/test_nfrs_and_schema.py::test_canonical_schema_partitions_sensitive_vector_indexes tests/test_nfrs_and_schema.py::test_postgres_perf_tuning_file_is_versioned_but_evidence_gated tests/test_postgres_perf_lanes.py::test_vector_schema_fully_present_issues_no_ddl_but_runs_backfills tests/test_postgres_perf_lanes.py::test_vector_schema_creates_btree_none_and_null_fallback_indexes tests/test_postgres_perf_lanes.py::test_vector_schema_missing_index_privilege_denied_warns_only tests/test_postgres_perf_lanes.py::test_postgres_null_embedding_fallback_is_capped_and_observable -q`
  passed.
- `uv run pytest tests/test_runtime_surfaces.py::test_mcp_server_stateless_mode_reuses_warm_tools_for_same_scope tests/test_runtime_surfaces.py::test_mcp_server_stateless_warm_tools_reload_after_external_store_write tests/test_runtime_surfaces.py::test_mcp_server_stateless_mode_reloads_durable_engine_and_runtime_state -q`
  passed.
- `uv run pytest tests/test_postgres_perf_lanes.py::test_postgres_vector_hygiene_snapshot_counts_null_vector_backlog tests/test_runtime_parity_extensions.py::test_ops_report_can_gate_postgres_vector_hygiene tests/test_runtime_parity_extensions.py::test_ops_dashboard_renderer_escapes_snapshot_values -q`
  passed.
- `uv run pytest tests/test_runtime_parity_extensions.py::test_ops_report_can_gate_postgres_vector_hygiene tests/test_cli_runtime_tools.py::test_cli_ops_report_requires_postgres_vector_hygiene_probe -q`
  passed.
- `uv run ruff check src/mnemosyne/postgres_engine.py src/mnemosyne/observability.py src/mnemosyne/cli.py tests/test_postgres_perf_lanes.py tests/test_runtime_parity_extensions.py`
  passed.
- `uv run ruff check src/mnemosyne/mcp_server.py tests/test_runtime_surfaces.py`
  passed.
- `uv run ruff check src/mnemosyne/postgres_engine.py tests/test_nfrs_and_schema.py tests/test_postgres_perf_lanes.py`
  passed.
- `uv run pytest -q tests/test_nfrs_and_schema.py tests/test_postgres_perf_lanes.py`
  passed with expected live-DB skips.
- `uv run ruff check`
  passed.
- `uv run pytest -q`
  passed.
- `node /Users/admin/.codex/get-shit-done/bin/gsd-tools.cjs validate consistency --raw`
  passed.
- `EMBEDDING_SERVICE_FORCE_FALLBACK=1 uv run python services/embedding/selftest.py`
  passed.
- `cargo test --manifest-path rust/mneme-providers/Cargo.toml`
  passed.
- `cargo clippy --manifest-path rust/mneme-providers/Cargo.toml --all-targets -- -D warnings`
  passed.
- `uv run pytest -q tests/test_engine_perf_lanes.py tests/test_capability.py`
  passed.
- `uv run ruff check src/mnemosyne/pipeline.py src/mnemosyne/capability.py src/mnemosyne/sqlite_engine.py tests/test_engine_perf_lanes.py tests/test_capability.py`
  passed.
- `git diff --check` passed.
- `uv run pytest -q tests/test_sqlite_retrieve.py tests/test_sqlite_scans.py tests/test_engine_perf_lanes.py tests/test_capability.py`
  passed with one expected skip.
- `uv run pytest -q` passed locally.
- `node /Users/admin/.codex/get-shit-done/bin/gsd-tools.cjs validate consistency --raw`
  passed.
- `node /Users/admin/.codex/get-shit-done/bin/gsd-tools.cjs verify phase-completeness 09`
  passed.

## Review Notes

- CBM diff impact was reviewed for the central retrieval pipeline and SQLite
  scan-oracle cache path before shipping.
- CBM/agent review confirmed `embedding_partition='none'` is non-embeddable,
  so HNSW would be semantically wrong; ADR-003 records btree coverage plus
  fallback exclusion instead.
- The vector hygiene gate is an observability/operator check only. It does not
  run a production backfill and does not prove a live production zero-null-vector
  state without retained operator evidence.
- The backfill plan is read-only, while `vector-backfill-apply` is the guarded
  write path. Neither proves production completion without retained operator
  output and a clean post-backfill hygiene probe.
- GSD health has only pre-existing, non-repairable governance warnings: numeric
  phase references inside historical text and intentional root-level planning
  artifacts. No repairable GSD health errors remain for this slice.
- This verification does not claim Tier-B production/operator completion.
  Production evidence remains governed by the existing capture and release
  audit surfaces.
