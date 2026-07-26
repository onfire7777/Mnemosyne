# Goal: Phase 13 MemoryAgentBench Competency Contract

## Objective

Implement P13-MAB-A, the first dependency-ready Phase 13 source package: a
deterministic MemoryAgentBench scoring contract that reports retrieval,
test-time learning, long-range understanding, and conflict resolution
separately. It must never hide a weak competency behind an aggregate score.

This is source preparation only. It must not download or run held-out datasets,
tune on test data, publish a result, access production, satisfy the protected
Phase 12 attempt, or claim Phase 15 hardware proof.

## Controlling Sources

- `.planning/ROADMAP.md` — Phase 13
- `.planning/REQUIREMENTS.md` — BENCH-006 and RAIL-001..004
- `.planning/STATE.md`
- `docs/superpowers/plans/2026-07-15-W4-neutral-adapter-suite-plan.md` — Phase 2
- `docs/EXECUTION-PLAN-B-Benchmark-and-Leaderboard.md`
- `eval/public/` existing public-harness contracts

## Exact Lease

- `GOAL.md`
- `eval/public/adapters/memoryagentbench.py`
- `tests/test_public_memoryagentbench.py`
- `docs/plans/2026-07-26-phase13-memoryagent-contract.md`

No other tracked path may change. `GOAL.md` and the round plan may update their
own task and verification state.

## Acceptance Contract

- Accept only a supplied, canonical in-memory sequence of scored cases; perform
  no I/O, network access, dataset acquisition, judging, or benchmark execution.
- Require exactly the four canonical competencies: `retrieval`,
  `test_time_learning`, `long_range_understanding`, and
  `conflict_resolution`.
- Validate identifiers, finite numeric scores in `[0, 1]`, and non-empty
  competency coverage; fail closed on malformed, missing, duplicate, unknown,
  NaN, infinity, or boolean scores.
- Emit deterministic per-competency counts and means in canonical order.
- Do not emit an overall, composite, weighted, or averaged-across-competencies
  headline.
- Add focused RED tests first, then the smallest stdlib-only shared-flow
  implementation.
- Run both native review stages, focused tests, unrestricted MCP-extra full
  pytest, full Ruff, diff, exact-lease, secret, and risky-file checks.
- Commit and push intentionally, open/update a PR, require exact-head CI,
  CodeRabbit, Greptile, clear review state and threads, then merge normally.
- Verify exact post-merge main CI before refreshing CBM/Gbrain and admitting the
  next lease-disjoint package.

## Operating Contract

- Native RalphEx only: plan/task/review `gpt-5.6-sol:low`, Codex executor,
  external review none, at most 12 iterations.
- Work only in this Worktrunk checkout and exact lease.
- Hermes dispatch remains zero; no fleet or legacy automation binding.
- Apply Ponytail, TDD, receiving-review, systematic-debugging, and
  verification-before-completion where triggered.
- Use CBM first for code structure, context-mode for large outputs, and Gbrain
  only after a coherent merged milestone.
- Never direct-push main, force-push, bypass hooks/checks, dismiss reviews,
  fabricate evidence, or run protected production/hardware gates.

## Tasks

### Task 1: Freeze the contract

- [x] Add focused RED tests for the four separate competencies and fail-closed
  boundary behavior.
- [x] Commit the RED contract.

### Task 2: Implement the minimum scorer

- [x] Add the stdlib-only scorer in the leased adapter module.
- [x] Make focused tests green.
- [x] Commit the implementation.

### Task 3: Review and deliver

- [x] Run both native review stages and repair confirmed findings.
- [x] Complete local verification and exact-lease checks.
- [x] Push, open/update the PR, clear exact-head CI, CodeRabbit, Greptile, and
  all review threads, then merge normally.
- [x] Verify post-merge main CI, then refresh CBM/Gbrain once.

## Completion

Completed 2026-07-26 after PR #74 merged normally as `main@f6ec163f`; exact-head
CI, CodeRabbit, Greptile, and both review threads cleared on reviewed head
`e345e3b5`; and post-merge main CI run `30217700006` succeeded. The merged
review hardening keeps oversized integers and whitespace-bearing identifiers
inside the fail-closed validation boundary.

Local closure evidence:

- `PYTHONPATH=src uv run --extra mcp pytest -q tests/test_public_memoryagentbench.py`
  — 20 passed.
- `uv run ruff check eval/public/adapters/memoryagentbench.py tests/test_public_memoryagentbench.py`
  — all checks passed.
- `git diff --check` — clean.
- Exact-head CI run `30217070318` on `e345e3b5` passed the unrestricted
  MCP-extra test environment (`uv run --locked python -m pytest`) and full Ruff
  (`uv run --locked ruff check .`).
- `git diff --name-only 16af34d7..e345e3b5` returned exactly the four paths in
  the Exact Lease; the risky-file scan returned no matches.
- `gitleaks git --log-opts='16af34d7..f6ec163f' --no-banner` scanned all six
  feature commits and found no leaks.

This package does not complete BENCH-006: the upstream-pinned dataset adapter,
identical-harness execution, and real per-competency results remain
evidence-gated follow-ups. The previously reconciled Phase 16 L4 source package
remains complete, while PBPP, Part-I, Register-A, identical-treatment,
operator-entry, publication, protected Phase 12, and Phase 15 hardware gates
remain unsatisfied.
