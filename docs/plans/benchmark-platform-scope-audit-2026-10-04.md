# Benchmark platform: original-plan scope audit

Date: 2026-10-04. Source baseline: `bad975f7` on `codex/development`.
Status: execution reconciliation, not benchmark admission or a result.

Current reconciliation at `a458bcea` supersedes the baseline-only missing-work
statements below where explicitly updated. The original scope and acceptance
criteria remain unchanged. The product name is now Mnemetric; OpenMemBench
technical identifiers and signed historical artifacts retain their original names.

Verification of the accumulated source at `a458bcea`: the combined invocation
of `tests/test_leaderboard*.py`, `tests/test_burnos_http_compatibility.py` and
`tests/test_public_development_bundle_lifecycle.py` completed successfully with
452 collected tests, all passing. This includes the real M06 development-bundle
round trip; M02/M04 plumbing explicitly uses the synthetic transport described
in that test. The separate LoCoMo environment passed 102 tests. These are local
regression results, not benchmark quality measurements or full-project closure.
GitHub validation of the accumulated unpushed changes remains pending.

## Owner's intended product

The primary website product is **Mnemetric, a public memory-system benchmark
platform**. It compares existing memory systems, explains the evidence, and
hosts a comprehensive whole-memory evaluation program. Mnemosyne is one
entrant, with its operator conflict disclosed. A Mnemosyne feature page or a
single retrieval result does not fulfill this product.

The engineering ambition is category leadership and comprehensive coverage.
Neither a universal "best" result nor superiority in every category is an
assumption of the benchmark. Improve Mnemosyne against development evidence;
freeze evaluation before held-out access; publish losses as well as wins.
Do not change the tests, exclude systems, or alter weights to force a win.

This is already substantially present in the original plans. The gap is
execution and a detailed website product contract, not a missing ambition.
The owner's latest clarification restores that full scope as the work target;
it does not discard Plan A, lower acceptance gates, or change frozen protocols.

## Review coverage and authoritative sources

The review inventories 162 planning/specification/roadmap documents, including
historical plans, with file hashes, headings and open checklist items retained
in the local audit evidence. That inventory is navigation evidence, not 162
completion certifications. The substantive scope review follows these owners:

| Source | Requirement retained |
|---|---|
| [Plan A](../EXECUTION-PLAN-A-Memory-System.md), S1–S5 | Build real capability: grounded multi-hop QA, learning, safety/calibration, performance, physical 8 GiB parity and promised research artifacts. |
| [Plan B](../EXECUTION-PLAN-B-Benchmark-and-Leaderboard.md), M1–M5 and L0–L4 | Public benchmark adapters; reproducibility; memory-native evaluation; multi-system site, methods, evidence and launch. |
| [Approved platform design](../superpowers/specs/2026-07-15-world-best-memory-platform-design.md), §§8, 11 | Per-category targets, W1–W5, full adapter suite; no single average may hide a weak category. |
| [Whole-memory specification](../superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md), §§1, 7–9, 15 | Comprehensive standard, 24 capabilities, 20 modules, joint scenarios, official/successor separation and reproducible comparison projections. |
| [MNB](../benchmark/MEMORY-NATIVE-BENCHMARK.md) | D1–D9 research dimensions, portable graders, external comparisons and anti-self-dealing rules. Its dimensions map into WMBS rather than becoming a duplicate suite. |
| [W2](../superpowers/plans/2026-07-15-W2-harvest-strengths-plan.md), [W3](../superpowers/plans/2026-07-15-W3-taxonomy-completion-plan.md), [W4](../superpowers/plans/2026-07-15-W4-neutral-adapter-suite-plan.md), [W5](../superpowers/plans/2026-07-15-W5-compact-answering-plane-plan.md) | Supersession/deletion/procedural evidence; working/prospective memory; full external slate; compact answering without quality reduction. |
| [GSD roadmap](../../.planning/ROADMAP.md) and its 17 current phase plans | Phases 10–16 retain their exact source-versus-measurement boundaries. Six Phase 16 source packages are not a complete benchmark platform. |
| [Pilot plan](../superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md) and 14 dedicated module plans | All M01–M20 have planning coverage. Partial pilots do not replace the full module contracts. |
| [Evaluation traceability](../blueprint/eval/00-traceability-matrix.md) and its metric/data/test owners | Preserve G1–G8, FR-1–FR-21, canonical metrics, golden scenarios and invariant rails. |
| [Credibility model](../governance/CREDIBILITY-MODEL.md), [board status](../governance/BOARD-STATUS.md), PBPP | Equal treatment, signed registration/attempts, reproduction, public limitations and publication approval. Outside reproduction/board seating remain optional for the operator-run label. |

