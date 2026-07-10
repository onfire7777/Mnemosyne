---
phase: 09-performance-and-refactoring-continuation
plan: 06
status: complete-local-gated
completed: 2026-07-09
---

# 09-06 Summary: Stateless MCP Warm Bundle Reuse

## Outcome

The source-owned part of Phase 09 Task 7 is complete locally. Stateless MCP
mode now reuses a warmed tool bundle for repeated calls in the same
tenant/user/session scope, while local durable stores still invalidate the
bundle when another process writes the store or runtime-state file.

## Implementation Notes

- `MnemosyneMcpServer` owns a per-instance stateless bundle cache.
- Cache keys include queue tenant, tenant, user, and session/source identity.
- Local and SQLite modes stamp the durable store plus `.runtime.json` file.
- Postgres mode reuses the wrapper bundle without file stamps because reads are
  DB-backed.
- The stateful MCP path remains unchanged.

## Verification

- `uv run ruff check src/mnemosyne/mcp_server.py tests/test_runtime_surfaces.py`
  passed.
- `uv run pytest tests/test_runtime_surfaces.py::test_mcp_server_stateless_mode_reuses_warm_tools_for_same_scope tests/test_runtime_surfaces.py::test_mcp_server_stateless_warm_tools_reload_after_external_store_write tests/test_runtime_surfaces.py::test_mcp_server_stateless_mode_reloads_durable_engine_and_runtime_state -q`
  passed.

## Remaining Work

This slice does not claim a production latency improvement. Operator runtime
flip evidence, before/after benchmarks, and broader production performance
proof remain under the Phase 09 evidence gates.
