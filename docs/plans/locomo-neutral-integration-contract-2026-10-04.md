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
