# Phase 16 Metric-Family Taxonomy

## Scope

LEAD-002 requires separate retrieval, QA, security, calibration, performance,
and reproducibility dimensions. The merged result contract currently admits
only `retrieval` and `judged_qa`. This package extends that existing closed
taxonomy while preserving the one-family-per-record rule and every other
validation invariant.

## Design

Reuse `leaderboard.validate._validate_metric`. Replace its two-value family
allowlist with the six controlling LEAD-002 values:

- `retrieval`
- `judged_qa`
- `security`
- `calibration`
- `performance`
- `reproducibility`

No new schema version, dependency, abstraction, renderer behavior, or
publication claim is needed. A later lease may render these validated families
as distinct columns; this package only makes the contract capable of carrying
them.

## TDD Sequence

1. Add parameterized focused tests proving each new family is accepted.
2. Preserve focused rejection tests for unknown and mixed families.
3. Run the new acceptance test against the current validator and record RED.
4. Extend the existing allowlist once.
5. Run the focused contract suite and full repository verification.

## Acceptance Checks

```sh
uv run pytest -q tests/test_leaderboard_result_contract.py
uv run --extra mcp pytest -q
uv run ruff check .
git diff --check
git diff --name-only "$(git merge-base HEAD origin/main)"..HEAD
```

Only the four paths in `GOAL.md` may change. Secret and risky-file checks must
be clean. Phase 12 protected evidence and Phase 15 hardware proof remain
operator-owned gates and are not exercised here.
