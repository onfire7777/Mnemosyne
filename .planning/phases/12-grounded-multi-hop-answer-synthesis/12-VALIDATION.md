# Phase 12 Validation Strategy

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
  protected ledger. Candidate v8 binds claims-only exact-CID generation with
  application-derived unresolved state before any next protected action.
- Run public LongMemEval-QA once across all 500 held-out questions after the
  candidate and `qa_hard_v2` result are frozen.
- Preregister transport retries. A provider failure consumes the held-out
  attempt; record partial/error counts and fail the candidate rather than
  silently rerunning or selecting successful questions.

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
