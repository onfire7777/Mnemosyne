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

## Remaining implementation sequence

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
