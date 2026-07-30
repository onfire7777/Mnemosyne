# Goal: Whole-Memory Pilot and Dependency-Ready Mnemosyne Continuation

## Objective

Continuously advance the authoritative Mnemosyne program from this dedicated
GoalEx worktree. First land and implement the smallest trustworthy whole-memory
reference-harness pilot authorized by the owner-landed hardened specification
and implementation plan. After that pilot is merged and exact-head CI is green,
reassess the canonical GSD roadmap and advance only the highest-value
dependency-ready, lease-disjoint source task.

GoalEx is the cross-task coordinator. RalphEx may execute one bounded round
under GoalEx, but RalphEx never selects the program direction.

## Authority

This goal does not create a second roadmap. Task status and dependency order
remain owned by:

- `.planning/STATE.md`
- `.planning/ROADMAP.md`
- `.planning/REQUIREMENTS.md`
- `.planning/MILESTONES.md`
- approved repository plans and specifications
- live GitHub PR, review, and CI state

The whole-memory standard and pilot plan are executable authority on canonical
`main`. They were imported from verified clean handoff
`605ecd3ddf7faf308f664f0869e5e2eb431afa7d`; the first closed-ABI slice merged
by PR #79 at `a95fe4d291093253f8ce49adff32ba875a35e884`, its bounded remediation
merged by PR #80 at `28805ccf54f99f098a5abc23fe6f1155400d0f22`, and the reviewed M01/M10
development pilots merged by PR #81 at
`392b1fc173f454893e1b133ff3a727462586a8b0`, and the bounded M12/M13
development-evidence confirmations merged by PR #82 at
`7e9cd01feb2a31cbba96252943697245a4edd024`. The bounded M03 valid-time
development slice then merged by PR #83 at
`7f60d8ba8274a8ac8036a80737467654f862008f`:

- `docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md`
- `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`

Do not copy, edit, commit, stash, reset, or otherwise consume uncommitted work
from `/Users/admin/Mnemosyne.codex-whole-memory-benchmark-spec`. Do not touch
`/Users/admin/Mnemosyne.codex-phase16-signed-publication`; both are external
leases until their owners land or hand them off.

## Current Phase

**Bounded M03 valid-time slice delivered — M15 composed replay slice next.**

WMBS-A/WMB-P1 authority, traceability, the closed common ABI, and fail-closed
reference validation landed through PR #80. PR #81 then merged exact M01/M10
source head `98b83e4be373cf0acd5411769b80b98dfd1a8caa`; exact-merge CI run
`30506775012`, 507 focused tests, and Ruff passed on
`main@392b1fc173f454893e1b133ff3a727462586a8b0`. Round 18 proved that the
mapped seven-path M03 lease cannot persist caller-supplied `valid_from`: both
authorized assertion/supersession write methods live in excluded
`src/mnemosyne/mcp_tools.py`, and bypassing them would skip authorization.
The integration owner has now admitted that one additional path so the existing
authorized write facade can accept an optional timezone-aware `valid_from`;
direct engine/table writes, caller-controlled `valid_to`, and caller-controlled
`transaction_time` remain forbidden. PR #82 merged the bounded M12/M13 test-only
confirmations as `main@7e9cd01f`; exact-head CI run `30521721192`, exact-merge
CI run `30522846090`, and 46 focused tests passed. M12/M13 remain `PROPOSED`
and non-publishable. PR #83 merged reviewed source head
`3189cc24c570f12be06e3d04252a06f48c71f971` as
`main@7f60d8ba8274a8ac8036a80737467654f862008f`. Exact-head CI run
`30532543366` and exact-merge CI run `30534061552` passed all required jobs,
CodeRabbit and Greptile were green, and all review threads were resolved. This
is a bounded valid-time development slice only: full
transaction-time/bitemporal M03 remains deferred, and the result remains
`PROPOSED`, non-publishable, non-headline-eligible, non-independent, and
non-upstream-comparable.

