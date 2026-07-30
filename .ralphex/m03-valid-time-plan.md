# Plan: Implement the Bounded M03 Valid-Time Slice

## Overview

This is the GoalEx-selected Round 23 implementation handoff. Work only in
`/Users/admin/Mnemosyne.codex-wmb-m03-valid-time` on
`codex/wmb-m03-valid-time`, created by Worktrunk from clean
`main@7e9cd01feb2a31cbba96252943697245a4edd024`.

The exact write lease is:

- `eval/public/fixtures/wmbs-m03-valid-time-development.json`
- `src/mnemosyne/mcp_tools.py`
- `src/mnemosyne/cli.py`
- `eval/harness/cli_driver.py`
- `eval/public/adapters/whole_memory_reference.py`
- `eval/public/scoring.py`
- `tests/test_public_whole_memory_reference.py`
- `tests/test_cli_runtime_tools.py`

Reuse `MemoryTools.assert_fact`, `MemoryTools.supersede`, the existing CLI
wrappers, and `graph-as-of`. `_authorize` remains the first write decision.
Accept only optional timezone-aware `valid_from`, normalize it to UTC, and
preserve wall-clock behavior when omitted. Do not expose caller-controlled
`valid_to` or `transaction_time`, access internal validity tables, change
registry/runner/docs/result-v2/sandbox/publication surfaces, or run a broad
repository suite. The development cell remains proposed and non-publishable.

## Validation Commands

- `test "$(pwd -P)" = "/Users/admin/Mnemosyne.codex-wmb-m03-valid-time"`
- `test "$(git branch --show-current)" = "codex/wmb-m03-valid-time"`
- `test "$(git merge-base HEAD main)" = "7e9cd01feb2a31cbba96252943697245a4edd024"`
- `test "$(git diff --name-only main...HEAD)" = "$(printf '%s\n' eval/public/fixtures/wmbs-m03-valid-time-development.json eval/harness/cli_driver.py eval/public/adapters/whole_memory_reference.py eval/public/scoring.py src/mnemosyne/cli.py src/mnemosyne/mcp_tools.py tests/test_cli_runtime_tools.py tests/test_public_whole_memory_reference.py)"`
- `PYTHONPATH=src uv run --extra mcp pytest -q tests/test_cli_runtime_tools.py -k 'graph_as_of or supersede or assert'`
- `uv run pytest -q tests/test_public_whole_memory_reference.py`
- `uv run ruff check src/mnemosyne/mcp_tools.py src/mnemosyne/cli.py eval/harness/cli_driver.py eval/public/adapters/whole_memory_reference.py eval/public/scoring.py tests/test_public_whole_memory_reference.py tests/test_cli_runtime_tools.py`
- `git diff --check`

### Task 1: Write the failing M03 contracts
- [x] Add focused RED tests for aware timestamps, UTC normalization, naive or malformed rejection, authorization-first behavior, omitted-value compatibility, and rejection of caller-owned `valid_to` or `transaction_time`.
- [x] Add observable RED cases for ordered and late events, retroactive correction, exact boundaries, tied valid times, current answers, and historical `graph-as-of` answers.
- [x] Add the deterministic five-timeline/five-seed fixture labeled exactly `wmbs-m03-valid-time-development`, with transaction-time explicitly unsupported.

### Task 2: Implement the minimum shared-path change
- [x] Add one optional `valid_from` parameter to `MemoryTools.assert_fact` and `MemoryTools.supersede`, validate and normalize it after `_authorize`, and pass it through the existing `Assertion`/engine write path.
- [x] Thread the optional value through existing `assert` and `supersede` CLI commands and `MnemoCLI` wrappers; omission preserves current behavior.
- [x] Keep `valid_to` and `transaction_time` system-owned and use only existing `graph-as-of`/`as_of` behavior.

### Task 3: Add and score the development cell
- [x] Extend the existing whole-memory adapter and scorer through the CLI wrapper only.
- [x] Produce exact current/history answers, `M-ASOF-ACC=1.0`, zero stale-current leakage, deterministic tied-time replay, and five-seed canonical replay.
- [x] Preserve all non-publication and non-comparability labels and never call this full bitemporal M03.

### Task 4: Verify and commit the candidate
- [x] Run only the focused CLI/runtime tests, whole-memory reference tests, focused Ruff, and `git diff --check`.
- [x] Review the complete diff for exact lease, authorization ordering, timestamp validation, deterministic tie behavior, stale leakage, secrets, risky files, dependency churn, and evidence language.
- [x] Commit the clean candidate and report exact SHA and focused evidence. Leave push, PR, exact-head CI, merge, post-merge proof, CBM, and Gbrain to the GoalEx delivery round.
