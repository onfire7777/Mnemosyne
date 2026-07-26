# Phase 16 Launch-Readiness Gate Plan

## Scope

P16-L4-A turns the existing LEAD-003 launch conditions into a deterministic
local admission check. It validates supplied evidence; it does not collect,
manufacture, or publish evidence.

## Dependency Trace

- `.planning/REQUIREMENTS.md` LEAD-003 requires PBPP, Part I results, Register A
  gates, identical treatment, and the Mnemosyne operator-entry label.
- `.planning/ROADMAP.md` keeps Phase 12 production evidence and Phase 15
  hardware proof open and operator-gated.
- The merged Phase 16 result contract, run ledger, renderer, signed publication,
  and metric taxonomy provide the existing leaderboard substrate.

## Exact Lease

- `GOAL.md`
- `leaderboard/readiness.py`
- `tests/test_leaderboard_readiness.py`
- `docs/plans/2026-07-26-phase16-launch-readiness.md`

## Delivery

1. Freeze canonical ready, blocked, invalid, and deterministic-output behavior
   with RED tests.
2. Implement one stdlib-only validator and CLI that reads only its input file.
3. Run native review and the full local verification matrix.
4. Push the Worktrunk branch, open a PR, require exact-head CI and both review
   bots, merge normally, and verify post-merge main CI.

## Non-Goals

- No protected Phase 12 attempt or production access.
- No Phase 15 hardware claim.
- No benchmark execution, external publication, or launch claim.
- No environment, network, clock, or prior-run inference.
