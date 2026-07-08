# Performance Blueprint Synthesis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Continue the performance/refactoring blueprint from current `main` without reimplementing already-landed work, preserving byte-parity and making every shipped slice verifiable through tests, GSD/CBM/gbrain sync, and CI.

**Architecture:** Mnemosyne keeps exactness in the scoring/fusion/calibration oracle and takes speed from transport, caching, indexing, native kernels, and operator topology. Approximate layers may improve candidate generation only; final scoring and exposed semantics stay byte-identical unless a slice is explicitly opt-in and recalibrated.

**Tech Stack:** Python 3.12, uv, pytest, ruff, Rust/PyO3/maturin, pgvector/Postgres, SQLite, GSD planning, Graphify, codebase-memory-mcp, gbrain.

## Global Constraints

- Do not claim blueprint parity from source-only work; operator evidence and production benchmarks remain distinct gates.
- Prefer no-op/doc correction when the blueprint is stale and code already landed the feature.
- Keep `MNEMOSYNE_*` operator overrides authoritative and registered in `CONFIG-DRIFT-CHECKS.md`.
- Rebuild the native extension before Python parity tests when Rust PyO3 code changes.
- Refresh CBM, gbrain, GSD graph/status, and CI after committed slices.

## Tasks

- [x] Task 1: Verify current graph/memory state and preserve Graphify local artifacts.
  - Enable GSD Graphify in `.planning/config.json`.
  - Keep generated graph files locally under `.planning/graphs/`.
  - Ignore generated `.planning/graphs/` and `graphify-out/` output so CBM
    does not index redundant graph JSON.

- [x] Task 2: Correct cache/status drift instead of duplicating caches.
  - Register `MNEMOSYNE_EMBEDDING_CACHE_SIZE` and `MNEMOSYNE_EMBEDDING_MODEL_REVISION`.
  - Update the performance blueprint and Phase 09 docs to show the landed process-local HTTP embedding LRU, retrieval result LRU, and Postgres positive calibration cache.
  - Add provider cache tests for mixed cached/uncached batches, model-revision key busting, and `cache_size=0`.

- [x] Task 3: Release the GIL for the smallest native-owned kernels.
  - Wrap `mmr_select_indices` and `ppr_power_iteration` compute bodies in `Python::detach`.
  - Keep validation before detach and arithmetic/order untouched.
  - Run cargo, maturin, native parity, and benchmark guard tests.

- [ ] Task 4: Add Postgres prepared-statement/plan-reuse slice.
  - Scope to existing pooled connections and hot vector/FTS paths.
  - Preserve tenant `set_config(..., true)` binding and rollback behavior.
  - Add perf-lane tests plus one live DSN smoke when available.

- [ ] Task 5: Add provider contract/conformance CI lane.
  - Share `/embed` and `/rerank` contract fixtures across Python service, HTTP adapter, and `mneme-providers`.
  - Keep bake-off output reproducible before any provider default flip.

- [ ] Task 6: Close Postgres vector coverage/tuning gaps.
  - Add `'none'` partition index coverage before any halfvec/pgvectorscale work.
  - Version server tuning with before/after evidence instead of silent defaults.

- [ ] Task 7: Implement stateless MCP warm-bundle reuse.
  - Cache reusable tool/provider bundles without crossing tenant/session boundaries.
  - Add repeated-call reuse and cross-tenant isolation tests.

- [ ] Task 8: Run operator-gated runtime flip evidence.
  - Execute only with operator confirmation against the live stack.
  - Commit retained before/after benchmark evidence and rollback proof.
