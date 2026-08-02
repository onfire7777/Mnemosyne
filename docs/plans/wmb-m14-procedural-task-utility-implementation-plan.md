# WMB M14 — Procedural Task Utility Implementation Plan

Status: **PLANNING ARTIFACT ONLY — NOT CODE-READY.**
Authored: 2026-08-01.
Base: `origin/main@effc5e039505c09e575ca5e4aeb2b96949676366`.
Lane: `codex/wmb-m14-plan` in `/Users/admin/Mnemosyne.codex-wmb-m14-plan`.
Write lease exercised by this document: exactly
`docs/plans/wmb-m14-procedural-task-utility-implementation-plan.md`.

This document authorizes no code, no benchmark execution, no measurement, no
admission-state change, no push, no pull request, and no publication claim. It
freezes an implementation contract so that a future, separately admitted lane
can be evaluated against it.

---

## 1. Authority

| Source | Role here |
|---|---|
| `docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md` | Governing design. Section 6.1 divisions, Section 6.3 closed agent ABI, Section 8 `M14` module specification, Section 9.4 inferential contract. |
| `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md` | Pilot plan. Explicitly excludes M14 from the implementation lane and from scope. |
| `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md` | Scheduling authority. Places M14 in `U-MODULES`. |
| `GOAL.md` | Round policy, Ponytail rule, carve-out lapse rule. |
| `eval/public/schema/wmbs-0.1-draft.schema.json` | Frozen protocol `wmbs/0.1-draft`. |

Authoritative statements about M14 on this exact base:

- Spec, `M14` module record: **`Feasibility disposition: DEFERRED` until the
  deterministic simulator, protocol, paired control, and scorer are pinned;
  official STATE-Bench/EvoMemBench variants are also `DEFERRED`. M14 is not in
  the first pilot.**
- Spec Section 6.3: **"M14 remains deferred until this ABI and one
  deterministic simulator are implemented."**
- Pilot plan, execution boundary: "The implementation lane may not touch M02,
  M04–M09, M11, **M14**, or M16–M19 except where a shared existing contract
  must remain compatible." Out of scope: "M02, M04–M09, M11, **M14**, and
  M16–M19 implementation."
- Lease map row `U-MODULES`: class `SPEC UNSTABLE`, produces `No artifact
  authorized`, lease `No lease`, admission rule "Each needs an approved exact
  plan, protocol, scorer, license/custody, and dependency placement before
  code."

Nothing in this plan overrides any of the above. This plan is a candidate for
the "approved exact plan" the `U-MODULES` admission rule names; approval is not
self-granted here.

---

## 2. Verdict

**NOT CODE-READY.** Stable local inputs do not exist, and no implementation
lease disjoint from an existing exclusive owner can carry M14 to a reachable
state.

The irreducible blockers are named in Section 3. They are irreducible in the
specific sense required: none can be discharged by an M14 lane operating under
a lease disjoint from every surface in the lease map's `Shared-file owners`
table. Section 4 records what an M14 lane could build under a disjoint lease
and why that work would be stranded rather than useful, which is the reason
the verdict is `NOT CODE-READY` rather than `CODE-READY (Stage A only)`.

---

## 3. Irreducible blockers

### B1 — The Section 6.3 closed agent ABI does not exist in the frozen protocol

M14's contract is, verbatim, "the Section 6.3 `reset`/`observe`/`act`/
`finish_episode` protocol connected to a deterministic sandboxed task
environment."

Verified at base `effc5e03`: the compound schema
`eval/public/schema/wmbs-0.1-draft.schema.json` defines exactly these protocol
operations — `negotiate`, `create_run`, `ingest`, `retrieve`, `answer`,
`finalize` — through the definition set

```
negotiate_request/response, create_run_request/response/payload/receipt,
ingest_request/response/payload/receipt/status, retrieve_request/response/payload,
answer_request/response/payload/envelope, finalize_request/response/payload/receipt
```

There is **no** `EpisodeManifest`, `Observation`, `ActionEnvelope`,
`ActionReceipt`, or `EpisodeReceipt` definition, and no `reset`, `observe`,
`act`, or `finish_episode` request/response pair. `ProtocolValidator`
(`eval/public/adapters/whole_memory_reference.py`) validates only the six
existing operations and gates them through `_operation_allowed`.

