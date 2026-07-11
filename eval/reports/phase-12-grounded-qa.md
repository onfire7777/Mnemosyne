# Phase 12 Grounded QA Evidence

Status: in progress — the consumed v3 frozen run failed systemically; no held-out result exists.

## Preregistered Candidate

- Protocol: `phase12-candidate-v12` (new candidate required; not yet executed)
- Reader/decomposer: local Ollama `qwen3:8b`, exact content digest
  `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`
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
run. A new committed v9 candidate is required before any further protected
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

Historical candidate v8 (retired) passed structural retrieval but corrupted exact evidence text
(`Q3 2026` became `Q3 2:026`) at the synthetic reader gate. It never reached a
protected run and has no ledger. Candidate v9 makes model-authored claim text
impossible by selecting replay-validated raw evidence spans.
Candidate v9 public traces retain rendered claim text plus only privacy-safe
span custody (`cid`, Unicode code-point `start`/`end`, and UTF-8
`slice_sha256`). Bundle verification reconstructs each slice and the
single-space rendering from the benchmark capture corpus and exact authorized
CID mapping rather than trusting trace self-attestation.
Candidate v9's model-authored offset selector failed synthetic exact-answer
quality and never reached protected evaluation; it has no protected ledger.
Candidate v10 replaces authored offsets with exact `{cid, quote}` selection.
The application rejects any non-substring and deterministically selects the
lowest raw Unicode code-point occurrence before deriving the unchanged public
offset and hash custody. The installed `qwen3:8b` manifest digest above was
verified locally for synthetic-only preparation; no protected run was made.
Candidate v10 was rejected at the repeated synthetic exact-answer gate because
both deterministic runs returned the full supporting sentence instead of the
shortest answer value. Retrieval remained perfect and two-hop; it never reached
protected evaluation and has no protected ledger. Candidate v11 makes the
answer-only minimality contract explicit while preserving exact raw-substring
selection, zero retries, and all frozen retrieval and authorization rails.
Candidate v11 was rejected at the repeated synthetic exact-answer gate for the
same full-sentence output and likewise has no protected ledger. Candidate v12
adds one generic, non-benchmark contrastive contract example so the local model
must distinguish an answer value from its supporting sentence; no rail, schema,
model, budget, or retry setting changes.

No CAP-001/CAP-002/CAP-003/BENCH-005 completion or public number is claimed.
