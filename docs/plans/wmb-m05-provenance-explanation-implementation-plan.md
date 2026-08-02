# WMB M05 — Provenance and Explanation: Exact Implementation Contract

**Date:** 2026-08-01

**Status:** `PROPOSED` — planning artifact only. This document authorizes no
code, no fixture, no benchmark execution, no measurement, no admission-state
change, and no publication.

**Base:** all source inspection in this document was performed at
`origin/main@effc5e039505c09e575ca5e4aeb2b96949676366` (worktree
`Mnemosyne.codex-wmb-m05-plan`, branch `codex/wmb-m05-plan`, clean at plan
time).

**Base drift — acknowledged, not repaired here.** `origin/main` has since
advanced to `2091d01c8cea22da49a50bb1f0859d8108102f29` (PR #94, the T5 lifecycle
carve-out lapse delivery, which also changed the lease map and added a canonical
baseline-ancestry CI check). This document therefore describes `effc5e03`, not
current `main`. That does not invalidate any finding below — every quarantine
concerns `eval/public/**`, `src/mnemosyne/**`, and the frozen ABI, and PR #94 is
a lifecycle/CI delivery — but it does mean **every §2 asset validation and every
§3 quarantine must be re-verified against the then-current base before Stage A
begins**, exactly as P2 already requires for the lease map. No claim in this
document may be treated as current-head-bound without that re-verification.

**Lane lease (this document):** exactly
`docs/plans/wmb-m05-provenance-explanation-implementation-plan.md`. No other
path in this repository is written by this lane.

**Author scope:** convert the M05 module feasibility specification into an exact,
adversarially validated implementation contract that a later, separately
admitted lane can execute without re-deriving prerequisites. Producing this
contract is the artifact that the dependency map's `U-MODULES` row names as the
precondition for M05 code; it is not itself an admission of that code.

---

## 0. Authority

Resolved in this order. Where this document conflicts with anything above it,
the affected item is `DEFERRED-CONFLICT` and no implementer may pick the easier
rule.

| Precedence | Source | Retained authority |
|---|---|---|
| 1 | `docs/blueprint/Mnemosyne-v2-Build-Blueprint.md`, `.planning/PROJECT.md` | Product architecture, invariants, trust boundaries |
| 2 | `.planning/STATE.md`, `.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md`, `.planning/MILESTONES.md`, `GOAL.md` | Status, dependencies, milestones, leases |
| 3 | `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md` **as it stands on current `main`** | Admission, exact leases, concurrency |
| 4 | `docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md` §6, §8 (M05), §9, §10, §11 | Module contract, ABI, rails, anti-gaming, rights |
| 5 | `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md` | Pilot task shape and delivery-checkpoint discipline |
| 6 | `eval/public/` implemented bundle, `leaderboard/` result-v1 semantics | Behavior of the exact code they produce |
| 7 | This document | M05 prerequisites, interfaces, fixture, scorer, lease, RED/GREEN ladder |

**Governing spec facts, quoted verbatim from §8 M05 and not re-litigated here.**
M05's contract is `query_with_evidence` **or** optional `evidence_ids` in the
answer envelope; systems with neither are `unsupported`. Its data is
deterministic claims requiring one or more source events, distractors, derived
claims, and tampered lineage records. Its scorer is citation precision/recall,
claim coverage, unsupported-claim rate, lineage tamper detection, and
explanation consistency. Its acceptance is `M-PROV-COMPLETE=1.0`,
`M-EXPLAIN-COV=1.0`, zero unsupported claims on the protected slice, and 100%
rejection of tampered lineage, with citation precision/recall remaining a
diagnostic on non-protected material. Its repeat/replay is at least five seeds
with a retained source manifest and citation order not affecting set metrics.
Its disposition is `PROPOSED` for citation/lineage scoring and `DEFERRED` for
explanation-faithfulness scoring. **M05 is not in the first pilot** and its
placement is advanced public certification.

### 0.1 Hard exclusions

This plan and every lane it later authorizes must avoid, and must not
speculatively prepare for: official or protected-suite attempts; publication,
leaderboard, certification, superiority, or headline claims; `result-v2` and
every `leaderboard/` path; the development sandbox (`SBOX`) and any OCI
isolation path; signed publication and signing keys; and all T5 paths. The M05
spec's "signed source manifest retained" requirement is therefore satisfied in
Stage A by an **unsigned, content-addressed** source manifest only, and signing
is `DEFERRED` behind the protected signed-publication lease (§14, D6).

---

## 1. Verified baseline and evidence custody

Everything asserted below was read from this worktree at the base SHA. Custody
of that evidence is stated honestly and is not upgraded by restatement.

| Evidence | What it is | Custody label |
|---|---|---|
| File/AST reads of `eval/public/**`, `src/mnemosyne/**`, `tests/**` at base SHA | Direct inspection of current-main-bound source | **Reliable** for structure and control flow |
| Recomputed `dataset_sha256` for `wmbs-m01-development` and `wmbs-m10-development` over `runner._canonical(fixture)` | Both matched the committed registry values exactly | **Reliable**; recomputed at base SHA, not quoted from a report. This was a one-off *verification-time* use of a private helper by this planning lane; the M05 module must **not** import it (§5, §6) |
| Local run of `tests/test_public_wmbs_m01.py`, `tests/test_public_wmbs_m10.py`, `tests/test_public_whole_memory_reference.py` at base SHA — exit 0 | Focused suites pass on the exact current head | **Development-local only.** No CI run id, no workflow receipt, no signed custody. It is *not* a publishable green and *not* a substitute for exact-head CI |

