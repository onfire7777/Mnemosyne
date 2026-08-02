# WMB M14 — Procedural Task Utility Implementation Plan

Status: **PLANNING ARTIFACT ONLY — NOT CODE-READY.**
Authored: 2026-08-01. Revised: 2026-08-01 (independent review pass).
Lane base: `origin/main@effc5e039505c09e575ca5e4aeb2b96949676366`.
Lane: `codex/wmb-m14-plan` in `/Users/admin/Mnemosyne.codex-wmb-m14-plan`.
Write lease exercised by this document: exactly
`docs/plans/wmb-m14-procedural-task-utility-implementation-plan.md`.

**Base drift.** `origin/main` has advanced to
`2091d01c8cea22da49a50bb1f0859d8108102f29` since this lane was cut. This lane
was **not** rebased. Every "at base" / "verified" statement in this document is
scoped to `effc5e03` and to no later commit. A future admitting owner must
re-verify Sections 3, 5, and 6 against then-current `main` before treating any
finding here as current. Where this document asserts currentness, read it as
currentness *at `effc5e03`*.

This document authorizes no code, no benchmark execution, no measurement, no
admission-state change, no push, no pull request, and no publication claim. It
freezes an implementation contract so that a future, separately admitted lane
can be evaluated against it.

---

## 1. Authority

| Source | Role here |
|---|---|
| `docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md` | Governing design. Section 6.1 divisions, Section 6.3 closed agent ABI, Section 6.5 trust boundaries, Section 8 `M14` module specification, Section 9.4 inferential contract. |
| `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md` | Pilot plan. Explicitly excludes M14 from the implementation lane and from scope. |
| `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md` | Scheduling authority. Places M14 in `U-MODULES`. |
| `GOAL.md` | Round policy, Ponytail rule, carve-out lapse rule. |
| `eval/public/schema/wmbs-0.1-draft.schema.json` | Frozen protocol `wmbs/0.1-draft`. |

Authoritative statements about M14 at this base:

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
table. Section 4 records why a new-files-only lane is not a safe fallback.

---

## 3. Irreducible blockers

### B1 — The Section 6.3 closed agent ABI does not exist in the frozen protocol

M14's contract is, verbatim, "the Section 6.3 `reset`/`observe`/`act`/
`finish_episode` protocol connected to a deterministic sandboxed task
environment."

Verified at base: the compound schema
`eval/public/schema/wmbs-0.1-draft.schema.json` defines exactly these protocol
operations — `negotiate`, `create_run`, `ingest`, `retrieve`, `answer`,
`finalize`. There is **no** `EpisodeManifest`, `Observation`, `ActionEnvelope`,
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
SBOM, provenance, and resource receipts exist." `GOAL.md` records the same.
Sandbox paths are additionally excluded from this lane by its own instructions.

### B3 — M14's acceptance requires paired-interval inference that exists nowhere, on a surface this lane cannot lease

M14's acceptance is "a paired confidence-interval lower bound above zero versus
no-memory and the inherited no-degradation lower bound at least zero on
unrelated/novel tasks."

Verified at base: no paired-interval estimator exists anywhere in the tree.
`eval/public/scoring.py` produces single-arm intervals only — `_wilson_projection`
over `wilson_interval`, `_bootstrap` over one value list, or the literal
`{"method": "descriptive"}` returned by `_score_wmbs_m10`. The two no-memory
comparisons that exist are **point** comparisons (Q3, Section 5.2).

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

Quarantines **Q2** and **Q5** record that `run_m03_valid_time_development` and
`run_m15_composed_development` exist, are scorer-backed and unit-tested, and are
nevertheless unreachable from `run_public_suite`: no registry entry, no
`_ADAPTERS` key, no `_PROFILE_CONTRACTS` key. They therefore carry no pinned
`dataset_sha256`, emit no run bundle, and never pass through the runner's
digest re-check. A Stage-A-only M14 lane reproduces that state by construction,
because every one of M14's integration points (Section 9) sits on the
public-harness owner's exclusive lease.

Building a stranded third cell is not the smallest useful change. Under
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
| `eval/public/registry.json` entries `wmbs-m01-development`, `wmbs-m10-development`, `pm-bench-development`, `triggerbench-development`, `working-memory-action-development`, `qa-smoke`, `smoke` | Recomputed each suite's normalized `dataset_sha256` by executing `load_registry()`, the registered normalizer, and `_canonical()` at base, and compared against the registry pin. Also confirmed each `adapter` key resolves in `runner._ADAPTERS` and each `scoring_profile` resolves in `runner._PROFILE_CONTRACTS`. | All seven: digest match, adapter registered, profile contract present. No stale digest. **Digest custody only** — this check says nothing about whether a suite exercises the SUT (see Q1, Q3). |
| `eval/public/custody.py:load_pinned_json_asset` (via `assets.py`) | Read the failure paths: 40-hex revision pin, 64-hex lowercase SHA-256, SPDX allowlist, symlink rejection on every path component, dataset-root escape rejection, non-finite JSON rejection, duplicate-key rejection, and the explicit "This function deliberately has no downloader." | Fail-closed. Safe to reuse as M14's external-asset custody path if M14 ever admits an external asset. |
| `eval/public/runner.py:run_public_suite` digest discipline | Confirmed the normalized benchmark digest is checked **twice** — once on adapter input and again on the adapter-returned benchmark — so an adapter that mutates its benchmark fails closed rather than silently rescoring. | Sound. M14 must return its benchmark unmutated or explicitly as the three-tuple form. |
| `eval/public/wmbs_m10.py` `Case`/`AnswerEnvelope`/`generate_fixture`/`fixture_digest` and the `system_seam: "harness-owned-reference-core"` dispatch | Read the seam: when `system_seam` is `harness-owned-reference-core`, `run_public_suite` invokes the adapter with `cli=None` and no `MnemoCLI` subprocess. Confirmed the frozen-dataclass case model, deterministic per-seed generation, and split manifests. | Citable as the structural precedent for a **harness-owned deterministic environment**: frozen dataclasses, per-seed generation, split manifests. **Not** citable as SUT evidence (Q3). |
| `eval/public/adapters/whole_memory_reference.py` bounded-trust constants | Read the enforced limits and their call sites. | Sound and binding on M14. Enumerated in Section 9.3. |
| `src/mnemosyne/guard.py:no_degradation_guard` | Read the implementation and its tests. | Real and current, but **point-estimate only**. Citable as the inherited no-degradation rail; **not** citable as M14's paired-CI acceptance (Q3). |

