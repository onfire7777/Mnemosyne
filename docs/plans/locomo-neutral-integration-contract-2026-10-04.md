# LoCoMo neutral integration contract

Status: implementation contract for remaining integration, not dataset admission,
run registration, resource approval or a completed adapter.
Source review: `4a0e4c4c`; parent [W4](../superpowers/plans/2026-07-15-W4-neutral-adapter-suite-plan.md).
Protocol evidence: [pinned intake](locomo-upstream-intake-2026-10-04.md).

## Keep the measured systems explicit

The current `prepare_nonrag_request` path builds a full-conversation model
baseline. It does not call Mnemosyne or prove memory-system behavior. Its
successful tokenizer/prompt tests must not be counted as a Mnemosyne adapter.

`eval/public/adapters/longmemeval_qa.py` demonstrates the existing public memory
boundary: capture through `MnemoCLI`, then use the product answer path. The
product controls retrieval, evidence formatting and answer generation. Sending
the same source questions through that boundary does not reproduce upstream's
exact model prompt. Likewise, using the upstream non-RAG prompt without calling
the memory system does not evaluate Mnemosyne's memory architecture.

Retain three distinct protocol identities:

| Track | System under test | Required disclosure |
|---|---|---|
| Pinned upstream non-RAG baseline | Registered answer model with the bounded source conversation | Exact upstream revision, explicit observed speaker order, tokenizer/vocabulary hashes, model content/provider revision, prompt bytes, generation parameters and truncation. |
| Pinned upstream RAG baseline | Registered upstream retriever plus answer model | All preceding applicable fields plus dialog/observation/summary mode, preprocessing, encoder content pins, top-k, ordered retrieved IDs and context bytes. This path is not implemented by the non-RAG helpers. |
| Native memory-system evaluation | Mnemosyne or another system through its declared public adapter | Source conversation/caption policy, public commands, lifecycle operations actually invoked, internal retrieval/reader policy, structured response conversion, resource budget and differences from upstream prompts. Report separately from unchanged baseline results. |

No cross-track overall ranking. Within a comparative track, every participant
must receive the same admitted source population, questions and declared budget
policy. Differences in model, preprocessing or capabilities stay visible.
Category 5's source-answer distractor belongs only in the registered question
transformation, never in ingested memory. Category-specific scoring remains
the pinned scorer, with missing predictions and recall applicability explicit.

## Current integration audit — descriptive result projection update

This table supersedes the original sequence's prospective descriptions below;
it does not close W4 or any measured acceptance requirement.

| Original step | Current implementation evidence | Remaining acceptance work |
|---|---|---|
| 1. Freeze track/configuration | Optional native configuration binds full and normalized source hashes, replay policy, reader/choice policies, CLI settings and runtime/resource artifact references. Its digest is retained in each answer and the replay report. | Candidate/installed-runtime file checks are available through the optional artifact verifier. Admit the resource artifact, effective model/provider/tokenizer/context settings and preregistered choice policy, then integrate these gates into registered execution; file consistency is not execution or resource proof. |
| 2. Native public adapter | `iter_native_answers` validates the population first, captures one isolated conversation at a time, invokes public read-only answers, retains command options and cleans stores. Public capture tests exercise actual subprocesses. | Full admitted population under the registered runtime and resource envelope; signed attempt persistence. |
| 3. Response conversion | Raw outputs, missing reader execution, explicit abstention, category-5 decoding, citations, spans, answer rendering and opt-in synthesis derivations are retained/validated. The independent derivation checker does not call the product synthesizer. | Optional candidate-bound reader policy now checks exact model, prompt, serializer and decoding disclosures and is retained in offline replay. Authenticate that candidate and actual runtime through the registered bundle path; a matching disclosure is not proof of provider execution. |
| 4. Neutral bundle/replay | Full-population offline scoring and exact saved-report replay work across interpreters. Versioned development category summaries now fit result-v2, render counts/missingness and preserve absent categories without invented intervals. | Assemble complete result records and neutral bundles with configuration/registry anchors and verifier dispatch; implement preregistered uncertainty before claiming that acceptance gate. Generic QA semantics remain separate. |
| 5. Registry/scoring dispatch | No real LoCoMo registry entry or runnable official suite has been added. | Dedicated native scoring profile plus coordinated runner/verifier dispatch; resolve dataset rights/admission before real data enters the registry. |
| 6. Model/resource preflight | Two retained synthetic reader probes stopped at warning memory pressure; the latest receipt is linked in project state. | Required-setting feasibility and complete context coverage, then the original scale gate. Tokenizer/scorer success does not discharge this requirement. |
| 7. Registered run/public evidence | No real LoCoMo run or ranking is claimed. | Pre-execution registration, retained attempts, full execution, reproducible bundle and accurate website presentation. |