Historical GoalEx delivery records and v1.0 plans remain evidence of their
original scope. Their old branch names, stale missing-file statements and
completed delivery instructions are not commands to repeat work. Current owner
instructions require solo work, `main` plus `codex/development`, and continued
BurnOS compatibility. Technical admission, custody and measurement requirements
still apply regardless of old administrative lease language.

## What the original website scope requires

Plan B L2 specifies public versioned data, permanent run URLs and per-question
traces. WMBS §9.5 additionally specifies comparison projections, filters,
compatible-record selection, declared exclusions and resource views. It
explicitly leaves detailed website interaction design to a later specification.
The subsequent website plan and comparison-context contract now cover the
implemented directories, coverage map, comparison workspace and attempt history.
Operational admission, comparable system runs and public launch remain open.

| Product surface | Required behavior | Current evidence / gap |
|---|---|---|
| Main benchmark workspace | Start with systems, benchmarks and measured results; select comparable systems and tracks. | Result table and shareable comparison workspace exist, including filters and explicit exclusions. Real matched multi-system evidence remains absent. |
| System directory | Initial roster: Mnemosyne, Mem0, Graphiti/Zep, Letta, Cognee, MemOS, Supermemory, HippoRAG. Pin actual product/OSS variants and versions; permit further systems through fair adapters. | Eight sourced architecture profiles exist. Profiles are not tested competitor adapters or results. |
| Benchmark directory | Explain each construct, protocol/version, datasets, grading, coverage and limitations. Distinguish official upstream, enhanced successor and development tracks. | Structured 14-family directory and six-project editorial review exist. Protocol-fit explanation distinguishes coverage from adapter compatibility. Most full adapters and measured evidence remain open. |
| Comparison view | Side-by-side compatible results with CIs, ties, sample counts, dates, cost/latency/RAM and environment disclosures. Publish filters, exclusions and source record IDs. | Digest-bound comparison candidates, side-by-side rendering, filters and URL state exist. Candidate eligibility is not publication authorization; the v1 real run lacks comparable v2 metadata and remains explicitly excluded. |
| Whole-memory coverage | Show all 24 capabilities / 20 modules, their evidence state, missing work and per-system support. Capability presence is separate from measured quality. | Public program-scope map covers all 24 capabilities, 20 modules and six joint scenarios. Per-system measured coverage still needs real adapters and evidence. |
| Run and trace browser | System → track → benchmark version → immutable run → per-question stored/retrieved/answer evidence → downloaded artifacts and reproduction command. | Local preview now contains one real 500-question retrieval run, trace pages and verified raw downloads. Its clean-checkout reproduction matched all nine bundle hashes. The operator run is nonpublishable and does not prove QA or multi-system leadership. |
| Methodology and trust | Registration, all attempts including failures/no-runs, conflicts, changes, judge diagnostics, losses, appeals and reproduction. | Verified ledger snapshots and local attempt-history pages exist and show the retained operator run without invented extra attempts. Public operating history, dispute handling and launch approval remain open. |
| Durable publication | Versioned public data, permanent URLs, site hosting, licensed dump, DOI snapshot/archive mirror and working submission/dispute channels. | No deployed final platform or completed archival launch evidence. |

Missing, unsupported, failed, aborted and not measured must remain distinct.
Do not display a missing capability as a zero-quality score. Never pool
official/successor tracks, incompatible versions/divisions, or unequal resource
profiles into a rank. Safety failures cannot be offset by another score.
Optional user-selected averages are exploratory and reproducible, not an
official overall winner. The site must show insufficient evidence clearly.

