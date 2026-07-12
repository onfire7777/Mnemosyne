# Phase 12 Validation Strategy

All hardware-intensive validation follows
`.planning/runbooks/HARDWARE-WORKLOAD-PREFLIGHT.md`. Model admission and
full-scale/protected runs fail closed when its memory, load, residency, GPU,
swap-delta, topology, health, or serialization gates do not pass.

## Development Gate

- New synthetic/dev multi-hop, temporal, contradiction, missing-hop, poison,
  prompt-injection, fabricated-CID, and episode-contiguity fixtures only.
- Unit/adversarial tests for hop/query/evidence/token caps, cycle/dedupe,
  deterministic trace ordering, caller-context propagation, existence-silent
  abstention, and zero answer persistence.
- Hash the primary store and all runtime sidecars before/after single and batch
  answer calls, including provider timeout, partial output, and aborted batches.
- Public traces contain only permitted evidence/grounding fields and generic
  abstention; internal denial reason codes never cross the normal CLI boundary.
- Shared Local/Postgres observable-contract tests for authorized trace shape and
  provenance closure; SQLite parity where the existing contract applies.

## Frozen Candidate Gate

- Preregister model revision/digest, prompt digest, decoding settings, evidence
  budget, hop cap, abstention rule, scoring profile, and dataset split roles.
- Verify candidate prompt custody against the aggregate digest of both complete
  role bundles and verify the concrete serializer and decoding digests; provider
  self-disclosure alone is not evidence.
- Synthetic provider checks must prove each role-specific Ollama JSON Schema is
  used; generic `format: json` is not an acceptable substitute.
- Commit code/config before `qa_hard_v2`; then write a no-overwrite external
  candidate manifest containing the resulting git SHA and all model/prompt/
  config digests. Verify that manifest before every one-shot run. Never patch against individual frozen
  failures without creating and preregistering a new candidate version.
- Candidate v3 consumed its `qa_hard_v2` attempt and failed systemically with
  24/24 empty abstentions and zero retrieval hops. No protected per-question
  inspection occurred; a new candidate must be committed and preregistered before another
  protected action.
- Candidate v4 failed the synthetic live-model gate before any protected run or
  ledger creation; its inferred intent query was not an atomic literal anchor.
  A new candidate was therefore required for any next protected action.
- Candidate v5 also failed its synthetic direct-provider gate and has no
  protected ledger. Candidate v6 then bound deterministic source-bound anchor
  normalization before its synthetic exact-runtime gate.
- Candidate v6 failed its synthetic exact-runtime gate and has no protected
  ledger. Candidate v7 then bound deterministic later-hop traversal plus
  dynamic exact-CID/XOR reader schemas before its reader gate.
- Candidate v7 failed its synthetic exact-runtime reader gate and has no
  protected ledger. Candidate v8 then bound claims-only exact-CID generation
  with application-derived unresolved state before its reader quality gate.
- Historical candidate v8 (retired) failed its synthetic reader quality gate and has no protected
  ledger. Candidate v9 binds replay-validated extractive spans before any next
  protected action.
- Candidate v9 synthetic validation covers strict string content, Boolean and
  integer offset boundaries, Unicode code points, cross-CID ordering, per-CID
  overlap, UTF-8 hashes, inert evidence instructions, trace privacy, and bundle
  mutations of text, offsets, hashes, CIDs, and evidence custody.
- Candidate v9 failed synthetic exact-answer quality and has no protected
  ledger. Candidate v10 preregisters exact quote selection with `qwen3:8b`
  digest `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`;
  tests prove non-substrings fail and repeated quotes choose the lowest raw
  Unicode code-point occurrence. Preparation remains synthetic-only.
- Candidate v17 consumed one protected attempt after passing the expanded
  repeated entity/lowercase synthetic gate. Aggregate-only results were 2/24
  answered, 22 zero-hop abstentions, EM/F1 0.08333333333333333, Recall@5
  0.08333333333333333, and nDCG@5 0.0625.
- Candidate v18 passed the same expanded synthetic gate and reproduced the v17
  protected aggregate exactly. No per-question protected data was inspected.
  This non-improvement blocks speculative v19 execution; redesign and validate
  hop-0 behavior on synthetic data first.
- Run public LongMemEval-QA once across all 500 held-out questions after the
  candidate and `qa_hard_v2` result are frozen.
- Preregister transport retries. A provider failure consumes the held-out
  attempt; record partial/error counts and fail the candidate rather than
  silently rerunning or selecting successful questions.
- Before every future protected attempt, run the canonical 24-question
  `qa_scale_dev_v1` dataset through the exact CLI batch wrapper and immutable
  candidate runtime. Require a no-overwrite receipt bound to candidate,
  runtime, dataset, and result digests with 24 non-abstained traces, EM/F1 1.0,
  and Recall@5/nDCG@5 1.0. Bind that receipt digest into the attempt ledger.

## Required Metrics

- `qa_hard_v2`: EM >= 0.85 and token F1 >= 0.85.
- LongMemEval-QA (500): EM >= 0.85 and token F1 >= 0.85.
- EM uses Wilson 95% intervals; token F1 uses fixed-seed bootstrap 95%
  intervals. Thresholds apply to point estimates unless the requirement is
  explicitly changed.
- Unsupported-citation and fabricated-CID rates are zero; every non-abstained
  claim closes to at least one authorized active evidence CID.
- Positive second-hop and graph/PPR participation is trace-visible for
  applicable multi-hop cases.
- QA abstention is scored from the canonical empty answer while retaining the
  explicit abstention flag; scorer tests lock this behavior.

## Regression Gate

- Phase 11 LongMemEval Recall@5/nDCG@5 and all three Hippo Recall@2/@5 point
  metrics do not decrease; additive reader work should keep retrieval traces
  byte-identical.
- `qa_hard_v2` retrieval remains Recall@5 1.0 and nDCG@5 1.0.
- Full locked tests, §31/§33 rails, provider/security/parity tests, Ruff,
  dependency isolation, secret scan, bundle/report verification, and exact-SHA
  CI are required. GitHub billing failures remain external blockers, not passes.
- Run a real configured command-provider smoke and, when reachable, a live
  self-hosted Ollama smoke. If unavailable, keep provider realism explicitly
  open rather than substituting mocks.