### Exact bundle integration boundaries

The current `eval/public/bundle.py` has two separate verification contracts:

- `verify_bundle` uses `_REGISTERED_SCORING_PROFILES`, `_scoring_labels` and the
  canonical registry anchor. Generic traces normally require one metric total
  per trace; native missing answers require the full source denominator instead.
  Do not add LoCoMo to `qa-em-f1-v1` or turn missing predictions into blank
  successful outputs to satisfy that counter.
- Its reproducibility-v1 branch calls `_bound_repro_scoring_profile` and
  `_recompute_repro_metrics`, which currently admit only `smoke-hit-at-k-v1` and
  a single Wilson hit-at-k metric. A valid native report is not yet a valid
  reproducibility-v1 bundle. Its multiple category scores and native evidence
  recall need dedicated metric projection and recomputation together.
- `reproduce_bundle` currently re-executes `run_public_suite` and compares files.
  Offline score replay is a different operation: retain that distinction rather
  than copying saved responses and calling it another model execution.
- `run_public_suite` gates candidate/runtime manifests and attempt claiming on
  the QA family. A new native family must preserve those gates explicitly;
  adding only a family/profile name would otherwise bypass them. Reuse the
  candidate/runtime verification code where its invariants apply, while keeping
  native preprocessing and per-category scoring distinct.

Next implementation order: complete effective provider/context and resource admission,
then integrate the existing candidate/runtime artifact checks with coordinated bundle/result metric projection and
verification using the existing isolated replay worker; then add gated runner
and registry dispatch. The production interpreter must validate registry,
candidate, runtime and artifact custody before invoking the minimal scorer
worker. The worker verifies source/records/report consistency, not rights,
model execution, signatures or publication. Acceptance tests must cover altered
source/config/model identity, missing answers, both category-5 orders, synthesis,
wrong-category metrics, missing runtime custody and failed/partial attempts.

## Original implementation sequence (scope retained)

1. Freeze the selected track and its versioned configuration schema. Include
   source/normalized-input hashes, caption policy, all model and tokenizer pins,
   adapter revision, context budget, generation settings and option-order seed.
   Do not reuse the generic QA profile: LoCoMo's per-category aggregation and
   fallback recall behavior require their own scoring contract.
2. Implement the native public adapter using normalized dialog records. Isolate
   state per source conversation; preserve source dates as data without claiming
   a virtual-clock experiment. Capture only the whitelisted conversation fields.
   Record whether consolidation, recurrence, deletion or other lifecycle actions
   were actually invoked. A retrieval/QA run does not prove those capabilities.
3. Define response conversion for the structured product answer, including
   abstention, provider failures, evidence IDs and category-5 decoding. Retain
   both the original response and the exact decoded string passed to scoring.
   Do not silently substitute an empty string or fabricated evidence on failure.
4. Extend the neutral bundle/verifier together. Replay must bind question IDs,
   the full source denominator, request/response bytes, context/retrieved IDs,
   per-case scores, category aggregates and all configuration hashes. Reject
   mismatched requests, missing labels, duplicate outputs and tampered metrics.
   Missing predictions stay visible; no favorable filtering or overall average.
5. Add registry/scoring dispatch only after the contracts and custody validate.
   The real dataset remains excluded until its CC-BY-NC-4.0 rights/admission
   decision is resolved. Synthetic tests may exercise code paths, but must use
   explicitly developmental identities and cannot become official run evidence.
6. Validate required model settings and resource bounds on non-protected inputs
   before registration. The successful tokenizer-only tests do not discharge the
   blocked grounded-model preflight. Preserve the computer's resource limits.
7. Register the frozen run before protected access, retain all attempted runs,
   execute the full admitted population, reproduce the bundle and expose the
   per-category results and limitations through the existing result validator.

## Acceptance evidence

- A public-boundary integration test proves correct conversation isolation,
  input-label separation, stable evidence mapping and original response retention.
- A full synthetic replay test covers all five categories, both adversarial
  option orders, truncation, missing outputs and provider failures; tampering
  with any bound input/output/metric fails verification.
- A pinned real-asset run uses the admitted full population and frozen protocol;
  synthetic passage or scorer tests are insufficient for this criterion.