## Full benchmark slate retained

The original scope is larger than the six benchmarks discussed on the current
editorial page. Keep all named families on the delivery inventory:

- LongMemEval-S and LongMemEval-V2; LongMemEval-QA remains internal-only under
  the current publication policy even when using a public dataset.
- HippoRAG's MuSiQue, 2WikiMultiHopQA and HotpotQA tracks, with separate
  deterministic retrieval and disclosed-reader results.
- MemoryAgentBench's four competencies, separately reported, plus the
  originally promised upstream adapter contribution.
- BEAM-1M and BEAM-10M, including the original compact-profile scale obligation.
- LoCoMo, preserving the existing restriction against leading headline claims.
- Memora/FAMA, MemoryArena, AFTER, STATE-Bench, GroupMemBench/GateMem,
  PM-Bench/TriggerBench, EvoMemBench and EMemBench as named in the approved
  platform design, W2/W4 or WMBS reuse registry.

Listing an upstream name is not evidence of an available, licensed, pinned or
faithfully implemented protocol. Resolve the official source, revision,
rights, dataset, scorer, environment and fidelity contract before its adapter.
Do not use a locally inspired fixture under an official benchmark label.
Newer reviewed projects such as LoCoMo-Plus, MemLens and OmniMemEval belong in
the landscape/coverage assessment; adding their scored protocols requires the
same explicit admission process and does not remove the original slate.

The current LongMemEval retrieval registration is useful baseline preparation,
but covers one system and one metric family. It cannot close W4, M5, L2, L4 or
the comprehensive whole-memory program. Its exact source and stopping rules
remain frozen. It was unexecuted at the initial scope review; it subsequently
completed with Recall@5 0.2806 and nDCG@5 0.2967188496001503. These measurements
describe the registered retrieval configuration, not full upstream QA results.

LoCoMo now has synthetic-tested ingestion, dialog normalization, question/prompt
construction, context truncation, category scoring/replay and a verified offline
tokenizer. The upstream asset's exact hash is known but its CC-BY-NC-4.0 license
is outside the current admission allowlist. Full neutral-harness integration,
runtime/preflight, admitted data and actual measurements remain open. See the
[current intake and evidence](locomo-upstream-intake-2026-10-04.md).

## Whole-memory implementation and evidence inventory

Source inspected directly in `eval/public/`, `leaderboard/`, module tests and
the per-module plans at the baseline above. This table is a scope disposition,
not a promotion to a run-ready or publicly measured state.

| Module | Construct | Current scope disposition |
|---|---|---|
| M01 | Capture/durability | Local development pilot exists; broader backend and failure/durability evidence remains. |
| M02 | Retrieval/organization | Registered development cell and replay exist; full external/comparative acceptance remains. |
| M03 | Temporal evolution | Valid-time slice exists; full transaction-time bitemporality remains. |
| M04 | Conflict/correction | Development matrix and replay exist; full public acceptance remains. |
| M05 | Provenance/explanation | Development cell exists; quarantines and complete outcome/lineage evidence remain. |
| M06 | Consolidation/learning | Stage A/B development cell exists; sustained learning and non-degradation acceptance remains. |
| M07 | Retention/rehearsal/decay | Public CLI clock/rehearsal prerequisite characterized and regression-tested; dedicated multi-seed benchmark fixture/scorer/integration and resource admission remain missing. |
| M08 | Reversible forgetting | Plan exists; dedicated benchmark fixture/scorer/integration missing. |
| M09 | Declared-surface erasure | Plan exists; full benchmark and explicit surface/restore evidence missing. |
| M10 | Calibration/abstention | Deterministic pilot exists; model-backed calibration and public-label evidence remain. |
| M11 | Security/isolation | Plan and separate security-development infrastructure exist; full M11 benchmark missing. |
| M12 | Prospective action | Development probes and explicit recurrence forwarding exist; multiweek recurrence, calibrated baseline and lateness magnitude remain. |
| M13 | Working memory | Development probe exists; capacity and promotion-control experiment remains. |
| M14 | Procedural task utility | Plan exists; closed-agent environment, policy/baseline/inference contract and implementation remain. |
| M15 | Determinism/replay | Pilot composition exists; all admitted payloads and real clean-checkout reproduction remain. |
| M16 | Backend/transport parity | Bounded local cassette exists; broader pairs, migration, resource and acceptance evidence remain. |
| M17 | Custody/recovery | Plan exists; benchmark implementation and declared fault/recovery scope remain. |
| M18 | Interoperability | Plan exists; benchmark implementation and fair cross-system interchange contracts remain. |
| M19 | Multimodal memory | Plan exists, module deferred; portable modality contracts, rights, resources and implementation remain. |
| M20 | Publication integrity | Result-v1/v2, signed ledger, renderer and publication/readiness infrastructure exist; operational admission and full public evidence remain. |

