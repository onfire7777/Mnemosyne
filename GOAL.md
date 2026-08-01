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

The active scheduling policy is the committed DAG/write-lease map at
`docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md` **as it
stands on current `main`** — never a frozen revision of that file, since any
pinned SHA re-authorizes launches that later merges already retired. Its
package statuses must be recomputed from current main after every merge; the
map is not blanket permission to launch stale or overlapping lanes.

The whole-memory standard and pilot plan are executable authority on canonical
`main`. They were imported from verified clean handoff
`605ecd3ddf7faf308f664f0869e5e2eb431afa7d`. The closed ABI and bounded
remediation merged through PRs #79-#80; reviewed development pilots M01/M10,
M12/M13, M03, and M15 merged through PRs #81-#84. PR #85 froze the Phase
13-15 execution contracts, and PR #86 merged the development-only scheduled
regression workflow as
`main@661343ce05186e9a7f0f0740d1edef7c23532857`:

- `docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md`
- `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`

Do not copy, edit, commit, stash, reset, or otherwise consume uncommitted work
from `/Users/admin/Mnemosyne.codex-whole-memory-benchmark-spec`. Do not touch
`/Users/admin/Mnemosyne.codex-phase16-signed-publication`; both are external
leases until their owners land or hand them off.

## Current Phase

**Phase 13 development-source lane delivered; reconcile truth before fresh admission.**

WMBS-A/WMB-P1 authority, traceability, the closed common ABI, fail-closed
reference validation, and the bounded M01/M03/M10/M12/M13/M15 development
pilots are merged through PR #84. PR #85 froze one Phase 13 plan, one Phase 14
plan, and four ordered Phase 15 plans without claiming their gated evidence.
PR #86 merged the two-file scheduled-regression source at exact head
`baf5c1852593885e37eed75da69b02d93e1bff11`; manual development operability
run `30561430522` and exact post-merge main CI run `30561266140` passed on the
exact merge commit. PR #87 then merged the canonical truth reconciliation at
`main@2ba4ed80` (post-merge CI `30566984814`), PR #88 merged public-regression
README documentation plus hardened workflow contract tests at `main@4a891042`
(post-merge CI `30659705054`), and PR #89 merged the post-PR-#88 recomputation
of the dependency/write-lease map and `.planning/STATE.md` at `main@a8e9444c`
(post-merge CI `30672194635`). PR #90 then landed the previously stranded
M12/M13 development gap disclosures in `eval/public/README.md`, their two
pinning test suites, a cert-rotator lock-timeout flake fix, and the
pilots-plan delivery checkpoints at `main@061c2e1c` (exact-head CI
`30679262270`, post-merge CI `30680201900`), which is the current canonical
baseline. PRs #87-#90 are documentation and test-contract only: none admitted
a new implementation package or changed a benchmark, measurement, admission
state, or publication claim, and M12/M13 remain `PROPOSED` /
`publishable:false` / `pbpp_headline_eligible:false`. The controller branch is
merged to `main@061c2e1c`, so its remaining undelivered delta is exactly:
`GOAL.md`, `.planning/STATE.md`, and the lease map (recording PR #90's
post-merge receipts on top of earlier lifecycle content that was itself never
delivered, including the PR #81-#84 whole-memory Decisions entry in
`.planning/STATE.md`), the pilots-plan PR #90 checkpoint, and 25 round records
touched since round 14 without being delivered through a PR: 23 new
`docs/plans/goalex-r15..r37*.md` files, the new
`docs/plans/completed/goalex-r36-*.md` file, and an undelivered edit to
`docs/plans/goalex-r14-*.md` (whose original text is already on `main`).
Landing all of them is deferred to the next round's GoalEx-owner PR so
lifecycle and public-harness leases stay unmixed; the plan-doc backlog is
disclosed here rather than left to accumulate silently. That pilots-plan
checkpoint is a correction, not an addition: PR #90 shipped
`docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`
without updating its earlier paragraph, so canonical `main@061c2e1c` still
states that the M12/M13 gap-disclosure paragraphs and their pinning tests
"are not on main and are still pending PR delivery" — a claim that same
commit falsified. Until the deferred PR lands, read that sentence on `main`
as known-stale; Tasks 7 and 8 are closed on `main` by PR #90. Fifteen of those
records (r17, r19-r21, r23-r31, r34, r35) still carry unchecked task boxes:
those boxes record the plan as written at the time and are not a delivery
signal, because each round's merged receipts are recorded here and in the
lease map rather than back-filled into the round record. The first actual
scheduled-cadence receipt and every official/upstream benchmark run remain
open.

Result-v2 remains blocked by the protected signed-publication lease. Local OCI
sandbox commits are reviewed development-source receipts only and remain
quarantined: no immutable build, daemon probe, filesystem/network/write-boundary
enforcement receipt, SBOM, provenance, or admission evidence exists. The next
package must be recomputed from current main and the committed dependency/write
lease map at
`docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`; neither
result-v2 nor sandbox delivery is implicitly admitted.

## Scope

Once the activation gate passes:

1. Reconcile the landed whole-memory standard against the current GSD state,
   roadmap, requirements, blueprint, PBPP, public harness, result-v1, ledger,
   custody, and publication contracts.
2. Execute the owner-approved pilot plan in dependency order under one
   lifecycle/integration owner. Admit parallel Worktrunk implementation lanes
   only when the dependency map proves their exact write leases are disjoint;
   shared schemas, registries, runners, planning, and docs stay serialized.
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
3. Select the highest-value dependency-ready package set within the map's
   sustained concurrency ceiling. Every lane uses an isolated Worktrunk and an
   exact disjoint file lease; serialize on any path or ancestry overlap, and
   preserve unowned dirty work.
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
   language, and result compatibility. Use focused tests during repair and one
   authoritative full suite on each stable exact PR head; do not duplicate
   broad suites across lanes. Push normally; require a PR, review/thread/
   mergeability clearance, and post-merge `main` proof. Never force-push,
   bypass hooks, dismiss findings, or write directly to main.
8. After merge, safely fast-forward canonical local `main`, prove it equals
   clean `origin/main`, reconcile affected canonical truth, then refresh CBM
   once and sync one deduplicated durable Gbrain milestone. Do not refresh both
   before and after the same reconciliation.
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

Achieved for the current development-source milestone:

- owner-landed hardened specification and implementation plan;
- merged compound schema, reference validator, focused contract fixtures, and
  bounded M01/M03/M10/M12/M13/M15 development pilots through PR #84;
- frozen Phase 13-15 execution contracts through PR #85;
- normal PR #86 exact-head CI/review/merge gates plus passing input-free manual
  development operability run `30561430522` and passing exact post-merge main
  CI run `30561266140`;
- documentation- and contract-test-only reconciliation through PR #87
  (`main@2ba4ed80`, post-merge CI `30566984814`), PR #88 (`main@4a891042`,
  post-merge CI `30659705054`), PR #89 (`main@a8e9444c`, post-merge CI
  `30672194635`), and PR #90 (`main@061c2e1c`, exact-head CI `30679262270`,
  post-merge CI `30680201900`), none of which changed a benchmark,
  measurement, admission state, or publication claim.

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
git merge-base --is-ancestor 661343ce05186e9a7f0f0740d1edef7c23532857 main
git merge-base --is-ancestor a95fe4d291093253f8ce49adff32ba875a35e884 main
git merge-base --is-ancestor baf5c1852593885e37eed75da69b02d93e1bff11 main
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
