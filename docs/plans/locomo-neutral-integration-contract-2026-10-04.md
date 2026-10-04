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
