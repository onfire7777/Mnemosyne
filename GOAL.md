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

## Current Priority (operator directive, 2026-08-03)

**Build the benchmark itself. The Whole-Memory Benchmark Standard specifies
modules M01-M20; only five are implemented.** Everything downstream — Phase 12
measured closure, the official adapters, reproduction, and the leaderboard —
presumes a benchmark that does not yet exist. Completing it is the single
highest-value thing this loop can do, and unlike the evidence gates it is
almost entirely *ungated*: exact plans, deterministic fixtures, scorers, and
tests are ordinary source work needing no operator authorization.

Measured at `main@b8673031`:

- implemented (`eval/public/wmbs_*.py`): **M01, M02, M04, M05, M10** — 5 of 20
- registry-admitted: **M01, M10** — 2 of 20
- per-module implementation plans: **M02, M04, M05, M14** — 4 of 20
- no plan and no module: **M06, M07, M08, M09, M11, M16, M17, M18, M19, M20**

**Execute the existing plans and specifications as written. Do not rewrite
them.** The standard, the roadmap, the phase plans, and the approved
implementation plans are the authority and are not to be revised, restructured,
reworded, or "improved" by this loop. Where an approved plan looks wrong,
incomplete, or contradicted by the tree, **surface it in the round record and
stop — do not edit it.** The only documents this loop authors are the ones an
approved plan itself calls for, plus the lifecycle receipts the lease map
requires. Optimise for progressing through the existing plans fully and
completely, not for producing new prose.

**Round 0 of this directive: take an inventory, in the round record.** Before
choosing module work, determine for each of M01-M20 whether an approved exact
plan, fixture, scorer, test suite, and registry entry exist, and its admission
state. Recompute this from the tree rather than trusting the counts above, and
correct them if they are wrong. Keep it in the round record; do not create a new
tracked document for it unless an approved plan already calls for one.

**Then work the ladder, one module at a time, cheapest genuine gap first.** The
`U-MODULES` row authorizes no artifact until an approved exact plan exists, so
for each module the order is fixed and must not be short-circuited:

1. **If, and only if, the module has no approved exact plan**, author one
   (protocol, scorer contract, fixture design, license/custody, dependency
   placement). This is the missing artifact `U-MODULES` explicitly requires
   before any code, so writing it is mandated — it is not a revision of an
   existing plan. **If an approved plan already exists (M02, M04, M05, M14),
   skip straight to step 3 and implement it as written.**
2. Freeze/approve that new plan the way PR #85 froze the Phase 13-15 contracts.
3. Implement the deterministic fixture and scorer against the frozen closed
   ABI, test-first, conforming to `$defs.portable_event` where the plan claims
   conformance.
4. Land it through a reviewed PR with exact-head CI green, then record the
   receipts in the lease map row that authorized it.

**Efficiency rules — these are what "optimized" means here:**

- Finish one module completely before starting another. A half-built module is
  worth nothing and costs a future round to rediscover.
- Never re-plan, re-derive, or re-litigate an already-approved plan. Read it
  and execute it. Planning effort belongs only on modules that have no plan.
- A round that produces only lifecycle bookkeeping is a wasted round. It is
  never sufficient on its own.
- Reuse established precedent instead of reinventing: M01 is the conforming
  reference for fixture and `public_metadata` shape, M05 for provenance, M10
  for abstention scoring. Copy the pattern; do not invent a second one.
- Modules with an approved plan already written (M02, M04, M05, M14) and those
  whose fixtures already exist but whose scorer does not (M03, M12, M13, M15
  are candidates — verify in the inventory) are far cheaper than greenfield
  modules and must come first.

Also outstanding, and to be assessed rather than ignored: unlanded work on
`codex/goalex-r26-sandbox` (9 commits, development sandbox + OCI isolation),
`codex/wmb-m04-stage-a` (M04 scorer review-gap fix),
`codex/goalex-r23-m03-valid-time`, and `codex/whole-memory-benchmark-spec`
(2 standard-hardening docs). These predate the current baseline and were never
merged. Where the map requires an admission decision before landing them,
**surface that decision rather than bypassing it.**

Lifecycle/reconciliation bookkeeping is now the *lowest* priority and is never
a sufficient round on its own. Rounds 36-43 were consumed almost entirely by
it; that backlog is discharged.

**The percentage is an output, never a target.** These are hard rules:

