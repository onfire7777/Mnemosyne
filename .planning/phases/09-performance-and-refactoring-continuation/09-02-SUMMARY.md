---
phase: 09-performance-and-refactoring-continuation
plan: 02
status: complete-local-gated
completed: 2026-07-08
target_metric: cache_drift_native_gil_release
target_value: documented_landed_caches_and_detached_mmr_ppr
gate: focused-local-plus-native-parity
gate_result: passed
---

# 09-02 Summary: Cache Drift Closure and Native GIL Detach

Phase 09 Plan 02 is implemented and locally verified. The performance blueprint
and Phase 09 context now distinguish already-landed cache surfaces from the
remaining durable/privacy-scoped provider cache and operator-evidence work.

## Implementation

- `CONFIG-DRIFT-CHECKS.md` now registers
  `MNEMOSYNE_EMBEDDING_CACHE_SIZE` and
  `MNEMOSYNE_EMBEDDING_MODEL_REVISION`.
- The blueprint now records the process-local `HttpEmbeddingProvider`
  content-hash LRU, default-off retrieval result LRU, and Postgres positive
  calibration lookup cache as landed.
- Provider batching tests now prove mixed cached/uncached batch behavior,
  model-revision cache separation, and `cache_size=0` no-cache behavior.
- `mmr_select_indices` and `ppr_power_iteration` now release the GIL while
  running Rust-owned compute loops; validation and arithmetic order are
  unchanged.
- GSD Graphify is enabled and generated graph artifacts live locally under
  `.planning/graphs/`; duplicate `graphify-out/` scratch output is ignored.

## Verification

- `uv run pytest -q tests/test_provider_batching.py tests/test_postgres_perf_lanes.py`
  passed with expected skips.
- `cargo fmt --manifest-path rust/mnemosyne-native/Cargo.toml --check` passed.
- `cargo test --manifest-path rust/mnemosyne-native/Cargo.toml` passed.
- `uv run maturin develop --manifest-path rust/mnemosyne-native/Cargo.toml`
  rebuilt the local PyO3 extension.
- `uv run pytest -q tests/test_native_parity.py tests/test_native_dispatch.py tests/benchmarks/test_retrieval_baselines.py`
  passed with expected skips.

## Remaining Work

Future Phase 09 slices should handle Postgres prepared statements/plan reuse,
provider contract/conformance CI, `'none'` partition vector index coverage,
stateless MCP warm reuse, durable/provider-cache hardening, and operator-run
runtime-flip evidence.
