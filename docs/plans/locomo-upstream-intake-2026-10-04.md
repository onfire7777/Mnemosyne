# LoCoMo adapter intake — pinned source review

Status: initial source review and ingestion boundary implemented; full protocol parity, runnable adapter, dataset admission and measurement remain open.
Parent: [W4 neutral benchmark suite](../superpowers/plans/2026-07-15-W4-neutral-adapter-suite-plan.md).

## Source custody

Reviewed official `snap-research/locomo` commit
`3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376` on 2026-10-04.
The following UTF-8 source files were downloaded for inspection only, not executed:

| File | Bytes | SHA-256 |
|---|---:|---|
| `task_eval/evaluation.py` | 9441 | `8e3be5d57ff2ff9ec5cd05939592f468c5f3f1fd95d13e431932bdf6bf0fd6fd` |
| `task_eval/evaluate_qa.py` | 4381 | `dde7c1c6b5501486f96ce31398d6e49de76abbfa656e980b137e54fc69e9f6ee` |
| `scripts/evaluate_rag_gpts.sh` | 1038 | `7a066d13578e2793c00dc2850b2fb81caf34975763a8547bb3f09b99b6d544a2` |
| `LICENSE.txt` | 19347 | `41003d4a74749c0220e33dd415042164b5a1093ed401f36277234f772d22d3d0` |

