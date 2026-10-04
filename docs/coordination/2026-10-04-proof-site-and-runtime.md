# Proof-site preparation and local reader receipt

Date: 2026-10-04. This receipt advances original Plan B L2/L3 and real-run
preparation; it does not close those deliverables or replace Plans A/B.

## Implemented and checked

Latest sink continuation: the previous `82311010`/`857372cb` turn made progress
by retaining a replayable timing execution. `d2af156a` adds the durable inert
sink, concurrent/reopen/rollback checks and the optional replayed sink annex.
The [committed-source execution](../../eval/reports/m12-inert-sink-development-2026-10-04/README.md)
retains 30 records and 60 attempts without hidden retries. Thirty-four tests
passed, followed by 12 sink tests after snapshot transaction tightening.
Public operation idempotency and remaining full M12 acceptance are not closed.
CI `37225669534` was rechecked: unit/drift is still live, with no observed
failure on that job. The elapsed run was only about eleven minutes at the
18:56:57 UTC clock check; no restart or inference of a hang is justified.

Latest persisted-execution continuation: the preceding `97bb84c7` turn made
progress with public observations and scoring. `82311010` adds the deterministic
five-seed runner, partial-failure retention and operation-bound replay. Twenty
tests passed, followed by a separate committed-source CLI run and replay. Its
[raw development evidence](../../eval/reports/m12-exact-time-development-2026-10-04/README.md)
is retained with all 145 operations and the deliberately late observations.
Source delivery and this bounded development execution do not close M12's
registered corpus, other trigger families, calibrated baseline, full sink,
cost/resource or publication gates. Only `main` and `codex/development` are
named local branches. CI `37225669534` was rechecked and remains live in
unit/drift; later local work has not superseded that run.

Latest timing continuation: the prior `5882d192` turn made progress by fixing
duplicate-observation suppression. The next [M12 diagnostic implementation](../../eval/reports/m12-exact-time-diagnostic-2026-10-04.md)
adds opt-in public firing observations and an independent descriptive
exact-time scorer, exercised by the five seeded four-week real-CLI sequences.
57 action/scorer checks and 55 renderer/documentation checks passed. Missing,
pending, early, late, duplicate, cancelled and unexpected outcomes remain
distinct; no aggregate score, complete M12 claim or admission is implied.
The website now describes this source state. CI run `37225669534` was polled
again: unit/drift remains live; all other gating jobs passed on `762f12c8`.
Later local commits remain outside that head. No push, restart or merge was
used to interrupt the active run.

Latest action continuation: the preceding offline-tokenizer turn made progress
at `b8a8dc7a`. The [M12 follow-up](../../eval/reports/m12-action-observation-integrity-2026-10-04.md)
fixes a real observation-integrity bug: the public adapter silently deduplicated
firing evidence before the benchmark could reject it. Two regressions prove
the fix, and five seeded four-week real-CLI cases cover delayed polling,
duplicate polling, cancellation and termination. Validation and the one fixed
stale documentation assertion are recorded in the report. Lateness magnitude
and cost remain unimplemented; no registered result or acceptance gate changes.

Latest continuation: the preceding website turn made verified progress
(`4f240e36`, clearer benchmark-coverage example, live page checked, 54 rendering
tests passed). This turn advances the Plan A S1 / native-run context prerequisite:
the [offline Qwen diagnostic](../research/benchmark-intake/local-reader-reference-tokens-2026-10-04.md)
matches actual model vocabulary, added IDs and ordered merges to a pinned
reference and measures the unchanged probe's user/system message contents.
Six actual-artifact tests passed in 1.69 seconds, including mismatch rejection.
No model execution or production dependency change occurred. No acceptance
target is lowered and no M07/M08 or official benchmark gate is closed.

The specific live CI run `37225669534` was re-polled: nine gating jobs have
succeeded and unit/drift remains in progress, currently in the test-suite step.
It covers `762f12c8`, not subsequent local commits. Leave that run running;
do not merge on partial checks. Next model-execution prerequisites remain
effective context plus complete rendered-input coverage and a viable resource
configuration. The full original platform/module slate remains in scope.

The existing static renderer now supplies a responsive results table, explicit
empty state, methods reading guide, and consistent result/trace navigation.
Rows preserve record IDs, operator and publication disclosures, supplied
uncertainty and immutable artifact digests. Missing intervals are labeled as
missing; the renderer does not invent a confidence level or a universal ranking.

The CLI supports an empty JSON array without trace mappings. Nonempty results
still require validated trace mappings and existing artifact custody checks.
An empty preview can be generated without synthetic leaderboard entries:

```sh
printf '[]\n' > /tmp/mnemosyne-empty-results.json
python -m leaderboard.render /tmp/mnemosyne-empty-results.json /tmp/mnemosyne-proof-preview
python -m http.server 8791 --bind 127.0.0.1 --directory /tmp/mnemosyne-proof-preview
```