- Required resource preflight and replay succeed on the actual declared runtime.
- The website distinguishes measured native-system outcomes from upstream
  baseline outcomes and retains the existing non-headline LoCoMo policy.

This contract preserves original W4 scope. It does not close its LoCoMo checkbox,
authorize a license-policy bypass, establish superiority or claim that other
memory-system adapters have been implemented.

## Native capture implementation checkpoint

`eval/public/adapters/locomo_native.py::captured_conversations` now exposes a
bounded-lifetime local capture context. It uses only public `MnemoCLI`
capture-batch calls, creates a separate temporary store and hashed tenant for
each source conversation, and verifies the returned CID sequence against
the public evidence-identity formula before yielding any handles.

The disclosed native preprocessing serializes source timestamp, speaker, text
and selected caption as canonical JSON. Unique source types bind each dialog's
stable identity, so identical text in two turns retains distinct provenance.
This is not the upstream baseline's prompt formatting. Question/answer/evidence
annotations are not passed to capture. Temporary stores are removed on context
exit and the caller's original store is untouched. No explicit consolidation,
clock advancement, answer generation or scoring is performed by this boundary.

Three focused tests passed using the installed Python 3.14 project environment:
one real public-CLI test captured and searched two independent conversations,
verified distinct evidence identities for duplicate text, excluded source labels,
checked cross-conversation lookup isolation and cleanup; two synthetic receipt
tests rejected wrong result counts and invalid CIDs before yielding. The initial
negative tests omitted the required CLI store argument; that test setup was
corrected before the passing rerun. Ruff passed.

This advances step 2 only. It does not complete response conversion, measured
capability testing, registry integration, real-dataset admission or W4 acceptance.

## Native response projection checkpoint

`project_native_response` now retains a deep copy of the original public response,
the registered question transformation and its explicit category-5 choice draw,
and mapped retrieved dialog IDs. Unknown retrieval evidence fails closed rather
than being filtered out. Duplicate retrieval references retain their first order.

The public API can return `abstained: true` with empty reader disclosure after a
provider timeout (`tests/test_public_eval_cli.py` demonstrates this). Accordingly,
responses without a nonempty grounded-reader disclosure produce
`incomplete-reader-execution` and a null decoded prediction. They must remain
missing/incomplete outcomes in the eventual replay report, not earn an
abstention score or be dropped from denominators.

For responses with grounded-reader disclosure, the explicitly versioned native
projection maps a boolean abstention with null/empty answer to `No information
available`. Non-abstaining answers are stripped and category 5 uses the pinned
option decoder. Contradictory abstention plus nonempty answer is rejected.
This mapping is native-adapter behavior, not an unchanged upstream response.
Presence of reader disclosure does not verify its truth or runtime custody:
the returned record explicitly leaves `runtime_custody_verified` false pending
registered provider-manifest validation.

All ten native tests passed, covering public capture plus response projection,
timeout separation, raw-response retention, option mapping, malformed answers
and foreign retrieval evidence. Ruff passed. Answer invocation, admission,
full replay binding and official measurements remain open.

## Public answer invocation checkpoint

`answer_captured_question` now checks the question's conversation and source
query, applies the declared category transformation, and invokes
`eval-answer-batch` through a cloned public CLI with `--evaluation-read-only`.
It requires a live captured store, binds the returned single result to the
requested question ID, and passes it through the explicit native projection.
The exact request JSONL and SHA-256, structured request and original batch
response are retained. Temporary request files are cleaned on exit. Exceptions
propagate to the future registered runner's attempt handling; they are never
converted into successful answers or silently removed from the population.

All 15 native tests passed. New invocation tests use an explicitly synthetic
transport to verify read-only flags, request-label exclusion, conversation and
response identity, request cleanup and exception propagation. The existing
capture/isolation test still exercises the real public CLI. No real model
answering is claimed by these tests. Ruff passed. Dataset/runtime admission,
complete population orchestration, signed replay bundles and measured quality
remain required before a real native LoCoMo result.

## Claim and quotation custody

Native response projection now also requires the public claim list. Claim
citations must identify registered evidence and appear in the response's
retrieval trace. Every quoted span must belong to its claim's cited evidence;
its integer character offsets must fall within the captured content, and the
SHA-256 of that UTF-8 encoded substring must match the supplied slice hash.
This follows the product's character-indexed span convention. Foreign citations,
malformed claims and altered quotations fail before score projection.

