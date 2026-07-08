---
phase: 09-performance-and-refactoring-continuation
plan: 01
status: complete-local-gated
completed: 2026-07-08
target_metric: retrieval_parallel_channels_tier_default
target_value: standard_plus_on_floor_off
gate: focused-local-plus-full-pytest
gate_result: passed
---

# 09-01 Summary: Retrieval Channel Capability Defaults

Phase 09 Plan 01 is implemented and locally verified. Retrieval channel
parallelism now defaults from capability tier when
`MNEMOSYNE_PARALLEL_CHANNELS` is absent, while explicit operator env values
remain authoritative.

## Implementation

- `pipeline.parallel_channels_enabled()` now honors explicit
  `MNEMOSYNE_PARALLEL_CHANNELS` first and falls back to capability tier only
  when the env var is absent.
- `floor` remains conservative with parallel retrieval channels off.
- `standard`, `accelerated`, and `frontier` enable parallel retrieval channels
  by default through the capability tier.
- `capability.recommended_env()` now recommends
  `MNEMOSYNE_PARALLEL_CHANNELS=1` for `standard` and above.
- SQLite scan-oracle memo miss filling now holds the engine RLock through
  hydrate-and-store, so default parallel dense/lexical retrieval still coalesces
  to one SQL hydration per candidate scope.
- Tests now distinguish capability-default behavior from explicit env override
  behavior, while preserving the existing Local/SQLite byte-identical
  parallel-vs-sequential retrieval checks.

## Documentation

- `CONFIG-DRIFT-CHECKS.md` documents the tier-driven default and explicit
  override semantics.
- `docs/blueprint/Mnemosyne-Performance-and-Refactoring-Blueprint.md` records
  the B5 default-policy slice as landed and leaves remaining async/overlap work
  as future scope.
- `.planning/codebase/ARCHITECTURE.md` describes the current retrieval
  threading policy.

## Verification

- `uv run pytest -q tests/test_engine_perf_lanes.py tests/test_capability.py`
  passed.
- `uv run ruff check src/mnemosyne/pipeline.py src/mnemosyne/capability.py src/mnemosyne/sqlite_engine.py tests/test_engine_perf_lanes.py tests/test_capability.py`
  passed.
- `git diff --check` passed.
- `uv run pytest -q tests/test_sqlite_retrieve.py tests/test_sqlite_scans.py tests/test_engine_perf_lanes.py tests/test_capability.py`
  passed with one expected skip.
- `uv run pytest -q` passed locally.
- GSD `validate consistency` passed.

## Remaining Work

Future Phase 09 slices should handle durable/privacy-scoped provider cache
hardening, structured async provider/SQL I/O, Postgres prepared statements and
server/index tuning, stored-vector MMR bake-off/recalibration, and CLI
decomposition. The process-local HTTP embedding LRU, retrieval result LRU, and
Postgres positive calibration lookup cache are already landed; future cache work
should focus on durability, cache-safety, metrics, and operator evidence.