### 5.2 Integrity quarantines

Each quarantine records the defect, the evidence, the owner of the affected
surface, the consequence for M14, and the smallest RED regression that would
pin it. **No quarantined asset was edited by this lane.** Each RED regression is
specified for the owner named, not for this lane, except where marked
M14-owned.

Module quarantines are ordered **M01 → M03 → M10 → M12 → M15**, followed by the
non-module quarantines Q6–Q8.

---

#### Q1 — M01: the reference cell does not exercise the SUT, and its five-run replay evidence is one payload repeated

**Owner:** public-harness integration owner
(`eval/public/adapters/whole_memory_reference.py`, `eval/public/wmbs_m01.py`).

**Evidence (base `effc5e03`).** `run_m01_development(benchmark, _cli)` takes its
CLI parameter as `_cli` and **never uses it**. The registry pins
`system_seam: "harness-owned-reference-core"`, so `run_public_suite` invokes it
as `adapter(adapter_input, None)`; no `MnemoCLI` subprocess and no Mnemosyne
engine is involved. Every trace field is synthesized from the fixture by
`m01.perfect_receipts(fixture)`, `m01.perfect_export_rows(fixture)`, and
`m01.perfect_stored_projection(fixture)` — ideal outputs derived from the
fixture, not observed from a system under test.

The replay evidence is stronger than "unexecuted"; it is tautological.
`eval/public/wmbs_m01.py` sets `MIN_CLEAN_REPLAY_RUNS = 5` and its scorer
rejects `len(clean_run_payloads) < MIN_CLEAN_REPLAY_RUNS`. The adapter
satisfies that check with

```
"clean_run_payloads": [receipts for _ in range(m01.MIN_CLEAN_REPLAY_RUNS)],
"restart_replay_payload": receipts,
```

— the same `receipts` object listed five times, plus the same object again as
the "restart" payload. The five-run and restart-replay gates are satisfied by
list construction, not by five executions or any restart. Byte-equality across
those five entries is guaranteed by Python object identity.

**Consequence for M14.** Two binding consequences:

1. M01 is **not** citable as SUT, durability, or capture evidence. It is a
   fixture-to-projection contract.
2. M01 is **not** citable as five-run or restart-replay precedent. Copying its
   shape would make M14's `pass^5` and replay requirements vacuous. This is the
   direct source of the seed-distinctness requirement in Section 10 and the
   M14-owned RED `R8` in Section 12.

**Smallest RED regression (owner).** Assert that the five entries of
`clean_run_payloads` are five **distinct objects produced by five separate
invocations** — minimally, that mutating the first entry does not change the
others, and that a run ledger records five distinct execution identities.
RED at base: the entries are one object.

---

#### Q2 — M03: the valid-time cell is unreachable from the public runner, and the registry does not disclose the asymmetry

**Owner:** public-harness integration owner (`eval/public/registry.json`,
`eval/public/runner.py`).

**Evidence (base `effc5e03`).**
`eval/public/adapters/whole_memory_reference.py` exports
`run_m03_valid_time_development`. `eval/public/scoring.py:score_profile`
dispatches `wmbs-m03-valid-time-v1` to `_score_wmbs_m03_valid_time`. The fixture
`eval/public/fixtures/wmbs-m03-valid-time-development.json` exists on disk.

But executing `load_registry()`, `runner._ADAPTERS`, and
`runner._PROFILE_CONTRACTS` at base yields:

- registry suites: `hipporag-2wiki`, `hipporag-hotpot`, `hipporag-musique`,
  `longmemeval-retrieval`, `pm-bench-development`, `qa-smoke`, `smoke`,
  `triggerbench-development`, `wmbs-m01-development`, `wmbs-m10-development`,
  `working-memory-action-development` — **no M03 entry**;
- `_ADAPTERS` keys cover `wmbs-m01-reference` and `wmbs-m10-reference` only —
  **no M03 adapter key**;
- `_PROFILE_CONTRACTS` covers `wmbs-m01-v1` and `wmbs-m10-v1` only — **no
  `wmbs-m03-valid-time-v1`**.

**Consequence for M14.** M03 has no pinned `dataset_sha256`, never passes
through either of `run_public_suite`'s digest re-checks, never emits a run
bundle, and is bound only by direct calls in
`tests/test_public_whole_memory_reference.py`. `eval/public/registry.json` — the
custody record — does not disclose the asymmetry. M03 is cited in this document
**only** as unit-level contract precedent, never as executable replay, custody,
or bundle precedent.

**Smallest RED regression (owner).** In
`tests/test_public_whole_memory_reference.py`, assert that every public
`run_m*_development` callable exported by
`eval.public.adapters.whole_memory_reference` is either present as a value in
`eval.public.runner._ADAPTERS` **or** named in an explicit, documented
`UNREGISTERED_CONTRACT_ONLY` constant carrying a one-line reason per entry.
RED at base for `run_m03_valid_time_development` and
`run_m15_composed_development`. It turns an undisclosed asymmetry into a
declared one without changing any measurement.

