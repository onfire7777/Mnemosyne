# Coding Conventions

**Analysis Date:** 2026-07-08

## Naming Patterns

**Files:**
- Use lowercase snake_case Python modules in `src/mnemosyne/`, such as `src/mnemosyne/sqlite_engine.py`, `src/mnemosyne/access_policy.py`, and `src/mnemosyne/evidence_redaction.py`.
- Use `test_*.py` for pytest files under `tests/`, `tests/chaos/`, `tests/completion/`, and `eval/tests/`, such as `tests/test_sqlite_engine_core.py` and `eval/tests/test_metrics.py`.
- Use focused support modules with leading underscores only when they are test helpers, such as `tests/chaos/_chaos_harness.py` and `tests/completion/portability/_portability.py`.

**Functions:**
- Use snake_case for public functions, methods, and pytest tests: `route()` in `src/mnemosyne/engine.py`, `validate_access_policy()` in `src/mnemosyne/access_policy.py`, and `test_evidence_round_trip_byte_identical_vs_local_oracle()` in `tests/test_sqlite_engine_core.py`.
- Use leading underscores for module-private helpers and internal seams: `_normalise_privacy_tags()` in `src/mnemosyne/engine.py`, `_graph_ppr_seed_hash()` in `src/mnemosyne/sqlite_engine.py`, and `_env_or_file_secret()` in `src/mnemosyne/mcp_server.py`.
- Use verb-led names for state-changing operations: `append_evidence`, `upsert_assertion`, `add_relation`, `register_entity`, and `set_calibration` in engine-facing modules such as `src/mnemosyne/engine.py` and `src/mnemosyne/sqlite_engine.py`.

**Variables:**
- Use snake_case domain names consistently: `tenant_id`, `user_id`, `access_policy`, `trust_tier`, `source_evidence_cids`, and `runtime_residency` across `src/mnemosyne/models.py`, `src/mnemosyne/access_policy.py`, and `src/mnemosyne/mcp_server.py`.
- Use uppercase constants for durable policy values and backend names: `ROLE_SENSITIVITY_CEILINGS` in `src/mnemosyne/access_policy.py`, `PROTOCOL_VERSION` in `src/mnemosyne/mcp_server.py`, and `LEXICAL_BACKEND` in `src/mnemosyne/sqlite_engine.py`.
- Use uppercase environment variable names and keep their parsing close to the owning runtime path: `MNEMOSYNE_MCP_TOKEN` in `src/mnemosyne/mcp_server.py`, `MNEMOSYNE_CHAOS` in `tests/chaos/conftest.py`, and `MNEMOSYNE_BENCH_ABSOLUTE` in `tests/benchmarks/conftest.py`.

**Types:**
- Use `@dataclass(slots=True)` for record-like domain models and snapshots, as in `src/mnemosyne/models.py` and `src/mnemosyne/observability.py`.
- Use `Literal[...]` for constrained string domains such as `Actor`, `AssertionStatus`, and `BeliefOperation` in `src/mnemosyne/models.py`.
- Use `Protocol` / `runtime_checkable` for engine contracts in `src/mnemosyne/engine.py`, with runtime contract tests in `tests/test_sqlite_engine_core.py`.

## Code Style

**Formatting:**
- No formatter-specific config is detected in `pyproject.toml`; keep code compatible with the checked-in `ruff==0.15.20` dependency in `pyproject.toml`.
- Use `from __future__ import annotations` at the top of Python modules, after the module docstring, matching `src/mnemosyne/models.py`, `src/mnemosyne/engine.py`, and most tests.
- Prefer explicit imports over wildcard imports. Keep imports grouped as future import, standard library, third-party packages, then `mnemosyne` imports, as in `src/mnemosyne/engine.py` and `tests/test_postgres_engine_live.py`.
- Use short explanatory comments for load-bearing invariants, especially where protocol, security, parity, or datetime behavior can regress; examples live in `src/mnemosyne/sqlite_engine.py`, `src/mnemosyne/access_policy.py`, and `.github/workflows/ci.yml`.

**Linting:**
- Use Ruff as the lint gate: `uv run --locked ruff check .`, defined in `.github/workflows/ci.yml`.
- Keep dependencies and lint/test environments locked through `uv.lock`; CI runs `uv sync --locked --group dev` before Ruff in `.github/workflows/ci.yml`.
- Ruff rule tuning is not customized in `pyproject.toml`, so avoid relying on project-specific ignores unless they are inline and justified, such as `# noqa: BLE001` comments in `src/mnemosyne/mcp_server.py`.

## Import Organization

**Order:**
1. Module docstring, then `from __future__ import annotations`.
2. Standard library imports, alphabetized enough to stay readable, as in `src/mnemosyne/models.py`.
3. Third-party imports such as `pytest`, `hypothesis`, or optional SDKs, as in `tests/test_journal_properties.py` and `tests/test_postgres_engine_live.py`.
4. First-party imports from `mnemosyne.*`, grouped by module responsibility, as in `src/mnemosyne/engine.py`.

