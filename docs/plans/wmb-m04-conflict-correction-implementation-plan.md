# M04 — Conflict and Correction Implementation Plan

Status: `PROPOSED` planning artifact. This document authorizes no code, no
benchmark execution, no measured run, no push, no pull request, and no claim.

Authored: 2026-08-01
Verification baseline (all §3 facts recomputed here):
`origin/main@effc5e039505c09e575ca5e4aeb2b96949676366`
Integration baseline: `origin/main@2091d01c8cea22da49a50bb1f0859d8108102f29`
Lane: `codex/wmb-m04-plan`
Exact write lease for this lane:
`docs/plans/wmb-m04-conflict-correction-implementation-plan.md` (new file only).

The two baselines are interchangeable **for this plan's subject matter and for
no other purpose**: `git diff --stat effc5e03 2091d01c` touches only
`.github/workflows/ci.yml`, `GOAL.md`, `.planning/STATE.md`, the dependency
lease map, three `docs/plans/goalex-r39..r41` round records, and
`tests/test_planning_traceability.py`. No file under `eval/`, `src/`,
`tests/test_public_*`, or any fixture changed, so every digest, dispatch-table,
and quarantine finding in §3 was re-checked and still holds verbatim at
`2091d01c`. Any later drift in those trees re-opens §3.

---

## 1. Authority

| Source | Role here |
|---|---|
| `docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md` | Controlling design. §3 evidence language, §4 admission gate, §6.2/§6.4 ABI and hooks, §7.1 C05, §7.4 inherited rails, §8 "M04 — Conflict and correction", §9.5 result contract, §11 rights, §14 labels. |
| `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md` | Precedent for module shape, task structure, and delivery-checkpoint honesty. **Not** an authorization for M04: its §17-derived boundary covers only M01, M03, M10, M12, M13, M15, M20, and it states the implementation lane "may not touch M02, M04–M09, M11, M14, or M16–M19". |
| `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md` | Row `U-MODULES` (`SPEC UNSTABLE`) covers M04: "No artifact authorized / No lease / Each needs an approved exact plan, protocol, scorer, license/custody, and dependency placement before code." This document is exactly that plan; it does not itself admit a node. **The map is lapsed — see §1.2.** |
| `.planning/STATE.md`, `GOAL.md` | Lifecycle authorities. Not edited by this lane. |

### 1.2 The dependency lease map is lapsed and is not present admission authority

