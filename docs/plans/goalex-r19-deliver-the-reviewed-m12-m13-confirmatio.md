# Plan: Deliver the Reviewed M12/M13 Confirmation Integration

## Overview
Canonical `main` and `origin/main` must remain anchored at `392b1fc173f454893e1b133ff3a727462586a8b0` before integration. M01/M10 landed through PR #81. Round 18 proved that M03 cannot persist caller-supplied `valid_from` without the excluded `src/mnemosyne/mcp_tools.py`; M03 therefore remains `PROPOSED` and must not be touched.

Two reviewed satellites are ready and based directly on canonical main:

- M12: `codex/wmb-m12-confirmation@18871c2db26f651f71211486bf8210d30902f8b8`, comprising commits `c86b29ab` and `18871c2d`, modifying only `tests/test_public_pm_bench_triggerbench.py`.
- M13: `codex/wmb-m13-confirmation@d6befbc8f2a6de61e2fe76f4ad731be3afa9ebc0`, modifying only `tests/test_public_working_memory_action_probe.py`.

The integration must remain test-only. Preserve `admission_state=PROPOSED`, `evidence_level=INTERNALLY_MEASURED`, `publishable:false`, `headline_eligible:false`, `independent_reproduction:false`, and `upstream_comparable:false`. Do not add recurrence support, promotion behavior, adapters, fixtures, result-v2, documentation, registry/runner changes, or measured benchmark receipts. No independent post-round findings require adjudication.

## Validation Commands
- `test "$(pwd -P)" = "/Users/admin/.codex/worktrees/9697/Mnemosyne" && test "$(git branch --show-current)" = "codex/goalex-whole-memory-pilot" && test -z "$(git status --porcelain)"`
- `git fetch --prune origin && test "$(git rev-parse main)" = "$(git rev-parse origin/main)" && test "$(git rev-parse main)" = "392b1fc173f454893e1b133ff3a727462586a8b0"`
- `test "$(git merge-base main codex/wmb-m12-confirmation)" = "$(git rev-parse main)" && test "$(git merge-base main codex/wmb-m13-confirmation)" = "$(git rev-parse main)"`
- `test "$(git diff --name-only main...codex/wmb-m12-confirmation)" = "tests/test_public_pm_bench_triggerbench.py"`
- `test "$(git diff --name-only main...codex/wmb-m13-confirmation)" = "tests/test_public_working_memory_action_probe.py"`
- `uv run pytest -q tests/test_public_pm_bench_triggerbench.py tests/test_public_working_memory_action_probe.py`
- `uv run ruff check tests/test_public_pm_bench_triggerbench.py tests/test_public_working_memory_action_probe.py`
- `git diff --check && test -z "$(git status --porcelain)"`

### Task 1: Establish the exact integration lease
- [x] Refresh `origin`, verify clean root/branch state and exact canonical-main hash, and stop if main advanced, either satellite changed, or either satellite is not based on canonical main.
- [x] Inspect `main...codex/wmb-m12-confirmation` and `main...codex/wmb-m13-confirmation`; confirm the aggregate diff modifies exactly the two authorized test files with no generated files, secrets, dependency churn, or production behavior.
- [x] Create one isolated Worktrunk integration branch from exact canonical main with an explicit two-file lease; do not write directly to `main` or modify this GoalEx controller branch.

### Task 2: Integrate the reviewed satellite heads
- [ ] Apply M12 commits `c86b29ab` then `18871c2d` and M13 commit `d6befbc8` without rewriting their test semantics.
- [ ] Confirm the resulting diff contains only `tests/test_public_pm_bench_triggerbench.py` and `tests/test_public_working_memory_action_probe.py`; abort on conflicts or any required out-of-lease change.
- [ ] Inspect the combined assertions to ensure M12 explicitly proves only the declared schedule/update/cancel/tick, regularity, late-event, and cost-gap disclosures, while M13 explicitly records its single seed/capacity and missing promotion-control limitations.
- [ ] Confirm neither test converts blocked gaps into implemented capability or upgrades publication, upstream-comparability, independence, admission, or evidence labels.

### Task 3: Verify the combined exact head
- [ ] Run both focused test files together, then Ruff on both files and `git diff --check`.
- [ ] Run the repository’s applicable non-official test matrix without launching external benchmarks, paid providers, containers, protected datasets, or measured pilot cells; report any unrelated environmental failure literally instead of weakening the gate.
- [ ] Review the final diff for trust-boundary leakage, fixture gold reaching policy inputs, scope/isolation regressions, executable payloads, automatic promotion, secrets, risky files, and changes outside the two-file lease.
- [ ] Record the exact candidate SHA and prove both reviewed satellite heads are represented by the candidate diff.

### Task 4: Deliver through exact-head gates
- [ ] Push the integration branch normally, open a PR against `main`, and require exact-head tests, Ruff, review findings, unresolved-thread clearance, and mergeability clearance.
- [ ] Fix only confirmed findings within the two-file lease; if a finding requires production, adapter, fixture, documentation, or shared-contract changes, fail closed and return the dependency instead of widening scope.
- [ ] After normal merge, verify the merge contains the exact reviewed two-file diff, exact-merge CI is green, canonical local `main` fast-forwards cleanly to `origin/main`, and the GoalEx worktree remains clean.
- [ ] Refresh CBM once after merge and record one deduplicated durable milestone stating that M12/M13 gained test-only development confirmation while remaining `PROPOSED`, non-publishable, non-headline-eligible, non-independent, and non-upstream-comparable.
