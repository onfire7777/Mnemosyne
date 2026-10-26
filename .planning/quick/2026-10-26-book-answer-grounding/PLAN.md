---
phase: quick-book-answer-grounding
plan: "01"
autonomous: true
requirements: [BA1, BA2, BA3, BA4]
---

# Book answer grounding continuation

Baseline: `97091695ccd90330e8300804524bd5b2d3043c7a`.
The preceding goal turn made progress: whole-book conversion fixes and their
verification records were pushed. This continuation improves the downstream
answer path; it does not redefine the broader memory-quality goal as complete.

## Constraints and findings

Use the user's Karpathy guidance and scoped GSD plan/review/verification loop.
No full benchmarks or model-provider inference. Use local synthetic regressions,
retain unrelated work, and commit/push verified fixes to main. Mnemosyne and
Mnemetric remain independent. Historical benchmark acceptance stays open.

Two independent read-only audits reproduced:

- A large first-ranked item stops selection of smaller useful items.
- Preserved chapter contribution fields are absent from the search index.
- Independently selected framework nodes can lack their cited source passages.
- Rendered contribution payloads can exceed the estimate and hard request bound.
- Answer coercion accepts string booleans, malformed text and unavailable citations.

## Work and acceptance

1. **BA1 — Evidence-aware context selection.** Rank complete original contribution
   views, preserve identity and provenance, pack the actual serialized content,
   continue past oversized candidates, and reserve each selected view's cited
   source passages. Retain bounded source retrieval and expose partial coverage.
2. **BA2 — Strict answer contract.** Validate input selections and returned answer
   types. A successful answer requires nonempty text and valid integer citations
   limited to the source actually supplied. Invalid output must abstain without
   repeating unsupported generated claims as an accepted answer.
3. **BA3 — Local evidence and independent review.** Regression tests reproduce the
   defects with real lexical scoring and deterministic model doubles. Run the
   affected book suite, review integration and failure paths, and retain source
   hashes and receipts. Inspect current CI failures separately; do not infer that
   pending or ancestor CI proves the new source passed.
4. **BA4 — Documentation and delivery.** Explain retrieval coverage and remaining
   semantic limits, record actual results, and push the reviewed change to main.

Ownership: context selection in `skills.py`; rendering/validation in
`frameworks.py`; disjoint regression files. Integrate only after both owners freeze.
This is not a new storage format or a replacement for whole-book conversion.
Complete source retention and valid citation IDs do not prove semantic accuracy.

## Confirmed CI repairs within the ongoing memory-quality goal

- **CI1:** The role validator omits `documents` from its default exception list,
  although `infra/postgres/roles.sql` already grants its table-owner DELETE for
  the branch foreign-key cascade. Add that existing narrow exception, bind the
  regression to the SQL grants, and verify real restricted roles. Do not change
  database permissions or weaken evidence/audit deletion checks.
- **CI2:** The native answering worker publishes a completed result before its
  admission permit is released. Release the permit after inference and before
  completion publication; prove the next request can enter while preserving
  timeout protection for inference that is still running.

These findings came from ancestor CI run `40400787108`, not an assumption that
the latest run had passed. Retain the exact diagnostics and focused local tests.