[Official pinned source tree](https://github.com/snap-research/locomo/tree/3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376).
The supplied license is CC BY-NC 4.0. Source inspection does not grant a new
commercial-use or redistribution permission. Retain the current non-headline
policy and complete the existing rights review before release use.
No held-out conversation or answer data was inspected in this review.
No dataset SHA-256, normalized-data digest or measurement is invented here.

## Protocol details that the adapter must preserve

The upstream QA path uses category-specific deterministic scores, not one
generic exact-match score and not an LLM judge:

- Categories 2, 3 and 4 use normalized, Porter-stemmed token F1. Category 3 first
  restricts the reference to the text before its first semicolon.
- Category 1 splits comma-separated subanswers, takes the best predicted
  subanswer F1 for each reference subanswer, then averages over references.
- Category 5 recognizes two specific abstention phrases in the lowercased
  output. It is a phrase-based test, not semantic proof of appropriate abstention.
- Normalization removes punctuation and the words `a`, `an`, `the`, `and`.
  A substitute generic QA normalizer would change the protocol.
- The runner rounds per-case QA scores to three decimals before its statistics
  step. The statistics implementation still needs review before selecting an
  aggregate or claiming exact parity.
- Retrieval recall has separate session-ID and dialog-ID paths. Critically,
  the scorer supplies recall 1 when context/evidence is absent. Such fallback
  values must not be represented as observed successful retrieval. Preserve
  raw upstream outputs and label applicability; any corrected metric needs a
  separately named/versioned enhanced track.

The example RAG script has dialog, observation and summary modes, each with
its own top-k settings. These modes must not share an undifferentiated result.
The README describes ten conversations and image URLs/captions but no released
images. A text-only adapter cannot claim evaluation of the image content.

## Next implementation and evidence gates

1. Review and pin the statistics, prompting, retrieval and preprocessing source
   paths reachable from the chosen upstream mode. Freeze model/token budget,
   mode, top-k and truncation behavior before any scored run.
2. Admit the dataset through the existing asset-custody mechanism: record exact
   raw SHA-256 and size, rights, split role and no-tuning policy. Retain all
   categories; do not select favorable cases.
3. Build synthetic structural/conformance cases first, covering all five
   categories, repeated/empty evidence, session/dialog IDs, semicolon and comma
   rules, punctuation, stems, abstention and upstream per-case rounding.
   Scorer parity must be checked against the pinned upstream behavior rather
   than asserted from matching function names.
4. Normalize conversations with stable sample/session/dialog identifiers and
   separate scorer-only answer/evidence labels from the memory input. Preserve
   timestamps and declared caption policy; isolate each conversation's state.
5. Wire the adapter, scoring profile and frozen mode into the neutral harness.
   Retain per-category results, raw predictions, retrieved IDs, applicability
   and immutable configuration in the reproducible bundle. Do not report
   recall fallback 1 as measured retrieval.
6. Run model/resource preflight on unprotected inputs. Only then register and
   execute the actual benchmark; reproduce its bundle. The current blocked
   grounded-reader preflight is not waived by the fast retrieval-only run.

This intake does not close W4 Phase 1, its adapter acceptance criterion, or any
quality target. It prevents a generic F1 shortcut from being mislabeled as an
upstream-faithful LoCoMo implementation.

## Ingestion boundary and extended source review

`eval/public/adapters/locomo.py::split_samples` now separates source conversation
objects, query-only records and full scoring annotations. IDs bind sample ID and
original QA position without ambiguous delimiter concatenation. It preserves
category/evidence annotations exactly, including empty or parenthesized evidence,
and does not substitute generated observations or summaries for conversations.
It deep-copies inputs and rejects invalid categories, duplicate samples, absent
labels and non-finite JSON. This is an ingestion component, not a registered
runnable suite or a claim of upstream-equivalent scoring.

Further pinned files inspected (same upstream commit):

| File | Bytes | SHA-256 |
|---|---:|---|
| `task_eval/evaluation_stats.py` | 8398 | `d36bf596de05ea6f1c355e433167a8cd704bea3a3745277c650ac0c464bba139` |
| `task_eval/gpt_utils.py` | 15800 | `5fc977375878199735acd28fba5ae6f4d657fa0e000c0d2918a90c07b6035793` |
| `task_eval/rag_utils.py` | 8635 | `136a30a444a1b3a2533e71a5aa94f8b4f30f06f784b66528a8efcb6dbe50f6c7` |
| `requirements.txt` | 7941 | `c09ca9b9a54a4c78b316b546719712394855202b9e3c5d37c52aebb6d17c9936` |

The statistics path accumulates rounded per-case scores by category and divides
by total category counts, including rows without a metric. Its retrieval
accumulation requires nonempty evidence but retains total category counts as
the denominator. Preserve this as upstream reporting, while separately exposing
missingness; do not quietly recompute a more favorable denominator.

The GPT prompt path adds a date instruction for category 2. Category 5 explicitly
constructs two answer choices using the source answer as a distractor and random
choice ordering, then converts the selected option back to text. This is an
intentional protocol transformation, not permission to send all scorer labels
to the memory store. A replayable implementation must retain its choice order,
random state, prompt and raw/decoded output. Plain query-only ingestion does not
yet reproduce that prompt path.

The upstream retrieval encoders call CUDA directly and do not pin model content
revisions in these calls. The supplied environment export includes NLTK 3.8.1,
NumPy 1.26.0 and regex 2022.10.31 alongside Linux/CUDA packages. None were installed
or executed during this review. The unchanged CUDA path is unavailable on this
Mac; a disclosed CPU/MPS adaptation needs parity and resource evidence. Resolve
model content pins and transitive prompt/call helpers before run registration.

Validation: all 17 synthetic ingestion tests passed. No held-out input, model
execution, benchmark score or upstream parity result is represented by them.

## Explicit question transformation and decoder

`prepare_upstream_question` now applies the reviewed category-2 date instruction
and category-5 answer-choice transformation. Category 5 requires a caller-supplied
finite draw in [0, 1); the result retains that draw and the option mapping. It never
uses hidden global randomness. This is the question fragment only, not the full
model prompt, retrieval context, tokenizer or call configuration. The eventual
runner must still record the registered RNG state, actual prompt and raw output.

`decode_upstream_category5` preserves raw text alongside the decoded value. It
intentionally preserves upstream's permissive one-/three-character behavior,
including mapping `x` and `yes` to option B. It must not be advertised as semantic
validation. An improved decoder belongs to a separately versioned enhanced track.

Validation: all 34 ingestion/transformation tests passed. An additional local
parity check first verified the pinned `gpt_utils.py` SHA-256, extracted only the
reviewed pure `get_cat_5_answer` function, and compared 209 synthetic inputs; all
matched. No module imports, model calls or dataset examples were executed by
that parity check. The receipt is retained locally as `locomo-decoder-parity.json`.
Full scoring parity, resource preflight and suite admission remain unverified.

## Per-case scorer and measured-recall distinction

`eval/public/adapters/locomo_scoring.py::score_case` implements category-specific
upstream token normalization, Porter stemming, multi-answer matching, category-3
reference truncation, adversarial phrase scoring and three-decimal reporting.
It requires the exact versions in `eval/public/requirements-locomo.txt`; these
are isolated evaluation dependencies, not additions to the production package.
The verified local environment uses Python 3.11.16; Mnemosyne itself continues
to require Python >=3.12 and is not installed into this scorer environment.
No NLTK data download, model weight or upstream generation package is required.

The return value retains unrounded score, rounded upstream score, upstream
recall and rounded upstream recall. `measured_recall` is null and
`recall_applicable` false when the upstream value came from absent context or
empty evidence. A supplied empty context with nonempty evidence is rejected
because upstream would index its nonexistent first element. Category-level
aggregation must preserve its separately reviewed denominators; this function
does not yet perform aggregate reporting or claim full suite parity.

Validation: 52 tests across ingestion and scoring passed in the isolated
environment (34 ingestion/transformation plus 18 scoring tests). Those new
scoring tests explicitly require the pinned optional environment and skip in
a default environment without it; the 52-pass result is from their actual
execution, not a skip-only default run. Ruff and diff checks passed.

A local parity run verified the original `evaluation.py` SHA-256, extracted
only its reviewed normalization/F1/QA functions, and compared 2,000 synthetic
cases across all categories, punctuation/stems, empty strings, adversarial
responses, absent contexts, dialog IDs and session IDs. Scores, upstream recall
and reported rounding matched exactly. `locomo-scorer-parity.json` retains the
source hash, Python version and all installed dependency versions. This verifies
these functions on that population, not an upstream model run or held-out score.

To execute the focused tests after creating a separate Python 3.11 environment:

```sh
uv pip install --python /path/to/scorer/bin/python --require-hashes -r eval/public/requirements-locomo-test.lock
/path/to/scorer/bin/python -m pytest tests/test_locomo_scoring.py tests/test_locomo_ingestion.py -q
```

Remaining: source-complete prompt/retrieval contract, aggregate reporting,
pinned dataset admission, adapter/runner/bundle integration, permitted runtime
and resource preflight, then registered actual evaluation and reproduction.

## Category replay report

`score_prediction_set` binds decoded outputs to the full explicitly supplied
source population using ingestion IDs. It rejects unknown/duplicate IDs, extra
prediction fields and explicit null context. Absent outputs remain explicit
`missing-prediction` cases with null scores. All five categories remain present,
including categories with no source examples.

Per-category fields retain source/scored/missing counts, the sum of rounded
per-case scores, the upstream-style source-denominator mean, recall numerator
and mean, and observed/fallback recall counts. The upstream-style mean can be
zero for an unscored category with source examples, but its missing count and
`complete: false` are explicit; it is not a measured zero-score claim. Categories
without examples have null means. No overall average, ranking or publication
authorization is emitted. Original source order controls accumulation; order of
prediction submission does not alter the output or its canonical digest.

The report retains source/prediction SHA-256 digests for replay binding. These
are not substitutes for dataset admission, signed registration or model-execution
evidence. The input field is deliberately named `decoded_prediction`; this
scoring boundary does not claim to retain an unprovided raw model response.

Validation: all 59 ingestion and scoring tests passed in the isolated scorer
environment. New tests cover missing category outputs, full denominators,
three-decimal per-case accumulation, submission-order invariance, separate
fallback counts and malformed/ambiguous prediction populations. Ruff passed.
Adapter execution, asset admission, surrounding prompts and immutable neutral
bundles are still required before any real benchmark result.

## Asset hash verified; license admission remains closed

The exact upstream `data/locomo10.json` was streamed for hashing only. Its
2,805,274 bytes match Git blob `d95b872480b413d935821fdc3c84f8a8f5f29e73`;
SHA-256 is `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`.
The downloaded payload was not retained, parsed, used for question inspection
or scored. [Machine-readable intake evidence](../research/benchmark-intake/locomo-2026-10-04.json)
records the immutable URL, hashes and exact current loader rejection.

`eval/public/assets.py::validate_asset_spec` rejects `CC-BY-NC-4.0` because it
is outside the current license allowlist. This is a concrete admission gate,
not an absent-data problem and not permission to substitute a permissive
license label. No runtime registry entry was added and no allowlist was widened.
Resolving rights and the project's admission policy for the intended use is
required before this asset enters the benchmark runner. Synthetic component
work may continue; full LoCoMo measurement cannot be claimed from those tests.

The existing bundle writer also requires admitted suite/scoring contracts and
QA reader custody. Do not wrap the standalone replay report in an existing
retrieval bundle or generic QA profile to bypass those requirements.

## Continuous scorer conformance

The `LoCoMo scorer conformance` job in the existing CI workflow uses a separate
Python 3.11 environment, hash-locked test dependencies and a ten-minute timeout.
It runs only synthetic ingestion/scoring checks; no held-out assets, model
weights, API credentials or NLTK datasets are downloaded. An explicit pinned
runtime preflight runs before pytest so missing optional dependencies cannot
turn this job into a successful skip-only run. The regular production test
environment remains unchanged. No new scheduled automation was created.

`requirements-locomo-test.in` composes the upstream scorer requirements with
the pinned test runner; `requirements-locomo-test.lock` pins all resolved
transitive dependencies with hashes. Local verification reinstalled that lock,
passed the runtime preflight and executed all 59 tests successfully. The new
GitHub job still requires its own successful run after this batch is pushed.
