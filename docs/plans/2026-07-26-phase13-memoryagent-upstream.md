# Phase 13 MemoryAgentBench Upstream Submission Envelope

## Scope

P13-MAB-B adds the deterministic submission envelope required after the merged
four-competency scoring contract. It pins upstream identity and preserves
separate competency reporting without running or publishing benchmark evidence.

## Exact Lease

- `GOAL.md`
- `eval/public/adapters/memoryagentbench.py`
- `tests/test_public_memoryagentbench.py`
- `docs/plans/2026-07-26-phase13-memoryagent-upstream.md`

## Delivery

- [x] RED: freeze canonical metadata, ordering, and fail-closed behavior.
- [x] GREEN: implement the smallest stdlib-only submission builder.
- [x] REVIEW: both native stages completed; the confirmed reporting and module
  docstring findings were repaired.
- [x] VERIFY: 30 focused tests, unrestricted MCP-extra full pytest, Ruff, diff,
  lease, secret, and risky-file checks passed; one intervening runtime-lock
  fixture race reproduced green in isolation before the successful full rerun.
- [ ] INTEGRATE: reviewed successor commits, PR, exact-head CI/reviews, merge,
  and main CI remain pending.

## Non-Goals

- No dataset download, held-out run, tuning, judge, production access,
  upstream submission, publication, Phase 12 protected attempt, or Phase 15
  hardware claim.
- No aggregate score, new dependency, filesystem access, or network access.
- Hermes dispatch remains zero; no fleet or legacy automation binding.
