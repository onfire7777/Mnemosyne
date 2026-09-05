# Remaining Dependency and Write-Lease Map

Updated: 2026-09-05 (P13-C discharge and obsolete signed-publication lease release)
Baseline: `main@f688c74757365a9d946100687a04288cde12a7fc`

This is the checkout-resident admission map for the remaining Mnemosyne v2.0
benchmark program. It supersedes the runtime snapshot in the original
`a7221348` version while preserving that map's dependency, exact-lease,
single-owner, and concurrency rules. `GOAL.md`, `.planning/ROADMAP.md`,
`.planning/REQUIREMENTS.md`, `.planning/STATE.md`, and the named approved plans
remain the lifecycle authorities; this map does not create another roadmap.

## Merged baseline

The following packages are complete source history, not runnable work:

- PRs #79-#80: closed common ABI and review hardening.
- PR #81: M01 capture and M10 abstention development pilots.
- PR #82: M12 prospective-action and M13 working-memory confirmations.
- PR #83: M03 valid-time development slice.
- PR #84: M15 canonical replay and the composed M01-M03-M10 vertical slice.
- PR #85: Phase 13-15 contract freeze.
- PR #86: bounded weekly/manual development regression source.
- PR #87: canonical truth reconciliation of the GOAL/GSD lifecycle files
  (`main@2ba4ed80`, post-merge CI `30566984814`).
- PR #88: public-regression README documentation and workflow contract-test
  hardening (`main@4a891042`, post-merge CI `30659705054`).
- PR #89: this map and `.planning/STATE.md` recomputed after PR #88
  (`main@a8e9444c`, post-merge CI `30672194635`). Documentation only: it moved
  no package status, so the rows below are unchanged by it.
- PR #90: the previously stranded M12/M13 development gap disclosures in
  `eval/public/README.md`, their two pinning test suites, a cert-rotator
  lock-timeout flake fix, and the pilots-plan delivery checkpoints
  (`main@061c2e1c`, exact-head CI `30679262270`, post-merge CI `30680201900`).
  Development-source documentation and tests only: it moved no package status,
  changed no benchmark, measurement, admission state, or publication claim, and
  left `eval/public/registry.json`, the fixtures, and all adapter/scoring code
  untouched. M12/M13 remain `PROPOSED` / `publishable:false` /
  `pbpp_headline_eligible:false`, so the rows below are unchanged by it.
- PR #91: the GoalEx lifecycle delivery of the previously stranded controller
  delta — the three lifecycle files, the pilots-plan PR #90 checkpoint, and the
  26 round records (`main@e157e035`, exact-head CI `30686224929`, post-merge CI
  `30687385118`). Documentation only: it moved no package status, changed no
  benchmark, measurement, admission state, or publication claim, and touched no
  source, test, or workflow path. This is node `T3`, now `MERGED`; the rows
  below are unchanged by it except for `T3`'s own state.
- PR #92: the receipt-level lifecycle update discharging `T3`'s residue — the
  three lifecycle files at `Baseline: main@e157e035` plus the round-38 and
  round-39 records (`main@39cfa67a`, exact-head CI `30693874030`, post-merge CI
  `30694818231`). Documentation only: it moved no package status, changed no
  benchmark, measurement, admission state, or publication claim, and touched no
  source, test, or workflow path. This is node `T4`, now `MERGED`; the rows
  below are unchanged by it except for `T4`'s own state.
- PR #93: fail-closed GoalEx round-cleanup and ignored-state custody contract,
  including behavioral traceability (`main@effc5e03`, exact-head CI
  `30718912376`, post-merge CI `30719645207`). It changed no benchmark source,
  measurement, admission state, roadmap percentage, or publication claim.
- PR #94: the `T5` lifecycle delivery (`main@2091d01c`, exact head
  `41b21305`, exact-head CI `30730185494`, post-merge CI `30730918452`).
  Documentation, contract-test, and CI configuration only: it admitted no
  source node. Its own
  `docs/plans/` lease omitted the round-42 record, which is the non-receipt
  residue discharged by `T6`.
- PR #95: the `T6` lifecycle delivery (`main@42abaab7`, exact head
  `d7c0938f`, exact-head CI `30737466988`, post-merge CI `30738303497`).
  Documentation only: it delivered the r42 and r43 round records, admitted no
  source node, and changed no benchmark, measurement, admission state, or
  publication claim.
- PR #96: the independently delivered development-only M02/M04/M05 evaluation
  oracles (`main@088e2f31`, exact head `1050749a`, CI `30744318093`). This
  advanced canonical `main` outside the GoalEx lifecycle-node sequence without
  changing publication eligibility.
- PR #97: the round-43 review adjudication and controller
  reconciliation. It records PR #96 above, recomputes
  the canonical baseline to `main@088e2f31`, makes M05's source events conform
  to the frozen `portable_event` ABI, and replaces the traceability test's
  ancestry assertion with the unrecorded-merge detector this row satisfies.
  It admits no source node and changes no benchmark, measurement, admission
  state, or publication claim. It is recorded here before merge because the
  detector requires every PR merged after the baseline to appear in this map,
  and — by the terminal canonical-state property — no commit can carry its own
  merge receipts, which is equally why no exact head is claimed for it here:
  the commit recording one would change it. **The GoalEx loop is paused at this
  PR, not retired**: it is stopped with its blocking condition cleared, and a
  later round may resume and recompute this map. Its receipts, verifiable only
  from a later commit and recorded here now: merge `71e492b4`, exact head
  `13c05d65`, exact-head CI `30774834604`, post-merge CI `30775783472`.
- PR #98: documentation-only correction of PR #97's overstated claim that the
  loop was retired, restoring it to paused. It admits no source node and
  changes no benchmark, measurement, admission state, or publication claim.
  Recorded here before merge for the same reason as PR #97: the detector
  requires every PR merged after the baseline to appear in this map. Its
  receipts, likewise recorded only now: merge `b8673031`, exact head
  `b49b0b35`, exact-head CI `30787319275`, post-merge CI `30788531829`.
- PR #99: the Round-0 M01-M20 whole-memory module inventory and its derivations,
  `tests/test_wmbs_module_inventory.py`, the `T7` M02/M04/M05 Stage-A disclosure
  in `eval/public/README.md` with `tests/test_public_wmbs_stage_a_disclosure.py`,
  and the admission of lease-map nodes `T8` and `T9`. It changed no benchmark,
  measurement, admission state, or publication claim. Its receipts: merge
  `d7eefb7c`, exact head `2375aba5`, exact-head CI `30808291831` green. **It did
  not pre-record itself here**, so its post-merge run `30810160121` failed on the
  baseline-lapse detector and left `main` red; run `30894938975` reproduced the
  same single failure. PR #101 below discharges that lapse — recorded honestly
  rather than elided.
- PR #101: this recomputation of the canonical baseline from `main@b8673031` to
  `main@d7eefb7c`, updating this map's `Baseline:` line, `GOAL.md`, and
  `.planning/STATE.md`, and recording PR #99's receipts above so the
  baseline-lapse detector passes and `main` is green again. It admits no source
  node and changes no benchmark, measurement, admission state, or publication
  claim. Recorded here before merge for the same reason as PRs #97 and #98: the
  detector requires every PR merged after the baseline to appear in this map.
  Delivered from exact head `0d3e3069b9ca061d9f894f1396239fe2c2f817cb`
  with all required exact-head CI green in run `30957633560`; merge
  `58ae5bbafeffab3388c6539a419e56fcd85112da` at
  `2026-08-04T23:13:57Z`.
