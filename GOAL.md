# Goal: Phase 16 L2 Public Result Contract

## Objective

Implement the first dependency-ready production-code package from the approved
benchmark/leaderboard track: a versioned public leaderboard result contract and
a deterministic, fail-closed validator for Phase 16 L2.

This package establishes the machine-readable boundary consumed later by the
append-only run ledger and static leaderboard renderer. It must not publish a
score, run a protected benchmark, or claim Phase 12, 14, 15, or 16 complete.

## Why This Package Is Ready

- Phase 16 explicitly permits the site and data pipeline to be built against
  the tracks that genuinely exist; unmeasured dimensions remain absent.
- The contract operates on synthetic fixtures and retained bundle metadata. It
  does not depend on Phase 12's protected production attempt or measured QA
  thresholds.
- It does not depend on Phase 15's physical 8 GiB hardware proof or remaining
  capability/evidence work.
- There are no open pull requests, and this isolated worktree owns the lease
  below.

## Controlling Sources

Read these before planning or editing. They are authoritative over this goal:

- `/Users/admin/Mnemosyne/GOAL.md` (historical program goal; its own
  point-in-time warning defers live status to `.planning/STATE.md`)
- `.planning/ACTIVE-GOAL-OPERATING-CONTRACT.md`
- `.planning/OPS-HANDOFF-AND-OWNERSHIP.md`
- `.planning/ROADMAP.md`
- `.planning/STATE.md`
- `.planning/REQUIREMENTS.md`
- `.planning/phases/12-grounded-multi-hop-answer-synthesis/12-04-PLAN.md`
- `.planning/runbooks/COMPACT-MODEL-8GB-ACCEPTANCE.md`
- `docs/CODEX-HANDOFF-EXECUTION-PROMPT.md`
- `docs/EXECUTION-PLAN-B-Benchmark-and-Leaderboard.md`
- `docs/benchmark/MEMORY-NATIVE-BENCHMARK.md`
- `docs/governance/BOARD-STATUS.md`
- `docs/governance/CHARTER.md`
- `docs/governance/CREDIBILITY-MODEL.md`
- `docs/governance/METHODOLOGY.md`
- `docs/governance/OPERATOR-FIREWALL.md`
- `eval/public/README.md`
- `eval/public/bundle.py`
- `eval/public/runner.py`
- `docs/superpowers/specs/2026-07-15-world-best-memory-platform-design.md`
- `docs/superpowers/plans/2026-07-15-W4-neutral-adapter-suite-plan.md`

Traceability: the historical program goal explicitly requires Phases 13-16
agent-owned work and names W4's reproducibility standard plus leaderboard
preparation. The live roadmap's revised Phase 16 sequencing permits the site and
data pipeline before full Phase 15 closure, while the active-goal and operations
contracts forbid treating local code/tests as production evidence. This package
implements only that data-contract seam and leaves the higher-priority,
operator-owned production capture path untouched.

The Phase 13, 14, and 16 decomposition is:

1. **P16-L2-A (this goal, ready):** versioned result contract plus deterministic
   validator.
2. **P16-L2-B (after A):** append-only signed run ledger and recorded-absence
   semantics.
3. **P16-L2-C (after B):** static data renderer and per-question trace browser.
4. **P13-M1.4/M1.5:** MemoryAgentBench and BEAM adapters, separately leased;
   their real results remain gated by pinned upstream inputs and disclosed
   reader configuration.
5. **P13-M1.6:** scheduled regression-only CI after the deterministic adapter
   inventory is explicit.
6. **P14-M2/M3:** bundle-level one-command reproduction demonstration after a
   headline-eligible retained result exists; never fabricate reproduction.
7. **P16-L3/L4:** content and launch only after the data pipeline exists and
   Register A is evidenced.

## Exact Lease

The implementation may modify only:

- `GOAL.md`
- `leaderboard/schema/**`
- `leaderboard/validate.py`
- `leaderboard/__init__.py`
- `tests/test_leaderboard_result_contract.py`
- the round plan under `docs/plans/`

Do not modify product retrieval, storage, reader, benchmark adapter, governance,
planning, release, deployment, or hardware code. If the package cannot be
completed inside this lease, stop and report the required boundary change.

## Operating Context

