# Phase 06 Plan 04 Summary - Cached PPR

Completed the A12 cached-PPR implementation as a default-off Postgres
materialization seam.

## Files

- `sql/schema.sql`
- `src/mnemosyne/engine.py`
- `src/mnemosyne/postgres_engine.py`
- `tests/test_shared_engine_contract.py`
- `eval/benches/bench_oq1_ppr_latency.py`
- `config/drift-baseline.toml`

## Implementation

- Added tenant-scoped `graph_ppr_cache` storage with RLS.
- Added `PostgresEngine.refresh_graph_ppr_cache()` to materialize PPR hits.
- Added explicit `graph_ppr(..., use_cache=True)` cached reads while keeping
  the default recursive path unchanged.
- Added relation-set fingerprint and cache-depth guards so stale or undersized
  caches fall back to recursive PPR.
- Added Local protocol parity for the optional `use_cache` argument.

## Verification

- `.venv/bin/python -m pytest -q tests/test_shared_engine_contract.py -k "cached_ppr or graph_ppr"`
- `MNEMOSYNE_POSTGRES_DSN=... .venv/bin/python -m pytest -q tests/test_config_drift.py::test_no_undocumented_stores tests/test_config_drift.py::test_declared_stores_exist_in_schema tests/test_shared_engine_contract.py tests/test_postgres_engine_live.py -k "cached_ppr or graph_ppr or graph or cache or stores"`
- `.venv/bin/python eval/benches/bench_oq1_ppr_latency.py`
- `.venv/bin/python -m pytest -q`

The benchmark reports `cached_ppr_available: true` and keeps cached-read latency
explicitly unmeasured unless a DSN-backed refresh/read timing path is run.
