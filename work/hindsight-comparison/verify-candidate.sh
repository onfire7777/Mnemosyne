#!/usr/bin/env bash
# Run from the Mnemosyne repository root. Logs are case-local.
set -euo pipefail
uv run --locked python -m pytest -q \
  tests/test_passage_graph.py \
  tests/test_retrieval_integrity.py \
  tests/test_parity_retrieval.py \
  tests/test_time_window.py \
  tests/test_store_recall.py \
  tests/test_cli_internals.py \
  tests/test_cli_mcp_parity.py \
  tests/test_mcp_validation_regressions.py \
  tests/test_engine_perf_lanes.py \
  tests/test_longmemeval_dry_run.py \
  tests/test_config_drift.py \
  tests/test_longmemeval_recall.py \
  tests/test_codex_reader.py \
  tests/test_reflect.py \
  tests/test_grounded_answering.py \
  tests/test_default_source_ranking.py \
  tests/test_compact_answering_embedder.py \
  tests/test_latency_docs_consistency.py \
  tests/test_network_egress_policy.py \
  tests/test_postgres_perf_lanes.py \
  tests/test_retrieval_as_of.py \
  tests/test_entity_identity_safety.py \
  tests/test_summary_source_custody.py \
  tests/test_proposal_source_custody.py \
  tests/test_summary_retrieval_custody.py \
  tests/test_consolidation_timescales.py \
  tests/test_consolidation_external_corroboration.py \
  tests/test_consolidation_rail_read.py \
  tests/test_shared_engine_contract.py \
  tests/test_global_sensemaking.py \
  tests/test_runtime_parity_extensions.py \
  tests/test_engine_contract.py \
  tests/test_sqlite_engine_core.py \
  tests/test_sqlite_ledger.py \
  tests/test_sqlite_erasure.py \
  tests/test_erasure_ids.py \
  tests/test_access_policy_enforcement.py \
  tests/test_evidence_redaction.py \
  tests/test_store_shared_values.py \
  tests/test_provider_contract.py \
  --junitxml=work/hindsight-comparison/runtime-final-verification.xml \
  > work/hindsight-comparison/runtime-final-verification.log 2>&1
uv run --locked ruff check . > work/hindsight-comparison/runtime-final-lint.log 2>&1
git diff --check