Use CBM/codebase-memory-mcp as the primary source for repository discovery and
understanding: verify the index, then use architecture/schema, graph search,
traces, snippets, impact, and ADRs as relevant. Use Gbrain as the primary
durable project-knowledge layer. Check/refresh CBM before code reasoning and
after meaningful code milestones; sync Gbrain after coherent committed or
merged milestones without duplicating another memory owner's content. Use
context-mode for retained command/log/document captures and derivation, keeping
only derived findings active. Restrict text search to precise literals, config,
errors, or an identified graph gap. Reconcile code, GitHub, canonical docs,
planning state, and memory surfaces against verified evidence. These are
operating practices, not additional launch gates.

Deliver every coherent package through its isolated Worktrunk branch: inspect
the diff and secret/risky-file surface, run relevant checks, commit
intentionally, push the branch, and open or update its pull request. Monitor
exact-head CI and review, fix confirmed failures inside the lease, and merge
normally only when required checks and reviews are green and GitHub reports the
pull request mergeable. Never push directly to `main`, force-push, bypass hooks
or checks, or merge unresolved failures. Verify post-merge `main` CI before
milestone planning/docs/CBM/Gbrain synchronization and selection of the next
dependency-ready package.

## Loop Authority and Continuity

Later user instructions supersede earlier conflicts. Run native RalphEx with
`gpt-5.6-sol:low` for plan, task, review, and monitoring; keep external review,
Hermes, and legacy automation bindings off. Use a fresh Worktrunk-isolated
worktree for each dependency-ready package, Ponytail for every implementation
choice, and only the Superpowers/GSD workflows triggered by the work.

Continue autonomously across ordinary configuration/startup failures, test or
CI failures, review findings, branch/PR synchronization, documentation/planning
drift, CBM/Gbrain refreshes, recoverable stalls, and rate limits. Stop only for
a real safety gate, a scope-changing decision, or a blocker that cannot be
repaired inside the lease. Record an ADR only for a durable architectural
decision, refresh canonical docs/planning only when evidence changes their
truth, and report only substantive verified progress or blockers.

## Acceptance Criteria

1. A versioned JSON Schema defines one leaderboard result record with:
   system identity; track and benchmark version; immutable run/build/config
   fingerprints; bundle and trace provenance; metric-family-separated metrics
   with confidence intervals; judge disclosure when a judged metric is present;
   publication eligibility; operator-entry disclosure; and version/supersession
   links that preserve history.
2. A standard-library validator provides a deterministic command that validates
   one record or a JSON array of records and exits nonzero with stable,
   path-specific errors for malformed input.
3. Validation fails closed for missing provenance, mixed retrieval and judged-QA
   metric families, absent judge disclosure, mutable/unpinned identifiers,
   ineligible development results presented as publishable, and destructive
   history replacement.
4. Validation accepts a minimal synthetic deterministic-retrieval fixture and a
   minimal synthetic disclosed-judge fixture. Fixtures contain no measured
   Mnemosyne claim and no protected data.
5. Tests cover the valid contracts and each fail-closed rule without network,
   protected-environment, external-custody, or hardware access.
6. No new dependency is added. Existing public bundle conventions are reused
   where they already define fingerprints, hashes, or trace references.
7. Documentation and errors call the result/operator-run and auditable; they do
   not use the stronger neutral label unless optional Register B is actually
   satisfied.

## Non-Goals and Hard Gates

- Do not run Phase 12's protected environment, single protected attempt,
  production Postgres parity, or production evidence capture.
- Do not create, alter, or claim external custody evidence or copy expected
  fingerprints from a bundle under review.
- Do not run or simulate Phase 15's physical 8 GiB hardware acceptance.
- Do not generate public benchmark numbers, tune on held-out/test data, or
  mark any requirement or phase complete.
- Do not implement the ledger, website, adapters, scheduled CI, or launch in
  this package.
- Do not enable or use the Hermes fleet.

## Verification

```sh
uv run pytest -q tests/test_leaderboard_result_contract.py
uv run ruff check leaderboard tests/test_leaderboard_result_contract.py
git diff --check
```

## Completion Evidence

The goal is complete only when the acceptance tests pass, the worktree contains
a verified implementation commit inside the exact lease, and the
`gpt-5.6-sol:low` review stages report no unresolved high-confidence finding. A
passing local contract test is not evidence for any protected production or
hardware gate.
