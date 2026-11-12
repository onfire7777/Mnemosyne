# Remaining Dependency and Write-Lease Map

## Status reconciliation — 2026-10-04

Source inspected at `f2903662`. This dated reconciliation supersedes older
prospective status statements below; historical receipts and candidate SHAs
remain unchanged. Source delivery is distinct from measured acceptance.

- N12 result-v2 dispatch landed in PR #139 (`73bea352`); REPRO-001 bundle
  standard landed in PR #144 (`525d2a13`). REPRO-002 remains evidence-blocked.
- Phase 15 S2 source/development closure landed through PR #160 (`75ae284f`),
  S3 through #162/#164 (`50e52925`, `b29ba998`), S4 report through #177
  (`315c7770`), and S5 research-only go/no-go through #199 (`a6933b51`).
  These deliveries do not satisfy official security/calibration, real provider,
  protected QA, exact-scale, or physical Windows/Linux 8 GiB acceptance.
- M06 Stage A landed in #202 (`d2fa3084`) and Stage B registry reachability
  in #205 (`f5b113b7`). The development cell remains PROPOSED, non-publishable,
  and does not establish whole-memory capability or public admission.
- Phase 12 protected QA, official dataset/provider evidence, REPRO-002,
  physical 8 GiB acceptance, and publication/launch gates remain open.

Evidence sources: `eval/public/bundle.py`, `leaderboard/validate.py`,
`eval/public/security_calibration.py`, `eval/public/wmbs_m06.py`,
`eval/reports/phase-15-s2-capabilities.md`,
`eval/reports/phase-15-s4-performance-scale.md`, and
`research/activation-memory/GO-NO-GO.md`. Existing contract tests are evidence
of implementation coverage, not a new execution or measurement receipt.


Updated: 2026-10-04 (source-delivery reconciliation; historical baseline retained)
Baseline: `main@d181666b61cd483e50326f42eb59328f6c8f9da4`

This is the checkout-resident admission map for the remaining Mnemosyne v2.0
benchmark program. It supersedes the runtime snapshot in the original
`2779a434` version while preserving that map's dependency, exact-lease,
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
  (`main@5b07f320`, post-merge CI `30566984814`).
- PR #88: public-regression README documentation and workflow contract-test
  hardening (`main@a6a92ac9`, post-merge CI `30659705054`).
- PR #89: this map and `.planning/STATE.md` recomputed after PR #88
  (`main@064cb4fe`, post-merge CI `30672194635`). Documentation only: it moved
  no package status, so the rows below are unchanged by it.
- PR #90: the previously stranded M12/M13 development gap disclosures in
  `eval/public/README.md`, their two pinning test suites, a cert-rotator
  lock-timeout flake fix, and the pilots-plan delivery checkpoints
  (`main@94c0c96a`, exact-head CI `30679262270`, post-merge CI `30680201900`).
  Development-source documentation and tests only: it moved no package status,
  changed no benchmark, measurement, admission state, or publication claim, and
  left `eval/public/registry.json`, the fixtures, and all adapter/scoring code
  untouched. M12/M13 remain `PROPOSED` / `publishable:false` /
  `pbpp_headline_eligible:false`, so the rows below are unchanged by it.
- PR #91: the GoalEx lifecycle delivery of the previously stranded controller
  delta — the three lifecycle files, the pilots-plan PR #90 checkpoint, and the
  26 round records (`main@f75b58cc`, exact-head CI `30686224929`, post-merge CI
  `30687385118`). Documentation only: it moved no package status, changed no
  benchmark, measurement, admission state, or publication claim, and touched no
  source, test, or workflow path. This is node `T3`, now `MERGED`; the rows
  below are unchanged by it except for `T3`'s own state.
- PR #92: the receipt-level lifecycle update discharging `T3`'s residue — the
  three lifecycle files at `Baseline: main@f75b58cc` plus the round-38 and
  round-39 records (`main@c56e65fb`, exact-head CI `30693874030`, post-merge CI
  `30694818231`). Documentation only: it moved no package status, changed no
  benchmark, measurement, admission state, or publication claim, and touched no
  source, test, or workflow path. This is node `T4`, now `MERGED`; the rows
  below are unchanged by it except for `T4`'s own state.
- PR #93: fail-closed GoalEx round-cleanup and ignored-state custody contract,
  including behavioral traceability (`main@7aabe560`, exact-head CI
  `30718912376`, post-merge CI `30719645207`). It changed no benchmark source,
  measurement, admission state, roadmap percentage, or publication claim.
- PR #94: the `T5` lifecycle delivery (`main@fe7e6adc`, exact head
  `41e7ac3e`, exact-head CI `30730185494`, post-merge CI `30730918452`).
  Documentation, contract-test, and CI configuration only: it admitted no
  source node. Its own
  `docs/plans/` lease omitted the round-42 record, which is the non-receipt
  residue discharged by `T6`.
- PR #95: the `T6` lifecycle delivery (`main@89f7ff82`, exact head
  `b05ee030`, exact-head CI `30737466988`, post-merge CI `30738303497`).
  Documentation only: it delivered the r42 and r43 round records, admitted no
  source node, and changed no benchmark, measurement, admission state, or
  publication claim.
- PR #96: the independently delivered development-only M02/M04/M05 evaluation
  oracles (`main@82a2fb65`, exact head `e9206707`, CI `30744318093`). This
  advanced canonical `main` outside the GoalEx lifecycle-node sequence without
  changing publication eligibility.
- PR #97: the round-43 review adjudication and controller
  reconciliation. It records PR #96 above, recomputes
  the canonical baseline to `main@82a2fb65`, makes M05's source events conform
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
  from a later commit and recorded here now: merge `3d0ad051`, exact head
  `97745878`, exact-head CI `30774834604`, post-merge CI `30775783472`.
- PR #98: documentation-only correction of PR #97's overstated claim that the
  loop was retired, restoring it to paused. It admits no source node and
  changes no benchmark, measurement, admission state, or publication claim.
  Recorded here before merge for the same reason as PR #97: the detector
  requires every PR merged after the baseline to appear in this map. Its
  receipts, likewise recorded only now: merge `2c6a63f1`, exact head
  `d0021d12`, exact-head CI `30787319275`, post-merge CI `30788531829`.
- PR #99: the Round-0 M01-M20 whole-memory module inventory and its derivations,
  `tests/test_wmbs_module_inventory.py`, the `T7` M02/M04/M05 Stage-A disclosure
  in `eval/public/README.md` with `tests/test_public_wmbs_stage_a_disclosure.py`,
  and the admission of lease-map nodes `T8` and `T9`. It changed no benchmark,
  measurement, admission state, or publication claim. Its receipts: merge
  `e5d0f6a9`, exact head `5cc1c866`, exact-head CI `30808291831` green. **It did
  not pre-record itself here**, so its post-merge run `30810160121` failed on the
  baseline-lapse detector and left `main` red; run `30894938975` reproduced the
  same single failure. PR #101 below discharges that lapse — recorded honestly
  rather than elided.
- PR #101: this recomputation of the canonical baseline from `main@2c6a63f1` to
  `main@e5d0f6a9`, updating this map's `Baseline:` line, `GOAL.md`, and
  `.planning/STATE.md`, and recording PR #99's receipts above so the
  baseline-lapse detector passes and `main` is green again. It admits no source
  node and changes no benchmark, measurement, admission state, or publication
  claim. Recorded here before merge for the same reason as PRs #97 and #98: the
  detector requires every PR merged after the baseline to appear in this map.
  Delivered from exact head `380294beeffaf4881e0c1531c9edb1efa2bde1f9`
  with all required exact-head CI green in run `30957633560`; merge
  `39e25411e81f7cc1189929211464d0fcf09a0ffe` at
  `2026-08-04T23:13:57Z`.
- PR #100: the node `T9` M03 registry admission, registering
  `wmbs-m03-valid-time-development` in `eval/public/registry.json` with its
  runner adapter, profile contract, `allowed_profile` label, scored-denominator
  handling in `eval/public/bundle.py`, `eval/public/README.md` disclosure, and
  `tests/test_public_wmbs_m03_registry_admission.py`. Reachability only: M03
  stays `PROPOSED` and full bitemporal transaction-time remains a hard deferral.
  Delivered from exact head `0a9e5bedd991409e58c4317f2fa48b78c3458c1e`
  after all required exact-head CI and Greptile passed in run `31854371658`;
  merge `b84b351bcd5a0397065821f60db425ae8c85a13a` at
  `2026-08-15T01:12:26Z`; successful post-merge CI `31855873247`. It changed no
  fixture byte, scorer, schema, admission state, publication claim, or progress
  counter and admitted no source node or successor node.
- PR #103: Restore canonical memory sources and patch cryptography (merge 4b086a3d4a).
- PR #105: preserve hash-bound text as LF and make installer/custody tests
  explicit about their native-Windows and POSIX execution contracts. Delivered
  from exact head `c1cbae81a579ea1f8398c98074b522aae7209d7e` after all
  required exact-head CI passed in run `31856191898`; merge
  `66c989ef2fa599b41388975ad0516ff8d7f0e7e7` at
  `2026-08-15T01:46:23Z`. Post-merge run `31857410462` failed solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  (1 failed, 4709 passed, 151 skipped, 191 deselected) because PR #105 was
  absent from the lifecycle authorities; PR #108 repairs that traceability
  lapse here.
- PR #106: record merged PR #103 in the write-lease map (merge 4128b070f50cdf3b34c8cea97d53007c218e40ed).
- PR #107: record merged PR #106 in the write-lease map; delivered from exact
  head `ee319953c9d82cdcf35942b29152954cb1307273` with all required exact-head
  CI green in run `31852940363`; merge
  `518fdb8bb24927bd88bed596cb99e736038374b9` at
  `2026-08-15T00:40:44Z`.
- PR #108: reconcile PR #100's exact T9 lease and inventory wording and repair
  PR #105's baseline-lapse receipt. Delivered from exact head
  `2d8409c055f7f2eeb6453cd3b7caab002e4676e1` after all required exact-head CI
  passed in run `31859014653`; merge
  `b87331b2eaad7576728e07941983972ce19b906b` at
  `2026-08-15T02:45:01Z`; successful post-merge CI `31859997325`. It changed no
  source, benchmark, measurement, admission state, publication claim, or
  progress counter.
- PR #113: controller-only `T10` lifecycle receipt reserving the four frozen
  Windows portability content and its strict integration order. Delivered from
  exact head `37afb7e839277746b76baf01775a6f072deb2b09` after all required
  exact-head checks passed in run `31863057094`; merge
  `fbbd5c0ccebe9c4d821bcf619adec5d6cf1b2c24` at
  `2026-08-15T04:22:14Z`; successful post-merge CI `31864254074`. It changed
  only `GOAL.md`, `.planning/STATE.md`, and this map and admitted no benchmark
  authority.
- PR #114: controller-only `T10` amendment recording PR #109 delivery and
  replacing the ruleset-incompatible full-head freeze with immutable content
  anchors plus exact lifecycle-parent equality. Delivered from exact head
  `282d184baafaaa0164f06019bedf476bb3767d48` after all required exact-head
  checks passed in run `31868231552`; merge
  `94f1afd2d5bf5282764f4d1582e2425757490891` at
  `2026-08-15T06:26:57Z`; successful post-main CI `31869469070`. It changed
  only `GOAL.md`, `.planning/STATE.md`, and this map and granted no benchmark
  authority.
- PR #115: M02 Stage-B public-harness delivery from exact head
  `422883bf6fb75b125744ba23afe0bb15ba449362`; all required exact-head checks
  passed in run `31899050596`; merge
  `d181666b61cd483e50326f42eb59328f6c8f9da4` at
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
  `a660b8f80af424ca700dd8660dfbda6b92baf42c` as
  `752e1d1672ceb7c1a9b05301d296d42c250e90b2` at `2026-08-31T18:03:53Z`.
  The OPEN/READY text above is the historical self-record; PR #117 owns no
  current lifecycle writer.