Validation: 352 tests passed across render, output smoke, publish, readiness,
result contract and signed ledger modules. Ten governance/publication-policy
tests passed; Ruff passed for changed Python files. The broader repository
suite subsequently finished with five failures, detailed below; these focused
passes are not an all-suite or release-readiness claim.

Browser checks used the actual generated pages: Results → Methods → Results;
an explicitly labeled synthetic UI fixture → run disclosures → result →
question trace. This checks navigation only, not measured system quality.
At 390px the empty page has 390px document width and no horizontal overflow.

Visual comparison against the generated desktop concept retained: (1) white
background and navy text; (2) serif headline hierarchy; (3) Results/Methods
navigation; (4) five-column bordered table; (5) explicit empty evidence state;
(6) two explanatory columns, stacked on mobile; (7) operator-entry footer.
The implementation uses a narrower centered content area and native system
body type, so wrapping differs from the concept. Primary copy is preserved.
Local screenshots are in the ignored completion evidence directory.

## Reader runtime restored

Official Ollama 0.35.1 macOS distribution installed in the user's Applications
directory. Deep strict code-signature verification passed; signing authority
is Infra Technologies, Inc. The service binds to `127.0.0.1:11434`.

- CLI SHA-256: `5f0e245e8369a66b7b24654c51c8ec95f3eab9a1e263f6e95e20d2d4374b8e26`.
- Model: `qwen3:8b`, Q4_K_M, 5,225,388,164 bytes as reported by `/api/tags`.
- Installed manifest digest matches the planned pin:
  `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`.
- Generic smoke prompt requested the word `READY`; generation returned `READY`
  with `done=true`. It used no benchmark input or protected attempt.
- Host: arm64 Mac, 16 GiB RAM. This does not satisfy physical 8-GiB
  Windows/Linux acceptance or establish performance results.

## Remaining evidence and delivery

| Requirement | Current state / next evidence |
|---|---|
| Original raw benchmark artifacts | Referenced local artifact directory absent; recover or create new properly registered runs, never synthesize old evidence. |
| Frozen Phase 12 v19 candidate | Original external manifest absent; preserve its identity and historical attempt records. Do not recreate a manifest and claim the old digest. |
| Canonical scale gate | Evaluator and unprotected `qa_scale_dev_v1` exist. Exact candidate/runtime-bound 24-case passing receipt still needed before protected execution. |
| Real comparisons | Current-version registered runs under the same protocol, budgets and supported adapters; retain failed attempts and disclose absent systems. |
| L2 completion | Public versioned data, permanent URLs, deployed site, data mirror and at least one real fully browsable system remain unverified. |
| L3 completion | Reading guide and architecture summaries for the eight planned entries are prepared and linked locally. Public deployment and the full transparent methodology remain unfinished. |
| Launch | Register A real evidence, methods paper, populated adversarial report and operational public dispute channel remain open. |

`BOARD-STATUS.md` now distinguishes implemented tools from missing launch
evidence. No gate was removed or marked satisfied by this receipt. BurnOS
production APIs and transport behavior are unchanged by the renderer work.

## Hardware feasibility follow-up

After the owner asked whether this computer could actually run the planned
workload, live inspection identified an Apple M1 Pro with 10 CPU cores and
16 GiB unified memory. The short generation above took approximately 5.01
seconds including 4.56 seconds loading; it used a 2,048-token context and is
not evidence that the full reader workload fits.

A separate synthetic resource preflight invoked the real grounded-reader
provider with 24,000 evidence characters and the unchanged registered decoding
options. A monitor sampled macOS `kern.memorystatus_vm_pressure_level` every
two seconds and terminated the preflight if warning/critical pressure appeared.
Pressure changed from 1 (normal) to 2 (warning) during model loading; the monitor
terminated the caller after 2.04 seconds. Ollama logged client cancellation and
aborted loading. A subsequent check showed normal pressure and no loaded model.
Swap usage remained 722.56 MiB across the sampled interval.

The Ollama log reported a 4,096-token context for the actual reader request,
roughly 5,311 MiB projected Metal allocation and 373 MiB host allocation. These
are runtime estimates, not measured peak resident usage; the canceled load did
not establish sustainable throughput, full-context coverage or completion.
The difference between the default context and maximum evidence budget also
needs verification before a valid full benchmark.

Therefore full local model-benchmark feasibility is **not established under
current application load**. The 24-case scale run has not started, no protected
attempt was consumed, and no model/context/acceptance criterion was weakened.
Continue ordinary code tests locally and existing CI checks. Before model
benchmarks, obtain a successful monitored preflight at the required settings
with sufficient headroom, or use a suitable separately authorized compute host.
Do not close the user's other applications or launch paid compute implicitly.

## Architecture explainer follow-up

`leaderboard/explainers.py` supplies a source-owned `systems.html` page linked
from the methods guide. It covers Mem0, Graphiti/Zep, Letta, Cognee, MemOS,
Supermemory, HippoRAG and Mnemosyne. Summaries were checked against their linked
official documentation/repositories on 2026-10-04, using the historical market
research as a starting inventory rather than copying its dated feature or
performance claims. Each entry links its source; the Mnemosyne link is pinned
to the inspected commit. Hosted products and open-source variants are not
treated as interchangeable. No vendor score is imported as a measured result.

