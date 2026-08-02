# WMB M02 — Retrieval and Organization Implementation Contract

Status: `PROPOSED` (plan document only — no source, fixture, registry, scorer,
measurement, admission-state, or publication change is made or authorized by
this file).

Author lane: M02 retrieval-and-organization planning lane.
Verified base: `origin/main@effc5e039505c09e575ca5e4aeb2b96949676366`.
Written: 2026-08-01.

## 0. What this document is, and what it is not

This is the exact implementation contract the dependency/write-lease map
requires before any M02 code may be admitted. The map's `U-MODULES` row places
M02 under `SPEC UNSTABLE` / `No lease` with the admission rule: "Each needs an
approved exact plan, protocol, scorer, license/custody, and dependency
placement before code." This document is the candidate for that approval.

It is **not**:

- an approval (the GoalEx lifecycle/integration owner approves, not this lane);
- an admission (the lease map admits, and it must first be recomputed — see
  §2.2);
- evidence that any M02 behaviour was measured, executed, or verified;
- a benchmark, ranking, certification, superiority, publication, leaderboard,
  official-suite, result-v2, sandbox, signed-publication, or T5 claim of any
  kind. None of those paths are touched, proposed, or implied here.

### 0.1 This document's own write-lease status

**This file is not lease-clean.** `docs/plans/` is an exclusive surface of the
GoalEx lifecycle/integration owner (lease map, shared-file owner table, GoalEx
row: ``GOAL.md``; ``.planning/``; ``docs/plans/``; …), and a trailing `/`
leases every descendant of that directory. Writing this document therefore
consumed that owner's surface without holding their write slot.

The remedy is theirs to choose, and exactly one of:

1. the GoalEx lifecycle/integration owner grants a write slot for this exact
   path and adopts the file as-is; or
2. the file is relocated to a surface that owner does not lease, and the lease
   map records where M02 planning documents live.

Until one of those happens this document is an **unadmitted draft occupying a
leased path**, not an approved plan. It is listed as gate **G0** in §2.1 and it
blocks §14's admission decision on the same footing as G1 and G2. Nothing in
this document may be read as a claim that its own placement was authorized.

### 0.2 Grounding promise, stated narrowly

No test suite was executed to completion in the session that produced this
document. One focused run was started and **intentionally stopped** under an
explicit resource guard; its partial output is not verification and is not
cited anywhere below.

The grounding promise applies **only to claims that carry an exact file-and-line
anchor**. Those — §2.3, §4, §5, §6, and quarantine rows Q1, Q2, Q3, Q4, Q5, Q7,
Q8, Q11, Q12 — were each re-derived by a targeted read of the named file at the
verified base above, and a reviewer can re-check them from the anchor without
trusting this document.

The remaining quarantine rows — **Q6, Q9, Q10, Q13, and Q14** — are **carried
forward from prior integrity findings supplied to this lane and were not
independently verified here.** They carry no exact anchor, they are labelled
`carried, unverified in this lane` in §3.2, and they must not be cited as
though this lane confirmed them. They are recorded because suppressing a
known-alleged integrity finding would be worse than disclosing an unverified
one; the disclosure is the claim, not the finding's truth.

## 1. Module scope

Per `docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md`
§8, "M02 — Retrieval and organization" (lines 643–671):

- **Contract:** universal `ingest`, `retrieve`, and `answer`.
- **Data:** public adapters for LoCoMo, LongMemEval, LongMemEval-V2, and
  HippoRAG-compatible multi-hop sets where licensing permits; deterministic
  2,000-event local corpus with exact, paraphrase, entity, relation, multi-hop,
  and unanswerable queries.
- **Scorer:** answer EM/F1, Recall@K, nDCG@K, evidence recall when IDs exist,
  unsupported-claim rate, latency, tokens, calls, and storage.
- **Acceptance:** public comparison has no quality-based admission floor.
  Improvement claims require the paired confidence-interval lower bound above
  zero versus the named baseline; non-inferiority uses a preregistered
  two-percentage-point margin.
- **Feasibility disposition:** `PROPOSED` for the deterministic local corpus;
  each official adapter `DEFERRED` until exact baseline, dataset, rights,
  environment, and scorer manifests exist. **"M02 is not in the first pilot."**

The spec's own exclusion is load-bearing and is preserved here: this contract
plans a *successor* development cell, and does not reopen, widen, or re-scope
the first reference-harness pilot.

## 2. Prerequisites (frozen)

### 2.1 Governance prerequisites — not discharged by this lane

| # | Prerequisite | Owner | Why it is not mine |
|---|---|---|---|
| G0 | A write slot for **this document's own path**, or its relocation off a leased surface | GoalEx lifecycle/integration owner | `docs/plans/` is that owner's exclusive surface and a trailing `/` leases every descendant — see §0.1 |
| G1 | Lease map recomputed from current `main` and M02 admitted with an exact lease | GoalEx lifecycle/integration owner | `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md` is that owner's exclusive surface |
| G2 | Pilot-plan exclusion of M02 amended, or this contract approved as a successor plan | Same owner | `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md` line 42 and line 865 place M02 implementation out of scope for that lane; that file is the same owner's exclusive surface |
| G3 | A serialized public-harness integration slot for Stage B | Public-harness integration owner | `eval/public/{runner,scoring,bundle,registry.json,README.md}` and `eval/public/adapters/whole_memory_reference.py` are that owner's exclusive surfaces |
| G4 | A CI-owner slot if M02 tests are added to the bounded public regression | CI integration owner | `.github/workflows/` is that owner's exclusive surface |

### 2.2 Baseline-drift finding (blocking G1)