All 20 native tests passed, including valid span projection, changed span hashes,
foreign/malformed citations and registered-but-unretrieved evidence. Ruff passed.
These checks establish structural evidence custody, not semantic entailment or
truth of a claim. Full replay and provider custody remain separate requirements.

## Offline per-question replay checkpoint

`verify_native_answer_record` reconstructs the complete expected capture map,
tenant, transformed question, request JSONL/hash and response projection from
the source conversation, selected source question, caption policy and explicit
choice draw. Capture generation and replay share the same pure capture planner.
The retained record now binds a digest of the complete capture map, so changes
to unreturned as well as retrieved evidence are detected. Canonical finite-JSON
comparison rejects changed derived values, extra fields and forged verification
flags. Replay does not require the original temporary store or a model call.

All 21 native tests passed, including a real capture followed by a synthetic
answer and offline replay after store cleanup. Mutations to predictions, request
hashes, verification flags, extra fields, retrieved source content and unreturned
source content were rejected. Ruff passed.

This establishes per-question internal consistency. A fully consistent forged
response is not authenticated by recomputation: signed registration, original
provider execution evidence, whole-population score replay and neutral bundle
integration remain required. No benchmark or publication gate is closed here.

## Native population score replay

`locomo_scoring.replay_native_population` now verifies every supplied native
record against its source question/capture and then recomputes per-category QA
scores with the pinned scorer. Unknown/duplicate IDs, changed derived fields,
and missing/extra category-5 choice draws are rejected. All source questions
remain in the QA denominator; absent records and incomplete-reader execution
retain explicit missing counts and null per-case scores. Record submission
order does not change the report. Source and record-population digests are
retained alongside caption policy and explicit choice draws.

The new `mnemosyne.locomo-native-replay/v1` report intentionally separates
`native_evidence_recall` from upstream retrieval reporting. It uses exact source
dialog-ID membership, yields zero for an observed empty retrieval against
nonempty evidence, and yields null for empty gold evidence. Its category mean
includes only cases with an executed projection and applicable gold evidence;
that count and missing QA count remain visible. No upstream fallback value of
one is represented as observed retrieval. This is a disclosed native metric,
not a retroactive change to the original upstream scorer.

The combined isolated suite passed 103 tests. Extended population checks then
passed all 26 scorer tests, covering all five categories, submission-order
invariance, empty retrieval, no-gold applicability, timeout missingness,
duplicate/tampered records and option-order custody. Ruff passed. The report
keeps runtime custody and publication authorization false. It is offline
structural/score replay, not signed execution evidence, registry admission,
model-quality proof or a completed native adapter run.

Completeness refinement: native reports now distinguish
`source_population_complete` (every supplied question has a projected response)
from `complete` (that condition plus nonempty coverage of all five categories).
`absent_categories` and per-category completeness remain explicit. A synthetic
single-category population with every question answered is therefore not marked
as a complete LoCoMo report. All 26 scorer tests, including this regression,
passed; Ruff passed. Even the stricter complete flag does not establish admitted
dataset coverage, runtime authenticity or publication eligibility.

Replay resource refinement: population replay now prepares each conversation's
normalized inputs, evidence map and capture digest once, then reuses that local
context across its questions. Previously those full-conversation operations were
repeated for every answer record. Contexts own copied question/annotation data
and remain local to the invocation; there is no global cache or cross-run state.
The public single-record verifier continues to prepare its own independent
context. Existing tamper, complete-population and order-invariance tests still
exercise the same verification rules. This reduces repeated preprocessing by
construction, not a measured wall-time or RAM performance claim.

## Native execution sequence

`iter_native_answers` now validates the complete supplied population, caption
policy and exact category-5 choice map before any capture. Transformed queries
must fit the existing 2,000-character public query contract; overlong inputs
fail explicitly rather than being truncated. The sequence copies its option
choices at startup, captures isolated conversations, then yields one retained
record per question in original source order. Caller mutation of the choice
map after the first yield does not change subsequent prompts.

The caller must admit the data/runtime before use and persist each yielded
record in its attempt ledger. Exceptions stop execution without retries or
invented completion. Previously yielded records remain available to the caller;
temporary stores are cleaned when the context unwinds. This sequence does not
itself provide signed attempt persistence or replace the public runner's gates.

All 24 native tests passed. Sequence tests used real public captures with a
synthetic answer transport to verify full population order, retained progress
before a later failure, no automatic retries, choice-map isolation and cleanup.
Invalid choice maps and overlong questions failed before capture. Ruff passed.
Real model execution, signed persistence and neutral registry integration remain
open.