- Never edit `progress.completed_plans`, `progress.completed_phases`, or
  `progress.percent` except as the arithmetic consequence of a plan whose work
  is actually delivered and merged. Moving a counter without the underlying
  delivery is a fabrication and violates the no-fabrication rule below.
- Never mark a plan, phase, requirement, or capability complete on the strength
  of a document alone. A plan is complete when its code, its tests, and its
  documentation are merged and exact-head CI is green.
- Items gated on operator or external evidence — P12-E operator measurement,
  P13-C a real scheduled event, P13-O official upstream admission, production
  Postgres/PPR parity, physical-hardware and held-out evidence — **stay gated**.
  Do not synthesize their evidence, weaken their validators, or reclassify them
  to reach a higher number. If every ungated plan is exhausted, say so and stop
  rather than manufacturing progress.

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
merges behind. That receipt-level remainder has since been delivered too:
`T4` merged as PR #92 at `main@39cfa67a` (exact-head CI `30693874030`,
post-merge CI `30694818231`), landing the recomputation to
`Baseline: main@e157e035` with `T3` as `MERGED` plus PR #91's receipt block, and
the matching `GOAL.md` and `.planning/STATE.md` text, on `main`. PR #93 then
merged independently from a separate lane at `main@effc5e03` (exact-head CI
`30718912376`, post-merge CI `30719645207`), so the carve-out's explicit lapse
rule fired. The residue was no longer receipt-only: it contained an undelivered
test contract and the r39, r40, and r41 round records. Exactly one node, `T5`,
was admitted to discharge that bounded residue. It admitted no source node.
This terminates because the lapse was triggered by an independent external
merge, not by the residue regenerating itself. `T5` merged as PR #94 at
`main@2091d01c` (exact head `41b21305`,
exact-head CI `30730185494`, post-merge CI `30730918452`). It discharged the
test-contract residue without admitting a source node, but omitted the r42
record from its own `docs/plans/` lease. `T6` discharged that residue and the
r42/r43 records as PR #95 at `main@42abaab7` (exact head `d7c0938f`, exact-head
CI `30737466988`, post-merge CI `30738303497`). It admitted no source node and
no successor node; this branch-resident recomputation is its own accepted
standing-condition residue.

