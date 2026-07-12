# Phase 12 Grounded QA Evidence

Status: in progress — consumed v3, v13, v17, and v18 frozen runs remain below threshold; no held-out result exists.

## Preregistered Candidate

- Protocol source: candidate v19; external post-commit manifest pending
- Decomposer: deterministic `mnemosyne-extractive-hop0-v1`, exact policy-spec digest
  `623c47250430e7f3a00ce0f11053b9c5397d2efcddd89428b556c507fb50805d`
- Decomposer implementation SHA-256:
  `1f00f376e79385a52fabd6fd2013d993b4f6eae84cda1e4d0065d462f97e9c6b`
- Reader: local Ollama `qwen3:8b`, exact content digest
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
run. At that checkpoint, a new committed v9 candidate was required before any
further protected action.

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
Candidate v12 passed the repeated synthetic gate, then consumed its protected
attempt without a benchmark result because the outer CLI batch wrapper timed
out at 120 seconds. The ledger exists, the result file does not, and no
question-level protected data was inspected. Candidate v13 raises only that
outer frozen-batch process bound to 3,600 seconds; per-provider timeouts, zero
retries, protocol content, retrieval rails, and answer custody are unchanged.

Candidate v13 passed both repeated immutable-runtime synthetic gates, then its
single protected `qa_hard_v2` attempt completed with 24/24 canonical
abstentions, zero retrieval hops, zero claims, EM/F1 0, and Recall@5/nDCG@5 0.
Only these aggregate metrics and structural counts were inspected; no protected
question, answer, trace content, or per-ID failure was read. Result SHA-256:
`af3497af93d07abe86217cc7cfb8408ae3b41e38dd94cb67be23d7c76242ee2d`.
Attempt-ledger SHA-256:
`3addbc57c640c64c8bbc807bbcce348075ff3e54e10374c4fc1b851a5c3c3a9e`.
The held-out LongMemEval and Hippo reader runs remain blocked by the frozen QA
threshold, and publication flags remain false.

Candidate v14 addresses only the aggregate zero-hop class without inspecting
protected content: when a model proposal contains no recognized entity, the
normalizer may recover the exact token-identical source span as a query. The
fallback rejects command/policy terms and Unicode-confusable control labels,
retains the existing entity path when available, and still sends every query
through the unchanged retrieval support and authorization gates.

Candidate v14 passed the original entity synthetic case twice but failed the
new lowercase literal case twice: the first hop retrieved only the ownership
record, and the reader returned that record instead of the answer. It never
reached protected evaluation and has no ledger. Candidate v15 retains the exact
literal proposal and, only on the fallback path, adds trailing substantive
source tokens in reverse order within the existing four-query budget. This
lets lowercase bridge terms participate without changing any retrieval rail.

Candidate v15 failed both lowercase synthetic repetitions at hop 0 and has no
protected ledger. Synthetic-only direct decomposition showed the proposal
`project cobalt launch`; expanding the question predicate created an
unsupported mandatory query. Candidate v16 therefore keeps hop 0 to the exact
literal proposal and enables trailing-token expansion only on later hops, where
the source is authorized retrieved evidence.

Candidate v16 passed the entity case but repeated the first lowercase record in
both literal repetitions and has no protected ledger. Synthetic-only
evidence-aware decomposition confirmed the model repeated `project cobalt`
instead of proposing the unseen bridge. Candidate v17 extends deterministic
later-hop traversal to safe substantive tokens from authorized evidence in
reverse source order; control ranges, deny terms, budgets, and ordinary
retrieval authorization remain enforced.

Candidate v17 passed all four expanded synthetic gates, then its single
protected attempt answered 2/24 with three hops and canonical claims while 22
items abstained at zero hops. Aggregate-only metrics were EM/F1
`0.08333333333333333`, Recall@5 `0.08333333333333333`, and nDCG@5 `0.0625`.
No protected content or per-ID result was inspected. Result SHA-256:
`908d50dd3ce340ba09ccb1e248749d175b11cb5d1a96b2a1bcb484d0cfb69d11`;
ledger SHA-256:
`c3826c2e7f4777e9361086e7648ad7adcee3786f8cb1d50436ee7e6fa1d7fe45`.
Candidate v18 adds a fail-closed partial-proposal fallback: when no full literal
span matches, select only the longest substantive source token also present in
the proposal. Control and command terms remain ineligible, and the selected
token still passes through ordinary retrieval and authorization.