**Integrity rule inherited and binding on every later M05 stage:** a historical
green report is non-publishable and non-citable as evidence unless an
exact-current-head rerun **plus** custody bind it. No M05 stage may cite a prior
run id, a prior report, or this document's local run as proof of anything beyond
"these suites executed and returned 0 at this SHA on a developer host."

---

## 2. Adversarial asset validation

Each asset the M05 plan would otherwise cite was tested against the claim
"this exercises the behavior M05 needs, and is current-main bound." Assets are
**not** edited by this lane.

| Asset | Claimed reusable behavior | Verdict |
|---|---|---|
| `eval/public/schema/wmbs-0.1-draft.schema.json` `$defs.answer_envelope` | Frozen `evidence_handles` carrier for M05's `evidence_ids` contract | **PARTIAL** — carrier exists and is `required`; it enforces none of M05's rails. See Q1, Q2, Q4 |
| Same, `$defs.retrieval_hit.provenance_status` | Per-hit provenance verification signal | **REJECTED as a scorer input** — self-declared, unbound. See Q3 |
| Same, `$defs.replay_protocol` | M15 `m15-v1` canonical replay contract | **PARTIAL** — the *shape* is frozen and constant-pinned; the *binding* to real artifacts is absent. See Q7 |
| `eval/public/registry.json` M01/M10 cells + `runner.py` two-sided digest gate | Fixture integrity is enforced, not decorative | **VALIDATED** — digest checked pre-adapter on input and post-adapter on the returned benchmark; both recomputed and matched at base SHA |
| `eval/public/adapters/whole_memory_reference.py::run_m03_valid_time_development` | Custody/label gate + canonical-matrix gate with negative tests | **VALIDATED as a pattern** — nine-field label gate and matrix gate, each with parametrized rejection tests. This is the pattern M05 copies |
| `run_m01_development`, `run_m10_development` | Reference cells that exercise a system under test | **REJECTED as behavioral evidence** — they synthesize traces and ignore the supplied CLI. Usable only as deterministic oracles. See Q5 |
| `eval/public/bundle.py::_CANONICAL_REPLAY_SEEDS`, `canonical_replay_digest`, `CANONICAL_REPLAY_VOLATILE_FIELDS` | Seed-matrix and volatile-field discipline | **VALIDATED as a pattern**, **QUARANTINED as evidence** (Q7) |
| M12/M13 cells (`pm-bench-development`, `triggerbench-development`, `working-memory-action-development`) and their registry rows | Reusable fixture/replay contract | **QUARANTINED** — registry `revision` pins may be stale; must be re-verified and re-bound before any reuse. See Q6 |
| `mnemosyne.ids.evidence_cid`, `eval/public/custody.py::capture_cid` | Content-addressed evidence identity → tamper detection primitive | **VALIDATED, PROVISIONAL** — the CID is genuinely derived from content plus `{tenant_id, source_type, content_pointer, modality}` (and `user_id` when `sensitivity >= 2` or PII is detected), so content mutation changes the CID. Reuse is provisional pending Q8 |
| `mnemosyne.answering._strict_source_cids` and the projection-provenance set-equality check | Rejects a hit whose `provenance` and `source_evidence_cids` disagree | **VALIDATED, PROVISIONAL** — real algebraic check; reachable only on the grounded-answer path, which is not model-free (Q9) |
| `mnemosyne.consolidation._load_evidence` → `(evidence, missing)` | Dangling-CID detection exists | **VALIDATED, PROVISIONAL** — detects unresolvable CIDs; does not verify that a resolvable CID still matches its content |
| `mnemo answer` / `CommandGroundedProvider` | Claim-level, span-level grounded citations | **NOT A STABLE LOCAL INPUT** — requires external role commands and preregistered model digests. See Q9 |
| HowProvenance / provenance-algebra surface | Semiring lineage over derived claims | **EFFECTIVELY UNWIRED** — no reachable production path binds it to the public evaluation surfaces. See Q10 |
| M05 benchmark fixture, scorer profile, bundle seed entry, registry cell | — | **DO NOT EXIST.** There is no `wmbs-m05-*` fixture, no `wmbs-m05-*` scoring profile, no `_CANONICAL_REPLAY_SEEDS` entry, and no registry cell anywhere on current main |

---

## 3. Quarantine register

Each quarantine records a defect or a limit in an asset this lane may not edit,
plus the **smallest RED regression** that a later, correctly leased lane must
write to pin it. A quarantine is discharged only by that RED test going GREEN
against a real fix authored by the asset's owner — never by restating it.

**Q1 — `query_with_evidence` is not in the frozen ABI.**
The advanced-hook list names `query_with_evidence(question)` as M05's primary
contract, but `wmbs-0.1-draft.schema.json` `$defs` contains no
`query_with_evidence` request/response definition and no capability-hook
declaration definition at all. An adapter therefore cannot declare the hook
`native | emulated | unsupported` under the closed ABI, which §6.4 requires.
*Consequence:* M05 Stage A binds **only** to `answer_envelope.evidence_handles`.
Native `query_with_evidence` is `DEFERRED` (§14, D1).
*Smallest RED:* one test asserting that the schema exposes a hook-declaration
definition covering `query_with_evidence` with the three declaration states. It
fails today and must stay RED until the public-harness owner freezes the hook.

