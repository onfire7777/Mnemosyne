# Testing Patterns

**Analysis Date:** 2026-07-08

## Test Framework

**Runner:**
- Pytest 9.1.1.
- Config: `pyproject.toml`
- Test discovery: `testpaths = ["tests"]`, with `pythonpath = ["src", "."]` in `pyproject.toml`.

**Assertion Library:**
- Native `assert` statements plus pytest helpers.
- Use `pytest.raises`, `pytest.approx`, `pytest.skip`, `pytest.importorskip`, `monkeypatch`, `tmp_path`, and `capsys` where needed.
- Property tests use Hypothesis from the dev dependency group in `pyproject.toml`.

**Run Commands:**
```bash
uv run --locked python -m pytest                          # Run local deterministic tests
uv run --locked ruff check .                              # Run lint gate
uv run --locked python -m pytest tests/test_config_drift.py -q
uv run --locked python -m pytest tests/test_postgres_engine_live.py -q
MNEMOSYNE_CHAOS=1 uv run --locked python -m pytest tests/chaos -q
uv run --locked python -m pytest tests/benchmarks --benchmark-only
```

## Test File Organization

**Location:**
- Main unit/integration tests live in `tests/`.
- Gated chaos/fault-injection tests live in `tests/chaos/`.
- Completion/release rail tests live under `tests/completion/`.
- Benchmark tests and baseline capture helpers live in `tests/benchmarks/`.
- Evaluation harness tests live in `eval/tests/`, `eval/calibration/`, `eval/latency/`, and `eval/replay_fidelity/`.
- Service smoke tests live beside service code, such as `services/embedding/selftest.py`.

**Naming:**
- Test files use `test_*.py`, such as `tests/test_algorithms.py`, `tests/test_sqlite_engine_core.py`, and `eval/tests/test_metrics.py`.
- Test functions use descriptive `test_<behavior>` names that state the invariant, such as `test_hostile_tenant_id_is_contained_inside_root_dir()` in `tests/test_sqlite_engine_core.py`.
- Helper factories use leading underscores inside test modules, such as `_rich_evidence()` in `tests/test_sqlite_engine_core.py` and `_hit()` in `tests/test_algorithms.py`.

**Structure:**
```text
tests/
├── test_<module_or_contract>.py          # standard pytest suites
├── benchmarks/                           # pytest-benchmark opt-in suites
├── chaos/                                # MNEMOSYNE_CHAOS-gated suites
└── completion/<area>/                    # release/completion rails

eval/
├── tests/                                # eval harness tests
├── calibration/                          # calibration tests and fixtures
├── latency/                              # latency benchmarks/tests
└── replay_fidelity/                      # replay fidelity checks
```

## Test Structure

**Suite Organization:**
```python
from __future__ import annotations

import pytest

from mnemosyne.models import Evidence
from mnemosyne.sqlite_engine import SqliteEngine


def _rich_evidence(**overrides) -> Evidence:
    base = {"tenant_id": "tenant-rt", "user_id": "user-1", "actor": "user"}
    base.update(overrides)
    return Evidence(**base)


def test_insert_evidence_requires_cid(tmp_path):
    engine = SqliteEngine(tmp_path / "root")
    with pytest.raises(ValueError):
        engine._insert_evidence(_rich_evidence(cid=None))
```

**Patterns:**
- Group related tests with section comments inside large files, as in `tests/test_sqlite_engine_core.py`.
- Prefer in-file helper factories over shared fixture frameworks unless multiple files need the same setup.
- Use `tmp_path` for filesystem/database roots and verify containment explicitly, as in `tests/test_sqlite_engine_core.py`.
- Use `pytest.mark.parametrize` for matrixed seeds and rail constants, as in `tests/chaos/test_sqlite_chaos.py` and `tests/test_parity_learning.py`.
- Use focused subprocess checks for CLI behavior, as in `tests/test_postgres_engine_live.py` and `tests/test_g0_harness.py`.

## Mocking

**Framework:** pytest `monkeypatch`; no standalone mocking framework is configured.

**Patterns:**
```python
def test_seed_provider_health_parametric_corpus_yields_four_rows_two_tiers(monkeypatch) -> None:
    class _FakeEngine:
        def __init__(self, dsn, require_safe_role: bool = False) -> None:
            assert dsn == "postgresql://health"

    monkeypatch.setattr(postgres_engine, "PostgresEngine", _FakeEngine)
```

**What to Mock:**
- Patch external providers, environment variables, optional modules, subprocess-facing commands, and network primitives at the owning module boundary. Examples: `tests/test_provider_check_parametric_probe.py`, `tests/test_mcp_token_file.py`, and `tests/test_network_egress_policy.py`.
- Use fake classes or local scripts when behavior must be inspected, such as fake parametric/retrieval commands in `tests/test_postgres_engine_live.py`.