Owner: the lease map's **Public-harness integration owner** holds
`eval/public/schema/wmbs-0.1-draft.schema.json` and
`eval/public/adapters/whole_memory_reference.py` as exclusive surfaces, "One
writer; serialize any package touching one of these paths." The agent ABI is
also not M14-specific: it is the required public surface for the whole
`AGENT-CLOSED` division (Section 6.1). Freezing it is a shared-protocol
package, not an M14 package.

### B2 — No deterministic task environment exists, and its natural host is quarantined

The spec conditions M14 on "one deterministic simulator." No such component
exists at base: a repository-wide search for the episode vocabulary returns no
implementation, and the indexed code graph for this checkout contains no
`episode` symbol.

The spec's contract also says "deterministic **sandboxed** task environment,"
and Section 6.5 requires an unprivileged ephemeral process/container with
default-deny egress and a harness-owned metering proxy for the entrant/runner
boundary. The lease map's `SBOX` row is `QUARANTINED`: "No push/PR/merge until
immutable image, daemon probe, filesystem/network/write-boundary enforcement,
SBOM, provenance, and resource receipts exist." `GOAL.md` records the same:
"Local OCI sandbox commits are reviewed development-source receipts only and
remain quarantined." Sandbox paths are additionally excluded from this lane by
its own instructions.

### B3 — M14's acceptance requires paired-interval inference that exists nowhere, on a surface this lane cannot lease

M14's acceptance is "a paired confidence-interval lower bound above zero versus
no-memory and the inherited no-degradation lower bound at least zero on
unrelated/novel tasks."

Verified at base: no paired-interval estimator exists anywhere in the tree.
`eval/public/scoring.py` produces single-arm intervals only — `_wilson_projection`
over `wilson_interval`, `_bootstrap` over one value list, or the literal
`{"method": "descriptive"}` returned by `_score_wmbs_m10`. The two no-memory
comparisons that do exist are **point** comparisons, not interval comparisons:

- `eval/public/wmbs_m10.py` derives `useful_coverage_floor` as the no-memory
  arm's `useful_coverage` plus a fixed margin, and `_score_wmbs_m10` reports
  `meets_useful_coverage_floor` as a scalar `>=` test.
- `src/mnemosyne/guard.py:no_degradation_guard` compares
  `memory_score - no_memory_baseline` against a scalar `minimum_margin`.

Registering any M14 scorer additionally requires editing `_PROFILE_CONTRACTS`
in `eval/public/runner.py` (enforced in `load_registry()`) and adding a
dispatch branch to `score_profile` in `eval/public/scoring.py`. Both files are
exclusive surfaces of the public-harness integration owner. There is no
disjoint lease under which an M14 scorer becomes reachable.

### B4 — The resource prerequisite requires a harness-owned model policy that is out of scope and unpinned

M14's resource prerequisite is "a measured receipt for the exact task simulator
**and model policy**," and Section 6.3 states "The harness owns the model policy
in the closed division."

No agent-loop model policy is preregistered. The only preregistered model
policy at base is `_qa_protocol` in `eval/public/registry.json`, which pins a
`qwen3:8b` Ollama **grounded reader** for `qa-em-f1-v1` — a single-shot
extractive reader, not a multi-turn tool-calling agent policy. The pilot plan
places "Paid/model-backed QA, LLM judging, provider bakeoffs" out of scope, and
`GOAL.md` gates protected/paid-provider evidence behind an operator.

---

## 4. Why a disjoint new-files-only lane is not a safe fallback

