---
phase: 09-performance-and-refactoring-continuation
validated: 2026-07-10
status: passed-current-coverage
nyquist_compliant: true
wave_0_complete: true
reconstructed: true
---

# Phase 09 Nyquist Validation

This coverage map was reconstructed on 2026-07-10 from Plans/Summaries 01-13
and current tests. It does not retroactively claim the historical sampling
cadence.

| Plans | Seam | Focused check | Backstop |
|---|---|---|---|
| 01-03 | Capability defaults, concurrency, cache/scan safety | `uv run --locked python -m pytest tests/test_engine_perf_lanes.py tests/test_capability.py tests/test_sqlite_scans.py -q` | Full suite/CI |
| 04 | Provider contract conformance | `uv run --locked python -m pytest tests/test_provider_contract.py tests/test_provider_batching.py tests/test_parity_retrieval.py -q` | Provider self-test/CI |
| 05-09 | Postgres tuning, hygiene, plan/apply backfill | `uv run --locked python -m pytest tests/test_nfrs_and_schema.py tests/test_postgres_perf_lanes.py tests/test_runtime_parity_extensions.py -q` | DSN-gated CI |
| 10 | Durable scoped/TTL/redaction-safe embedding cache | `uv run --locked python -m pytest tests/test_provider_batching.py tests/test_http_embedding_cache_privacy.py -q` | Full suite/CI |
| 11 | Bake-off evidence harness | `uv run --locked python -m pytest eval/tests/test_provider_bakeoff.py -q` | Independent report review |
| 12 | Native wheel build/install/import parity | `uv run --locked python -m pytest tests/test_native_packaging.py tests/test_native_parity.py -q` | Native-wheel CI jobs |
| 13 | Planning/doc hygiene | `uv run --locked python -m pytest tests/test_latency_docs_consistency.py tests/test_planning_traceability.py -q` | GSD consistency/audit |

The following remain explicit non-blocking future evidence obligations: real
provider default selection, production cache hit-rate/latency, retained
production vector backfill, broader wheel publication/adoption,
negative/abstention caching, and runtime-default-flip evidence.