There are 11 modules with dedicated or inline development scoring/comparison
logic (M01–M06, M10, M12, M13, M15, M16), plus M20 infrastructure. This count
does not mean 11 complete modules. Nine modules have registry-routed
development suites (M01–M06, M10, M12, M13); M15 is a cross-run property rather
than a separate suite. These implementation facts do not establish public
benchmark coverage or full capability acceptance.

Retain all six WMBS §9.6 joint scenarios: correction with evidence; retain /
forget / erase; learn without leaking; authorized future action; working-to-
long-term promotion; recoverable public evidence. Passing isolated modules
does not prove their interactions. Language/domain diversity, group memory
and external validity also remain research gaps declared by the standard.

## Reconciliation findings and execution order

1. **Restore product scope in the delivery plan.** The benchmark platform is
   the primary website. Keep Mnemosyne's architecture page as one system's
   profile. Preserve the original Plan A work alongside Plan B.
2. **Complete the detailed website contract.** Specify benchmark/system
   directories, compatible comparison projections, 24-capability coverage,
   result drill-down, methodology, attempts and publication. Reuse validated
   result/ledger authority; no manually curated score database.
3. **Keep source and evidence lanes moving.** Complete current integration
   gates, then build the missing platform surfaces and dependency-ready
   benchmark contracts. A single baseline run is not the critical-path end.
4. **Finish comprehensive benchmark contracts and adapters.** Freeze missing
   module contracts, implement objective graders and fair external adapters,
   then close partial cells and joint scenarios. Start from actual public
   system interfaces; never infer a tested adapter from a system explainer.
5. **Run real preregistered comparisons.** Use original upstream protocols
   unchanged, separate successor tracks, pinned rosters/versions, matched
   budgets and full attempt retention. Improve product code on development
   data while preserving protected-test discipline and original targets.
6. **Earn publication and full completion.** Real reproducible bundles,
   populated coverage, losses, methods, dispute channel, archival data and
   deployed site must satisfy original acceptance criteria. Physical 8 GiB,
   production and large-scale requirements remain open until measured on
   appropriate hosts; this Mac is not a substitute.

### Stale text that must not drive decisions

- MNB's original blanket descriptions of public benchmarks are overbroad:
  [LongMemEval](https://github.com/xiaowu0162/LongMemEval) explicitly tests
  abstention, temporal reasoning and updates, and broader frameworks such as
  [OmniMemEval](https://github.com/MemTensor/OmniMemEval) exist. The need is demonstrable coverage of
  specific contracts, not a claim that no sound benchmark exists.
- The WMBS inventory's old M04 replay and M12 recurrence-plumbing gaps are
  repaired in this development branch; full module evidence remains open.
- Older W4/M3 text requiring outside reproduction is superseded by the current
  credibility model. Actual independent reproduction must still be required
  before using that stronger label.
- Six completed Phase 16 source packages mean foundation delivery. They do
  not establish delivery of every website interaction envisioned by WMBS §9.5.
- The signed retrieval registration is now public at `bad975f7`; the recorded
  pre-execution public-file checks matched all three registration/key/signature
  files. No retrieval score or comparison has been produced by this effort.

No result, target, acceptance threshold or frozen scorer is changed by this
audit. The next website specification and implementation must remain traceable
to this full retained scope.