Early-stop verification: callers that do not exhaust the sequence must use
`contextlib.closing(iter_native_answers(...))` or explicitly call `close()`.
The native regression now pauses after the first yielded record, confirms the
store is live, closes the sequence and verifies immediate cleanup with no
additional answer invocation. All 24 native tests and Ruff passed after this
addition. A plain loop `break` alone is not documented as immediate cleanup.

## Sequential store lifetime

The native sequence now captures and answers one conversation at a time, closing
its temporary store before capturing the next. The entire supplied population
and option map are still validated before the first public capture; question
order and full denominators are unchanged. The input population is copied at
iterator startup so caller changes between yields cannot alter later captures
or questions. This bounds simultaneously live conversation stores to one; it is
not a measured RAM ceiling or a successful grounded-model resource preflight.

All 24 native tests and Ruff passed. The public-CLI sequence test verifies that
previous conversation stores no longer exist when a later conversation answers,
that post-start source mutations do not change offline replay, and that failures
and explicit early closure still release stores. Neutral bundle integration,
real-dataset admission, runtime preflight and official measurements remain open.

## Isolated scorer process boundary

`eval.public.adapters.locomo_replay.replay_in_environment` now invokes the
existing pinned scorer with an explicitly supplied Python executable. Isolated
Python mode ignores ambient Python paths and user packages, while the bootstrap
loads the repository's evaluation code and public identity helper. This leaves
Mnemosyne's production dependencies unchanged; it installs no packages and
performs no model execution. The worker checks all scorer dependency pins even
when every answer is missing, then runs the existing native population replay.

Requests and responses use finite, duplicate-key-free JSON with a 64 MiB
transport bound. A SHA-256 receipt binds the returned report to the exact
request bytes. The parent enforces a finite positive subprocess timeout, reads
bounded output from a temporary file, and fails on worker errors, invalid JSON
or receipt mismatch. This is local consistency checking with a trusted selected
interpreter, not interpreter attestation, signed custody or a memory/RSS bound.

Validation: all 110 isolated ingestion/scoring/tokenizer/process tests passed;
all five categories matched the in-process report through the subprocess. Seven
process-boundary tests also passed from the production Python 3.14 environment
using the pinned Python 3.11 scorer, including a scored synthetic answer,
missingness, tamper rejection, malformed JSON and timeout propagation. Ruff and
CI YAML parsing passed. CI includes this boundary in the isolated scorer job.
The prior remote CI head `df99593b` passed all nine gating jobs; a new-head CI run
is still required for the accumulated local changes.

CI correction: GitHub rejected workflow head `3d132c74` before dispatch because
`runner.temp` was used in job-level `env`, where the runner context is unavailable.
The earlier YAML parse only proved syntax, not GitHub's context rules. Moved the
same vocabulary path into the download/test step environments, where runner
context is supported. No test, runtime pin or acceptance gate was removed.

## Replay policy and saved-report verification

Native reports now disclose `mnemosyne.locomo-native-scoring/v1`, the pinned
upstream revision and scorer dependencies, source-dialog capture format,
question/abstention transformations, per-case rounding, separate QA/recall
denominators and the absence of an overall rank. The policy includes SHA-256
hashes for its seven listed replay/public-boundary source files and is itself
digest-bound. Caption policy and exact category-5 choices remain explicit in
each report. These are replay-policy identifiers, not a SUT/model manifest or
proof that the listed files cover an entire runtime.

`verify_report_in_environment` recomputes the report in the selected scorer
interpreter and compares every field using canonical finite JSON. Modified
metrics, caption policy, dependency declarations, policy digest and even a
boolean replaced by numeric zero are rejected. A changed implementation must
be replayed in its original checkout rather than silently treated as identical.
The returned record still denies runtime-custody verification and publication.
Actual dataset admission, candidate/model bindings, signed attempts and neutral
bundle dispatch remain separate unfinished integration requirements.

Validation: all 110 isolated tests passed, including all-category subprocess
parity and saved JSON report roundtrip/tamper checks. Seven process tests also
passed from the installed production Python 3.14 environment into the pinned
Python 3.11 scorer. Ruff and diff checks passed. Remote CI at `046f08a8` now
successfully executes the LoCoMo scorer job and lint; the full suite/platform
jobs were still running at this checkpoint. This local policy change waits
for that run to finish before another push.