**Q2 — `answer_envelope` cannot express M05's grounding rail.**
`evidence_handles` is `required` but carries no `minItems`, and the envelope's
`oneOf` constrains only `answer_text` against `abstained`. A conforming envelope
may therefore assert a non-abstained claim with **zero** citations, or abstain
while citing evidence. Under `M-PROV-COMPLETE=1.0` and "zero unsupported claims
for the protected slice", the ABI validates exactly the envelopes M05 must fail.
*Consequence:* the rail lives entirely in the M05 scorer; ABI validity is never
evidence of grounding.
*Smallest RED:* two scorer tests — a non-abstained, schema-valid envelope with
`evidence_handles: []` on a protected-slice claim must score
`unsupported_claim_rate > 0` and `passed == False`; an abstained envelope
carrying evidence handles must be rejected as malformed by the M05 scorer.

**Q3 — `retrieval_hit.provenance_status` is self-declared and unbound.**
Nothing in the schema, runner, or bundle correlates `provenance_status:
"verified"` with any digest, evidence handle, or source record. An adapter that
hardcodes `"verified"` passes every check.
*Consequence:* the M05 scorer must **never** read `provenance_status`.
*Smallest RED:* a scorer test feeding a tampered lineage record whose hits all
declare `provenance_status: "verified"`; the tamper-detection metric must still
be `1.0` (tamper rejected), proving the scorer ignores the self-declaration.

**Q4 — evidence handles carry no digest binding.**
`evidence_handles` items are `identifier`-typed opaque strings. The schema
defines `digest_reference` (`name@sha256:<64hex>`) and uses it **widely** — it is
referenced from fifteen places across the ABI, including `modality_handle`,
build/artifact, and manifest surfaces. The gap is therefore not that the schema
lacks a digest idiom; it is that **`evidence_handles` specifically opted out of
it** and remain opaque `identifier`-typed strings. Evidence is the one lineage
surface the ABI leaves undigested. A tampered lineage record therefore yields a
byte-identical envelope.
*Consequence:* M05's gold fixture must carry its own `evidence_cid` and
`slice_sha256` bindings; tamper detection is scorer-side recomputation, never
envelope inspection.
*Smallest RED:* a scorer test where two distinct source contents produce the
same `evidence_handles` list; the scorer must fail closed on the digest
recomputation rather than accept the handle equality.

**Q5 — M01/M10 reference adapters synthesize traces; they do not execute the
supplied CLI.**
`run_m01_development` builds its traces from `wmbs_m01.perfect_receipts(...)`
and its `_cli` parameter is unused; `run_m10_development` runs the module's own
in-process `full-context` baseline and likewise ignores `_cli`. Only
`run_m03_valid_time_development` actually drives `MnemoCLI`.
*Consequence:* M01/M10 are admissible to M05 **only as deterministic oracles**
(fixture-shape, label-gate, and digest-discipline precedent). No M05 claim may
rest on them as executed-path evidence. M05's own adapter must drive the real
CLI, as M03 does.
*Smallest RED:* an M05 adapter test asserting that the adapter invokes the
supplied `MnemoCLI` — e.g. a CLI double that raises on first use makes the
adapter raise. A synthesizing adapter passes this test only by not synthesizing.

**Q6 — M12/M13 registry revisions may be stale.**
The M12/M13 cells carry 40-hex `revision` pins that `load_registry()` validates
for *shape* only; nothing validates that the pin still names the commit that
produced the fixture.
*Consequence:* no M05 stage reuses an M12/M13 fixture, replay contract, or
registry row until its `revision` and `dataset_sha256` are re-verified against
then-current main and re-bound.
*Smallest RED:* a contract test that recomputes each reused cell's canonical
digest and asserts equality with its registry `dataset_sha256`, and that fails
loudly rather than skipping when the fixture is absent.

**Q7 — M15 custody accepts well-formed but unbound hashes.**
The `replay_protocol` definition pins constants (`canonical_payload: "m15-v1"`,
`run_count: 5`, the volatile-field list, `artifact_digest: "sha256"`) and the
manifest keys `{bundle,fixture,generator}_manifest_sha256` are required to be
present and well-formed — but nothing binds those digests to the actual schema
file, generator source, emitted traces, or frozen fixture. Any syntactically
valid 64-hex string satisfies them.
*Consequence:* **M15 behavioral evidence is quarantined for M05.** M05 may reuse
the `m15-v1` canonical-payload *shape* and the volatile-field list, and must
compute its own digests over real bytes, but may not cite M15 replay as proof
that its own replay is sound until a real executed-path regression exists.
*Smallest RED:* an M05 replay test that mutates one byte of the M05 fixture and
asserts the recomputed `fixture_manifest_sha256` changes and the replay
comparison fails. A digest that is merely well-formed cannot pass it.

**Q8 — content-addressed evidence identity is reusable only provisionally.**
`evidence_cid` is genuinely content-derived, but its metadata envelope is
conditional: `user_id` enters the digest only when `sensitivity >= 2` or PII is
detected. Two records differing only in `user_id` at low sensitivity collide by
construction. This is a deliberate privacy property, not a bug — but it means
CID equality is **not** a universal identity proof.
*Consequence:* the M05 fixture must hold every protected-slice claim at a
sensitivity and shape where the binding it relies on is actually in the digest,
and must state that choice explicitly in the fixture.
*Smallest RED:* a fixture-contract test asserting every protected-slice source
record declares the sensitivity tier under which its CID binding holds.