**What NOT to Mock:**
- Do not mock core engine parity paths when cross-backend behavior is the subject. Use local/oracle comparisons like `tests/test_sqlite_engine_core.py` and `tests/test_algorithms.py`.
- Do not mock SQLite filesystem behavior for containment, WAL, integrity, or byte round-trip tests; use `tmp_path` real files.
- Do not hide Postgres behavior in live integration tests; `tests/test_postgres_engine_live.py` requires `MNEMOSYNE_POSTGRES_DSN` and skips when it is absent.

## Fixtures and Factories

**Test Data:**
```python
def _sample_lists() -> list[list[Hit]]:
    dense = [_hit("evidence", "a", 0.9, "dense_hash")]
    lexical = [_hit("evidence", "b", 3.0, "lexical")]
    return [dense, lexical, []]
```

**Location:**
- Keep small factories in the test file that uses them, such as `_hit()` and `_sample_lists()` in `tests/test_algorithms.py`.
- Use directory-scoped `conftest.py` only for collection or suite policy. `tests/benchmarks/conftest.py` skips benchmark tests unless opted in; `tests/chaos/conftest.py` deselects chaos tests unless `MNEMOSYNE_CHAOS=1`.
- Use temporary directories manually in Hypothesis tests when pytest fixtures do not mix cleanly, as documented in `tests/test_journal_properties.py`.

## Coverage

**Requirements:** No coverage percentage gate or coverage tool config is detected in `pyproject.toml`.

**View Coverage:**
```bash
uv run --locked python -m pytest
```

**Practical Gate:**
- CI gates on Ruff, the full local pytest suite, explicit drift checks, G0 preregistration replay, a Postgres integration job, native parity checks when Rust is present, and a non-gating nightly chaos suite in `.github/workflows/ci.yml`.
- README documents current expected verification surfaces and commands in `README.md`.

## Test Types

**Unit Tests:**
- Pure helper and algorithm tests compare extracted helpers to engine statics and expected rankings in `tests/test_algorithms.py`.
- Domain serialization and model behavior tests should assert exact dictionaries or byte-compatible representations, matching `tests/test_sqlite_engine_core.py` and `src/mnemosyne/models.py`.

**Integration Tests:**
- SQLite integration tests use real temporary DB files in `tests/test_sqlite_engine_core.py`, `tests/test_sqlite_ledger.py`, and related `tests/test_sqlite_*.py` suites.
- Postgres live tests live in `tests/test_postgres_engine_live.py`, require `psycopg`, and skip when `MNEMOSYNE_POSTGRES_DSN` is unset.
- CLI and runtime surface tests use subprocesses and JSON assertions in `tests/test_cli_runtime_tools.py`, `tests/test_runtime_surfaces.py`, and `tests/test_g0_harness.py`.

**E2E Tests:**
- No browser E2E framework is used.
- End-to-end verification is represented by CLI/runtime subprocess tests, MCP runtime tests, Postgres-backed integration tests, evaluation harness tests under `eval/tests/`, and service self-tests such as `services/embedding/selftest.py`.

## Common Patterns

**Async Testing:**
```python
result = subprocess.run(
    [sys.executable, "-m", "mnemosyne.cli", *args],
    check=False,
    text=True,
    capture_output=True,
)
result.check_returncode()
payload = json.loads(result.stdout)
```

**Error Testing:**
```python
with pytest.raises(ValueError, match="vendor_flag"):
    engine.append_evidence(Evidence(..., access_policy={"vendor_flag": True}))
```

**Environment Gates:**
- Use `monkeypatch.setenv()` / `monkeypatch.delenv()` for unit-level environment behavior, as in `tests/test_mcp_token_file.py` and `tests/test_candidate_memo_expiry.py`.
- Use `pytest.skip()` for optional live dependencies, as in `tests/test_postgres_engine_live.py`.
- Use collection-time gating for heavy suites: `tests/benchmarks/conftest.py` and `tests/chaos/conftest.py`.

**Property Testing:**
```python
@given(st.lists(st.uuids().map(str), min_size=1, max_size=30, unique=True))
@settings(max_examples=50, deadline=None)
def test_append_only_prefix_property(cid_list):
    ...
```

**Performance and Drift Checks:**
- Keep benchmark assertions opt-in under `tests/benchmarks/` and document any absolute benchmark mode with `MNEMOSYNE_BENCH_ABSOLUTE`.
- Add drift tests for generated/configured contracts under `tests/test_config_drift.py` or similarly explicit test files.

---

*Testing analysis: 2026-07-08*