- PR #121: M04-B public-harness registration of `wmbs-m04-development`
  (title: M04-B: register wmbs-m04-development (PROPOSED)) from exact head
  `a3c5836677f041043817f738c8ac83cb0d76f494`; all required exact-head
  checks passed in run `33425340224`; merge
  `08d39639c43e590688f66c196e5bea4835dd9a35` at `2026-08-31T19:05:18Z`
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
  from exact head `dad0d1d329b913edb08f58355cdafd5d64fef6fc`; all
  required exact-head checks passed in run `33910693005`; merge
  `eb3320d4eab18326e8013169c8b94bddf70ebb67` at `2026-09-04T19:46:04Z`.
  Prior tip was `9b451b192ea71dd5619deb073d3456d4ae7c9e49` (PR #129 /
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
  from exact head `92cc44f27486fec58442b5b81ef7818c0b7be152`; all
  required exact-head checks passed in run `33918171983`; merge
  `0bb4f559eb716a5c5958acf44859c774646d4c28` at `2026-09-04T21:20:51Z`.
  Prior tip was `94825265b0276cef1fc73d430d0d89f1a514b1b1` (PR #131 /
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
  from exact head `8d4a1ec29efb4f16fdff1b13f2c11aeef69db287`; all
  required exact-head checks passed in run `33923271250`; merge
  `9288c12c88a7a408b3d1ed047e142f96ea13aa63` at `2026-09-04T22:26:38Z`.
  Prior tip was `6e41fb161a3dfd4cf88ea301895a3488fec0fa71` (PR #133 /
  #130 receipt). Post-main may fail solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #132 is absent from this lease-map; this receipt repairs
  that bookkeeping. Exclusive File Set:
  `docs/coordination/2026-08-03-wmbs-module-completeness-inventory.md`.
  Owner: Docs / CoS (inventory ACCEPT). Purpose: Accept plan-PR
  receipts for M06–M09/M11/M17–M19 inventory; docs-only privacy.
  Gate: MERGED (merge commit
  `9288c12c88a7a408b3d1ed047e142f96ea13aa63`). The merge touched only
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
  from exact head `3d339c9eda07f8c2cccb9fd7c5b195cd859bf5fa`; all
  required exact-head checks passed in run `33938772720`; merge
  `eb51a0654545f31e123932dfd5598a67fb6de734` at `2026-09-05T02:50:49Z`.
  Prior tip was `89a74a019d0daff163e4319a7b59b0f8eb617dce` (PR #135).
  Post-main run `33940223834` failed solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #138 was absent from this lease-map; this receipt repairs
  that bookkeeping. Exclusive File Set:
  `eval/public/bundle.py`, `tests/test_public_whole_memory_reference.py`.
  Purpose: M02 canonical-replay seed pin; docs-only privacy for THIS
  receipt PR (the recorded #138 was code). This receipt changes no
  benchmark result or admission state and does not recompute the
  canonical baseline (baseline stays `main@d181666b`).
- PR #141: ordinary documentation receipt recording the merged PR #138
  lease-map lapse. It is **MERGED** at tip
  `9eefd48274462ecc8961dd5f53f053b496eb7d25`. It was **OPEN/READY** at the
  `2026-09-05T11:24:20Z` capture and adds only the PR #138 merged-baseline
  bullet and this structured self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #141 changes no benchmark result or admission state and does not
  recompute the canonical baseline. The OPEN/READY pre-merge instruction
  is historical; delivery is MERGED at tip
  `9eefd48274462ecc8961dd5f53f053b496eb7d25`.
- PR #139: N12 result-v2 Exact 12 leaderboard files
  (title: feat(leaderboard): additive result-v2 integration (N12))
  from exact head `363b60e5ff1bcef6787eec9793c8db3b278304fd`; all
  required exact-head checks passed in run `33966741689`; merge
  `73bea352a86e7eb868c9928219a4f9421fdea93b` at `2026-09-05T13:11:54Z`.
  Prior tip was `9eefd48274462ecc8961dd5f53f053b496eb7d25` (PR #141).
  Post-main tip CI may fail solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #139 was absent from this lease-map; this receipt repairs
  that bookkeeping. Exclusive File Set (Exact 12):
  `eval/provider_bakeoff/README.md`, `leaderboard/ledger.py`,
  `leaderboard/publish.py`, `leaderboard/readiness.py`,
  `leaderboard/render.py`, `leaderboard/schema/result-v2.schema.json`,
  `leaderboard/validate.py`, `tests/test_leaderboard_ledger.py`,
  `tests/test_leaderboard_publish.py`,
  `tests/test_leaderboard_readiness.py`,
  `tests/test_leaderboard_render.py`,
  `tests/test_leaderboard_result_contract.py`.
  Purpose: additive result-v2 integration (N12); docs-only privacy
  for THIS receipt PR (the recorded #139 was code). This receipt
  changes no benchmark result or admission state and does not
  recompute the canonical baseline (baseline stays `main@d181666b`).
- PR #142: ordinary documentation receipt recording the merged PR #139
  lease-map lapse. It is **MERGED** at tip
  `47f44ef364ff726ab9bb4d409a1b49ac23ea1fa5`. It adds only the PR #139
  merged-baseline bullet, the #141 MERGED mark, and this structured
  self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #142 changes no benchmark result or admission state and does not
  recompute the canonical baseline. Delivery is MERGED at tip
  `47f44ef364ff726ab9bb4d409a1b49ac23ea1fa5`.
- PR #140: Exact 1 smoke `tests/test_leaderboard_render_output_smoke.py`
  (title: test(leaderboard): Frontend render-output smoke (CLEAR of N12))
  from exact head `45a7ea18df6ba32b5664b408174376781aaf2b4f`; all
  required exact-head checks passed in run `33973084704`; merge
  `8badc4efe97f38119adc8ac24cdbdb06977aa8d4` at `2026-09-05T18:33:19Z`.
  Prior tip was `47f44ef364ff726ab9bb4d409a1b49ac23ea1fa5` (PR #142).
  Post-main tip CI may fail solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #140 was absent from this lease-map; this receipt repairs
  that bookkeeping. Exclusive File Set (Exact 1):
  `tests/test_leaderboard_render_output_smoke.py`.
  Purpose: Frontend render-output smoke (CLEAR of N12); docs-only privacy
  for THIS receipt PR (the recorded #140 was test). This receipt
  changes no benchmark result or admission state and does not
  recompute the canonical baseline (baseline stays `main@d181666b`).
- PR #143: ordinary documentation receipt recording the merged PR #140
  lease-map lapse. It is **MERGED** at tip
  `d98bf6467a2915b5a596830ec40add1f90a3bc38`. It adds only the PR #140
  merged-baseline bullet, the #142 MERGED mark, and this structured
  self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #143 changes no benchmark result or admission state and does not
  recompute the canonical baseline. Delivery is MERGED at tip
  `d98bf6467a2915b5a596830ec40add1f90a3bc38`.
- PR #137: Exact 1 ship-day receipt
  `docs/coordination/2026-09-04-ship-day-receipt.md`
  (title: docs(coordination): 2026-09-04 ship-day receipt)
  from exact head `54bbb3274f3060b8534ae52a30f970310870eecf`; all
  required exact-head checks passed in run `33988815458`; merge
  `787a0052e5319b103cbaae9b2aeeea5a066c3b1e` at `2026-09-05T20:30:00Z`.
  Prior tip was `d98bf6467a2915b5a596830ec40add1f90a3bc38` (PR #143).
  Post-main tip CI may fail solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #137 was absent from this lease-map; this receipt repairs
  that bookkeeping. Exclusive File Set (Exact 1):
  `docs/coordination/2026-09-04-ship-day-receipt.md`.
  Purpose: 2026-09-04 ship-day receipt; docs-only privacy for THIS
  receipt PR (the recorded #137 was documentation). This receipt
  changes no benchmark result or admission state and does not
  recompute the canonical baseline (baseline stays `main@d181666b`).
- PR #145: ordinary documentation receipt recording the merged PR #137
  lease-map lapse. It is **MERGED** at tip
  `30b3657b81bd28600296df4e658bb2104cb1cf1f`. It adds only the PR #137
  merged-baseline bullet, the #143 MERGED mark, and this structured
  self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #145 changes no benchmark result or admission state and does not
  recompute the canonical baseline. Delivery is MERGED at tip
  `30b3657b81bd28600296df4e658bb2104cb1cf1f`.
- PR #144: Exact 4 REPRO-001 files
  `eval/public/README.md`, `eval/public/bundle.py`,
  `eval/public/schema/reproducibility-bundle-v1.schema.json`,
  `tests/test_public_reproducibility.py`
  (title: feat(eval): REPRO-001 closed reproducibility-bundle/v1 standard)
  from exact head `cbe1b8e95ddfec1f6283bfcf948e0bbb659a3a9a`; all
  required exact-head checks passed in run `33995734474`; merge
  `525d2a1335b97b9ec44308623460e262427e8172` at `2026-09-05T22:53:04Z`.
  Prior tip was `30b3657b81bd28600296df4e658bb2104cb1cf1f` (PR #145).
  Post-main tip CI may fail solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #144 was absent from this lease-map; this receipt repairs
  that bookkeeping. Exclusive File Set (Exact 4):
  `eval/public/README.md`, `eval/public/bundle.py`,
  `eval/public/schema/reproducibility-bundle-v1.schema.json`,
  `tests/test_public_reproducibility.py`.
  Purpose: REPRO-001 closed reproducibility-bundle/v1 standard; docs-only
  privacy for THIS receipt PR (the recorded #144 was code). This receipt
  changes no benchmark result or admission state and does not
  recompute the canonical baseline (baseline stays `main@d181666b`).
- PR #146: ordinary documentation receipt recording the merged PR #144
  lease-map lapse. It is **MERGED** at tip
  `a648ab730f92b6d84d2c32580656184d8ce830f4`. It adds only the PR #144
  merged-baseline bullet, the #145 MERGED mark, and this structured
  self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #146 changes no benchmark result or admission state and does not
  recompute the canonical baseline. Delivery is MERGED at tip
  `a648ab730f92b6d84d2c32580656184d8ce830f4`.
- PR #147: Exact 3 P15-S2/15-01-01 cadence-tier files
  `src/mnemosyne/policy.py`, `src/mnemosyne/consolidation.py`,
  `tests/test_consolidation_timescales.py`
  (title: feat(consolidation): P15-S2 15-01-01 deterministic
  fast|medium|slow cadence tiers)
  from exact head `a9131fc3de0f37e7ebb0670c68d0edb683c97d0e`; all
  required exact-head checks passed in run `34000600922`; merge
  `1fb9b6e35c25ebc1e822d0f0bce8b9a05a45838b` at `2026-09-06T00:39:38Z`.
  Prior tip was `a648ab730f92b6d84d2c32580656184d8ce830f4` (PR #146).
  Post-main Unit+drift may fail solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #147 was absent from this lease-map; this receipt repairs
  that bookkeeping, and that lapse is expected until THIS receipt
  lands. Exclusive File Set (Exact 3):
  `src/mnemosyne/policy.py`, `src/mnemosyne/consolidation.py`,
  `tests/test_consolidation_timescales.py`.
  Purpose: P15-S2 CAP-007/008 first slice — deterministic
  fast|medium|slow cadence tiers; docs-only privacy for THIS receipt
  PR (the recorded #147 was code). Persist-history engine storage
  remains lease-OUT / deferred (not admitted by #147). Hold 15-01-02
  remains serialized after this. This receipt changes no benchmark
  result or admission state, admits no successor source node, and does
  not recompute the canonical baseline (baseline stays `main@d181666b`).
- PR #148: ordinary documentation receipt recording the merged PR #147
  lease-map lapse. It is **MERGED** at tip
  `9f9b9c7841d789a42d24299d4f406a8ce2efc8a7`. It was **OPEN/READY** at
  the `2026-09-06T00:42:00Z` capture and adds only the PR #147
  merged-baseline bullet, the #146 MERGED mark, and this structured
  self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #148 changes no benchmark result or admission state and does not
  recompute the canonical baseline. Delivery is MERGED at tip
  `9f9b9c7841d789a42d24299d4f406a8ce2efc8a7`.
- PR #118: Exact 1 M07 retention plan
  `docs/plans/wmb-m07-retention-rehearsal-decay-implementation-plan.md`
  (title: docs: PROPOSED M07 retention plan (not code-ready) — CoS
  ACCEPT merged)
  from exact head `301a1c60fc935697c2127cf74c088bd2057e7646`; all
  required exact-head checks passed in run `34004284333`; merge
  `1e46378319a3dbc189e9c7298eda026360a64354` at `2026-09-06T02:04:19Z`.
  Prior tip was `9f9b9c7841d789a42d24299d4f406a8ce2efc8a7` (PR #148).
  Post-main Unit+drift FAILED CI `34005513700` solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #118 was absent from this lease-map (baseline
  `main@d181666b`); this receipt repairs that bookkeeping.
  Exclusive File Set (Exact 1):
  `docs/plans/wmb-m07-retention-rehearsal-decay-implementation-plan.md`.
  Purpose: ACCEPT M07 retention/rehearsal/decay implementation plan
  (PROPOSED / NOT CODE-READY); docs-only privacy for THIS receipt
  PR (the recorded #118 was documentation). This receipt does not
  admit Stage A code or invent M16; the M14 freeze is unchanged.
  This receipt changes no benchmark result or admission state,
  admits no successor source node, and does not recompute the
  canonical baseline (baseline stays `main@d181666b`).
- PR #150: ordinary documentation receipt recording the merged PR #118
  lease-map lapse. It is **MERGED** at tip
  `b9c669adfd76dd3f2dbf76ffde35f5fb867cf3e1`. It was **OPEN/READY** at
  the `2026-09-06T02:28:00Z` capture and adds only the PR #118
  merged-baseline bullet, the #148 MERGED mark, and this structured
  self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #150 changes no benchmark result or admission state and does not
  recompute the canonical baseline. Delivery is MERGED at tip
  `b9c669adfd76dd3f2dbf76ffde35f5fb867cf3e1`.
- PR #149: Exact 3 P15-S2/15-01-02 async sleep job and freshness files
  `src/mnemosyne/consolidation.py`, `src/mnemosyne/jobs.py`,
  `tests/test_consolidation_timescales.py`
  (title: feat(consolidation): P15-S2 15-01-02 async sleep job and
  freshness)
  from exact head `d6f85c776f2129328bcb223aee40d93c148c91ce`; merge
  `9013b5dfe46897a68075774913a764fdaa555df6` at `2026-09-06T03:54:58Z`.
  Prior tip was `b9c669adfd76dd3f2dbf76ffde35f5fb867cf3e1` (PR #150).
  Post-main tip Unit+drift proving on CI `34010182120`
  because PR #149 was absent from this lease-map (baseline
  `main@d181666b`); this receipt repairs that bookkeeping like
  prior Exact-1 receipts. Exclusive File Set (Exact 3):
  `src/mnemosyne/consolidation.py`, `src/mnemosyne/jobs.py`,
  `tests/test_consolidation_timescales.py`.
  Purpose: P15-S2/15-01-02 async sleep consolidation job + freshness;
  docs-only privacy for THIS receipt PR is Exact-1 lease-map only
  (the recorded #149 was code). This receipt does not invent M16;
  the M14 freeze is unchanged. This receipt changes no benchmark
  result or admission state, admits no successor source node, and
  does not recompute the canonical baseline (baseline stays
  `main@d181666b`).
- PR #151: ordinary documentation receipt recording the merged PR #149
  lease-map lapse. It is **MERGED** at tip
  `0478bc02b73e4a6672b625b6246868f86dc067b1`. It was **OPEN/READY** at
  the `2026-09-06T03:58:00Z` capture and adds only the PR #149
  merged-baseline bullet, the #150 MERGED mark, and this structured
  self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #151 changes no benchmark result or admission state and does not
  recompute the canonical baseline. Delivery is MERGED at tip
  `0478bc02b73e4a6672b625b6246868f86dc067b1`.
- PR #152: Exact 1 M01/M03/M10 peer public README cells
  `eval/public/README.md`
  (title: docs(eval): promote M01/M03/M10 to peer public README cells)
  from exact head `ce1a3a8a8b2f9b94ad0d1205e30bec6e66351452`; all
  required exact-head checks passed in run `34011817634`; merge
  `b164c90f72019478ed009e3e03f8a7dd1048901e` at `2026-09-06T05:04:23Z`.
  Prior tip was `0478bc02b73e4a6672b625b6246868f86dc067b1` (PR #151).
  Post-main tip Unit+drift proving on CI `34013065647`
  because PR #152 was absent from this lease-map (baseline
  `main@d181666b`); this receipt repairs that bookkeeping like
  prior Exact-1 receipts. Exclusive File Set (Exact 1):
  `eval/public/README.md`.
  Purpose: promote M01/M03/M10 to peer public README cells;
  docs-only privacy for THIS receipt PR is Exact-1 lease-map only
  (the recorded #152 was documentation). This receipt does not
  invent modules; the M14 freeze is unchanged. This receipt
  changes no benchmark result or admission state, admits no
  successor source node, and does not recompute the canonical
  baseline (baseline stays `main@d181666b`).
- PR #154: ordinary documentation receipt recording the merged PR #152
  lease-map lapse. It is **MERGED** at tip
  `7b2921f0a01cdb65f8079fd2907d1c0439c61dc5`. It was **OPEN/READY** at
  the `2026-09-06T05:07:00Z` capture and adds only the PR #152
  merged-baseline bullet, the #151 MERGED mark, and this structured
  self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #154 changes no benchmark result or admission state and does not
  recompute the canonical baseline. Delivery is MERGED at tip
  `7b2921f0a01cdb65f8079fd2907d1c0439c61dc5`.
- PR #119: Exact 1 M08 reversible-forgetting plan
  `docs/plans/wmb-m08-reversible-forgetting-implementation-plan.md`
  (title: docs: PROPOSED M08 reversible-forgetting plan (not
  code-ready))
  from exact head `83d73817ca407b8731412522dfd724d798c42e06`; all
  required exact-head checks passed in run `34016028705`; merge
  `dfe27e78a0b2b1b704056d5e22c37060073997b1` at `2026-09-06T23:56:22Z`.
  Prior tip was `7b2921f0a01cdb65f8079fd2907d1c0439c61dc5` (PR #154).
  Post-main Unit+drift FAILED CI `34068262456` (and later scheduled
  nightly `34593641592`) solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #119 was absent from this lease-map (baseline
  `main@d181666b`); this receipt repairs that bookkeeping.
  Exclusive File Set (Exact 1):
  `docs/plans/wmb-m08-reversible-forgetting-implementation-plan.md`.
  Purpose: ACCEPT M08 reversible-forgetting implementation plan
  (PROPOSED / NOT CODE-READY); docs-only privacy for THIS receipt
  PR (the recorded #119 was documentation). This receipt does not
  admit Stage A code or invent M16; the M14 freeze is unchanged.
  This receipt changes no benchmark result or admission state,
  admits no successor source node, and does not recompute the
  canonical baseline (baseline stays `main@d181666b`).
- PR #156: ordinary documentation receipt recording the merged PR #119
  lease-map lapse. It is **MERGED** at tip
  `b7a0b8db65c5a91ce4b102491108ee027f7153ac`. It was **OPEN/READY** at
  the `2026-09-11T21:42:00Z` capture and adds only the PR #119
  merged-baseline bullet, the #154 MERGED mark, and this structured
  self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #156 changes no benchmark result or admission state and does not
  recompute the canonical baseline. Delivery is MERGED at tip
  `b7a0b8db65c5a91ce4b102491108ee027f7153ac`.
- PR #153: Exact 7 global_sensemaking RAPTOR projection
  `eval/g0/sensemaking.py`, `src/mnemosyne/engine.py`,
  `src/mnemosyne/pipeline.py`, `src/mnemosyne/postgres_engine.py`,
  `src/mnemosyne/retrieval.py`, `src/mnemosyne/sqlite_engine.py`,
  `tests/test_global_sensemaking.py`
  (title: feat(retrieval): global_sensemaking RAPTOR projection
  (15-01-03))
  from exact head `c7382cdf626dcd522585dc27ba457f0874950eeb`; all
  required exact-head checks passed in run `34656393990`; merge
  `1fc359792616910d003f4a22862851251c19f646` at `2026-09-11T23:28:34Z`.
  Prior tip was `b7a0b8db65c5a91ce4b102491108ee027f7153ac` (PR #156).
  Post-main tip Unit+drift will FAIL on CI `34658202166`
  solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #153 is absent from this lease-map (baseline
  `main@d181666b`); this receipt repairs that bookkeeping
  like prior Exact-1 receipts. Exclusive File Set (Exact 7):
  `eval/g0/sensemaking.py`, `src/mnemosyne/engine.py`,
  `src/mnemosyne/pipeline.py`, `src/mnemosyne/postgres_engine.py`,
  `src/mnemosyne/retrieval.py`, `src/mnemosyne/sqlite_engine.py`,
  `tests/test_global_sensemaking.py`.
  Purpose: P15-S2/15-01-03 global_sensemaking RAPTOR projection;
  docs-only privacy for THIS receipt PR is Exact-1 lease-map only
  (the recorded #153 was code). This receipt does not invent M16;
  the M14 freeze is unchanged. This receipt changes no benchmark
  result or admission state, admits no successor source node, and
  does not recompute the canonical baseline (baseline stays
  `main@d181666b`).
- PR #157: ordinary documentation receipt recording the merged PR #153
  lease-map lapse. It is **MERGED** at tip
  `cd8439c09f8940e2e6f3d427e79e303e0a5bb57e`. It was **OPEN/READY** at
  the `2026-09-11T23:31:00Z` capture and adds only the PR #153
  merged-baseline bullet, the #156 MERGED mark, and this structured
  self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #157 changes no benchmark result or admission state and does not
  recompute the canonical baseline. Delivery is MERGED at tip
  `cd8439c09f8940e2e6f3d427e79e303e0a5bb57e`.
- PR #158: Exact 4 surprise-gated write closure
  `src/mnemosyne/ingestion.py`, `src/mnemosyne/consolidation.py`,
  `eval/g0/write_gating.py`, `tests/test_surprise_gated_writes.py`
  (title: feat(write-gate): surprise-gated write closure (15-01-04))
  from exact head `51cf8326fc7b603989c5ed4d5ce93341a8589ab1`; all
  required exact-head checks passed in run `34662859990`; merge
  `deca887c71f7f94652645faf076420668dfcb599` at `2026-09-12T01:17:36Z`.
  Prior tip was `cd8439c09f8940e2e6f3d427e79e303e0a5bb57e` (PR #157).
  Post-main tip Unit+drift will FAIL on CI `34664389273`
  solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #158 is absent from this lease-map (baseline
  `main@d181666b`); this receipt repairs that bookkeeping
  like prior Exact-1 receipts. Exclusive File Set (Exact 4):
  `src/mnemosyne/ingestion.py`, `src/mnemosyne/consolidation.py`,
  `eval/g0/write_gating.py`, `tests/test_surprise_gated_writes.py`.
  Purpose: P15-S2/15-01-04 surprise-gated write closure;
  docs-only privacy for THIS receipt PR is Exact-1 lease-map only
  (the recorded #158 was code). This receipt does not invent M16;
  the M14 freeze is unchanged. This receipt changes no benchmark
  result or admission state, admits no successor source node, and
  does not recompute the canonical baseline (baseline stays
  `main@d181666b`).
- PR #159: ordinary documentation receipt recording the merged PR #158
  lease-map lapse. It is **MERGED** at tip
  `fd7864cc9a5e773be37168157a53078a44ded44a`. It was **OPEN/READY** at
  the `2026-09-12T01:20:00Z` capture and adds only the PR #158
  merged-baseline bullet, the #157 MERGED mark, and this structured
  self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #159 changes no benchmark result or admission state and does not
  recompute the canonical baseline. Delivery is MERGED at tip
  `fd7864cc9a5e773be37168157a53078a44ded44a`.
- PR #160: Exact 2 S2 continual-learning evidence closure
  `eval/g0/continual_learning.py`, `eval/reports/phase-15-s2-capabilities.md`
  (title: feat(eval): S2 continual-learning evidence closure (15-01-06))
  from exact head `35e06e7955b479480ae4670fc75ec88ad519bd58`; all
  required exact-head checks passed in run `34667992401`; merge
  `75ae284f7137bd527e983b4f493709e7f83f87c5` at `2026-09-12T03:03:18Z`.
  Prior tip was `fd7864cc9a5e773be37168157a53078a44ded44a` (PR #159).
  Post-main tip Unit+drift will FAIL on CI `34669328279`
  solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #160 is absent from this lease-map (baseline
  `main@d181666b`); this receipt repairs that bookkeeping
  like prior Exact-1 receipts. Exclusive File Set (Exact 2):
  `eval/g0/continual_learning.py`, `eval/reports/phase-15-s2-capabilities.md`.
  Purpose: P15-S2/15-01-06 S2 continual-learning evidence closure;
  docs-only privacy for THIS receipt PR is Exact-1 lease-map only
  (the recorded #160 was code). This receipt does not invent M16;
  the M14 freeze is unchanged. This receipt changes no benchmark
  result or admission state, admits no successor source node, and
  does not recompute the canonical baseline (baseline stays
  `main@d181666b`).
- PR #161: ordinary documentation receipt recording the merged PR #160
  lease-map lapse. It is **MERGED** at tip
  `0313630ed2f3a1a3ef8685976ae7428a7df25024`. It was **OPEN/READY** at
  the `2026-09-12T03:05:00Z` capture and adds only the PR #160
  merged-baseline bullet, the #159 MERGED mark, and this structured
  self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #161 changes no benchmark result or admission state and does not
  recompute the canonical baseline. Delivery is MERGED at tip
  `0313630ed2f3a1a3ef8685976ae7428a7df25024`.
- PR #162: Exact 3 security-calibration development Stage A
  `eval/public/fixtures/security-calibration-development.json`,
  `eval/public/security_calibration.py`,
  `tests/test_public_security_calibration.py`
  (title: feat(eval): security-calibration development Stage A (15-02))
  from exact head `b03f3a73fe60c363fa15d79e689db0204783e386`; all
  required exact-head checks passed in run `34701573916`; merge
  `50e5292513e0d7ce5f1bfaaa5aab9c6bc89de022` at `2026-09-12T15:37:22Z`.
  Prior tip was `0313630ed2f3a1a3ef8685976ae7428a7df25024` (PR #161).
  Post-main tip Unit+drift will FAIL on CI `34702788518`
  solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #162 is absent from this lease-map (baseline
  `main@d181666b`); this receipt repairs that bookkeeping
  like prior Exact-1 receipts. Exclusive File Set (Exact 3):
  `eval/public/fixtures/security-calibration-development.json`,
  `eval/public/security_calibration.py`,
  `tests/test_public_security_calibration.py`.
  Purpose: 15-02 security-calibration development Stage A;
  docs-only privacy for THIS receipt PR is Exact-1 lease-map only
  (the recorded #162 was code). This receipt does not invent M16;
  the M14 freeze is unchanged. This receipt changes no benchmark
  result or admission state, admits no successor source node, and
  does not recompute the canonical baseline (baseline stays
  `main@d181666b`).
- PR #163: ordinary documentation receipt recording the merged PR #162
  lease-map lapse. It is **MERGED** at tip
  `c7cf6958dec615baa2ad1c20a6dc5aad900cd9c5`. It was **OPEN/READY** at
  the `2026-09-12T15:40:00Z` capture and adds only the PR #162
  merged-baseline bullet, the #161 MERGED mark, and this structured
  self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #163 changes no benchmark result or admission state and does not
  recompute the canonical baseline. Delivery is MERGED at tip
  `c7cf6958dec615baa2ad1c20a6dc5aad900cd9c5`.
- PR #164: Exact 8 security-calibration Stage B
  `eval/public/adapters/security_calibration_probe.py`,
  `eval/public/bundle.py`,
  `eval/public/registry.json`,
  `eval/public/runner.py`,
  `eval/public/scoring.py`,
  `tests/test_public_eval.py`,
  `tests/test_public_eval_scoring.py`,
  `tests/test_wmbs_module_inventory.py`
  (title: feat(eval): security-calibration Stage B public registration
  (15-02))
  from exact head `3876a62a3be158beb65fab2439f79adbfccda160`; all
  required exact-head checks passed in run `34709624586`; merge
  `b29ba9983c844cddd1673db4a5503222e695155a` at `2026-09-12T18:21:34Z`.
  Prior tip was `c7cf6958dec615baa2ad1c20a6dc5aad900cd9c5` (PR #163).
  Post-main tip Unit+drift will FAIL on CI `34710947939`
  solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #164 is absent from this lease-map (baseline
  `main@d181666b`); this receipt repairs that bookkeeping
  like prior Exact-1 receipts. Exclusive File Set (Exact 8):
  `eval/public/adapters/security_calibration_probe.py`,
  `eval/public/bundle.py`,
  `eval/public/registry.json`,
  `eval/public/runner.py`,
  `eval/public/scoring.py`,
  `tests/test_public_eval.py`,
  `tests/test_public_eval_scoring.py`,
  `tests/test_wmbs_module_inventory.py`.
  Purpose: 15-02 security-calibration Stage B;
  docs-only privacy for THIS receipt PR is Exact-1 lease-map only
  (the recorded #164 was code). This receipt does not invent M16;
  the M14 freeze is unchanged. This receipt changes no benchmark
  result or admission state, admits no successor source node, and
  does not recompute the canonical baseline (baseline stays
  `main@d181666b`).
- PR #165: ordinary documentation receipt recording the merged PR #164
  lease-map lapse. It is **MERGED** at tip
  `f0f31d31bc0b3ec753d3f1505ae230b76d591e19`. It was **OPEN/READY** at
  the `2026-09-12T18:26:00Z` capture and adds only the PR #164
  merged-baseline bullet, the #163 MERGED mark, and this structured
  self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #165 changes no benchmark result or admission state and does not
  recompute the canonical baseline. Delivery is MERGED at tip
  `f0f31d31bc0b3ec753d3f1505ae230b76d591e19`.
- PR #166: Exact 6 CAP-006 / P15-S4 / 15-03-01 warm-serial + concurrent
  latency receipts
  `eval/latency/bench.py`,
  `eval/latency/bench_concurrent.py`,
  `eval/latency/test_latency_bench.py`,
  `eval/latency_warm/bench_warm.py`,
  `eval/latency/reports/phase15-s4-warm.json`,
  `eval/latency/reports/phase15-s4-concurrent.json`
  (title: feat(eval): freeze CAP-006 warm and concurrent latency
  receipt ABI (15-03-01))
  from exact head `2d578aedfdee91051bd9963ffd0940789dc679c6`; all
  required exact-head Unit+drift checks passed in run `34715638835`;
  merge `6a6d88a41081c95124a2e1e3c82ea857b0b392eb` at
  `2026-09-12T20:21:56Z`.
  Prior tip was `f0f31d31bc0b3ec753d3f1505ae230b76d591e19` (PR #165).
  Post-main tip Unit+drift will FAIL solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #166 is absent from this lease-map (baseline
  `main@d181666b`); this receipt repairs that bookkeeping
  like prior Exact-1 receipts. Exclusive File Set (Exact 6):
  `eval/latency/bench.py`,
  `eval/latency/bench_concurrent.py`,
  `eval/latency/test_latency_bench.py`,
  `eval/latency_warm/bench_warm.py`,
  `eval/latency/reports/phase15-s4-warm.json`,
  `eval/latency/reports/phase15-s4-concurrent.json`.
  Purpose: P15-S4/15-03-01 CAP-006 warm/concurrent latency (no claimed
  P95); docs-only privacy for THIS receipt PR is Exact-1 lease-map only
  (the recorded #166 was code). This receipt does not invent M16;
  the M14 freeze is unchanged. This receipt changes no benchmark
  result or admission state, admits no successor source node, and
  does not recompute the canonical baseline (baseline stays
  `main@d181666b`).
- PR #167: ordinary documentation receipt recording the merged PR #166
  lease-map lapse. It is **MERGED** at tip
  `a71599efffb3e4eb65c3fcfbe425d01c06a26e82`. It was **OPEN/READY** at
  the `2026-09-12T20:24:00Z` capture and adds only the PR #166
  merged-baseline bullet, the #165 MERGED mark, and this structured
  self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #167 changes no benchmark result or admission state and does not
  recompute the canonical baseline. Delivery is MERGED at tip
  `a71599efffb3e4eb65c3fcfbe425d01c06a26e82`.
- PR #170: Exact 1 sitecustomize/planning_traceability fix
  `tests/test_planning_traceability.py`
  (title: fix planning_traceability sitecustomize bootstrap test for
  Ubuntu 3.12 site import)
  from exact head `bad2911b0ab6ca01f9daee64b408d69147c7c98c`; all
  required exact-head Unit+drift checks passed in run `35463262102`;
  merge `d070681cd27633a2387fac0634c3e307777d8102` at
  `2026-09-19T19:27:35Z`.
  Prior tip was `a71599efffb3e4eb65c3fcfbe425d01c06a26e82` (PR #167).
  Post-main tip Unit+drift will FAIL solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #170 is absent from this lease-map (baseline
  `main@d181666b`); this receipt repairs that bookkeeping
  like prior Exact-1 receipts. Exclusive File Set (Exact 1):
  `tests/test_planning_traceability.py`.
  Purpose: sitecustomize/planning_traceability Ubuntu 3.12 site-import
  fix; docs-only privacy for THIS receipt PR is Exact-1 lease-map only
  (the recorded #170 was test). This receipt does not invent M16;
  the M14 freeze is unchanged. This receipt changes no benchmark
  result or admission state, admits no successor source node, and
  does not recompute the canonical baseline (baseline stays
  `main@d181666b`).
- PR #171: ordinary documentation receipt recording the merged PR #170
  lease-map lapse. It is **MERGED** at tip
  `7789649d1f40d3b047d4edfec93c56c3edb0a6d2`. It was **OPEN/READY** at
  the `2026-09-19T19:55:00Z` capture and adds only the PR #170
  merged-baseline bullet, the #167 MERGED mark, and this structured
  self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #171 changes no benchmark result or admission state and does not
  recompute the canonical baseline. Delivery is MERGED at tip
  `7789649d1f40d3b047d4edfec93c56c3edb0a6d2`.
- PR #169: Exact 4 harness-only 15-03-03 scale/100k
  `eval/scale/bench_100k.py`,
  `tests/test_scale_100k.py`,
  `tests/test_postgres_perf_lanes.py`,
  `eval/scale/reports/phase15-s4-100k.json`
  (title: feat(eval): add harness-only 15-03-03 100k scale stubs)
  from exact head `9427b497f319f8c82a79ed4f080e7644fdfc9f77`; all
  required exact-head Unit+drift checks passed in run `35466916029`;
  merge `5c6cf6dd3ed9e61d3f932e0d02fa69256e756599` at
  `2026-09-19T20:41:16Z`.
  Prior tip was `7789649d1f40d3b047d4edfec93c56c3edb0a6d2` (PR #171).
  Post-main tip Unit+drift will FAIL solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #169 is absent from this lease-map (baseline
  `main@d181666b`); this receipt repairs that bookkeeping
  like prior Exact-1 receipts. Exclusive File Set (Exact 4):
  `eval/scale/bench_100k.py`,
  `tests/test_scale_100k.py`,
  `tests/test_postgres_perf_lanes.py`,
  `eval/scale/reports/phase15-s4-100k.json`.
  Purpose: P15-S4/15-03-03 harness-only 100k scale stubs (no CAP-006
  measured claim); docs-only privacy for THIS receipt PR is Exact-1
  lease-map only (the recorded #169 was code). This receipt does not
  invent M16; the M14 freeze is unchanged. This receipt changes no
  benchmark result or admission state, admits no successor source
  node, and does not recompute the canonical baseline (baseline stays
  `main@d181666b`).
- PR #172: ordinary documentation receipt recording the merged PR #169
  lease-map lapse. It is **MERGED** at tip
  `041bfd25ccea9abaacc34e5198b56ef13f4e81bd`. It was **OPEN/READY** at
  the `2026-09-19T20:50:00Z` capture and adds only the PR #169
  merged-baseline bullet, the #171 MERGED mark, and this structured
  self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #172 changes no benchmark result or admission state and does not
  recompute the canonical baseline. Delivery is MERGED at tip
  `041bfd25ccea9abaacc34e5198b56ef13f4e81bd`.
- PR #168: Exact 3 P15-S4/15-03-02 provider bake-off
  `eval/provider_bakeoff/run.py`,
  `eval/tests/test_provider_bakeoff.py`,
  `eval/provider_bakeoff/reports/phase15-s4-provider.json`
  (title: feat(eval): freeze CAP-006 provider bake-off decision ABI
  (15-03-02))
  from exact head `dd0f44ab668b22e56a8e4ddc0d3cd471c93b88fa`; all
  required exact-head Unit+drift checks passed in run `35469947839`;
  merge `8f3781a1ac24c85b1c155e2f1bd259da38eb1e3f` at
  `2026-09-19T21:44:41Z`.
  Prior tip was `041bfd25ccea9abaacc34e5198b56ef13f4e81bd` (PR #172).
  Post-main tip Unit+drift will FAIL on CI `35471317284`
  solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #168 is absent from this lease-map (baseline
  `main@d181666b`); this receipt repairs that bookkeeping
  like prior Exact-1 receipts. Exclusive File Set (Exact 3):
  `eval/provider_bakeoff/run.py`,
  `eval/tests/test_provider_bakeoff.py`,
  `eval/provider_bakeoff/reports/phase15-s4-provider.json`.
  Purpose: P15-S4/15-03-02 provider bake-off CAP-006 freeze (no claimed
  P95); docs-only privacy for THIS receipt PR is Exact-1
  lease-map only (the recorded #168 was code). This receipt does not
  invent M16; the M14 freeze is unchanged. This receipt changes no
  benchmark result or admission state, admits no successor source
  node, and does not recompute the canonical baseline (baseline stays
  `main@d181666b`).
- PR #173: ordinary documentation receipt recording the merged PR #168
  lease-map lapse. It is **MERGED** at tip
  `625f01ff10fe58e84bd081be19ea4fdc5a36e7ce`. It was **OPEN/READY** at
  the `2026-09-19T21:50:00Z` capture and adds only the PR #168
  merged-baseline bullet, the #172 MERGED mark, and this structured
  self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #173 changes no benchmark result or admission state and does not
  recompute the canonical baseline. Delivery is MERGED at tip
  `625f01ff10fe58e84bd081be19ea4fdc5a36e7ce`.
- PR #174: Exact 5 P15-S4/15-03-04 CAP-011 compact 8GB acceptance
  harness
  `eval/compact_answering/acceptance.py`,
  `tests/test_compact_answering_acceptance.py`,
  `.planning/runbooks/COMPACT-MODEL-8GB-ACCEPTANCE.md`,
  `eval/compact_answering/reports/phase15-s4-8gb-windows.json`,
  `eval/compact_answering/reports/phase15-s4-8gb-linux.json`
  (title: feat(eval): Exact 5 CAP-011 compact 8GB acceptance harness
  (15-03-04))
  from exact head `20eeea3b333f74e0dad3ffbff89ebbdceeabc85f`; all
  required exact-head Unit+drift checks passed in run `35474061398`;
  merge `21642c7c88d0b69c1c05ace45e58e0b9aa7786db` at
  `2026-09-19T23:06:23Z`.
  Prior tip was `625f01ff10fe58e84bd081be19ea4fdc5a36e7ce` (PR #173).
  Post-main tip Unit+drift will FAIL on CI `35475178719`
  solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #174 is absent from this lease-map (baseline
  `main@d181666b`); this receipt repairs that bookkeeping
  like prior Exact-1 receipts. Exclusive File Set (Exact 5):
  `eval/compact_answering/acceptance.py`,
  `tests/test_compact_answering_acceptance.py`,
  `.planning/runbooks/COMPACT-MODEL-8GB-ACCEPTANCE.md`,
  `eval/compact_answering/reports/phase15-s4-8gb-windows.json`,
  `eval/compact_answering/reports/phase15-s4-8gb-linux.json`.
  Purpose: P15-S4/15-03-04 CAP-011 compact 8GB acceptance harness
  (stub receipts do NOT close CAP-011; physical dual-host later);
  docs-only privacy for THIS receipt PR is Exact-1
  lease-map only (the recorded #174 was code). This receipt does not
  invent M16; the M14 freeze is unchanged. This receipt changes no
  benchmark result or admission state, admits no successor source
  node, and does not recompute the canonical baseline (baseline stays
  `main@d181666b`).
- PR #175: ordinary documentation receipt recording the merged PR #174
  lease-map lapse. It is **MERGED** at tip
  `e04263af9445239d8c3fbca4ab294dc85000ba35`. It was **OPEN/READY** at
  the `2026-09-19T23:12:00Z` capture and adds only the PR #174
  merged-baseline bullet, the #173 MERGED mark, and this structured
  self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #175 changes no benchmark result or admission state and does not
  recompute the canonical baseline. Delivery is MERGED at tip
  `e04263af9445239d8c3fbca4ab294dc85000ba35`.
- PR #176: Exact 4 residual RAPTOR/global-sensemaking harden post-#155
  SPLIT
  `src/mnemosyne/retrieval.py`,
  `src/mnemosyne/pipeline.py`,
  `tests/test_global_sensemaking.py`,
  `tests/test_postgres_engine_live.py`
  (title: feat(retrieval): Exact residual RAPTOR/global-sensemaking
  harden (post-#155 SPLIT))
  from exact head `9502948fca1de93c61421b0215971d63bfa58883`; all
  required exact-head Unit+drift checks passed in run `35476826176`;
  merge `4d1ff09868175493837e2c6ff8484f0e6ac44811` at
  `2026-09-20T00:12:33Z`.
  Prior tip was `e04263af9445239d8c3fbca4ab294dc85000ba35` (PR #175).
  Post-main tip Unit+drift will FAIL on CI `35478157511`
  solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #176 is absent from this lease-map (baseline
  `main@d181666b`); this receipt repairs that bookkeeping
  like prior Exact-1 receipts. Exclusive File Set (Exact 4):
  `src/mnemosyne/retrieval.py`,
  `src/mnemosyne/pipeline.py`,
  `tests/test_global_sensemaking.py`,
  `tests/test_postgres_engine_live.py`.
  Purpose: Exact residual RAPTOR/global-sensemaking harden post-#155
  SPLIT (3-way reconcile from closed #155 `e16b92d0`; NOT historical
  Exact 8 #164); docs-only privacy for THIS receipt PR is Exact-1
  lease-map only (the recorded #176 was code). This receipt does not
  invent M16; the M14 freeze is unchanged. This receipt changes no
  benchmark result or admission state, admits no successor source
  node, and does not recompute the canonical baseline (baseline stays
  `main@d181666b`).
- PR #178: ordinary documentation receipt recording the merged PR #176
  lease-map lapse (Exact-1 lease-map receipt for product #176 residual
  RAPTOR harden @ `9502948fca1de93c61421b0215971d63bfa58883`). It is
  **MERGED** at tip `5fe064d4a090d8a62f8cfb7bb93e494e09c0cf2d` from
  Exact HEAD `a3ddda39ff998e18ba3d897734777a82fe9259a8`. It was
  **OPEN/READY** at the `2026-09-20T00:14:48Z` capture and adds only
  the PR #176 merged-baseline bullet, the #175 MERGED mark, and this
  structured self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  Post-main tip Unit+drift FAIL on CI `35479642827` /
  job `105995001280` solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #178 is absent from this lease-map (baseline
  `main@d181666b`); this receipt repairs that bookkeeping
  like prior Exact-1 receipts. PR #178 changes no benchmark result
  or admission state and does not recompute the canonical baseline
  (baseline stays `main@d181666b`). Delivery is MERGED at tip
  `5fe064d4a090d8a62f8cfb7bb93e494e09c0cf2d`.
- PR #179: ordinary documentation receipt recording the merged PR #178
  lease-map lapse. It is **MERGED** at tip
  `b17cd5eda8db34e345074ebbc681c93f85368238` from Exact HEAD
  `71e7eeef1db990401937e60a635bb57c228213a1`. It was **OPEN/READY**
  at the `2026-09-20T01:16:00Z` capture and adds only the PR #178
  merged-baseline bullet and this structured self-record in this
  map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #179 changes no benchmark result or admission state and does
  not recompute the canonical baseline. Delivery is MERGED at tip
  `b17cd5eda8db34e345074ebbc681c93f85368238`.
- PR #177: Exact 1 P15-S4/15-03-05 performance-scale report
  `eval/reports/phase-15-s4-performance-scale.md`
  (title: docs(eval): Exact 1 P15-S4 performance-scale report
  (15-03-05))
  from exact head `ce4c86ee808038efe88d41a74045556a0efb357f`; all
  required exact-head Unit+drift checks passed in run `35482333874`;
  merge `315c7770b10364e1e4afc06fcb6313c1e52050f9` at
  `2026-09-20T02:15:39Z`.
  Prior tip was `b17cd5eda8db34e345074ebbc681c93f85368238` (PR #179).
  Post-main tip Unit+drift will FAIL on CI `35483526085`
  solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #177 is absent from this lease-map (baseline
  `main@d181666b`); this receipt repairs that bookkeeping
  like prior Exact-1 receipts. Exclusive File Set (Exact 1):
  `eval/reports/phase-15-s4-performance-scale.md`.
  Purpose: P15-S4/15-03-05 performance-scale report (CAP-006 OPEN;
  CAP-011 harness-ready-blocked; no asserted P95); docs-only privacy
  for THIS receipt PR is Exact-1 lease-map only (the recorded #177
  was docs). This receipt does not invent M16; the M14 freeze is
  unchanged. This receipt changes no benchmark result or admission
  state, admits no successor source node, and does not recompute
  the canonical baseline (baseline stays `main@d181666b`).
- PR #180: ordinary documentation receipt recording the merged PR #177
  lease-map lapse (Exact-1 lease-map receipt for product #177
  P15-S4/15-03-05 performance-scale report @
  `ce4c86ee808038efe88d41a74045556a0efb357f`). It is **MERGED** at tip
  `3f2fc35ec05187ccac44154879307e59b7598b44` from Exact HEAD
  `913728daacd7357a48f8d3c841302af64222372d`. It was **OPEN/READY**
  at the `2026-09-20T02:18:16Z` capture and adds only the PR #177
  merged-baseline bullet, the #179 MERGED mark, and this structured
  self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #180 changes no benchmark result or admission state and does
  not recompute the canonical baseline. Delivery is MERGED at tip
  `3f2fc35ec05187ccac44154879307e59b7598b44`.
- PR #181: Exact 3 P15-S5/15-04-01 activation-memory contract
  `research/activation-memory/contract.py`,
  `research/activation-memory/fixtures/development.json`,
  `tests/test_activation_memory_contract.py`
  (title: feat(research): Exact 3 activation-memory contract
  (15-04-01))
  from exact head `9ac7077b93d7f20e2889bca8773198179c4478db`; all
  required exact-head Unit+drift checks passed in run `35484900818`;
  merge `15467fe0ba09b556c2ac410fd3edbd2e06ef7b8c` at
  `2026-09-20T03:15:43Z`.
  Prior tip was `3f2fc35ec05187ccac44154879307e59b7598b44` (PR #180).
  Post-main tip Unit+drift will FAIL on CI `35486118444`
  solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #181 is absent from this lease-map (baseline
  `main@d181666b`); this receipt repairs that bookkeeping
  like prior Exact-1 receipts. Exclusive File Set (Exact 3):
  `research/activation-memory/contract.py`,
  `research/activation-memory/fixtures/development.json`,
  `tests/test_activation_memory_contract.py`.
  Purpose: P15-S5/15-04-01 activation-memory contract
  (development-only observations; no product write/model-import);
  docs-only privacy for THIS receipt PR is Exact-1 lease-map only
  (the recorded #181 was code). This receipt does not invent M16;
  the M14 freeze is unchanged. This receipt changes no benchmark
  result or admission state, admits no successor source node, and
  does not recompute the canonical baseline (baseline stays
  `main@d181666b`).
- PR #182: ordinary documentation receipt recording the merged PR #181
  lease-map lapse (Exact-1 lease-map receipt for product #181
  P15-S5/15-04-01 activation-memory contract @
  `9ac7077b93d7f20e2889bca8773198179c4478db`). It is **MERGED** at tip
  `d8a3e4d3802a369e005c1d4d093b8cc99c4b226d` from Exact HEAD
  `c877c95b596c1a077a445f66db71b62765559025`. It was **OPEN/READY**
  at the `2026-09-20T03:18:00Z` capture and adds only the PR #181
  merged-baseline bullet, the #180 MERGED mark, and this structured
  self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #182 changes no benchmark result or admission state and does
  not recompute the canonical baseline. Delivery is MERGED at tip
  `d8a3e4d3802a369e005c1d4d093b8cc99c4b226d`.
- PR #183: Exact 3 P15-S5/15-04-02 CAP-009 cartridge A/B harness
  `eval/benches/bench_cartridge_ab.py`,
  `eval/benches/reports/phase15-s5-cartridge.json`,
  `tests/test_cartridge_ab.py`
  (title: feat(eval): Exact 3 P15-S5/15-04-02 CAP-009 cartridge
  A/B harness)
  from exact head `6ca7c11540f7af343cc4aa4e82dda54c808e76f0`; all
  required exact-head Unit+drift checks passed in run `35488845280`;
  merge `5c53a11447a0d14f5782c9016a8b9b099c5dab90` at
  `2026-09-20T04:50:52Z`.
  Prior tip was `d8a3e4d3802a369e005c1d4d093b8cc99c4b226d` (PR #182).
  Post-main tip Unit+drift will FAIL on CI `35490166255`
  solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #183 is absent from this lease-map (baseline
  `main@d181666b`); this receipt repairs that bookkeeping
  like prior Exact-1 receipts. Exclusive File Set (Exact 3):
  `eval/benches/bench_cartridge_ab.py`,
  `eval/benches/reports/phase15-s5-cartridge.json`,
  `tests/test_cartridge_ab.py`.
  Purpose: P15-S5/15-04-02 CAP-009 cartridge A/B harness
  (research-only bounded decision; no product adoption/speedup);
  docs-only privacy for THIS receipt PR is Exact-1 lease-map only
  (the recorded #183 was code). This receipt does not invent M16;
  the M14 freeze is unchanged. This receipt changes no benchmark
  result or admission state, admits no successor source node, and
  does not recompute the canonical baseline (baseline stays
  `main@d181666b`).
- PR #184: ordinary documentation receipt recording the merged PR #183
  lease-map lapse (Exact-1 lease-map receipt for product #183
  P15-S5/15-04-02 CAP-009 cartridge A/B harness @
  `6ca7c11540f7af343cc4aa4e82dda54c808e76f0`). It is **MERGED** at tip
  `3d3a71e66d88284cc7235bfa915fa7ead24c56a9` from Exact HEAD
  `a2196f9b4a3ebc72d4410e1d3dc92fdf49201073`. It was **OPEN/READY**
  at the `2026-09-20T04:53:00Z` capture and adds only the PR #183
  merged-baseline bullet, the #182 MERGED mark, and this structured
  self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #184 changes no benchmark result or admission state and does
  not recompute the canonical baseline. Delivery is MERGED at tip
  `3d3a71e66d88284cc7235bfa915fa7ead24c56a9`.
- PR #185: Exact 3 P15-S5/15-04-03 J-lens tripwire
  `research/activation-memory/j_lens_eval.py`,
  `research/activation-memory/reports/phase15-s5-j-lens.json`,
  `tests/test_j_lens_tripwire.py`
  (title: feat(research): Exact 3 P15-S5/15-04-03 J-lens tripwire)
  from exact head `9b7ec59652ade7678d7d442934d0a1632e47b93e`; all
  required exact-head Unit+drift checks passed in run `35492870190`;
  merge `2840a149eb538ebed713c81f2b49cc63a89f3bbd` at
  `2026-09-20T06:24:56Z`.
  Prior tip was `3d3a71e66d88284cc7235bfa915fa7ead24c56a9` (PR #184).
  Post-main tip Unit+drift will FAIL on CI `35494168611`
  solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #185 is absent from this lease-map (baseline
  `main@d181666b`); this receipt repairs that bookkeeping
  like prior Exact-1 receipts. Exclusive File Set (Exact 3):
  `research/activation-memory/j_lens_eval.py`,
  `research/activation-memory/reports/phase15-s5-j-lens.json`,
  `tests/test_j_lens_tripwire.py`.
  Purpose: P15-S5/15-04-03 J-lens tripwire
  (research-only functional tripwire; no product write/model-import);
  docs-only privacy for THIS receipt PR is Exact-1 lease-map only
  (the recorded #185 was code). This receipt does not invent M16;
  the M14 freeze is unchanged. This receipt changes no benchmark
  result or admission state, admits no successor source node, and
  does not recompute the canonical baseline (baseline stays
  `main@d181666b`).
- PR #186: ordinary documentation receipt recording the merged PR #185
  lease-map lapse (Exact-1 lease-map receipt for product #185
  P15-S5/15-04-03 J-lens tripwire @
  `9b7ec59652ade7678d7d442934d0a1632e47b93e`). It is **MERGED** at tip
  `dd65c86c9607ca74e15aeccb259842c40beb508a` from Exact HEAD
  `9805361fd5b9a048059e033a492357e259a68877`. It was **OPEN/READY**
  at the `2026-09-20T06:27:00Z` capture and adds only the PR #185
  merged-baseline bullet, the #184 MERGED mark, and this structured
  self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #186 changes no benchmark result or admission state and does
  not recompute the canonical baseline. Delivery is MERGED at tip
  `dd65c86c9607ca74e15aeccb259842c40beb508a`.
- PR #187: ordinary documentation receipt recording the merged PR #186
  lease-map lapse (Exact-1 lease-map receipt for receipt #186
  of product #185 @
  `9805361fd5b9a048059e033a492357e259a68877`). It is **MERGED** at tip
  `a7fdf0e8d7b6453aaef7f333f332c2b968f17884` from Exact HEAD
  `c05805064203cf2876da2e35c2878246ad3198e0`. It was **OPEN/READY**
  at the `2026-09-20T06:49:00Z` capture and adds only the #186 MERGED
  mark and this structured self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #187 changes no benchmark result or admission state and does
  not recompute the canonical baseline. Delivery is MERGED at tip
  `a7fdf0e8d7b6453aaef7f333f332c2b968f17884`.
- PR #188: ordinary documentation receipt recording the merged PR #187
  lease-map lapse (Exact-1 lease-map receipt for receipt #187
  of product #185 @
  `c05805064203cf2876da2e35c2878246ad3198e0`). It is **MERGED** at tip
  `85ce18f8f420be87a683a2d44519378a0e4b9c5e` from Exact HEAD
  `202e8c30beaafb0f74d657903ab0483a05e4f217`. It was **OPEN/READY**
  at the `2026-09-20T07:17:00Z` capture and adds only the #187 MERGED
  mark and this structured self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #188 changes no benchmark result or admission state and does
  not recompute the canonical baseline. Delivery is MERGED at tip
  `85ce18f8f420be87a683a2d44519378a0e4b9c5e`.
- PR #189: ordinary documentation receipt recording the merged PR #188
  lease-map lapse (Exact-1 lease-map receipt for receipt #188
  of product #185 @
  `202e8c30beaafb0f74d657903ab0483a05e4f217`). It is **MERGED** at tip
  `60d737a82b789f267475f621e7f1faadbb3d6b01` from Exact HEAD
  `785d6bd11493a2ca054f134b45a4020fac66196f`. It was **OPEN/READY**
  at the `2026-09-20T07:49:00Z` capture and adds only the #188 MERGED
  mark and this structured self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #189 changes no benchmark result or admission state and does
  not recompute the canonical baseline. Delivery is MERGED at tip
  `60d737a82b789f267475f621e7f1faadbb3d6b01`.
- PR #190: ordinary documentation receipt recording the merged PR #189
  lease-map lapse (Exact-1 lease-map receipt for receipt #189
  of product #185 @
  `785d6bd11493a2ca054f134b45a4020fac66196f`). It is **MERGED** at tip
  `2b6cbac4b9b6a969641b1d923052f65bbb709a52` from Exact HEAD
  `ae64511924fe8f1ca8e35c4640988edb09b2660d`. It was **OPEN/READY**
  at the `2026-09-20T08:21:00Z` capture and adds only the #189 MERGED
  mark and this structured self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #190 changes no benchmark result or admission state and does
  not recompute the canonical baseline. Delivery is MERGED at tip
  `2b6cbac4b9b6a969641b1d923052f65bbb709a52`.
- PR #191: ordinary documentation receipt recording the merged PR #190
  lease-map lapse (Exact-1 lease-map receipt for receipt #190
  of product #185 @
  `ae64511924fe8f1ca8e35c4640988edb09b2660d`). It is **MERGED** at tip
  `ccdb326d871421b9385954734a55dd0871e5f25d` from Exact HEAD
  `4ac86d78e44f7c7bcbf356e7cb4f708dcfdd65ad`. It was **OPEN/READY**
  at the `2026-09-20T08:48:00Z` capture and adds only the #190 MERGED
  mark and this structured self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #191 changes no benchmark result or admission state and does
  not recompute the canonical baseline. Delivery is MERGED at tip
  `ccdb326d871421b9385954734a55dd0871e5f25d`.
- PR #192: ordinary documentation receipt recording the merged PR #191
  lease-map lapse (Exact-1 lease-map receipt for receipt #191
  of product #185 @
  `4ac86d78e44f7c7bcbf356e7cb4f708dcfdd65ad`). It is **MERGED** at tip
  `f77fd73beef550565d6f595bb23872137fdee165` from Exact HEAD
  `4e4f8f79369f9df79295e43f6e4d9144648b34b5`. It was **OPEN/READY**
  at the `2026-09-20T09:20:00Z` capture and adds only the #191 MERGED
  mark and this structured self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #192 changes no benchmark result or admission state and does
  not recompute the canonical baseline. Delivery is MERGED at tip
  `f77fd73beef550565d6f595bb23872137fdee165`.
- PR #194: ordinary documentation receipt recording the merged PR #192
  lease-map lapse (Exact-1 lease-map receipt for receipt #192
  of product #185 @
  `4e4f8f79369f9df79295e43f6e4d9144648b34b5`). It is **MERGED** at tip
  `eb0d5e1ce4971c189c2a274c000b902bf1d19fb5` from Exact HEAD
  `52d4e10482930f916a397c80bbae42f3d942113f`. It was **OPEN/READY**
  at the `2026-09-20T09:53:00Z` capture and adds only the #192 MERGED
  mark and this structured self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #194 changes no benchmark result or admission state and does
  not recompute the canonical baseline. Delivery is MERGED at tip
  `eb0d5e1ce4971c189c2a274c000b902bf1d19fb5`.
- PR #193: Exact 3 P15-S5/15-04-04 persona-drift diagnostic
  `research/activation-memory/persona_drift_eval.py`,
  `research/activation-memory/reports/phase15-s5-persona-drift.json`,
  `tests/test_persona_drift_eval.py`
  (title: feat(research): Exact 3 P15-S5/15-04-04 persona-drift
  diagnostic)
  from exact head `06f54766dfa27166205ad9bd3acb7ccca957ac6b`; all
  required exact-head Unit+drift checks passed in run `35504813545`;
  merge `c7b28b41e20daeecfea8e0cfc5b3562baa3450b9` at
  `2026-09-20T10:50:24Z`.
  Prior tip was `eb0d5e1ce4971c189c2a274c000b902bf1d19fb5` (PR #194).
  Post-main tip Unit+drift will FAIL on CI `35506179082`
  solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #193 is absent from this lease-map (baseline
  `main@d181666b`); this receipt repairs that bookkeeping
  like prior Exact-1 receipts. Exclusive File Set (Exact 3):
  `research/activation-memory/persona_drift_eval.py`,
  `research/activation-memory/reports/phase15-s5-persona-drift.json`,
  `tests/test_persona_drift_eval.py`.
  Purpose: P15-S5/15-04-04 persona-drift diagnostic
  (research-only diagnostic; no product write/model-import);
  docs-only privacy for THIS receipt PR is Exact-1 lease-map only
  (the recorded #193 was code). This receipt does not invent M16;
  the M14 freeze is unchanged. This receipt changes no benchmark
  result or admission state, admits no successor source node, and
  does not recompute the canonical baseline (baseline stays
  `main@d181666b`).
- PR #195: ordinary documentation receipt recording the merged PR #193
  lease-map lapse (Exact-1 lease-map receipt for product #193
  P15-S5/15-04-04 persona-drift diagnostic @
  `06f54766dfa27166205ad9bd3acb7ccca957ac6b`; folds the #194 MERGED
  receipt and voids stale Exact-1 HEAD
  `2ad9879c82349894ae4c16ee66149a73a801f810`). It is **MERGED** at tip
  `a6673cfd03d0c801dc46a7a33d8fcb8f48e67b11` from Exact HEAD
  `77f1b6baf9f0b3f4b54a5aaf9b5127e56777bc2b`. It was **OPEN/READY**
  at the `2026-09-20T10:53:16Z` capture and adds the #193 MERGED
  mark, the #194 MERGED mark, and this structured self-record in
  this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #195 changes no benchmark result or admission state and does
  not recompute the canonical baseline. Delivery is MERGED at tip
  `a6673cfd03d0c801dc46a7a33d8fcb8f48e67b11`.
- PR #196: ordinary documentation receipt recording the merged PR #195
  lease-map lapse (Exact-1 lease-map receipt for receipt #195
  of product #193 @
  `77f1b6baf9f0b3f4b54a5aaf9b5127e56777bc2b`). It is **MERGED** at tip
  `7e77574a80e8f1e4a3969d36fc73e144b52b3d15` from Exact HEAD
  `f90672e63a9ab23fe4d44a26c7088aa98510cf01`. It was **OPEN/READY**
  at the `2026-09-20T11:25:00Z` capture and adds only the #195 MERGED
  mark and this structured self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #196 changes no benchmark result or admission state and does
  not recompute the canonical baseline. Delivery is MERGED at tip
  `7e77574a80e8f1e4a3969d36fc73e144b52b3d15`.
- PR #199: Exact 2 P15-S5/15-04-05 go/no-go closure
  `research/activation-memory/README.md`,
  `research/activation-memory/GO-NO-GO.md`
  (title: Exact 2 · 15-04-05 P15-S5 go/no-go closure)
  from exact head `bd5f27bf1d9be3aabbf3746111bb8c285b0be7e1`; all
  required exact-head Unit+drift checks passed in run `36196910526`;
  merge `a6933b51f4eceff469cfc8cd30389f3abaf12e2d` at
  `2026-09-25T22:49:37Z`.
  Prior tip was `7e77574a80e8f1e4a3969d36fc73e144b52b3d15` (PR #196).
  Post-main tip Unit+drift failed on CI `36198508216`
  solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #199 is absent from this lease-map (baseline
  `main@d181666b`); this receipt repairs that bookkeeping
  like prior Exact-1 receipts. Exclusive File Set (Exact 2):
  `research/activation-memory/README.md`,
  `research/activation-memory/GO-NO-GO.md`.
  Purpose: P15-S5/15-04-05 go/no-go closure
  (research-only closure; no product adoption, public claim, or
  write/trust/mutation authority);
  docs-only privacy for THIS receipt PR is Exact-1 lease-map only
  (the recorded #199 was research documentation). This receipt does
  not invent M16; the M14 freeze is unchanged. This receipt changes
  no benchmark result or admission state, admits no successor source
  node, and does not recompute the canonical baseline (baseline stays
  `main@d181666b`).
- PR #200: ordinary documentation receipt recording the merged PR #199
  lease-map lapse (Exact-1 lease-map receipt for product #199
  P15-S5/15-04-05 go/no-go closure @
  `bd5f27bf1d9be3aabbf3746111bb8c285b0be7e1`). It is **MERGED** at tip
  `75f98f9bf4a806906a402202e1ecb8a685089295` from Exact HEAD
  `a626f0d12a8ab143fe707b05b4fa1fcf5f76b645`. It was **OPEN/READY**
  at the `2026-09-25T23:20:09Z` capture and adds the PR #199
  merged-baseline bullet, the #196 MERGED mark, and this structured
  self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #200 changes no benchmark result or admission state and does
  not recompute the canonical baseline. Delivery is MERGED at tip
  `75f98f9bf4a806906a402202e1ecb8a685089295`.
- PR #202: Exact 15-05-01 · WMBS M06 Stage A development cell
  `eval/public/wmbs_m06.py`,
  `eval/public/fixtures/wmbs-m06-consolidation-development.json`,
  `tests/test_public_wmbs_m06.py`,
  `eval/public/README.md`,
  `docs/coordination/2026-08-03-wmbs-module-completeness-inventory.md`
  (title: Exact 15-05-01 · WMBS M06 Stage A development cell)
  from exact head `2dfa70a923b24a7e93b92ce54e365462fb72168b`; all
  required exact-head Unit+drift checks passed in run `36259034748`;
  merge `d2fa30844a1ab5a0cd1582518f3885e5a25b5002` at
  `2026-09-26T17:56:50Z`.
  Prior tip was `7dcadd21b5f65a69546e3f0adadeee5800f1a3a0` (PR #201 plan).
  Post-main tip Unit+drift failed on CI `36260812674`
  solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #202 is absent from this lease-map (baseline
  `main@d181666b`); this receipt repairs that bookkeeping
  like prior Exact-1 receipts. Plan `15-05-PLAN.md` / Exact Exclusive-3
  authorized only:
  `eval/public/wmbs_m06.py`,
  `eval/public/fixtures/wmbs-m06-consolidation-development.json`,
  `tests/test_public_wmbs_m06.py`
  (README/inventory forbidden by plan).
  Mid-cascade, after tip-aligned Unit+drift FAILURE on inventory cells
  for the Stage A artifacts, CoS authorized an expansion beyond plan
  Exclusive-3 to also lease `eval/public/README.md` and
  `docs/coordination/2026-08-03-wmbs-module-completeness-inventory.md`
  (Lease-5). That expansion is a recorded deviation; plan Exclusive-3
  otherwise unchanged; Stage B still blocked; publication closed; no
  harness/registry registration.
  Shipped paths remain the five listed above:
  `eval/public/wmbs_m06.py`,
  `eval/public/fixtures/wmbs-m06-consolidation-development.json`,
  `tests/test_public_wmbs_m06.py`,
  `eval/public/README.md`,
  `docs/coordination/2026-08-03-wmbs-module-completeness-inventory.md`.
  Purpose: WMBS M06 Stage A development cell
  (stdlib descriptive oracle + fixture + contract tests +
  inventory/README disclosure).
  docs-only privacy for THIS receipt PR is Exact-1 lease-map only
  (the recorded #202 shipped those five paths; README and inventory
  are the recorded Lease-5 deviation from plan Exclusive-3, not an
  authorized Exclusive-3 lease). This receipt
  does not invent M16; the M14 freeze is unchanged. This receipt
  changes no benchmark result or admission state, admits no successor
  source node, and does not recompute the canonical baseline
  (baseline stays `main@d181666b`).
- PR #203: ordinary documentation receipt recording the merged PR #202
  lease-map lapse (Exact-1 lease-map receipt for product #202
  Exact 15-05-01 WMBS M06 Stage A development cell @
  `2dfa70a923b24a7e93b92ce54e365462fb72168b`). It is **MERGED** at tip
  `0628b23fd9dd9ff8adfa85a8f6281d3b2061873f` from Exact HEAD
  `9999e20e1b0b3150883b2faa49f2644cb47dd6b6` (amended GO HEAD).
  Post-main CI SUCCESS run `36266686905`. It was **OPEN/READY**
  at the `2026-09-26T18:27:47Z` capture and adds the PR #202
  merged-baseline bullet, the #200 MERGED mark, and this structured
  self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #203 changes no benchmark result or admission state and does
  not recompute the canonical baseline. Delivery is MERGED at tip
  `0628b23fd9dd9ff8adfa85a8f6281d3b2061873f`.
- PR #204: docs: add 15-06 Exact plan for WMBS M06 Stage B reachability
  `.planning/phases/15-security-calibration-performance-and-scale-columns/15-06-PLAN.md`
  (title: docs: add 15-06 Exact plan for WMBS M06 Stage B reachability)
  from exact head `bf1fb8f33b8f089987700f2f76e98def9602e588`; all
  required exact-head Unit+drift checks passed in run `36357084597`;
  merge `17e044de55a4c4df4353d5cbdab0dd447d55a0c4` at
  `2026-09-27T23:29:59Z`.
  Prior tip was `0628b23fd9dd9ff8adfa85a8f6281d3b2061873f` (PR #203 Exact-1).
  Post-main tip Unit+drift failed on CI `36358892337`
  solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #204 is absent from this lease-map (baseline
  `main@d181666b`); this receipt repairs that bookkeeping
  like prior Exact-1 receipts. Exclusive File Set (Exact 1):
  `.planning/phases/15-security-calibration-performance-and-scale-columns/15-06-PLAN.md`.
  Purpose: Exact plan bar for WMBS M06 Stage B reachability (15-06).
  Docs-only plan; no product harness edit in #204.
  docs-only privacy for THIS receipt PR is Exact-1 lease-map only
  (the recorded #204 was a docs-only plan). This receipt does not
  invent M16; the M14 freeze is unchanged. This receipt changes no
  benchmark result, admission state, or publication claim, admits no
  successor source node, and does not recompute the canonical baseline
  (baseline stays `main@d181666b`).
- PR #206: ordinary documentation receipt recording the merged PR #204
  lease-map lapse (Exact-1 lease-map receipt for product #204
  15-06 Exact plan for WMBS M06 Stage B reachability @
  `bf1fb8f33b8f089987700f2f76e98def9602e588`). It is **MERGED** at tip
  `166b2a0a25a93478876b05de2682588a08476d82` from Exact HEAD
  `490a7e305d3476958aff16760011527c08d75dcd`.
  Post-main CI SUCCESS run `36362670329`. It was **OPEN/READY**
  at the `2026-09-28T00:01:02Z` capture and adds the PR #204
  merged-baseline bullet, the #203 MERGED mark, and this structured
  self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  PR #206 changes no benchmark result or admission state and does
  not recompute the canonical baseline. Delivery is MERGED at tip
  `166b2a0a25a93478876b05de2682588a08476d82`.
- PR #205: Exact 15-06-01 · WMBS M06 Stage B reachability
  (title: Exact 15-06-01: WMBS M06 Stage B reachability)
  from exact head `7bcd9ded1ffefc8864fa2512fa0d17a62a8c0ad1`; all
  required exact-head Unit+drift checks passed in run `36367066800`;
  merge `f5b113b7760fb22b16a93653e008b474e2705141` at
  `2026-09-28T02:20:21Z`.
  Prior tip was `166b2a0a25a93478876b05de2682588a08476d82` (PR #206 Exact-1).
  Post-main tip Unit+drift failed on CI `36369440257`
  solely at
  `tests/test_planning_traceability.py::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`
  because PR #205 is absent from this lease-map (baseline
  `main@d181666b`); this receipt repairs that bookkeeping
  like prior Exact-1 receipts. Exclusive File Set (Exact Exclusive-7):
  `eval/public/registry.json`,
  `eval/public/runner.py`,
  `eval/public/scoring.py`,
  `eval/public/adapters/whole_memory_reference.py`,
  `eval/public/README.md`,
  `tests/test_public_wmbs_m06.py`,
  `docs/coordination/2026-08-03-wmbs-module-completeness-inventory.md`.
  Purpose: Exact 15-06-01 WMBS M06 Stage B reachability under frozen plan
  `.planning/phases/15-security-calibration-performance-and-scale-columns/15-06-PLAN.md`.
  Suite `wmbs-m06-development` / adapter `wmbs-m06-reference` / profile
  `wmbs-m06-v1` / seam `public-cli-subprocess`; all publication flags false.
  Adapter maps ingest/retrieve → capture, assert_fact, search; does not call
  `MnemoCLI.answer`; empty `answer_text` when model-free payload has no
  string; never copies gold. Does not invent M16; M14 freeze unchanged.
  Changes no admission/publication claim beyond the leased Exact
  reachability; admits no successor source node; does not recompute the
  canonical baseline (baseline stays `main@d181666b`).
  docs-only privacy for THIS receipt PR is Exact-1 lease-map only
  (the recorded #205 shipped the Exclusive-7 product paths above).
- PR #207: ordinary documentation receipt recording the merged PR #205
  lease-map lapse (Exact-1 lease-map receipt for product #205
  Exact 15-06-01 WMBS M06 Stage B reachability @
  `7bcd9ded1ffefc8864fa2512fa0d17a62a8c0ad1`). It is **OPEN/READY**
  at the `2026-09-28T02:50:30Z` capture and adds the PR #205
  merged-baseline bullet, the #206 MERGED mark, and this structured
  self-record in this map. Exclusive File Set:
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  Because this record changes the branch head, no exact final head,
  merge SHA/time, or post-main CI is claimed here. PR #207 changes
  no benchmark result or admission state, does not recompute the
  canonical baseline, and must pass fresh exact-head review,
  security, and CI before merge.
- PR #208: owner-directed maintenance outside the GoalEx lease sweep:
  Windows MAX_PATH-safe `ParametricArtifactStore` writes, the POSIX-only
  infra-tooling suites skipped on Windows through `pytest.importorskip`,
  an optional `resource` import in the provider bake-off, and the
  `jsonschema` development dependency the scheduled Public regression job
  needs (its `--group dev` sync stopped run `36445311486` at collection).
  It is **OPEN/READY** and adds this structured self-record in this map.
  Exclusive File Set:
  `pyproject.toml`,
  `uv.lock`,
  `src/mnemosyne/parametric.py`,
  `eval/provider_bakeoff/run.py`,
  `tests/test_runtime_exclusive_lock.py`,
  `tests/test_production_evidence_preflight.py`,
  `tests/test_production_mcp_client_cert_rotator.py`,
  `tests/test_production_blackbox_probe.py`,
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  Because this record changes the branch head, no exact final head,
  merge SHA/time, or post-main CI is claimed here. PR #208 changes
  no benchmark result or admission state, does not recompute the
  canonical baseline, and must pass fresh exact-head review,
  security, and CI before merge.
- PR #209: owner-directed maintenance outside the GoalEx lease sweep:
  the MCP validation sweep across all 59 `TOOL_SPEC` tools moved from
  14 `FAIL` to `FAIL 0`/`CRASH 0` (`PASS` 219 -> 233, `INFO` 125 steady,
  59/59 tools exercised). Corrected schema/handler drift where tools
  advertised parameters no handler read, `min_trust_tier` and
  `max_trust_tier` treated as two independent filters rather than aliases
  of one range, argument coercion rejecting valid JSON-typed input, and
  handlers raising instead of returning a structured error on empty or
  absent scope. Adds the access-policy checks the scope-sensitive tools
  lacked, consistent protocol-level method errors, and `python -m
  mnemosyne` through a new `__main__.py`. Two further findings from
  driving the SDK transport with signed sessions: the SDK adapter
  validated the bound `session_identity` against the published schema
  and so refused every signed call to a `session_identity` tool (B15),
  and working memory had no kind for a turn of conversation (B16) -
  `conversation_turn` joins the kind set on all three backends, pinned
  identical by test.
  It is **OPEN/READY** and adds this structured self-record in this map.
  Exclusive File Set:
  `src/mnemosyne/mcp_tools.py`,
  `src/mnemosyne/mcp_server.py`,
  `src/mnemosyne/security.py`,
  `src/mnemosyne/cli.py`,
  `src/mnemosyne/__main__.py`,
  `src/mnemosyne/engine.py`,
  `src/mnemosyne/sqlite_engine.py`,
  `src/mnemosyne/postgres_engine.py`,
  `tests/test_mcp_validation_regressions.py`,
  `tests/test_cli_mcp_serve.py`,
  `tests/test_access_policy_enforcement.py`,
  `tests/test_cli_runtime_tools.py`,
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  Because this record changes the branch head, no exact final head,
  merge SHA/time, or post-main CI is claimed here. PR #209 changes
  no benchmark result or admission state, does not recompute the
  canonical baseline, and must pass fresh exact-head review,
  security, and CI before merge.
- PR #210: owner-directed maintenance outside the GoalEx lease sweep:
  session-aware reads for the MCP server, requested by the BurnOS
  client. `working_query` takes `limit` and `kinds`; `search` and
  `deep_search` take `session_id` - honoured only with a verified
  session identity for that session - and rank that session's live
  working items with long-term memory through the existing
  working-memory route, fusing a working item and the ledger record it
  cites into one hit; every hit's metadata says `memory_type` and
  `created_at`; `token_budget` (clamped to the policy budget) and `lean`
  give a smaller answer; `serverInfo.version` and `/healthz` report the
  build. Also the profile fixes that request asks for: a `profile_retire`
  tool (60 tools), `profile_correct` superseding the entry it corrects,
  `forget` retracting profile entries built on the erased record, and
  only inferred entries yielding to a higher-authority statement that
  merely differs. Additive: a call without the new arguments takes the
  path it always took, on all three backends.
  It is **OPEN/READY** and adds this structured self-record in this map.
  Exclusive File Set:
  `src/mnemosyne/pipeline.py`,
  `src/mnemosyne/engine.py`,
  `src/mnemosyne/sqlite_engine.py`,
  `src/mnemosyne/postgres_engine.py`,
  `src/mnemosyne/models.py`,
  `src/mnemosyne/mcp_tools.py`,
  `src/mnemosyne/mcp_server.py`,
  `src/mnemosyne/buildinfo.py`,
  `src/mnemosyne/user_model.py`,
  `tests/test_session_aware_reads.py`,
  `tests/test_shared_engine_contract.py`,
  `README.md`,
  `docs/ARCHITECTURE-OVERVIEW.md`,
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  Because this record changes the branch head, no exact final head,
  merge SHA/time, or post-main CI is claimed here. PR #210 changes
  no benchmark result or admission state, does not recompute the
  canonical baseline, and must pass fresh exact-head review,
  security, and CI before merge.
- PR #211: owner-directed maintenance outside the GoalEx lease sweep:
  one version for the package, the tag and the healthcheck. The first
  release cut on this repository is tagged `v1.0.1` while the package
  still declared `0.1.0`, so `serverInfo.version` and `/healthz`
  reported a version no release matched. `pyproject.toml` and the
  `uv.lock` entry for the local package now declare `1.0.1`,
  `buildinfo._FALLBACK_VERSION` follows it, a test pins that fallback to
  the version declared in `pyproject.toml` so the two cannot drift apart
  again, and `README.md` and `docs/ARCHITECTURE-OVERVIEW.md` name the
  same version. No runtime behaviour changes: the build string still
  comes from the installed distribution metadata plus the commit when it
  is known.
  It is **OPEN/READY** and adds this structured self-record in this map.
  Exclusive File Set:
  `pyproject.toml`,
  `uv.lock`,
  `src/mnemosyne/buildinfo.py`,
  `tests/test_session_aware_reads.py`,
  `README.md`,
  `docs/ARCHITECTURE-OVERVIEW.md`,
  `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.
  Because this record changes the branch head, no exact final head,
  merge SHA/time, or post-main CI is claimed here. PR #211 changes
  no benchmark result or admission state, does not recompute the
  canonical baseline, and must pass fresh exact-head review,
  security, and CI before merge.

The following is the historical `T10` reservation snapshot from
`2026-08-15T05:54:05Z`, retained to preserve its immutable-anchor evidence.
Current delivery receipts are appended to the affected rows:

- PR #109: Windows configured-command portability and the first native Windows
  workflow gate. Immutable non-lifecycle content anchor
  `0b07441e3641608177f9500d28a305fffdca87d6`; first refreshed topology head
  `f07d0733c8d9c9bfb5d5015c4a3ed57fa185029e`. The two trees differ only at
  `GOAL.md`, `.planning/STATE.md`, and this map. Refreshed exact-head CI run
  `31865413163` completed successfully, including every required/native job.
  Anchor scan
  `aa623d98-c231-40f3-8831-64db80ca7744` is sealed with complete coverage and
  zero findings. PR #109 nevertheless raced this amendment and is **MERGED** as
  `83444101f65c49c4d70d32bcd5a4362f2655367d` at
  `2026-08-15T05:24:36Z`; post-main run `31866875258` succeeded. Its
  implementation content and pre-merge gates matched this receipt, but the
  ordering deviation is recorded explicitly and opens no later edge.
- PR #110: shared stdlib POSIX/Windows file locking and signed-ledger migration,
  with immutable cumulative non-lifecycle content anchor
  `212af50442f3c50525d4eec7a698427ac523ebe2` and first refreshed topology head
  `e5bfea116e6c059309e9bafecbbdb807e1e195ee`. The exclusion check is clean.
  Refreshed exact-head CI run `31865422216` completed successfully, including
  every required/native job.
  Component head
  `a3b181c2a58c8f56b53ca19495d53a08d26ca15a` has sealed zero-finding security
  scan `90861fd0-f76f-4207-b1df-36e4cdec69e4`. Delivered from exact refreshed
  head `2841a73077cf8a47453d64fdc71b35c3969653e0`, exact-head CI
  `31870720134`, merge `e4121325f0ef0f75a6c2e47679882a01d0f75b39`
  at `2026-08-15T07:19:40Z`, and successful post-main CI `31871667827`.
- PR #111: bounded native-Windows process-tree containment while preserving the
  existing POSIX runner. Immutable cumulative non-lifecycle content anchor
  `4c88322843923b3afe611d0aa2eea3383e12c2e5`; first refreshed topology head
  `5d17b0044ab6fb053536c30421043c8e89961cc4`; the exclusion check is clean.
  Refreshed exact-head CI run `31865430468` completed successfully, including
  every required/native job.
  Component head `4f59e1cd6672800fc0a1f82cdd96fff714b8ab82` has sealed
  zero-finding security scan `a2660fdb-115a-4f0e-80a8-10266d48403b`.
  Delivered from exact refreshed head
  `4ac53dc2f0357cbc9cb47561b517420d19082d60`, exact-head CI
  `31872923876`, merge `ba32c2cef6851d73a5eaf1a031228c7dd891c586`
  at `2026-08-15T08:18:20Z`, and successful post-main CI `31874150626`.
- PR #112: Windows filesystem/environment/LF portability. Immutable cumulative
  non-lifecycle content anchor `1ad03788618e0c2659f367dc5babbc03924da5fc`;
  first refreshed topology head `5f79d384ec0ace10c18bbfca84b5dda153c639db`;
  the exclusion check is clean. Refreshed exact-head CI run `31865438529`
  completed successfully, including all three native-Windows jobs and every
  required job. Its
  isolated filesystem head
  `3c0a0152a3e47d4f86bdaab8fa5e91912a65f7de` has sealed zero-finding security
  scan `866900a1-641e-4278-b652-c1e4797b5979`. Cumulative exact-stack scan
  `8f92e955-a68a-4bec-817a-810a76fce21b` is sealed at the content anchor with
  complete coverage of 20 source items plus 12 workflow/test files and zero
  findings. Fresh refreshed-stack scan
  `e95df6b0-da9d-4688-a2a0-4378be4973d1` covers all 32 changed files at exact
  head `5f79d384ec0ace10c18bbfca84b5dda153c639db`, validates the contract, and
  reports zero findings. Delivered from exact refreshed head
  `72db90ae0223c560c1ac49352777d14080fd23e5`, exact-head CI
  `31875248786`, merge `661ebbed48d78a846c507cfb8ec4764e4e7e9a1e`
  at `2026-08-15T14:48:25Z`, and successful post-main CI `31890934043`.

The completed integration receipt verifies the serialized merge chain
`main@83444101` -> PR #114 `94f1afd2` -> PR #110 `e4121325` -> PR #111
`ba32c2ce` -> PR #112 `661ebbed`. Every edge preserved its immutable
non-lifecycle anchor, inherited the immediately preceding lifecycle blobs,
passed exact-head required/native CI and fresh security review, and waited for
successful post-main CI. The cumulative diff retained binary hash
`f538e11916f0621cb951f8393debb66e032abaa69c9053fb4562c9d245fc778d`;
exactly three unique Windows jobs and the five PR #112 filesystem nodes landed.
The Windows stack is delivered and no implementation writer remains open.

This map is recomputed from the new baseline `main@d181666b`, which the
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
from the resulting `main@f75b58cc` that the delivery required before any further
admission, and it records the receipt residue that could not exist inside the
commit it describes: PR #91, exact-head CI `30686224929`, merge SHA
`f75b58cc`, post-merge `main` CI `30687385118`. That recomputation was
**branch-resident only** until node `T4` delivered it as PR #92: this revision
is therefore also the recomputation from the resulting
`main@c56e65fbe9bcd9b0ae249694f563fc104a5fea03`, and it records `T4`'s own
receipt residue — PR #92, exact-head CI `30693874030`, merge SHA `c56e65fb`,
post-merge `main` CI `30694818231`. `T4` carried exactly that receipt-level
update to the three lifecycle files plus the round-38 record and the round-39
record, and nothing else; it was documentation only and admitted no source node.
PR #93 then merged independently from the `codex/goalmd-round-ends-clean` lane
at `main@7aabe560` (exact-head CI `30718912376`, post-merge CI `30719645207`).
That external merge lapsed the branch-resident carve-out. At lapse, the residue
was no longer receipt-only: it included the undelivered baseline-pinning test
contract and the r39, r40, and r41 round records. Node `T5` discharged that
bounded residue as PR #94 at `main@fe7e6adc`, with exact-head CI `30730185494`
and post-merge CI `30730918452`; it admitted no source node. Its delivery
omitted the r42 record from its own `docs/plans/` lease. `T6` discharged that
non-receipt residue together with the r43 record as PR #95 at `main@89f7ff82`,
with exact head `b05ee030`, exact-head CI `30737466988`, and post-merge CI
`30738303497`; it admitted no source node and no successor node. This
branch-resident recomputation is `T6`'s own standing-condition residue. It
admits no successor node and no source node. The plan-doc backlog is disclosed
here rather than left to accumulate silently.
That pilots-plan checkpoint is a correction, not an addition: PR #90 shipped
`docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`
without updating its earlier paragraph, so canonical `main@94c0c96a` still
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
  `78d9453f1f8e3b81c38ac886ad973ab5ca257c9b`, with successful exact-head CI
  `33933485295`; merged as `51bdf0c51a043b2bf1780da685787b05315b3b2e`
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
check used clean `origin/main@e29ea51bf1b76d6fa50958eaf0bdde4054373642`, whose
post-main CI run `33927734374` succeeded. The standing canonical baseline
above is preserved; this receipt admits no source writer.

- **P13-C: DISCHARGED.** GitHub's authenticated run and job APIs verify
  [Public regression run 30807305055](https://github.com/onfire7777/Mnemosyne/actions/runs/30807305055):
  `event=schedule`, `status=completed`, `conclusion=success`, workflow
  `.github/workflows/public-regression.yml`, head
  `2c6a63f12291eb938b2d284c938298fc035d6105`, started
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
  `2026-07-26T12:42:20Z` as `d8f131f85cbc708b2e81cca25f3fe0aed8e471b2`.
  PR #70 delivered its completion receipt at `2026-07-26T12:59:59Z` as
  `882f7fb38311188244b9cd1cda314241ef1419a2`. Both are ancestors of the
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
  `origin/main@e29ea51bf1b76d6fa50958eaf0bdde4054373642`: the result-v1 schema,
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
  `51bdf0c51a043b2bf1780da685787b05315b3b2e`; its sole changed file is the
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
| T0 | MERGED | Canonical truth PR after PR #86; consumed exact-head CI `30559003114`, merge `60b82731`, manual run `30561430522`, and post-merge CI `30561266140` | Truthful GOAL/GSD lifecycle state and this current map | `GOAL.md`; `.planning/STATE.md`; `.planning/ROADMAP.md`; `.planning/REQUIREMENTS.md`; `.planning/phases/13-external-benchmark-adapters-and-scheduled-ci/13-01-PLAN.md`; `.planning/phases/13-external-benchmark-adapters-and-scheduled-ci/13-01-SUMMARY.md`; `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`; `tests/test_planning_traceability.py`. GoalEx owner only | Complete: merged as PR #87 at `main@5b07f320` with post-merge CI `30566984814` |
| T3 | MERGED | GoalEx lifecycle delivery of the previously undelivered controller delta; consumed verified canonical `main@94c0c96a` and PR #90's post-merge receipts, delivered from a lane cut from `main@94c0c96a` | The three lifecycle files, the pilots-plan PR #90 checkpoint, and the 26 round records delivered on `main`, reducing the `GOAL.md` Authority carve-out to receipt scope | `GOAL.md`; `.planning/STATE.md`; `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`; `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`; `docs/plans/`. GoalEx owner only | Complete: merged as PR #91 at `main@f75b58cc` with exact-head CI `30686224929` and post-merge CI `30687385118`. Documentation only; it was disjoint from every public-harness, CI, and result-v2 lease and admitted no new implementation package. This map is recomputed from that `main` and the receipt block it could not contain is recorded here; that recomputation was branch-resident, so `T3`'s residual undelivered item was exactly the receipt-level lifecycle update carried by node `T4`, now `MERGED` as PR #92 |
| T4 | MERGED | Receipt-level lifecycle update discharging `T3`'s residue; consumed verified canonical `main@f75b58cc` and PR #91's post-merge receipts, delivered from a lane cut from `main@f75b58cc` | This map at `Baseline: main@f75b58cc` with `T3` as `MERGED`, the matching `GOAL.md` and `.planning/STATE.md` receipt text, the updated round-38 record (whose original text PR #91 already landed on `main`), and the round-39 record, delivered on `main`, plus the branch-resident receipt recomputation below | `GOAL.md`; `.planning/STATE.md`; `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`; `docs/plans/`. GoalEx owner only | Complete: merged as PR #92 at `main@c56e65fb` with exact-head CI `30693874030` and post-merge CI `30694818231`. Documentation only; exact-lease-disjoint from every public-harness, CI, result-v2, and evidence lease, and it admitted no source node. This map is recomputed here from that `main`, and the receipt block PR #92 could not contain is recorded above. That recomputation is `T4`'s own receipt residue, generated for the same structural reason `T3`'s was: no commit describes its own merge, so `main`'s copy of this map always lags by exactly one receipt block. That residual lag is an accepted standing condition and admits **no successor node** and **no source node**; `T4` is the last node this carve-out admits |
| T5 | MERGED | Bounded GoalEx lifecycle delivery after PR #93's independent merge lapsed the branch-resident carve-out; consumed verified canonical `main@7aabe560`, PR #93 exact-head CI `30718912376` and post-merge CI `30719645207`, and a lane cut from `main@7aabe560` | The three lifecycle files, both baseline-pinning tests, and the r39/r40/r41 round records delivered by PR #94 | `GOAL.md`; `.planning/STATE.md`; `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`; `docs/plans/`; `tests/test_planning_traceability.py`; `.github/workflows/ci.yml`. GoalEx owner with CI integration shared-owner serialization | Complete: merged as PR #94 at `main@fe7e6adc`, exact head `41e7ac3e`, exact-head CI `30730185494`, post-merge CI `30730918452`. Documentation, contract-test, and CI configuration only; it admitted no source node. Its delivery omitted the round-42 record from its own `docs/plans/` lease, the non-receipt residue discharged by `T6` |
| T6 | MERGED | Verified canonical `main@fe7e6adc` plus PR #94 exact-head CI `30730185494` and post-merge CI `30730918452`; lane cut from `main@fe7e6adc` | The three lifecycle files at `Baseline: main@fe7e6adc` with `T5` as `MERGED`, plus the r42 and r43 round records | `GOAL.md`; `.planning/STATE.md`; `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`; `docs/plans/`. GoalEx owner only | Complete: merged as PR #95 at `main@89f7ff82`, exact head `b05ee030`, exact-head CI `30737466988`, post-merge CI `30738303497`. Documentation only; it admitted no source node and no successor node. This branch-resident recomputation is `T6`'s own accepted standing-condition residue and admits no successor or source node |
| T7 | MERGED | Bounded documentation-and-tests node disclosing PR #96's development-only M02/M04/M05 evaluation oracles; consumed verified canonical `main@2c6a63f1` plus PR #97 (merge `3d0ad051`, exact-head CI `30774834604`, post-merge CI `30775783472`) and PR #98 (merge `2c6a63f1`, exact-head CI `30787319275`, post-merge CI `30788531829`) receipts | The M02/M04/M05 Stage-A development gap disclosures in `eval/public/README.md`, their pinning tests, and the three lifecycle files recomputed to `Baseline: main@2c6a63f1` | `eval/public/README.md` and `tests/test_public_wmbs_stage_a_disclosure.py` under the **Public-harness integration owner**, serialized as sole writer on `eval/public/*` for this documentation-only edit; `GOAL.md`; `.planning/STATE.md`; `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`; `docs/plans/` under the **GoalEx lifecycle owner**. Both owners are required and they land together in one serialized PR (PR-1 of round 46); no other lane touches `eval/public/*` at this baseline | Documentation and tests only. It admits **no source node**, **no Stage-B integration**, and **no successor node**: no `eval/public/registry.json` entry, adapter, runner routing, profile contract, or scoring-profile registration is authorized, no module behavior or fixture byte changes, M02/M04/M05 stay `PROPOSED` / `publishable:false` / `pbpp_headline_eligible:false`, and no progress counter moves. Stage B for all three remains blocked on the public-harness integration owner's lease. **Delivery statement:** the `eval/public/README.md` M02/M04/M05 Stage-A development-oracle gap disclosure and its pinning suite `tests/test_public_wmbs_stage_a_disclosure.py` are delivered by PR-1 of GoalEx round 46 **Merged receipts:** delivered as PR #99, merge `e5d0f6a9`, exact head `5cc1c866`, exact-head CI `30808291831`; its post-merge run `30810160121` failed the baseline lapse detector because PR #99 landed after the then-recorded baseline `main@2c6a63f1` without pre-recording itself, which PR #101 discharges by recomputing this map to `main@e5d0f6a9` |
| T8 | MERGED | Bounded GoalEx lifecycle documentation-and-tests node landing the stranded Round-0 M01-M20 completeness inventory; consumes verified canonical `main@2c6a63f1` and the same PR #97/#98 receipts `T7` consumes | The M01-M20 module completeness inventory, its line-level derivations, the drift test that pins the inventory to the tree, and the three lifecycle files recomputed to `Baseline: main@2c6a63f1` | Exactly `docs/coordination/2026-08-03-wmbs-module-completeness-inventory.md`; `docs/coordination/2026-08-03-wmbs-module-completeness-derivation.md`; `tests/test_wmbs_module_inventory.py`; `GOAL.md`; `.planning/STATE.md`; `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`; `docs/plans/`. GoalEx owner only | Documentation and tests only. It admits **no source node** and **no publication claim**: no module implementation, protocol, scorer, adapter, registry entry, fixture byte, schema, or admission state changes, and no progress counter moves. Its lease contains no public-harness source path. It **overlaps `T7`** on `GOAL.md`, `.planning/STATE.md`, this map, and `docs/plans/`, so `T7` and `T8` are not concurrent writers: they are one serialized GoalEx lifecycle writer landing as a single PR (PR-1 of round 46) **Merged receipts:** delivered as PR #99, merge `e5d0f6a9`, exact head `5cc1c866`, exact-head CI `30808291831`; its post-merge run `30810160121` failed the baseline lapse detector because PR #99 landed after the then-recorded baseline `main@2c6a63f1` without pre-recording itself, which PR #101 discharges by recomputing this map to `main@e5d0f6a9` |
| T9 | MERGED | Public-harness Stage-B M03 registry-admission node; consumed canonical `main` through PR #107 at `main@518fdb8b` | The `wmbs-m03-valid-time-development` entry in `eval/public/registry.json`, its `_ADAPTERS` and `_PROFILE_CONTRACTS` keys in `eval/public/runner.py`, its matching `allowed_profile` label in `eval/public/bundle.py` (a second, independent profile-contract table that rejects an unlabelled profile with `wrong interval-family metadata`), its `eval/public/README.md` documentation, its tests, and the derived-fact inventory update already present in this PR | Exactly `eval/public/registry.json`; `eval/public/runner.py`; `eval/public/bundle.py`; `eval/public/README.md`; `tests/test_public_whole_memory_reference.py`; `tests/test_public_wmbs_m03_registry_admission.py`; `docs/coordination/2026-08-03-wmbs-module-completeness-inventory.md`. Delivered under the public-harness integration owner's exclusive serialized lease after `T7`'s `eval/public/README.md` write; that serialization is discharged and no active writer remains on the lease | Authorizes **M03 only**. It admits no other module, changes no fixture byte, no scorer logic, and no schema, and it advances **no admission state**: M03 stays `PROPOSED` / `publishable:false` / `pbpp_headline_eligible:false`, with full bitemporal transaction-time query semantics retained as a hard deferral per `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md` line 68. Reachability fix only; it admits **no successor node** or source node. **Merged receipts:** PR #100 exact head `0a9e5bedd991409e58c4317f2fa48b78c3458c1e`; all required exact-head CI and Greptile green in run `31854371658`; merge `b84b351bcd5a0397065821f60db425ae8c85a13a` at `2026-08-15T01:12:26Z`; post-merge CI `31855873247` successful |
| T10 | MERGED | Windows portability stack from PR #109 through PR #112, with controller amendment PR #114, immutable non-lifecycle content anchors, exact lifecycle-parent equality, and three native-Windows CI jobs | Delivered configured-command portability, shared stdlib file locking, bounded native-Windows process-tree containment, and filesystem/environment/LF portability | Historical lifecycle authority: `GOAL.md`; `.planning/STATE.md`; this map. Historical implementation anchors: PR #110 `212af50442f3c50525d4eec7a698427ac523ebe2`, PR #111 `4c88322843923b3afe611d0aa2eea3383e12c2e5`, PR #112 `1ad03788618e0c2659f367dc5babbc03924da5fc`; `.github/workflows/ci.yml` remained under one integration owner | Complete: PR #114 merge `94f1afd2` and post-main CI `31869469070`; PR #110 merge `e4121325` and post-main CI `31871667827`; PR #111 merge `ba32c2ce` and post-main CI `31874150626`; PR #112 merge `661ebbed` and post-main CI `31890934043`. Exact-head required/native CI and fresh security review passed at every edge; no Windows stack writer remains open |
| T1 | COMPLETE | GitHub Wiki reconciliation; consumed verified canonical main | Current Home, status, evaluation, and development pages with no v2 claim upgrade | `wiki:Home.md`; `wiki:Roadmap-and-Status.md`; `wiki:Calibration-and-Evaluation.md`; `wiki:Development-Guide.md`. Wiki owner only | Complete: wiki commit `46c34287fe064842e72c3f52a9afad0c822b1846`; PR #88 changed no benchmark boundary, claim, or status any wiki page asserts, so it required no further wiki change |
| T2 | COMPLETE | Deduplicated knowledge refresh; consumed final canonical and wiki source | One current CBM graph and one Gbrain milestone | No product/source lease | Complete: single deduplicated refresh of 2026-07-30, Gbrain milestone `milestones/mnemosyne-pr86-pr87-wiki-canonical-delivery-2026-07-30`; the earlier refresh at `1fcf4925` was not duplicated |
| P12-E | EXTERNAL/OPERATOR BLOCKED | Phase 12 measured closure; consumes existing 12-04 source, production Postgres PPR parity, runtime readiness, grounded-reader QA, protected attempt | Frozen/held-out EM/F1 and positive graph/PPR evidence | No new code lease; operator evidence paths in Phase 12 plan 12-04 | Protected data, production/runtime, operator authorization |
| P13-C | DISCHARGED | First real weekly cron receipt; consumes merged fixed workflow, whose cron is `23 7 * * 1` (Mondays 07:23 UTC) | Retained scheduled-cadence receipt for BENCH-007 | No code lease | Real `schedule` run `30807305055` succeeded on `2c6a63f12291eb938b2d284c938298fc035d6105` on 2026-08-03; job `91665545558` and its fixed public-contract test step succeeded. Metadata and scope are retained in the P13-C discharge section; no official benchmark or publication claim |
| P13-O | EXTERNAL/PLAN BLOCKED | Official MemoryAgentBench and BEAM; consumes P12-E plus pinned upstream revisions/protocols | BENCH-006 conforming upstream evidence | No admitted lease; a future exact plan must name every source/evidence path | Rights/license, provider/model/judge disclosure, capacity, operator admission |
| SBOX | QUARANTINED | Development sandbox/external-meter candidate; consumes the common ABI and local reviewed sandbox commits | Only development-source isolation receipts until enforcement is proven | Current local source/test lease: `eval/public/sandbox.py`, `eval/public/sandbox/Dockerfile`, `tests/test_public_sandbox.py`; public-harness owner for any later shared integration | No push/PR/merge until immutable image, daemon probe, filesystem/network/write-boundary enforcement, SBOM, provenance, and resource receipts exist |
| N12 | SOURCE DELIVERED (#139) | Additive result-v2 and M20 publication-integrity dispatch; consumes result-v1, signed ledger, renderer/publisher/readiness, official/enhanced lineage, atomic attempt identities | Compatible result-v2 projections, visible safety failures, cross-version supersession | `leaderboard/schema/result-v2.schema.json`; `leaderboard/validate.py`; `leaderboard/ledger.py`; `leaderboard/render.py`; `leaderboard/publish.py`; `leaderboard/readiness.py`; `eval/provider_bakeoff/README.md`; `tests/test_leaderboard_result_contract.py`; `tests/test_leaderboard_ledger.py`; `tests/test_leaderboard_render.py`; `tests/test_leaderboard_publish.py`; result-v2 owner only | Obsolete protected reservation released by the 2026-09-05 owner confirmation; effective after this receipt lands. Assign one owner and recheck current main/exact leases before implementation; result-v1 bytes and behavior remain immutable |
| P14-B | SOURCE DELIVERED (#144) | REPRO-001 implementation; consumes N12, existing bundle/reproduce lifecycle, M15 replay, signed ledger, static renderer | Neutral reproducibility-bundle v1 schema and one clean-checkout reproduction command | Exactly `eval/public/schema/reproducibility-bundle-v1.schema.json`, `eval/public/bundle.py`, `eval/public/README.md`, `tests/test_public_reproducibility.py`; one integration owner | N12 merged, protected lease released, result-v1 golden compatibility green |
| P14-R | EVIDENCE BLOCKED | REPRO-002; consumes P14-B and a headline-eligible official result | Clean-checkout reproduction receipt | Evidence-only future lease | Official result, public bundle, custody, disclosed judge, human approval |
| P15-S2 | SOURCE DELIVERED (#160) | CAP-007/008 capability work; consumes Phase 14 and existing consolidation/queue/retrieval rails | Cadence tiers, bounded sleep consolidation, global sensemaking, surprise-gated writes | Exact `files_modified` list in `15-01-PLAN.md`; shared lifecycle files excluded | Phase 14 implementation and fresh Worktrunk lease check |
| P15-S3 | DEVELOPMENT SOURCE DELIVERED (#164) | CAP-004/005 security and calibration development evidence | Separate attack-family hard failures and calibration/abstention diagnostics | Stage A new-file lease, then serialized Stage B integration lease in `15-02-PLAN.md` | Dataset/model/judge rights and protected-suite controls remain external |
| P15-S4 | SOURCE DELIVERED; MEASUREMENTS OPEN | CAP-006/011 performance, scale, provider, and 8 GiB closure | Warm/concurrent, provider, 100k, compact-host receipts kept separate | Task-specific exact leases in `15-03-PLAN.md`; one measurement owner | Real 100k/production backfill and physical Windows/Linux 8 GiB evidence are operator/resource gated |
| P15-S5 | RESEARCH ARTIFACT DELIVERED (#199) | CAP-009/010 research closure | Cartridge A/B, reduced activation-memory diagnostics, explicit go/no-go | Task-specific exact leases in `15-04-PLAN.md`; no product write path | Model/tool/license/hardware/custody admission; research never grants authority |
| P16-L | HUMAN/EVIDENCE BLOCKED | Open leaderboard launch; consumes N12, P14-R, PBPP, custody, and accepted official evidence | Public activation only after all launch gates; optional Register B/neutral review enables only the `neutral` label | No admitted source lease | Human approval, evidence sufficiency, custody, rollback and publication gates |
| U-MODULES | SPEC UNSTABLE | Module implementation for M02, M04-M09, M11, M14, M16-M19 — **excluding** the development-only M02/M04/M05 evaluation oracles already delivered by PR #96 | No artifact authorized | No lease | Each needs an approved exact plan, protocol, scorer, license/custody, and dependency placement before code. PR #96's oracles are development-only: they authorize no module implementation, protocol, scorer admission, or publication claim, so these IDs remain SPEC UNSTABLE for module work |

## Topological waves

Only dependency-ready and exact-lease-disjoint nodes may share a wave.

```text
Prior delivery wave (complete)
  T0 PR #87 canonical truth            [merged main@5b07f320]
    -> T1 GitHub Wiki reconciliation   [wiki 46c34287]
      -> T2 one deduplicated CBM/Gbrain refresh [done 2026-07-30]
  PR #88 documentation/contract-test hardening merged at main@a6a92ac9
  and admitted no new implementation package.
  PR #89 recomputed this map and STATE at main@064cb4fe
  and admitted no new implementation package.
  PR #90 landed the stranded M12/M13 development gap disclosures, their
  pinning tests, and a cert-rotator lock-timeout flake fix at main@94c0c96a
  and admitted no new implementation package.
  T3 GoalEx lifecycle backlog delivery merged as PR #91 at main@f75b58cc
  and admitted no new implementation package.
  T4 receipt-level lifecycle update merged as PR #92 at main@c56e65fb
  and admitted no new implementation package.
  PR #93 independently merged at main@7aabe560 (the merge that lapsed the branch-resident carve-out), lapsing the
  branch-resident carve-out.
  T5 lifecycle delivery merged as PR #94 at main@fe7e6adc
  and admitted no source node.
  T6 lifecycle delivery merged as PR #95 at main@89f7ff82
  and admitted no source node or successor node. Its branch-resident
  recomputation is T6's own accepted standing-condition residue.

Current delivery wave
  Through PR #96 this wave's recorded status was: No GoalEx lifecycle or source
  node is admitted. PR #96 independently merged
  development-only M02/M04/M05 evaluation oracles; no writer for them remains
  active, and their publication eligibility is unchanged. PR #99 then delivered
  T7 and T8 (merge e5d0f6a9, exact head 5cc1c866, exact-head CI 30808291831):
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
    0a9e5bedd991409e58c4317f2fa48b78c3458c1e passed all required exact-head CI
    and Greptile in run 31854371658; merge
    b84b351bcd5a0397065821f60db425ae8c85a13a at 2026-08-15T01:12:26Z;
    post-merge CI 31855873247 successful.
  T7 and T8 are NOT lease-disjoint: both write GOAL.md, .planning/STATE.md,
  this map, and docs/plans/. They are one serialized GoalEx lifecycle writer
  delivered as PR #99. T7 additionally wrote eval/public/README.md and its
  pinning test under the public-harness owner. T9 overlapped T7 on
  eval/public/README.md, so it followed PR #99 strictly in sequence and was
  delivered as PR #100. That ordering and both write leases are now discharged:
  T7, T8, and T9 are all MERGED, and no writer remains admitted from this wave.

Delivered Windows portability wave (serialized; content-anchored)
  PR #113 receipt@fbbd5c0c -> PR #109@83444101 -> PR #114@94f1afd2
    -> PR #110@e4121325 -> PR #111@ba32c2ce -> PR #112@661ebbed
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
  by PR #100 at `main@b84b351b`. Their required order is discharged, and no
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

## Owner-directed documentation consolidation — PR #120

- PR #217: owner-directed batch-scale ingest fix outside the GoalEx lease sweep,
  the successor to PR #216. The promotion gate can now run once per batch of fact
  candidates on one canary branch instead of once per candidate
  (`src/mnemosyne/gate.py`, `src/mnemosyne/consolidation.py`), opt-in through
  `capture-batch --consolidation-gate-batch N` with the default `1` preserving the
  per-candidate gate exactly; a failing group is discarded and split in half down to
  single candidates, so every merge into main follows a passing gate run on the state
  it lands on. Supporting work: shared interned source lists and a compact store
  encoding (`src/mnemosyne/engine.py`, `src/mnemosyne/cid_lists.py`), the read
  predicate memoised per stored access-policy object, the exact sparse dense path
  preferred over the native kernel for hashing embeddings, indexed lesson and
  procedure stores, and opt-in reporting of gate rejections in `capture-batch`
  (`src/mnemosyne/cli.py`, `eval/public/adapters/hipporag_multihop.py`).
  `eval/harness/cli_driver.py` is deliberately byte-identical to its recorded state,
  because `eval/public/action_pressure.py` pins its SHA-256 for retained replay.
  Measured on this host: the 6119-document 2Wiki corpus (59,867 candidates)
  `capture-batch --consolidate` in **296 s and 333 s across two runs**, against a
  600 s acceptance and a baseline that never completed; all 11 golden scenarios
  IDENTICAL to legacy `737a1ef8` with and without the native kernels. It is
  **OPEN/READY** and adds this structured self-record. Exclusive File Set: the files
  named above, `tests/test_batched_promotion_gate.py`,
  `tests/test_read_decision_memo.py`, `tests/test_store_shared_values.py`,
  `tests/test_native_dispatch.py`, `tests/test_algorithms.py`,
  `tests/test_capture_batch_rejections.py` and this lease-map entry. No exact final
  head, merge SHA/time, or post-main CI is claimed here.

- PR #216: owner-directed performance fix outside the GoalEx lease sweep. The
  promotion gate's supersession-rail check now reads only the budget's active
  facts on the candidate branch instead of exporting the whole tenant once per
  candidate (`src/mnemosyne/consolidation.py`); decision-equivalence and
  rail-scaling tests are in `tests/test_consolidation_rail_read.py`. It is
  **OPEN/READY** and adds this structured self-record. Exclusive File Set: those
  two files and this lease-map entry. The 2Wiki `capture-batch --consolidate`
  acceptance (under 600 s) is NOT met by this change and is not claimed; no
  exact final head, merge SHA/time, or post-main CI is claimed here.

- PR #214: the 2026-10-04 successor repairs development bundle verification/
  replay and recurrence forwarding, adds bounded local M16 conformance, and
  reconciles source status and installation guidance. Its exact head, checks
  and integration state are tracked at
  `https://github.com/onfire7777/Mnemosyne/pull/214`. This tracking entry makes
  no pre-merge success or measured-admission claim; the original source and
  documentation ancestry is retained on the single development branch.

- PR #213: dependency lock update merged on 2026-10-04 at
  `34c521eecb12037dd611fb153e84c4aa5334fb47`, from exact reviewed head
  `c61332ba64a40e50b7739613ff09ce8d1af04941`. The only changed file was
  `uv.lock`: PyJWT 2.15.0, AnyIO 4.15.1 and typing-extensions 4.16.0.
  PR workflow `36962578172` completed with all nine applicable jobs passing;
  its nightly-only chaos job was skipped. This receipt does not claim a
  post-merge main run, advance the historical canonical baseline, or close
  any product measurement/admission gate. GitHub removed the merged
  dependency branch; the Desktop main checkout was fast-forwarded to this merge.

- PR #212: receipt repair, contributor README and AnyIO lockfile consolidation;
  MERGED on 2026-10-02 at 03:57:07 UTC, merge commit
  `f2903662e0693ab84f82bb59dfb87207bb85d666`, head
  `5ad8a0d1301e62103b71d2faa9f2e363de6e57b9`. GitHub merge metadata was
  verified on 2026-10-04. This records delivery without claiming new measured
  capability, implementation admission or historical baseline advancement.

- Source PR #198 — contributor README history consolidated into PR #212 under the
  owner's branch-reduction request; preserve current package version and
  readiness caveats. Repository navigation URLs are absolute for PyPI.
- Source PR #197 — AnyIO 4.14.2 lockfile update history consolidated into PR #212;
  dependency compatibility and combined-head CI remain required before merge.
  These consolidation records do not claim either source PR merged to main.

- PR #120: MERGED on October 2, 2026 at 00:54:50 UTC; merge commit
  `5b31e965e00b4962d943ed805c6dbfd8d7395e8e`, reviewed head
  `9b730c66eb16c1aac8c676c3231fc4a51ceec799`, exact-head CI
  `36945970613` SUCCESS. All six repaired source heads from PR #122–127
  are ancestors of this merge; GitHub marked those PRs MERGED and retired
  their branches. This is a documentation-placement receipt only, not
  implementation admission, runtime readiness or architectural approval.

On October 1, 2026 the repository owner explicitly requested repairing the
documentation review findings and consolidating plan-only branches. This is
one serialized documentation writer on canonical `main@41c375a6`, not a
successor source node or module implementation admission. PR #120 consumes
the repaired proposed documents from PR #122, PR #123, PR #124, PR #125,
PR #126 and PR #127 and updates their on-tree inventory atomically.

Exact documentation write scope:
- `GOAL.md` (reset-staging and trusted provider-preflight verification only);
- `docs/superpowers/plans/2026-08-15-goalex-full-reset.md`;
- `docs/superpowers/specs/2026-08-15-goalex-full-reset-design.md`;
- `docs/plans/wmb-m09-declared-surface-erasure-implementation-plan.md`;
- `docs/plans/wmb-m11-security-isolation-implementation-plan.md`;
- `docs/plans/wmb-m17-custody-recovery-implementation-plan.md`;
- `docs/plans/wmb-m18-interoperability-implementation-plan.md`;
- `docs/plans/wmb-m19-multimodal-memory-implementation-plan.md`;
- `docs/plans/wmb-m20-publication-integrity-implementation-plan.md`;
- `docs/coordination/2026-08-03-wmbs-module-completeness-inventory.md`;
- this lease map (this scoped record only).

Plan placement is approved for documentation organization; contract freeze,
implementation leases, G1/G2/G3 and resource/operator gates remain separately
unadmitted. Every proposed module plan remains NOT CODE-READY. No registry,
fixture, scorer, product, CI configuration, publication flag, module admission
or runtime-launch change is authorized by this consolidation. Unknown-lineage
artifact handling still requires its separate explicit architectural decision.
Required exact-head CI and review resolution precede merge; superseded plan
PRs/branches are retired only after their tips are verified contained in main.