**Q9 — the grounded-answer path is not model-free.**
`CommandGroundedProvider.from_environment()` requires
`MNEMOSYNE_QUERY_DECOMPOSER_COMMAND` and `MNEMOSYNE_GROUNDED_READER_COMMAND`
with `command` transport and preregistered selector plus content digests; the
`compact` variant requires `MNEMOSYNE_COMPACT_*` artifact digests. Neither is
available as a stable local input, and both would introduce a provider budget
and a judge-disclosure obligation.
*Consequence:* M05 Stage A must not depend on `mnemo answer`. Natural-language
claim-level citation scoring is `DEFERRED` with the model-backed reader (§14,
D2). Stage A binds to the model-free write/read provenance surfaces instead.
*Smallest RED:* an M05 adapter test run with a cleared environment allowlist;
the adapter must complete without any `MNEMOSYNE_GROUNDED_*` or
`MNEMOSYNE_COMPACT_*` variable set.

**Q10 — HowProvenance is effectively unwired.**
No reachable production path binds a provenance-semiring/HowProvenance
derivation to the public evaluation surfaces. Derived-claim lineage — M05's
"derived claims" data requirement — therefore has no implemented algebra to
score against.
*Consequence:* M05 Stage A scores **one-hop** claim→source grounding only.
Multi-hop derived-claim lineage and its algebra are `DEFERRED` (§14, D3), and
the fixture's derived-claim cases exist to pin the gap, not to score it.
*Smallest RED:* a fixture-contract test asserting every derived-claim case is
labelled `scored: false` with `deferral_reason: "howprovenance-unwired"`, so the
gap cannot be silently promoted into a score later.

