# Phase 12 Grounded QA Evidence

Status: in progress — the consumed v3 frozen run failed systemically; no held-out result exists.

## Preregistered Candidate

- Protocol: `phase12-candidate-v8` (new candidate required; not yet executed)
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

The v3 `qa_hard_v2` one-shot was consumed and returned 24/24 empty
abstentions with zero retrieval hops. Aggregate-only diagnosis identified the
systemic pre-provider query-support gate; no protected question, trace, or
content was inspected. LongMemEval-QA and Hippo reader evaluation remain not
run. A new committed v8 candidate is required before any further protected
action.

Candidate v4 was rejected at the synthetic live-model gate because its initial
query used inferred intent terms rather than an independently retrievable
literal anchor. It never reached a protected run and has no attempt ledger.

Candidate v5 was also rejected at the synthetic direct-provider gate: the
model returned a possessive entity plus a general intent noun. It never reached
a protected run and has no attempt ledger. Candidate v6 adds deterministic,
source-bound anchor normalization before ordinary retrieval.

Candidate v6 was rejected at the synthetic exact-runtime gate. An external,
never-protected diagnostic transcript showed that the evidence-aware model
omitted `Helios` and the reader emitted contradictory unresolved claims with a
malformed CID. Candidate v6 never reached a protected run and has no ledger.
Internal diagnostics: `~/.local/share/mnemosyne/diagnostics/v6-synthetic-transcript/`
(`result.json` SHA-256 `a700ccd6546f8b02c9eac32097c17c91247d72ec3b7b7c6724f102501b68218a`,
`transcript.jsonl` SHA-256 `2d484f7f49dee2cf5018d0aa8e970d19575a6461d053ac96dca4164c7b2ef644`).

Candidate v7 was rejected at the synthetic exact-runtime reader gate when
Ollama returned a claims/unresolved contradiction despite the dynamic XOR
schema. It never reached a protected run and has no ledger. Diagnostics:
`~/.local/share/mnemosyne/diagnostics/v7-synthetic-transcript/`
(`result.json` SHA-256 `865be871bd417f68ba653c417b3610a95c5c846c36005ff35feea2f3c4d33e85`,
`transcript.jsonl` SHA-256 `d0e611354f89582578b4dc4a42bc1ff712d92542edc3188ab0a01bd73f828812`).

No CAP-001/CAP-002/CAP-003/BENCH-005 completion or public number is claimed.