---

#### Q3 — M10: the calibration cell is also non-SUT, and its no-memory arm is a point floor, not a paired control

**Owner:** public-harness integration owner (`eval/public/wmbs_m10.py`,
`eval/public/scoring.py`); `src/mnemosyne/guard.py` for the inherited rail.

**Evidence (base `effc5e03`).** `run_m10_development(benchmark, _cli)` likewise
takes `_cli` and never uses it; under
`system_seam: "harness-owned-reference-core"` it runs
`m10.run_baseline("full-context", cases)` — a harness-side baseline, not the
Mnemosyne engine. Unlike M01 it does compute per case, so it is a real
deterministic computation; it is still not SUT evidence.

On the control arm: `m10.retrieve_no_memory` feeds
`useful_coverage_floor_from_fixture`, which returns the no-memory arm's
`useful_coverage` plus a fixed margin, and `_score_wmbs_m10` reports
`meets_useful_coverage_floor` as a scalar `>=` test against that floor. Its
interval is the literal `{"method": "descriptive"}`.
`src/mnemosyne/guard.py:no_degradation_guard` is likewise a scalar
`memory_score - no_memory_baseline` against a scalar `minimum_margin`.

**Classification.** Not a defect — a boundary. These components do exactly what
they claim. The defect would be citing them for more than they do.

**Consequence for M14.** Three binding consequences:

1. M10 is not citable as SUT evidence.
2. M10's no-memory arm may **not** be cited as precedent for M14's paired
   control. It is a baseline floor, not a paired difference estimator.
3. Because the `whole-memory-development` family is contractually
   descriptive-interval, an M14 cell admitted into that family **cannot** carry
   the paired confidence-interval lower bound its acceptance requires. M14's
   acceptance is therefore structurally undeliverable at the development tier.
   Recorded as a claim boundary in Section 11 and pinned in Section 10.

---

#### Q4 — M12: the action fixtures are one-seed and near-trivial, recurrence is metadata only, and lateness is an inert-looking binary counter

**Owner:** public-harness integration owner (`eval/public/fixtures/`,
`eval/public/adapters/pm_bench_triggerbench.py`, `eval/public/README.md`).

**Evidence (base `effc5e03`).** `eval/public/README.md` discloses, and the
fixtures confirm:

- `pm-bench-development`: **one seed (`7`), one case**, five tasks, seven steps.
- `triggerbench-development`: **one seed (`7`), twenty one-step cases**, and
  **no calibrated baseline**.
- "Recurrence is represented in fixture metadata but is **not forwarded as
  production recurrence plumbing**."
- "Lateness is scored only as a binary `late` safety counter, which is **zero on
  both committed fixtures because they are easy rather than because the counter
  is inert**; neither suite measures lateness magnitude or cost."

**Classification.** Disclosed development gaps, not hidden defects. The README
is honest. The quarantine exists because the disclosure lives in prose and does
not travel with the metrics.

**Consequence for M14.** M12 is citable as precedent for the **authenticated
action seam and fail-closed scorer discipline** (`_bind_action`'s duplicate/
missing-ID, category-mismatch, operating-point, and gold-leakage rejections) and
for the honest-disclosure style M14's README paragraph must follow. It is **not**
citable as precedent for multi-seed reliability, recurrence semantics, latency/
lateness measurement, or a calibrated baseline. A zero safety counter on an easy
fixture is not evidence that the counter fires.

**Sibling note.** M13 (`working-memory-action-development`) carries the same
class of disclosed limits — one seed (`94125`), six cases, no capacity parameter
in the operating point, and no promotion-versus-no-promotion control — and is
subject to the same restriction.

**Smallest RED regression (owner).** Assert that each deterministic-action
suite's emitted metrics object carries a machine-readable
`development_limits` block (seed count, case count, control presence, and the
counters that are structurally unexercised on the committed fixture), and that
its values equal the README's disclosure. RED at base: the disclosure exists
only in prose.

---

#### Q5 — M15: unregistered, and `replay_protocol` is a self-asserted declaration that nothing executes

**Owner:** public-harness integration owner
(`eval/public/schema/wmbs-0.1-draft.schema.json`,
`eval/public/adapters/whole_memory_reference.py`, `eval/public/README.md`).

**Evidence (base `effc5e03`), part 1 — unreachable.** As with Q2,
`run_m15_composed_development` has no registry entry, no `_ADAPTERS` key, and no
`_PROFILE_CONTRACTS` key.

**Evidence, part 2 — self-assertion.** `$defs.replay_protocol` requires
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
constants and the tests asserting those constants are frozen
(`test_m15_replay_protocol_is_frozen`).

**Classification.** Pass-without-execution. The schema pins the *claim*; no
code pins the *fact*. The round record is honest about this; the README
sentence, read alone, is not. Q1 is the same failure at the payload level.

**Consequence for M14.** M14's repeat/replay requirement must be enforced by an
executed run ledger whose length, seed set, and process identity the validator
checks — never by a schema `const` and never by a repeated payload.

**Smallest RED regression (owner).** Build a `FeasibilityRecord` whose
`replay_protocol.run_count` and `clean_process_replay` are the frozen constants
but whose accompanying executed run ledger contains fewer than five entries and
records a single process identity, and assert `validate_evidence_bundle`
rejects it. RED at base: no ledger field is cross-checked, so the record
validates.

---

#### Q6 — MemoryAgentBench: the adapter consumes pre-scored cases and only aggregates them

**Owner:** public-harness integration owner
(`eval/public/adapters/memoryagentbench.py`).

