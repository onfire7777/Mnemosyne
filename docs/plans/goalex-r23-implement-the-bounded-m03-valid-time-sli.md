# Plan: Implement the Bounded M03 Valid-Time Slice

## Overview
Work from clean canonical `main@7e9cd01feb2a31cbba96252943697245a4edd024` in a new isolated Worktrunk branch, never on `codex/goalex-whole-memory-pilot` or canonical `main`. PR #82 already delivered M12/M13; do not revisit those files or claims.

Implement only Task 5 of `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`. The exact lease is:

- `eval/public/fixtures/wmbs-m03-valid-time-development.json`
- `src/mnemosyne/mcp_tools.py`
- `src/mnemosyne/cli.py`
- `eval/harness/cli_driver.py`
- `eval/public/adapters/whole_memory_reference.py`
- `eval/public/scoring.py`
- `tests/test_public_whole_memory_reference.py`
- `tests/test_cli_runtime_tools.py`

Reuse `MCPTools.assert_fact`, `MCPTools.supersede`, the existing CLI wrappers, and `graph-as-of`. `_authorize` must remain the first write decision. Accept only optional timezone-aware `valid_from`, normalize it to UTC, and preserve current wall-clock behavior when omitted. Do not expose caller-controlled `valid_to` or `transaction_time`, access internal validity tables, add another M03 module, or change registry, runner, shared documentation, result-v2, sandbox, publication, or official-suite behavior. The development cell remains `PROPOSED`, `INTERNALLY_MEASURED`, non-publishable, non-headline-eligible, non-independent, and non-upstream-comparable. No independent post-round findings require adjudication.

## Validation Commands
- `test "$(git rev-parse main)" = "$(git rev-parse origin/main)" && test "$(git rev-parse main)" = "7e9cd01feb2a31cbba96252943697245a4edd024"`
- `test "$(git diff --name-only main...HEAD)" = "$(printf '%s\n' eval/public/fixtures/wmbs-m03-valid-time-development.json eval/harness/cli_driver.py eval/public/adapters/whole_memory_reference.py eval/public/scoring.py src/mnemosyne/cli.py src/mnemosyne/mcp_tools.py tests/test_cli_runtime_tools.py tests/test_public_whole_memory_reference.py)"`
- `PYTHONPATH=src uv run --extra mcp pytest -q tests/test_cli_runtime_tools.py -k 'graph_as_of or supersede or assert'`
- `uv run pytest -q tests/test_public_whole_memory_reference.py`
- `uv run ruff check src/mnemosyne/mcp_tools.py src/mnemosyne/cli.py eval/harness/cli_driver.py eval/public/adapters/whole_memory_reference.py eval/public/scoring.py tests/test_public_whole_memory_reference.py tests/test_cli_runtime_tools.py`
- `git diff --check`

### Task 1: Establish the isolated exact lease
- [ ] Fetch `origin`, prove canonical `main` is clean and exactly `7e9cd01f`, then create one isolated Worktrunk branch from that commit with only the eight authorized paths leased.
- [ ] Inspect the existing assertion, supersession, CLI-wrapper, `graph-as-of`, adapter, fixture, and scoring flows; reuse them without adding a parallel M03 execution path.
- [ ] Stop if `main` advanced incompatibly, another writer owns any leased path, or the implementation requires registry, runner, engine/table, documentation, result-v2, or sandbox changes.

### Task 2: Write the failing M03 contracts
- [ ] Add focused RED tests proving assertion and supersession accept aware timestamps, normalize non-UTC offsets to UTC, reject naive or malformed timestamps, and preserve authorization as the first write decision.
- [ ] Add RED observable-behavior cases for ordered and late events, retroactive correction, exact boundaries, tied valid times, current answers, historical `graph-as-of` answers, omitted-`valid_from` wall-clock compatibility, and rejection of caller-owned `valid_to` or `transaction_time`.
- [ ] Add the deterministic five-timeline/five-seed fixture labeled exactly `wmbs-m03-valid-time-development`, including an explicit unsupported disclosure for transaction-time queries.

### Task 3: Implement the minimum shared-path change
- [ ] Add one optional `valid_from` parameter to `MCPTools.assert_fact` and `MCPTools.supersede`, validating and normalizing it only after `_authorize`, then pass it through the existing `Assertion`/engine write path.
- [ ] Thread the same optional value through the existing `assert` and `supersede` CLI commands and `MnemoCLI` wrappers; omission must use the existing wall-clock behavior.
- [ ] Keep `valid_to` and `transaction_time` system-owned and use only existing `graph-as-of`/`as_of` behavior for historical valid-time questions.

### Task 4: Add and score the development cell
- [ ] Extend the existing whole-memory adapter and scorer to execute the fixture exclusively through the CLI wrapper, without direct engine imports or internal-table inspection.
- [ ] Produce exact current/history answers, `M-ASOF-ACC=1.0`, zero stale-current leakage, deterministic tied-time replay, and five-seed canonical replay.
- [ ] Preserve all non-publication and non-comparability labels; describe the result as the bounded valid-time development slice, never full bitemporal M03.

### Task 5: Verify the candidate without delivering it
- [ ] Run the focused CLI/runtime tests, whole-memory reference tests, focused Ruff, and `git diff --check`; do not run an official suite, protected dataset, paid provider, measured cell, container, or duplicate repository-wide candidate suite.
- [ ] Review the complete diff for exact lease compliance, authorization ordering, trust-boundary validation, deterministic tie behavior, stale-current leakage, secrets, risky files, dependency churn, and prohibited evidence-language upgrades.
- [ ] Commit the clean candidate and report its exact SHA, test counts, remaining transaction-time deferral, and any blocker. Leave push, PR, exact-head CI, review, merge, post-merge proof, CBM refresh, and durable milestone recording for the next delivery round.