PRs #96-#99 then advanced canonical `main` through `main@d7eefb7c`; PR #99
delivered `T7` and `T8`, the documentation-and-tests-only disclosure and
inventory nodes. PR #101 discharged PR #99's baseline lapse at
`main@58ae5bba`, and PRs #103, #106, and #107 advanced `main` through
`main@7f305090` without changing the whole-memory admission boundary. PR #100
then delivered `T9` as the bounded M03 registry-reachability node: exact head
`e072dda5a9e7ef078d317156c49c54bbee7a5124`, all required exact-head CI and
Greptile green in run `31854371658`, merge
`b3570937918c7de40cd89ea543fab9e7b16f7471` at
`2026-08-15T01:12:26Z`, and successful post-merge CI `31855873247`. The
subsequent PR #105 preserved hash-bound LF text and made installer/custody tests
explicit about native-Windows and POSIX execution contracts: exact head
`d60857fdf61122106eeede789432dd5bac955137`, all required exact-head CI green in
run `31856191898`, merge `7b6c5a121107ee80533a5b4ec794e602e1e1ab33`
at `2026-08-15T01:46:23Z`. Its post-merge run `31857410462` failed solely at
`tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
(1 failed, 4709 passed, 151 skipped, 191 deselected) because PR #105 was absent
from the lifecycle authorities. PR #108 repaired that lapse from exact head
`bda5588abc2a181c1bd7b5ae17ca31deeae7d85e`, with all required exact-head CI
green in run `31859014653`, and merged as
`7c5264d815d44c375173dcd1e8ab57783a397a7e` at
`2026-08-15T02:45:01Z`; post-merge run `31859997325` succeeded. Controller PR
#113 then delivered the three-file `T10` reservation from exact head
`c1bf6a10335e30fe797c54a42285922552647a9e`, with all required exact-head CI
green in run `31863057094`, as merge
`6929fd3703ff262d3264b58a5af90d506a804da2` at
`2026-08-15T04:22:14Z`; post-merge run `31864254074` succeeded. PR #109 then
merged from audited topology head
`cb44f21296fc22cf92f847b8201a6881e915400c`, after all required and native-
Windows checks passed in exact-head run `31865413163`, as
`6801fbd0b34565dc3dbe915e8d1f6e04455cb9e4` at
`2026-08-15T05:24:36Z`. That merge raced this lifecycle amendment; post-merge
run `31866875258` completed successfully at `2026-08-15T05:51:12Z`; no later
stack edge opened before that gate closed. The
carve-out is therefore recomputed from `main@6801fbd0`. `T7`, `T8`, and `T9` are all
**MERGED**, and no writer remains admitted from that wave. None is a source
node or admits a successor node. `T9` changed reachability only: M03 remains
`PROPOSED` / `publishable:false` / `pbpp_headline_eligible:false`, with no
fixture, scorer, schema, admission-state, or progress-counter change.

Controller node `T10` reserves the Windows portability stack by immutable
non-lifecycle content anchors: PR #109
`08397dab1220c87a3e8e3a92bf353cc65b68dba3` -> PR #110
`7e282b7c95f51a6446e25d92f8284de261551703` -> PR #111
`226e4416a4e76671d7ca079fe97664b8617f5bfa` -> PR #112
`259a6361355ab80cbbfa75ca1a6de6ec4b1f9a96`. Repository ruleset `19157561`
enforces strict required-check freshness, so PR #113 correctly made those
pre-controller full heads behind `main`. Their first topology-only refresh onto
`main@6929fd37` produced PR #109
`cb44f21296fc22cf92f847b8201a6881e915400c` -> PR #110
`26f95a09827d3e56ffe86e65b7db7493ecf79c73` -> PR #111
`02a724e9333a47a1cb7096d59b558ab80c1e5300` -> PR #112
`c8d95dafe5131f965591b84aeabb095fac34f1b6`. Each refreshed tree is byte-for-
byte identical to its content anchor outside `GOAL.md`, `.planning/STATE.md`,
and the lease map. Exact-head CI runs `31865413163`, `31865422216`,
`31865430468`, and `31865438529` all completed successfully, including every
required and native-Windows job. Fresh exact refreshed-stack security scan
`e95df6b0-da9d-4688-a2a0-4378be4973d1` covers all 32 changed files with zero
findings; its binary diff hash exactly matches the approved cumulative stack at
`f538e11916f0621cb951f8393debb66e032abaa69c9053fb4562c9d245fc778d`.
PR #109 is **MERGED** at `main@6801fbd0`; its implementation content and
pre-merge gates matched this receipt, but its merge preceded the amendment and
is recorded as a sequencing deviation rather than silently reclassified as
compliant. PRs #110-#112 remain open drafts. No later edge may merge until PR
#109's post-main CI is green; this amendment must still land before the next
edge. Their lifecycle blobs
already satisfy the stronger parent-equality invariant: #110 equals current
`main`, #111 equals #110, and #112 equals #111. Controller amendment PR #114
is **OPEN/DRAFT** and changes only `GOAL.md`, `.planning/STATE.md`, and the
lease map. Its self-record changes its head, so no exact PR #114 head, merge
SHA/time, or post-main CI is claimed. PR #114 must pass and merge before #110.
Topology-only merges of current `main` or the immediately
preceding stack PR are therefore permitted without another controller PR only
when all three lifecycle blobs exactly equal that parent, every non-lifecycle
blob remains equal to the corresponding content anchor, the required/native
exact-head CI is green, a fresh security review finds no issue, local/remote/
hosted heads agree, and all review threads are clear. Any lifecycle divergence
or non-lifecycle blob change voids the reservation. The controller remains the
sole CI integration owner. Merge commits for the remaining stack only in the
order #110 -> #111 -> #112 are permitted, with
successful post-merge `main` CI required before refreshing and merging each
next edge. Those already-merged T10 edges predate this executable gate and
were discharged by their recorded exact recursive-tree proofs; their legacy
anchors are not inputs to this new command. For every future topology-only
refresh whose parent and anchor descend from the commit introducing this
verifier, authenticate the permitted-parent and immutable-anchor commit IDs
independently, then obtain and run this block from the
permitted-parent `GOAL.md` blob (for example, inspect it with
`git --no-replace-objects show "$PERMITTED_PARENT_SHA:GOAL.md"`). Never use the
candidate checkout's copy as the launcher:

```sh
(
  expected_verifier_oid=7c40b18bd0097968157708d04988e59d2e2d1ca7
  resolved_parent="$(
    git --no-replace-objects rev-parse --verify \
      "$PERMITTED_PARENT_SHA^{commit}" 2>/dev/null
  )" &&
  [ "$resolved_parent" = "$PERMITTED_PARENT_SHA" ] &&
  resolved_anchor="$(
    git --no-replace-objects rev-parse --verify \
      "$IMMUTABLE_ANCHOR_SHA^{commit}" 2>/dev/null
  )" &&
  [ "$resolved_anchor" = "$IMMUTABLE_ANCHOR_SHA" ] &&
  parent_verifier_oid="$(
    git --no-replace-objects rev-parse --verify \
      "$resolved_parent:infra/scripts/verify-topology-refresh.py" 2>/dev/null
  )" &&
  anchor_verifier_oid="$(
    git --no-replace-objects rev-parse --verify \
      "$resolved_anchor:infra/scripts/verify-topology-refresh.py" 2>/dev/null
  )" &&
  [ "$parent_verifier_oid" = "$expected_verifier_oid" ] &&
  [ "$anchor_verifier_oid" = "$expected_verifier_oid" ] &&
  topology_verifier="$(
    git --no-replace-objects show \
      "$resolved_parent:infra/scripts/verify-topology-refresh.py" 2>/dev/null
  )" &&
  [ -n "$topology_verifier" ] || {
    printf '%s\n' 'error: cannot authenticate trusted topology verifier'
    exit 2
  }
  if python3 -I -S -c '