**Evidence (base `effc5e03`).** `score_cases(cases)` requires each case to be
exactly `{"case_id", "competency", "score"}` and validates `score` only as a
finite number in `[0, 1]`. The `score` is an **input**. The function never
invokes an adapter, a SUT, or an environment; it groups by competency and
returns `{"count", "mean"}` per competency. `build_submission` wraps that in an
envelope with a 40-hex `dataset_revision` and a `protocol_id`. The module
docstring is accurate — "scoring and submission-envelope contracts" — but the
function name `score_cases` reads as if it scores.

**Consequence for M14.** MemoryAgentBench is **not citable by M14** for any
purpose: not as a scorer, not as an execution path, not as upstream comparability,
and not as evidence that a competency was measured. Any caller can supply
arbitrary conforming numbers and obtain a valid envelope. M14's scorer must
derive every value from observed episode state, never accept a supplied score.
This is independently reinforced by the lease map's `P13-O` row
(`EXTERNAL/PLAN BLOCKED`) and the spec's `BENCH-006` note that "MemoryAgentBench
and BEAM source work does not equal execution or results."

**Smallest RED regression (owner).** Assert that `score_cases` rejects a case
set whose scores are not accompanied by a run-identity reference binding each
`case_id` to an executed attempt — or, if the aggregation-only role is
intentional, rename the entry point to `aggregate_scored_cases` and assert the
module exports no symbol named `score_*`. RED at base under either form.

---

#### Q7 — Counterfactual replay and the protected-regression rail are substring-judged

**Owner:** engine/product owner (`src/mnemosyne/gate.py`,
`src/mnemosyne/self_optimization.py`). **Not** the public-harness owner, and not
an M14 lane.

**Evidence (base `effc5e03`).** `src/mnemosyne/self_optimization.py`
`_session_succeeds` decides whether a replayed session succeeded by:

```
rendered = "\n".join(getattr(hit, "text", "") for hit in result.hits)
return session.expected_substring.lower() in rendered.lower() and not getattr(result, "abstained", False)
```

— case-insensitive substring containment in the concatenation of retrieved hit
text. Its comment states this mirrors the promotion gate's criterion exactly.
`counterfactual_replay_score` is then `(after_successes - before_successes) /
total_cases`, a point difference with no interval.

The same criterion carries the protected rail: `src/mnemosyne/gate.py` defines
`RegressionCase` with `expected_substring` and `protected`, and `GateResult`
exposes `protected_regressions`, populated when a `protected` case fails that
substring test. `promoted = not protected_regressions and not failed and margin > 0`.

**Consequence for M14.** Two binding consequences:

1. Counterfactual replay is **not citable by M14** as a scorer, a paired
   control, or a replay contract. Substring containment in retrieved text is a
   proxy judge; M14 requires deterministic final-state assertions over terminal
   environment state.
2. M14's inherited "zero protected regressions" acceptance term depends on this
   suite. It is therefore **DEFERRED with no claim** (Section 11): M14 cannot
   assert zero protected regressions without executing a protected suite it
   does not own, whose pass criterion is a substring proxy, and which lives
   behind the engine/product owner's surface rather than the public harness.

**Smallest RED regression (owner).** Assert that a protected `RegressionCase`
whose `expected_substring` appears in retrieved text **only inside content the
retrieval layer marked untrusted or abstained-over** is scored as a failure,
not a pass. RED at base: the check is a flat substring test over concatenated
hit text with no provenance or trust condition.

---

#### Q8 — The whole-memory contract suite has an undeclared test-time dependency on the `mcp` extra

**Owner:** CI integration owner / dependency owner (`pyproject.toml`,
`.github/workflows/ci.yml`).

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
dependency, and the failure surfaces as a collection error rather than a
dependency error.

**Smallest RED regression (owner).** Declare `jsonschema` explicitly in
`[dependency-groups].dev` and assert its importability in an environment synced
with `--group dev` alone. RED at base.

---

## 6. Prerequisites frozen

M14 is admissible for implementation only when **all** of the following are
true on then-current `main`. This list is exhaustive and ordered.

| # | Prerequisite | Owner | Discharges |
|---|---|---|---|
| P1 | `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md` is recomputed from then-current `main` and its `U-MODULES` row no longer covers M14. | GoalEx lifecycle/integration owner | Scheduling authority (Section 7) |
| P2 | Section 6.3's `EpisodeManifest`, `Observation`, `ActionEnvelope`, `ActionReceipt`, `EpisodeReceipt` and the `reset`/`observe`/`act`/`finish_episode` request/response pairs are frozen in `eval/public/schema/wmbs-0.1-draft.schema.json`, and `ProtocolValidator` admits them with ordering, deadline, idempotency, and error-class semantics matching the six existing operations. | Public-harness integration owner | B1 |
| P3 | One deterministic task environment exists as a harness-owned reference core, seeded, with a frozen rule digest and deterministic final-state assertions, and it executes rather than synthesizing its outputs (Q1). | Public-harness integration owner, or a newly admitted M14 owner | B2 |
| P4 | An agent-loop model policy is preregistered with the same custody discipline `_qa_protocol` applies to the grounded reader — provider, selector, resolved content digest, decoding options, and role-template digests — **or** the M14 cell is explicitly restricted to a deterministic non-model policy and labelled as such. | Public-harness integration owner + operator | B4 |
| P5 | A paired-difference interval estimator exists, is unit-tested against known inputs, and is admitted into `score_profile`; and a family whose registry `interval_method` is not `descriptive` is available for M14. | Public-harness integration owner | B3, Q3 |
| P6 | Q1, Q2, Q4, Q5, and Q6 are dispositioned by the public-harness owner — either fixed or converted into declared, tested disclosures. | Public-harness integration owner | Q1, Q2, Q4, Q5, Q6 |
| P7 | A sandbox/metering receipt path exists for the episode environment, or the M14 cell is explicitly restricted to the in-process harness-owned seam with no entrant-supplied code, and labelled as such. Cost is claimable only after this holds (Section 10). | `SBOX` owner + operator | B2 (partial), cost |
| P8 | A protected regression suite is executable against the M14 SUT boundary, its pass criterion is stronger than substring containment (Q7), and its result is bound to the M14 attempt. | Engine/product owner + operator | Q7, the "zero protected regressions" term |