The lease map on the branch records `Baseline: main@e157e035`. The verified base
of this checkout is `main@effc5e03`, which is **22 commits ahead** of that
baseline (`git log --oneline e157e035..effc5e03 | wc -l` → 22, spanning PR #92 and
PR #93). `GOAL.md`'s own verification block asserts
`test "$(git rev-parse main)" = "e157e0350c503c9cde4aca0eff71d643a4adb200"` and
annotates it as the carve-out's **lapse detector**: "if it fails, `main` has
advanced past the recorded baseline and the carve-out must be recomputed from
the new `main` before any further admission."

That assertion fails at this base. By `GOAL.md`'s own rule the Authority
carve-out has therefore **lapsed**, and the map must be recomputed before it is
treated as operative. This is recorded, not worked around: no lease in §11 may
be taken up until G1 discharges it. Neither `GOAL.md`, `.planning/STATE.md`,
nor the lease map is edited by this lane.

**This plan's own base is also stale.** It was written against
`main@effc5e03`, while `origin/main` is now
`2091d01c8cea22da49a50bb1f0859d8108102f29` (PR #94,
`codex/goalex-t5-carveout-lapse-delivery`) — **13 commits ahead** of this base
(`git log --oneline effc5e03..2091d01c | wc -l` → 13). Those commits include CI
and lease-scope changes (`docs: include CI in T5 lease`, `ci: fetch canonical
main history`, `test: require canonical baseline ancestry`), so they can move
exactly the lease and CI facts §3, §11, and §12 depend on.

Consequently the recomputation named above must run against **then-current
`origin/main`, not against `main@effc5e03`**, and every drift figure, anchor,
line number, and lease boundary in this document must be re-derived at approval
time rather than taken from this text. The anchors below are true of
`main@effc5e03`; they are *evidence at a stated base*, not a standing claim
about `origin/main`. Approving this plan without that re-derivation would
repeat precisely the staleness failure G1 exists to correct.

### 2.3 Technical prerequisites — verified present at this base

| # | Prerequisite | Anchor | State |
|---|---|---|---|
| T1 | Closed common ABI (`wmbs/0.1-draft`): schema; `PROTOCOL_VERSION` at `whole_memory_reference.py:21`; `canonical_json` `:654`; `canonical_artifact_sha256` `:672`; `canonical_projection` `:822`; `validate_definition` `:839`; `validate_evidence_bundle` `:901`; `class ProtocolValidator` `:1103` | `eval/public/schema/wmbs-0.1-draft.schema.json`; `eval/public/adapters/whole_memory_reference.py` at the lines named | Present; SAFE/BOUNDED for contract validation only |
| T2 | `RetrievalHit` rank contract: contiguous ranks `1..N` in response order, unique `stable_item_id`, enforced `top_k` | `eval/public/README.md` ("Retrieval hits use contiguous ranks…"), `whole_memory_reference.py` response binding | Present; this is M02's consumed retrieval interface |
| T3 | Generic retrieval label extraction for `{"questions": [...]}` fixtures with `gold_references` / `gold_doc_ids` / `gold_passage_ids` | `eval/public/bundle.py:696-772` | Present; **reusable with no edit to `bundle.py`** |
| T4 | Seeded, deterministic bootstrap and descriptive-interval scoring shapes | `eval/public/scoring.py:465-478` (`_fractional_result`), `:527` (`_bootstrap`, `BOOTSTRAP_SEED`), `:94-153` (`_score_wmbs_m01` descriptive shape) | Present |
| T5-LOCAL | Local corpus needs no external dataset, no network, no model, no provider, no Docker | spec §8 M02 "local conformance needs neither" | Satisfied by construction |
| T6 | Runner fails closed when an `assets` suite is invoked without `--dataset-dir` | `eval/public/runner.py:356-358` | Present; no pass-without-execution at the runner seam for asset suites |
| T7 | Registry pins `revision` (40-hex) and `dataset_sha256` (64-hex) per suite, and gates `scoring_profile`/`family`/`interval_method` triples | `eval/public/runner.py:103-114`, `:71-81` | Present; Stage B must satisfy it |

## 3. Adversarial validation of every asset this contract would reuse

Rule applied: an asset is citable only if (a) it exercises the behaviour
claimed for it, (b) it is bound to current main, and (c) it has no
pass-without-execution, stale-digest, mutable-evidence, or unbound-custody
path. Assets failing any leg are **quarantined below and not edited**; each
carries the smallest RED regression that would expose the defect, to be written
by that asset's own owner in that owner's own lane.

### 3.1 Verified SAFE / BOUNDED for reuse

| Asset | Bounded use permitted for M02 | Bound |
|---|---|---|
| Closed ABI schema, custom validator, `ProtocolValidator`, canonical JSON | Contract validation only | Never as behavioural or measurement evidence |
| Bundle writer/verifier + scorer recomputation | Development bundles only | `whole-memory-development` family recompute path, `runner.py:432-437` |
| `eval/public/wmbs_m01.py` fixture + scorer | Deterministic harness **oracle** only | Current bytes/hashes/revision match; never as SUT evidence |
| `eval/public/wmbs_m10.py` fixture, core, scorer | Deterministic harness **oracle/baseline** only | Same; its four retrievers are stdlib-only reference retrievers, not neural models |
| `eval/public/adapters/whole_memory_reference.py::run_m03_valid_time_development` + `scoring._score_wmbs_m03_valid_time` | Bounded valid-time development only | No transaction-time semantics; see Q7 |
| M13 working-memory action probe | Disclosed 1-seed / 6-case development only | Never as scale or capability evidence |
| `_FROZEN_RETRIEVAL_BASELINES` / `_FROZEN_PHASE11_CUSTODY` duplication between `runner.py:83-94` and `registry.json` | Reference only | `validate_qa_protocol` (`runner.py:179-186`) enforces byte equality, so drift fails closed — **verified clean, no defect** |

### 3.2 Quarantine register

Each row is a defect or unproven claim. **No quarantined asset is edited by
this lane.** Each names the smallest RED regression that would turn the defect
into a failing test, and the lane that owns writing it.

Read the provenance label on every row. Rows **Q1–Q5, Q7, Q8, Q11, Q12** are
`verified in this lane` — each was re-derived from the exact file and lines it
names, at `main@effc5e03`. Rows **Q6, Q9, Q10, Q13, Q14** are
`carried, unverified in this lane` — supplied to this lane as prior integrity
findings and recorded without independent confirmation, per §0.2. A carried row
is a disclosure, not a finding this lane stands behind; its owning lane must
verify it before acting on it.

*(verified in this lane)*
**Q1 — Duplicate ranked IDs inflate nDCG and Recall above 1.0.**
`eval/harness/metrics.py:79-87` (`ndcg_at_k`) takes `retrieved_ids` as a bare
`Sequence[str]` and applies no uniqueness check; `dcg_at_k` credits a repeated
relevant ID at every rank it occupies, so nDCG can exceed 1.0. The same shape
appears in `src/mnemosyne/benchmarks.py:84,113-155`. Neither is usable as an
M02 retrieval-quality surface until duplicates are rejected.
*Smallest RED (owner: harness-metrics lane):* feed `["a","a","b"]` against gold
`{"a","b"}` and assert `ndcg_at_k <= 1.0` and that a duplicate ranked ID raises
rather than scores. *M02 consequence:* M02's scorer must reject duplicate
ranked IDs at its own boundary and must not import either surface.

*(verified in this lane)*
**Q2 — Existing public retrieval profiles cannot express M02's mandated
unanswerable queries.** `eval/public/scoring.py:496-500` (`_unique_strings`)
and `:502-508` (`_ranked_strings`) both reject empty lists. `longmemeval-
retrieval-v1` (`:46-57`) and `hipporag-retrieval-v1` (`:58-66`) therefore raise
`ScoringError` for a question with empty gold, and for a system that correctly
returns nothing. M02's spec **requires** unanswerable queries, so neither
profile is reusable for the M02 cell. This is a reuse limit at M02's boundary,
not a defect in those suites' own fixtures (which carry non-empty gold), so no
RED regression is filed against them. *M02 consequence:* `wmbs-m02-retrieval-v1`
defines an explicit unanswerable policy (§8) instead of reusing those formulas.

*(verified in this lane)*
**Q3 — `_fractional_result`'s top-level `interval` carries one metric's
unlabelled `low`/`high` into bundles.** `eval/public/scoring.py:465-478` sets
`interval = next(iter(intervals.values()))`, so the top-level field is whichever
metric happens to be first in the `values` dict — `recall_at_5` for
`longmemeval-retrieval-v1`, `recall_at_2` for `hipporag-retrieval-v1`.

**Runner gating is unaffected, and the earlier draft of this row overstated the
defect.** `_bootstrap` (`scoring.py:527-540`) returns
`{confidence, high, low, method, iterations, seed}` with `method` fixed to
`"bootstrap"`, and every metric inside one profile goes through it, so the
`method` the runner reads (`runner.py:438-446`) is identical whichever entry
lands first. The gate cannot be tripped or evaded by ordering.

The real defect is narrower and downstream: the top-level `interval` also
carries that one metric's **`low` and `high` bounds with no metric label**, and
that unlabelled pair propagates into the written bundle as if it were the
suite's interval. A consumer reading `interval.low`/`interval.high` without
also reading `intervals` gets one arbitrarily-selected metric's bounds
presented as the suite's. Nothing currently mislabels a *method*; what
propagates unlabelled is a *bound*.

*M02 consequence:* M02 emits a top-level `interval` carrying a method and no
bounds, plus per-metric keyed `intervals` (§8), and never reads the top-level
`low`/`high`. No edit to shared code; the constraint is discharged inside M02's
own scorer.

*(verified in this lane)*
**Q4 — ABI conformance suite can silently skip in full.**
`tests/test_public_whole_memory_reference.py:47-53` computes
`_MISSING = [path for path in (SCHEMA_PATH, ADAPTER_PATH) if not path.is_file()]`
and gates the file's coverage behind
`requires_abi = pytest.mark.skipif(bool(_MISSING), reason="ABI artifacts are RED")`.
If either artifact is deleted or renamed, the entire 3,441-line ABI suite
degrades to skips and CI stays green — a pass-without-execution path.
*Smallest RED (writable inside M02's own new, unleased test file):*
`test_whole_memory_abi_artifacts_are_present` asserting both paths exist as a
hard failure that can never become a skip. *M02 consequence:* M02 may not cite
`requires_abi`-gated coverage as proof of ABI conformance.

*(verified in this lane)*
**Q5 — `jsonschema` is not a declared test dependency.** It reaches the test
environment only transitively through the optional `mcp` extra
(`uv.lock`: `mcp` → `jsonschema`); `pyproject.toml`'s
`[dependency-groups] dev` lists only pytest, ruff, hypothesis, and
pytest-benchmark. `.github/workflows/ci.yml` syncs
`--extra mcp --group dev` so the ABI suite imports there;
`.github/workflows/public-regression.yml` syncs `--group dev` only. Any M02
test importing `jsonschema` would hard-error on collection in the
public-regression environment. *M02 consequence (binding constraint, not an
edit):* `eval/public/wmbs_m02.py` and `tests/test_public_wmbs_m02.py` are
**stdlib-only**, matching `wmbs_m01.py` and `wmbs_m10.py`. `pyproject.toml` is
not touched.

*(carried, unverified in this lane)*
**Q6 — Historical green reports are not evidence.** Any previously recorded
green CI run, focused-suite pass, or report digest is nonpublishable and
non-citable unless an exact-current-head rerun plus custody prove it at the
head being claimed. *M02 consequence:* every GREEN gate in §12 is defined as a
rerun at the exact PR head. No historical run id is cited as M02 evidence
anywhere in this document.

*(verified in this lane)*
**Q7 — M03 valid-time is not runner-reachable and not registry-digest-pinned.**
`run_m03_valid_time_development` exists (`whole_memory_reference.py:138`), its
scorer exists (`scoring.py:37-38,156`), its fixture exists
(`eval/public/fixtures/wmbs-m03-valid-time-development.json`, 3,853 bytes), and
its replay seeds are frozen (`bundle.py:44`). But `wmbs-m03-valid-time-
development` appears **zero times** in `eval/public/registry.json`, is absent
from `runner._ADAPTERS` (`runner.py:51-62`) and from `_PROFILE_CONTRACTS`
(`:71-81`). `run_public_suite` therefore cannot execute it, and its fixture
bytes are never checked against a registry `dataset_sha256`. This matches
pilot-plan Task 5's `Files:` list, which names no registry path, so it is a
scope choice rather than a regression — but the integrity consequence stands:
the M03 cell's fixture is guarded only by unit tests. *M02 consequence:* M03 is
not citable as an end-to-end registry-pinned whole-memory cell, and M02's
Stage B must either add the registry entry and `_PROFILE_CONTRACTS` row or
carry the identical gap as an explicit disclosure. *Smallest RED (owner:
public-harness lane):* pin M03's exact fixture and schema identity to a
registry digest.

*(verified in this lane)*
**Q8 — M01/M10 reference adapters synthesize traces rather than execute the
supplied CLI.** `run_m01_development(benchmark, _cli)`
(`whole_memory_reference.py:88-110`) manufactures receipts via
`m01.perfect_receipts(fixture)` and ignores `_cli` entirely;
`run_m10_development(benchmark, _cli)` (`:112-134`) likewise runs the
in-process reference reader and ignores `_cli`. Both are registered with
`system_seam: "harness-owned-reference-core"`, and `runner.py:385-386` passes
`None` for the CLI on that seam. *M02 consequence:* these are deterministic
oracles, never SUT evidence. **M02's development cell must not adopt the
harness-owned-reference-core seam for any retrieval-quality claim** — see the
seam decision in §6.
*Smallest RED (owner: public-harness lane):* a recording-CLI seam for M01 and
M10 that fails if the adapter never issues a call through it.

*(carried, unverified in this lane)*
**Q9 — M15 behavioural evidence is quarantined.** The M15 composition wraps
reference-only M01/M10 around a real M03, so it does not prove a shared SUT and
it skips the constituent scorers. Its custody additionally accepts
well-formed-but-fake hashes without binding the actual schema, generator,
traces, or frozen fixture, and its volatile projections diverge.
*M02 consequence:* M02 may not cite M15 as replay or composition evidence, and
may not claim canonical-replay conformance by association. M02's own replay
evidence must bind its own fixture, generator, code, and traces.
*Smallest RED order (owner: public-harness / M15 lane):* (3) shared-state,
constituent-scorer-corruption, and exact M10 trace-set tests; (4) reject fake
custody hashes and bind schema/fixture/generator/code/traces; (6) one shared
volatile projection.

*(carried, unverified in this lane)*
**Q10 — M12 registry revisions may be stale.** Normalized hashes do not prove
the pinned `revision` still identifies the fixture bytes it claims. Revisions
must be verified and rebound before reuse.
*M02 consequence:* M02 pins its own `revision` to the exact commit that lands
its fixture, and Stage B's RED set includes a `git show`-based
registry-revision/fixture identity check for M02's own row.
*Smallest RED order (owner: public-harness lane):* (1) `git show`
registry-revision fixture identity; split/repair the M12 revisions.

*(verified in this lane)*
**Q11 — one parity test derives its gold from the engine's own retrieval.**
Scoped precisely: `tests/test_parity_retrieval.py:842-878`,
`test_retrieval_quality_runs_against_real_local_engine`, builds its labels at
line 870 as `relevant_ids = tuple(hit.id for hit in probe.hits[:1])` — taken
straight from `engine.retrieve(...)`'s own output at line 869 — and then feeds
them back to `retrieval_quality_benchmark` as gold. Its assertions are
correspondingly weak (`0.0 <= metric <= 1.0`). It is a self-consistency and
wiring check, not an independent quality measurement.

The scoping matters: the sibling tests in that file are **not** implicated.
`test_retrieval_quality_metric_math_is_exact` (`:798`),
`test_retrieval_quality_counts_labeled_misses_but_skips_unlabeled` (`:816`),
and `test_retrieval_quality_empty_and_invalid_inputs` (`:832`) use fixed
synthetic labels and exact expected values, and remain valid metric-math tests.
No RED regression is filed: the one test is sound for what it actually checks,
and only its *reuse as quality evidence* is refused.

*M02 consequence:* `test_retrieval_quality_runs_against_real_local_engine` is
not citable as an M02 baseline or quality reference. M02's gold is
generator-owned and fixed before any retrieval runs (§7).

*(verified in this lane)*
**Q12 — MemoryAgentBench only aggregates caller-supplied scores.**
`eval/public/adapters/memoryagentbench.py:48-98` — `score_cases`, whose own
docstring reads "Validate and aggregate scored cases without producing an
overall score" — reads `case["score"]` from its input, range-checks it
(`:66-84`, finite and within `0..1`), and groups the values by competency
(`:84-98`). It runs no system and derives no score. *M02 consequence:* not
citable as upstream behavioural evidence for M02; the official-adapter row
stays `DEFERRED` (§10).

*(carried, unverified in this lane)*
**Q13 — Backend portability may silently omit PostgreSQL.** When no DSN is
present, ordinary portability paths may skip the PostgreSQL backend without
saying so. *M02 consequence:* M02's Stage B bundle metadata must carry an
explicit backend disclosure naming the backend actually exercised; a run that
omits PostgreSQL discloses that omission rather than reporting undifferentiated
portability.

*(carried, unverified in this lane)*
**Q14 — The audit that produced Q1–Q13 was intentionally stopped.** Its six
suites were halted above 84% during slow M12 reproduction. It is **not** a
completed verification run and is recorded as such. No completion claim is made
for it, and none of its partial results is cited as a pass.

## 4. Consumed interfaces (exact)

M02 consumes, and does not modify:

| Interface | Exact anchor | Use |
|---|---|---|
| `wmbs/0.1-draft` protocol version and compound schema | `eval/public/schema/wmbs-0.1-draft.schema.json`; `PROTOCOL_VERSION` at `whole_memory_reference.py:21` | Contract validation of M02's request/response shapes |
| `RetrievalHit` rank/`stable_item_id`/`top_k` contract | ABI response binding | Defines what a ranked hit list may contain |
| `ingest` / `retrieve` / `answer` operations | `_OPERATIONS` at `whole_memory_reference.py:33` declares **six** operations in total — `negotiate`, `create_run`, `ingest`, `retrieve`, `answer`, `finalize` | M02 **exercises three of those six** (`ingest`, `retrieve`, `answer`), matching spec §8's M02 contract. `negotiate`, `create_run`, and `finalize` remain part of the ABI and are honoured by the run lifecycle; M02 neither redefines nor omits them |
| `_scoring_labels` generic `questions` path | `bundle.py:696-772` | Produces `{question_id, gold_references, answers?}` labels — **no `bundle.py` edit required** |
| `_bind` (question-ID binding) | `scoring.py:480-494` | Binds M02 labels to M02 traces |
| `_trace_id` for the `whole-memory-development` family | `bundle.py:775-786` | Requires a non-empty `case_id` on every trace |
| `_bootstrap` seeded resampler | `scoring.py:527` | Available but **not used** by Stage A (descriptive only) |
| `MnemoCLI` subprocess seam | `eval/harness/cli_driver.py` | Stage B real-SUT path only |

**Binding conflict, resolved by construction.** `_trace_id` requires `case_id`
for `whole-memory-development`, while `_bind` requires `question_id`. M02
traces therefore carry **both**, with `case_id == question_id`, so the bundle's
trace identity and the scorer's label binding cannot disagree. This is not an
assumption: §12 RED-A6 fails if the two identities ever diverge.

## 5. Produced interfaces (exact)

| Produced | Path | Stage |
|---|---|---|
| `eval.public.wmbs_m02` module: `generate_fixture(seed)`, `validate_fixture`, `load_fixture`, `normalize_fixture`, `score_retrieval`, `canonical_json`, `canonical_sha256`, plus module constants | `eval/public/wmbs_m02.py` (new) | A |
| Frozen development fixture, byte-identical to `canonical_json(generate_fixture(DEFAULT_SEED))` | `eval/public/fixtures/wmbs-m02-retrieval-development.json` (new) | A |
| Focused stdlib-only test suite | `tests/test_public_wmbs_m02.py` (new) | A |
| `run_m02_retrieval_development(benchmark, cli)` | `eval/public/adapters/whole_memory_reference.py` (modify) | B |
| `_score_wmbs_m02_retrieval` dispatched from `score_profile` | `eval/public/scoring.py` (modify) | B |
| `wmbs-m02-retrieval-development` suite row | `eval/public/registry.json` (modify) | B |
| `_ADAPTERS` + `_PROFILE_CONTRACTS` rows | `eval/public/runner.py` (modify) | B |
| `_CANONICAL_REPLAY_SEEDS` row | `eval/public/bundle.py` (modify) | B |
| Cell documentation and gap disclosure | `eval/public/README.md` (modify) | B |

## 6. System seam decision

Stage A produces **no** system seam: it is a pure generator plus a pure scorer,
exercising nothing.

Stage B routes M02 through the **real `MnemoCLI` subprocess seam**, exactly as
`run_m03_valid_time_development` does — **not** through
`system_seam: "harness-owned-reference-core"`. This is the direct consequence
of Q8: the reference-core seam passes `cli=None` and the M01/M10 adapters
ignore it entirely, so a retrieval-quality number produced on that seam would
measure the harness's own reference retriever while being labelled as an M02
cell. M02's registry row therefore omits `system_seam` and inherits
`public-cli-subprocess` (`runner.py:485`).

Consequence, stated plainly: Stage B cannot be delivered by simply mirroring
M01/M10. It must issue real `ingest` and `retrieve` calls through the CLI and
record what came back, and RED-B2 (§12) fails if the adapter ever ignores the
CLI it was handed.

## 7. Fixture contract (Stage A, frozen)

| Parameter | Value | Rationale |
|---|---|---|
| `FIXTURE_ID` | `wmbs-m02-retrieval-development` | Development label; never an official suite name |
| `SCHEMA_ID` | `wmbs-m02-retrieval-development/fixture/0.1` | Mirrors M10's `schema_id` convention |
| `GENERATOR_ID` / `GENERATOR_VERSION` | `wmbs_m02.generate_fixture` / `1.0.0` | Mirrors `wmbs_m01.py:56-57` |
| `DEFAULT_SEED` | `20260801` | Single pinned seed; deterministic retrieval needs one run (spec §8 M02 "deterministic retrievers once") |
| Corpus size | 240 documents | Bounded development scale — see the deferral note below |
| Query families | exact 10, paraphrase 10, entity 10, relation 10, multi-hop 10, unanswerable 10 = **60 queries** | The six families the spec names, at equal weight |
| Top-level shape | `{"questions": [...], "corpus": [...], "schema_id", "generator_id", "generator_version", "seed", "fixture_sha256"}` | `questions` is the shape `bundle._scoring_labels` already understands (T3) |
| Per question | `question_id`, `family`, `text`, `gold_doc_ids` (empty list permitted **only** for `family == "unanswerable"`), `answers` | `gold_doc_ids` is one of the four keys `_scoring_labels` accepts |
| Licence | `CC0-1.0` | Wholly generated locally; no third-party text |

**Deferral — corpus scale.** The spec names a 2,000-event local corpus. Stage A
commits 240 documents and defers the 2,000-event variant until a measured
resource receipt admits a profile, exactly as the spec requires ("a measured
receipt must establish an admitted profile; 45 minutes, 8 GiB peak RSS, 8 GiB
disk, and four workers is only an L16-DEV planning hypothesis"). This is
consistent with delivered practice rather than a new liberty: M01's spec names
10,000 events and its committed development fixture carries 46 rows
(`wmbs_m01.py:60-64`; fixture 29,237 bytes), and M10's carries 100 cases
(fixture 101,401 bytes). The 240/60 shape keeps the committed fixture in the
same order of magnitude. The gap between spec scale and committed scale is
disclosed in the registry row and the README, never elided.

**Digest binding.** The committed file's **raw bytes** — not a re-serialization
of its parsed value — must equal `canonical_json(generate_fixture(DEFAULT_SEED))`,
following `wmbs_m01.py`'s documented convention. `fixture_sha256` is computed
over the fixture with the `fixture_sha256` field omitted, matching the ABI's
`artifact_sha256` self-digest rule.

## 8. Scorer contract (Stage A, frozen)

Profile `wmbs-m02-retrieval-v1`, family `whole-memory-development`, interval
method `descriptive`, `profile_version` 1. The output shape mirrors
`_score_wmbs_m01` (`scoring.py:139-153`): `family`, `finite_corpus_only: True`,
`interval`, `metrics`, `passed`, `profile`, `profile_version`, `total`,
`trace_count`, plus keyed `intervals`.

**Descriptive intervals, defined exactly (Q3).** "Descriptive" here is a
declared *absence* of an interval estimate, not an interval computed by a
descriptive method:

- The top-level field is exactly `interval: {"method": "descriptive"}` — a
  method and nothing else. It carries **no `low`, no `high`, no `confidence`,
  no `iterations`, and no `seed`.**
- `intervals` is keyed by metric name, and every entry is exactly
  `{"method": "descriptive"}` — again with **no `low` and no `high`**. Each
  metric declares its own method so no metric's bounds can stand in for
  another's, which is the precise failure mode Q3 records.
- `_bootstrap` is not called, so no resampled bounds exist to mislabel. This is
  deliberate: the fixture is a bounded finite corpus, and a resampled interval
  over it would invite a population reading the evidence cannot support.
- Nothing reads the top-level `interval`'s bounds, because there are none.

RED-A7 (§12) asserts each of these four properties, so a later change that
starts emitting bounds under the `descriptive` label fails rather than
silently publishing them.

Metrics computed, per the spec's scorer list:

| Metric | Definition | Notes |
|---|---|---|
| `recall_at_k` for k ∈ {1, 3, 5, 10} | Size of (top-k ∩ gold) divided by size of gold, over answerable questions | Undefined for unanswerable; excluded from the denominator |
| `ndcg_at_k` for k ∈ {5, 10} | Binary-relevance DCG over top-k divided by ideal DCG | Computed inside `wmbs_m02.py`; **must not** import `eval/harness/metrics.py` or `src/mnemosyne/benchmarks.py` (Q1) |
| `evidence_recall` | Fraction of gold evidence IDs surfaced when the SUT returns evidence IDs | Reported `unsupported` when no IDs exist, never synthesized |
| `unanswerable_correct_rate` | Fraction of unanswerable questions for which the ranked list is empty **or** the answer abstains | The explicit unanswerable policy Q2 requires |
| `unsupported_claim_rate` | Fraction of answered questions whose answer is not grounded in a returned hit | Diagnostic |
| `exact_match`, `token_f1` | Uses a stdlib-only local normalizer kept behaviorally equal to `scoring.normalize_answer` (`scoring.py:459-463`) by direct parity tests | Answer-side only; Stage A scores the deterministic answer path without importing quarantined harness modules |

Hard scorer boundaries, each with a RED test in §12:

1. **Duplicate ranked IDs are rejected** at M02's boundary, before any metric
   is computed (Q1). A duplicate raises, it does not score.
2. **Empty gold is legal only for `family == "unanswerable"`**, and empty
   ranked hits are legal for the same family (Q2). Every other family requires
   non-empty gold and non-empty hits.
3. **Ranks must be contiguous `1..N` with unique `stable_item_id`**, matching
   the ABI's `RetrievalHit` contract (T2).
4. **No baseline comparison, improvement claim, non-inferiority claim, or
   paired confidence interval is computed.** The spec's acceptance rules for
   those claims (paired CI lower bound above zero; preregistered 2-point
   margin) are `DEFERRED` with their preregistration.
5. **`finite_corpus_only: True`** — the numbers are descriptive full-corpus
   evidence over a bounded fixture, never a population inference.
6. **Latency, tokens, calls, and storage are `unsupported`** at Stage A. They
   require a measured external-meter receipt from an admitted profile, which
   does not exist; they are never estimated, sampled, or inferred.

## 9. Custody, licence, and claim constraints

- Fixture licence `CC0-1.0`; wholly locally generated; no third-party corpus
  text, no scraped content, no protected or licensed dataset.
- No network, no model, no provider, no judge, no Docker, no sandbox, no
  external meter, no operator evidence, no hardware profile.
- Registry row carries `publishable: false`, `pbpp_headline_eligible: false`,
  `headline_eligible: false`, `independent_external_reproduction: false`,
  `upstream_comparable: false`, `admission_state: "PROPOSED"`,
  `track_kind: "ENHANCED-SUCCESSOR"`, `split_role: "development"`.
- `revision` is pinned to the exact commit that lands the fixture, and Stage B
  RED includes a `git show` identity check binding that revision to the fixture
  bytes (Q10).
- Backend disclosure is explicit in bundle metadata (Q13).
- The result-v1 contract is untouched. No result-v2, ledger, renderer,
  publisher, readiness, signed-publication, or leaderboard path is read,
  written, or referenced. No official-suite name is ever attached to M02's
  synthetic corpus (spec §8: "Synthetic results cannot use the official suite
  name").
- BENCH-003 and BENCH-004 remain `Complete` on their existing evidence
  (`.planning/REQUIREMENTS.md:9-10`); the existing LongMemEval retrieval path
  remains authoritative for BENCH-004. M02's local cell is additive
  whole-memory-standard coverage and reopens neither requirement.

## 10. Dependency edges and integration order

```text
G1 lease-map recomputation from main@effc5e03  (blocking, GoalEx owner)
G2 pilot-plan amendment or successor approval  (blocking, GoalEx owner)
  -> Stage A  M02 generator + scorer + tests        [new files only, disjoint]
       -> Stage B  public-harness integration       [serialized, G3]
            -> Stage C  bounded regression wiring   [serialized, G4, optional]

Deferred, admitted by no stage here:
  official LoCoMo / LongMemEval-V2 / HippoRAG multi-hop M02 adapters
    <- pinned dataset revision + split digest + licence + rights + custody
       + exact baseline manifest + environment manifest + scorer manifest
  baseline comparison, paired bootstrap CIs, improvement / non-inferiority
    <- preregistration + admitted baselines
  latency / tokens / calls / storage
    <- measured external-meter receipt from an admitted resource profile
  2,000-event corpus
    <- the same measured resource receipt
```

Stage A is independent of Q1, Q7, Q8, Q9, Q10, Q11, Q12: it consumes none of
the quarantined assets. Stage B depends on Q7's and Q10's remedies only insofar
as it must not repeat them — it adds its own registry row with its own verified
revision binding rather than waiting on the M03/M12 repairs.

## 11. Exact future write lease

### Stage A — CODE-READY, disjoint

```text
eval/public/wmbs_m02.py                                    (new)
eval/public/fixtures/wmbs-m02-retrieval-development.json   (new)
tests/test_public_wmbs_m02.py                              (new)
```

Disjointness argument, checked against the lease map's shared-file owner table:
none of these three paths appears in any owner's exclusive surface list. The
public-harness owner's list enumerates exact files
(`eval/public/runner.py`, `scoring.py`, `bundle.py`, `registry.json`,
`README.md`, `adapters/whole_memory_reference.py`,
`schema/wmbs-0.1-draft.schema.json`, `tests/test_public_whole_memory_reference.py`,
`src/mnemosyne/cli.py`, `eval/harness/cli_driver.py`) and no directory under
`eval/public/` except `eval/public/receipts/`, which the evidence/operator owner
holds. The precedent is exact: `eval/public/wmbs_m01.py`,
`eval/public/wmbs_m10.py`, `tests/test_public_wmbs_m01.py`, and
`tests/test_public_wmbs_m10.py` occupy the same unleased position today, and
`tests/test_public_wmbs_m01.py` describes its target as "the exclusive-lease
module `eval.public.wmbs_m01`".

Stage A touches no leased file, no shared schema, no registry, no runner, no
CI, no source under `src/`, and no fixture other than its own new one.

### Stage B — NOT code-ready (needs G3, serialized public-harness slot, **plus a second owner**)

```text
eval/public/registry.json                               (modify)
eval/public/runner.py                                   (modify)
eval/public/scoring.py                                  (modify)
eval/public/bundle.py                                   (modify)   [DOUBLE-LEASED]
eval/public/adapters/whole_memory_reference.py          (modify)
eval/public/README.md                                   (modify)   [DOUBLE-LEASED]
tests/test_public_whole_memory_reference.py             (modify)
```

**Double-lease disclosure — `bundle.py` and `README.md` are claimed twice.**
G3 is necessary but **not sufficient** for Stage B. Two of the seven paths
above appear on *two* rows of the lease map at once:

| Path | Owner 1 | Owner 2 |
|---|---|---|
| `eval/public/bundle.py` | Public-harness integration owner (shared-file owner table) | `P14-B` REPRO-001, whose lease is "Exactly `eval/public/schema/reproducibility-bundle-v1.schema.json`, `eval/public/bundle.py`, `eval/public/README.md`, `tests/test_public_reproducibility.py`" |
| `eval/public/README.md` | Public-harness integration owner | `P14-B`, same row |

`P14-B` is itself `BLOCKED on N12`, and `N12` is `LEASE BLOCKED` — the map's
own text: "No admission until the protected signed-publication paths are
released on current main." So the chain reaching those two files is
`released protected result-v2 lease → N12 → P14-B`, and none of it is open.

Three consequences, stated rather than engineered around:

1. Stage B cannot be scheduled purely on G3. Whenever `P14-B` becomes live,
   Stage B and `P14-B` must be **serialized against each other**, not run as
   disjoint lanes, because they would write the same two files.
2. If serialization proves unacceptable, the honest alternative is to reduce
   Stage B's footprint: M02 requires **no** `bundle.py` edit for label
   extraction (T3 — the generic `questions` path already handles M02's fixture
   shape), so the only `bundle.py` change contemplated is the
   `_CANONICAL_REPLAY_SEEDS` row. That row could be deferred, at the cost of
   M02 carrying no frozen replay seed — a disclosed gap, not a silent one.
3. `eval/public/README.md` has no such escape: M02's cell documentation and
   gap disclosure belong there, and that is a genuine second-owner edge.

This is the one place where §14's "Stage A is disjoint" claim must not be read
as extending to Stage B. Stage A remains disjoint; **Stage B is double-leased
and this document does not claim otherwise.**

### Stage C — NOT code-ready (needs G4, CI owner), optional

```text
.github/workflows/public-regression.yml                 (modify)
tests/test_public_regression_workflow.py                (modify)
```

Stage C is optional and is listed only so the edge is visible. Note Q5: the
public-regression environment syncs `--group dev` without `--extra mcp`, so
only stdlib-only M02 tests may ever be added there.

## 12. RED / GREEN checks

RED first in every case; each RED must fail for the stated reason before any
implementation exists.

### Stage A RED (all inside `tests/test_public_wmbs_m02.py`, stdlib-only)

| ID | Test | Fails until |
|---|---|---|
| RED-A1 | `test_committed_fixture_bytes_equal_generated_bytes` | The committed fixture's raw bytes equal `canonical_json(generate_fixture(DEFAULT_SEED))` |
| RED-A2 | `test_generator_is_seed_deterministic_and_seed_sensitive` | Same seed reproduces byte-identically and a different seed produces different bytes |
| RED-A3 | `test_scorer_rejects_duplicate_ranked_ids` | The scorer raises on a repeated ranked ID instead of inflating nDCG/Recall (Q1) |
| RED-A4 | `test_scorer_scores_unanswerable_with_empty_gold_and_empty_hits` | Empty gold and empty hits score correctly for `family == "unanswerable"` and raise for every other family (Q2) |
| RED-A5 | `test_scorer_rejects_noncontiguous_or_duplicate_ranks` | Ranks are contiguous `1..N` with unique `stable_item_id` (T2) |
| RED-A6 | `test_trace_identity_agrees_across_bundle_and_scoring_bindings` | Every trace carries `case_id == question_id`, satisfying both `bundle._trace_id` and `scoring._bind` (§4) |
| RED-A7 | `test_metrics_shape_is_descriptive_and_finite_corpus_only` | Output carries `finite_corpus_only: True`; the top-level `interval` is exactly `{"method": "descriptive"}`; every entry in `intervals` is exactly `{"method": "descriptive"}`; and **no `low`, `high`, `confidence`, `iterations`, or `seed` key appears in any interval** (Q3, §8) |
| RED-A8 | `test_unmeasured_metrics_are_unsupported_not_estimated` | Latency, tokens, calls, and storage report `unsupported` and are never synthesized |
| RED-A9 | `test_no_baseline_or_improvement_claim_is_produced` | The scorer emits no baseline comparison, paired interval, improvement, or non-inferiority field |
| RED-A10 | `test_whole_memory_abi_artifacts_are_present` | Both ABI artifacts exist, as a hard failure that can never degrade to a skip (Q4) |
| RED-A11 | `test_module_imports_only_stdlib_and_eval_public` | The module imports no `jsonschema`, no `eval.harness.metrics`, and no `mnemosyne.benchmarks` (Q1, Q5) |

Exact focused command, **recorded and deliberately not executed in this
planning session** (resource guard; the coordinator serializes broad
validation):

```bash
uv run --locked --group dev python -m pytest tests/test_public_wmbs_m02.py -q
```

`--group dev` without `--extra mcp` is intentional: it proves the stdlib-only
constraint of Q5 holds.

### Stage A GREEN gates

- The focused command above passes at the exact PR head (Q6: a rerun at that
  head, never a historical run id).
- `uv run --locked ruff check .` clean.
- Markdown, diff-scope, lease, risky-file, and secret checks clean.
- One authoritative full suite on the stable exact PR head, run once by the
  integration owner — not duplicated across lanes.

### Stage B RED (owner: public-harness lane, after G3)

| ID | Test | Fails until |
|---|---|---|
| RED-B1 | `test_registry_revision_matches_fixture_bytes_under_git_show` | The pinned `revision` resolves under `git show` to exactly the committed fixture bytes (Q10) |
| RED-B2 | `test_m02_adapter_issues_real_cli_calls` | The adapter is exercised through a recording CLI seam that fails if no call is issued (Q8) |
| RED-B3 | `test_runner_rejects_m02_fixture_digest_drift` | A one-byte fixture change fails `run_public_suite`'s `dataset_sha256` gate (`runner.py:375-378`) |
| RED-B4 | `test_m02_metrics_recompute_from_anchored_profile` | Bundle verification recomputes M02's metrics from labels plus traces and rejects adapter-supplied metrics (`bundle.py:369-376`) |
| RED-B5 | `test_m02_bundle_declares_backend_explicitly` | Bundle metadata names the backend actually exercised (Q13) |
| RED-B6 | `test_m02_publication_flags_are_false` | `publishable`, `pbpp_headline_eligible`, and `independent_external_reproduction` are all `false` |
| RED-B7 | `test_m02_custody_rejects_wellformed_fake_hashes` | Custody binds the real schema, fixture, generator, code, and traces rather than accepting any well-formed digest (Q9) |

## 13. Claim boundary — PROPOSED vs DEFERRED

| Item | State after Stage A | State after Stage B |
|---|---|---|
| M02 module feasibility disposition | `PROPOSED` | `PROPOSED` |
| Deterministic local development corpus (240 docs / 60 queries) | `PROPOSED`, committed, digest-bound | unchanged |
| Recall@K, nDCG@K, evidence recall, unanswerable rate, unsupported-claim rate, EM/F1 over that corpus | Computed, descriptive, finite-corpus-only | Recomputed by the harness from labels + traces |
| Real-SUT retrieval through the public CLI seam | `DEFERRED` | `PROPOSED`, development only |
| 2,000-event corpus | `DEFERRED` — needs a measured resource receipt | `DEFERRED` |
| Latency / tokens / calls / storage | `DEFERRED` — `unsupported`, never estimated | `DEFERRED` |
| Baselines, paired bootstrap CIs, improvement and non-inferiority claims | `DEFERRED` — needs preregistration | `DEFERRED` |
| Official LoCoMo / LongMemEval / LongMemEval-V2 / HippoRAG M02 adapters | `DEFERRED` — needs dataset revision, split digest, licence, rights, custody, baseline, environment, and scorer manifests | `DEFERRED` |
| `PILOT-READY-DEV` for M02 | Not claimed | Not claimed |
| Publishable / headline-eligible / upstream-comparable / independently reproduced | `false` throughout | `false` throughout |
| BENCH-003, BENCH-004 | Unchanged (`Complete` on existing evidence) | Unchanged |

Nothing in this contract advances a certification, ranking, superiority,
launch, production, official-suite, publication, result-v2, sandbox,
signed-publication, or T5 claim, and nothing here admits an
official/protected attempt.

## 14. Admission decision

**Stage A is CODE-READY** on the two technical criteria:

1. *Stable local inputs exist.* T1–T4, T6, T7 are present at the verified base;
   the local corpus needs no external dataset, network, model, provider, or
   container; and the generic `bundle._scoring_labels` questions path means
   Stage A requires no edit to any leased file.
2. *A disjoint implementation lease exists.* The three new paths in §11 appear
   in no owner's exclusive surface list, and `wmbs_m01.py` / `wmbs_m10.py` and
   their tests establish the precedent exactly.

**Stage A is not yet admissible**, for reasons that are governance, not
technical, and that this lane cannot discharge:

- **G0** — this document itself sits on `docs/plans/`, the GoalEx owner's
  exclusive surface, without that owner's write slot (§0.1). An unadmitted
  draft on a leased path cannot be the approved plan that admits M02.
- **G1** — the lease map must be recomputed, and against **then-current
  `origin/main`**, not against this plan's base. Its recorded baseline is 22
  commits stale versus `main@effc5e03`, `GOAL.md`'s own lapse detector fails
  there, and `origin/main` has since moved a further 13 commits to
  `2091d01c` (§2.2). Until then the map is not operative and its `U-MODULES`
  row still reads `No lease`.
- **G2** — the approved pilot plan places M02 implementation out of scope
  (lines 42 and 865). An owner amendment, or approval of this document as a
  successor plan, is required.

Stage B additionally requires **G3**, *and* resolution of the `bundle.py` /
`README.md` double-lease against `P14-B` (§11) — G3 alone does not clear it.
Stage C additionally requires **G4**.

These are the only irreducible blockers. Every other gap named in this document
is either deferred with its exact missing evidence (§13) or quarantined with
its smallest RED regression and owning lane (§3.2) — subject to the provenance
labels: five quarantine rows are carried, not verified here (§0.2).

**Every anchor, line number, drift figure, and lease boundary in this document
must be re-derived at approval time** against then-current `origin/main`. They
are evidence at a stated base, not standing claims (§2.2).

## 15. Non-goals

- No edit to any quarantined asset, to PR #94 paths, to `GOAL.md`,
  `.planning/STATE.md`, the lease map, `tests/test_planning_traceability.py`,
  `.github/workflows/ci.yml`, or any source, test, fixture, registry, or shared
  doc. This lane writes exactly one file — this one — whose own placement is
  disclosed as unadmitted in §0.1 rather than presented as lease-clean.
- No official or protected attempt, no publication claim, no result-v2, no
  sandbox, no signed publication, no T5 path.
- No M04–M09, M11, M14, M16–M19 work, and no reopening of the first pilot's
  scope.
- No second roadmap, benchmark lifecycle, runner, registry, evidence store, or
  result ledger.

## 16. Historical plan-authoring validation

This block records the pre-implementation lane check that proved the three
Stage A paths were absent when this plan was frozen. It is not an executable
acceptance check for a later integrated head, where those paths are expected to
exist and are validated by the Stage A tests in §12.

```bash
set -euo pipefail
git rev-parse HEAD
git merge-base --is-ancestor e157e0350c503c9cde4aca0eff71d643a4adb200 HEAD
test -f docs/plans/wmb-m02-retrieval-organization-implementation-plan.md
# Exactly one file changed by this lane.
test "$(git diff --name-only origin/main...HEAD)" \
  = "docs/plans/wmb-m02-retrieval-organization-implementation-plan.md"
# Cited surfaces exist at this base.
test -f eval/public/schema/wmbs-0.1-draft.schema.json
test -f eval/public/adapters/whole_memory_reference.py
test -f eval/public/wmbs_m01.py
test -f eval/public/wmbs_m10.py
test -f eval/public/fixtures/wmbs-m03-valid-time-development.json
# Q7: M03 is not registry-registered.
test "$(grep -c 'wmbs-m03-valid-time-development' eval/public/registry.json)" = "0"
# T1 corrected ABI anchors resolve to the symbols this plan cites.
sed -n '839p' eval/public/adapters/whole_memory_reference.py | grep -q 'def validate_definition'
sed -n '1103p' eval/public/adapters/whole_memory_reference.py | grep -q 'class ProtocolValidator'
# §4: _OPERATIONS declares six operations; M02 exercises three of them.
sed -n '33p' eval/public/adapters/whole_memory_reference.py \
  | grep -q '"negotiate", "create_run", "ingest", "retrieve", "answer", "finalize"'
# Q11 is scoped to exactly the one test that derives gold from engine retrieval.
sed -n '870p' tests/test_parity_retrieval.py \
  | grep -q 'relevant_ids = tuple(hit.id for hit in probe.hits\[:1\])'
# Q12 anchor: the adapter aggregates caller-supplied scores.
sed -n '48,49p' eval/public/adapters/memoryagentbench.py \
  | grep -q 'without producing an overall score'
# Q3: every metric in a bootstrap profile shares one method, so runner gating
# is unaffected; what propagates unlabelled is a bound.
grep -q '"method": "bootstrap"' eval/public/scoring.py
# §2.2: this plan's base is stale versus origin/main.
test "$(git rev-parse origin/main)" != "$(git rev-parse HEAD)"
# The three Stage A paths do not exist yet.
test ! -e eval/public/wmbs_m02.py
test ! -e eval/public/fixtures/wmbs-m02-retrieval-development.json
test ! -e tests/test_public_wmbs_m02.py
```