**Path Aliases:**
- Runtime package imports use the installed package name `mnemosyne.*`; examples include `from mnemosyne.models import Evidence` in `tests/test_sqlite_engine_core.py`.
- Pytest adds `src` and the repo root to `pythonpath` through `[tool.pytest.ini_options]` in `pyproject.toml`, so tests can import both `mnemosyne` and top-level `eval`.
- Avoid relative imports between production modules; first-party imports are absolute in `src/mnemosyne/*.py`.

## Error Handling

**Patterns:**
- Validate at trust boundaries and fail closed with typed exceptions. Use `ValueError` for invalid configuration or input shape in `src/mnemosyne/mcp_server.py` and `src/mnemosyne/access_policy.py`.
- Use `PermissionError` for denied session/tool authorization paths in `src/mnemosyne/mcp_server.py` and security-facing tests such as `tests/test_blueprint_later_phases.py`.
- Use domain-specific subclasses when a family of failures needs a stable boundary, such as `SessionAuthError(ValueError)` in `src/mnemosyne/security.py`.
- Chain exceptions when preserving root cause helps operators, e.g. `raise ValueError(...) from exc` in `src/mnemosyne/mcp_server.py` and `src/mnemosyne/security.py`.
- Keep secret values out of messages. `validate_access_policy()` in `src/mnemosyne/access_policy.py` reports unknown key names, not policy values.
- Tests should pin failure modes with `pytest.raises(..., match=...)`, as in `tests/test_network_egress_policy.py`, `tests/test_audit_chain.py`, and `tests/completion/rails/test_parametric_rail_gate.py`.

## Logging

**Framework:** console plus structured metrics; no centralized Python logging framework is configured.

**Patterns:**
- Prefer structured return objects, JSON reports, metrics counters, and explicit CLI output over ad hoc log streams. `src/mnemosyne/observability.py` exposes `MetricsRegistry`, `MetricsSnapshot`, and `build_ops_report()`.
- Use `print()` only for CLI/reporting paths or test baseline capture, such as `src/mnemosyne/mcp_server.py` self-test output and `tests/benchmarks/capture_baselines.py`.
- For new operational surfaces, add counters/gauges to `src/mnemosyne/observability.py` or return structured JSON from the command path rather than introducing a one-off logger.

## Comments

**When to Comment:**
- Comment invariants whose violation changes safety, parity, or performance semantics, such as timestamp serialization in `src/mnemosyne/sqlite_engine.py`, access-policy behavior in `src/mnemosyne/access_policy.py`, and CI native/chaos gating in `.github/workflows/ci.yml`.
- Keep comments near the code they protect. `tests/benchmarks/conftest.py` and `tests/chaos/conftest.py` explain why collection-time gating exists.
- Do not add comments that restate simple assignments or obvious control flow.

**JSDoc/TSDoc:**
- Not applicable. This repo is Python-first.
- Use Python docstrings for public modules, records, and non-obvious helpers, as in `src/mnemosyne/models.py`, `src/mnemosyne/sqlite_engine.py`, and `tests/test_journal_properties.py`.

## Function Design

**Size:** Small pure helpers should stay short and deterministic, as in `src/mnemosyne/models.py` and `src/mnemosyne/access_policy.py`. Larger orchestration methods are acceptable when they enforce a single runtime boundary, such as MCP setup in `src/mnemosyne/mcp_server.py`.

**Parameters:** Use typed parameters and keyword-only options for policy-sensitive helpers. Examples include `validate_access_policy(..., tenant_id=..., location=...)` in `src/mnemosyne/access_policy.py` and `safe_urlopen(..., validated=..., timeout=..., context=...)` tested by `tests/test_network_egress_policy.py`.

**Return Values:** Return typed dataclasses or plain JSON-serializable dictionaries at boundaries. `to_dict()` / `from_dict()` methods in `src/mnemosyne/models.py` centralize serialization, and `RoutePlan.to_dict()` in `src/mnemosyne/engine.py` keeps router output inspectable.

## Module Design

**Exports:** Prefer explicit module-level classes, constants, and functions. `src/mnemosyne/models.py` owns domain records, `src/mnemosyne/access_policy.py` owns access-policy decisions, and `src/mnemosyne/observability.py` owns metrics/report helpers.

**Barrel Files:** Minimal. `src/mnemosyne/__init__.py` is present but production code imports concrete modules directly.

**New Code Guidance:**
- Put production code under `src/mnemosyne/` with absolute `mnemosyne.*` imports.
- Add tests under `tests/test_<area>.py` for ordinary behavior, `tests/completion/<area>/` for completion-gate rails, `tests/chaos/` for env-gated chaos/fault tests, and `eval/tests/` for evaluation harness behavior.
- Keep optional external dependencies behind extras and runtime gates, matching `postgres`, `mcp`, `native`, and `sqlitevec` extras in `pyproject.toml`.

---

*Convention analysis: 2026-07-08*