## Answer rendering and synthesis boundary

Native projection now enforces the public output's structural guarantees:
non-abstaining answers require claims and must render their ordered text exactly;
claims require nonempty bounded text, unique citations, ordered span/citation
agreement, valid span hashes and non-overlapping ranges. Up to 20 claims and
16 spans per claim preserve the product's synthesis capacity. Abstentions may
not retain claims. The previous synthetic transports that supplied successful
answers without claims were corrected to supply real source-bound quotations.

Inspection of `src/mnemosyne/answering.py` showed a necessary distinction:
`AnswerClaim` retains text, CIDs and spans but not the synthesis operation that
produced derived text. Requiring all claim text to equal joined quotations
would reject legitimate deterministic synthesis and misrepresent native memory
behavior. Projection therefore records per-claim `claim_text_custody` as either
`exact-quoted-spans` or `derived-text-unverified`, preserving both answer types.
The latter proves citation structure only, not the derivation. Completing
native derivation replay needs versioned public synthesis provenance; it must
not infer a missing operation or import private engine state as evidence.

Validation: 32 native tests passed, including malformed rendering/citations and
preservation of derived output. All 110 isolated scoring/tokenizer/replay tests
passed. The native recall test now uses a valid quoted answer from a different
source turn than the annotated gold evidence, retaining the zero-recall case
without constructing an impossible successful answer with no claims. No
product API, BurnOS contract, quality target or publication gate was changed.

## Opt-in public derivation trace

The public `eval-answer-batch` command now accepts `--include-derivation`.
`MnemoCLI.eval_answer_batch(..., include_derivation=True)` forwards the option.
Without it, claim and response keys remain unchanged. The option adds one
`derivation` object per claim with schema `mnemosyne.claim-derivation/v1`,
`kind` (`quotation` or `synthesis`) and `operation` (null for quotations or the
validated synthesis operation). Existing span offsets and hashes remain the
source of operands; raw evidence content is not added to the trace.

The grounded answer host now retains the operation after it validates and
executes the synthesis proposal. This closes the public-observability gap noted
above without changing the reader protocol, model invocation, default answer
serialization or BurnOS endpoints. The native LoCoMo adapter does not yet opt
into this field; consuming it and independently replaying derivations remains
the next integration step. The field alone is not proof of provider authenticity.

Validation: the existing 133-test grounded-answer/public-CLI/BurnOS group passed.
The public-CLI roundtrip was then expanded to cover both quotation and arithmetic
synthesis, and both cases passed: the latter derived 4 from source operands 1.20
and 2.80. In each case, removing the opted-in provenance gave the exact default
response; input stores remained byte-for-byte unchanged. Unit checks also
retained arithmetic/date operations through the public serializer. Ruff passed.

## Native derivation replay connected

Native answer execution now requests the public derivation trace and retains
`command_options.include_derivation: true`. Both execution and saved-record
verification reject nonempty claim lists missing the requested receipts. The
native projection accepts the versioned optional claim field and reconstructs
operands from the already verified CID/span pairs. Synthesis operands must also
be unambiguous within their captured source content.

`eval/public/derivation.py` independently verifies quotations, exact rational
arithmetic and calendar composition using the standard library; it does not
call the product synthesizer. It preserves operation ordering, decimal bounds,
canonical output and the declared five-operation allowlist. No arbitrary code
or numeric-expression evaluation is permitted. Verified synthesis is labeled
`replayed-deterministic-synthesis`; legacy receipt-free projection still exposes
`derived-text-unverified`, but new retained native records require receipts.
Older developmental records must use their original verifying checkout.

The replay protocol now fingerprints eight listed source files including this
verifier. Runtime/provider authenticity, dataset admission and signed neutral
bundle integration are still outstanding; replaying a calculation does not
prove those conditions or establish benchmark superiority.

Validation: 135 isolated checks passed, including 25 derivation checks and 200
seeded arithmetic comparisons with the product contract. The initial isolated
run exposed a test-only package import that pulled in production dependencies;
the parity test now loads only the standalone standard-library provider file,
without expanding the scorer environment. All 41 production-environment native,
cross-interpreter and public-CLI roundtrip checks passed. The latter exercise
real public captures and a synthetic provider for quotation and arithmetic,
then verify the emitted derivation through the independent native projection.
Ruff, diff checks and CI YAML parsing passed. Remote CI remains in progress on
`046f08a8`; these subsequent commits remain local to avoid cancelling it.