The committed dependency/write-lease map remains the admission authority. The
highest-value dependency-ready package is now M15 canonical replay and the
composed M01→M03→M10 development slice. It has this exact shared-file lease,
owned only by the integration owner:

- `eval/public/bundle.py`
- `eval/public/adapters/whole_memory_reference.py`
- `tests/test_public_whole_memory_reference.py`
- `tests/test_public_eval.py`

Result-v2 remains blocked by the protected signed-publication lease, and the
sandbox lane remains quarantined until it provides real OCI, filesystem,
network, and write-boundary enforcement. Five-run/new-process reproduction,
measured cells, hardware receipts, official runs, and publication remain behind
their existing operator/evidence gates.

## Scope

Once the activation gate passes:

1. Reconcile the landed whole-memory standard against the current GSD state,
   roadmap, requirements, blueprint, PBPP, public harness, result-v1, ledger,
   custody, and publication contracts.
2. Execute the owner-approved pilot plan in dependency order with one active
   exact implementation lease at a time.
3. Prefer the smallest feasible pilot: closed ABI and validators, development
   sandbox/metering receipt, existing public-runner registration, and only the
   explicitly authorized M01/M03-valid-time/M10/M12/M13/M15/M20 development
   cells.
4. Preserve official-suite comparability and keep official, enhanced, and
   exploratory evidence separate.
5. After each normally merged round, refresh live `main`, GitHub gates, CBM,
   and durable Gbrain knowledge before selecting another task.
6. After the pilot is merged, continue only with the next dependency-ready
   source phase already present in the canonical GSD roadmap.

## Non-Goals

- No benchmark ranking, certification, superiority, launch, or production
  claim without held-out reproducible evidence and the required human approval.
- No official external benchmark substitution with synthetic or development
  fixtures.
- No production, hardware, custody, protected-dataset, paid-provider, or
  operator evidence fabrication.
- No publication, leaderboard activation, or result-v1 reinterpretation.
- No parallel benchmark lifecycle, runner, evidence store, result ledger, or
  roadmap.
- No Hermes fleet enablement and no direct writes to canonical `main`.
- No speculative implementation of all twenty modules.

## Approval and Operator Gates

The following remain blocked unless their owning canonical contract and human
operator supply the required evidence:

- Tier-B production validation and real-provider-forbid-local receipts.
- Protected or licensed dataset access and official external-suite execution.
- P32/H8 or other hardware-profile measurements.
- PBPP publication eligibility, signed custody, neutral/independent review
  labels, and public leaderboard activation.
- Any comparative or superiority claim.

An unavailable gate is recorded with its owner, missing evidence, and next safe
action. It is never widened, bypassed, averaged away, or relabeled as complete.

## Bounded Task-Selection Rules

For every GoalEx round:

1. Refresh canonical `main`, worktrees, dirty state, active tasks/processes,
   open PRs, reviews, CI, usage, and resource gates.
2. Reject any task that is dependency-blocked, operator-gated, leased, stale,
   broader than an approved plan, or merely housekeeping when substantive
   dependency-ready product or benchmark engineering exists.
3. Select exactly one highest-value task on an isolated Worktrunk branch with
   an explicit file lease. Preserve unowned dirty work and prevent redundant
   writers.
4. Apply Ponytail fully: reuse current contracts/code, then stdlib/platform,
   then installed dependencies; make the smallest tested root-cause change
   without speculative abstractions or dependencies.
5. Use context-mode for large output and resumable analysis. Refresh/query CBM
   before broad code reads, run impact analysis for risky diffs, and update ADRs
   only for genuine source-grounded architecture decisions.
6. Use GSD as lifecycle authority and only the relevant Superpowers checkpoint:
   approved design/planning, isolated worktrees, TDD, debugging, execution,
   review, verification, or branch completion.
7. Review trust boundaries, secrets, supply chain, failure modes, evidence
   language, and result compatibility. Use focused local tests during repair
   and exactly one authoritative repository-wide suite per stable candidate:
   the required exact-head CI run. Do not duplicate that broad suite locally.
   Push normally; require a PR, review/thread/mergeability clearance, and
   post-merge `main` proof. Never force-push, bypass hooks, dismiss findings,
   or write directly to main.