At the integration baseline `main@2091d01c` (PR #94, node `T5`), the committed
lease map still carries `Baseline: main@effc5e03` in its header and still shows
`T5` as `DELIVERING` with the text "This PR is the `T5` delivery". That is
PR #94's own pre-merge text: by the map's own standing rule, no commit can
describe its own merge, so `main`'s copy always lags by at least one receipt
block.

Consequences this plan accepts rather than papers over:

1. Every lease-map row cited below — `U-MODULES`, the shared-file owner table,
   the `T5` lease — is read from a revision that the map itself declares must
   be **recomputed from then-current `main` before any further admission**.
2. This plan therefore claims **no present admission authority**. It is a
   proposal for the GoalEx lifecycle owner to evaluate *after* recomputing the
   map from the `main` that PR #94 produced.
3. `T5`'s lease is broader than earlier nodes: it names `GOAL.md`,
   `.planning/STATE.md`, the lease map, `docs/plans/`,
   `tests/test_planning_traceability.py`, and `.github/workflows/ci.yml`, under
   "GoalEx owner with CI integration shared-owner serialization". Node `M04-A`
   in §5 must be re-validated against the recomputed map, not against the row
   quoted here.
4. The one fact that is *stable* across the lapse is the one this plan depends
   on: `U-MODULES` still lists M04 with "No artifact authorized / No lease" at
   `2091d01c`, unchanged from `effc5e03`. The lapse does not create an M04
   admission; it only means the surrounding rows must be re-derived.

**Authorization boundary.** Design spec §17 scopes the *pilots* plan. It does not
extend to M04. Admission of any M04 implementation node remains the GoalEx
lifecycle/integration owner's decision, recorded in the lease map, after this
plan is reviewed. Nothing below may be read as that admission.

### 1.1 Excluded by standing instruction

This plan contains no official/upstream benchmark attempt, no protected or
held-out surface, no publication or signed-publication path, no result-v2
dependency, no sandbox dependency, and no T5 path. It never proposes a
`certified`, `governed`, `neutral`, headline, superiority, or
independently-reproduced label.

---

## 2. What M04 is, restated from the controlling spec

Design spec §8 "M04 — Conflict and correction" fixes:

- **Contract:** universal `ingest`, `retrieve`, `answer`; the §6.4 `update` hook
  is optional.
- **Data:** seeded independent, duplicated, low-quality, high-quality,
  malicious, unresolved, and later-resolved conflicting sources.
- **Scorer:** correct current answer, preserved historical answer, calibrated
  unresolved state, false supersession, source-ablation sensitivity.
- **Acceptance:** 100% preservation of superseded history; at most 1% false
  high-confidence resolution; no monotonic-source-policy violation.
- **Repeat/replay:** three source-order permutations per case and at least five
  seeds.
- **Resource prerequisite:** measured admission receipt. The former L16 numbers
  are **not** an admitted profile.
- **External dependencies:** none.
- **Deferral:** reject scoring based on Mnemosyne-specific trust-tier labels;
  the gold defines only observable source reliability and expected outcome.
- **Feasibility disposition:** `PROPOSED`; branch/merge subcapabilities are
  `UNSUPPORTED-BY-SYSTEM` unless an entrant exposes a public contract.
- **Placement:** universal public comparison and internal regression.

Capability row §7.1 `C05` binds M04 to `RAIL-001` and states branch/merge is
"unsupported until a hook exists". Cross-capability row §9.6 "Correction with
evidence" (M03/M04/M05) stays `DEFERRED`: M05 is not admitted, so no joint
claim is available from a passing M04 smoke.

---

## 3. Adversarial validation of every asset this plan cites

Each row was checked against **this exact checkout at the stated baseline** for
fixture/scorer integrity, stale revision or baseline pins, pass-without-execution
paths, mutable or tamperable evidence, custody/provenance binding, failure paths,
and runtime assumptions. Verified facts are recorded with the value observed.

### 3.1 SAFE / BOUNDED — reusable under the stated bound

| Asset | Bound under which M04 may consume it | Verification performed |
|---|---|---|
| `eval/public/schema/wmbs-0.1-draft.schema.json` + the closed-ABI validator and canonical-JSON helpers in `eval/public/adapters/whole_memory_reference.py` | Contract validation only. M04 consumes the *shape* vocabulary (`RequestContext`, `IngestReceipt`, `RetrievalEnvelope`, `AnswerEnvelope`, `ErrorEnvelope`), never a conformance claim. | Schema file present and hashed into every canonical replay payload via `_canonical_replay_evidence`; error enum closed and unknown codes fail closed (§6.2). |
| `eval/public/bundle.py` `write_bundle` / `verify_bundle` and its scorer recomputation | **Development bundles only.** M04 must not assume bundle custody proves executable build provenance. | `verify_bundle` recomputes scoring and fails closed on unknown trace fields; `_canonical` is `json.dumps(sort_keys, (",",":"), allow_nan=False) + "\n"`. |
| `eval/public/wmbs_m01.py` fixture + scorer | Deterministic harness **oracle/pattern** only: pure stdlib generator, frozen bytes, pure scorer, closed field sets, canonical replay projection over a closed field list. | Registry `dataset_sha256` for `wmbs-m01-development` = `81f3d4483729989876dfce71a2aabcf4681fd4edcff6f74b228c8473f4adb462`; recomputed canonical digest of the committed fixture **matches exactly**. |
| `eval/public/wmbs_m10.py` fixture + core + scorer | Deterministic **baseline/abstention oracle** only, for the shape of a "calibrated unresolved state" metric and for disjoint calibration/scored partitioning. | Registry `dataset_sha256` for `wmbs-m10-development` = `41820cefb6e2a853a75bedb61d31b5a92045df8783544ebbbbcb18e7a77530f4`; recomputed canonical digest **matches exactly**. (The raw file bytes differ from this value by design — the pin is over canonical JSON, not raw bytes.) |
| `eval/public/adapters/whole_memory_reference.py::run_m03_valid_time_development` and `eval/public/scoring.py::_score_wmbs_m03_valid_time` | **Bounded valid-time development only.** No transaction-time semantics. M04 reuses (a) the CLI-only observation discipline, (b) the projection of `graph_as_of` down to `object` values, (c) the temp-store clean-process replay pattern. | Fixture declares `transaction_time.supported = false`; scorer returns `full_bitemporal_m03: false`; adapter observes only through `MnemoCLI`. The focused selection `pytest -q tests/test_public_whole_memory_reference.py -k "m03 or m15_composed"` was executed once in this checkout and reported no failure and no error (see §10 for the recorded scope of that observation). |
| `eval/public/adapters/working_memory_action_probe.py` (M13) | **Disclosed 1-seed / 6-case development probe only.** Cited solely as precedent for publishing an explicit gap disclosure beside a development metric. | `eval/public/README.md` carries the M13 gap disclosure pinned by `tests/test_public_working_memory_action_probe.py::test_public_readme_records_development_evidence_gaps` (delivered by PR #90 at `main@061c2e1c`). |

### 3.2 QUARANTINE — cited defects; **do not** consume as evidence, **do not** edit here

These are recorded so a future M04 implementation cannot silently inherit them.
No asset is modified by this lane. Each entry names the smallest RED regression
that a future owner (the public-harness integration owner, **not** M04) must
land before the corresponding M04 capability may claim anything beyond a pure
unit contract.

| Q | Defect | Why it invalidates naive reuse | Smallest RED regression (owner: public-harness) |
|---|---|---|---|
| Q1 | `run_m01_development` manufactures receipts from `m01.perfect_receipts(fixture)` and ignores its `_cli` argument entirely. | The "M01 pilot" trace is a harness-authored oracle replayed against itself. It proves scorer arithmetic, not that any SUT captured anything. Any M04 design that copies this shape would score itself. | A recording-CLI seam test asserting the M01 adapter issues at least one observed CLI invocation per fixture row and fails closed when the recorder observes zero calls. |
| Q2 | `run_m10_development` likewise ignores `_cli` and answers in-process from `m10.run_baseline("full-context", cases)`. | Same self-scoring hazard, plus the abstention metric describes the reference reader, not a submitted system. | A recording-CLI seam test for M10 with the same fail-closed assertion. |
| Q3 | `run_m15_composed_development` composes reference-only M01 and M10 around the one real-CLI cell (M03), asserts seven gates directly, and never invokes `score_profile` for the constituent cells. | "Composed replay" therefore does not prove one shared SUT state, and a corrupted constituent scorer would not be detected by the composition. | Three RED tests: (a) shared-state — mutating state through one cell must be visible to the next; (b) constituent-scorer corruption must fail the composition; (c) the exact M10 trace set must be asserted, not sampled. |
| Q4 | `eval/public/registry.json` M12 rows carry stale `revision` pins even though their normalized `dataset_sha256` values still verify. | A matching content hash beside a stale commit pin makes provenance look bound when the lineage claim is false. | A `git show`-based registry-revision identity test proving each row's `revision` actually contains the pinned fixture bytes; then split/repair the M12 revisions. |
| Q5 | `wmbs-m03-valid-time-development` has **no** `eval/public/registry.json` entry, no `_ADAPTERS` entry, no `_NORMALIZERS` entry and no `_PROFILE_CONTRACTS` entry in `eval/public/runner.py` — while `eval/public/bundle.py::_CANONICAL_REPLAY_SEEDS` *does* carry `"wmbs-m03-valid-time-development": (11, 23, 37, 53, 71)`. | The M03 cell is reachable only by direct adapter/scorer calls from `tests/test_public_whole_memory_reference.py`. It has no frozen dataset digest, no license row, no custody anchor, and cannot be run through `run_public_suite`. Task 3 of the pilots plan lists the suite ID with an **unchecked** box, so this is a disclosed incompleteness, not a hidden one — but it is still not a custody-bound asset. | Pin M03's exact fixture and schema: a registry row whose `dataset_sha256` equals the canonical digest of the committed fixture, plus a runner-routing test. The recomputed canonical digest today is `04c8e8a89d25c281744d57c20654bd035d85cb2f2cf96fbbd631592e4488bb91` (raw file SHA-256 `5162dbcb9228f289db8566aee85cf293eb5947d2a8acfce9e18121525f6c0823`). This plan records the value; it does not write it. |
| Q6 | `bundle.canonical_replay_fixture_custody` accepts any 64-hex string that matches `manifests.fixture_manifest_sha256`; the two values are compared to each other, not to real content. Volatile-field projections also diverge across three definitions: `bundle.CANONICAL_REPLAY_VOLATILE_FIELDS` is exactly the **seven** members `host_path`, `path`, `receipt_id`, `rss_samples_bytes`, `runtime_timestamp_utc`, `signature`, `wall_time_ms`; `whole_memory_reference.VOLATILE_FIELDS` is the five members `wall_time_ms`, `rss_samples_bytes`, `signature`, `path`, `runtime_timestamp_utc`; `wmbs_m01._CANONICAL_REPLAY_VOLATILE_FIELDS` is `("evidence_handle",)` alone. | A fabricated but self-consistent hash pair passes custody. The three sets are not nested consistently — `bundle` adds `host_path` and `receipt_id` that the adapter omits, and `wmbs_m01` shares no member with either — so "the canonical projection" is not one thing. | (a) Reject fabricated custody hashes by binding schema, fixture, generator, code, and traces to real content; (b) collapse to **one** shared volatile projection consumed by all three call sites. |

### 3.3 Assets deliberately **not** reused

| Asset | Why M04 must not consume it |
|---|---|
| `eval/datasets/belief_cases.json` + `belief-revision-check` + `src/mnemosyne/belief.py` | Its gold is expressed in Mnemosyne-internal vocabulary — operations `ADD`/`SUPERSEDE`/`CONTEST`/`NOOP`, statuses `active`/`contested`/`superseded`/`retracted`, `superseded_by` references, and numeric `confidence`. Design spec §8 M04 explicitly rejects scoring on Mnemosyne-specific labels. This asset remains a valid **internal regression** surface and M04 must not weaken, duplicate, or re-point it. |
| CLI `branch` / `merge` / `discard` and `tests/test_sqlite_branch_merge.py` | §7.1 `C05` and §8 M04 hold branch/merge `UNSUPPORTED-BY-SYSTEM` until a public §6.4 hook contract exists. Exercising the internal commands would manufacture a capability claim. |
| `leaderboard/` result-v2, signing, publication, readiness | Excluded by standing instruction and by lease-map node `N12` (`LEAD BLOCKED`). |
| `eval/public/sandbox*` | Node `SBOX` is `QUARANTINED`; no measured or isolated execution is in scope. |

### 3.4 Runtime assumptions that must be disclosed, not assumed

1. **Assertion identity is non-deterministic.** `src/mnemosyne/ids.py::new_id`
   returns `uuid.uuid4()`. `Assertion.to_dict()` therefore exposes a volatile
   `id`, a volatile `superseded_by` (an id), a `transaction_time` and
   `last_accessed` defaulted to wall clock, and a mutable `access_count`. Any
   M04 canonical projection **must** be a closed allowlist of stable fields.
   This is precisely why the M03 adapter projects only `item["object"]`.
2. **Unresolved state is observable without reading a label.**
   `MemoryTools.graph_as_of` filters to the latest `valid_from` per scope and
   returns **all** survivors. The committed M03 `tied-valid-time` timeline
   therefore yields two ordered current objects
   (`["tie-alpha-{seed}", "tie-beta-{seed}"]`). M04 can express "unresolved" as
   observable multiplicity of returned current values — architecture-neutral —
   instead of reading Mnemosyne's `contested` status. This is the single most
   important reuse finding in this plan.
3. **That ordering is proven only for the local JSON store.** The M03 evidence
   binds `MnemoCLI` over a JSON store. SQLite and PostgreSQL result ordering is
   **not** proven for this projection. M04 declares Local-JSON only; other
   backends are `DEFERRED` (M16 territory).
4. **`trust_tier` / `source_trust_tier` are authorization inputs, not
   reliability signals.** They appear on `assert`, `supersede`, `confirm`, and
   `correct`. M04 must hold them **constant** across every source so no
   Mnemosyne-specific label can discriminate an outcome, and must never place
   them in gold.
5. **`dataset_sha256` is a canonical-JSON pin, not a file pin.** It is
   `sha256(json.dumps(value, sort_keys=True, separators=(",",":"),
   allow_nan=False) + "\n")`. A future M04 registry row must be computed this
   way or it will fail closed in `run_public_suite`.

---

## 4. Exact implementation contract

### 4.1 Module identity

| Field | Frozen value |
|---|---|
| `module_id` | `M04` |
| `module_version` | `0.1.0` |
| Suite ID | `wmbs-m04-development` |
| Fixture ID | `wmbs-m04-development` |
| Fixture schema ID | `wmbs-m04-development/fixture/0.1` |
| Generator ID | `wmbs_m04.generate_fixture` |
| Generator version | `1.0.0` |
| Scoring profile ID | `wmbs-m04-v1` (Stage B only) |
| Family | `whole-memory-development` |
| `track_kind` | `DEVELOPMENT` |
| Division | `COMPONENT-CLOSED` is **not** claimed; the cell is a repository development cell. |
| `admission_state` | `PROPOSED` |
| `evidence_level` | `DESIGN_ONLY` until Stage A merges; `IMPLEMENTED` thereafter. Never `INTERNALLY_MEASURED` without a §4.1 receipt. |
| `interval_method` | `descriptive` |
| License | `CC0-1.0` (harness-generated synthetic content only) |
| `publishable` / `pbpp_headline_eligible` / `headline_eligible` / `independent_external_reproduction` / `upstream_comparable` | all `false` |

### 4.2 Prerequisites (frozen)

- **P1.** Baseline is `main@effc5e03`, or a later `main` re-verified by the same
  procedure. Any drift in `eval/public/registry.json`, `runner.py`,
  `scoring.py`, `bundle.py`, or `whole_memory_reference.py` re-opens §3.
- **P2.** Stage A (below) requires **no** shared-file edit and **no** unblocked
  quarantine.
- **P3.** Stage B requires the public-harness integration owner to have landed
  the Q1–Q6 RED order, in that order, and to hold the shared lease at the time.
- **P4.** Stage C (any measured statement) requires the full §4.1 record:
  `adapter_schema_id@sha256`, `generator_id@sha256` + golden fixtures,
  `scorer_id@sha256` + golden vectors, `baseline_manifest_id@sha256`,
  `power_plan_id@sha256`, `sandbox_profile_id@sha256`,
  `resource_receipt_id@sha256`, and the software/data BOM. None exists.
  Stage C is `DEFERRED` and is **not** planned here.

### 4.3 Consumed interfaces

| Interface | Source | Consumption rule |
|---|---|---|
| `wmbs/0.1-draft` portable event shape | spec §6.2 | Fixture rows carry `event_id`, `content`, `actor_label`, `event_time`, `ingestion_time`, `content_sha256`, `public_metadata`. `valid_from`/`valid_to` are used only where the case is a dated correction. |
| `IngestReceipt` outcome enum | spec §6.2 | `accepted` / `deduplicated` / `rejected` only. |
| `AnswerEnvelope` | spec §6.2, as enforced by `eval/public/schema/wmbs-0.1-draft.schema.json` `$defs.answer_envelope` | **M04 adopts the schema, not a module's loader.** The schema's base `required` is `abstained`, `evidence_handles`, `action_handles`, `adapter_metadata`; *both* `oneOf` branches additionally `required: ["answer_text"]`, so `answer_text` is required in every valid instance. **`confidence` is the only optional key**, and `additionalProperties` is `false`. `eval/public/wmbs_m10.py::AnswerEnvelope.from_dict` is a **relaxation** of that contract in both directions — it treats `confidence` as required and `action_handles`/`adapter_metadata` as `.get()`-defaulted — and M04 **does not inherit it**; M10's schema-facing `to_dict` is unaffected, since it rematerializes all six keys unconditionally. M04's own emission rules: `action_handles[]` is **present and empty** (M04 has no action surface); `answer_text` is **present and `null` exactly when `abstained` is `true`**, and a non-empty string exactly when it is `false`, per the `oneOf`; `evidence_handles[]` is present and may be empty; `adapter_metadata` is present and restricted to a closed key set. `confidence` is never synthesized when the SUT omits it (M10 precedent). |
| `update(selector, replacement)` §6.4 hook | spec §6.4 | Declared `emulated` for Local: emulated through the public `supersede` / `correct` commands. Every emulated call's cost counts. It is **never** declared `native`. |
| `graph_as_of(subject, predicate, valid_time)` | `MnemoCLI.graph_as_of` | Used for valid-time questions only. Projection is a closed allowlist (§4.6). |
| M01 scorer shape | `eval/public/wmbs_m01.py` | Pattern only, per §3.1. |
| M10 abstention/coverage shape | `eval/public/wmbs_m10.py` | Pattern only, per §3.1. |

### 4.4 Produced interfaces

`eval/public/wmbs_m04.py` (new, pure, stdlib-only) exports exactly:

```text
MODULE_ID, ADMISSION_STATE, FIXTURE_ID, FIXTURE_SCHEMA_ID,
GENERATOR_ID, GENERATOR_VERSION, DEFAULT_SEED, SEEDS, PERMUTATIONS,
FIXTURE_PATH, WmbsM04Error

canonical_json(value) -> bytes
canonical_sha256(value) -> str
generate_fixture(seed=DEFAULT_SEED) -> dict
validate_fixture(fixture) -> Mapping          # fail-closed, closed key sets
load_fixture(path=FIXTURE_PATH) -> dict
normalize_fixture(fixture) -> dict

score_current_answer(fixture, observations) -> dict
score_historical_preservation(fixture, observations) -> dict
score_unresolved_calibration(fixture, observations) -> dict
score_false_supersession(fixture, observations) -> dict
score_source_ablation_sensitivity(fixture, observations, ablations) -> dict
score_permutation_invariance(fixture, observations_by_permutation) -> dict
score_conflict(fixture, observations, ablations) -> dict   # aggregate
```

No adapter, no registry row, no runner entry, no scoring-profile entry is
produced by Stage A. Those are Stage B and are owned elsewhere.

### 4.5 Fixture design (deterministic, bounded, label-neutral)

Seven source classes, exactly as spec §8 M04 names them:

| Class | Construction | Expected observable outcome |
|---|---|---|
| `independent` | Two sources assert non-overlapping subject/predicate pairs. | Both current; no supersession. |
| `duplicated` | Two sources assert byte-identical content for one pair. | One current value; duplicate is `deduplicated`, never a conflict. |
| `low_quality` | A source whose corroboration count is 1 and whose later events are self-contradictory. | Never supersedes a corroborated value. |
| `high_quality` | A source corroborated by ≥ 3 independent `actor_label`s. | Current value, once its `valid_from` is latest. |
| `malicious` | A source whose content embeds instruction-shaped text and asserts a conflicting value. | Must not supersede; must not alter retrieval order. Inherits `M-POISON-BLOCK`; no new threshold is created. |
| `unresolved` | Two equally corroborated sources with equal `valid_from`. | **Multiplicity ≥ 2** in the current answer set (§3.4.2), and `abstained = true` in `normal` response mode. |
| `later_resolved` | An `unresolved` pair followed by a dated correction. | Single current value **and** the pre-correction value still recoverable at the historical `as_of`. |

Scale: 7 classes × 4 cases = **28 cases**, × **5 seeds** (`11, 23, 37, 53, 71`,
reusing the M03 seed set for cross-cell comparability) × **3 source-order
permutations** (`as_authored`, `reversed`, `interleaved`) = **420 observations**.
Bounded by construction; no unbounded corpus.

**Label neutrality is a fixture invariant, not a convention.**
`validate_fixture` fails closed if any row or gold contains `trust_tier`,
`source_trust_tier`, `status`, `superseded_by`, `contested`, `confidence`, or
any other system-internal resolution signal. Source reliability is expressed
**only** through observable structure: corroboration count, distinct
`actor_label` count, internal self-consistency, and `event_time` ordering.

The frozen fixture is committed as the exact `canonical_json()` bytes of
`generate_fixture(DEFAULT_SEED)` with `DEFAULT_SEED = 20260801`, carrying its
own `fixture_sha256` over the fixture-without-digest (M01 precedent).

### 4.6 Scorer contract

Observation projection is a **closed allowlist** over `graph_as_of` results —
exactly `object` plus the harness-supplied `as_of` — reproducing the M03
discipline and excluding every volatile field named in §3.4.1.

| Metric | Definition | Gate |
|---|---|---|
| `M04-CURRENT-ACC` | Fraction of cases whose current answer set equals gold exactly (ordered). | Reported; no floor asserted at `PROPOSED`. |
| `M04-HIST-PRESERVE` | Fraction of superseded values still retrievable at their historical `as_of`. | **`= 1.0`.** Spec acceptance: 100% preservation of superseded history. |
| `M04-FALSE-RESOLVE` | Fraction of `unresolved` observations returning a single non-abstained current value. | **`<= 0.01`.** Spec acceptance: at most 1% false high-confidence resolution. The `unresolved` class is 4 cases × 3 permutations = **12 observations per seed**, hence **60 across the five seeds**, inside the 420-observation total. The smallest non-zero rate expressible is 1/60 ≈ 0.0167, which is already above the 1% bound, so the bound is **not resolvable at this n**. It is reported as `unresolvable-at-this-n` and, at development scale, **any** non-zero count is a hard failure. Raising n to resolve 1% honestly is Stage C work behind a power plan, not a fixture-size tweak. |
| `M04-MONOTONIC` | Count of outcomes where a strictly-weaker-evidence source supersedes a strictly-stronger one. | **`= 0`.** Spec acceptance: no monotonic-source-policy violation. |
| `M04-UNRESOLVED-CAL` | Agreement between observed multiplicity/abstention and gold unresolved state. | Reported. Numeric ECE only when the SUT supplies confidence; otherwise `unsupported` (M10 precedent). |
| `M04-ABLATION-SENS` | Change in current answer when one source is withheld, versus gold sensitivity. | Reported. |
| `M04-PERM-INVARIANT` | Fraction of cases whose scored outcome is identical across all three source-order permutations. | **`= 1.0`** for every non-`unresolved` class. Deterministic tie policy applies to `unresolved`. |
| `M04-REPLAY-EQ` | Byte equality of the closed canonical projection across five seeds plus one clean-process replay. | **`= 1.0`** (M15 discipline, applied locally in Stage A). |

Inherited rails are not restated as new thresholds. `RAIL-001`,
`M-PROTECTED-REG`, `M-AUDIT-COMPLETE`, `M-POISON-BLOCK`, and `M-BENIGN-DROP`
apply unchanged; no M04 diagnostic may weaken one. Where an M04 metric and an
approved rail would conflict, §3 of the spec applies and the module goes
`DEFERRED-CONFLICT` — the agent does not pick the easier value.

### 4.7 Custody, licensing, and rights

- All content is harness-generated synthetic text: no personal data, no
  consent basis required, no takedown surface, `CC0-1.0`.
- No external dataset, no upstream benchmark name, no pinned model, no judge,
  no provider call, no network access. §11 `NOASSERTION` risk does not arise.
- Stage A adds no runtime dependency: stdlib only (`hashlib`, `json`, `random`,
  `datetime`, `pathlib`), matching `eval/public/wmbs_m01.py`. Ponytail holds —
  no new abstraction and no new dependency.
- Stage B custody, if ever admitted, must use the canonical-JSON `dataset_sha256`
  form of §3.4.5 and a `revision` pin that actually contains the fixture bytes
  (Q4).

---

## 5. Dependency edges and lease placement

Proposed lease-map node, for the GoalEx lifecycle owner to accept or reject:

| ID | Class | Consumes | Produces | Exact write lease | Integration gate |
|---|---|---|---|---|---|
| `M04-A` | **CODE-READY** (see §7) | Design spec §8 M04; M01/M10 scorer patterns; frozen `main@effc5e03` | Pure M04 fixture + scorer + focused tests; no claim | `eval/public/wmbs_m04.py`; `eval/public/fixtures/wmbs-m04-development.json`; `tests/test_public_wmbs_m04.py` — **all three new** | None. Disjoint from every current owner surface. |
| `M04-B` | **BLOCKED on Q1–Q6** | `M04-A`; the repaired common harness | Registry row, adapter, runner routing, scoring profile | Public-harness owner's existing exclusive surfaces (`registry.json`, `runner.py`, `scoring.py`, `bundle.py`, `adapters/whole_memory_reference.py`, `README.md`, `tests/test_public_whole_memory_reference.py`) | Public-harness lease; Q1–Q6 landed in order. |
| `M04-C` | **DEFERRED** | `M04-B`; sandbox; resource receipt; BOM; power plan | Any measured or admitted statement | Not named — no plan may name paths it cannot justify | `SBOX` released; §4.1 record complete; operator admission. |

**Lease disjointness, verified against the lease map's "Shared-file owners"
table.** The public-harness owner's exclusive surfaces are
`eval/public/runner.py`, `eval/public/scoring.py`, `eval/public/bundle.py`,
`eval/public/registry.json`, `eval/public/README.md`,
`eval/public/adapters/whole_memory_reference.py`,
`eval/public/schema/wmbs-0.1-draft.schema.json`,
`tests/test_public_whole_memory_reference.py`, `src/mnemosyne/cli.py`, and
`eval/harness/cli_driver.py`. None of `M04-A`'s three paths appears in that
list, in the GoalEx owner's list, in the result-v2 owner's list, in the CI
owner's list, or in the evidence owner's list. The precedent is exact:
`eval/public/wmbs_m01.py` and `tests/test_public_wmbs_m01.py` sit outside the
shared lease today for the same reason.

`M04-A` also does not touch `GOAL.md`, `.planning/STATE.md`, the lease map,
`tests/test_planning_traceability.py`, `.github/workflows/ci.yml`, any fixture,
or any registry.

### 5.1 This plan file's own interaction with planning traceability

An earlier revision of this document asserted that
`tests/test_planning_traceability.py` "reads only `.planning/`". **That was
false and is retracted.** At `main@2091d01c` the suite reads, outside
`.planning/`: `GOAL.md`, `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`,
`docs/ARCHITECTURE-OVERVIEW.md`, `docs/ENGINE-CONTRACT.md`, and — through
`test_unit_drift_checkout_fetches_canonical_main_history` — `.github/workflows/ci.yml`.
The correct analysis is narrower and is stated here in full rather than as a
blanket exemption.

**What was checked.** `grep -rl "docs/plans" tests/ .github/` returns nothing at
either baseline, and no test in the suite globs or enumerates a directory; every
source is a named constant resolved to one file. `docs/plans/` is therefore not
an input to any assertion, and adding a file to it changes no test outcome.

**Two live interactions remain, and neither is an exemption.**

1. **Ownership, not enumeration.** `docs/plans/` *is* inside the GoalEx
   lifecycle owner's exclusive surface — the `T4` and `T5` lease rows both name
   it. This file's write lease was granted explicitly for this one new path, but
   the directory around it is leased. Integration of this plan must therefore be
   serialized with the GoalEx owner exactly as any other `docs/plans/` write,
   and §1.2's recomputation requirement applies before that serialization is
   judged.
2. **A maintenance constraint this file must keep honouring.** PR #94 added
   `LEASE_BASELINE = re.compile(r"^Baseline: \`main@([0-9a-f]{40})\`$", re.MULTILINE)`
   and two tests —
   `test_canonical_baseline_is_identical_across_the_three_lifecycle_files` and
   `test_lease_map_body_names_only_the_header_baseline` — which require
   **exactly one** canonical-baseline claim per lifecycle file. Their file set is
   the lease map, `GOAL.md`, and `.planning/STATE.md`; this plan is not in it.
   This document's own baseline lines are deliberately written as
   `Verification baseline (...)` / `Integration baseline: ...` with an
   `origin/main@` prefix, so they do not match that anchored pattern even by
   accident. A future editor must not introduce a bare
   ``Baseline: `main@<40-hex>` `` line here: if the pinned set were ever widened
   to `docs/plans/`, such a line would register as a second canonical-baseline
   claim and break both tests.

---

## 6. RED / GREEN plan for `M04-A`

Strict TDD. Every step is RED first. The fixture bytes are frozen **last**,
after the schema invariants are proven, so that no later invariant change
invalidates a committed digest.

| # | RED test (all in `tests/test_public_wmbs_m04.py`) | Proves | GREEN |
|---|---|---|---|
| R1 | `test_fixture_schema_is_label_neutral` | `validate_fixture` raises `WmbsM04Error` when any row or gold carries `trust_tier`, `source_trust_tier`, `status`, `superseded_by`, `contested`, or `confidence`. | Closed key sets + the rejection list in `validate_fixture`. |
| R2 | `test_fixture_covers_seven_source_classes_five_seeds_three_permutations` | Exactly 28 cases, seeds `(11,23,37,53,71)`, permutations `(as_authored, reversed, interleaved)`; a reduced but self-consistent matrix is rejected. | Generator matrix + shape validation. |
| R3 | `test_generate_fixture_is_byte_reproducible` | `canonical_json(generate_fixture(DEFAULT_SEED))` equals the committed file's **raw bytes**, and the embedded `fixture_sha256` matches the digest over the fixture-without-digest. | Freeze the fixture file. |
| R4 | `test_historical_preservation_gate_is_exact` | `M04-HIST-PRESERVE < 1.0` fails; a single dropped superseded value fails. | `score_historical_preservation`. |
| R5 | `test_unresolved_state_is_scored_by_multiplicity_not_by_status` | A gold-conformant observation carrying only `object` values scores correctly; injecting a `status` field into the observation is rejected. | Closed observation allowlist. |
| R6 | `test_false_resolution_and_monotonic_violations_fail_closed` | Any single false high-confidence resolution and any monotonic violation fail. | `score_false_supersession`, monotonic check. |
| R7 | `test_permutation_invariance_and_clean_process_replay_equality` | Reordering sources changes no non-`unresolved` outcome; the closed canonical projection is byte-identical across five seeds and one clean-process replay. | `score_permutation_invariance`, canonical projection. |
| R8 | `test_source_ablation_sensitivity_matches_gold` | Withholding a source moves the current answer exactly where gold says it should, and nowhere else. | `score_source_ablation_sensitivity`. |
| R9 | `test_scorer_emits_no_publication_or_measurement_claim` | The aggregate result carries `admission_state="PROPOSED"`, `publishable=false`, `pbpp_headline_eligible=false`, `headline_eligible=false`, `independent_external_reproduction=false`, `upstream_comparable=false`, `interval={"method":"descriptive"}`, and no `evidence_level` above `IMPLEMENTED`. | Aggregate result envelope. |
| R10 | `test_branch_merge_and_transaction_time_are_declared_unsupported` | The module declares branch/merge `UNSUPPORTED-BY-SYSTEM` and transaction-time `unsupported`, and fails closed if either is asserted supported. | Explicit disclosure block. |

**Exact focused command for a future implementation session — recorded, not
executed here:**

```text
PYTHONPATH=src uv run --extra mcp pytest -q tests/test_public_wmbs_m04.py
```

Ruff and `git diff --check` run on the same head. No broad or full suite runs in
the M04 lane; the coordinator serializes broad validation.

### 6.1 Integration order

1. `M04-A` R1 → R10, in order, each RED before GREEN. Fixture frozen at R3.
2. Public-harness owner lands Q1 → Q6 in the stated order, on their lease.
3. Only then `M04-B`: registry row (canonical digest form), `_ADAPTERS`,
   `_NORMALIZERS` if needed, `_PROFILE_CONTRACTS` (`wmbs-m04-v1` →
   `("whole-memory-development", "descriptive")`), `score_profile` dispatch, a
   CLI-only adapter, and a README gap disclosure with a pinning test (M13
   precedent).
4. `M04-C` is not scheduled.

---

## 7. CODE-READY determination

**`M04-A` is CODE-READY.**

Stable local inputs: the controlling spec section is frozen; the M01 module is
byte- and digest-verified against its registry pin at this baseline; the
fixture/scorer pattern is stdlib-only and self-contained; and the module needs
no CLI, no adapter, no registry, no bundle, and therefore inherits none of
Q1–Q6.

**What Stage A's numbers are, exactly.** Every metric in §4.6 that Stage A can
produce — including `M04-HIST-PRESERVE`, `M04-MONOTONIC`, `M04-PERM-INVARIANT`,
and `M04-REPLAY-EQ` — is measured over **fixture-supplied observations**, not
over any system's output. Stage A therefore evidences exactly two things:
*generator determinism* (the committed bytes are reproducible from the pinned
seed) and *scorer determinism and fail-closed behaviour* (the scorer accepts
gold-conformant input, rejects every malformed or label-bearing input, and
projects identically across seeds and a clean process). It evidences **nothing
about any SUT.** A green Stage A run is not a conformance result, not a
capability claim, and not `INTERNALLY_MEASURED` evidence about Mnemosyne or any
entrant.

**How Stage A avoids the Q1/Q2 self-scoring shape.** It does *not* avoid it by
observing a SUT — Stage A observes nothing. It avoids it by **making no claim
that would require an observation**. The failure in Q1/Q2 is not that the M01
and M10 adapters compute against harness-authored data; it is that they do so
while sitting behind a registered suite whose output is labelled a module
"pilot" result. Stage A ships no adapter, no registry row, and no runner
routing, so there is no surface on which a self-scored number could be mistaken
for a measurement. The moment Stage B adds that surface, the Q1/Q2 hazard
becomes live for M04 too — which is why Stage B is gated on Q1 and Q2 being
fixed first, and why the R9 disclosure test exists to keep Stage A's envelope
honest in the interim.

Exact lease for the implementing session — **these three new files and nothing
else**:

```text
eval/public/wmbs_m04.py
eval/public/fixtures/wmbs-m04-development.json
tests/test_public_wmbs_m04.py
```

**`M04-B` is not code-ready.** Its irreducible blockers are exactly:

1. The public-harness integration lease is held by one owner and covers every
   file `M04-B` must edit.
2. Q1 and Q2 — the M01/M10 adapters do not exercise a SUT, so an M04 adapter
   modelled on them would score the harness against itself.
3. Q3 — composed replay does not prove shared SUT state or run constituent
   scorers.
4. Q4 and Q5 — registry provenance is not trustworthy for a new row until
   revision identity is testable and M03's own row exists.
5. Q6 — custody accepts fabricated hashes and there is no single volatile
   projection to bind to.

**`M04-C` is `DEFERRED`.** No §4.1 resource receipt, sandbox profile, BOM,
baseline manifest, or power plan exists for M04, and `SBOX` is quarantined.

---

## 8. Claim boundary

`PROPOSED` at every stage of this plan.

- After `M04-A`: `admission_state = PROPOSED`, `evidence_level = IMPLEMENTED`.
  A passing unit contract is **not** `CONTRACT-READY`, **not**
  `PILOT-READY-DEV`, and **not** a measurement.
- `CONTRACT-READY` additionally requires the reviewed §4.1 contract set minus
  the resource and smoke receipts. Not claimed.
- `PILOT-READY-DEV` additionally requires a deterministic smoke receipt on a
  measured L16-DEV profile. Not claimed; the former L16 numbers are explicitly
  not an admitted profile for M04.
- `RUN-READY-<profile>` is unreachable in this plan.

`DEFERRED` / `UNSUPPORTED` disclosures M04 carries permanently until a real hook
exists: branch/merge (`UNSUPPORTED-BY-SYSTEM`, §7.1 C05); transaction-time
semantics (`unsupported`, inherited from the bounded M03 cell); native `update`
(declared `emulated`, never `native`); non-JSON backends (`DEFERRED`, M16);
the §9.6 "Correction with evidence" joint scenario (`DEFERRED` — M05 is not
admitted, and passing constituent smokes cannot imply joint conformance).

Every M04 record is `publishable:false`, `pbpp_headline_eligible:false`,
`headline_eligible:false`, `independent_external_reproduction:false`,
`upstream_comparable:false`. No official, enhanced-successor, certified,
governed, neutral, headline, superiority, or independently-reproduced claim is
made or enabled here.

---

## 9. Explicitly out of scope

Official or upstream benchmark attempts; protected or held-out data; any
publication, signing, or rendering path; result-v2; sandbox execution; measured
resource receipts; T5 paths; branch/merge; transaction-time queries; SQLite or
PostgreSQL backends; M02, M05–M09, M11, M14, M16–M19; any edit to `GOAL.md`,
`.planning/`, the lease map, `tests/test_planning_traceability.py`,
`.github/workflows/`, or any existing source, test, fixture, registry, or
shared document.

---

## 10. Verification performed for this document

- Verification baseline confirmed at
  `main@effc5e039505c09e575ca5e4aeb2b96949676366`; working tree clean at start.
- Integration baseline `main@2091d01c8cea22da49a50bb1f0859d8108102f29` confirmed
  present locally, and `git diff --stat` between the two was taken to establish
  that no `eval/`, `src/`, fixture, or `tests/test_public_*` path changed, so
  every §3 finding was re-checked and carried forward rather than re-asserted on
  faith. The lease map's lapsed state at that baseline was read directly from
  `git show origin/main:docs/coordination/...` and is disclosed in §1.2. No
  rebase, checkout, or fetch-mutating operation was performed.
- Registry ↔ fixture custody recomputed independently for
  `wmbs-m01-development` and `wmbs-m10-development`; both match under the
  canonical-JSON pin. The M03 fixture's canonical and raw digests were computed
  and recorded in §3.2 Q5 without being written anywhere else.
- `eval/public/runner.py` dispatch tables, `eval/public/bundle.py` replay seed
  map, and `eval/public/scoring.py` profile dispatch were read directly to
  confirm Q5's routing gap and Q6's volatile-field divergence.
- `src/mnemosyne/ids.py` and `src/mnemosyne/models.py` were read to confirm the
  volatility of `id`, `superseded_by`, `transaction_time`, `last_accessed`, and
  `access_count`.
- `MemoryTools.graph_as_of` and the committed M03 `tied-valid-time` timeline
  were read to confirm that unresolved multiplicity is observable without any
  Mnemosyne-specific label.
- `tests/test_planning_traceability.py` was read in full at both baselines. It
  reads `GOAL.md`, the dependency lease map, `docs/ARCHITECTURE-OVERVIEW.md`,
  `docs/ENGINE-CONTRACT.md`, and `.github/workflows/ci.yml` in addition to
  `.planning/`. The earlier "reads only `.planning/`" claim is retracted; the
  corrected analysis is §5.1.
- One focused selection
  (`pytest -q tests/test_public_whole_memory_reference.py -k "m03 or m15_composed"`)
  ran once in this checkout at `b88dac0e`'s tree and reported **no failure and
  no error**. No selection count is asserted: the count previously recorded here
  (17) was read off streaming progress dots from a truncated tail, not off a
  pytest summary line, and an independent review reports the same command
  selecting 28 passing tests. The count is therefore unverified from this lane's
  own evidence and has been dropped rather than restated. The pass/fail
  observation stands; the cardinality does not, and nothing in this plan depends
  on it. No broad or full suite was run in this lane, and none was re-run for
  this revision under the standing resource guard.
- Diff scope, markdown structure, and secret scan were checked before commit.
  This document contains no credential, token, key, or endpoint.

No asset was modified. This lane wrote exactly one new file.