The renderer remains offline: these source links are fixed editorial links,
not fetches or URLs supplied by result records. Its prior result/trace URL
validation remains unchanged. Ruff and 89 relevant render/publication/policy
tests passed. The actual browser path from Methods to the eight-entry guide
was inspected. This prepares L3 content but does not establish its public
publication or close the methods-paper requirement.

## Trace semantics and registered retrieval preparation

A trace review found that the `answer` field in deterministic retrieval runs
contains a retrieved identifier, while the site previously called it a final
answer. The renderer now labels it “Retrieval output (not a generated answer)”.
QA traces retain “Final answer”; unrecognized families use “Recorded output”.
Eighty-five focused rendering, publication and policy checks passed, as did
Ruff. Browser navigation through a synthetic result to its trace confirmed
the corrected label; the temporary synthetic site was then removed and the
empty real-results preview restored.

The signed registration in
`eval/registrations/2026-10-04-longmemeval-retrieval-b0cdbd89/` fixes a
500-question, retrieval-only characterization at source commit
`b0cdbd8986b94c91a3bf20833ed33f405612025a`. Its signature, seven source-file
hashes, clean detached checkout and both raw dataset digests were verified.
The detached checkout creates no additional named branch. Public registration
verification, completion of the existing local test workload, and an exclusive
start receipt remain execution gates. No scoring attempt has started.

`docs/research/OpenMemBench-Methods-Draft.md` records the methods and remaining
publication requirements. Neither this draft nor the single-system retrieval
registration replaces the original comparative roster, QA evaluation,
adversarial report, independent review or public website requirements.

## Feature comparison and coverage review

At the owner's request, the homepage links a new `comparisons.html` page.
It highlights evidence-ledger/branch semantics, working and prospective memory,
gated learning/deletion, and local access boundaries. Each section distinguishes
implemented primitives from remaining validation. It cites the pinned Mnemosyne
source and the relevant peer's documentation. It does not infer that a peer
lacks a capability merely because its overview does not document it.

Primary sources reviewed on 2026-10-04 include the official repositories/docs
for Mem0, Graphiti, Letta, Cognee, MemOS, Supermemory and HippoRAG, linked in the
page and the existing system profiles. Shared features are explicitly credited.
No verified exclusive feature or comparative superiority claim was established.

