# Phase 06 Plan 07 Summary - Lane G Runtime Readiness

Completed the 06-07 compose-Postgres and hosted-MCP readiness checkpoint.

## Files

- `tests/test_postgres_engine_live.py`
- `.planning/phases/06-exact-blueprint-runtime-parity/06-07-SUMMARY.md`
- `.planning/STATE.md`
- `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md`
- `docs/ROADMAP-TO-100.md`
- `docs/STATE-OF-COMPLETION.md`

## Implementation

- Closed the remaining FR-20 live-Postgres method coverage gap by
  parametrizing the live `media_extract` job test across image, audio, and
  video. Each modality now proves derived text evidence, source modality/media
  metadata, `media-derived-text` lineage, retrieval, and erasure propagation on
  the compose Postgres path.
- Parametrized the live CLI raw-media embedding/vector-retrieval test across
  image, audio, and video. Each modality now verifies externalized empty-content
  evidence, persisted media embeddings, media metadata, stored-vector dense
  retrieval, and RLS-scoped Postgres storage.
- Extended A12 cached-PPR live coverage with a direct compose-Postgres
  `refresh_graph_ppr_cache()` materialization test. The live test proves the
  default recursive PPR path remains unchanged, `use_cache=True` reads the
  materialized JSON cache, cache depth/fingerprint metadata is written, and a
  relation-set mutation invalidates the stale cache before refresh.
- Verified A13 recompute memo already runs through shared Local/Postgres
  contracts, and FR-21 parametric trainer/rollback already has a live Postgres
  command-provider coverage path.
- No production engine/runtime behavior changed for Lane G cached-PPR coverage;
  the new cached-PPR work is test-only coverage for existing A12 behavior.

## Verification

- `MNEMOSYNE_POSTGRES_DSN=postgresql://mnemosyne:<redacted>@127.0.0.1:54329/mnemosyne?connect_timeout=5 .venv/bin/python -m pytest -q tests/test_postgres_engine_live.py -k "media_extract_job_appends_searchable_derived_evidence_live or raw_media_embedding_for_vector_retrieval_live"` passed with 6/6 selected cases.
- `MNEMOSYNE_POSTGRES_DSN=postgresql:///<ephemeral-db> PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /tmp/mnemosyne-pg-repro-venv312/bin/python -m pytest tests/test_postgres_engine_live.py::test_postgres_graph_ppr_cache_refresh_materializes_live -q` passed against a freshly created local Postgres database loaded from `sql/schema.sql`.
- `MNEMOSYNE_POSTGRES_DSN=postgresql://mnemosyne:<redacted>@127.0.0.1:54329/mnemosyne?connect_timeout=5 .venv/bin/python -m pytest -q` passed with the full 864-test collection, 0 failures, and 0 errors.
- `.venv/bin/python -m mnemosyne.cli belief-revision-check --cases <generated belief_revision_cases()> --min-cases 3 --require-case supersession-contradiction --require-case cascade-invalidation --require-case contested-hypotheses` passed with fingerprint `a82ae8e72482a108c33699d0306e496c8292e5c5b1cec08e0a2a2f1bf6952f5f`.
- `.venv/bin/python -m mnemosyne.cli mcp-http-soak --base-url http://127.0.0.1:<local> --iterations 2 --timeout 5 --read-only-tool profile_context --tool-arguments '{"tenant_id":"tenant-a","user_id":"user-a"}' --expected-transport http-json-rpc --require-stateless` passed against the local stateless hosted JSON-RPC server.
- `.venv/bin/python -m mnemosyne.cli mcp-streamable-http-soak --base-url http://127.0.0.1:<local> --iterations 2 --timeout 5 --read-only-tool profile_context --tool-arguments '{"tenant_id":"tenant-a","user_id":"user-a"}' --expected-transport mcp-sdk-streamable-http` passed against the local SDK StreamableHTTP server.
- `.venv/bin/python -m mnemosyne.cli mcp-sse-soak --base-url http://127.0.0.1:<local> --iterations 2 --timeout 5 --min-events 1 --expected-event endpoint --require-endpoint-data` passed against a local SSE-compatible endpoint.

## Remaining

- This does not flip any production audit row to Done. The 10 strict-parity rows
  still require operator-captured production evidence from concrete deployed
  infrastructure under `release-audit --require-production-validated --require-provider-forbid-local`.
- A11 hosted MCP production parity remains an operator evidence task for real
  deployed endpoints, certificates, sessions, and redaction bundles.
