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
- [ ] GREEN: implement the smallest stdlib-only submission builder.
- [ ] REVIEW: run both native stages and repair confirmed findings.
- [ ] VERIFY: focused/full pytest, Ruff, diff, lease, secret, risky-file.
- [ ] INTEGRATE: branch push, PR, exact-head CI/reviews, normal merge, main CI.

## Non-Goals

- No dataset download, held-out run, tuning, judge, production access,
  upstream submission, publication, Phase 12 protected attempt, or Phase 15
  hardware claim.
- No aggregate score, new dependency, filesystem access, or network access.
- Hermes dispatch remains zero; no fleet or legacy automation binding.