P1 is false at this base: the lease map reads
`Baseline: main@e157e0350c503c9cde4aca0eff71d643a4adb200` and carries `T4` as
`DELIVERING`, while `main` at the time this lane was cut was already `effc5e03`
and has since advanced to `2091d01c`. `GOAL.md`'s lapse rule fires: the
carve-out "lapses the moment any merge lands on `main` that the branch-resident
map does not already record, at which point the map must be recomputed from
current `main` before it is treated as operative again." Recomputation is the
GoalEx owner's, not this lane's.

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
This lease is **not claimed by this document** and confers nothing until P1–P8
hold.

### Stage A — M14-owned, disjoint from every current exclusive surface

| Path | Status | Purpose |
|---|---|---|
| `eval/public/wmbs_m14.py` | new | Harness-owned deterministic episode environment: frozen case/task dataclasses, per-seed generator, rule digest, final-state assertion evaluator, executed-run ledger, and the no-memory control arm. Structural analogue of `eval/public/wmbs_m10.py`; explicitly **not** the `perfect_*` synthesis pattern of `eval/public/wmbs_m01.py` (Q1). |
| `eval/public/adapters/wmbs_m14_task.py` | new | `run_m14_task_utility_development(fixture, cli)` adapter. **Must not** be added to `eval/public/adapters/whole_memory_reference.py`, which is an exclusive surface. |
| `eval/public/fixtures/wmbs-m14-task-utility-development.json` | new | Generated development fixture. |
| `tests/test_public_wmbs_m14.py` | new | M14 contract, generator determinism, seed distinctness, run-ledger, scorer, and failure-path suite. |

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
Stage A is Q2/Q5 again.

### Explicitly excluded from every M14 stage

`GOAL.md`; `.planning/`; `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`;
`tests/test_planning_traceability.py`; `.github/workflows/`;
`leaderboard/` and every result-v2 path; every signed-publication path;
`eval/public/sandbox.py`, `eval/public/sandbox/`, `tests/test_public_sandbox.py`;
every `T5` carve-out path; `eval/public/receipts/`;
`src/mnemosyne/gate.py` and `src/mnemosyne/self_optimization.py` (Q7).

---

## 9. Consumed and produced interfaces

### 9.1 Consumed

| Interface | Source | Binding |
|---|---|---|
| `RequestContext`, `ErrorEnvelope`, closed error enum | `wmbs-0.1-draft.schema.json` | Reused unchanged. `WholeMemoryValidationError.code` carries one of the nine closed codes. |
| `canonical_json` / `canonical_sha256` / `canonical_projection` | `eval/public/adapters/whole_memory_reference.py` | Reused for the M14 canonical payload and digests. |
| `canonical_replay_projection` / `canonical_replay_fixture_custody` / `canonical_replay_digest` | `eval/public/bundle.py` | Reused for replay custody, subject to Q5: the executed run ledger must be checked, not the schema `const`. |
| `AssetSpec` / `load_pinned_json_asset` | `eval/public/assets.py` | Reused only if M14 ever admits an external asset. The development cell admits none. |
| `harness-owned-reference-core` seam | `eval/public/runner.py` | M14's environment is harness-owned; the adapter receives `cli=None`. M14 must record that this seam is non-SUT, exactly as Q1/Q3 require of M01/M10. |
| `_bind_action` fail-closed discipline | `eval/public/scoring.py` | Reused as the pattern for M14's label/trace binding rejections. |
| `no_degradation_guard` | `src/mnemosyne/guard.py` | Inherited rail only. Not the paired-CI acceptance (Q3). |
| Section 6.3 agent ABI | **does not exist** | B1. Consumed only after P2. |
| MemoryAgentBench / BEAM adapters | `eval/public/adapters/` | **Not consumed.** Q6. |
| Counterfactual replay / protected regression suite | `src/mnemosyne/` | **Not consumed.** Q7; gated on P8. |

### 9.2 Produced

| Artifact | Shape |
|---|---|
| `wmbs-m14-task-utility-development` suite entry | `family: whole-memory-development`, **`interval_method: "descriptive"`** (Section 10), `admission_state: PROPOSED`, `license: CC0-1.0`, `split_role: development`, `system_seam: harness-owned-reference-core`, `track_kind: DEVELOPMENT`, `publishable: false`, `pbpp_headline_eligible: false`, `headline_eligible: false`, `independent_external_reproduction: false`, `upstream_comparable: false`, exact `dataset_sha256` and 40-hex `revision`. |
| M14 traces | One row per `(task_id, seed, arm)` carrying `case_id`, `scoring_family`, arm label (`memory` / `no-memory`), final-state assertion outcomes, procedure-compliance outcome, `turns`, `tool_calls`, and `tokens`. **No cost field** (Section 10.4). Entrant self-reported usage is disclosure only. |
| M14 executed-run ledger | One entry per executed run, carrying `task_id`, `seed`, `arm`, run index, process identity, and the canonical payload digest of that run. Length and seed-distinctness are checked, not declared (Q1, Q5). |
| M14 evidence | Canonical replay projection, rule digest, the full seed set, the executed-run ledger, exact gates, and the four false publication flags. |
| Development gap disclosure | A README paragraph in the M12/M13 style naming every deferred acceptance component, plus the non-SUT seam statement. |

### 9.3 Bounded trust inherited from the common ABI