import sys

source = sys.argv.pop(1)
try:
    exec(compile(source, "permitted-parent topology verifier", "exec"))
except SystemExit:
    raise
except Exception:
    raise SystemExit(2)
' "$topology_verifier" \
    "$CANDIDATE_SHA" \
    "$PERMITTED_PARENT_SHA" \
    "$IMMUTABLE_ANCHOR_SHA"; then
    topology_status=0
  else
    topology_status=$?
  fi
  case "$topology_status" in
    0 | 1 | 2) exit "$topology_status" ;;
    *) exit 2 ;;
  esac
)
```

It exits 0 only for a valid topology, 1 for contract deviations, and 2 for
invocation, reference-read, or tree-parse errors.

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

**Phase 12 evidence closure is the serial critical path; no fresh source node is admitted.**

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
post-merge CI `30687385118`). PR #92 then delivered the receipt-level
lifecycle update carried by lease-map node `T4` at `main@39cfa67a` (exact-head
CI `30693874030`, post-merge CI `30694818231`). PR #93 then merged the
fail-closed round-cleanup and ignored-state custody contract at
`main@effc5e03` (exact-head CI `30718912376`, post-merge CI `30719645207`),
then PR #94 delivered `T5` at `main@2091d01c` (exact head `41b21305`,
exact-head CI `30730185494`, post-merge CI `30730918452`). PR #95 then
delivered `T6` at `main@42abaab7`
(exact head `d7c0938f`, exact-head CI `30737466988`, post-merge CI
`30738303497`). PR #96 then independently delivered the development-only
M02/M04/M05 evaluation oracles at `main@088e2f31` (exact head `1050749a`, CI
`30744318093`). PR #97 then merged the round-43 review adjudication and
controller reconciliation at `main@71e492b4` (exact head `13c05d65`, exact-head
CI `30774834604`, post-merge CI `30775783472`), and PR #98 merged the
documentation-only correction of PR #97's "retired" claim back to "paused" at
`main@b8673031` (exact head `b49b0b35`, exact-head CI `30787319275`, post-merge
CI `30788531829`). PR #99 then merged the `T7`/`T8` disclosure-and-admission
work at `main@d7eefb7c` (exact head `2375aba5`, exact-head CI `30808291831`,
post-merge CI `30810160121`, which failed the lapse detector because PR #99
landed without pre-recording itself). PR #101 discharged that lapse at
`main@58ae5bba`; PRs #103, #106, and #107 subsequently advanced the recorded
history through `main@7f305090`. PR #100 then merged `T9` at
`main@b3570937`: exact head
`e072dda5a9e7ef078d317156c49c54bbee7a5124`, all required exact-head CI and
Greptile green in run `31854371658`, merge
`b3570937918c7de40cd89ea543fab9e7b16f7471` at
`2026-08-15T01:12:26Z`, and successful post-merge CI `31855873247`. PR #105
then merged at exact head `d60857fdf61122106eeede789432dd5bac955137`
after all required exact-head CI passed in run `31856191898`, as merge
`7b6c5a121107ee80533a5b4ec794e602e1e1ab33` at
`2026-08-15T01:46:23Z`. Post-merge run `31857410462` failed solely at the
canonical-baseline traceability test (1 failed, 4709 passed, 151 skipped, 191
deselected) because PR #105 was absent from the lifecycle authorities. PR #108
repaired that lapse from exact head
`bda5588abc2a181c1bd7b5ae17ca31deeae7d85e`, all-required-green exact-head CI
run `31859014653`, merge `7c5264d815d44c375173dcd1e8ab57783a397a7e`
at `2026-08-15T02:45:01Z`, and successful post-merge run `31859997325`. The
controller receipt then delivered as PR #113 from exact head
`c1bf6a10335e30fe797c54a42285922552647a9e`, all-required-green exact-head CI
run `31863057094`, merge `6929fd3703ff262d3264b58a5af90d506a804da2`
at `2026-08-15T04:22:14Z`, and successful post-merge run `31864254074`. PR
#109 then merged from exact head `cb44f21296fc22cf92f847b8201a6881e915400c`
after all required/native checks passed in run `31865413163`, as
`6801fbd0b34565dc3dbe915e8d1f6e04455cb9e4` at
`2026-08-15T05:24:36Z`; post-main run `31866875258` succeeded. The
current canonical baseline is `main@6801fbd0`. `T5` and `T6` are discharged.
Through PR #96
the recorded position was that no GoalEx lifecycle or source node is currently
admitted; PR #99 admitted and delivered `T7` and `T8`, and PR #100 has now
delivered `T9`, so no writer remains admitted from this wave. `T7` is a
documentation-and-tests node that discloses PR #96's three
development-only oracles in `eval/public/README.md` and pins the disclosure with
tests; that disclosure and its pinning suite
`tests/test_public_wmbs_stage_a_disclosure.py` are delivered. `T8` is a
documentation-and-tests node carrying the Round-0 M01-M20 module completeness
inventory, its line-level derivations, and `tests/test_wmbs_module_inventory.py`,
the drift test that pins the inventory to the tree; those are delivered too.
Neither `T7` nor `T8` admits a source node, a Stage-B integration, or a
successor node. `T7` and `T8` are **not** lease-disjoint from each other: both
write `GOAL.md`, `.planning/STATE.md`, the lease map, and `docs/plans/`, so they
are one serialized GoalEx lifecycle writer landing as a single PR, which also
holds the public-harness lease for `T7`'s `eval/public/README.md` write and
therefore requires both owners. `T9` was the public-harness Stage-B M03 registry-admission node:
it registers the `wmbs-m03-valid-time-development` cell — already fixture-,
scorer-, and adapter-backed and unit-tested on `main`, yet unreachable from
`run_public_suite` for want of a registry entry, two `runner.py` keys, and the
matching `allowed_profile` label in `eval/public/bundle.py`, whose independent
profile-contract table would otherwise reject the bundle — and nothing else.
`T9` authorizes M03 only, changes no fixture byte, no scorer logic, and no
schema, keeps M03 at `PROPOSED` / `publishable:false` /
`pbpp_headline_eligible:false` with full bitemporal transaction-time retained as
a hard deferral, and admits no successor node or source node. Its delivery by
PR #100 discharged the serialized `eval/public/*` lease; no competing or
admitted writer remains on that lease. None of the three moves an admission
state, publication claim, or progress counter.
PRs #87-#92 are documentation and test-contract only: none admitted
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
and admits no source node. The lease map was recomputed from the
resulting `main@e157e035` and carried PR #91's own receipt block; that
recomputation was branch-resident until PR #92 — the documentation-only
receipt-level lifecycle update carried by lease-map node `T4`, the sole writer
admitted from that baseline, which admitted no source node — landed it,
this file's and `.planning/STATE.md`'s matching post-merge text, and the
round-38 and round-39 records on `main` at `39cfa67a`. PR #93's independent
merge at `main@effc5e03` then lapsed the branch-resident carve-out. `T5` was the
one bounded delivery admitted to discharge the resulting non-receipt-only
residue and merged as PR #94 at `main@2091d01c`; it admitted **no source node**.
`T6` then merged as PR #95 at `main@42abaab7` (exact head `d7c0938f`,
exact-head CI `30737466988`, post-merge CI `30738303497`) and admitted no source
node or successor node. No lifecycle writer is now admitted. The
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
under the standing controller Authority carve-out above; neither result-v2
nor sandbox delivery is implicitly admitted.
That map admits no source node or current writer at this baseline: the bounded
documentation-and-tests nodes `T7` and `T8` and the bounded public-harness
reachability node `T9` are all delivered. The next source admission waits on an
external gate opening, and the map must be recomputed from then-current `main`
at that time.

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
    directory's own mode change unnoticed. Build each row from relative path
    bytes plus the `lstat` object type and permission bits, then add a
    type-specific identity field: SHA-256 over raw bytes for a non-secret
    regular file, raw `readlink` target bytes for a symlink, and for a directory
    no identity field at all, since its contents are already covered by its
    entries' own rows and path, type, and mode are what a directory can change
    on its own. Keep a lossless copy of their contents outside the controller
    worktree only when its classification permits export under the rules
    below. Secret-bearing paths are manifested but never copied out, because
    `Mnemosyne-Secret-Handling-Policy.md`'s P8 forbids materializing a secret
    value anywhere persistent outside the secret store while explicitly
    permitting non-secret metadata. A raw content hash is not such metadata
    here: for a guessable single-value secret like `keycloak/out/admin-password`
    it is an offline verification oracle for anyone who obtains the manifest.
    So a secret-bearing regular-file row records path, type, and mode plus a
    keyed digest of the local bytes whose key lives in the secret store and is
    never persisted alongside the manifest; a secret-bearing symlink applies
    the same keyed digest to its raw `readlink` target bytes, while a directory
    row still has no identity field and relies on its recursively manifested
    entries. Record secret-store version metadata too where the
    store exposes it, but never substitute that metadata for the keyed digest:
    an unchanged store version cannot detect a rewrite of its materialized
    local copy. The carve-out is a classification, not a fixed
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
    Privacy- or custody-bearing ignored state, including `.mnemosyne/` object
    stores and ignored `*.db` or `*.sqlite` files, may be copied only to an
    operator-approved encrypted custody location with explicit access and
    retention controls; absent that approval it follows the same durable park
    and operator-handoff path as secret-bearing state.
    Before admitting mutable ignored runtime state as baseline, obtain its
    owner's lock/quiescence or use the engine's native consistent-snapshot
    operation; if neither is available, park instead of hashing, copying, or
    later restoring a racing tree. Treat every permitted baseline copy as a
    temporary access-controlled snapshot. Delete it after the final successful
    manifest comparison, retaining an external archive only when an actual
    cleanup or park handoff requires recovery evidence.
    The residue check compares every manifest row — path, object type, mode,
    and the type-specific identity field — against the full start-of-round
    manifest, so a mode-only or nested-only change must fail it, alongside
    `git status --porcelain --untracked-files=all --ignored`. If a round does
    rewrite a baseline ignored file anyway, that is the one case where cleanup
    restores such a path: preserve the round's version externally under the
    lossless procedure below only when its classification permits export, then
    restore the whole affected subtree — bytes,
    modes, symlinks, and deletions — from the external copy and record the
    violation in the round record. A secret-bearing path has no external copy
    to restore from by design, so a round that rewrites one restores nothing:
    it escalates to the operator under rule 10 and parks under the handoff
    above until they resolve it. That park must be durable, because the ignored
    rewrite is invisible to the preflight that would otherwise catch it — a bare
    `git status --porcelain` reports no ignored file, so the next invocation
    would pass preflight and silently adopt the rewritten secret as its new
    permitted baseline. Write a persistent park marker outside the controller
    worktree naming the affected paths, and require the launcher to abort its
    preflight while that marker exists. Only the operator clears it, once they
    have restored or rotated the secret themselves.

    If any round-owned change cannot be committed — a receipt, a scratch
    artifact, a partial edit, tracked, untracked, or ignored alike — preserve
    it without leaving residue, subject to the secret/privacy/custody export
    restrictions above. When export is permitted, preserve it losslessly:
    write an exact patch or archive outside the controller worktree, one that
    carries deletions,
    renames, mode changes, symlinks, and binary content, since copying file
    text alone silently drops all of those. Then restore each uncommitted
    round-owned tracked path in both the index and worktree to current `HEAD` —
    which is round-start `HEAD` when the round has made no valid commit — so a
    staged-but-uncommitted path cannot remain dirty and an earlier valid round
    commit is not overwritten. Remove only the untracked or ignored files this
    round created. Touch nothing the round does not own. Require targeted
    `git diff --cached --quiet` and
    `git diff --quiet` checks for those tracked paths, then confirm the ignored
    manifest equals its round-start value and the residue check above reports
    nothing beyond the permitted baseline. Record the external path and the
    blocker in a summary that also lives outside the controller worktree.
    Relocation means preserve-then-clear: moving a tracked file leaves its
    original path deleted, which is still dirty. Before restoring or removing
    any round-owned artifact whose classification forbids export — tracked,
    untracked, or ignored — complete and verify a handoff into the canonical
    secret store or an operator-approved custody destination that is allowed
    to hold that classification. If no such destination is available, keep the
    controller stopped under the durable park, disclose the remaining residue,
    and require operator action; never delete the only copy or claim that the
    round ended clean.

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
- GoalEx planner/verifier: Opus 5 High through the canonical GoalEx planner.
- Bounded RalphEx plan, task, and review stages: `gpt-5.6-sol:low`.
- Independent post-round GoalEx review/adjudication: Opus 5 High via
  `GOALEX_DUAL_REVIEW_MODEL=opus:high`.
- Dual planning, Fable, mixed-provider native RalphEx, and Hermes are disabled.
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
  post-merge CI `30680201900`), PR #91 (`main@e157e035`, exact-head CI
  `30686224929`, post-merge CI `30687385118`), PR #92 (`main@39cfa67a`,
  exact-head CI `30693874030`, post-merge CI `30694818231`), and PR #93
  (`main@effc5e03`, exact-head CI `30718912376`, post-merge CI `30719645207`),
  and PR #94 (`main@2091d01c`, exact head `41b21305`, exact-head CI
  `30730185494`, post-merge CI `30730918452`), none of which
  changed a benchmark, measurement, admission state, or publication claim.

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

Canonical `main` may retain the accepted terminal one-block receipt residue
after a merge because no commit can describe its own merge. That terminal
canonical-state property does not weaken the executable controller-branch
check below: every controller-branch baseline mismatch is treated as a lapse, and the check fails closed.

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
git merge-base --is-ancestor 39cfa67aa7692bf47d5dde5842af3d8ec0736bb0 main
git merge-base --is-ancestor effc5e039505c09e575ca5e4aeb2b96949676366 main
git merge-base --is-ancestor 2091d01c8cea22da49a50bb1f0859d8108102f29 main
git merge-base --is-ancestor 42abaab7ba4fa83f9838c3d32ee96db4256bfcad main
git merge-base --is-ancestor 088e2f31003e3a7e96119bc8cdba162252226ac1 main
git merge-base --is-ancestor 71e492b4507d84e6631fef851cec820bcd80215b main
git merge-base --is-ancestor b8673031a80158c49d552a4b3647829d213243bd main
git merge-base --is-ancestor d7eefb7c3595e786851a7d416ba54ea3997a8b6c main
git merge-base --is-ancestor b3570937918c7de40cd89ea543fab9e7b16f7471 main
git merge-base --is-ancestor 7b6c5a121107ee80533a5b4ec794e602e1e1ab33 main
git merge-base --is-ancestor 7c5264d815d44c375173dcd1e8ab57783a397a7e main
git merge-base --is-ancestor 6929fd3703ff262d3264b58a5af90d506a804da2 main
git merge-base --is-ancestor 6801fbd0b34565dc3dbe915e8d1f6e04455cb9e4 main
# Exact canonical baseline. Ancestry alone also passes when `main` carries later,
# unrecorded merges, which is precisely the condition under which the Authority
# carve-out lapses. This equality is the lapse detector: if it fails, `main` has
# advanced past the recorded baseline and the carve-out must be recomputed from
# the new `main` before any further admission.
#
# This equality is deliberately scoped to this pre-admission controller-branch
# check and must NOT be lifted into the always-on test suite: by the terminal
# canonical-state property above, the commit that records a baseline lands after
# it, so on `main` the equality is false the instant it merges and would hold CI
# permanently red. The suite enforces the same invariant in the form that
# survives its own merge — `tests/test_planning_traceability.py` fails if any PR
# merged into `main` after the recorded baseline is absent from the lease map.
test "$(git rev-parse main)" = "6801fbd0b34565dc3dbe915e8d1f6e04455cb9e4"
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