## Reproducible native option ordering

`native_choice_policy` now resolves either a complete explicit draw map or an
unsigned 64-bit seed, never an ambient/default seed. Seeded mode draws from a
local Python `Random.random()` instance once per category-5 question in original
source order. Both the sequential public adapter and isolated scoring worker use
this same policy. The report retains its versioned identity, seed and exact draws;
changing the seed or relabeling seeded draws as explicit inputs fails saved-report
verification. Original upstream question/decoder semantics remain unchanged.
This native generation policy does not claim the upstream script's RNG state,
pre-execution registration, provider execution or dataset admission.

Validation: 144 isolated conformance tests passed, 48 production native/reader/
replay tests passed, and an additional Python 3.14-to-3.11 seeded replay test
passed. Both option orders, invalid/ambiguous seeds, unchanged ambient RNG state,
changed policy, missing outputs and retained full denominators are exercised.


## Native configuration binding checkpoint

`locomo_config.py` defines a closed `mnemosyne.locomo-native-config/v1`
declaration. `build_native_run_config` binds the full source and normalized input,
current replay source/protocol, caption/reader/choice policies, runtime and
resource manifest SHA-256 references, and local CLI backend/flags/timeout.
Flag values are represented by a canonical digest rather than copied into the
artifact, since a flag may contain a credential. Store paths are intentionally
excluded: execution uses fresh per-conversation stores. Environment, interpreter,
provider and effective context identity still require the runtime/resource
artifacts and their authentication; this declaration does not infer them.

Pass `run_config` to `iter_native_answers` together with the same caption,
reader and explicit/seeded choice policy. It validates the source/configuration
before capture and the CLI again before each question. Each returned record
retains `run_config_sha256`. Full-population replay and the isolated worker
accept the same configuration, recompute its input bindings, check every
record’s digest and retain the declaration in the report. Configured records
require full-population replay; the single-record helper remains for unconfigured
structural checks. Missing configuration, changed source, policy, CLI settings or
artifact references reject the configured record/report path.

The configuration is optional for existing development calls and never sets
runtime custody or publication authorization true. A caller-supplied artifact
hash is a reference, not verification of that artifact. Registered execution
still needs pre-access registration, candidate/runtime checks, resource admission,
retained attempts and neutral bundle integration. No real LoCoMo data was used.

Validation: 145 isolated tests passed, 49 production native/reader/replay tests
passed, and the expanded 15-test reader/configuration suite passed. Coverage
includes a real public capture path with a synthetic empty-reader response,
cross-interpreter configured replay, changed artifact/input bindings, pre-capture
CLI drift rejection and malformed declarations. Ruff passed.


## Referenced native artifact verification

`verify_native_artifacts` now reads bounded regular JSON files for the candidate,
installed runtime manifest and resource artifact, rejects symlink paths, and
checks their raw bytes against the configuration references. The candidate must
match the current clean Git HEAD and its exact reader policy. The existing
`grounded_runtime_environment` verifier checks the installed tree against that
candidate’s committed source, so a forged runtime with fresh file hashes still
fails. Referenced files are checked again for changes before returning.

`verify_report_in_environment(..., runtime_artifacts={"candidate": path,
"runtime": path, "resource": path})` applies this optional artifact gate before
starting isolated score replay. It does not alter the worker’s report or promote
its runtime/publication flags. Standalone file-verification receipts distinguish
`runtime_files_verified` and `resource_artifact_hash_verified` from the still-false
`resource_preflight_verified`, `model_execution_verified` and
`publication_authorized`. No provider command or network/model call is executed.

A synthetic Git repository and installed runtime test proves valid file custody,
rejects changed resource bytes, symlink references, dirty candidate source and
forged runtime files even after rehashing. A deliberately failed resource JSON
artifact remains only hash-verified, never a passing resource gate. The saved-
report entry point rejects changed artifacts before the scorer starts. All 29
runtime-installation, cross-interpreter replay and reader/configuration checks
passed together; Ruff passed. Effective provider/model loading, context coverage,
resource admission, signed attempts and registered neutral bundles remain open.


## Development category-summary projection

The existing result-v2 metric contract required a numeric value and interval for
every entry. It could not accurately represent absent native categories or
undefined evidence-recall means, and its `judged_qa` family requires a model
judge. Native reference scoring does not use such a judge. Added an explicit,
closed `locomo-native-category/v1` summary variant for development records only,
with `reference_qa` and `retrieval` kept in separate homogeneous metric lists.
The legacy metric shape and result-v1 contract are unchanged.