`eval/public/adapters/whole_memory_reference.py` enforces, and M14 inherits
unchanged:

| Bound | Value |
|---|---|
| `_MAX_REQUESTS` | 10,000 requests per validator instance |
| `_MAX_REQUEST_BYTES` | 16 MiB per request |
| `_MAX_RESPONSE_BYTES` | 16 MiB per response |
| `_MAX_JSON_DEPTH` | 64 levels of JSON nesting |
| `_MAX_RETAINED_BYTES` | 64 MiB of retained canonical request bytes |

The validator additionally "performs no persistence, network, model, benchmark,
ranking, or publication work" (`eval/public/README.md`).

**Binding consequence for M14.** The episode budget frozen in each
`EpisodeManifest` — maximum turns, tool calls, and tokens — must be chosen so
that the **whole** episode set for one attempt fits inside these bounds:
every `reset`/`observe`/`act`/`finish_episode` call counts against the 10,000
request ceiling and the 64 MiB retention ceiling, and no single `Observation` or
`ActionReceipt` may exceed 16 MiB or 64 levels of nesting. An M14 fixture whose
task count multiplied by five seeds multiplied by two arms multiplied by
maximum turns exceeds 10,000 requests is inadmissible as specified and must be
reduced, not granted a raised bound. Because the validator does no persistence,
network, or model work, any M14 component needing those must live outside it and
is gated by P4/P7.

---

## 10. Fixture, scorer, and custody contract

### 10.1 Fixture and seeds

Repository-authored, CC0-1.0, generated by a committed deterministic generator
with a pinned `generator_id`/`generator_version`, a `fixture_sha256`
self-digest, and an explicit seed list.

**Five distinct seeds per task.** M14's reliability requirement is satisfied by
**five runs at five distinct seeds per task per arm**, never by five runs at one
seed. Under a deterministic environment, five runs at one seed are byte-identical
by construction, so `pass^5` would collapse to `pass@1` and carry no reliability
information at all. Q1 shows this failure already realised in the tree, where
five "clean run payloads" are one object repeated. The `DataSourceContract`
`seed_domain` array (`minItems: 1`, `uniqueItems: true`) is the custody record
for that seed set, and M14 must populate it with at least five entries.

**Determinism is a per-seed property only.** The determinism claim M14 may make
is: *for a fixed seed, a replay reproduces the canonical projection byte for
byte.* It is **not**: *all five runs of a task agree.* Cross-seed agreement is
the measured reliability result (`pass^5`), not a determinism guarantee, and it
must be free to be less than 1.0.

Task families follow the spec's four controls: repeated, structurally related,
novel, and unrelated. Local stateful support/travel/shopping-style tasks only.
Named `*-development`; never an upstream official benchmark name. No official
STATE-Bench or EvoMemBench adapter, pinned or otherwise.

### 10.2 Scorer

Deterministic final-state assertions over the environment's terminal state,
plus procedure compliance, `pass@1`, `pass^5`, turns, and tool calls.

- `pass^5` is computed over the **actual executed runs recorded in the ledger**,
  at five distinct seeds, and fails closed if fewer than five distinct
  `(task_id, seed, arm)` executions exist. It is never satisfied by a repeated
  payload (Q1) or a declared constant (Q5).
- Every scored value derives from observed episode state. No value may be
  accepted as a scorer input (Q6).
- Success is a final-state assertion, never substring containment in rendered
  text (Q7).
- The scorer fails closed on label/trace mismatch, duplicate or missing case
  IDs, arm mismatch, seed collision, missing ledger entries, and gold leakage
  into traces, matching the discipline in `_bind_action`.
- The secondary UX rubric is `DEFERRED`: it is a judged output and no judge is
  admitted here.

### 10.3 Interval method

The registry entry pins **`interval_method: "descriptive"`**, and
`_PROFILE_CONTRACTS["wmbs-m14-v1"]` must be
`("whole-memory-development", "descriptive")`. This is not a preference; it is
what `load_registry()` enforces for the `whole-memory-development` family, and
what `_score_wmbs_m10` already returns for its sibling. **Any other interval
method requires P5 and a new family**, and until both exist M14 reports point
values with a descriptive interval and makes no inferential claim.

### 10.4 Cost

**Cost is absent or explicitly `null` in the development cell.** M14 emits no
cost figure, and no M14 metric is denominated in cost. The spec lists cost among
M14's scorer outputs, but a cost figure requires harness-owned metering across
the declared SUT boundary (Section 6.5), which is exactly what P7 gates. Until
P7 holds there is no metered source for a cost value, and a self-reported or
estimated one would be disclosure dressed as measurement. Cost becomes
claimable only after P7, and remains `DEFERRED` in Section 11 until then. This
supersedes any reading of Section 9.2 that would place a cost field in the
traces.

### 10.5 Custody, licence, and BOM

Fixture and generator are repository-authored CC0-1.0. No external asset,
protected dataset, or upstream corpus. No paid provider. If P4 admits a model
policy, its custody must bind provider, selector, resolved content digest,
decoding options, and role-template digests exactly as `_qa_protocol` does.
Logs redact secrets and direct personal data per Section 6.5.

The M14 `DataSourceContract` uses `source_kind: "deterministic-synthetic"`, a
`seed_domain` carrying the five-per-task seed set, and `golden_fixture_refs`
digest references.

The M14 entry in `SoftwareDataBOM.datasets` must carry **all twelve mandatory
`dataset_item` fields**, none omitted and none empty:

