# W3 P3 E — working-memory CLI and MCP API

Allowed files:
- src/mnemosyne/cli.py
- src/mnemosyne/mcp_tools.py
- src/mnemosyne/mcp_server.py
- src/mnemosyne/engine.py
- src/mnemosyne/sqlite_engine.py
- src/mnemosyne/postgres_engine.py
- tests/test_working_memory_api.py
- tests/test_shared_engine_contract.py
- tests/test_sqlite_working_memory.py
- tests/test_postgres_working_memory.py

Forbidden files:
- all other files, including schemas, retrieval, docs/planning, dependencies, benchmarks, and lockfiles

Validation:
- uv run ruff check src/mnemosyne/cli.py src/mnemosyne/mcp_tools.py src/mnemosyne/mcp_server.py src/mnemosyne/engine.py src/mnemosyne/sqlite_engine.py src/mnemosyne/postgres_engine.py tests/test_working_memory_api.py tests/test_shared_engine_contract.py tests/test_sqlite_working_memory.py tests/test_postgres_working_memory.py
- PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest -q tests/test_working_memory_api.py tests/test_shared_engine_contract.py tests/test_sqlite_working_memory.py tests/test_postgres_working_memory.py tests/test_parity_mcp.py tests/test_runtime_surfaces.py
- git diff --check b1ace355..HEAD

### Task 1: Subject-scoped expiry contract
- [x] Extend expire_working with optional user_id, agent_id, task_id, and branch selectors while preserving legacy behavior when omitted.
- [x] Enforce selectors before mutation in Local, SQLite, and PostgreSQL atomic expiry paths.
- [x] Pass all authenticated subject selectors from MemoryTools.working_expire.

### Task 2: Regression coverage
- [x] Add Local/shared-contract, SQLite, PostgreSQL, and public API regressions proving scope A cannot expire scope B in one tenant/session.
- [x] Preserve idempotency, half-open TTL semantics, provenance validation, rollback, and audit behavior.

### Task 3: Verify
- [ ] Run focused Ruff and focused API/MCP/backend tests.
- [ ] Confirm the complete diff is restricted to the allowed files and task metadata remains untracked.
