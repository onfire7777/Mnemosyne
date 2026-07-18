# W3 P2 finalizer task t_51c65abe

Authoritative plan: /Users/admin/Mnemosyne/docs/superpowers/plans/2026-07-15-W3-taxonomy-completion-plan.md
Integration source: codex/hermes-w3-p2-integration

### Task 1: Adjudicate W3 Phase 2 reviews and finalize candidate
- [x] Fast-forward this branch to the integration head (already exact at 8107e877).
- [x] Re-verify every R1/R2 review finding against live code and tests: PostgreSQL provenance lookup, dependency validation, durable receipt reuse protection, and CLI dependency scheduling are all present and covered by the focused/shared tests; PostgreSQL live execution is unavailable because MNEMOSYNE_POSTGRES_DSN is unset.
- [x] Apply only verified fixes within the exclusive Phase 2 write set (the verified fixes are already included in 8bb9cc4; no additional code changes were required).
- [x] Run focused prospective-memory, API, security, and shared-contract validation (green with the SQLite suite; PostgreSQL cases skipped solely for the unset DSN).
- [x] Run the full deterministic suite only under the admitted memory tier (50% free memory, no competing pytest/model workload). The authoritative worktree-bound run completed with 12 failures outside this write set: config-drift baseline coverage, MCP transport-schema parity, and pre-existing Local writer-ownership/runtime reload surfaces.
- [x] Run diff, Ruff, secret/risky-file, and exact-head cleanliness checks (all scoped checks green; no tracked secret material; HEAD equals integration head).
- [x] Create the clean final candidate commit and receipt.

Exclusive allowed write set:
- sql/schema.sql
- src/mnemosyne/cli.py
- src/mnemosyne/engine.py
- src/mnemosyne/mcp_server.py
- src/mnemosyne/mcp_tools.py
- src/mnemosyne/postgres_engine.py
- src/mnemosyne/security.py
- src/mnemosyne/sqlite_engine.py
- src/mnemosyne/sqlite_schema.py
- tests/test_postgres_prospective_memory.py
- tests/test_prospective_memory.py
- tests/test_prospective_memory_api.py
- tests/test_prospective_memory_security.py
- tests/test_shared_engine_contract.py
- tests/test_sqlite_prospective_memory.py

Forbidden/shared files:
- No Phase 3/Phase 4 implementation.
- No files outside the exclusive write set, including config/drift-baseline.toml, docs/**, .planning/**, .ralphex task metadata, .env, credentials, or secret files.
- Do not push, open a PR, merge, update planning state, or run protected benchmarks.

Focused validation commands:
- git diff --check
- .venv/bin/ruff check --quiet .
- PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_prospective_memory.py tests/test_prospective_memory_api.py tests/test_prospective_memory_security.py tests/test_shared_engine_contract.py tests/test_sqlite_prospective_memory.py
- If PostgreSQL DSN and psycopg are available: PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_postgres_prospective_memory.py
- Full deterministic suite, only at >=35% free memory and no competing heavy suite: PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/
- Secret/risky-file sweep over tracked files, excluding ignored credentials and environment files.