| Field | M14 value |
|---|---|
| `name` | `wmbs-m14-task-utility-development` |
| `declared_license` | `CC0-1.0` |
| `concluded_license` | `CC0-1.0` |
| `redistribution` | `allowed` |
| `lineage` | The committed generator's module path, `generator_id`, `generator_version`, and content digest — sufficient to regenerate the fixture. |
| `modifications` | `none` — generated, not derived from an upstream corpus. |
| `attribution` | Repository-authored; no upstream attribution required. |
| `pii` | `none` |
| `consent_basis` | Not applicable — wholly synthetic, no data subject. |
| `privacy_scan` | `not-applicable`, or `passed` if a scan is run. |
| `retention` | Retained in-repository for the life of the cell. |
| `takedown` | Repository-owned; removal is a repository change. |

`lineage` is the load-bearing field here: it must name the deterministic
generator precisely enough that regenerating from it reproduces the fixture
digest. That is what RED `R9` checks.

---

## 11. Claim boundary

### PROPOSED — a future admitted lane may honestly claim these

- The M14 adapter, fixture, and scorer contracts as **contract shapes**.
- Fixture generator determinism and self-digest custody.
- Deterministic final-state assertion outcomes on the committed development
  fixture.
- Procedure-compliance outcomes and harness-measured turn and tool-call
  counters.
- Simulator seed set and rule-digest retention.
- Per-seed replay equality of the canonical projection, stated at exactly the
  run count, seed set, and process discipline actually executed and recorded in
  the ledger.
- `admission_state: PROPOSED`, `publishable: false`,
  `pbpp_headline_eligible: false`, `independent_external_reproduction: false`,
  `upstream_comparable: false`.

### DEFERRED — no lane may claim these under this plan

- Any improvement claim versus no-memory. The paired confidence-interval lower
  bound above zero does not exist (B3, Q3).
- Any no-degradation claim on unrelated/novel tasks stated as an interval lower
  bound at least zero. Only the inherited point-estimate rail exists.
- **Zero protected regressions.** M14's acceptance inherits this term, and M14
  cannot claim it. The protected suite lives behind the engine/product owner's
  surface (`src/mnemosyne/gate.py`), its pass criterion is case-insensitive
  substring containment in concatenated retrieved hit text rather than a
  deterministic assertion (Q7), and no protected suite is executable against an
  M14 SUT boundary. **No claim, in either direction** — M14 asserts neither zero
  protected regressions nor their absence, and records the dependency as
  unmet. Gated on P8.
- `pass^5` reliability, until five runs at five distinct seeds per task per arm
  are executed and counted from the ledger (Q1, Q5).
- **Cost.** Absent or `null` in development; gated on P7 metering (Section 10.4).
- The secondary UX rubric.
- Official STATE-Bench and EvoMemBench variants — `DEFERRED` in the spec, and
  their simulator/model contracts are unpinned. MemoryAgentBench and BEAM
  supply no execution evidence (Q6).
- Every `official_local`, `hosted_service`, and `production_operations`
  feasibility disposition. `DEFERRED` in all three.
- Any resource receipt, sandbox receipt, smoke receipt, or `PILOT-READY-DEV`
  label, until P3/P4/P7 hold.
- Any inferential interval, until P5 and a non-descriptive family exist
  (Section 10.3).
- Any ranking, certification, superiority, launch-readiness, publication,
  leaderboard, or result-v2 statement.

M14's `feasibility_disposition.development` remains **`DEFERRED`** at this base
and does not move to `PROPOSED` until P1–P8 hold. This document does not move
it.

---

## 12. RED/GREEN checks for the future lane

Every check is RED at base; none may be written before its prerequisites hold.
Ownership is marked, because six of these belong to surfaces an M14 lane
cannot lease.

| # | Owner | RED test | GREEN condition |
|---|---|---|---|
| R1 | public-harness | `ProtocolValidator` rejects a `reset` request as `UNSUPPORTED_OPERATION`. | After P2, `reset(EpisodeManifest)` validates and returns a schema-valid `Observation`; an out-of-order `act` before `reset` is `ORDER_VIOLATION`; `finish_episode` with an unresolved in-flight `act` is rejected exactly as `finalize` is today. |
| R2 | **M14** | `wmbs_m14.generate_fixture()` does not exist. | Two invocations at a fixed seed produce byte-identical canonical JSON; `fixture_sha256` equals the canonical digest of the fixture with that field omitted; and the fixture declares at least five distinct seeds per task. |
| R3 | **M14** | Per-seed replay determinism: two `reset`→scripted-action→`finish_episode` sequences **at the same seed** diverge. | Byte-identical `EpisodeReceipt` canonical projections for that seed, and a stable rule digest. This asserts determinism **per seed only**; it must not assert agreement across different seeds, which is the measured `pass^5` result and is free to be below 1.0. |
| R4 | **M14** | `score_profile("wmbs-m14-v1", ...)` raises `unknown scoring profile`. | Returns final-state accuracy, procedure compliance, `pass@1`, `pass^5`, turns, tool calls, `family`, `profile`, `profile_version`, and `total`, with **no cost field**, and fails closed on arm mismatch, duplicate case IDs, seed collision, and gold leakage. |
| R5 | public-harness | `load_registry()` raises for a `wmbs-m14-task-utility-development` entry (no `_PROFILE_CONTRACTS` key). | Entry loads with `interval_method: "descriptive"`; the recomputed normalized digest equals the pinned `dataset_sha256` under both of `run_public_suite`'s checks. |
| R6 | public-harness | A `run_count: 5` / `clean_process_replay: true` declaration validates against an executed ledger of length 2 with one process identity. | The validator rejects the mismatch. **Q5's regression.** |
| R7 | public-harness | No paired-difference estimator exists. | Given synthetic paired arms with a known difference, the estimator returns the analytically expected point estimate and a lower bound whose sign is correct at a fixed seed. |
| R8 | **M14** | The scorer accepts a task whose ledger holds fewer than five executed runs, or five runs sharing one seed, or five references to one payload object. | The scorer **fails closed** in all three cases: it requires at least five ledger entries per `(task_id, arm)` at five **distinct** seeds, each with its own execution identity and its own canonical payload digest, and it computes `pass^5` from those actual executed runs rather than from a declared `run_count`. This is the direct M14-owned counterpart to Q1 and Q5. |
| R9 | **M14** | No lineage check exists on the M14 BOM entry. | The M14 `SoftwareDataBOM.datasets` entry carries all twelve mandatory `dataset_item` fields, non-empty; and regenerating the fixture from the deterministic generator named in `lineage` — at its recorded `generator_id`, `generator_version`, and content digest — reproduces `fixture_sha256` byte for byte. A lineage string that does not permit that regeneration fails. |
| R10 | public-harness | `score_cases` accepts caller-supplied scores with no execution binding. | Q6's regression, in whichever of its two forms the owner chooses. |
| R11 | engine/product | A protected `RegressionCase` passes on substring containment inside untrusted or abstained-over content. | Q7's regression. Gates P8. |

