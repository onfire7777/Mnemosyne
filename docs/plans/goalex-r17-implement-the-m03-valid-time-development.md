# Plan: Implement the M03 Valid-Time Development Cell

## Overview
Canonical `main` and `origin/main` are both `392b1fc173f454893e1b133ff3a727462586a8b0`, containing PR #81 and exact M01/M10 source head `98b83e4be373cf0acd5411769b80b98dfd1a8caa`. The dedicated GoalEx branch is clean but contains post-merge planning/verification commits through `387a130a`; preserve those commits and perform implementation in a new Worktrunk-isolated branch from `origin/main`.

Implement only Task 5 from `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`: expose timezone-aware `valid_from` through the existing assertion and supersession write paths, query history only through the existing public `graph-as-of` command, and add a deterministic CLI-only M03 development fixture, adapter, and scorer. Reuse `Assertion.valid_from`, `MemoryTools.assert_fact`, `MemoryTools.supersede`, `MnemoCLI`, the existing whole-memory registry/runner/scoring conventions, and the M01/M10 pilot patterns.

The implementation lease is limited to `src/mnemosyne/{cli.py,mcp_tools.py}`, `eval/harness/cli_driver.py`, `eval/public/{adapters/whole_memory_reference.py,registry.json,runner.py,scoring.py,wmbs_m03.py}`, `eval/public/fixtures/wmbs-m03-valid-time-development.json`, `tests/test_cli_runtime_tools.py`, `tests/test_public_whole_memory_reference.py`, `tests/test_public_wmbs_m03.py`, and minimal affected public documentation. Do not touch result-v2, ledgers, publication, sandbox enforcement, protected worktrees, or external benchmark adapters. Keep `wmbs-m03-valid-time-development`, `PILOT-READY-DEV`/`PROPOSED`, `publishable:false`, and `pbpp_headline_eligible:false`. Explicitly report transaction-time queries as unsupported; do not add `query_as_of(valid_time, transaction_time)`.

## Validation Commands
- `test "$(git rev-parse origin/main)" = "392b1fc173f454893e1b133ff3a727462586a8b0" && git merge-base --is-ancestor 98b83e4be373cf0acd5411769b80b98dfd1a8caa origin/main`
- `PYTHONPATH=src uv run --extra mcp pytest -q tests/test_cli_runtime_tools.py -k 'graph_as_of or supersede or valid_from'`
- `PYTHONPATH=src uv run --extra mcp pytest -q tests/test_public_wmbs_m03.py tests/test_public_whole_memory_reference.py`
- `PYTHONPATH=src uv run --extra mcp pytest -q tests/test_public_eval.py tests/test_public_wmbs_m01.py tests/test_public_wmbs_m10.py tests/test_public_wmbs_m03.py`
- `uv run ruff check src/mnemosyne/cli.py src/mnemosyne/mcp_tools.py eval/harness/cli_driver.py eval/public tests/test_cli_runtime_tools.py tests/test_public_whole_memory_reference.py tests/test_public_wmbs_m03.py`
- `git diff --check && git status --short`

### Task 1: Establish the isolated M03 lease
- [ ] Refresh `origin`, confirm canonical `main` and `origin/main` equal `392b1fc173f454893e1b133ff3a727462586a8b0`, confirm PR #81 source head is an ancestor, and inspect active worktrees/branches so no existing writer owns the M03 files.
- [ ] Create a Worktrunk-isolated `codex/wmb-m03-valid-time` branch from `origin/main`; do not implement on canonical `main` or consume either protected external worktree.
- [ ] Confirm all PR #81 files are present in the isolated checkout, then record the exact file lease listed in the overview and reject unrelated dirty or overlapping changes.
- [ ] Read the landed M03 specification, pilot Task 5, M01/M10 runner/scorer patterns, and current assertion/supersession/as-of implementations before editing.

### Task 2: Expose the minimum public valid-time write contract
- [ ] Add RED CLI/runtime tests covering aware `valid_from` on `assert` and `supersede`, rejection of naive or malformed timestamps, ordered and late events, retroactive correction, half-open exact boundaries, tied valid times, current state, and historical `graph-as-of` results.
- [ ] Add optional `valid_from: datetime | str | None` parameters to `MemoryTools.assert_fact` and `MemoryTools.supersede`; parse them with the repository’s existing datetime parser, fail closed unless timezone-aware, and pass the resulting value into `Assertion.valid_from`.
- [ ] Add optional `--valid-from` to only the `assert` and `supersede` CLI commands, thread it through `cmd_assert`/`cmd_supersede`, and add matching optional arguments to the existing `MnemoCLI` assertion and supersession wrappers.
- [ ] Preserve existing behavior when `valid_from` is omitted, reuse current engine tie and half-open interval rules, and make no schema, storage-table, transaction-time, or direct internal-validity-table changes.
- [ ] Run the focused CLI/runtime validation command and commit the tested public temporal surface separately.

### Task 3: Add the deterministic CLI-only M03 development pilot
- [ ] Create `eval/public/wmbs_m03.py` and its tests using the established M01/M10 pure fixture-validation and scoring style; validate exactly five deterministic timelines across at least five seeds with explicit virtual-clock, event, ingestion, and query order.
- [ ] Create `eval/public/fixtures/wmbs-m03-valid-time-development.json` with ordered events, late events, retroactive corrections, exact boundaries, tied valid times, current queries, and historical queries; include canonical replay inputs and an explicit disclosure that transaction-time queries are unsupported.
- [ ] Extend `whole_memory_reference.py` to execute the fixture solely through `MnemoCLI` assertion, supersession, and `graph_as_of` wrappers; the adapter and scorer must not import an engine or inspect validity tables.
- [ ] Register only `wmbs-m03-valid-time-development` with scoring profile `wmbs-m03-valid-time-v1`, following existing registry/runner dispatch conventions without widening official or publication states.
- [ ] Extend `scoring.py` to recompute `M-ASOF-ACC`, stale-current leakage, and deterministic tie-policy replay from fixture labels and CLI traces; require `M-ASOF-ACC=1.0`, zero stale-current leakage, and exact replay.
- [ ] Add adversarial tests for missing/extra timeline cases, duplicate seeds, reordered events or queries, altered labels, malformed timestamps, unsupported transaction-time requests, direct-engine bypass attempts, and non-finite or fabricated metrics.
- [ ] Run the focused M03 and existing M01/M10 regression commands, then commit the deterministic development cell separately.

### Task 4: Verify and prepare the candidate head
- [ ] Run all validation commands from a clean candidate checkout and retain exact counts and command outputs; do not substitute a measured benchmark run for contract tests.
- [ ] Inspect the full diff for lease violations, secrets, unsafe paths or subprocess construction, schema/registry drift, direct engine imports in the scorer/adapter, misleading evidence language, and accidental transaction-time or publication scope.
- [ ] Confirm the fixture replays identically in a clean process, all five seeds are represented, transaction-time remains explicitly unsupported, and every result remains non-publishable and PBPP-ineligible.
- [ ] If the repository-wide suite encounters the previously documented certificate-rotator environmental timeout unchanged on `main`, preserve the focused green evidence and defer the uncontended full-suite gate to exact-head GitHub CI; do not weaken or skip tests.
- [ ] Push normally to a non-protected branch and leave a clean candidate head ready for independent review and a later delivery round; do not merge or declare the whole-memory milestone complete.