**Q11 — promoted lessons lose trajectory evidence lineage.**
Promotion of a consolidated/promoted item does not carry the originating
trajectory's evidence lineage forward, so a promoted claim can present as
grounded while its lineage back to source events is severed.
*Consequence:* this is a **shared prerequisite**, not an M05-local defect. M05
cannot honestly score `M-PROV-COMPLETE` over any promoted-item slice until
lineage survives promotion. The promoted-item slice is `DEFERRED` (§14, D4).
*Smallest RED (shared, owned by the promotion path's owner, not by M05):* a
lineage-preservation test asserting that a promoted item's
`source_evidence_cids` is a superset of the originating trajectory's evidence
CIDs. M05's plan records this as a prerequisite edge; the M05 lane does not
write it.

**Q12 — a file-existence `skipif` converts a missing artifact into a green
skip.** `tests/test_public_whole_memory_reference.py` gates its ABI tests on a
`skipif` over schema/adapter file existence (`"ABI artifacts are RED"`). It is
inert at base SHA because both files exist, but the idiom turns deletion into a
silent pass.
*Consequence:* `tests/test_public_wmbs_m05.py` must not copy this idiom.
*Smallest RED:* a positive assertion that the M05 fixture and module paths
exist, failing rather than skipping when they do not.

---

## 4. Frozen prerequisites

Stage A may not begin until all of P1–P5 hold. P6–P8 gate Stage B only.

- **P1.** The dependency/write-lease map on **then-current `main`** admits an
  M05 node with the exact lease in §9. M05 sits in the map's `U-MODULES` row
  (`SPEC UNSTABLE`, "no artifact authorized", "no lease") and that row requires
  an approved exact plan, protocol, scorer, license/custody, and dependency
  placement before code. This document supplies the plan; **only the GoalEx
  lifecycle owner can supply the node.** This lane cannot and does not write it.
- **P2.** The map is recomputed from then-current `main` immediately before
  admission, and no dirty path, active writer, open PR, or branch-ancestry
  overlap touches the §9 lease or the §8 integration surfaces.
- **P3.** Exact-head CI is green on the then-current base, with a real run id.
  This document's local run (§1) does not satisfy P3.
- **P4.** The four M05 RED contracts of §10.1 — claim→source completeness,
  citation precision, unsupported-claim rate, and lineage tamper detection —
  are written and **failing** before any implementation byte is written. The
  authoritative audit conditions CODE-READY on exactly these four.
- **P5.** Quarantines Q1–Q4, Q7, Q9, Q10, and Q12 are carried into the M05
  module's own docstring and fixture labels verbatim, so that the gaps travel
  with the artifact rather than living only here.
- **P6 (Stage B).** The public-harness integration owner accepts the §8
  integration edge as a serialized package on their own lease.
- **P7 (Stage B).** Q6 is discharged for any M12/M13 asset actually reused.
- **P8 (Stage B).** Q1 is discharged, or Stage B ships with `query_with_evidence`
  explicitly declared `unsupported` in the M05 cell's disclosures.
- **P9 (gates D4 only, never Stage A or Stage B).** The Q11 shared
  trajectory-lineage RED regression is landed by the promotion path's owner and
  GREEN. Until then the promoted-item slice stays `DEFERRED` (§12, D4) and no
  M05 metric covers a promoted item. M05 does not write this test and cannot
  discharge it.

---

## 5. Consumed interfaces

All exact, all model-free, all present at base SHA. Nothing below is invented.

**From the repository (read-only, never modified by the M05 lane):**

| Interface | Exact surface | Use in M05 |
|---|---|---|
| Evidence identity | `mnemosyne.ids.evidence_cid(content, *, tenant_id, user_id, source_type, content_pointer, modality, sensitivity)` | Compute gold source CIDs; recompute for tamper detection |
| Evidence identity helper | `eval.public.custody.capture_cid(capture)` | Same, through the public-eval seam rather than the engine |
| Capture | `eval.harness.cli_driver.MnemoCLI.capture` / `.capture_batch` | Materialize source events and obtain their CIDs |
| Grounded write | `MnemoCLI.assert_fact(..., evidence_cids=Sequence[str], trust_tier=int, valid_from=...)` | Create claims bound to declared source CIDs |
| Grounded proposal | `MnemoCLI.propose(..., evidence_cid=str\|None)` | Distractor and low-support cases |
| Claim readback | `MnemoCLI.export(tenant)` — returns an `evidence` row set — and `MnemoCLI.search(...)`, whose hit metadata carries `source_evidence_cids` (`mnemosyne/retrieval.py`) | Read back each claim's declared source CIDs. **There is no `MnemoCLI.get`**; these two are the actually existing stable readbacks |
| Lineage read | `MnemoCLI.explain(tenant, query, branch=...)` → `MemoryTools.explain` → `engine.deep_search(...).to_dict()` | Retrieval-level lineage for the explanation-coverage metric |
| Tenant projection | `MnemoCLI.export(tenant)` | Retained source manifest input |
| Canonical serialization | **Module-local** `canonical_json` / `canonical_sha256` defined inside `eval/public/wmbs_m05.py`, matching the `wmbs_m01.py` and `wmbs_m10.py` precedent | Digest-stable byte form. M05 must **not** import `runner._canonical` or `bundle._canonical`: both are private helpers in shared-owner files, and importing them would contradict the module's stdlib-only, no-shared-internals promise. Byte-for-byte equality with the registry digest is asserted by test, not by shared import (§10.3) |
| Replay projection | `eval.public.bundle.canonical_replay_digest`, `bundle.CANONICAL_REPLAY_VOLATILE_FIELDS` | Shape and volatile-field discipline only — evidence quarantined by Q7 |

**From the frozen ABI (shape only, no new definitions authored by M05):**
`answer_envelope` — whose `required` set is exactly `abstained`,
`evidence_handles`, **`action_handles`**, and `adapter_metadata`, so every M05
envelope must emit `action_handles` (empty for this module, which takes no
actions) or fail schema validation —
`retrieval_envelope`/`retrieval_hit` (**excluding** `provenance_status`, Q3),
`portable_event` — whose `required` set is all seven of `event_id`, `content`,
`actor_label`, `event_time`, `ingestion_time`, `content_sha256`, and
`public_metadata` under `additionalProperties: false`, so every M05 source event
carries all seven or fails ABI validation (`valid_from`, `valid_to`, and
`modality_handle` remain optional and unused by M05) —
`ingest_status.evidence_handle`, `error_envelope` with the exact nine-code enum,
and `replay_protocol` constants.

**Explicitly not consumed:** `mnemo answer` and every `CommandGroundedProvider`
path (Q9); `retrieval_hit.provenance_status` (Q3); `runner._canonical` and
`bundle._canonical` (private helpers in shared-owner files); a `MnemoCLI.get`
readback, **which does not exist**; private validity tables; any `leaderboard/`
module; any sandbox path; any signing surface; any M01/M10 adapter output
treated as behavioral evidence (Q5).

---

## 6. Produced interfaces

**`eval/public/wmbs_m05.py`** — standalone, stdlib-only, deterministic. Mirrors
the `wmbs_m01`/`wmbs_m10` module shape (which is precedent for a *file layout*,
not for their synthesizing adapters, Q5).

```
MODULE_ID           = "M05"
FIXTURE_ID          = "wmbs-m05-provenance-development"
FIXTURE_SCHEMA_ID   = "wmbs-m05-provenance-development/fixture/0.1"
GENERATOR_ID        = "wmbs-m05-deterministic-generator"
GENERATOR_VERSION   = "1.0.0"
SEEDS               = (13, 29, 41, 59, 73)          # five seeds, distinct from M03's
PROTECTED_SLICE_ID  = "protected-grounding"
FINITE_CORPUS_DISCLOSURE: str
INTEGRATION_DEPENDENCIES: tuple[str, ...]           # carries Q1-Q4, Q7, Q9, Q10, Q12

class WmbsM05Error(ValueError)                      # base for every contract violation
canonical_json(value) -> bytes                      # module-local; wmbs_m01/m10 precedent
canonical_sha256(value) -> str                      # module-local; no shared-owner import
generate_fixture(seed: int) -> dict                 # deterministic, no I/O, no clock
validate_fixture(fixture: Mapping) -> Mapping       # label gate + canonical matrix gate
source_manifest(fixture: Mapping) -> dict           # unsigned, content-addressed
recompute_source_cids(fixture: Mapping) -> dict[str, str]
score(fixture: Mapping, traces: Sequence[Mapping]) -> dict   # pure; no engine import
```

`score` returns exactly:

```
{
  "metrics": {
    "M-PROV-COMPLETE":        float,   # 1.0 required on the protected slice
    "M-EXPLAIN-COV":          float,   # complete source CIDs + retrieval stages required
    "unsupported_claim_rate": float,   # 0.0 required on the protected slice
    "lineage_tamper_rejection": float, # 1.0 required
    "citation_precision":     float,   # diagnostic, non-protected material only
    "citation_recall":        float,   # diagnostic, non-protected material only
    "five_seed_canonical_replay": float,
  },
  "diagnostics": {...},
  "deferred": {"explanation_faithfulness": "...", "derived_claim_lineage": "...",
               "promoted_item_slice": "...", "query_with_evidence": "..."},
  "passed": bool,
  "profile": "wmbs-m05-v1",
  "disclosure": FINITE_CORPUS_DISCLOSURE,
}
```

`passed` is `True` only when all four provenance rails hold simultaneously and
`five_seed_canonical_replay == 1.0`. Citation precision/recall never contribute
to `passed` — they are diagnostics per §8 M05. Before scoring, the trace set
must contain exactly one trace for each of the 80 scored cases; the 20 deferred
derived-claim cases remain outside that required trace matrix.

**`eval/public/fixtures/wmbs-m05-provenance-development.json`** — see §7.

**`tests/test_public_wmbs_m05.py`** — see §10.

---

## 7. Fixture contract

Custody labels are **mandatory and gated**, copying the validated
`run_m03_valid_time_development` pattern (§2). The adapter raises on any
deviation, and each deviation has a parametrized rejection test.

```json
{
  "admission_state": "PROPOSED",
  "comparability": "proposed-non-comparable",
  "fixture_id": "wmbs-m05-provenance-development",
  "headline_eligible": false,
  "pbpp_headline_eligible": false,
  "independent_reproduction": false,
  "module_id": "M05",
  "publishable": false,
  "schema_id": "wmbs-m05-provenance-development/fixture/0.1",
  "track": "DEVELOPMENT",
  "upstream_comparable": false,
  "license": "CC0-1.0",
  "seeds": [13, 29, 41, 59, 73],
  "sensitivity_binding": { "protected_slice_sensitivity": 2, "reason": "Q8" },
  "slices": [ ... ],
  "source_manifest": { "signed": false, "reason": "signing deferred behind the protected lease" }
}
```

Five canonical slices, ordered and fixed. The slice-id tuple is the canonical
matrix; any reduction, reordering, duplication, or rename must raise.

| Slice id | Cases/seed | Purpose | Scored |
|---|---|---|---|
| `protected-grounding` | 4 | Claims each requiring ≥1 source event; the protected slice carrying `M-PROV-COMPLETE`, `M-EXPLAIN-COV`, and the zero-unsupported rail | Yes |
| `distractor-sources` | 4 | Plausible but non-supporting sources present in the corpus; drives citation precision as a diagnostic | Diagnostic only |
| `tampered-lineage` | 4 | Source content mutated after CID assignment; must be rejected 100% by digest recomputation, **not** by `provenance_status` (Q3) | Yes |
| `unsupported-claim` | 4 | Non-abstained claims with zero valid supporting sources; must raise `unsupported_claim_rate` (Q2) | Yes |
| `derived-claims` | 4 | Multi-hop derived claims; carried to pin the HowProvenance gap | **No** — `scored: false`, `deferral_reason: "howprovenance-unwired"` (Q10) |

Five seeds × five slices × four cases = 100 cases. Every case is generated by
`generate_fixture(seed)` with no clock, no randomness beyond the seed, no
network, and no filesystem read. Citation order must not affect any set metric;
the scorer sorts canonically before comparison. Each case carries
`retrieval_stages: ["lexical"]`, using the frozen local retrieval explain
channel value, and `M-EXPLAIN-COV` requires both complete source CIDs and that
surfacing-stage attribution.

Integrity: `dataset_sha256` over the module-local `canonical_json(fixture)`,
whose bytes a test asserts are identical to those the runner's canonicaliser
produces for the same object (§10.3), verified in both
directions exactly as the M01/M10 cells are (§2, VALIDATED). Committed fixture
bytes and generator output must be byte-identical.

---

## 8. Dependency edges and integration order

**Stage A — module, fixture, tests. Fully disjoint; no shared-owner file
touched.** Produces a self-contained, deterministic, model-free M05 core plus
its RED→GREEN ladder. Nothing is registered, nothing runs through
`eval/public/runner.py`, and no admission state changes anywhere.

**Stage B — harness integration. Serialized on the public-harness integration
owner's lease. Not in this lane's future lease and not authorized here.**
Ordered, because each step depends on the previous one:

1. `eval/public/schema/wmbs-0.1-draft.schema.json` — add the M05 fixture schema
   entry so the fixture validates against the closed ABI rather than only
   against the module's own gate.
2. `eval/public/adapters/whole_memory_reference.py` — add
   `run_m05_provenance_development(benchmark, cli)` that **drives the supplied
   `MnemoCLI`** (Q5) exactly as the M03 entry point does.
3. `eval/public/scoring.py` — dispatch `wmbs-m05-v1` to `wmbs_m05.score`.
4. `eval/public/bundle.py` — add `"wmbs-m05-provenance-development": (13, 29,
   41, 59, 73)` to `_CANONICAL_REPLAY_SEEDS`.
5. `eval/public/runner.py` — register `wmbs-m05-reference` in `_ADAPTERS` and
   `"wmbs-m05-v1": ("whole-memory-development", "descriptive")` in
   `_PROFILE_CONTRACTS`.
6. `eval/public/registry.json` — add the `wmbs-m05-development` cell. It must be
   **executable**, not merely well-labelled: `load_registry()` and the runner
   dispatch resolve the cell through `adapter`, `fixture`, `scoring_profile`,
   and `system_seam`, so all four are required alongside the custody fields.
   The complete cell is:

   ```json
   "wmbs-m05-development": {
     "adapter": "wmbs-m05-reference",
     "fixture": "fixtures/wmbs-m05-provenance-development.json",
     "scoring_profile": "wmbs-m05-v1",
     "system_seam": "harness-owned-reference-core",
     "license": "CC0-1.0",
     "family": "whole-memory-development",
     "interval_method": "descriptive",
     "split_role": "development",
     "track_kind": "ENHANCED-SUCCESSOR",
     "admission_state": "PROPOSED",
     "publishable": false,
     "headline_eligible": false,
     "pbpp_headline_eligible": false,
     "independent_external_reproduction": false,
     "upstream_comparable": false,
     "revision": "<exact 40-hex pin>",
     "dataset_sha256": "<verified digest>"
   }
   ```

   `load_registry()` rejects a non-40-hex `revision`, a non-64-hex
   `dataset_sha256`, and any `(scoring_profile, family, interval_method)` triple
   that disagrees with `_PROFILE_CONTRACTS`, so step 5 must land before this one.
7. `eval/public/README.md` — the M05 gap disclosure carrying Q1–Q4, Q7, Q9,
   Q10, Q12 in the same voice as the existing M12/M13 disclosures.
8. `tests/test_public_whole_memory_reference.py` — adapter/scorer contract tests.

**Registration is not optional.** The M03 cell is registered in `scoring.py`,
`bundle.py`, and the adapter but has **no `registry.json` cell**, so it never
passes through the runner's two-sided digest gate or `load_registry()`'s
revision-pin validation and is reachable only from tests. M05 must not
replicate that asymmetry: it either completes step 6 or it declares itself
test-only in its own README disclosure.

**Cross-lane prerequisite edges M05 does not own and must not write:** Q11
(lineage survival across promotion) and Q1 (ABI hook freeze).

---

## 9. Exact future write lease

The Stage A lane's lease is exactly these three paths. All three do not exist at
base SHA (verified) and none appears in any owner's exclusive surface list in
the dependency/write-lease map — the same structural position `wmbs_m01.py`,
`wmbs_m10.py`, and their test modules occupy.

```
eval/public/wmbs_m05.py                                    (new)
eval/public/fixtures/wmbs-m05-provenance-development.json  (new)
tests/test_public_wmbs_m05.py                              (new)
```

Nothing else. In particular the Stage A lane must **not** touch
`eval/public/{runner,scoring,bundle,registry.json,README.md}`,
`eval/public/adapters/**`, `eval/public/schema/**`,
`tests/test_public_whole_memory_reference.py`, **`eval/harness/cli_driver.py`**,
`src/mnemosyne/cli.py`, the rest of `src/**`, `GOAL.md`, `.planning/**`,
`docs/coordination/**`, `.github/workflows/**`,
`tests/test_planning_traceability.py`, or any `leaderboard/**` path.

`eval/harness/cli_driver.py` deserves explicit mention because M05 consumes
`MnemoCLI` heavily (§5) and the temptation to add a convenience readback there
is real. It is an **exclusive surface of the public-harness integration owner**,
alongside `src/mnemosyne/cli.py`. M05 must compose the methods that already
exist — `capture`, `capture_batch`, `assert_fact`, `propose`, `search`,
`explain`, `export` — and must not add, widen, or wrap a method on that class.
If M05 genuinely needs a readback that `MnemoCLI` does not expose, that is a
Stage B request to the public-harness owner, not a Stage A edit.

---

## 10. RED → GREEN ladder

Every RED test below must be written and observed **failing** before the
corresponding implementation exists. A test that has never been observed RED is
not evidence.

### 10.1 The four gating RED contracts (P4)

These four are the audit's explicit precondition for CODE-READY.

1. **Claim→source completeness.** Every protected-slice claim resolves to ≥1
   gold source whose recomputed `evidence_cid` matches the fixture binding.
   `M-PROV-COMPLETE == 1.0`; anything less fails.
2. **Citation precision.** On non-protected material with distractors present,
   `citation_precision` and `citation_recall` are computed as set metrics,
   invariant to citation order, and reported as **diagnostics** that cannot
   flip `passed`.
3. **Unsupported-claim rate.** A non-abstained, schema-valid claim with zero
   valid supporting sources yields `unsupported_claim_rate > 0` and
   `passed == False` (Q2).
4. **Lineage tamper detection.** Every `tampered-lineage` case is rejected by
   digest recomputation, at `1.0`, **while every hit declares
   `provenance_status: "verified"`** — proving the scorer ignores the
   self-declaration (Q3).

### 10.2 Quarantine-pinning RED tests

Q1 (hook declaration absent), Q2, Q3, Q4 (handle-collision fail-closed),
Q5 (adapter must invoke the supplied CLI), Q7 (one-byte fixture mutation
changes the manifest digest and fails replay), Q8 (protected-slice sensitivity
declared), Q9 (adapter completes with a cleared `MNEMOSYNE_*` environment),
Q10 (derived-claim cases labelled `scored: false`), Q12 (positive path-existence
assertions, never `skipif`).

Q6 and Q11 are **not** M05 tests — they are prerequisite edges owned elsewhere
(§8) and are recorded here so they are not silently absorbed.

### 10.3 Contract and custody RED tests

Label gate (each of the nine custody fields, missing and permissive variants,
parametrized, mirroring the validated M03 pattern); canonical-matrix gate (slice
reduction, reorder, duplication, rename); fixture/generator byte-identity;
`dataset_sha256` recomputation in both directions; five-seed canonical replay
with the frozen volatile-field set; citation-order invariance.

**Canonicaliser equality (B2).** One test asserts that the module-local
`canonical_json(fixture)` is byte-for-byte identical to the bytes the runner's
own canonicaliser produces for the same object, and that
`canonical_sha256(fixture)` equals the registry `dataset_sha256`. The test — not
a shared private import — is what keeps the two canonicalisers in agreement, so
the module keeps its stdlib-only, no-shared-internals promise while any future
divergence fails loudly instead of silently producing a mismatched digest.

### 10.4 GREEN definition for Stage A

Stage A is GREEN when: every §10.1 and §10.2 test passes against the real
implementation; `tests/test_public_wmbs_m05.py` runs with zero skips and zero
xfails; the module imports no engine internals and reads no private validity
table; the fixture round-trips byte-identically through
`generate_fixture`; and the run is reproducible in a clean process with a
cleared environment. Stage A GREEN is **development-local evidence only** — it
is not a measured receipt, not a resource receipt, not CI, and not publishable
(§1 integrity rule).

---

## 11. Custody, license, and rights constraints

- Fixture license `CC0-1.0`; content is synthetic and generator-derived. No
  official, upstream, protected, or licensed corpus is read, adapted, or
  referenced. M05 never uses an official suite name.
- The retained source manifest is content-addressed and **unsigned**. Signing is
  deferred behind the protected signed-publication lease and is out of scope.
- Every artifact carries `PROPOSED` / `publishable: false` /
  `headline_eligible: false` / `pbpp_headline_eligible: false` /
  `independent_external_reproduction: false` / `upstream_comparable: false`, and
  the adapter raises if any is missing or permissive.
- Resource ceilings are planning hypotheses only. M05 emits **no** resource
  receipt and claims **no** admitted profile; the §8 M05 "measured admission
  receipt" prerequisite stays open.
- No secret, credential, key, token, personal datum, or host path enters the
  fixture, the module, or the tests.

---

## 12. Claim boundary

### PROPOSED (what Stage A may honestly claim)

Deterministic, model-free, local, descriptive evidence about the exact finite
`wmbs-m05-provenance-development` corpus: one-hop claim→source grounding
completeness and explanation coverage on the protected slice; unsupported-claim
rate; lineage tamper rejection by digest recomputation; and citation
precision/recall as diagnostics on non-protected material. Nothing more.

### DEFERRED (explicit, with the gate that would close each)

- **D1 — native `query_with_evidence`.** Gate: the hook is frozen in the closed
  ABI with declaration states (Q1). Until then the M05 cell declares it
  `unsupported`.
- **D2 — explanation faithfulness and natural-language claim-level citation
  scoring.** Gate: an objective claim-to-source alignment scorer plus a
  disclosed, budgeted, model-backed reader (Q9). The spec itself defers this.
- **D3 — derived-claim / multi-hop lineage.** Gate: HowProvenance wired to a
  reachable public surface (Q10).
- **D4 — promoted-item slice.** Gate: **the Q11 shared trajectory-lineage RED
  exists, is owned by the promotion path's owner, and has gone GREEN against a
  real fix.** This is a hard, explicit prerequisite, not a soft dependency: D4
  may not be closed, and no promoted-item case may be added to the M05 fixture
  or counted in `M-PROV-COMPLETE`, until that RED regression — asserting that a
  promoted item's `source_evidence_cids` is a superset of the originating
  trajectory's evidence CIDs — is landed and passing. Absent it, a promoted
  claim presents as grounded while its lineage to source events is severed, so
  scoring the slice would report a grounding completeness the system does not
  have. M05 must not write that test (§9) and must not proxy, approximate, or
  emulate it.
- **D5 — M15 replay cited as behavioral evidence.** Gate: a real executed-path
  M15 regression and digests bound to actual artifacts (Q7).
- **D6 — signed source manifest.** Gate: the protected signed-publication lease
  is released. Out of scope here.
- **D7 — measured resource admission, official adapters, publication,
  certification, ranking, and any comparative or superiority claim.** No gate is
  opened by this plan.

### Never claimed

That the M05 cell is a benchmark result; that ABI schema validity implies
grounding (Q2); that `provenance_status` verifies anything (Q3); that M01/M10
reference traces are executed-path evidence (Q5); that a local green is a
publishable green (§1).

---

## 13. Readiness verdict

**Stage A: CODE-READY**, conditional on P1–P5 and specifically on the four §10.1
RED contracts being written and observed failing first. The two technical
conditions the verdict requires are met:

- *Stable local inputs exist.* `evidence_cid` / `capture_cid`,
  `MnemoCLI.capture` / `capture_batch`, `assert_fact(evidence_cids=...)`,
  `propose`, `search`, `explain`, `export`, and the `m15-v1` payload shape are
  all present at the inspected base SHA, model-free, deterministic, stdlib- and
  repo-only. Canonical serialisation is module-local, matching the
  `wmbs_m01`/`wmbs_m10` precedent, not a shared private import. No new
  dependency and no speculative abstraction is required.
- *A disjoint implementation lease exists.* Exactly the three new paths in §9,
  verified absent at base SHA and outside every owner's exclusive surface list.

**Exact lease:**
`eval/public/wmbs_m05.py`,
`eval/public/fixtures/wmbs-m05-provenance-development.json`,
`tests/test_public_wmbs_m05.py`.

**Irreducible blockers — governance, not engineering.** Neither can be resolved
by this lane, and both must be resolved before a single implementation byte:

1. **No admitted lease-map node.** M05 sits in `U-MODULES` (`SPEC UNSTABLE`, "no
   artifact authorized", "no lease"), and the map currently admits **zero new
   implementation writers**. Only the GoalEx lifecycle owner can add the node,
   recomputed from then-current `main`.
2. **Stage B is another owner's lease.** Every registration surface in §8
   belongs to the public-harness integration owner and must be serialized on
   their lease. Without Stage B, Stage A remains an unregistered local module —
   honest, but not a harness cell.

Everything else needed to execute M05 Stage A is specified in this document.