A new-files-only M14 lane (Section 8's Stage-A lease) would touch no existing
owner's surface and would therefore be admissible on lease grounds alone. It is
still rejected here, because the repository already contains the exact failure
mode such a lane produces.

**Quarantine Q1** below records that `run_m03_valid_time_development` and
`run_m15_composed_development` exist, are scorer-backed and unit-tested, and are
nevertheless unreachable from `run_public_suite`: no registry entry, no
`_ADAPTERS` key, no `_PROFILE_CONTRACTS` key. They therefore carry no pinned
`dataset_sha256`, emit no run bundle, and never pass through the runner's
digest re-check. A Stage-A-only M14 lane reproduces that state by construction,
because every one of M14's integration points (Section 9) sits on the
public-harness owner's exclusive lease.

Building a stranded fourth cell is not the smallest useful change. Under
`GOAL.md` rule 4 (Ponytail) the smallest correct action is to leave M14 unbuilt
until B1 is discharged by its actual owner.

---

## 5. Adversarial validation of every asset this plan cites

Each asset below was checked against the base commit for fixture/scorer
integrity, stale digests, pass-without-execution paths, mutable or tampered
evidence, custody/provenance binding, failure paths, and runtime assumptions.
Results are recorded whether or not they favour reuse. No asset was edited.

### 5.1 Assets validated as current-main bound and safe to cite

| Asset | Check performed | Result |
|---|---|---|
| `eval/public/registry.json` entries `wmbs-m01-development`, `wmbs-m10-development`, `pm-bench-development`, `triggerbench-development`, `working-memory-action-development`, `qa-smoke`, `smoke` | Recomputed each suite's normalized `dataset_sha256` by executing `load_registry()`, the registered normalizer, and `_canonical()` at base, and compared against the registry pin. Also confirmed each `adapter` key resolves in `runner._ADAPTERS` and each `scoring_profile` resolves in `runner._PROFILE_CONTRACTS`. | All seven: digest match, adapter registered, profile contract present. No stale digest. |
| `eval/public/custody.py:load_pinned_json_asset` (via `assets.py`) | Read the failure paths: 40-hex revision pin, 64-hex lowercase SHA-256, SPDX allowlist, symlink rejection on every path component, dataset-root escape rejection, non-finite JSON rejection, duplicate-key rejection, and the explicit "This function deliberately has no downloader." | Fail-closed. Safe to reuse as M14's external-asset custody path if M14 ever admits an external asset. |
| `eval/public/runner.py:run_public_suite` digest discipline | Confirmed the normalized benchmark digest is checked **twice** — once on adapter input and again on the adapter-returned benchmark — so an adapter that mutates its benchmark fails closed rather than silently rescoring. | Sound. M14 must return its benchmark unmutated or explicitly as the three-tuple form. |
| `eval/public/wmbs_m10.py` `Case`/`AnswerEnvelope`/`generate_fixture`/`fixture_digest` and the `system_seam: "harness-owned-reference-core"` dispatch | Read the seam: when `system_seam` is `harness-owned-reference-core`, `run_public_suite` invokes the adapter with `cli=None` and no `MnemoCLI` subprocess. Confirmed the frozen-dataclass case model, deterministic per-seed generation, and split manifests. | This is the correct structural precedent for a **harness-owned deterministic environment**. M14's environment should follow this seam, not the `MnemoCLI` subprocess seam. |
| `src/mnemosyne/guard.py:no_degradation_guard` | Read the implementation and its tests. | Real and current, but **point-estimate only**. Citable as the inherited no-degradation rail; **not** citable as M14's paired-CI acceptance. See Q3. |

### 5.2 Integrity quarantines

Each quarantine records the defect, the evidence, the consequence for M14, and
the smallest RED regression that would pin it. **No quarantined asset was
edited by this lane.** Each RED regression is specified for the owner of the
affected surface, not for this lane.

---

#### Q1 — M03 and M15 development cells are unreachable from the public runner, and the registry does not disclose the asymmetry

**Evidence (base `effc5e03`).**
`eval/public/adapters/whole_memory_reference.py` exports
`run_m03_valid_time_development` and `run_m15_composed_development`.
`eval/public/scoring.py:score_profile` dispatches
`wmbs-m03-valid-time-v1` to `_score_wmbs_m03_valid_time`. The fixture
`eval/public/fixtures/wmbs-m03-valid-time-development.json` exists on disk.

But executing `load_registry()`, `runner._ADAPTERS`, and
`runner._PROFILE_CONTRACTS` at base yields:

- registry suites: `hipporag-2wiki`, `hipporag-hotpot`, `hipporag-musique`,
  `longmemeval-retrieval`, `pm-bench-development`, `qa-smoke`, `smoke`,
  `triggerbench-development`, `wmbs-m01-development`, `wmbs-m10-development`,
  `working-memory-action-development` — **no M03 or M15 entry**;
- `_ADAPTERS` keys cover `wmbs-m01-reference` and `wmbs-m10-reference` only —
  **no M03 or M15 adapter key**;
- `_PROFILE_CONTRACTS` covers `wmbs-m01-v1` and `wmbs-m10-v1` for the
  `whole-memory-development` family — **no `wmbs-m03-valid-time-v1` and no M15
  profile**.

**Consequence.** M03 and M15 have no pinned `dataset_sha256`, never pass
through either of `run_public_suite`'s digest re-checks, never emit a run
bundle, and are bound only by direct calls in
`tests/test_public_whole_memory_reference.py`. `eval/public/registry.json` — the
custody record — does not disclose that two of the six named development pilots
are unregistered while the other two are registered.

**Effect on this plan.** M03's valid-time contract and M15's composed replay
are cited in this document **only** as unit-level contract precedent. They are
**not** cited as executable replay, custody, or bundle precedent, and no M14
acceptance may inherit from them.

**Smallest RED regression (public-harness integration owner).** In
`tests/test_public_whole_memory_reference.py`, assert that every public
`run_m*_development` callable exported by
`eval.public.adapters.whole_memory_reference` is either present as a value in
`eval.public.runner._ADAPTERS` **or** named in an explicit, documented
`UNREGISTERED_CONTRACT_ONLY` constant carrying a one-line reason per entry.
This is RED at base for `run_m03_valid_time_development` and
`run_m15_composed_development`, and it turns an undisclosed asymmetry into a
declared one without changing any measurement.

---

#### Q2 — `replay_protocol` is a self-asserted declaration; nothing executes the five runs or the clean-process restart it claims

**Evidence (base `effc5e03`).** `$defs.replay_protocol` in
`eval/public/schema/wmbs-0.1-draft.schema.json` requires
`run_count: {"const": 5}` and
`clean_process_replay: {"type": "boolean", "const": true}`. It is a required
member of `FeasibilityRecord`. A record satisfies it by writing the constants.

`run_m15_composed_development` executes `run_once` exactly **twice** — once on
the supplied CLI and once on a `replace(cli, store=...)` copy inside a
`TemporaryDirectory` — **in the same process**. There is no fifth run and no
process restart. The `canonical_equality` gate compares those two in-process
runs.

`eval/public/README.md` nevertheless states: "M15 replay freezes canonical
payload `m15-v1`, exactly five runs, and required clean-process replay." The
round record `docs/plans/goalex-r24-implement-m15-canonical-replay-and-compo.md`
concedes the actual scope: "Unit-shape five golden deterministic payloads plus
one new-process-shaped payload per admitted suite, **recording their projection
digests without claiming actual clean-process reproduction**."

Grepping the tree for any executable cross-check of `run_count` or
`clean_process_replay` against a real run ledger returns only the schema
constants and the tests that assert those constants are frozen
(`test_m15_replay_protocol_is_frozen`).

**Classification.** Pass-without-execution. The schema pins the *claim*; no
code pins the *fact*. The round record is honest about this; the README
sentence, read alone, is not.

**Consequence for M14.** M14's spec requires "five runs per task for
reliability" and "simulator seed and rule digest retained." Those must be
enforced by an executed run ledger whose length and process identity the
validator checks, not by a schema `const`. M14 must not satisfy its
repeat/replay requirement by declaration.

**Smallest RED regression (public-harness integration owner).** Add one test
that builds a `FeasibilityRecord` whose `replay_protocol.run_count` and
`clean_process_replay` are the frozen constants but whose accompanying executed
run ledger contains fewer than five entries and records a single process
identity, and assert `validate_evidence_bundle` rejects it. This is RED at
base: no ledger field is cross-checked, so the record validates.

---

#### Q3 — Reuse quarantine: no existing no-memory comparison is a paired control

**Evidence.** Detailed in B3. `m10.retrieve_no_memory` and
`useful_coverage_floor_from_fixture` produce a scalar floor;
`no_degradation_guard` produces a scalar margin. The `whole-memory-development`
family's registry contract is `interval_method: "descriptive"` for both
registered profiles, and `_score_wmbs_m10` hard-codes
`"interval": {"method": "descriptive"}`.

**Classification.** Not a defect — a boundary. These components do exactly what
they claim.

**Consequence for M14.** Two distinct things follow, and both are binding:

1. M10's no-memory arm may **not** be cited as precedent for M14's paired
   control. It is a baseline floor, not a paired difference estimator.
2. Because the `whole-memory-development` family is contractually
   descriptive-interval, an M14 cell admitted into that family **cannot** carry
   the paired confidence-interval lower bound its acceptance requires. M14's
   acceptance is therefore structurally undeliverable at the development tier.
   This is recorded as a claim boundary in Section 11, not as work an M14 lane
   can close.

---

#### Q4 — The whole-memory contract suite has an undeclared test-time dependency on the `mcp` extra

**Evidence (base `effc5e03`, reproduced locally).**
`tests/test_public_whole_memory_reference.py` imports
`from jsonschema import Draft202012Validator`. `pyproject.toml` declares
`[project].dependencies = ["cryptography>=42"]`, extras `postgres`, `mcp`,
`native`, `sqlitevec`, and `[dependency-groups].dev = ["pytest==9.1.1",
"ruff==0.15.20", "hypothesis>=6.100", "pytest-benchmark>=5.1"]`. `jsonschema`
appears in none of them; it is pulled in transitively by `mcp`.

`uv sync --locked --group dev` followed by
`uv run --locked python -m pytest tests/test_public_whole_memory_reference.py`
fails at collection with `ModuleNotFoundError: No module named 'jsonschema'`.
`.github/workflows/ci.yml` masks this because its unit job syncs
`uv sync --locked --extra mcp --group dev`.

**Consequence for M14.** M14's contract suite inherits the same latent
dependency. A future M14 test file that validates against the compound schema
is uncollectable in a dev-group-only environment, and the failure surfaces as a
collection error rather than a dependency error.

**Smallest RED regression (CI integration owner or the dependency owner).**
Declare `jsonschema` explicitly in `[dependency-groups].dev` and assert its
importability in an environment synced with `--group dev` alone. RED at base.

---

## 6. Prerequisites frozen

M14 is admissible for implementation only when **all** of the following are
true on then-current `main`. This list is exhaustive and ordered.

| # | Prerequisite | Owner | Discharges |
|---|---|---|---|
| P1 | `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md` is recomputed from then-current `main` and its `U-MODULES` row no longer covers M14. | GoalEx lifecycle/integration owner | Scheduling authority (Section 7) |
| P2 | Section 6.3's `EpisodeManifest`, `Observation`, `ActionEnvelope`, `ActionReceipt`, `EpisodeReceipt` and the `reset`/`observe`/`act`/`finish_episode` request/response pairs are frozen in `eval/public/schema/wmbs-0.1-draft.schema.json`, and `ProtocolValidator` admits them with ordering, deadline, idempotency, and error-class semantics matching the six existing operations. | Public-harness integration owner | B1 |
| P3 | One deterministic task environment exists as a harness-owned reference core, seeded, with a frozen rule digest and deterministic final-state assertions. | Public-harness integration owner, or a newly admitted M14 owner | B2 |
| P4 | An agent-loop model policy is preregistered with the same custody discipline `_qa_protocol` applies to the grounded reader — provider, selector, resolved content digest, decoding options, and role-template digests — **or** the M14 cell is explicitly restricted to a deterministic non-model policy and labelled as such. | Public-harness integration owner + operator | B4 |
| P5 | A paired-difference interval estimator exists, is unit-tested against known inputs, and is admitted into `score_profile`; and a family whose registry `interval_method` is not `descriptive` is available for M14. | Public-harness integration owner | B3, Q3 |
| P6 | Q1 and Q2 are dispositioned by their owner — either fixed or converted into declared, tested disclosures. | Public-harness integration owner | Q1, Q2 |
| P7 | A sandbox/metering receipt path exists for the episode environment, or the M14 cell is explicitly restricted to the in-process harness-owned seam with no entrant-supplied code, and labelled as such. | `SBOX` owner + operator | B2 (partial) |

P1 is currently false on this base: the lease map reads
`Baseline: main@e157e0350c503c9cde4aca0eff71d643a4adb200` and carries `T4` as
`DELIVERING`, while `main` is at `effc5e03`, two merges further on (`39cfa67a`,
PR #92; `effc5e03`, PR #93). `GOAL.md`'s own lapse rule fires: the carve-out
"lapses the moment any merge lands on `main` that the branch-resident map does
not already record, at which point the map must be recomputed from current
`main` before it is treated as operative again." Recomputation is the GoalEx
owner's, not this lane's.

---

## 7. Scheduling constraint at this base

The lease map's concurrency rule reads: "Current safe coding concurrency is
**zero new implementation writers**: every remaining source package is
dependency-, lease-, evidence-, or spec-blocked." Its `Topological waves`
block places `U-MODULES` in `Quarantine`: "U-MODULES stay outside every wave
until exact plans exist."

M14 therefore has no admissible wave at this base regardless of this document's
quality. This plan does not create one.

---

## 8. Exact future source and test file lease

Recorded so that a future admitted lane inherits an exact, checkable lease.
This lease is **not claimed by this document** and confers nothing until P1–P7
hold.

### Stage A — M14-owned, disjoint from every current exclusive surface

| Path | Status | Purpose |
|---|---|---|
| `eval/public/wmbs_m14.py` | new | Harness-owned deterministic episode environment: frozen case/task dataclasses, per-seed generator, rule digest, final-state assertion evaluator, and the no-memory control arm. Structural analogue of `eval/public/wmbs_m10.py`. |
| `eval/public/adapters/wmbs_m14_task.py` | new | `run_m14_task_utility_development(fixture, cli)` adapter. **Must not** be added to `eval/public/adapters/whole_memory_reference.py`, which is an exclusive surface. |
| `eval/public/fixtures/wmbs-m14-task-utility-development.json` | new | Generated development fixture. |
| `tests/test_public_wmbs_m14.py` | new | M14 contract, generator determinism, scorer, and failure-path suite. |

### Stage B — public-harness integration owner, serialized, NOT in the M14 lane's lease

| Path | Required edit |
|---|---|
| `eval/public/schema/wmbs-0.1-draft.schema.json` | P2 agent-ABI definitions. |
| `eval/public/adapters/whole_memory_reference.py` | `ProtocolValidator` operation table and response binding for the four new operations. |
| `eval/public/runner.py` | `_ADAPTERS["wmbs-m14-task-reference"]`, `_PROFILE_CONTRACTS["wmbs-m14-v1"]`. |
| `eval/public/scoring.py` | `score_profile` dispatch to `_score_wmbs_m14`; paired-difference estimator from P5. |
| `eval/public/registry.json` | Suite entry `wmbs-m14-task-utility-development`. |
| `eval/public/README.md` | Development gap disclosures, in the style already used for M12/M13. |
| `tests/test_public_whole_memory_reference.py` | Agent-ABI validator tests. |

Stage B is the whole reason for the `NOT CODE-READY` verdict: without it,
Stage A is Q1 again.

### Explicitly excluded from every M14 stage

`GOAL.md`; `.planning/`; `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`;
`tests/test_planning_traceability.py`; `.github/workflows/`;
`leaderboard/` and every result-v2 path; every signed-publication path;
`eval/public/sandbox.py`, `eval/public/sandbox/`, `tests/test_public_sandbox.py`;
every `T5` carve-out path; `eval/public/receipts/`.

---

## 9. Consumed and produced interfaces

### Consumed

| Interface | Source | Binding |
|---|---|---|
| `RequestContext`, `ErrorEnvelope`, closed error enum | `wmbs-0.1-draft.schema.json` | Reused unchanged. `WholeMemoryValidationError.code` carries one of the nine closed codes. |
| `canonical_json` / `canonical_sha256` / `canonical_projection` | `eval/public/adapters/whole_memory_reference.py` | Reused for the M14 canonical payload and digests. |
| `canonical_replay_projection` / `canonical_replay_fixture_custody` / `canonical_replay_digest` | `eval/public/bundle.py` | Reused for replay custody, subject to Q2: the executed run ledger must be checked, not the schema `const`. |
| `AssetSpec` / `load_pinned_json_asset` | `eval/public/assets.py` | Reused only if M14 ever admits an external asset. The development cell admits none. |
| `harness-owned-reference-core` seam | `eval/public/runner.py` | M14's environment is harness-owned; the adapter receives `cli=None`. |
| `no_degradation_guard` | `src/mnemosyne/guard.py` | Inherited rail only. Not the paired-CI acceptance (Q3). |
| Section 6.3 agent ABI | **does not exist** | B1. Consumed only after P2. |

### Produced

| Artifact | Shape |
|---|---|
| `wmbs-m14-task-utility-development` suite entry | `family: whole-memory-development` (or the P5 family), `admission_state: PROPOSED`, `license: CC0-1.0`, `split_role: development`, `system_seam: harness-owned-reference-core`, `track_kind: DEVELOPMENT`, `publishable: false`, `pbpp_headline_eligible: false`, `headline_eligible: false`, `independent_external_reproduction: false`, `upstream_comparable: false`, exact `dataset_sha256` and 40-hex `revision`. |
| M14 traces | One row per `(task_id, seed, arm)` carrying `case_id`, `scoring_family`, arm label (`memory` / `no-memory`), final-state assertion outcomes, procedure-compliance outcome, `turns`, `tool_calls`, `tokens`, and the harness-measured cost fields. Entrant self-reported usage is disclosure only. |
| M14 evidence | Canonical replay projection, rule digest, simulator seed set, executed run ledger (Q2), exact gates, and the four false publication flags. |
| Development gap disclosure | A README paragraph in the M12/M13 style naming every deferred acceptance component. |

---

## 10. Fixture, scorer, and custody contract

**Fixture.** Repository-authored, CC0-1.0, generated by a committed
deterministic generator with a pinned `generator_id`/`generator_version`, a
`fixture_sha256` self-digest, and an explicit seed list. Task families follow
the spec's four controls: repeated, structurally related, novel, and unrelated.
Local stateful support/travel/shopping-style tasks only. Named
`*-development`; never an upstream official benchmark name. No official
STATE-Bench or EvoMemBench adapter, pinned or otherwise.

**Scorer.** Deterministic final-state assertions over the environment's
terminal state, plus procedure compliance, `pass@1`, `pass^5`, turns, tool
calls, tokens, and cost. `pass^5` requires five executed runs per task, which
under Q2 must be counted from an executed ledger. The secondary UX rubric is
`DEFERRED`: it is a judged output and no judge is admitted here. The scorer
must fail closed on label/trace mismatch, duplicate or missing case IDs, arm
mismatch, and gold leakage into traces, matching the discipline already in
`_bind_action`.

**Custody and licence.** Fixture and generator are repository-authored CC0-1.0.
No external asset, protected dataset, or upstream corpus. No paid provider. If
P4 admits a model policy, its custody must bind provider, selector, resolved
content digest, decoding options, and role-template digests exactly as
`_qa_protocol` does. Logs redact secrets and direct personal data per Section
6.5.

---

## 11. Claim boundary

### PROPOSED — a future admitted lane may honestly claim these

- The M14 adapter, fixture, and scorer contracts as **contract shapes**.
- Fixture generator determinism and self-digest custody.
- Deterministic final-state assertion outcomes on the committed development
  fixture.
- Procedure-compliance outcomes and harness-measured turn/tool-call/token
  counters.
- Simulator seed and rule-digest retention.
- Canonical-projection replay equality between an original run and a replay,
  stated at exactly the run count and process discipline actually executed.
- `admission_state: PROPOSED`, `publishable: false`,
  `pbpp_headline_eligible: false`, `independent_external_reproduction: false`,
  `upstream_comparable: false`.

### DEFERRED — no lane may claim these under this plan

- Any improvement claim versus no-memory. The paired confidence-interval lower
  bound above zero does not exist (B3, Q3).
- Any no-degradation claim on unrelated/novel tasks stated as an interval lower
  bound at least zero. Only the inherited point-estimate rail exists.
- `pass^5` reliability, until five runs per task are executed and counted from a
  ledger rather than asserted (Q2).
- Cost and the secondary UX rubric.
- Official STATE-Bench and EvoMemBench variants — `DEFERRED` in the spec, and
  their simulator/model contracts are unpinned.
- Every `official_local`, `hosted_service`, and `production_operations`
  feasibility disposition. `DEFERRED` in all three.
- Any resource receipt, sandbox receipt, smoke receipt, or `PILOT-READY-DEV`
  label, until P3/P4/P7 hold.
- Any ranking, certification, superiority, launch-readiness, publication,
  leaderboard, or result-v2 statement.

M14's `feasibility_disposition.development` remains **`DEFERRED`** on this base
and does not move to `PROPOSED` until P1–P7 hold. This document does not move
it.

---

## 12. RED/GREEN checks for the future lane

Written so the first implementation step is unambiguous. Every check is RED at
base; none may be written before P1–P7.

| # | RED test | GREEN condition |
|---|---|---|
| R1 | `ProtocolValidator` rejects a `reset` request as `UNSUPPORTED_OPERATION`. | After P2, `reset(EpisodeManifest)` validates and returns a schema-valid `Observation`; an out-of-order `act` before `reset` is `ORDER_VIOLATION`; `finish_episode` with an unresolved in-flight `act` is rejected exactly as `finalize` is today. |
| R2 | `wmbs_m14.generate_fixture()` does not exist. | Two invocations at a fixed seed produce byte-identical canonical JSON, and `fixture_sha256` equals the canonical digest of the fixture with that field omitted. |
| R3 | Environment determinism: two `reset`→scripted-action→`finish_episode` sequences at one seed diverge. | Byte-identical `EpisodeReceipt` canonical projections; the rule digest is stable across both. |
| R4 | `score_profile("wmbs-m14-v1", ...)` raises `unknown scoring profile`. | Returns final-state accuracy, procedure compliance, `pass@1`, turns, tool calls, tokens, `family`, `profile`, `profile_version`, and `total`, and fails closed on arm mismatch, duplicate case IDs, and gold leakage. |
| R5 | `load_registry()` raises for a `wmbs-m14-task-utility-development` entry (no `_PROFILE_CONTRACTS` key). | Entry loads; the recomputed normalized digest equals the pinned `dataset_sha256` under both of `run_public_suite`'s checks. |
| R6 | A `run_count: 5` / `clean_process_replay: true` declaration validates against an executed ledger of length 2 with one process identity. | The validator rejects the mismatch. **This is Q2's regression and belongs to the public-harness owner, not the M14 lane.** |
| R7 | No paired-difference estimator exists. | Given synthetic paired arms with a known difference, the estimator returns the analytically expected point estimate and a lower bound whose sign is correct at a fixed seed. |

**First concrete test decision.** `R2` — `tests/test_public_wmbs_m14.py::test_generate_fixture_is_byte_identical_at_a_fixed_seed`. It is the only check in the table that depends on no unmet prerequisite except the lane's own admission: it needs neither the agent ABI (P2), nor a model policy (P4), nor the paired estimator (P5). It is therefore the correct first RED test whenever M14 is admitted, and it is the one Stage-A artifact that retains value even if the environment design later changes.

---

## 13. Integration order

1. **Stage 0 — GoalEx owner.** Recompute the lease map from current `main`
   (P1). Without this, no admission is valid.
2. **Stage 1 — public-harness owner.** Freeze the Section 6.3 agent ABI in the
   schema and `ProtocolValidator` (P2). Shared-protocol package; not
   M14-specific.
3. **Stage 2 — public-harness owner.** Disposition Q1 and Q2 (P6). Doing this
   before M14 exists prevents a third stranded cell and a third self-asserted
   replay claim.
4. **Stage 3 — M14 lane, Stage-A lease.** Deterministic environment, generator,
   fixture, adapter, tests. RED-first from R2.
5. **Stage 4 — public-harness owner.** Paired estimator and non-descriptive
   family (P5), then scorer dispatch, `_PROFILE_CONTRACTS`, `_ADAPTERS`,
   registry entry, README disclosure.
6. **Stage 5 — operator.** Model policy (P4) and sandbox/metering disposition
   (P7), or the explicit restriction labels those prerequisites permit.
7. **Stage 6.** Development-tier evidence at `PROPOSED` only, with every
   Section 11 `DEFERRED` item stated as deferred.

Stages 1, 2, 4 serialize on the public-harness owner's single-writer rule.
Stage 3 is the only stage an M14 lane owns.

---

## 14. Ponytail compliance

- No new runtime dependency. The Stage-A lease is stdlib-only and reuses the
  existing canonical-JSON, digest, custody, bundle, and seam contracts.
- No speculative abstraction. No generic "environment framework" is proposed;
  one deterministic environment, mirroring `wmbs_m10.py`'s shape.
- Smallest change: this base's smallest correct action for M14 is **no code**.
  The plan says so rather than manufacturing a stranded artifact.

---

## 15. Validation performed by this lane

- Baseline suite receipt (read-only, this lane, no artifact retained): under
  the CI environment `uv sync --locked --extra mcp --group dev`,
  `uv run --locked python -m pytest tests/test_public_whole_memory_reference.py
  tests/test_public_wmbs_m01.py tests/test_public_wmbs_m10.py
  tests/test_public_working_memory_action_probe.py
  tests/test_public_pm_bench_triggerbench.py -q` exits 0 at `effc5e03`. The same
  invocation under `--group dev` alone fails at collection, which is Q4's
  evidence. This is a development operability observation only; it is not a
  benchmark run, a measurement, or evidence for any claim.
- Markdown: single H1, ordered heading levels, closed fenced block, balanced
  tables.
- Diff scope: exactly one added file,
  `docs/plans/wmb-m14-procedural-task-utility-implementation-plan.md`. No other
  path in the working tree was modified, staged, or removed.
- Secret and risky-file check: this document contains no credential, token,
  key, endpoint, host path outside the repository, or personal data. No
  `.env`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `credentials.json`,
  `service-account.json`, `secrets.json`, `keycloak/out/`, `vault/out/`,
  `c2pa/out/`, `**/wrapped-keys/`, `.mnemosyne/`, `*.db`, or `*.sqlite` path
  was read, written, copied, or hashed.
- Excluded paths confirmed untouched: `GOAL.md`, `.planning/STATE.md`, the
  dependency/write-lease map, `tests/test_planning_traceability.py`,
  `.github/workflows/ci.yml`, all source, all tests, all fixtures, the
  registry, and every shared document.
- Quarantined assets were read only. None was edited.
