# PR 83 Confirmed Review Repair

Batch only the confirmed CodeRabbit findings on clean PR 83 head `a8723b12`.

## Guardrails

- Use GPT-5.6 Sol low through the caller-provided RalphEx flags.
- Exact write lease remains the same eight paths:
  - `eval/public/fixtures/wmbs-m03-valid-time-development.json`
  - `src/mnemosyne/mcp_tools.py`
  - `src/mnemosyne/cli.py`
  - `eval/harness/cli_driver.py`
  - `eval/public/adapters/whole_memory_reference.py`
  - `eval/public/scoring.py`
  - `tests/test_public_whole_memory_reference.py`
  - `tests/test_cli_runtime_tools.py`
- Do not edit docs, GOAL, planning/state, schema/registry/runner/result-v2,
  sandbox, CI, or dependencies.
- Preserve all authorization, temporal, canonical-matrix, claim-custody,
  fresh-replay, determinism, and system-owned-field behavior.
- Do not refactor the two working datetime parsers merely to share a helper.
- Keep adapter and scorer matrix constants independently defined and tested so
  either runtime boundary can detect drift; do not couple scorer validation to
  adapter implementation.
- Run focused tests during repair and one complete whole-memory reference file
  only after the stable candidate. Never run the repository-wide suite.

### Task 1: Repair the five confirmed PR findings

- [x] Add a RED check that `supersede new.valid_from` fails closed; then include
      nested `valid_from` with the existing system-owned `valid_to` and
      `transaction_time` rejection.
- [x] Give the `exact-boundary` fixture a distinct boundary probe, such as an
      exact earlier `valid_from` or a before-all-events empty observation, and
      update focused expectations without weakening the canonical 5x5 matrix.
- [x] Replace the tautological `five_seed_canonical_replay` metric with an
      actual per-seed agreement over original versus fresh-replay current and
      historical observations.
- [x] Type the adapter CLI parameter using a `TYPE_CHECKING` `MnemoCLI` import
      or equally minimal structural contract while preserving dataclass
      `replace(cli, store=...)`.
- [x] Reduce only the direct CLI temporal-observability test to one
      representative seed; the adapter/scorer test retains all five seeds.
- [x] Run focused review-regression tests and focused Ruff; commit the bounded
      repair.

### Task 2: Verify the repaired PR candidate

- [x] Review the complete diff for the exact eight-path lease and all retained
      security, temporal, replay, matrix, custody, and evidence boundaries.
- [x] Run the complete whole-memory reference test file once, the focused
      CLI/runtime review selection, focused Ruff, and `git diff --check`.
- [x] Commit only any required in-lease verification adjustment and report the
      exact clean SHA. Leave review replies, push, exact-head CI, merge, docs,
      CBM, and Gbrain to the integration owner.
