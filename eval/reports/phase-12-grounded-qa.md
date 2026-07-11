# Phase 12 Grounded QA Evidence

Status: preparation only — no frozen or held-out result exists.

## Preregistered Candidate

- Protocol: `phase12-candidate-v3`
- Reader/decomposer: local Ollama `qwen3:4b`, exact content digest required
- Transport retries: zero; maximum attempts per protected split: one
- Evidence: at most 20 records, 24,000 characters, and 3 hops
- Canonical abstention: empty answer, empty claims, `abstained=true`
- Candidate manifest: must be created outside the repository after a clean
  candidate commit and immutable commit-addressed runtime installation

## Prepared Gates

- Public-CLI-only internal QA evaluator with frozen-dataset execution guard
- Scorer-only gold labels and payload-isolation tests
- LongMemEval-QA question-set/answer anchoring with separate reader columns
- Hippo reader EM/F1 and provenance-linked graph/PPR participation columns
- Exact Phase 11/internal retrieval no-regression comparator
- Candidate/report custody and non-publication schema

## Results

Not run. `qa_hard_v2`, LongMemEval-QA, and Hippo reader evaluation remain
protected one-shot actions after the candidate commit, external manifest,
immutable runtime install, and successful configured provider smoke.

No CAP-001/CAP-002/CAP-003/BENCH-005 completion or public number is claimed.