**First concrete test decision.** `R2` —
`tests/test_public_wmbs_m14.py::test_generate_fixture_is_byte_identical_at_a_fixed_seed_and_declares_five_distinct_seeds_per_task`.
It is the only check in the table that depends on no unmet prerequisite except
the lane's own admission: it needs neither the agent ABI (P2), nor a model
policy (P4), nor the paired estimator (P5), nor metering (P7), nor the
protected suite (P8). It is therefore the correct first RED test whenever M14
is admitted, and it pins the seed-distinctness property that Q1 shows the
repository currently gets wrong — before any code can inherit that mistake.

---

## 13. Integration order

1. **Stage 0 — GoalEx owner.** Recompute the lease map from current `main`
   (P1). Without this, no admission is valid.
2. **Stage 1 — public-harness owner.** Freeze the Section 6.3 agent ABI in the
   schema and `ProtocolValidator` (P2). Shared-protocol package; not
   M14-specific.
3. **Stage 2 — public-harness owner.** Disposition Q1, Q2, Q4, Q5, and Q6 (P6).
   Doing this before M14 exists prevents a third stranded cell, a third
   self-asserted replay claim, and a fourth tautological five-run gate.
4. **Stage 3 — M14 lane, Stage-A lease.** Deterministic environment, generator,
   five-seed fixture, executed-run ledger, adapter, tests. RED-first from R2,
   then R8.
5. **Stage 4 — public-harness owner.** Paired estimator and non-descriptive
   family (P5), then scorer dispatch, `_PROFILE_CONTRACTS`, `_ADAPTERS`,
   registry entry, README disclosure.
6. **Stage 5 — operator.** Model policy (P4), sandbox/metering disposition and
   cost enablement (P7), and protected-suite executability (P8), or the
   explicit restriction labels those prerequisites permit.
7. **Stage 6.** Development-tier evidence at `PROPOSED` only, with every
   Section 11 `DEFERRED` item stated as deferred.

Stages 1, 2, 4 serialize on the public-harness owner's single-writer rule.
Stage 3 is the only stage an M14 lane owns. Stage 5's P8 additionally requires
the engine/product owner, who is a third distinct writer.

---

## 14. Ponytail compliance

- No new runtime dependency. The Stage-A lease is stdlib-only and reuses the
  existing canonical-JSON, digest, custody, bundle, and seam contracts.
- No speculative abstraction. No generic "environment framework" is proposed;
  one deterministic environment, mirroring `wmbs_m10.py`'s shape and explicitly
  avoiding `wmbs_m01.py`'s synthesis shape.
- Smallest change: at this base the smallest correct action for M14 is **no
  code**. The plan says so rather than manufacturing a stranded artifact.

---

## 15. Validation performed by this lane

- **Revision pass (this commit).** Nine independent-review findings were
  reproduced against the tree before being applied; none was accepted on
  assertion. Reproduction notes: the `pass^5` tautology is not merely possible
  but already realised at `eval/public/adapters/whole_memory_reference.py`
  where `clean_run_payloads` is one object repeated five times against
  `wmbs_m01.MIN_CLEAN_REPLAY_RUNS = 5` (Q1); the ABI bounds were read from the
  enforced constants `_MAX_REQUESTS`/`_MAX_REQUEST_BYTES`/`_MAX_RESPONSE_BYTES`/
  `_MAX_JSON_DEPTH`/`_MAX_RETAINED_BYTES` rather than from prose; the twelve
  `dataset_item` fields were enumerated from the schema `required` array; the
  MemoryAgentBench and counterfactual/protected findings were confirmed at
  `memoryagentbench.score_cases` and `self_optimization._session_succeeds`
  respectively.
- **Baseline suite receipt (previous commit, read-only, no artifact retained).**
  Under the CI environment `uv sync --locked --extra mcp --group dev`,
  `uv run --locked python -m pytest tests/test_public_whole_memory_reference.py
  tests/test_public_wmbs_m01.py tests/test_public_wmbs_m10.py
  tests/test_public_working_memory_action_probe.py
  tests/test_public_pm_bench_triggerbench.py -q` exits 0 at `effc5e03`. The same
  invocation under `--group dev` alone fails at collection, which is Q8's
  evidence. Development operability observation only; not a benchmark run, a
  measurement, or evidence for any claim. Not re-executed for this
  documentation-only revision.
- **This revision:** lightweight plan and traceability checks only
  (`tests/test_planning_traceability.py`), no broad suite.
- Markdown: single H1, ordered heading levels, closed fenced blocks, balanced
  tables.
- Diff scope: exactly one modified file,
  `docs/plans/wmb-m14-procedural-task-utility-implementation-plan.md`. No other
  path in the working tree was modified, staged, or removed. No rebase, no
  push, no pull request.
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
