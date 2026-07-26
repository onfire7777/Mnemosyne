# Goal: Phase 16 L2 Static Leaderboard Renderer

## Objective

Implement P16-L2-C, the dependency-ready package after the merged signed run
ledger: a deterministic, static-first leaderboard renderer with a
per-question trace browser. The renderer consumes only validated synthetic or
already-published artifacts. It must not run protected benchmarks, publish a
headline number, or claim that production, hardware, governance, Register A,
or launch gates are complete.

## Why This Package Is Ready

- P16-L2-A (result contract) and P16-L2-B (signed run ledger) are merged.
- Post-merge `main` CI for PR #67 is green at
  `b386d5f58edb27a89eb02079f5f220397e04fdf0`.
- The approved package order names P16-L2-C immediately after P16-L2-B.
- No open pull request, active RalphEx/Goalex process, or Hermes dispatcher
  owns this lease. The Hermes gateway has
  `HERMES_KANBAN_DISPATCH_IN_GATEWAY=0`.
- This package is local, deterministic code. Phase 12 protected production
  evidence and Phase 15 physical 8 GiB hardware proof remain explicit
  non-code gates and are not exercised here.

## Controlling Sources

Read and reconcile these before planning or editing:

- `.planning/ACTIVE-GOAL-OPERATING-CONTRACT.md`
- `.planning/OPS-HANDOFF-AND-OWNERSHIP.md`
- `.planning/STATE.md`
- `.planning/ROADMAP.md`
- `.planning/REQUIREMENTS.md`
- `docs/CODEX-HANDOFF-EXECUTION-PROMPT.md`
- `docs/EXECUTION-PLAN-B-Benchmark-and-Leaderboard.md`
- `docs/governance/BOARD-STATUS.md`
- `docs/governance/CREDIBILITY-MODEL.md`
- `docs/governance/METHODOLOGY.md`
- `docs/governance/OPERATOR-FIREWALL.md`
- `leaderboard/schema/result-v1.schema.json`
- `leaderboard/validate.py`
- `leaderboard/ledger.py`
- `eval/public/bundle.py`

Traceability: Phase 16 L2 and `LEAD-001` require a durable public,
versioned-results surface and a browser for disclosed per-question traces.
The public benchmark plan requires each trace to show what was stored, what
was retrieved, and the final answer. P16-L2-C renders that already-defined
evidence; it does not create or certify evidence.

## Exact Lease

The loop may modify only:

- `GOAL.md`
- `leaderboard/render.py`
- `tests/test_leaderboard_render.py`
- `docs/plans/2026-07-26-phase16-static-renderer.md`

If correct implementation requires any other path, stop and report the
boundary change instead of widening the lease.

## Acceptance Contract

1. Use the Python standard library and existing repository code; add no
   frontend framework, package, service, database, or network dependency.
2. Accept one result record or an array, validate every record through the
   existing leaderboard contract, and fail closed without partial output on
   malformed, non-finite, duplicate, or contract-invalid input.
3. Consume the existing public-bundle trace contract rather than inventing a
   second trace schema. Reject malformed, duplicate, or unlinked trace rows.
4. Emit a self-contained static output directory with:
   - a leaderboard index containing system, track, benchmark/version,
     publication label, operator disclosure, metrics, and immutable artifact
     digests;
   - stable links from each result to its disclosed per-question traces;
   - trace pages that expose stored context/evidence, retrieved
     context/evidence, and final answer fields present in the source trace;
   - explicit non-publishable/operator-run labels without upgrading any
     credibility claim.
5. Output is byte-deterministic for identical logical input regardless of
   input record/trace ordering, uses stable filenames, UTF-8, LF line endings,
   HTML escaping, and relative links only.
6. Write through a temporary sibling and atomically replace the destination
   only after the complete render succeeds; a failure leaves the previous
   output intact.
7. Focused tests must prove deterministic output, escaping, stable linking,
   validation failure, duplicate/unlinked trace rejection, honest publication
   labels, and atomic failure behavior.
8. Run focused renderer tests, the full repository suite with the declared
   MCP extra, full Ruff, diff/lease checks, and secret/risky-file checks.

## Operating Contract

- Native RalphEx only. Plan, task, review, and monitoring use
  `gpt-5.6-sol:low`; executor is Codex; external review is `none`.
- Hermes and legacy automation remain off and unbound.
- Work only in the Worktrunk checkout
  `/Users/admin/Mnemosyne.codex-phase16-static-renderer` on
  `codex/phase16-static-renderer`.
- Ponytail governs every implementation choice. Apply relevant Superpowers
  TDD, review, debugging, and verification checkpoints and existing GSD
  project state without creating a competing lifecycle.
- CBM is primary repository discovery and must be checked/refreshed before
  code reasoning and at meaningful code milestones. Gbrain is the durable
  project-knowledge layer and syncs after coherent committed/merged
  milestones. Context-mode retains command, log, and document captures.
  Record an ADR only for a durable architectural decision.
- Reconcile code, GitHub, canonical docs, planning state, CBM, and Gbrain only
  when evidence changes.
- Use the normal GitHub lifecycle: deliberate leased commit, normal push, PR,
  exact-head CI and review, ordinary repair, normal merge only when all gates
  are green and review state clears, then post-merge main verification.
- Never direct-push to main, force-push, bypass hooks/checks, dismiss reviews,
  fabricate evidence, run protected production work, or modify another
  worktree.
- Maximum 12 rounds (never above 20). Preserve normal 15-minute stall,
  rate-limit, failure, lease-overlap, and dirty-worktree guards.

### Task 1: Freeze the renderer contract and RED tests

- [x] Reconcile the controlling sources and existing public-bundle trace contract.
- [x] Write `docs/plans/2026-07-26-phase16-static-renderer.md` with the exact data
  flow, output tree, failure semantics, and acceptance commands.
- [x] Add focused tests in `tests/test_leaderboard_render.py` that initially fail
  for the missing renderer and cover every Acceptance Contract item.
- [x] Run the focused test file and record the expected RED result before writing
  implementation code.

### Task 2: Implement the minimal static renderer

- [x] Add `leaderboard/render.py` using only the standard library plus the existing
  validator.
- [x] Make the focused tests green with the smallest shared-flow implementation.
- [x] Keep all output deterministic, escaped, relative, and atomically published.
- [x] Do not add a framework, dependency, server, database, or new artifact schema.

### Task 3: Verify, review, and prepare normal delivery

- [x] Run the focused renderer tests, full repository pytest with the MCP extra,
  full Ruff, `git diff --check`, exact-lease verification, and secret/risky
  surface checks.
- [x] Review the complete diff against every controlling source and acceptance
  item; repair confirmed findings inside the lease only.
- [x] Leave a deliberate leased commit ready for normal push/PR/exact-head gates.
  Do not merge, bypass, dismiss, force-push, or modify `main`.

## Completion

Finish only when the leased implementation is merged normally, post-merge
main CI is green, CBM and Gbrain are refreshed, and the next
dependency-ready, lease-disjoint package has been identified. If a real gate
blocks progress, preserve the worktree and report the exact evidence.