Candidate v18 passed all four expanded synthetic gates, then reproduced v17's
protected aggregate exactly: 2/24 answered, 22 zero-hop abstentions, EM/F1
`0.08333333333333333`, Recall@5 `0.08333333333333333`, and nDCG@5 `0.0625`.
No protected content or per-ID result was inspected. Result SHA-256:
`9c3fbb85704afceeff9a23d30fc6cabcc1f8e8aa80db9f1fb7d9ff2f300e303d`;
ledger SHA-256:
`5d68a738b3e3f7270e0f802a31c07e3425bf94516956df4027a2efb9a5781c41`.
Because v18 made no aggregate improvement, no v19 candidate was preregistered
at that checkpoint; the next action was synthetic-only redesign, not another
speculative protected attempt. Phase 12 evaluation already uses host Ollama 0.24.0 directly at
`127.0.0.1:11434` with `qwen3:8b` on 100% GPU, so the production Colima
performance apply would not accelerate this evaluator and remains deferred.

A host-Metal `qwen3:14b` feasibility probe was rejected before
preregistration: the model occupied 9.8 GB at 100% GPU on the 16 GB host,
reduced free memory to roughly 60 MB, and failed to produce a trivial one-token
response within 300 seconds. Repeating the probe with Colima fully stopped
still produced no trivial response within 95 seconds, ruling out the VM's
reservation as the limiting cause. The model is installed externally for
possible future use on larger hardware, but it is not a candidate on this
machine.

A synthetic-only `qwen3.5:9b` probe was also rejected before preregistration.
The 6.6 GB model fit with the production VM active and completed a cold trivial
request in 39.237 seconds, but it reproduced the decisive decomposition defect:
given the lowercase question it proposed `project cobalt`, and after receiving
authorized evidence that project cobalt belongs to team juniper it again
proposed `project cobalt` instead of the newly exposed bridge. No protected
attempt or ledger was created. A model substitution must demonstrate a real
bridge-selection gain before it can become a custody-bound candidate.

Two final task-specialized reader-family probes were stopped at the same
synthetic boundary. `ministral-3:8b-instruct-2512-q4_K_M` fit the active host
topology but returned an empty query list for the lowercase hop-0 Project
Cobalt case. `granite3.3:8b` returned two nonliteral invented search phrases at
hop 0; after authorized evidence exposed Team Juniper, it generated two more
Project Cobalt questions instead of selecting the new bridge. Neither model
reached answer-minimality, scale preflight, preregistration, or protected
evaluation. These results close model substitution as the immediate strategy.
At that checkpoint, the next protocol had to disclose decomposition separately
from the reader and pass a broader synthetic matrix before becoming candidate
v19.

Candidate v19 now wires a separately disclosed extractive hop-0 planner. It
emits at most one exact substring of the question, fails closed on
custody/control terms, and deliberately emits no proposal once authorized
evidence exists; the already-tested orchestrator remains the sole owner of
later-hop authorized-evidence traversal and seen-query filtering. A
versioned 16-case development matrix covers proper and multiword names,
acronyms, mixed alphanumerics, lowercase project/archive identifiers,
hyphenation, generic marker use, marker-plus-intent cases, missing identifiers,
deny terms, and Unicode-confusable control labels. Runtime, environment,
candidate-manifest, registry, public-bundle, and verifier custody bind the
decomposer policy spec and exact implementation bytes independently from the
reader. Candidate v19 still requires its
external post-commit manifest, repeated synthetic validation, and the
24-question exact-wrapper receipt before any protected attempt.

The 2026-07-12 formal local admission retry failed before any suite or model
work: the three memory-free samples were 24%, 25%, and 22% against the required
55% floor. Host and Colima VM load, model residency, topology, and concurrency
checks otherwise passed; two production services remained in their already
documented stale-Vault-chain restart loop. Read-only attribution found the
unrelated Cotypist application using about 3.28 GiB RSS. Nothing was
terminated, no threshold changed, and the failed admission consumed no
candidate or protected attempt.

A follow-up context audit found a second, older 21-container Mnemosyne
production stack still running under Docker Desktop while the current 20-
container stack runs under Colima. The stacks use different image/config
identities, and Docker Desktop owns the host port 443 listener. Although recent
Desktop API/stream/operator/test logs were idle, it remains a live persistent
service surface and was not stopped. The hardware gate now also rejects
duplicate live Mnemosyne compose projects across Docker contexts.

Future protected attempts now require a no-overwrite, candidate/runtime-bound
receipt from the canonical 24-question `qa_scale_dev_v1` dataset. The exact CLI
batch wrapper must complete all 24 traces with no abstentions, EM/F1 1.0, and
Recall@5/nDCG@5 1.0 under the same 3,600-second outer bound. The frozen attempt
ledger binds the receipt digest before execution, preventing another
small-synthetic-pass/large-wrapper-timeout loss like v12.

No CAP-001/CAP-002/CAP-003/BENCH-005 completion or public number is claimed.