- PR #100: the node `T9` M03 registry admission, registering
  `wmbs-m03-valid-time-development` in `eval/public/registry.json` with its
  runner adapter, profile contract, `allowed_profile` label, scored-denominator
  handling in `eval/public/bundle.py`, `eval/public/README.md` disclosure, and
  `tests/test_public_wmbs_m03_registry_admission.py`. Reachability only: M03
  stays `PROPOSED` and full bitemporal transaction-time remains a hard deferral.
  Delivered from exact head `e072dda5a9e7ef078d317156c49c54bbee7a5124`
  after all required exact-head CI and Greptile passed in run `31854371658`;
  merge `b3570937918c7de40cd89ea543fab9e7b16f7471` at
  `2026-08-15T01:12:26Z`; successful post-merge CI `31855873247`. It changed no
  fixture byte, scorer, schema, admission state, publication claim, or progress
  counter and admitted no source node or successor node.
- PR #103: Restore canonical memory sources and patch cryptography (merge 5b0d99bcd7).
- PR #105: preserve hash-bound text as LF and make installer/custody tests
  explicit about their native-Windows and POSIX execution contracts. Delivered
  from exact head `d60857fdf61122106eeede789432dd5bac955137` after all
  required exact-head CI passed in run `31856191898`; merge
  `7b6c5a121107ee80533a5b4ec794e602e1e1ab33` at
  `2026-08-15T01:46:23Z`. Post-merge run `31857410462` failed solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  (1 failed, 4709 passed, 151 skipped, 191 deselected) because PR #105 was
  absent from the lifecycle authorities; PR #108 repairs that traceability
  lapse here.
- PR #106: record merged PR #103 in the write-lease map (merge 18e7e2f6c0cf92af399bc66385b0cbf335d1e8f7).
- PR #107: record merged PR #106 in the write-lease map; delivered from exact
  head `9e1df8966fbbf7d0b4c21f1e4aae01fcf3a9adc8` with all required exact-head
  CI green in run `31852940363`; merge
  `7f305090bb026db7aa4d73a3e127808b8ee4089c` at
  `2026-08-15T00:40:44Z`.
- PR #108: reconcile PR #100's exact T9 lease and inventory wording and repair
  PR #105's baseline-lapse receipt. Delivered from exact head
  `bda5588abc2a181c1bd7b5ae17ca31deeae7d85e` after all required exact-head CI
  passed in run `31859014653`; merge
  `7c5264d815d44c375173dcd1e8ab57783a397a7e` at
  `2026-08-15T02:45:01Z`; successful post-merge CI `31859997325`. It changed no
  source, benchmark, measurement, admission state, publication claim, or
  progress counter.
- PR #113: controller-only `T10` lifecycle receipt reserving the four frozen
  Windows portability content and its strict integration order. Delivered from
  exact head `c1bf6a10335e30fe797c54a42285922552647a9e` after all required
  exact-head checks passed in run `31863057094`; merge
  `6929fd3703ff262d3264b58a5af90d506a804da2` at
  `2026-08-15T04:22:14Z`; successful post-merge CI `31864254074`. It changed
  only `GOAL.md`, `.planning/STATE.md`, and this map and admitted no benchmark
  authority.
- PR #114: controller-only `T10` amendment recording PR #109 delivery and
  replacing the ruleset-incompatible full-head freeze with immutable content
  anchors plus exact lifecycle-parent equality. Delivered from exact head
  `7a2777663115554d7683dcb9f59301dd9d83fbf7` after all required exact-head
  checks passed in run `31868231552`; merge
  `c4337f6315833b930cba2d31c7e95778c4f6ddd5` at
  `2026-08-15T06:26:57Z`; successful post-main CI `31869469070`. It changed
  only `GOAL.md`, `.planning/STATE.md`, and this map and granted no benchmark
  authority.
- PR #115: M02 Stage-B public-harness delivery from exact head
  `c14c7a590aa12707e324d57d4dc15afc7fc9c0b7`; all required exact-head checks
  passed in run `31899050596`; merge
  `f688c74757365a9d946100687a04288cde12a7fc` at
  `2026-08-15T18:10:28Z`. Post-main run `31900402252` failed solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #115 was absent from the lifecycle authorities (1 failed, 4752
  passed, 156 skipped, 191 deselected); all eight faster jobs were green. PR
  #117 repairs that traceability lapse. The merge is recorded without waiving
  its reproduced review defects: a serialized successor must repair the missing
  bundle profile, explicit grounded read-only answer custody, empty-hit scoring,
  ranked-result order, `scoring_family`, and the weakened fixture-validation
  path before M02 can be treated as clean or publishable.
- PR #117: ordinary code-and-documentation remediation for the valid
  post-merge PR #114 topology-contract review finding and the coupled PR #115
  lifecycle reconciliation. It is **OPEN/READY** at the
  `2026-08-15T18:29:54Z` capture and adds the stdlib verifier, its focused
  planning-traceability tests, the trusted invocation in `GOAL.md`, the
  baseline/receipt update in `.planning/STATE.md`, and this structured
  self-record. Because this record changes the branch head, no exact final
  head, merge SHA/time, or post-main CI is claimed here. PR #117 is not a
  topology-only refresh, changes no benchmark result or admission state, and
  must pass fresh exact-head review, security, and CI before merge.
  Subsequent delivery verified on 2026-09-05: merged from
  `b818ab3237f85f311bb6a1e6ae7195f40a9d6f63` as
  `d11ffe5e61511269efcf38ccd2ad064564580109` at `2026-08-31T18:03:53Z`.
  The OPEN/READY text above is the historical self-record; PR #117 owns no
  current lifecycle writer.
- PR #121: M04-B public-harness registration of `wmbs-m04-development`
  (title: M04-B: register wmbs-m04-development (PROPOSED)) from exact head
  `5c629a67f7466e9a4d75b82681bac53612abb076`; all required exact-head
  checks passed in run `33425340224`; merge
  `eea12f798c22e281100a62552589225321b6c424` at `2026-08-31T19:05:18Z`
  (GitHub mergedAt `2026-08-31T19:05:19Z`). Post-main run `33428621397`
  (and later scheduled run `33867306126`) failed solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #121 was absent from this lease-map; this receipt repairs
  that bookkeeping. The merge remains `PROPOSED` with publication flags
  false (`publishable:false`, `pbpp_headline_eligible:false`,
  `headline_eligible:false`). It does not waive any open M02 defects from
  PR #115 and does not admit M05-B (PR #128 remains open).
- PR #129: ordinary documentation receipt recording the merged PR #121
  lease-map lapse. It is **OPEN/READY** at the `2026-09-04T17:53:16Z`
  capture and adds only the PR #121 merged-baseline bullet and this
  structured self-record in this map. Because this record changes the
  branch head, no exact final head, merge SHA/time, or post-main CI is
  claimed here. PR #129 changes no benchmark result or admission state,
  does not recompute the canonical baseline, and must pass fresh
  exact-head review, security, and CI before merge.
- PR #128: WMBS M05-B public-harness registration of `wmbs-m05-development`
  (title: WMBS M05-B: register wmbs-m05-development (provenance adapter))
  from exact head `7d4803e46463197e0cb9659cc22ecf02aa2c6b92`; all
  required exact-head checks passed in run `33910693005`; merge
  `ad9d5f809bb2a26df506c3958aef6a149a173f4a` at `2026-09-04T19:46:04Z`.
  Prior tip was `b7f351cdeeb989d7b84e7e2a0ad736efd5a6f5a1` (PR #129 /
  #121 receipt). Post-main run `33912845409` failed solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #128 was absent from this lease-map (1 failed, 4798
  passed); this receipt repairs that bookkeeping. M05-B remains
  `PROPOSED` with publication flags false (`publishable:false`,
  `pbpp_headline_eligible:false`, `headline_eligible:false`). This
  receipt changes no benchmark result or admission state and does
  not recompute the canonical baseline.
- PR #131: ordinary documentation receipt recording the merged PR #128
  lease-map lapse. It is **OPEN/READY** at the `2026-09-04T20:17:53Z`
  capture and adds only the PR #128 merged-baseline bullet and this
  structured self-record in this map. Because this record changes the
  branch head, no exact final head, merge SHA/time, or post-main CI is
  claimed here. PR #131 changes no benchmark result or admission state,
  does not recompute the canonical baseline, and must pass fresh
  exact-head review, security, and CI before merge.
