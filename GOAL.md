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

One carve-out applies and has never closed. It arose while the GoalEx lifecycle
delivery was deferred: `main`'s copy of that map was two merges behind (`Baseline: main@4a891042`; its
merged-baseline list ended at PR #88, so it carried neither a PR #89 nor a
PR #90 row), and the recomputed map at `Baseline: main@061c2e1c` existed only on
the controller branch, which made the branch-resident map the operative
revision. **That carve-out is now reduced to receipt scope.** PR #91 was the
deferred GoalEx-owner delivery: it landed the recomputed map, `GOAL.md`,
`.planning/STATE.md`, the pilots-plan PR #90 checkpoint, and the round-record
backlog on `main` (merge `e157e035`, exact-head CI `30686224929`, post-merge CI
`30687385118`), so the bulk gap is closed and `main`'s map is no longer two
merges behind. It is **not** yet fully closed. `main@e157e035`'s copy of the map
still reads `Baseline: main@061c2e1c` with `T3` as `DELIVERING` and "**This PR
is the delivery**", because PR #91 could not describe its own merge from inside
the commit being merged. The recomputation to `Baseline: main@e157e035`
carrying PR #91's receipt block and `T3` as `MERGED` exists only on the
controller branch, which kept the branch-resident map the operative revision
at exactly that receipt-level scope until this update is itself delivered
through the `T4` follow-up PR. **This PR is that `T4` delivery**: it lands the
receipt-level recomputation on `main`, discharging the carve-out down to the
accepted one-block standing residue described next. The same applies to `main`'s
`GOAL.md` and `.planning/STATE.md`,
whose present-tense "this PR" self-references PR #91 falsified on merge. This
`T4` delivery regenerates a one-block residue of its own for the same
structural reason: no commit can describe its own merge, so `main`'s copy always
lags the controller branch by exactly one receipt block. That one-block lag is
an accepted standing condition, not an open work item. `T4` was admitted once to
discharge the accumulated receipt block; `T4`'s own residue admits no successor
node, because admitting a fresh node for each regenerated residue would make the
delivery wave non-terminating. The
carve-out's lapse rule stands unchanged: it lapses the moment any merge lands on
`main` that the branch-resident map does not already record, at which point the
map must be recomputed from current `main` before it is treated as operative
again.

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
`30679262270`, post-merge CI `30680201900`). PR #91 then delivered the stranded
GoalEx lifecycle backlog at `main@e157e035` (exact-head CI `30686224929`,
post-merge CI `30687385118`), which is the current canonical baseline.
PRs #87-#91 are documentation and test-contract only: none admitted
a new implementation package or changed a benchmark, measurement, admission
state, or publication claim, and M12/M13 remain `PROPOSED` /
`publishable:false` / `pbpp_headline_eligible:false`. PR #91 landed exactly:
`GOAL.md`, `.planning/STATE.md`, and the lease map (recording PR #90's
post-merge receipts on top of earlier lifecycle content that had itself never
been delivered, including the PR #81-#84 whole-memory Decisions entry in
`.planning/STATE.md`), the pilots-plan PR #90 checkpoint, and the 26 round
records touched since round 14 without being delivered through a PR: 23 new
`docs/plans/goalex-r15..r38*.md` files, the two new
`docs/plans/completed/goalex-r36-*.md` and
`docs/plans/completed/goalex-r37-*.md` files, and the edit to
`docs/plans/goalex-r14-*.md` (whose original text was already on `main`).
That delivery kept the lifecycle and public-harness leases unmixed; it was
carried by lease-map node `T3`, now `MERGED`. The wave that held it is closed
and admits no source node. The lease map has been recomputed from the
resulting `main@e157e035` and now carries PR #91's own receipt block; that
recomputation was branch-resident: it, this file's and `.planning/STATE.md`'s
matching post-merge text, and the round-38 record were the controller branch's
entire remaining delta versus `main`. **This PR is the `T4` delivery that lands
them** — the documentation-only receipt-level lifecycle update carried by
lease-map node `T4`, the sole writer admitted from this baseline, which admits
no source node. After it merges the lease map must be recomputed from the
resulting `main` before any further admission, leaving only the accepted
one-block receipt residue. The
plan-doc backlog is
disclosed here rather than left to accumulate silently. That pilots-plan
checkpoint is a correction plus PR #90's receipt block — it rewrites one stale
paragraph and adds a new twelve-line `Gap-disclosure delivery:` receipt in the
M12/M13 checkpoint section: PR #90 shipped
`docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`
without updating its earlier paragraph, so canonical `main@061c2e1c` still
stated that the M12/M13 gap-disclosure paragraphs and their pinning tests
"are not on main and are still pending PR delivery" — a claim that same
commit falsified. That sentence was known-stale on `main` from PR #90 until
PR #91 replaced it; Tasks 7 and 8 are closed on `main` by PR #90. Fifteen of those
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
`docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`, read
under the receipt-scope remainder of the Authority carve-out above for as long
as that remainder is open; neither result-v2 nor sandbox delivery is implicitly
admitted.
That map admits no source node at this baseline — its only node is
the documentation-only receipt-level lifecycle update `T4`, which this PR
delivers and which itself admits no source node — so the next source
admission waits on an external gate opening, and the map must be recomputed
from then-current `main` at that time.

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
11. End every round leaving no round-owned residue in the controller worktree.
    This is unconditional for everything the round itself touched: no round
    outcome may leave a round-owned change — tracked or untracked — sitting in
    the controller worktree. Unowned dirty work that predates the round is the
    sole exception; rule 3 still governs it, and it is preserved untouched.
    Post-merge receipts, canonical-truth reconciliation, and plan-checkbox
    closure are part of the round, not afterthoughts — commit them on the
    controller branch as the round's final step, before yielding. The external
    GoalEx launcher aborts its next preflight on a dirty tree, so residue left
    behind stalls the loop instead of carrying forward.

    The unowned-work exception is checked at round start, not round end. If the
    controller worktree already carries unowned dirty work when the round
    begins, do not start the round: the tree cannot be brought clean without
    violating rule 3. Park instead, as an explicit owner handoff — record the
    unowned paths and their owner outside the controller worktree, and treat
    the loop as halted, not merely paused. This park is the one case that does
    not resume automatically: the launcher's preflight will keep aborting, by
    design, until that owner resolves their own paths. A round that does start
    therefore always ends with an empty residue check, and the launcher's next
    preflight always finds a clean tree.

    Ignored paths that already exist at round start are a permitted baseline,
    not blockers: they never trip the start-of-round gate above, and no round
    may deliberately modify or remove one. At round start, capture them as a
    manifest that enumerates every entry recursively — an ignored directory
    gets its own row *and* a row per entry beneath it, since a directory row
    alone cannot see a nested rewrite while omitting it would let a
    directory's own mode change unnoticed — each row carrying relative path,
    object type, content hash or symlink target, and mode. Keep a lossless
    copy of their contents outside the controller worktree, with one
    carve-out: every ignored path known to be secret-bearing is manifested but
    never copied out, because `Mnemosyne-Secret-Handling-Policy.md`'s P8
    forbids materializing a secret value anywhere persistent outside the secret
    store while explicitly permitting non-secret metadata, which a path, type,
    mode, and content hash are. The carve-out is a classification, not a fixed
    list: it covers the operator secret channel `CONFIG-DRIFT-CHECKS.md`
    designates and the secret patterns the root `.gitignore` carries (`.env`,
    `.env.*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `credentials.json`,
    `service-account.json`, `secrets.json`), and equally the generated provider
    material `infra/.gitignore` ignores and `infra/README.md` documents as
    secrets, private keys, and tokens (`keycloak/out/`, `vault/out/`,
    `c2pa/out/`, `**/wrapped-keys/`), whose members — `keycloak/out/admin-password`
    among them — match no filename pattern at all. Any ignored path a later
    `.gitignore` or its documentation designates the same way is covered on the
    same footing without amending this rule. All of this is needed: a bare
    `git status --porcelain` reports no ignored file at all, the `--ignored`
    listing reports an unchanged path and a rewritten one identically, and a
    hash alone can detect an accidental rewrite without being able to undo it.
    The residue check compares every manifest row — path, object type, hash or
    symlink target, and mode — against the full start-of-round manifest, so a
    mode-only or nested-only change must fail it, alongside
    `git status --porcelain --untracked-files=all --ignored`. If a round does
    rewrite a baseline ignored file anyway, that is the one case where cleanup
    restores such a path: preserve the round's version externally under the
    lossless procedure below, then restore the whole affected subtree — bytes,
    modes, symlinks, and deletions — from the external copy and record the
    violation in the round record. A secret-bearing path has no external copy
    to restore from by design, so a round that rewrites one restores nothing:
    it escalates to the operator under rule 10 and parks under the handoff
    above until they resolve it.

    If any round-owned change cannot be committed — a receipt, a scratch
    artifact, a partial edit, tracked, untracked, or ignored alike — preserve
    it without leaving residue. Preserve it losslessly: write an exact patch or
    archive outside the controller worktree, one that carries deletions,
    renames, mode changes, symlinks, and binary content, since copying file
    text alone silently drops all of those. Then clear the change from both the
    index and the worktree — a staged-but-uncommitted path left staged is still
    dirty — restoring the tracked paths this round modified and removing the
    untracked or ignored files this round created. Touch nothing the round does
    not own. Then confirm the residue check above reports nothing for every
    round-owned path. Record the external path and the blocker in a summary
    that also lives outside the controller worktree. Relocation means
    preserve-then-clear: moving a tracked file leaves its original path
    deleted, which is still dirty.

    A deliberate park of round-owned work is subject to the same invariant and
    to the same lossless preservation procedure — a park is not a licence to
    discard a partial edit or an uncommitted receipt. Preserve every round-owned
    change externally first, clear it from the index and worktree, then write
    the park's reason, owner, and the archive's location outside the controller
    worktree before stopping, so the loop can resume without a human first
    cleaning up after it.

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
  `30672194635`), PR #90 (`main@061c2e1c`, exact-head CI `30679262270`,
  post-merge CI `30680201900`), and PR #91 (`main@e157e035`, exact-head CI
  `30686224929`, post-merge CI `30687385118`), none of which changed a
  benchmark, measurement, admission state, or publication claim.

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
git merge-base --is-ancestor 061c2e1c13cbf1fd5324361a6ff61f47cd2a6534 main
git merge-base --is-ancestor e157e0350c503c9cde4aca0eff71d643a4adb200 main
# Exact canonical baseline. Ancestry alone also passes when `main` carries later,
# unrecorded merges, which is precisely the condition under which the Authority
# carve-out lapses. This equality is the lapse detector: if it fails, `main` has
# advanced past the recorded baseline and the carve-out must be recomputed from
# the new `main` before any further admission.
test "$(git rev-parse main)" = "e157e0350c503c9cde4aca0eff71d643a4adb200"
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