The benchmark table reviews the official sources for
[LongMemEval](https://github.com/xiaowu0162/LongMemEval),
[LoCoMo](https://github.com/snap-research/locomo),
[MemoryAgentBench](https://github.com/HUST-AI-HYZ/MemoryAgentBench),
[LoCoMo-Plus](https://github.com/xjtuleeyf/Locomo-Plus),
[MemLens](https://github.com/xrenaf/MEMLENS), and
[OmniMemEval](https://github.com/MemTensor/OmniMemEval).
These form a scoped review, not an exhaustive catalog. Broader work such as
OmniMemEval is included rather than treating conversational QA as the entire
field. The additional-evidence column is our inference from the documented
task boundary and the original project traceability requirements. It does not
claim that no good memory benchmark exists or that every listed benchmark
lacks every listed capability.

Browser checks verified homepage navigation, the coverage anchor and primary
source links in the rendered page. At a 390px viewport, the page remains 390px
wide; the 540px comparison table scrolls inside its 350px region. Desktop and
mobile screenshots are retained in the completion evidence directory.

## Downloadable evidence

The renderer exports validated result records as JSON. For v2 records it also
exports the exact verified bytes of build/config JSON, the bundle manifest and
raw traces, using the same in-memory snapshots as validation and rendering.
These are individual artifacts, not a complete downloadable benchmark bundle.
Legacy v1 records without verified artifact bindings get only result JSON.
Full raw-data mirrors and public hosting remain separate unfinished delivery.

The JSON projection retains array order for record identity; HTML metric order
remains deterministic. Generated record JSON escapes markup characters without
changing decoded values, while digest-bound files remain byte-for-byte intact.
Production hosting must serve these files as JSON/JSONL downloads with correct
content types and `X-Content-Type-Options: nosniff`; rendering alone does not
configure a host. All source rights and publication gates still apply.

Validation: 85 focused render/publication/policy checks and Ruff passed. The
tests cover exported digest equality and the verified trace snapshot even when
the original file changes after its first read. The full older-source suite
has now finished, as recorded below; this is not an all-suite pass claim.

## Completed local suite

The sequential local suite completed in 1,689.03 seconds (28 minutes, 9 seconds):
5,447 passed, 267 skipped, 191 deselected and five failed. It started before the
later website and monitor changes; their focused test results above are separate.

Four failures are the parameterized certificate-renewal integration cases in
`tests/test_production_mcp_client_cert_rotator.py`. The hardened production
subprocess selects this host's older system Python and fails on the `int | None`
annotation before completing transaction recovery. The separately investigated
system LibreSSL capability gap also remains unresolved. Required Python/OpenSSL
capabilities are documented in `infra/README.md`; no safe-PATH, certificate or
test gate was relaxed to turn these failures green.

The fifth failure was the obsolete M12 README assertion, corrected in commit
`19dc2c6c`. Its focused follow-up passed while preserving the outstanding
multiweek, calibrated-baseline and lateness evidence requirements. The local
skips include unavailable PostgreSQL, platform-specific and optional-extension
coverage; they are not successes. GitHub PostgreSQL and platform jobs provide
separate evidence, and the final development revision still needs its own CI.

The complete local log is retained in the ignored completion evidence directory
as `final-suite.log`. This establishes that the ordinary test workload can finish
on this Mac. It does not establish that the full model benchmark fits in memory.

## Full program catalog and coverage pages

The renderer now supplies `benchmarks.html` and `coverage.html`, with primary
navigation from every page and a downloadable `data/catalog.json`. The versioned
catalog separates program scope from result records. It maps all 24 original
capabilities to 20 modules, retains the six joint scenarios and groups the
original external slate into 14 benchmark families. Scope and status links are
pinned to source commit `963a56e6a0617aff72fb3029efee9a7b4215ad08`.

The coverage page reports implemented development work and remaining evidence;
it does not assign unsupported competitor capabilities or quality scores. The
live preview still contains zero result records. Measured per-system coverage,
compatible comparison controls and the real evidence pipeline remain open.

Validation: 87 rendering/publication/policy checks passed, including original
capability-to-module mapping and empty-result preservation; Ruff passed. Browser
navigation from Results to Coverage, a capability-to-module anchor, and the
benchmark catalog were verified. At a 390px viewport both pages had 390px
document width, with the 24 rows and 20 module cards present. The temporary
viewport override was reset. The local screenshot is retained as
`whole-memory-coverage-preview.png` in the ignored completion evidence directory.

## Projection shape enforcement

The runtime projection validator now enforces the already published closed
projection-v1 field contract: identifiers, filter object, exclusion strings,
finite numeric numerator/denominator, integer outcome counts, boolean safety
visibility and the closed optional weighting object. Previously 21 malformed
cases passed runtime validation despite violating the declared shape. All 21
regressions failed before the change and now pass; 274 contract, renderer,
publication and policy checks passed together, with Ruff and diff checks clean.

This is shape enforcement, not proof that a declared numerator, denominator or
uncertainty calculation is scientifically valid. No result schema, scorer,
BurnOS interface or public benchmark result changed. Dataset/model/resource
comparison metadata and reproducible grouping remain the next platform work.

## Mnemetric naming rollout

The local website now uses Mnemetric in every generated page title and header,
with “Evidence for AI memory” on the homepage. Coverage and methods identify
our suite as the Mnemetric Whole-Memory Benchmark and distinguish it from hosted
upstream benchmarks. The naming rationale and preliminary collision search are
recorded in `docs/plans/benchmark-platform-naming-2026-10-04.md`. Technical
identifiers, signed registration bytes and BurnOS interfaces are unchanged.
All 87 rendering/publication checks passed after updating the expected display
title; Ruff and diff checks passed. Real-browser homepage and coverage were
verified; screenshots are retained in the ignored completion directory as
`mnemetric-home-preview.png` and `mnemetric-preview.png`. This is a local preview,
not a public deployment.

The registered 500-question retrieval run is now executing under the resource
guard. Its exclusive signed start is outside the repository in the registered
run root. Session 66073 must be polled rather than restarted. Terminal evidence,
bundle verification/reproduction and the signed attempt ledger remain required.
No measured score is asserted by this naming change.

## Declared-context comparison index

The renderer now derives `data/comparison-index.json` from atomic results and
verified raw artifacts. The additive `comparison_context` contract is documented
in `docs/plans/benchmark-comparison-context-2026-10-04.md`; old configurations
remain visible with explicit missing-metadata exclusions. The index separates
method/split/policy/judge differences, discloses backend/hardware and splits
efficiency groups by those conditions. It never ranks, averages or authorizes
publication. Independent policy verification and interactive comparison UI
remain open. Validation: 301 grouping, contract, render, publish and policy
checks passed; Ruff and diff checks passed. The registered retrieval run was
still live with normal pressure during implementation; no second benchmark
workload was launched.

## Comparison workspace

`compare.html` now exposes compatible groups, per-system checkboxes, atomic
result tables, reported uncertainty, original run links, execution differences,
exact conditions and excluded-record reasons. JavaScript only filters existing
server-rendered rows; it fetches no mutable scores. Without JavaScript all
compatible groups remain visible. Filter URLs preserve group/system selection
and the source-dataset digest. Stale dataset links fail visibly rather than
silently substituting current results. No cross-group sorting or averaging is
introduced.

Validation: 111 workspace/grouping/render/publication checks passed, plus Ruff
and diff checks. Real-browser synthetic testing confirmed all-system default,
system filtering (3 to 2 rows), empty selection, reset, back navigation, selected
group restoration after reload and stale-dataset warning. At 390px, document
width is 390px after repairing long-fingerprint overflow. Synthetic pages were
removed by regenerating the real empty preview; no fixture score remains in the
served dataset. `comparison-workspace-preview.png` captures the resulting real
empty-state page. Keyboard-native form controls and a live status region are
present; broader assistive-technology testing remains outstanding.

## Comparison population review

Review against WMBS section 9.5 found two population edge cases: repeated metric
identities could duplicate rows, while the initial system/run/attempt shortcut
incorrectly excluded distinct module or seed cells. Grouping now rejects repeated
metric identities and identifies duplicates using the complete original atomic
identity. Three regressions failed before the fix; all 307 related checks now
pass. Ruff and diff checks pass. These are comparison semantics only; frozen
benchmark source and signed registration remain untouched.

CI run 37222196669 for pushed revision df99593b has eight successful platform,
lint, provider and PostgreSQL jobs; Unit + drift checks remains in progress.
This does not validate the later local grouping/workspace commits. Those remain
queued locally to avoid cancelling the active run before it yields evidence.
The real retrieval process 50773/session 66073 was verified live at 285 seconds
with normal pressure. A score and terminal status are not yet available.

## Registered retrieval source run completed

The frozen b0cdbd89 source run completed once in 312.304 seconds, with all sampled
memory-pressure levels normal. The bundle verifier passed and the trace contains
500 distinct question IDs, matching the registered population. The original
bundle, exact metrics, signed start/terminal/outcome/result and verified signed
ledger are retained outside the repository under the registered run root.
Publication and comparative-superiority flags remain false. This result proves
that the full retrieval-only workload can finish on this Mac; it does not resolve
the separate model-reader hardware gate or demonstrate leadership.

Local exact reproduction is now active under the same resource guard (session
24553). Its signed start identifies the frozen source and source-manifest digest.
The external reproduction wrapper calls the same frozen runner with the stored
custody input and retains artifacts on mismatch, unlike the convenience wrapper
that deletes a mismatching destination. No score or protocol is changed. The
terminal and artifact-comparison receipts still require verification and signing;
local reproduction is not independent external reproduction.

## Consistent signed attempt-history snapshot

`verified_ledger_snapshot` now returns verified entries, their signed head and
complete roster, plus the verification public key, while holding one ledger
lock. Existing `verify_ledger` behavior is preserved through this shared path.
A snapshot remains independently reconstructable after the live ledger grows;
tampering with the signed roster is rejected. The snapshot wrapper itself is
not signed and never grants publication authorization. This prepares the
attempt-history view without silently publishing inactive/nonpublishable results.

Validation: all 116 ledger/publication checks passed, including detached snapshot
reconstruction after an append and signed-head tampering. Ruff and diff checks
passed. Rendering the history and deciding which historical contents satisfy
release gates remain separate unfinished work. Retrieval reproduction session
24553 remains active with normal pressure; its result is not inferred here.

## Local attempt-history view

`render_site` accepts an optional ledger/public-key source pair. It captures and
verifies a consistent signed snapshot, rejects visible records absent from that
history, and renders `attempts.html` with every recorded outcome, roster,
supersession status, reason and available result link. The downloadable snapshot
preserves the original signatures and public key. Without a supplied ledger,
the page reports missing history instead of implying no attempts occurred.

The local preview is connected to the real completed retrieval attempt while
the ranking dataset remains empty. Generated snapshot reconstruction verified
successfully against its exported key/head/entries. All 88 history/render/publish
checks passed, with Ruff and diff checks clean. Real-browser verification showed
the actual signed attempt and a 390px document at a 390px mobile viewport;
`attempt-history-preview.png` retains the preview. Public history integration is
still gated: the existing public publisher does not automatically export inactive
or nonpublishable historical contents through this preview-only option.

## Exact reproduction and visible baseline

The registered 500-question retrieval result completed exact local reproduction: all nine bundle files matched SHA-256. Source execution took 312.30 seconds and reproduction 303.39 seconds, with normal monitored memory pressure. The signed `verified-reproduction.json` receipt is retained under the local retrieval-run custody directory. The local Mnemetric preview now renders the signed operator result, two metrics, 500 trace pages and its signed attempt history. Recall@5 is 0.2806 and nDCG@5 is 0.2967188496001503. This remains non-publishable and is not an independent reproduction, official upstream comparison or superiority claim. The original signed v1 configuration is preserved and the result is excluded from new comparison groups because comparison-context metadata is unavailable.

## Combined platform verification at d7b810d2

Ran the complete `tests/test_leaderboard*` selection with the installed verified virtual environment: all 439 tests passed (exit 0). Ruff passed for the leaderboard package and the changed grouping, history, workspace, ledger and rendering tests. Reviewed the accumulated comparison/history changes against artifact verification, duplicate atomic-cell rejection, compatibility grouping, signed-result membership and explicit local-only publication status. GitHub run 37222196669 remains active at df99593b: eight jobs passed, the full unit/drift job is still executing, and the optional nightly soak is skipped. These results do not claim full-suite coverage of the newer local commits; they are held for a single subsequent push so the active integration run can finish.

## Verified raw downloads for retained legacy results

The renderer now accepts optional bound raw artifacts for v1 results, while keeping them mandatory for v2. A supplied legacy artifact set must pass all four recorded SHA-256 digests before any page replacement; the same captured bytes are used for trace rendering and downloads. Download links are derived from verified artifact presence, not schema version. Existing v1 callers without artifacts remain supported. Original records, signed configurations and comparison eligibility remain unchanged.

All 111 rendering/publication/history/grouping tests passed, including byte tampering in each legacy artifact with preservation of the prior destination. Ruff and diff checks passed. Re-rendered the actual registered retrieval result and verified all four download URLs over localhost HTTP against its signed digests. Browser inspection confirmed build, configuration, manifest and raw-trace links. This is a local evidence preview, not release approval.

## LoCoMo upstream intake and plan reconciliation

Reviewed the official upstream scorer, runner, RAG script and license at commit `3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376`, retaining byte sizes and SHA-256 in the linked LoCoMo intake plan. Identified category-specific scoring, per-case rounding and the missing-context recall fallback that prevent substituting generic QA scoring. No held-out data was inspected or measured; no upstream code was executed. W4 now links the next-step contract without closing its adapter checkbox. Reconciled the comparison-context plan to reflect already implemented selection/URL state, local signed history and verified downloads while retaining operational admission and competitor-run gaps.

## LoCoMo ingestion component

Implemented separate conversation, query and annotation lanes with stable per-sample/question IDs, preserved source values and fail-closed structural validation. All 17 synthetic tests passed; no production dependencies or runtime contracts changed. Extended upstream review records prompt choice randomization, category denominator semantics, source hashes and the unchanged CUDA path incompatibility on this Mac. Full scorer parity, dataset admission, runnable adapter and real measurement remain open.

## LoCoMo replayable question components

Implemented caller-recorded category-5 choice draws and option mappings, the category-2 date instruction, and a raw-preserving upstream category-5 decoder. All 34 focused tests passed. Verified source hash and isolated-function parity matched on 209 synthetic decoder cases, without importing upstream model code or inspecting held-out data. Ruff passed. These components do not claim complete scorer, prompt or runnable-suite parity.

## LoCoMo per-case scoring parity

Implemented the category-specific scorer in an isolated optional evaluation environment, preserving upstream normalization, stemming, category rules and rounding. Missing context/evidence now retains upstream fallback recall separately from a null measured-recall field. All 52 ingestion/scoring tests executed and passed; 2,000 synthetic cases matched the hash-verified upstream pure scoring functions exactly. No held-out data or model was run. Production dependencies and BurnOS contracts are unchanged. Full adapter, aggregate reporting, asset admission and actual evaluation remain open.

## LoCoMo category replay reporting

Added replay reports bound to source and decoded-prediction digests, preserving all five category rows and every source question. Missing outputs remain null-scored cases with explicit counts; upstream-style denominators and observed/fallback retrieval counts stay distinct. Duplicate/unknown IDs, extra fields and explicit null contexts are rejected. No overall rank or publication authorization is emitted. All 59 isolated ingestion/scoring tests and Ruff passed. This closes the category-reporting component, not full adapter execution or benchmark admission.

## LoCoMo asset admission evidence

Verified the pinned 2,805,274-byte raw dataset against its Git blob SHA and recorded SHA-256 `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`. Streamed only for hashes, with no retained or parsed payload. The current asset validator rejected its actual `CC-BY-NC-4.0` license; retained exact rejection in the tracked intake receipt. No license relabeling, allowlist expansion, runtime registry entry or scored run occurred. LoCoMo real-data admission is a specific remaining gate; other implementation work remains possible.

## Isolated scorer CI gate

Added a ten-minute, synthetic-only LoCoMo conformance job to the existing CI workflow. It installs the complete hash-locked scorer/test dependency set into its own Python 3.11 environment and requires the pinned runtime before pytest, preventing skip-only success. Production dependencies and the existing workflow schedule are unchanged. Local hash-locked reinstall, runtime preflight and all 59 scorer/ingestion tests passed; all 40 planning-traceability tests passed. The new job is not claimed green on GitHub until the pending batch is pushed and executed.

## M07 public-clock prerequisite characterization

Reconciled stale N12/P14-B/P15-S2 predecessor claims against delivered source. Verified an existing public path using isolated `ingest`, queue enqueue and consolidation CLI processes: protected rehearsal states were false/true/false across before-due/due/after-due virtual dates, with persisted schedule and no model-backed roles. Added and passed a public-boundary regression plus a compact response-hash receipt. This is a one-item prerequisite probe, not M07 admission or a months-long benchmark. Global clock semantics, full fixture/scorer, resources and calibration remain unresolved.

## Reader feasibility recheck after local suite completion

At `4c4c9021`, repeated the unchanged 24,000-character synthetic request after
the long local test suite had finished. The pinned `qwen3:8b` model was initially
unloaded, Ollama reported 0.35.1, and macOS pressure was normal. The existing
outer guard sampled pressure every 0.5 seconds and retained a fresh attempt,
without overwriting the earlier failed probe or accessing protected questions.

Pressure became warning level 2 at 3.612 seconds; the caller was terminated and
the attempt ended after 3.780 seconds with return code -15. Explicit unload
succeeded, `/api/ps` was empty, and pressure returned to normal. Swap remained
714.56 MiB before and after. No answer was produced and no full-context or
benchmark acceptance is established. This is evidence about the current host
conditions, not proof that the model can never run on a 16 GiB computer.

The compact [repeat receipt](../research/benchmark-intake/local-reader-feasibility-2026-10-04-repeat.json)
binds the input, source files, samples and retained local log hashes. Avoid
repeating model-load attempts without a meaningful resource/runtime change.
Continue scorer, adapter, source and lightweight regression work; the required
model/resource and 24-case scale gates remain open without lowering settings.

## Candidate-bound reader disclosure policy

Native LoCoMo answers can now bind an explicit policy containing the candidate
commit, canonical candidate-manifest digest and exact reader/decomposer model,
prompt, serializer and decoding disclosures. The isolated replay request and
report retain that policy; omitted or changed policies reject bound records.
Missing reader execution remains incomplete, and matching metadata never sets
runtime custody true. The existing QA verifier shares disclosure construction.
Registered runtime authentication and native bundle integration remain open.

Validation: 135 isolated scorer/ingestion/tokenizer/replay/derivation tests;
95 production native/replay/reader-policy/reproducibility tests; and 26 QA/reader
policy tests passed, with one skip in that last group. Ruff passed. The live
benchmark page was also checked for the coverage-versus-compatibility explanation.
Current remote CI at 046f08a8 remains in progress; these local changes have not
been represented as remotely verified or merged.

## Native option-order and wire-byte custody

Added an explicit seeded native option policy alongside caller-supplied draws.
Execution and replay share source-order category-5 draw generation, preserve
policy identity/seed/draws, and reject ambiguous configuration. Both option
orders, full missing-answer denominators, changed policies and cross-interpreter
replay are tested. This does not establish pre-execution registration or reuse
the upstream script's ambient RNG state.

Fixed native capture/question JSONL writes to use exact UTF-8 bytes. The prior
question writer allowed platform newline translation after the recorded SHA-256
was calculated, which could make Windows wire bytes differ from retained
request evidence. The public-boundary test now includes Unicode and compares
actual file bytes and their hash with the retained request; Windows portability
CI explicitly selects that check. All 33 native tests and Ruff passed locally;
workflow YAML parsed successfully. Actual Windows validation awaits the next
pushed head; syntax parsing is not a claim that GitHub accepted or ran the job.

At 18:30 UTC, remote CI run 37224190672 still had Unit + drift checks running.
Its Windows file-lock failure is fixed locally by the earlier LF fixture change;
all other completed gating jobs passed. Accumulated local commits remain held
until that run finishes, avoiding cancellation of its long-running unit job.

## Native run configuration and store isolation

Added the optional source-bound native run configuration, with full/normalized
source and replay-policy digests, reader/choice policies, CLI settings and
runtime/resource artifact references. Sequential execution validates it before
capture; each record retains its digest and isolated full-population replay
recomputes the bindings. CLI flag values are hashed instead of copied, avoiding
credential disclosure. References still require independent artifact admission,
authentication and enforcement; matching declarations do not establish runtime
custody or publication eligibility. The neutral integration contract records the
remaining work and exact test evidence.

Review also identified that extra global `--store`/`--backend` flags could override
the isolated store/backend selected by the native harness. Both capture and answer
paths now reject separated and equals-form overrides before any CLI invocation.
The public parser already disables option abbreviations. Four regression cases
verify no command runs and the original store remains byte-identical.
All 37 native tests and Ruff passed after the isolation fix. No product API or
BurnOS integration code changed in this increment.


## Native candidate/runtime artifact verification

Added optional artifact verification before saved native report replay. Bounded
JSON files must match configuration references; the candidate must match a clean
exact HEAD and reader policy, and installed runtime files must match candidate
Git content. Symlink paths, changed references, dirty source and forged/rehashed
runtime files are rejected. Resource-file hash verification remains separate
from resource preflight, and no model execution/publication claim is promoted.
The 29 runtime-installation, cross-interpreter replay and reader/configuration
checks passed; Ruff passed. No model or protected-data execution occurred.


## Native trace inspector and local preview refresh

Reconciled native result assembly with the accepted one-record-per-atomic-attempt
rule: primary QA belongs in one result, with retrieval summaries retained in its
bound replay artifact rather than fabricated extra attempts. Full record/bundle
assembly remains open. Added named native request/response, projection, claim,
policy and custody fields to trace pages, plus escaped complete JSON on all trace
pages. The 75 focused checks passed. Refreshed the local preview from its existing
signed retrieval result, verified the served trace inspector and byte-identical
raw download, and added no new measured results.

## Benchmark interpretation clarification

The benchmark page now explicitly distinguishes partial lifecycle coverage from
inherent incompatibility. A QA protocol can observe benefits of an enabled
internal memory mechanism; it does not establish behavior of operations never
invoked by the run. Missing integration is an adapter limitation, not proof that
the source benchmark cannot evaluate Mnemosyne. The original LongMemEval and
LoCoMo upstream documentation was checked again; LongMemEval now links a V2,
so the page explicitly confines its coverage discussion to the original
protocol used by the current run. No V2 coverage assessment is claimed.

The existing signed retrieval preview was regenerated and its served benchmark
page checked for both clarifications. Ruff passed. No measurements, source
protocols or BurnOS contracts changed.

## Public intention creation retries

Added an optional session-scoped `idempotency_key` to schedule_intention and
`--idempotency-key` to intention-schedule. No-key callers preserve their current
behavior. All three engines use the existing atomic creation audit digest to
recognize a matching retry, validate live provenance, and return the original
creation acknowledgement without changing a later update, cancellation,
firing or recurrence state. Conflicting requests and incomplete creation
history fail closed. No new receipt table or runtime dependency was introduced.

Local/SQLite retry coverage passed 32 checks, including concurrent calls,
reopening, erased origins, session separation, missing records and default
behavior. The combined prospective-memory, CLI/MCP, BurnOS HTTP, validation and
session-read run passed 399 tests with 25 explicit prerequisite skips in 6.79s.
Repository-wide Ruff passed. PostgreSQL is not listening on this computer;
its 16 new cases are not claimed as locally verified. The live PostgreSQL CI
job now runs the prospective-memory and retry suites in addition to its prior
coverage. Review retained append-only audit enforcement: the orphan-history
PostgreSQL test creates an unaudited intention identity rather than disabling
or deleting audit protection.

The engine contract, M12 protocol, scope audit, state checkpoint and site
catalog distinguish creation retries from still-open update revisions and
idempotency. Full M12 calibration, trigger/cost/resource and admission work
remains. CI run 37225669534 at the earlier 762f12c8 head remains in progress;
none of its results certify this new source, and no merge is authorized by
partial checks.

## Public intention update retries and content preconditions

Extended the opt-in operation contract to updates. Clients obtain a content
revision through `intention-list --include-revision` / MCP `include_revision`;
new keyed updates require that revision to match under the backend transaction.
The token hashes complete canonical current state and is explicitly an ETag,
not a monotonic counter or proof that no intervening edit occurred. Existing
unkeyed calls and default response fields remain unchanged.

Keyed updates atomically record key/request digests and resulting revision in
the existing update audit; no second copy of the action payload is retained.
A matching retry rechecks authority/provenance and returns current state without
reapplying a mutation. An accepted no-op also records its key, so it cannot later
be repurposed. Changed payload/revision under the same key and fresh requests
with stale state are rejected. A deliberately injected failure after the audit
write rolls back both receipt and intention, allowing a subsequent clean retry.

The combined prospective-memory, CLI/MCP, validation, BurnOS HTTP and
session-read run passed 424 tests with 37 prerequisite skips in 6.98s. The
new combined create/update test module includes 28 PostgreSQL cases; those
remain pending live CI rather than being claimed as locally run. Ruff and
whitespace checks passed. CLI-to-MCP retries, concurrent competing updates,
reopening, terminal-state replay, no-op receipts, rollback, authority and
erasure behavior are covered by the local/SQLite checks.

Updated the engine contract, current state, M12 protocol, scope audit and site
catalog. Registered retry/recovery workloads and full M12 admission still
require completion. The older CI run 37225669534 remained active at inspection;
its earlier head does not certify this increment.

## Public action adapter response-loss recovery

The development action adapter now forwards explicit creation keys and paired
update keys/content revisions, and exposes `task.inspect` through the public
revision-bearing intention list. It validates the returned principal/session,
identity, revision and status; it never manufactures a new retry revision.
A live adapter rejects rebinding a keyed task or assigning its key to another
task. Cancellation key/revision fields remain explicitly unsupported, rather
than being silently ignored.

Twelve focused checks passed in 13.35s. Five of them run real CLI subprocesses
on separate calendar dates, discard the first successful creation/update
responses, reconstruct the adapter's in-memory mapping by replaying the
original keyed creation, and repeat the original update. They verify stable
intention identity, conflicts/stale revisions, exactly one observed firing,
no repeated-tick firing, and successful retry after the terminal transition.
Other checks reject misbound inspection output and invalid key binding before
an intention write. No engine internals or fabricated write responses are used
by the five recovery cases. This models lost responses after successful
subprocess exit, not power loss or arbitrary crash points. The original
registered fixture/scorer bytes are unchanged.

The combined response-loss, recurrence, PM-Bench/TriggerBench and persisted
timing-runner regressions passed 63 tests in 42.69s. Repository-wide Ruff and
whitespace checks passed. The served coverage page now names the response-loss
evidence and still-open keyed-cancellation/recovery gates. Remote branch reads
confirmed main at 8c103f0f and development at 762f12c8; newer local work is not
represented as remote-verified or merged.
