# P15-S5 go/no-go closure (15-04-05)

Internal research closure. One decision each for cartridge A/B, the J-lens
tripwire, and persona drift. Allowed states are `adopt`, `research-only`,
and `reject`.

This document grants no product adoption, no public claim, and no write,
trust, capability, or mutation authority. It does not change product
behavior. CAP-009 and CAP-010 in `.planning/REQUIREMENTS.md` remain
planned capability claims. A `research-only` result discharges the
promised research artifact and leaves the capability claim unsatisfied.

## Evidence head

Decisions below are relative to tip
`097bd6828c190e28261d799f4b57c4b3d038ec52` (merge of pull request #196).
That commit contains the three receipts unchanged. This closure commit
only adds `research/activation-memory/README.md` and this file. It is not
a new measurement candidate, and the receipt `candidate_sha` values are
not rewritten to this tip or to the pull-request head.

Unit + drift checks on that tip succeeded in CI run `36193689225`
(`https://github.com/onfire7777/Mnemosyne/actions/runs/36193689225`,
job `Unit + drift checks`, `headSha`
`097bd6828c190e28261d799f4b57c4b3d038ec52`). That run is the tip check.
It is not an admitted cartridge or activation measurement.

Receipts were admitted on main by these merges (git history at the tip;
distinct from each receipt's recorded `candidate_sha`):

| Task | Exact head | Merge |
| --- | --- | --- |
| 15-04-01 contract | `4b4a1ba13d946e7e457762b60aa867659ee3d504` | `20277f736af103ea505f32e507c5558030ed37b4` (#181) |
| 15-04-02 cartridge | `2f6200d910847bf3e5b96007e29a084662caa042` | `3eb8c30ee721c890c5339ebbbaeae43300f36bf4` (#183) |
| 15-04-03 J-lens | `aed883d5928929dc410d55bd41e6852d71cd1f7f` | `d15d78aea6fc677517b89c87f6dbe8303c306fb9` (#185) |
| 15-04-04 persona drift | `60e5150880a9d3931c03b6eb9230b73ee254afa2` | `02b1982f2a6d8010f36a4d38031bcbe65ba5d82c` (#193) |

## Rule applied

From `.planning/phases/15-security-calibration-performance-and-scale-columns/15-04-PLAN.md` task `15-04-05`:

- Missing or failed license, custody, safety, retention, mutation, or
  resource evidence selects `reject` for that path.
- After those hard gates pass, insufficient or inconclusive model or
  hardware evidence selects `research-only`.
- `adopt` would still require a separate product implementation plan.
  No path here meets `adopt`. No numeric threshold was invented.
  `approved_numeric_threshold` is null on every activation receipt, and
  the cartridge receipt records `numeric_threshold_invented: false`.

## Cartridge A/B (CAP-009)

**Decision: `research-only`**

Receipt: `eval/benches/reports/phase15-s5-cartridge.json`

- `schema`: `mnemosyne.cap009.cartridge-receipt/v1`
- `receipt_class`: `synthetic-development`
- `claim_status`: `synthetic-development-receipt-only`
- `official_claim`: false
- `admitted_measurement`: false
- `product_adoption`: false
- `speedup_asserted`: false
- `cap_go_no_go`: `15-04-05`
- Receipt-local `decision.decision`: `research-only`
- `decision.reasons`: `[]`
- `decision.blockers`: `admitted_measurement_missing`,
  `approved_numeric_threshold_absent`
- `decision.cap_go_no_go_owner`: `15-04-05`
- `decision.numeric_threshold_invented`: false

Identity, as recorded:

- `identity.repository_sha`: `d3cd013fe07540c3e561bab821e42504b15c82ce`
- `identity.candidate_sha`: `d3cd013fe07540c3e561bab821e42504b15c82ce`
- `identity.clean_tree`: false
- `identity.command`: `eval/benches/bench_cartridge_ab.py`
- `identity.arguments.workload`: `phase15-s5-cartridge-synthetic-dev-v1`
- `identity.arguments.kind`: `measured`
- `identity.arguments.admitted_measurement`: false
- `identity.host.accelerator`: `none`
- `identity.host.runtime_versions.python`: `3.12.3`
- `identity.digests.dataset` / `s4_identical_work`:
  `sha256:4f2d76f5311f88cfcec90522626dc39277fe7837f31823b2b26aa32ac2c953fc`
- `identity.digests.model`:
  `sha256:fa2a61a0a5796f20075d54c597ee79e7d86f148848dd132d1b35437105e07d01`
- `identity.digests.s4_retrieval_baselines`:
  `sha256:ed3a972190fe65bee129e8ebd82d1df64866a0dd6a23c873e56218780aad6b01`
- `identity.digests.s4_provider_receipt`:
  `sha256:d3725a935e5a1d7cb4fbcfaba21944a92609d62ab96b92e9bd9278d83feccab6`
- `identity.digests.s4_resource_receipt_identity`:
  `sha256:cf2b0f27ecaa35ba38b27db9484e13a541207882e399f0f2c19bd40c9563a604`
- `identity.digests.hardware_receipt`:
  `sha256:a94b4ebd240cd84e7d1dd80b97e20d798d0aea01f13839b8d3a2b42ba9448e2a`
- `identity.s4_binding.identical_work_abi`:
  `eval.provider_bakeoff.run:pinned_identical_workload`
- `raw_artifacts.observations_sha256`:
  `sha256:90d8e365be9cc2709021b5043d904c7d0f1a961899f1719a3286a3c92969773d`
- `raw_artifacts.workload_sha256`:
  `sha256:cc8c513b12ac29cb7acf84b0bcc3769ffbb60f10f03fd1231341f639724baca4`
- `raw_artifacts.result_digest`:
  `sha256:4f13f9ee60d42f0270e5587543d3b0215fd45dfebee171c0e6050d3d3a67ef18`
- `arms.cartridge.artifact_digest`:
  `sha256:18f8edcccbfd698fb1ea82817987e16605c3884102948bb25c0d9c44e247842f`
- `workload.tenant_digest`:
  `sha256:7893e78b82bb8f1d70513f209b1d35f08101acf945382e388db8215ecee9a1b7`

`d3cd013fe07540c3e561bab821e42504b15c82ce` resolves in this repository as
the merge of pull request #182. It is the receipt's recorded candidate,
with `clean_tree: false`. It is not replaced by the later #183 merge
`3eb8c30ee721c890c5339ebbbaeae43300f36bf4`.

### Hard-gate status

- **License: pass (no unlicensed artifact recorded).** The receipt has no
  SPDX `license` field. It also records no admitted external model
  (`admitted_measurement: false`, `claim_status:
  synthetic-development-receipt-only`, `official_claim: false`,
  `identity.host.accelerator: none`). `custody.consent` is
  `authored-from-scratch`. `decision.reasons` is empty. The model digest
  above is present and is not paired with an unlicensed-artifact finding.
- **Custody: pass.** `custody.redacted: true`, `custody.class:
  synthetic-development`, `custody.scan.raw_content: pass`,
  `custody.scan.secrets: pass`, `comparison.redaction_passed: true`.
- **Safety: pass.** `comparison.cross_tenant_reuse: false`,
  `comparison.identical_work: true`, `comparison.answer_equality: true`,
  `comparison.abstention_equality: true`,
  `comparison.citation_equality: true`,
  `comparison.retrieval_quality_match: true`. No quality-regression reason
  is recorded.
- **Retention: pass.** `custody.raw_content_omitted: true`,
  `custody.secrets_omitted: true`, `custody.tenant_identifiers_omitted:
  true`, `comparison.raw_secret_persistence: false`. Cases are
  pseudonymous `sha256` ids. Raw artifacts are digests only.
- **Mutation: pass (no activation-directed mutation recorded).**
  `product_adoption: false`, `speedup_asserted: false`,
  `sut_boundary.databases: []`, `sut_boundary.background_workers: []`,
  `decision.reasons: []`. This document adds no mutation authority. The
  schema has no `effects` object; that absence is a limitation, and the
  receipt does not record a mutation.
- **Resource: pass.** `comparison.resource_accounting_complete: true`,
  `comparison.setup_cost_accounted: true`,
  `resources.peak_ram_bytes: 38285312`, `resources.peak_vram_bytes: 0`,
  `resources.disk_bytes: 0`, `resources.network_bytes: 0`,
  `denominators.issued: 18`, `denominators.successes: 18`,
  `denominators.timeouts: 0`, `denominators.errors: 0`.

Hard gates are recorded and not failed. Model and hardware evidence is
inconclusive: `admitted_measurement` is false, the approved numeric
threshold is absent, and `identity.clean_tree` is false. That selects
`research-only`. The synthetic warm-latency aggregates in the receipt are
not a speedup claim (`speedup_asserted: false`).

### Limitations

Synthetic-development receipt only. One repetition. `clean_tree` is false.
The recorded candidate is an ancestor tip from before the harness merge.
No approved numeric threshold exists in the receipt.

### External blockers

No admitted measurement and no operator-admitted hardware run. No
preregistered numeric adopt threshold. S4 binding digests are recorded;
they do not admit this run.

### Successor required

A later research plan, before any product plan, must:

1. Measure on a clean tree whose `candidate_sha` is the measured commit.
2. Set `admitted_measurement` true only under the one-process,
   one-host-workload gate, with resources and custody filled as on this
   receipt.
3. Preregister any numeric threshold before the run. Do not invent one
   from these aggregates.
4. If a real model or third-party artifact enters the boundary, record
   its license in the receipt. A missing license on that artifact is
   `reject`.
5. Keep `product_adoption` false until a separate implementation plan
   exists. This closure does not open that plan.

## J-lens tripwire (CAP-010)

**Decision: `research-only`**

Receipt: `research/activation-memory/reports/phase15-s5-j-lens.json`

- `schema_id`: `activation-memory-development/j-lens-tripwire/0.1`
- `observation_schema_id`: `activation-memory-development/observations/0.1`
- `receipt_class`: `synthetic-development`
- `track`: `DEVELOPMENT`
- `split_role`: `development`
- `license`: `CC0-1.0`
- `admitted_measurement`: false
- `official_claim`: false
- `publishable`: false
- `headline_eligible`: false
- `product_adoption`: false
- `product_write_path`: false
- `model_import_path`: false
- `authoritative`: false
- `non_authoritative`: true
- `inference_class`: `functional`
- `inference_kind`: `correlational`
- `cap_go_no_go`: `15-04-05`
- Receipt-local `decision.decision`: `research-only`
- `decision.reasons`: `[]`
- `decision.blockers`: `admitted_measurement_missing`,
  `approved_numeric_threshold_absent`
- `decision.numeric_threshold_invented`: false
- `does_not_infer`: `consciousness`, `intent`, `honesty`, `ground_truth`,
  `authorization`
- `abort.status`: `completed`
- `threshold.preregistered_tripwire_threshold`: `0.5`
- `threshold.approved_numeric_threshold`: null
- `threshold.immutable`: true
- `threshold.tuned_post_hoc`: false

Identity, as recorded:

- `identity.candidate_sha`: `35033f3d85d4192fcae5e8c5930cf05514c740f9`
- `identity.model_revision`: `synthetic-open-weight-dev-0`
- `identity.model_license`: `Apache-2.0`
- `identity.model_content_digest`:
  `cb632244d9ecb5b0151bd5beb0fd7d6e21082f3c317cd8544e07a38f7c737316`
- `identity.collector_license`: `Apache-2.0`
- `identity.collector_code_digest`:
  `aa282ce9f3b762734f9e4fed1112700c35de29086c021309b4befa28640315fd`
- `identity.collector_config_digest`:
  `c2c7217eb97329ff6507f12d0547114433f418e29ab1bc377ccfb62812afd050`
- `identity.tokenizer_digest`:
  `eebf7d15b63e55fe6faae53a11e74656ad85bcf610e4a201284ba6a0440f931a`
- `identity.decoding_digest`:
  `c9856e8dd467167957b9a3a6669a3a21d332272e129782a2145ed5b007cfe2af`
- `identity.prompt_corpus_digest`:
  `53f204936c1102bfefa8740b3feaafd6857dc80a1b7f4a400ff7aa678380ca1e`
- `identity.raw_artifact_digest`:
  `fac146ca7e83e660eed8f5f2aefadb5a07c2997e8388d70496979c7ea199ac19`
- `identity.hook_layer`: `layer-12-residual`
- `identity.hardware_profile`: `synthetic-dev-cpu`
- `identity.seed`: `20260920`
- `identity.sut_boundary`: `external-collector-json`

`35033f3d85d4192fcae5e8c5930cf05514c740f9` does not resolve as a commit
in this checkout (`git cat-file -t` fails at tip
`097bd6828c190e28261d799f4b57c4b3d038ec52`) and GitHub has no commit for
that SHA. The same string is `identity.candidate_sha` in
`research/activation-memory/fixtures/development.json`. It is cited as
recorded and is not replaced by merge `d15d78aea6fc677517b89c87f6dbe8303c306fb9`.

Development cases, scorer-owned: `am-dev-j-lens-benign` (content digest
`1bf0a15321ad0220545e801787cc860c1d1d6d32e2ce692be89aef5a9a0ebb6f`) and
`am-dev-j-lens-tripwire` (content digest
`e48723e2b0bade882bc69716eaa1f4c85d762f75391615d71b45322058a08b69`).
Aggregates on one model/layer row: confusion `tp 1`, `fp 0`, `tn 1`,
`fn 0`; precision `1.0`; recall `1.0`; false-positive rate `0.0`;
coverage `1.0`; `pooled_across_models_or_layers: false`. Issued `2`,
valid `2`. These counts are a two-case development fixture.

### Hard-gate status

- **License: pass.** `license: CC0-1.0`, `identity.model_license:
  Apache-2.0`, `identity.collector_license: Apache-2.0`. These bind the
  synthetic development pin `synthetic-open-weight-dev-0`, not an
  admitted upstream weight release.
- **Custody: pass.** `custody.redacted: true`, `custody.class:
  operator-external-encrypted`, `custody.consent: synthetic-development`,
  `custody.authored_from_scratch: true`,
  `custody.protected_cases_included: false`,
  `custody.upstream_bytes_included: false`,
  `custody.scan.raw_content: pass`, `custody.scan.secrets: pass`.
- **Safety: pass.** `does_not_infer` lists consciousness, intent,
  honesty, ground truth, and authorization. `authoritative: false`,
  `non_authoritative: true`, `effects.authorization_granted: false`,
  `labels_are_scorer_owned_not_ground_truth: true`.
- **Retention: pass.** Cases store `content_digest` and a finite `value`
  under `redacted: true`. `identity.raw_artifact_digest` binds the
  external artifact. Scans pass. The receipt custody object does not
  repeat the contract booleans `raw_activations_retained` and
  `raw_prompts_retained`; the committed JSON contains no raw prompt or
  hidden-state payload.
- **Mutation: pass.** `effects.memory_mutated: false`,
  `effects.trust_mutated: false`, `effects.capability_mutated: false`,
  `effects.authorization_granted: false`,
  `effects.product_write_path: false`.
- **Resource: pass.** The single row records `resources.within_limits:
  true`, observed `time_s: 0.002`, `memory_mb: 0`, `vram_mb: 0`,
  `disk_mb: 0`, `network_bytes: 0`, `cost_usd: 0`, inside the declared
  limits (`time_limit_s: 30`, `memory_limit_mb: 512`, `vram_limit_mb: 0`,
  `case_limit: 4`).

Hard gates pass. Evidence is inconclusive for product use:
`admitted_measurement` is false, `approved_numeric_threshold` is null,
hardware is `synthetic-dev-cpu`, and the candidate SHA does not resolve
to a commit. That selects `research-only`. The preregistered `0.5`
tripwire is an immutable development setting, not an approved product
gate.

### Limitations

Two synthetic development cases, one model revision, one layer. The
functional correlational label is explicit. Perfect confusion counts on
this fixture are not an external validation. `candidate_sha` is an
unresolved pin shared with the development fixture.

### External blockers

No admitted white-box model run. No approved numeric threshold. Recorded
`candidate_sha` is not a commit in `onfire7777/Mnemosyne`. Held-out,
protected, or private inputs are absent and would need a separate rights
review.

### Successor required

A later research plan must:

1. Bind `candidate_sha` to a commit that exists in this repository.
2. Run one admitted white-box measurement on a licensed, digest-pinned
   open-weight model and collector, with encrypted raw artifacts kept
   outside Git and bound by digest.
3. Preregister any approved numeric threshold before viewing outputs.
   Leave `numeric_threshold_invented` false.
4. Keep the tripwire non-authoritative: no memory, trust, capability, or
   authorization effect.
5. Treat any product use as a new implementation plan. This closure does
   not open that plan.

## Persona drift (CAP-010)

**Decision: `research-only`**

Receipt: `research/activation-memory/reports/phase15-s5-persona-drift.json`

- `schema_id`: `activation-memory-development/persona-drift-diagnostic/0.1`
- `observation_schema_id`: `activation-memory-development/observations/0.1`
- `receipt_class`: `synthetic-development`
- `track`: `DEVELOPMENT`
- `split_role`: `development`
- `license`: `CC0-1.0`
- `admitted_measurement`: false
- `official_claim`: false
- `publishable`: false
- `headline_eligible`: false
- `product_adoption`: false
- `product_write_path`: false
- `model_import_path`: false
- `authoritative`: false
- `non_authoritative`: true
- `sole_ground_truth`: false
- `inference_class`: `functional`
- `inference_kind`: `correlational`
- `cap_go_no_go`: `15-04-05`
- Receipt-local `decision.decision`: `research-only`
- `decision.reasons`: `[]`
- `decision.blockers`: `admitted_measurement_missing`,
  `approved_numeric_threshold_absent`, `model_specific_diagnostic`
- `decision.numeric_threshold_invented`: false
- `abort.status`: `completed`
- `threshold.preregistered_false_alarm_threshold`: `0.2`
- `threshold.approved_numeric_threshold`: null
- `threshold.immutable`: true
- `threshold.tuned_post_hoc`: false
- `reference.digest`:
  `110c53f423eebda2a7442eff439f7ddefece689b72d750ecde8dacc3e501c50c`
- `reference.model_specific`: true
- `reference.raw_vector_retained`: false
- `reference.hook_layer`: `layer-12-residual`
- `reference.model_revision`: `synthetic-open-weight-dev-0`

Identity matches the J-lens receipt field for field, including unresolved
`identity.candidate_sha` `35033f3d85d4192fcae5e8c5930cf05514c740f9`,
`identity.model_content_digest`
`cb632244d9ecb5b0151bd5beb0fd7d6e21082f3c317cd8544e07a38f7c737316`,
`identity.raw_artifact_digest`
`fac146ca7e83e660eed8f5f2aefadb5a07c2997e8388d70496979c7ea199ac19`,
`identity.model_license` `Apache-2.0`, `identity.collector_license`
`Apache-2.0`, `identity.hardware_profile` `synthetic-dev-cpu`,
`identity.seed` `20260920`, and `identity.sut_boundary`
`external-collector-json`. The same non-resolution applies: that SHA is
not a commit in this repository. It is not replaced by merge
`02b1982f2a6d8010f36a4d38031bcbe65ba5d82c`.

Development cases, scorer-owned: `am-dev-persona-shift` (content digest
`e716adbd2b290724fe78e1d0ea9e0e85b4e132993ccb5af35422631a9489b230`,
distance `0.33`, projection `0.67`, perturbation `perturbed`) and
`am-dev-persona-stable` (content digest
`d39983d23469f424b57598b1f19972cab661f8f3ca331a10949ccfac6bbc1ad8`,
distance `0.04`, projection `0.96`, perturbation `control`).
`aggregates.drift_delta.distance` is `0.29`. False alarms:
`count 0`, `rate 0.0`, `control_n 1`. The Wilson interval on that rate
is `low 0.0`, `high 0.793456708526107`, `n 1`, `z 1.96`.
`pooled_across_models_or_layers: false`. Issued `2`, valid `2`.

`never_used_alone_for` is true for abstention, calibration, consolidation
promotion, quarantine, and user-profile edits. Every corresponding
`effects` flag is false, including `memory_mutated`, `trust_mutated`,
`product_write_path`, `abstention_mutated`, `calibration_changed`,
`quarantine_applied`, `promotion_mutated`, and `user_profile_edited`.

### Hard-gate status

- **License: pass.** `license: CC0-1.0`, `identity.model_license:
  Apache-2.0`, `identity.collector_license: Apache-2.0`, on synthetic
  revision `synthetic-open-weight-dev-0`.
- **Custody: pass.** Same custody record as the J-lens receipt:
  `operator-external-encrypted`, `authored_from_scratch: true`,
  protected and upstream bytes excluded, raw-content and secret scans
  `pass`.
- **Safety: pass.** `sole_ground_truth: false`, `non_authoritative:
  true`, scorer-owned labels, and `never_used_alone_for` all true. The
  diagnostic is not a calibration, abstention, quarantine, or promotion
  signal.
- **Retention: pass.** `reference.raw_vector_retained: false`. Cases are
  redacted with content digests. `identity.raw_artifact_digest` is the
  external binding. Scans pass.
- **Mutation: pass.** The `effects` object listed above is entirely
  false, including memory, trust, abstention, calibration, quarantine,
  promotion, and the product write path.
- **Resource: pass.** The single row records `resources.within_limits:
  true` with the same observed zeros and declared limits as the J-lens
  row (`time_s: 0.002`, `memory_mb: 0`, `vram_mb: 0`, `cost_usd: 0`,
  `time_limit_s: 30`, `memory_limit_mb: 512`, `case_limit: 4`).

Hard gates pass. Evidence is inconclusive: `admitted_measurement` is
false, `approved_numeric_threshold` is null, the receipt blocker
`model_specific_diagnostic` is set, `reference.model_specific` is true,
and the false-alarm interval on one control spans most of the unit
interval. That selects `research-only`.

### Limitations

Two synthetic cases, one model, one layer. The false-alarm rate of `0.0`
has a Wilson high of about `0.79` at `n = 1`. Persona vectors stay
model-specific. The candidate SHA does not resolve to a commit.

### External blockers

No admitted white-box run. No approved numeric threshold. Unresolved
`candidate_sha`. No held-out split.

### Successor required

A later research plan must:

1. Bind `candidate_sha` to a commit that exists in this repository.
2. Admit one licensed, digest-pinned white-box run per model and layer,
   without pooling those rows, and keep raw vectors off Git
   (`raw_vector_retained: false`) under encrypted external custody.
3. Preregister any approved false-alarm threshold before viewing outputs.
   The development value `0.2` is not that approval
   (`approved_numeric_threshold` is null).
4. Keep the diagnostic from being the sole input to calibration,
   abstention, quarantine, user-profile edits, or consolidation promotion.
5. Treat any product use as a new implementation plan. This closure does
   not open that plan.

## Scope stop

No path is `adopt`. No path is a launch gate. RAIL-001 through RAIL-004
are untouched by this note. Shared `GOAL.md`, `.planning/ROADMAP.md`,
`.planning/REQUIREMENTS.md`, `.planning/STATE.md`, and the coordination
lease map stay with the lifecycle owner.
