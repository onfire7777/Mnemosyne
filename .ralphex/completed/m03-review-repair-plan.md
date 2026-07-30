# M03 Review Repair

Repair only the confirmed M03 review findings on the existing
`codex/wmb-m03-valid-time` Worktrunk branch. The worktree already contains
uncommitted RED tests from the interrupted review; preserve and use them.

## Guardrails

- Use GPT-5.6 Sol low through the caller-provided RalphEx flags.
- Do not edit documentation, GOAL.md, planning/state files, registries, runners,
  schemas, result-v2, sandbox code, dependencies, or CI.
- The exact write lease is limited to:
  - `eval/public/fixtures/wmbs-m03-valid-time-development.json`
  - `src/mnemosyne/mcp_tools.py`
  - `src/mnemosyne/cli.py`
  - `eval/harness/cli_driver.py`
  - `eval/public/adapters/whole_memory_reference.py`
  - `eval/public/scoring.py`
  - `tests/test_public_whole_memory_reference.py`
  - `tests/test_cli_runtime_tools.py`
- Authorization must remain the first write decision. Preserve tenant, branch,
  trust, access-policy, and provenance checks.
- Accept only timezone-aware ISO-8601 `valid_from`, normalize it to UTC, and
  preserve omitted wall-clock behavior. Never accept caller-controlled
  `valid_to` or transaction time.
- Preserve PROPOSED/development-only/non-publishable/non-comparable evidence
  boundaries. Do not call this full bitemporal M03.
- Run focused tests only. Do not run the repository-wide suite; exact-head CI
  owns the authoritative broad run.
- Stop and report if a fix requires any path outside the lease.

### Task 1: Repair the confirmed graph-as-of semantic regression

- [x] Run the existing dirty RED CLI/runtime checks and confirm the failure.
- [x] Fix the shared root path so graph-as-of preserves distinct valid scopes
      instead of collapsing assertions that have the same semantic value.
- [x] Cover supersede UTC normalization, malformed/naive rejection, omitted
      wall-clock behavior, authorization-first validation, exact boundaries,
      and deterministic tied valid times.
- [x] Run only the focused CLI/runtime checks and Ruff for touched files.
- [x] Commit the bounded repair with a clean exact-lease worktree.

### Task 2: Make replay evidence a fresh deterministic replay

- [x] Run the existing dirty RED whole-memory checks and confirm the failures.
- [x] Make the adapter replay the fixture operations into a fresh store rather
      than rereading the original store, using the existing CLI wrapper.
- [x] Require the complete canonical timeline/seed matrix and fail closed on a
      replay mismatch.
- [x] Preserve `M-ASOF-ACC=1.0`, zero stale-current leakage, deterministic tied
      valid-time behavior, and development-only labels.
- [x] Run the complete whole-memory reference test file, the focused M03 CLI
      test, and focused Ruff.
- [x] Commit the bounded repair with a clean exact-lease worktree.

### Task 3: Verify the repaired candidate

- [x] Review the full `7e9cd01f...HEAD` diff for exact lease, authorization
      ordering, UTC validation, distinct-scope semantics, genuine fresh replay,
      complete-matrix scoring, deterministic ties, evidence language, secrets,
      risky files, and dependency churn.
- [x] Run only the focused CLI/runtime tests, whole-memory reference tests,
      focused Ruff, and `git diff --check`.
- [x] Commit only any required in-lease verification adjustment and report the
      exact candidate SHA. Leave docs, push, PR, CI, merge, CBM, and Gbrain to
      the integration owner.
