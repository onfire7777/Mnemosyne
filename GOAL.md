# Goal: Phase 13 BEAM Reader Disclosure Contract

## Objective

Implement `P13-BEAM-A`, the next dependency-ready BENCH-006 source package: a
deterministic, fail-closed BEAM disclosure envelope that reuses the public
harness candidate-manifest validator and binds it to an exact dataset revision
and frozen protocol identifier.

This is source preparation only. It must not download or run BEAM, invoke a
reader or judge, invent measured results, publish a claim, access production,
satisfy the protected Phase 12 attempt, or claim Phase 15 hardware proof.

## Merged Baseline

P13-MAB-A and P13-MAB-B are merged through `main@c78ee4e6`. They provide the
four-competency MemoryAgentBench scorer and canonical upstream submission
envelope. Exact post-merge main CI run `30223962377` succeeded.

Phase 16's six source packages remain complete, while PBPP, Part-I, Register-A,
identical-treatment, operator-entry, publication, protected Phase 12, and
Phase 15 hardware gates remain unsatisfied.

## Controlling Sources

- `.planning/ROADMAP.md` — Phase 13
- `.planning/REQUIREMENTS.md` — BENCH-006 and RAIL-001..004
- `.planning/STATE.md`
- `docs/superpowers/plans/2026-07-15-W4-neutral-adapter-suite-plan.md`
- `docs/EXECUTION-PLAN-B-Benchmark-and-Leaderboard.md` — M1.5
- `eval/public/runner.py` — existing candidate-manifest validation

## Exact Lease

- `GOAL.md`
- `eval/public/runner.py`
- `eval/public/adapters/beam.py`
- `tests/test_public_beam.py`
- `docs/plans/2026-07-26-phase13-beam-contract.md`

No other tracked path may change. `GOAL.md` and the round plan may update their
own task and verification state.

## Acceptance Contract

- Reuse `validate_candidate_manifest`; do not duplicate its candidate, model,
  prompt, decoding, custody, or digest validation.
- Keep the shared candidate-manifest validator filesystem-free when callers
  supply no explicit protocol, while preserving the separate registry-loading
  verification path.
- `canonical_qa_protocol()` is the public in-memory contract source;
  `load_qa_protocol()` separately verifies the checked-in registry custody.
- Accept only an exact lowercase 40-hex BEAM dataset revision and a non-empty
  protocol identifier with no surrounding whitespace.
- Emit one canonical mapping with a fixed schema version, dataset revision,
  protocol identifier, and a canonical copy of the validated candidate
  manifest.
- Reject malformed manifests, unknown/missing manifest keys, booleans,
  non-finite values, unpinned revisions, and non-canonical identifiers through
  one BEAM-specific `ValueError` subtype.
- Be deterministic for equivalent manifest mappings and require no filesystem,
  network, dataset, model, judge, CLI, production, or hardware access.
- Add focused RED tests first, observe the expected failures, then write the
  smallest stdlib-only shared-flow implementation.
- Run both native review stages, focused tests, unrestricted MCP-extra full
  pytest, full Ruff, diff, exact-lease, secret, and risky-file checks.
- Commit and push intentionally, open/update a PR, require exact-head CI,
  CodeRabbit, Greptile, clear review state and threads, then merge normally.
- Verify exact post-merge main CI before refreshing CBM/Gbrain and admitting the
  next lease-disjoint package.

## Operating Contract

- Native RalphEx only: plan/task/review `gpt-5.6-sol:low`, Codex executor,
  external review none, workspace-write, at most 12 iterations.
- Work only in this Worktrunk checkout and exact lease.
- Hermes dispatch remains zero; no fleet or legacy automation binding.
- Apply Ponytail, TDD, receiving-review, systematic-debugging, and
  verification-before-completion where triggered.
- Use CBM first for code structure, context-mode for large output, and Gbrain
  only after a coherent merged milestone.
- Never direct-push main, force-push, bypass hooks/checks, dismiss reviews,
  fabricate evidence, or run protected production/hardware gates.

## Tasks

### Task 1: Freeze the disclosure contract

- [x] Add focused RED tests for the canonical envelope and fail-closed inputs.
- [x] Run the focused tests and record the expected missing-feature failure.
- [x] Commit the RED contract after the supervisor repaired the Worktrunk
  metadata writable-root boundary.

### Task 2: Implement the minimum envelope

- [x] Add the stdlib-only BEAM disclosure builder using the existing manifest
  validator.
- [x] Make focused tests green without I/O or new dependencies.
- [x] Commit the implementation after the supervisor repaired the Worktrunk
  metadata writable-root boundary.

### Task 3: Review and deliver

- [x] Add focused RED regressions for filesystem-free shared validation and
  nested-value isolation, then apply the smallest dependency-free fixes.
- [x] Run both native review stages and repair confirmed in-lease findings.
- [x] Complete local verification and exact-lease checks. (22 focused tests,
  unrestricted MCP-extra full pytest, full Ruff, diff, exact-lease, secret,
  and risky-file checks passed.)
- [ ] Push, open/update the PR, clear exact-head CI and both reviewers, and merge
  normally.
- [ ] Verify post-merge main CI, then refresh CBM/Gbrain once.

## Completion

Finish only after normal merge and exact post-merge main CI. This package does
not complete BENCH-006: actual BEAM execution, disclosed reader measurements,
hardware evidence, and publication remain separate gated work.