8. After merge, safely fast-forward canonical local `main`, prove it equals
   clean `origin/main`, refresh CBM once, and sync one deduplicated durable
   Gbrain milestone rather than transient session facts.
9. Update only affected GSD state, plans, canonical docs, architecture/ADRs,
   benchmark contracts, and the real owner-discovered wiki. Never create a
   second wiki, roadmap, memory owner, or duplicate canonical content.
10. Self-repair routine transport, sandbox, CI, auth-independent, worktree, and
    review issues. Escalate only safety, authority, protected-environment, or
    product-direction decisions, then reassess the next lease-disjoint package.

## Runtime Contract

- Dedicated worktree:
  `/Users/admin/.codex/worktrees/9697/Mnemosyne`
- Branch: `codex/goalex-whole-memory-pilot`
- GoalEx planner/verifier: isolated derived launcher
  `.goalex/bin/goalex-sol` using `gpt-5.6-sol:low`.
- Bounded RalphEx plan, task, and review stages: `gpt-5.6-sol:low`.
- Claude/Fable planning, dual planning, dual review, and Hermes are disabled.
- Bounded guards: at most 20 rounds per process, three consecutive execution
  failures, three consecutive no-commit stalls, 15-minute idle timeout, and
  two-hour per-session timeout.
- Hermes fleet remains off.

## Success Evidence

Achieved for the closed-ABI slice and bounded remediation:

- owner-landed hardened specification and implementation plan;
- merged compound schema, reference validator, and focused contract fixtures;
- normal PR #79 review, exact-head CI, merge, and post-merge main proof.
- normal PR #80 remediation review, exact-head clearance, merge, exact-merge CI
  run `30484986865`, refreshed CBM, and a deduplicated Gbrain milestone.
- normal PR #81 review and merge of exact source head `98b83e4b`; exact-merge
  CI run `30506775012`, 507 focused tests, Ruff, refreshed CBM, and retained
  `publishable:false` / `pbpp_headline_eligible:false` boundaries.

The remaining whole-memory pilot milestone still requires:

- reviewed deterministic fixtures/generators, scorers, baselines,
  inferential plan, sandbox/metering contract, BOM/rights disclosures, resource
  receipts, and result-v1-compatible additive evidence contract;
- only honest development labels such as `PILOT-READY-DEV`,
  `publishable:false`, and `pbpp_headline_eligible:false`;
- focused and applicable full tests, Ruff, documentation/reference checks,
  security review, diff/lease/risky-file/secret checks;
- normal PR review, exact-head CI, merge, and exact post-merge main CI;
- refreshed CBM and a source-grounded Gbrain milestone.

The continuous program completes only when no approved dependency-ready source
task remains. Operator-gated work may remain blocked, but its owner and missing
evidence must be explicit.

## Verification

```bash
set -euo pipefail
test "$(pwd -P)" = "/Users/admin/.codex/worktrees/9697/Mnemosyne"
test "$(git branch --show-current)" = "codex/goalex-whole-memory-pilot"
test -z "$(git status --porcelain)"
git fetch --prune origin
test "$(git rev-parse main)" = "$(git rev-parse origin/main)"
test "$(git rev-parse main)" = "7e9cd01feb2a31cbba96252943697245a4edd024"
git merge-base --is-ancestor 98b83e4be373cf0acd5411769b80b98dfd1a8caa main
git merge-base --is-ancestor a3ca8108c22de350810dc3f574931a0d85810ed5 main
test -f .planning/STATE.md
test -f .planning/ROADMAP.md
test -f .planning/REQUIREMENTS.md
test -f docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md
test -f docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md
grep -q 'Proposed subordinate standard' \
  docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md
grep -q 'Whole-Memory Reference Harness and Pilot Modules Implementation Plan' \
  docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md
```
