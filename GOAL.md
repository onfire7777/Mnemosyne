# Goal: Phase 13 MemoryAgentBench Upstream Submission Envelope

## Objective

Implement P13-MAB-B, the next dependency-ready BENCH-006 source package: a
deterministic, fail-closed submission envelope built from the already-validated
four-competency MemoryAgentBench score result.

This package prepares an upstream submission path only. It must not download or
run held-out datasets, tune on test data, invent measured results, publish a
claim, access production, satisfy the protected Phase 12 attempt, or claim
Phase 15 hardware proof.

## Merged Baseline

P13-MAB-A merged to `main` at `f6ec163f`. Its deterministic scorer validates
and reports retrieval, test-time learning, long-range understanding, and
conflict resolution separately without an aggregate headline. P13-MAB-B
extends that merged scorer; it does not replace or duplicate it.

## Controlling Sources

- `.planning/ROADMAP.md` — Phase 13
- `.planning/REQUIREMENTS.md` — BENCH-006 and RAIL-001..004
- `.planning/STATE.md`
- `docs/superpowers/plans/2026-07-15-W4-neutral-adapter-suite-plan.md` — Phase 2
- `docs/EXECUTION-PLAN-B-Benchmark-and-Leaderboard.md`
- `docs/plans/2026-07-26-phase13-memoryagent-contract.md`
- `eval/public/adapters/memoryagentbench.py`

## Exact Lease

- `GOAL.md`
- `eval/public/adapters/memoryagentbench.py`
- `tests/test_public_memoryagentbench.py`
- `docs/plans/2026-07-26-phase13-memoryagent-upstream.md`

No other tracked path may change. `GOAL.md` and the round plan may update their
own task and verification state.

## Acceptance Contract

- Reuse `score_cases`; do not duplicate competency validation or aggregation.
- Accept only an exact lowercase 40-hex upstream dataset revision and an exact
  non-empty protocol identifier without surrounding whitespace.
- Emit one canonical submission mapping containing a fixed schema version,
  pinned dataset revision, protocol identifier, and the four separate
  competency results in canonical order.
- Never emit an overall, composite, weighted, or averaged-across-competencies
  headline.
- Reject malformed fields, booleans, non-finite values, missing/extra
  competencies, unknown keys, unpinned revisions, and non-canonical whitespace
  through `MemoryAgentBenchError`.
- Output must be deterministic for equivalent case orderings and require no
  filesystem, network, dataset, judge, CLI, or production access.
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

### Task 1: Freeze the submission contract

- [x] Add focused RED tests for the canonical envelope and fail-closed metadata.
- [x] Commit the RED contract.

### Task 2: Implement the minimum envelope

- [x] Add the stdlib-only submission builder in the leased adapter module.
- [x] Make focused tests green without I/O or new dependencies.
- [x] Commit the implementation.

### Task 3: Review and deliver

- [x] Run both native review stages and repair confirmed findings.
- [x] Complete local verification and exact-lease checks. (30 focused tests,
  unrestricted MCP-extra full pytest, Ruff, diff, lease, secret, and risky-file
  checks passed; one intervening runtime-lock fixture race passed on exact-node
  reproduction and the authoritative full rerun completed successfully)
- [ ] Push, open/update the PR, clear exact-head CI and both reviewers, and merge
  normally. (the implementation head is pushed; reviewed successor commits and
  PR delivery remain pending)
- [ ] Verify post-merge main CI, then refresh CBM/Gbrain once.

## Completion

Finish only after normal merge and exact post-merge main CI. This package does
not complete BENCH-006: upstream acceptance, identical-harness execution, and
real per-competency results remain evidence-gated follow-ups.
