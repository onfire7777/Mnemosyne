# Plan: Prove the M03 Write-Path Dependency

## Overview
Canonical `main` and `origin/main` are `392b1fc173f454893e1b133ff3a727462586a8b0`, with M01/M10 delivered through PR #81. The GoalEx branch is clean at `57986762dc654515c01c5d8b2b9220a05bc06b78`. Round 17 made no implementation edits and is explicitly marked rejected because it widened the committed M03 lease.

The authoritative M03 lease contains exactly seven paths: `eval/public/fixtures/wmbs-m03-valid-time-development.json`, `src/mnemosyne/cli.py`, `eval/harness/cli_driver.py`, `eval/public/adapters/whole_memory_reference.py`, `eval/public/scoring.py`, `tests/test_public_whole_memory_reference.py`, and `tests/test_cli_runtime_tools.py`. Do not edit any other path.

Current evidence shows the public CLI delegates assertion and supersession writes to `MemoryTools.assert_fact` and `MemoryTools.supersede` in excluded `src/mnemosyne/mcp_tools.py`. Neither method accepts or assigns `Assertion.valid_from`. Direct engine access from the CLI or adapter would bypass the shared authorization/write contract and is forbidden. This round must independently reproduce that dependency and return it without implementation, failing tests, or lease widening. No independent review findings require adjudication.

**Outcome (2026-07-30):** The exact checkout, graph trace, symbol trace, and
cleanliness checks confirmed this dependency without repository changes. The
bounded RalphEx child was stopped after it began retrying only because its
generic completion contract expected an edit. M03 remains `PROPOSED`; the
lease was not widened.

## Validation Commands
- `test "$(pwd -P)" = "/Users/admin/.codex/worktrees/9697/Mnemosyne" && test "$(git branch --show-current)" = "codex/goalex-whole-memory-pilot" && test -z "$(git status --porcelain)"`
- `test "$(git rev-parse main)" = "392b1fc173f454893e1b133ff3a727462586a8b0" && test "$(git rev-parse origin/main)" = "$(git rev-parse main)"`
- `test ! -e eval/public/fixtures/wmbs-m03-valid-time-development.json`
- `git diff --quiet main...HEAD -- eval/public/fixtures/wmbs-m03-valid-time-development.json src/mnemosyne/cli.py eval/harness/cli_driver.py eval/public/adapters/whole_memory_reference.py eval/public/scoring.py tests/test_public_whole_memory_reference.py tests/test_cli_runtime_tools.py`
- `rg -n 'def assert_fact|def supersede|Assertion\\(' src/mnemosyne/mcp_tools.py`
- `rg -n 'tools\\.(assert_fact|supersede)|def (supersede|graph_as_of)' src/mnemosyne/cli.py eval/harness/cli_driver.py`
- `git diff --check && test -z "$(git status --porcelain)"`

### Task 1: Reproduce the lease-blocking dependency
- [x] Verify the root, branch, clean state, canonical `main`, and the seven-path lease using the validation commands; do not fetch, branch, edit, or commit.
- [x] Trace `cmd_assert` and `cmd_supersede` through `MemoryTools.assert_fact` and `MemoryTools.supersede`, confirming that neither shared write method accepts `valid_from` nor assigns it to the constructed `Assertion`.
- [x] Confirm that adding only CLI flags or `MnemoCLI` wrapper parameters would be inert, while direct `tools.engine` access would bypass the existing authorization and shared write path.
- [x] Confirm that the fixture, adapter, and scorer cannot produce honest ordered/late/retroactive valid-time traces until the write surface can persist caller-supplied `valid_from`.

### Task 2: Fail closed with the exact admission request
- [x] Make no repository changes and leave the worktree clean.
- [x] Return the exact blocker: M03 requires owner authorization to add `src/mnemosyne/mcp_tools.py` to the lease so `MemoryTools.assert_fact` and `MemoryTools.supersede` can accept, validate, and assign timezone-aware `valid_from`.
- [x] Explicitly reject direct engine access, internal validity-table mutation, registry/runner changes, a second M03 module, transaction-time semantics, and shared-documentation edits.
- [x] State that M03 remains unimplemented and `PROPOSED`; do not claim pilot readiness, measured evidence, publication eligibility, or completion.