- PR #130: docs M05 README hierarchy residual + M12/M13 peer cells
  (title: docs: M05 README hierarchy residual + M12/M13 peer cells)
  from exact head `a75ec87431b9ee1c0caf9be49a12350afd88efba`; all
  required exact-head checks passed in run `33918171983`; merge
  `0679cdc762d6ac7be610b6be11f62a474fa74240` at `2026-09-04T21:20:51Z`.
  Prior tip was `ec8aa1f28822ac7e992cf110cd9be18643c12e46` (PR #131 /
  #128 receipt). Post-main may fail solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #130 is absent from this lease-map; this receipt repairs
  that bookkeeping. The merge touched only `eval/public/README.md` and
  `tests/test_public_wmbs_stage_a_disclosure.py`. This receipt
  changes no benchmark result or admission state and does
  not recompute the canonical baseline.
- PR #133: ordinary documentation receipt recording the merged PR #130
  lease-map lapse. It is **OPEN/READY** at the `2026-09-04T21:23:16Z`
  capture and adds only the PR #130 merged-baseline bullet and this
  structured self-record in this map. Because this record changes the
  branch head, no exact final head, merge SHA/time, or post-main CI is
  claimed here. PR #133 changes no benchmark result or admission state,
  does not recompute the canonical baseline, and must pass fresh
  exact-head review, security, and CI before merge.
- PR #132: inventory ACCEPT plan-PR receipts for M06–M09/M11/M17–M19
  (title: docs: inventory — record ACCEPT plan PRs for M06–M09/M11/M17–M19)
  from exact head `681bddd535dde6e8712d6be61bedb48bce50f8ce`; all
  required exact-head checks passed in run `33923271250`; merge
  `83804715d19c90c77161924f6acc79e62e567998` at `2026-09-04T22:26:38Z`.
  Prior tip was `661e3f3f3b8fc8714094e6e84c186871c842f756` (PR #133 /
  #130 receipt). Post-main may fail solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #132 is absent from this lease-map; this receipt repairs
  that bookkeeping. Exclusive File Set:
  `docs/coordination/2026-08-03-wmbs-module-completeness-inventory.md`.
  Owner: Docs / CoS (inventory ACCEPT). Purpose: Accept plan-PR
  receipts for M06–M09/M11/M17–M19 inventory; docs-only privacy.
  Gate: MERGED (merge commit
  `83804715d19c90c77161924f6acc79e62e567998`). The merge touched only
  that inventory file. This receipt changes no benchmark result or
  admission state and does not recompute the canonical baseline.
- PR #134: ordinary documentation receipt recording the merged PR #132
  lease-map lapse. It is **OPEN/READY** at the `2026-09-04T22:28:27Z`
  capture and adds only the PR #132 merged-baseline bullet and this
  structured self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  Owner: CoS. Purpose: lease-map receipt for #132 (inventory ACCEPT).
  Gate: OPEN then MERGED when shipped. Because this record changes the
  branch head, no exact final head, merge SHA/time, or post-main CI is
  claimed here. PR #134 changes no benchmark result or admission state,
  does not recompute the canonical baseline, and must pass fresh
  exact-head review, security, and CI before merge.
- PR #138: M02 canonical-replay seed pin
  (title: eval: pin M02 canonical-replay seed)
  from exact head `93bb5845a57a7c08a74e858dc4850fd9f02424b1`; all
  required exact-head checks passed in run `33938772720`; merge
  `ec26c40d359fc1f6904a97eac51aab461f9fd0f6` at `2026-09-05T02:50:49Z`.
  Prior tip was `c67e917410d7b468a337fda19ba654d57367d843` (PR #135).
  Post-main run `33940223834` failed solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #138 was absent from this lease-map; this receipt repairs
  that bookkeeping. Exclusive File Set:
  `eval/public/bundle.py`, `tests/test_public_whole_memory_reference.py`.
  Purpose: M02 canonical-replay seed pin; docs-only privacy for THIS
  receipt PR (the recorded #138 was code). This receipt changes no
  benchmark result or admission state and does not recompute the
  canonical baseline (baseline stays `main@f688c747`).
- PR #141: ordinary documentation receipt recording the merged PR #138
  lease-map lapse. It is **OPEN/READY** at the `2026-09-05T11:24:20Z`
  capture and adds only the PR #138 merged-baseline bullet and this
  structured self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  Because this record changes the branch head, no exact final head,
  merge SHA/time, or post-main CI is claimed here. PR #141 changes no
  benchmark result or admission state, does not recompute the
  canonical baseline, and must pass fresh exact-head review, security,
  and CI before merge.

The following is the historical `T10` reservation snapshot from
`2026-08-15T05:54:05Z`, retained to preserve its immutable-anchor evidence.
Current delivery receipts are appended to the affected rows:

- PR #109: Windows configured-command portability and the first native Windows
  workflow gate. Immutable non-lifecycle content anchor
  `08397dab1220c87a3e8e3a92bf353cc65b68dba3`; first refreshed topology head
  `cb44f21296fc22cf92f847b8201a6881e915400c`. The two trees differ only at
  `GOAL.md`, `.planning/STATE.md`, and this map. Refreshed exact-head CI run
  `31865413163` completed successfully, including every required/native job.
  Anchor scan
  `aa623d98-c231-40f3-8831-64db80ca7744` is sealed with complete coverage and
  zero findings. PR #109 nevertheless raced this amendment and is **MERGED** as
  `6801fbd0b34565dc3dbe915e8d1f6e04455cb9e4` at
  `2026-08-15T05:24:36Z`; post-main run `31866875258` succeeded. Its
  implementation content and pre-merge gates matched this receipt, but the
  ordering deviation is recorded explicitly and opens no later edge.
- PR #110: shared stdlib POSIX/Windows file locking and signed-ledger migration,
  with immutable cumulative non-lifecycle content anchor
  `7e282b7c95f51a6446e25d92f8284de261551703` and first refreshed topology head
  `26f95a09827d3e56ffe86e65b7db7493ecf79c73`. The exclusion check is clean.
  Refreshed exact-head CI run `31865422216` completed successfully, including
  every required/native job.
  Component head
  `1aacf2a8244dda853e1385707072a9e391f7271c` has sealed zero-finding security
  scan `90861fd0-f76f-4207-b1df-36e4cdec69e4`. Delivered from exact refreshed
  head `9655ef411399fed9d72fddb6f660d0fae39e8449`, exact-head CI
  `31870720134`, merge `6241984b15e85171bc036100fa5e20e05588bd81`
  at `2026-08-15T07:19:40Z`, and successful post-main CI `31871667827`.
- PR #111: bounded native-Windows process-tree containment while preserving the
  existing POSIX runner. Immutable cumulative non-lifecycle content anchor
  `226e4416a4e76671d7ca079fe97664b8617f5bfa`; first refreshed topology head
  `02a724e9333a47a1cb7096d59b558ab80c1e5300`; the exclusion check is clean.
  Refreshed exact-head CI run `31865430468` completed successfully, including
  every required/native job.
  Component head `0382f13132dd69bf93d123009c4bee2ba972a82d` has sealed
  zero-finding security scan `a2660fdb-115a-4f0e-80a8-10266d48403b`.
  Delivered from exact refreshed head
  `7754980eb2b5fdc227763e34c7b2af394fb1ea2c`, exact-head CI
  `31872923876`, merge `f95aabaca85ed6cbfbda66c0ceea12df22bfdd00`
  at `2026-08-15T08:18:20Z`, and successful post-main CI `31874150626`.
- PR #112: Windows filesystem/environment/LF portability. Immutable cumulative
  non-lifecycle content anchor `259a6361355ab80cbbfa75ca1a6de6ec4b1f9a96`;
  first refreshed topology head `c8d95dafe5131f965591b84aeabb095fac34f1b6`;
  the exclusion check is clean. Refreshed exact-head CI run `31865438529`
  completed successfully, including all three native-Windows jobs and every
  required job. Its
  isolated filesystem head
  `760377381c72f5d0494e96571977fd52260517a0` has sealed zero-finding security
  scan `866900a1-641e-4278-b652-c1e4797b5979`. Cumulative exact-stack scan
  `8f92e955-a68a-4bec-817a-810a76fce21b` is sealed at the content anchor with
  complete coverage of 20 source items plus 12 workflow/test files and zero
  findings. Fresh refreshed-stack scan
  `e95df6b0-da9d-4688-a2a0-4378be4973d1` covers all 32 changed files at exact
  head `c8d95dafe5131f965591b84aeabb095fac34f1b6`, validates the contract, and
  reports zero findings. Delivered from exact refreshed head
  `afc00bae1af9e9db7016ef3adffaca9bdc226bcf`, exact-head CI
  `31875248786`, merge `61f55b94a6f878973437d075adfcecf2cb684ae6`
  at `2026-08-15T14:48:25Z`, and successful post-main CI `31890934043`.

The completed integration receipt verifies the serialized merge chain
`main@6801fbd0` -> PR #114 `c4337f63` -> PR #110 `6241984b` -> PR #111
`f95aabac` -> PR #112 `61f55b94`. Every edge preserved its immutable
non-lifecycle anchor, inherited the immediately preceding lifecycle blobs,
passed exact-head required/native CI and fresh security review, and waited for
successful post-main CI. The cumulative diff retained binary hash
`f538e11916f0621cb951f8393debb66e032abaa69c9053fb4562c9d245fc778d`;
exactly three unique Windows jobs and the five PR #112 filesystem nodes landed.
The Windows stack is delivered and no implementation writer remains open.

This map is recomputed from the new baseline `main@f688c747`, which the
controller branch has fully merged into it — no commit on `main` is absent from
the controller branch. **The GoalEx lifecycle backlog is delivered except for
its own merge receipts.** PR #91
landed the whole stranded delta on `main`: the three lifecycle files (`GOAL.md`,
`.planning/STATE.md`, and this map) recording PR #90's post-merge receipts on
top of earlier lifecycle content that had itself never been delivered, including
the PR #81-#84 whole-memory Decisions entry in `.planning/STATE.md`; the
pilots-plan PR #90 checkpoint; and the 26 round records touched since round 14
without being delivered through a PR — 23 new `docs/plans/goalex-r15..r38*.md`
files, the two new `docs/plans/completed/goalex-r36-*.md` and
`docs/plans/completed/goalex-r37-*.md` files, and the edit to
`docs/plans/goalex-r14-*.md` (whose original text was already on `main`). Node
`T3` below, which carried that delivery, is now `MERGED`. The GoalEx lifecycle
lease and the public-harness lease stayed unmixed: PR #91 touched nothing
outside the GoalEx lifecycle surfaces. This revision **is** the recomputation
from the resulting `main@e157e035` that the delivery required before any further
admission, and it records the receipt residue that could not exist inside the
commit it describes: PR #91, exact-head CI `30686224929`, merge SHA
`e157e035`, post-merge `main` CI `30687385118`. That recomputation was
**branch-resident only** until node `T4` delivered it as PR #92: this revision
is therefore also the recomputation from the resulting
`main@39cfa67aa7692bf47d5dde5842af3d8ec0736bb0`, and it records `T4`'s own
receipt residue — PR #92, exact-head CI `30693874030`, merge SHA `39cfa67a`,
post-merge `main` CI `30694818231`. `T4` carried exactly that receipt-level
update to the three lifecycle files plus the round-38 record and the round-39
record, and nothing else; it was documentation only and admitted no source node.
PR #93 then merged independently from the `codex/goalmd-round-ends-clean` lane
at `main@effc5e03` (exact-head CI `30718912376`, post-merge CI `30719645207`).
That external merge lapsed the branch-resident carve-out. At lapse, the residue
was no longer receipt-only: it included the undelivered baseline-pinning test
contract and the r39, r40, and r41 round records. Node `T5` discharged that
bounded residue as PR #94 at `main@2091d01c`, with exact-head CI `30730185494`
and post-merge CI `30730918452`; it admitted no source node. Its delivery
omitted the r42 record from its own `docs/plans/` lease. `T6` discharged that
non-receipt residue together with the r43 record as PR #95 at `main@42abaab7`,
with exact head `d7c0938f`, exact-head CI `30737466988`, and post-merge CI
`30738303497`; it admitted no source node and no successor node. This
branch-resident recomputation is `T6`'s own standing-condition residue. It
admits no successor node and no source node. The plan-doc backlog is disclosed
here rather than left to accumulate silently.
That pilots-plan checkpoint is a correction, not an addition: PR #90 shipped
`docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`
without updating its earlier paragraph, so canonical `main@061c2e1c` still
stated that the M12/M13 gap-disclosure paragraphs and their pinning tests
"are not on main and are still pending PR delivery" — a claim that same
commit falsified. That sentence was known-stale on `main` from PR #90 until
PR #91 replaced it; Tasks 7 and 8 are closed on `main` by PR #90.
Fifteen of those records (r17, r19-r21, r23-r31, r34, r35) still carry
unchecked task boxes: those boxes record the plan as written at the time and
are not a delivery signal, because each round's merged receipts are recorded in
this map and in `.planning/STATE.md` rather than back-filled into the round
record.

These receipts do not prove an official benchmark, measured sandbox, hardware
profile, publishable result, leaderboard activation, or launch.

- PR #116: M06 plan-only delivery from head
  `e463f61f00fef1913bd7a0df9db739616a906b54`, with successful exact-head CI
  `33933485295`; merged as `1f6b3b1c236c837aee77ba504f9eb06eab2a9c98`
  at `2026-09-05T01:11:18Z`. It adds only
  `docs/plans/wmb-m06-consolidation-learning-implementation-plan.md`; it
  changes no N12 path and does not deliver M06 implementation. PR #135's
  branch incorporated that main update before continuing gate delivery.
- PR #135: receipt-only correction discharging P13-C from verified scheduled
  run `30807305055`, with matching `GOAL.md`, `.planning/STATE.md`,
  `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, and Phase 13 summary
  corrections closing BENCH-007 and retiring the unavailable Mac reservation,
  plus the matching current-status checkpoints in the executable pilot plan.
  Open at the 2026-09-05 capture;
  no final-head CI, merge, or post-main result is claimed in this self-record.
  It preserves the canonical baseline and progress counters, releases the
  obsolete signed-publication lease, and marks N12 READY FOR ADMISSION after
  this receipt lands. It assigns no implementation writer.

## P13-C discharge and N12 admission check (2026-09-05)

The owner requested resolution of the stale gate checklist. This bounded
receipt changes this map, `GOAL.md`, `.planning/STATE.md`,
`.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, and
`.planning/phases/13-external-benchmark-adapters-and-scheduled-ci/13-01-SUMMARY.md`
to reconcile BENCH-007's sole remaining cadence gate, plus the lease-status
checkpoints in `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`
so that the executable authority agrees with N12's admission state. Its approved
implementation contract is unchanged. The gate
check used clean `origin/main@3281e61ed6b3d077628e3fd03ce0ec8de22cde18`, whose
post-main CI run `33927734374` succeeded. The standing canonical baseline
above is preserved; this receipt admits no source writer.

- **P13-C: DISCHARGED.** GitHub's authenticated run and job APIs verify
  [Public regression run 30807305055](https://github.com/onfire7777/Mnemosyne/actions/runs/30807305055):
  `event=schedule`, `status=completed`, `conclusion=success`, workflow
  `.github/workflows/public-regression.yml`, head
  `b8673031a80158c49d552a4b3647829d213243bd`, started
  `2026-08-03T10:52:57Z`, updated `2026-08-03T10:53:18Z`.
  Job `91665545558` (`public-regression`) completed successfully at
  `2026-08-03T10:53:17Z`; its `Run fixed public contract regression` step
  succeeded. The configured Monday cron is `23 7 * * 1`; the actual delayed
  start time above is retained without substituting the nominal cron time.
  No workflow artifacts exist (`total_count=0`), as expected for this fixed
  contract-test workflow. This durable metadata receipt closes cadence only;
  it supplies no official benchmark result, BENCH-006 closure, publication
  eligibility, or progress-counter increment. BENCH-007 is Complete because
  its merged source and this retained scheduled run satisfy its contract;
  Phase 13 remains open for BENCH-006, and the source plan was already complete.
- **Signed-publication source: MERGED.** PR #69 merged at
  `2026-07-26T12:42:20Z` as `a4e80b5a67b0437d3a864af0fe347febfe32e58b`.
  PR #70 delivered its completion receipt at `2026-07-26T12:59:59Z` as
  `eeb8765ea1f4cc924002ad8234df50326e227aed`. Both are ancestors of the
  inspected main tip. `leaderboard/publish.py` exists there with blob
  `f6506215ece4dba8d37ce07829b5c22d84020963`.
- **Protected signed-publication lease: RELEASED.** On 2026-09-05 the owner
  clarified, "dont have old mac or its files", while requesting full resolution
  of this gate. The unavailable worktree
  `/Users/admin/Mnemosyne.codex-phase16-signed-publication` is therefore retired
  as an active reservation and its repository paths are released. This is an
  administrative disposition based on the owner's confirmation, not a clean
  worktree inspection or a claim that unavailable residual files were recovered,
  landed, or deleted. The delivered source remains preserved in PRs #69-#70.
  Any future recovery requires a fresh handoff/review and cannot revive this
  retired reservation. The separate whole-memory-spec lease is unchanged.
- **N12: READY FOR ADMISSION after this receipt lands.** Recomputed against
  `origin/main@3281e61ed6b3d077628e3fd03ce0ec8de22cde18`: the result-v1 schema,
  validator, signed ledger, renderer, publisher, and readiness source exist;
  `leaderboard/schema/result-v2.schema.json` is absent, so N12 is not delivered.
  Open PRs #116, #118-#120, #122-#127, #135, and #137 change none of N12's
  eleven exact source/test/documentation paths. The three local worktrees
  likewise have no changes on those paths. The runtime-hardening worktree has
  unrelated dirty work, which remains untouched. PR #120 overlaps this
  receipt on `GOAL.md` and is not merged or otherwise consumed here.
  The next step is one result-v2 integration owner's assignment on current
  main, preserving result-v1 bytes/behavior and rechecking exact leases at
  that time. This closes the obsolete lease blocker; it neither implements
  N12 nor starts a source writer automatically.
  Refresh after PR #116: main advanced to
  `1f6b3b1c236c837aee77ba504f9eb06eab2a9c98`; its sole changed file is the
  M06 plan, so the N12 lease/source assessment is unchanged. PR #116 is now
  merged rather than open. Before N12 source edits, the assigned owner must
  snapshot result-v1 golden bytes/behavior and prove its existing contract
  tests pass, as required by N12's compatibility contract.

The downstream order remains `N12 -> P14-B -> P15-S2`; module-specific
conditions still apply. This receipt starts no module implementation and
leaves the unrelated PR #120 unchanged.

## Shared-file owners

Every surface below is an exact repository-relative path. A trailing `/`
leases every descendant of that directory; no glob or brace expansion is
implied. `wiki:` paths name exact files in the separate Mnemosyne Wiki
repository.

| Owner | Exclusive surfaces | Admission rule |
|---|---|---|
| GoalEx lifecycle/integration owner | `GOAL.md`; `.planning/`; `docs/plans/`; `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`; `docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md`; `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`; `wiki:Home.md`; `wiki:Roadmap-and-Status.md`; `wiki:Calibration-and-Evaluation.md`; `wiki:Development-Guide.md` | One writer. Update only from verified merged reality. |
| Public-harness integration owner | `eval/public/runner.py`; `eval/public/scoring.py`; `eval/public/bundle.py`; `eval/public/registry.json`; `eval/public/README.md`; `eval/public/adapters/whole_memory_reference.py`; `eval/public/schema/wmbs-0.1-draft.schema.json`; `tests/test_public_whole_memory_reference.py`; `src/mnemosyne/cli.py`; `eval/harness/cli_driver.py` | One writer; serialize any package touching one of these paths. |
| Result-v2 integration owner | `leaderboard/schema/result-v2.schema.json`; `leaderboard/validate.py`; `leaderboard/ledger.py`; `leaderboard/render.py`; `leaderboard/publish.py`; `leaderboard/readiness.py`; `eval/provider_bakeoff/README.md`; `tests/test_leaderboard_result_contract.py`; `tests/test_leaderboard_ledger.py`; `tests/test_leaderboard_render.py`; `tests/test_leaderboard_publish.py`; `tests/test_leaderboard_readiness.py` | Obsolete signed-publication reservation released by the 2026-09-05 owner confirmation. N12 is ready for one owner's admission after this receipt lands, with a fresh main/lease check. |
| CI integration owner | `.github/workflows/`; `tests/test_public_regression_workflow.py` | One writer; one exact-head authoritative full suite. |
| Evidence/operator owner | `eval/public/receipts/` | One process and one worker; no concurrent coding or broad tests during measured runs. Future run-staging and evidence-index paths remain unleased until an approved plan names their exact repository-relative paths. |

Any dirty path, active writer, open PR, or branch-ancestry overlap with an
exact lease serializes the affected packages.

## Remaining package DAG

Each row records prerequisites and consumed interfaces, produced artifacts,
exact lease, shared owner/integration edge, and external gate.

| ID | Class | Package and prerequisites / consumes | Produces | Exact write lease and owner | Integration dependency / external gate |
|---|---|---|---|---|---|
| T0 | MERGED | Canonical truth PR after PR #86; consumed exact-head CI `30559003114`, merge `661343ce`, manual run `30561430522`, and post-merge CI `30561266140` | Truthful GOAL/GSD lifecycle state and this current map | `GOAL.md`; `.planning/STATE.md`; `.planning/ROADMAP.md`; `.planning/REQUIREMENTS.md`; `.planning/phases/13-external-benchmark-adapters-and-scheduled-ci/13-01-PLAN.md`; `.planning/phases/13-external-benchmark-adapters-and-scheduled-ci/13-01-SUMMARY.md`; `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`; `tests/test_planning_traceability.py`. GoalEx owner only | Complete: merged as PR #87 at `main@2ba4ed80` with post-merge CI `30566984814` |
| T3 | MERGED | GoalEx lifecycle delivery of the previously undelivered controller delta; consumed verified canonical `main@061c2e1c` and PR #90's post-merge receipts, delivered from a lane cut from `main@061c2e1c` | The three lifecycle files, the pilots-plan PR #90 checkpoint, and the 26 round records delivered on `main`, reducing the `GOAL.md` Authority carve-out to receipt scope | `GOAL.md`; `.planning/STATE.md`; `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`; `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`; `docs/plans/`. GoalEx owner only | Complete: merged as PR #91 at `main@e157e035` with exact-head CI `30686224929` and post-merge CI `30687385118`. Documentation only; it was disjoint from every public-harness, CI, and result-v2 lease and admitted no new implementation package. This map is recomputed from that `main` and the receipt block it could not contain is recorded here; that recomputation was branch-resident, so `T3`'s residual undelivered item was exactly the receipt-level lifecycle update carried by node `T4`, now `MERGED` as PR #92 |
| T4 | MERGED | Receipt-level lifecycle update discharging `T3`'s residue; consumed verified canonical `main@e157e035` and PR #91's post-merge receipts, delivered from a lane cut from `main@e157e035` | This map at `Baseline: main@e157e035` with `T3` as `MERGED`, the matching `GOAL.md` and `.planning/STATE.md` receipt text, the updated round-38 record (whose original text PR #91 already landed on `main`), and the round-39 record, delivered on `main`, plus the branch-resident receipt recomputation below | `GOAL.md`; `.planning/STATE.md`; `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`; `docs/plans/`. GoalEx owner only | Complete: merged as PR #92 at `main@39cfa67a` with exact-head CI `30693874030` and post-merge CI `30694818231`. Documentation only; exact-lease-disjoint from every public-harness, CI, result-v2, and evidence lease, and it admitted no source node. This map is recomputed here from that `main`, and the receipt block PR #92 could not contain is recorded above. That recomputation is `T4`'s own receipt residue, generated for the same structural reason `T3`'s was: no commit describes its own merge, so `main`'s copy of this map always lags by exactly one receipt block. That residual lag is an accepted standing condition and admits **no successor node** and **no source node**; `T4` is the last node this carve-out admits |
| T5 | MERGED | Bounded GoalEx lifecycle delivery after PR #93's independent merge lapsed the branch-resident carve-out; consumed verified canonical `main@effc5e03`, PR #93 exact-head CI `30718912376` and post-merge CI `30719645207`, and a lane cut from `main@effc5e03` | The three lifecycle files, both baseline-pinning tests, and the r39/r40/r41 round records delivered by PR #94 | `GOAL.md`; `.planning/STATE.md`; `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`; `docs/plans/`; `tests/test_planning_traceability.py`; `.github/workflows/ci.yml`. GoalEx owner with CI integration shared-owner serialization | Complete: merged as PR #94 at `main@2091d01c`, exact head `41b21305`, exact-head CI `30730185494`, post-merge CI `30730918452`. Documentation, contract-test, and CI configuration only; it admitted no source node. Its delivery omitted the round-42 record from its own `docs/plans/` lease, the non-receipt residue discharged by `T6` |
| T6 | MERGED | Verified canonical `main@2091d01c` plus PR #94 exact-head CI `30730185494` and post-merge CI `30730918452`; lane cut from `main@2091d01c` | The three lifecycle files at `Baseline: main@2091d01c` with `T5` as `MERGED`, plus the r42 and r43 round records | `GOAL.md`; `.planning/STATE.md`; `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`; `docs/plans/`. GoalEx owner only | Complete: merged as PR #95 at `main@42abaab7`, exact head `d7c0938f`, exact-head CI `30737466988`, post-merge CI `30738303497`. Documentation only; it admitted no source node and no successor node. This branch-resident recomputation is `T6`'s own accepted standing-condition residue and admits no successor or source node |
| T7 | MERGED | Bounded documentation-and-tests node disclosing PR #96's development-only M02/M04/M05 evaluation oracles; consumed verified canonical `main@b8673031` plus PR #97 (merge `71e492b4`, exact-head CI `30774834604`, post-merge CI `30775783472`) and PR #98 (merge `b8673031`, exact-head CI `30787319275`, post-merge CI `30788531829`) receipts | The M02/M04/M05 Stage-A development gap disclosures in `eval/public/README.md`, their pinning tests, and the three lifecycle files recomputed to `Baseline: main@b8673031` | `eval/public/README.md` and `tests/test_public_wmbs_stage_a_disclosure.py` under the **Public-harness integration owner**, serialized as sole writer on `eval/public/*` for this documentation-only edit; `GOAL.md`; `.planning/STATE.md`; `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`; `docs/plans/` under the **GoalEx lifecycle owner**. Both owners are required and they land together in one serialized PR (PR-1 of round 46); no other lane touches `eval/public/*` at this baseline | Documentation and tests only. It admits **no source node**, **no Stage-B integration**, and **no successor node**: no `eval/public/registry.json` entry, adapter, runner routing, profile contract, or scoring-profile registration is authorized, no module behavior or fixture byte changes, M02/M04/M05 stay `PROPOSED` / `publishable:false` / `pbpp_headline_eligible:false`, and no progress counter moves. Stage B for all three remains blocked on the public-harness integration owner's lease. **Delivery statement:** the `eval/public/README.md` M02/M04/M05 Stage-A development-oracle gap disclosure and its pinning suite `tests/test_public_wmbs_stage_a_disclosure.py` are delivered by PR-1 of GoalEx round 46 **Merged receipts:** delivered as PR #99, merge `d7eefb7c`, exact head `2375aba5`, exact-head CI `30808291831`; its post-merge run `30810160121` failed the baseline lapse detector because PR #99 landed after the then-recorded baseline `main@b8673031` without pre-recording itself, which PR #101 discharges by recomputing this map to `main@d7eefb7c` |
| T8 | MERGED | Bounded GoalEx lifecycle documentation-and-tests node landing the stranded Round-0 M01-M20 completeness inventory; consumes verified canonical `main@b8673031` and the same PR #97/#98 receipts `T7` consumes | The M01-M20 module completeness inventory, its line-level derivations, the drift test that pins the inventory to the tree, and the three lifecycle files recomputed to `Baseline: main@b8673031` | Exactly `docs/coordination/2026-08-03-wmbs-module-completeness-inventory.md`; `docs/coordination/2026-08-03-wmbs-module-completeness-derivation.md`; `tests/test_wmbs_module_inventory.py`; `GOAL.md`; `.planning/STATE.md`; `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`; `docs/plans/`. GoalEx owner only | Documentation and tests only. It admits **no source node** and **no publication claim**: no module implementation, protocol, scorer, adapter, registry entry, fixture byte, schema, or admission state changes, and no progress counter moves. Its lease contains no public-harness source path. It **overlaps `T7`** on `GOAL.md`, `.planning/STATE.md`, this map, and `docs/plans/`, so `T7` and `T8` are not concurrent writers: they are one serialized GoalEx lifecycle writer landing as a single PR (PR-1 of round 46) **Merged receipts:** delivered as PR #99, merge `d7eefb7c`, exact head `2375aba5`, exact-head CI `30808291831`; its post-merge run `30810160121` failed the baseline lapse detector because PR #99 landed after the then-recorded baseline `main@b8673031` without pre-recording itself, which PR #101 discharges by recomputing this map to `main@d7eefb7c` |
| T9 | MERGED | Public-harness Stage-B M03 registry-admission node; consumed canonical `main` through PR #107 at `main@7f305090` | The `wmbs-m03-valid-time-development` entry in `eval/public/registry.json`, its `_ADAPTERS` and `_PROFILE_CONTRACTS` keys in `eval/public/runner.py`, its matching `allowed_profile` label in `eval/public/bundle.py` (a second, independent profile-contract table that rejects an unlabelled profile with `wrong interval-family metadata`), its `eval/public/README.md` documentation, its tests, and the derived-fact inventory update already present in this PR | Exactly `eval/public/registry.json`; `eval/public/runner.py`; `eval/public/bundle.py`; `eval/public/README.md`; `tests/test_public_whole_memory_reference.py`; `tests/test_public_wmbs_m03_registry_admission.py`; `docs/coordination/2026-08-03-wmbs-module-completeness-inventory.md`. Delivered under the public-harness integration owner's exclusive serialized lease after `T7`'s `eval/public/README.md` write; that serialization is discharged and no active writer remains on the lease | Authorizes **M03 only**. It admits no other module, changes no fixture byte, no scorer logic, and no schema, and it advances **no admission state**: M03 stays `PROPOSED` / `publishable:false` / `pbpp_headline_eligible:false`, with full bitemporal transaction-time query semantics retained as a hard deferral per `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md` line 68. Reachability fix only; it admits **no successor node** or source node. **Merged receipts:** PR #100 exact head `e072dda5a9e7ef078d317156c49c54bbee7a5124`; all required exact-head CI and Greptile green in run `31854371658`; merge `b3570937918c7de40cd89ea543fab9e7b16f7471` at `2026-08-15T01:12:26Z`; post-merge CI `31855873247` successful |
| T10 | MERGED | Windows portability stack from PR #109 through PR #112, with controller amendment PR #114, immutable non-lifecycle content anchors, exact lifecycle-parent equality, and three native-Windows CI jobs | Delivered configured-command portability, shared stdlib file locking, bounded native-Windows process-tree containment, and filesystem/environment/LF portability | Historical lifecycle authority: `GOAL.md`; `.planning/STATE.md`; this map. Historical implementation anchors: PR #110 `7e282b7c95f51a6446e25d92f8284de261551703`, PR #111 `226e4416a4e76671d7ca079fe97664b8617f5bfa`, PR #112 `259a6361355ab80cbbfa75ca1a6de6ec4b1f9a96`; `.github/workflows/ci.yml` remained under one integration owner | Complete: PR #114 merge `c4337f63` and post-main CI `31869469070`; PR #110 merge `6241984b` and post-main CI `31871667827`; PR #111 merge `f95aabac` and post-main CI `31874150626`; PR #112 merge `61f55b94` and post-main CI `31890934043`. Exact-head required/native CI and fresh security review passed at every edge; no Windows stack writer remains open |
| T1 | COMPLETE | GitHub Wiki reconciliation; consumed verified canonical main | Current Home, status, evaluation, and development pages with no v2 claim upgrade | `wiki:Home.md`; `wiki:Roadmap-and-Status.md`; `wiki:Calibration-and-Evaluation.md`; `wiki:Development-Guide.md`. Wiki owner only | Complete: wiki commit `46c34287fe064842e72c3f52a9afad0c822b1846`; PR #88 changed no benchmark boundary, claim, or status any wiki page asserts, so it required no further wiki change |
| T2 | COMPLETE | Deduplicated knowledge refresh; consumed final canonical and wiki source | One current CBM graph and one Gbrain milestone | No product/source lease | Complete: single deduplicated refresh of 2026-07-30, Gbrain milestone `milestones/mnemosyne-pr86-pr87-wiki-canonical-delivery-2026-07-30`; the earlier refresh at `90841427` was not duplicated |
| P12-E | EXTERNAL/OPERATOR BLOCKED | Phase 12 measured closure; consumes existing 12-04 source, production Postgres PPR parity, runtime readiness, grounded-reader QA, protected attempt | Frozen/held-out EM/F1 and positive graph/PPR evidence | No new code lease; operator evidence paths in Phase 12 plan 12-04 | Protected data, production/runtime, operator authorization |
| P13-C | DISCHARGED | First real weekly cron receipt; consumes merged fixed workflow, whose cron is `23 7 * * 1` (Mondays 07:23 UTC) | Retained scheduled-cadence receipt for BENCH-007 | No code lease | Real `schedule` run `30807305055` succeeded on `b8673031a80158c49d552a4b3647829d213243bd` on 2026-08-03; job `91665545558` and its fixed public-contract test step succeeded. Metadata and scope are retained in the P13-C discharge section; no official benchmark or publication claim |
| P13-O | EXTERNAL/PLAN BLOCKED | Official MemoryAgentBench and BEAM; consumes P12-E plus pinned upstream revisions/protocols | BENCH-006 conforming upstream evidence | No admitted lease; a future exact plan must name every source/evidence path | Rights/license, provider/model/judge disclosure, capacity, operator admission |
| SBOX | QUARANTINED | Development sandbox/external-meter candidate; consumes the common ABI and local reviewed sandbox commits | Only development-source isolation receipts until enforcement is proven | Current local source/test lease: `eval/public/sandbox.py`, `eval/public/sandbox/Dockerfile`, `tests/test_public_sandbox.py`; public-harness owner for any later shared integration | No push/PR/merge until immutable image, daemon probe, filesystem/network/write-boundary enforcement, SBOM, provenance, and resource receipts exist |
| N12 | READY FOR ADMISSION | Additive result-v2 and M20 publication-integrity dispatch; consumes result-v1, signed ledger, renderer/publisher/readiness, official/enhanced lineage, atomic attempt identities | Compatible result-v2 projections, visible safety failures, cross-version supersession | `leaderboard/schema/result-v2.schema.json`; `leaderboard/validate.py`; `leaderboard/ledger.py`; `leaderboard/render.py`; `leaderboard/publish.py`; `leaderboard/readiness.py`; `eval/provider_bakeoff/README.md`; `tests/test_leaderboard_result_contract.py`; `tests/test_leaderboard_ledger.py`; `tests/test_leaderboard_render.py`; `tests/test_leaderboard_publish.py`; result-v2 owner only | Obsolete protected reservation released by the 2026-09-05 owner confirmation; effective after this receipt lands. Assign one owner and recheck current main/exact leases before implementation; result-v1 bytes and behavior remain immutable |
| P14-B | BLOCKED on N12 | REPRO-001 implementation; consumes N12, existing bundle/reproduce lifecycle, M15 replay, signed ledger, static renderer | Neutral reproducibility-bundle v1 schema and one clean-checkout reproduction command | Exactly `eval/public/schema/reproducibility-bundle-v1.schema.json`, `eval/public/bundle.py`, `eval/public/README.md`, `tests/test_public_reproducibility.py`; one integration owner | N12 merged, protected lease released, result-v1 golden compatibility green |
| P14-R | EVIDENCE BLOCKED | REPRO-002; consumes P14-B and a headline-eligible official result | Clean-checkout reproduction receipt | Evidence-only future lease | Official result, public bundle, custody, disclosed judge, human approval |
| P15-S2 | BLOCKED on P14-B | CAP-007/008 capability work; consumes Phase 14 and existing consolidation/queue/retrieval rails | Cadence tiers, bounded sleep consolidation, global sensemaking, surprise-gated writes | Exact `files_modified` list in `15-01-PLAN.md`; shared lifecycle files excluded | Phase 14 implementation and fresh Worktrunk lease check |
| P15-S3 | BLOCKED on P15-S2 | CAP-004/005 security and calibration development evidence | Separate attack-family hard failures and calibration/abstention diagnostics | Stage A new-file lease, then serialized Stage B integration lease in `15-02-PLAN.md` | Dataset/model/judge rights and protected-suite controls remain external |
| P15-S4 | BLOCKED on P15-S3 | CAP-006/011 performance, scale, provider, and 8 GiB closure | Warm/concurrent, provider, 100k, compact-host receipts kept separate | Task-specific exact leases in `15-03-PLAN.md`; one measurement owner | Real 100k/production backfill and physical Windows/Linux 8 GiB evidence are operator/resource gated |
| P15-S5 | BLOCKED on P15-S4 | CAP-009/010 research closure | Cartridge A/B, reduced activation-memory diagnostics, explicit go/no-go | Task-specific exact leases in `15-04-PLAN.md`; no product write path | Model/tool/license/hardware/custody admission; research never grants authority |
| P16-L | HUMAN/EVIDENCE BLOCKED | Open leaderboard launch; consumes N12, P14-R, PBPP, custody, and accepted official evidence | Public activation only after all launch gates; optional Register B/neutral review enables only the `neutral` label | No admitted source lease | Human approval, evidence sufficiency, custody, rollback and publication gates |
| U-MODULES | SPEC UNSTABLE | Module implementation for M02, M04-M09, M11, M14, M16-M19 — **excluding** the development-only M02/M04/M05 evaluation oracles already delivered by PR #96 | No artifact authorized | No lease | Each needs an approved exact plan, protocol, scorer, license/custody, and dependency placement before code. PR #96's oracles are development-only: they authorize no module implementation, protocol, scorer admission, or publication claim, so these IDs remain SPEC UNSTABLE for module work |

## Topological waves

Only dependency-ready and exact-lease-disjoint nodes may share a wave.

```text
Prior delivery wave (complete)
  T0 PR #87 canonical truth            [merged main@2ba4ed80]
    -> T1 GitHub Wiki reconciliation   [wiki 46c34287]
      -> T2 one deduplicated CBM/Gbrain refresh [done 2026-07-30]
  PR #88 documentation/contract-test hardening merged at main@4a891042
  and admitted no new implementation package.
  PR #89 recomputed this map and STATE at main@a8e9444c
  and admitted no new implementation package.
  PR #90 landed the stranded M12/M13 development gap disclosures, their
  pinning tests, and a cert-rotator lock-timeout flake fix at main@061c2e1c
  and admitted no new implementation package.
  T3 GoalEx lifecycle backlog delivery merged as PR #91 at main@e157e035
  and admitted no new implementation package.
  T4 receipt-level lifecycle update merged as PR #92 at main@39cfa67a
  and admitted no new implementation package.
  PR #93 independently merged at main@effc5e03 (the merge that lapsed the branch-resident carve-out), lapsing the
  branch-resident carve-out.
  T5 lifecycle delivery merged as PR #94 at main@2091d01c
  and admitted no source node.
  T6 lifecycle delivery merged as PR #95 at main@42abaab7
  and admitted no source node or successor node. Its branch-resident
  recomputation is T6's own accepted standing-condition residue.

Current delivery wave
  Through PR #96 this wave's recorded status was: No GoalEx lifecycle or source
  node is admitted. PR #96 independently merged
  development-only M02/M04/M05 evaluation oracles; no writer for them remains
  active, and their publication eligibility is unchanged. PR #99 then delivered
  T7 and T8 (merge d7eefb7c, exact head 2375aba5, exact-head CI 30808291831):
    T7 documentation-and-tests (MERGED as PR #99): discloses those three oracles in
    eval/public/README.md and pins the disclosure with tests. It admits no
    source node, no Stage-B integration, and no successor node, and it leaves
    every module's admission state, publication eligibility, and the registry
    untouched.
    T8 documentation-and-tests (MERGED as PR #99): lands the stranded Round-0
    M01-M20 completeness
    inventory, its derivations, and its drift test. It admits no source node and
    no publication claim.
    T9 public-harness Stage-B integration (MERGED as PR #100): registers the existing, already
    scorer-backed and unit-tested M03 valid-time development cell so it is
    reachable from run_public_suite. It is a reachability fix for M03 only. It
    changes no fixture byte, no scorer, no schema, and no admission state, and
    it admits no successor node or source node. Exact head
    e072dda5a9e7ef078d317156c49c54bbee7a5124 passed all required exact-head CI
    and Greptile in run 31854371658; merge
    b3570937918c7de40cd89ea543fab9e7b16f7471 at 2026-08-15T01:12:26Z;
    post-merge CI 31855873247 successful.
  T7 and T8 are NOT lease-disjoint: both write GOAL.md, .planning/STATE.md,
  this map, and docs/plans/. They are one serialized GoalEx lifecycle writer
  delivered as PR #99. T7 additionally wrote eval/public/README.md and its
  pinning test under the public-harness owner. T9 overlapped T7 on
  eval/public/README.md, so it followed PR #99 strictly in sequence and was
  delivered as PR #100. That ordering and both write leases are now discharged:
  T7, T8, and T9 are all MERGED, and no writer remains admitted from this wave.

Delivered Windows portability wave (serialized; content-anchored)
  PR #113 receipt@6929fd37 -> PR #109@6801fbd0 -> PR #114@c4337f63
    -> PR #110@6241984b -> PR #111@f95aabac -> PR #112@61f55b94
  Every edge preserved its immutable non-lifecycle anchor, inherited the
  immediately preceding lifecycle blobs, and closed on successful post-main CI.

Independent external gates (do not block T0-T10)
  P12-E operator measurement
  P13-C real scheduled event (DISCHARGED: run 30807305055)
  P13-O official upstream admission

Future benchmark source wave (currently no benchmark node is admitted)
  protected result-v2 lease released (2026-09-05 owner confirmation)
    -> N12 result-v2/M20
      -> P14-B REPRO-001 implementation
        -> P15-S2
          -> P15-S3
            -> P15-S4
              -> P15-S5

Future evidence/launch wave
  P12-E + P13-O + N12 + P14-B
    -> P14-R
      -> P16-L

Quarantine
  SBOX stays outside every wave until real enforcement receipts exist.
  U-MODULES stay outside every wave until exact plans exist.
```

## Concurrency and integration rules

- `T10` is delivered through PR #112; it is no longer an admitted source wave
  or concurrency allowance. Controller PRs #113/#114 and implementation PRs
  #109-#112 are merged, and every edge closed with the recorded topology,
  exact-head, security, and post-main receipts. The controller/CI integration
  owner remains the sole writer for any future serialized
  `.github/workflows/ci.yml` edge.
- Current admitted coding concurrency is **zero new module-implementation
  writers**. N12 is ready for a single result-v2 owner's admission after this
  receipt lands; other packages retain their dependency, evidence, and spec
  conditions. `T7` and `T8` were delivered by PR #99; `T9` was delivered
  by PR #100 at `main@b3570937`. Their required order is discharged, and no
  writer remains admitted from that wave or active on `eval/public/*`. `T7` and
  `T8` shared the lifecycle files and landed together; `T9` shared
  `eval/public/README.md` with `T7` and therefore landed strictly afterward.
  This completed serialization is the explicit remedy for PR #96's defect,
  where three modules merged onto that lease while this map admitted no writer
  for it. Otherwise only read-only reviews may run.
- **`GOAL.md` Authority carve-out status: standing controller condition from
  `T6` onward.** Both the one-block receipt lag and the current round's own plan
  record are accepted standing conditions of the controller branch. They are
  discharged only by branch-resident recomputation, never by admitting a
  successor node. `T6` admits no successor node and no source node.
- **P13-C is discharged; no new source node is admitted.** `T9` is already
  delivered. Real scheduled run `30807305055` supplies the previously missing
  cadence receipt. The Phase 12
  evidence path remains `P12-E`: exact candidate/runtime manifest and resolved model digest, repeated
  synthetic plus 24-case `qa_scale_dev_v1`, then one protected `qa_hard_v2`
  attempt, and only after that held-out LongMemEval/Hippo evidence. Host,
  mTLS, custody, and operator gates remain fail-closed. `N12` is ready for
  admission after the obsolete reservation's release lands, but still gates
  `P14-B` and the whole `P15-*` chain behind it; `SBOX` is quarantined until
  real enforcement receipts exist; `U-MODULES` lack approved exact plans;
  `P12-E`, `P13-O`, and `P14-R` are operator/evidence blocked; and `P16-L`
  needs human approval. For the N12 chain, the next action is to assign one
  result-v2 integration owner from then-current main after this receipt lands
  and the live exact-lease check passes. The old Mac reservation is retired
  on the owner's confirmation that the Mac and its files are unavailable;
  no access to that machine is required to close this administrative blocker.
- After N12 becomes genuinely admissible, sustain at most **4-6** useful
  exact-disjoint writers and burst to **7-8** only for short read-only review,
  focused-test, or plan-contract work. These are ceilings, never targets.
- Shared schemas, runner, registry, CLI, README, planning, CI, leaderboard, and
  wiki surfaces always have one integration owner.
- Rebase or recreate every future Worktrunk lane from then-current clean
  `origin/main` before admission. Recheck writers, dirty paths, open PRs, exact
  leases, and ancestry immediately before merge; serialize on any conflict.
- Satellites run focused tests. One authoritative full suite runs once on each
  stable exact PR head. Required reviews/threads/mergeability and exact
  post-merge-main CI must be fresh before the next integration edge opens.
- Measured benchmark or hardware work is always one process, one worker, one
  suite; no coding, broad test, or other measured lane runs concurrently.
- Official-upstream, enhanced-successor, exploratory, and development records
  remain separately identified and are never blended into one certified score,
  rank, interval, or headline.
