# Phase 13 MemoryAgentBench Competency Contract

## Scope

P13-MAB-A freezes the deterministic scoring boundary required by BENCH-006 and
W4 Phase 2. It reports the four MemoryAgentBench competencies separately and
forbids an aggregate headline.

## Exact Lease

- `GOAL.md`
- `eval/public/adapters/memoryagentbench.py`
- `tests/test_public_memoryagentbench.py`
- `docs/plans/2026-07-26-phase13-memoryagent-contract.md`

## Delivery

- [ ] RED: freeze canonical ordering, validation, and separate reporting.
- [ ] GREEN: implement the smallest stdlib-only in-memory scorer.
- [ ] REVIEW: run both native stages and repair confirmed findings.
- [ ] VERIFY: focused/full pytest, Ruff, diff, lease, secret, risky-file.
- [ ] INTEGRATE: branch push, PR, exact-head CI/reviews, normal merge, main CI.

## Non-Goals

- No dataset download, held-out run, tuning, judge, production access,
  publication, Phase 12 protected attempt, or Phase 15 hardware claim.
- No overall/composite score and no new dependency.
