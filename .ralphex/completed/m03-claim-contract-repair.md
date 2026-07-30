# M03 Claim Contract Repair

Repair the two confirmed independent-review findings on clean candidate
`c8cc472f` in the existing `codex/wmb-m03-valid-time` Worktrunk branch.

## Guardrails

- Use GPT-5.6 Sol low through the caller-provided RalphEx flags.
- Exact write lease only:
  - `eval/public/fixtures/wmbs-m03-valid-time-development.json`
  - `src/mnemosyne/mcp_tools.py`
  - `src/mnemosyne/cli.py`
  - `eval/harness/cli_driver.py`
  - `eval/public/adapters/whole_memory_reference.py`
  - `eval/public/scoring.py`
  - `tests/test_public_whole_memory_reference.py`
  - `tests/test_cli_runtime_tools.py`
- Do not edit docs, GOAL, planning/state, schemas, registries, runners,
  result-v2, sandbox, CI, or dependencies.
- Preserve all previously verified authorization, temporal, distinct-scope,
  fresh-replay, determinism, and system-owned-field behavior.
- Keep M03 explicitly PROPOSED, development-only, non-publishable,
  non-headline, independently unreproduced, and upstream-non-comparable.
- Run focused tests during repair and one whole-memory reference test-file run
  only after the stable candidate is ready. Never run the repository-wide
  suite; exact-head CI owns it.
- Stop if any fix requires a path outside the lease.

### Task 1: Freeze the canonical matrix and explicit claim custody

- [x] Add RED tests showing a self-consistent reduced or altered matrix fails
      runtime adapter/scorer validation rather than defining its own expected
      matrix.
- [x] Freeze the exact five canonical timeline IDs and five canonical seed
      values in the runtime contract, reusing the smallest existing constants
      or literal contract. Fail closed on missing, extra, duplicate, or changed
      values.
- [x] Add and require fixture custody fields:
      `admission_state=PROPOSED`, `headline_eligible=false`,
      `independent_reproduction=false`, and `upstream_comparable=false`.
- [x] Emit those fields in the scorer result and fail closed when any supplied
      value is missing or more permissive.
- [x] Preserve `publishable=false`,
      `comparability=proposed-non-comparable`, M-ASOF-ACC, stale leakage, and
      fresh replay behavior.
- [x] Run only focused M03 contract/scorer tests and focused Ruff.
- [x] Commit the bounded repair.

### Task 2: Verify the stable claim-boundary candidate

- [x] Review `7e9cd01f...HEAD` for exact eight-path lease, canonical 5x5
      runtime enforcement, explicit claim custody, authorization-first
      ordering, UTC rules, fresh replay, deterministic ties, secrets, risky
      files, and dependency churn.
- [x] Run the complete whole-memory reference test file once, the focused M03
      CLI/runtime selection, focused Ruff, and `git diff --check`.
- [x] Commit only an in-lease verification adjustment if required and report
      the exact clean candidate SHA. Leave docs, push, PR, CI, merge, CBM, and
      Gbrain to the integration owner.
