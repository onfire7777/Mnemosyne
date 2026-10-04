# LoCoMo adapter intake — pinned source review

Status: protocol review completed; adapter, dataset admission and measurement remain open.
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