Native replay now emits `category_metrics` for all five categories in both
families. Each summary retains numerator, denominator, source/observed/missing/
not-applicable counts, scorer digest and a derived status. QA preserves the
original full-source denominator, including missing-answer zero contributions;
its incomplete aggregate is labeled explicitly. Recall divides only by executed
questions with applicable gold evidence. Zero denominators retain null values.
Absent categories, incomplete observations and inapplicable recall remain
separate states. Intervals are null with `uncertainty_method: not-estimated`;
no fabricated CI or model-judge declaration is added.

Both JSON Schema and runtime validation accept the development variant, while
runtime checks enforce exact count/ratio/status arithmetic. It does not open an
official/publication path. Rendering displays missing values as a dash plus
status/counts, and explains missing-answer contributions to QA aggregates.
Comparison groups retain excluded category names/reasons, require matching
scorer context and keep descriptive summaries separate from legacy metrics.
No overall score or rank is calculated.

Validation: 145 isolated scorer tests passed, including native projection and
replay; 558 leaderboard/rendering/comparison/native/reproducibility checks passed.
The 21 new category-summary checks cover valid/absent/incomplete/inapplicable
values, arithmetic tampering, schema agreement, v1 rejection, publication/track
restrictions and visible comparison exclusions. Ruff passed. An initial schema
rule was inserted at the wrong nesting level; the contract test caught it and
the corrected root-level rule is covered by explicit official/publication
rejection checks. Full result-record construction, registered bundle integration,
preregistered uncertainty and real admitted execution remain open.


## Atomic-result assembly boundary and trace visibility

The accepted WMBS §9.5 identity contains no metric-family discriminator and
requires one immutable record per full atomic attempt identity. The comparison
contract rejects duplicate identities, while result-v2 keeps metric families
homogeneous. Do not create two attempt records or invent run/module/attempt IDs
to display QA and retrieval from the same native execution. The native result
assembly path should retain primary reference-QA category metrics in the single
atomic record and expose the separate retrieval category summaries through its
bound native replay artifact and supplementary view. All raw summaries remain
in `category_metrics`; none are discarded or blended into QA.

Registered record assembly still requires actual identity, artifact and resource
metadata from the registered run. Offline replay cannot invent these fields.
Its implementation must bind the single record to the source/configuration,
raw traces and replay report through the existing bundle verifier, and preserve
missing/failed attempts without manufacturing a completed run.

The trace renderer previously displayed only generic QA/retrieval fields,
leaving native request/response records mostly blank. It now shows native
projection status, the public request and its byte digest, option transformation,
scorer prediction, retrieved source IDs, claim checks, reader-policy match,
runtime-custody flag, configuration digest and original response. Every trace
also offers an escaped complete stored-JSON view for fields outside the named
layout. These are displayed records, not new execution attestations.

All 75 focused rendering/native-summary checks passed, including native false-
custody visibility, HTML escaping and unchanged raw downloads. The local site
was regenerated from the existing signed retrieval result; the served complete-
trace view and byte-identical raw download were checked. No synthetic native
result or additional competitor result was added to that preview.

## Development atomic-result projection

`eval/public/adapters/locomo_results.py` now assembles one development-only
reference-QA result from explicit metadata and immutable artifact bytes. It
checks the complete manifest inventory and raw digests, candidate/public-seam
binding, source identity, seed, adapter protocol and full scorer replay before
returning a schema-valid record. All five retrieval summaries remain in the
same bound replay artifact; no second attempt identity is invented.

Replay alone cannot establish execution, resource or safety admission. This
projection therefore requires not-measured, resource-unverified, operator-run
development metadata and rejects promoted safety or publication claims. Even a
complete synthetic answer population remains unverified execution. This helper
does not write a registered bundle, enter the common bundle verifier or grant
runner admission. Those integration steps and real measured execution remain
open; the earlier full-record-construction checkpoint is advanced only for this
explicit development projection.

Validation: 13 assembly tests passed both through production Python 3.14 to the
isolated scorer and within Python 3.11. The broader isolated suite passed 157
tests before the final answered-population test was added; that added test is
included in both 13-test passes. Rejections cover mutated/rehashed source and
reports, identities, seeds, manifest bytes and promoted evidence claims. Ruff,
diff whitespace and workflow YAML parsing passed. CI now includes the assembly
suite; this local validation does not claim a completed GitHub run.
