# Phase 12 Context: Grounded Multi-Hop Answer Synthesis

## Goal

Close Plan A S1 through a bounded retrieve-read loop that preserves caller
authorization on every hop, answers only from authorized provenance-tagged
evidence, cites active evidence CIDs for every claim, and abstains fail-closed.

## Locked Decisions

- Reuse the shared retrieval pipeline, existing engine PPR implementations,
  calibrated retrieval abstention, and existing Ollama role-provider boundary.
- Add one narrow answer-orchestration layer; do not fork ranking, graph, or
  provider infrastructure and do not add a required core dependency.
- Keep deterministic retrieval and reader QA in separate bundles and columns.
- Treat relation IDs as non-citable until resolved to authorized source
  evidence CIDs.
- Preserve the complete original read context across every decomposed query and
  hop. A hop may narrow access but never widen it.
- Represent that context with one immutable allowlisted `AnswerReadContext`
  carrying tenant, branch, principal/user, role, source trust, capabilities,
  purpose, residency, lawful basis, sensitivity, break-glass, and temporal
  scope. Tests compare every field at every hop.
- Let a schema-bound decomposer propose only bounded query strings. It cannot
  propose commands, filters, identities, or policy fields; orchestration owns
  and reapplies the unchanged read context.
- Keep generated answers ephemeral in Phase 12; no new durable write path.
- Public LongMemEval cleaned is a held-out test. Development uses new synthetic
  fixtures; the frozen candidate runs held-out evaluation once.
- Canonical abstention is `answer=""`, `claims=[]`, and `abstained=true`.
  Non-abstained output is rendered from an ordered atomic-claim list, avoiding
  brittle sentence-to-citation matching.
- QA correctness is not called calibrated until Phase 15 public-label work.
- Candidate protocol v6 binds the complete decomposer and reader system/user
  prompt bundles, response schemas, DATA framing, concrete canonical evidence
  serializer, role-specific Ollama JSON Schemas, and all decoding options. A
  short instruction, generic JSON mode, or serializer label is not sufficient custody.
- The v3 frozen attempt is consumed: aggregate output was 24/24 canonical empty
  abstentions with zero retrieval hops. No protected per-question trace or
  content was inspected. Aggregate-only diagnosis found a systemic pre-provider
  query-support gate, so any next protected action requires a new candidate.
- Candidate v4 was rejected at the synthetic live-model gate because its initial
  query remained an inferred intent phrase instead of an atomic literal anchor.
  No v4 protected attempt ran and no v4 attempt ledger exists.
- Candidate v5 was rejected at the synthetic direct-provider gate after it
  returned a possessive entity plus a general intent noun. No v5 protected run
  or ledger exists. Candidate v6 deterministically reduces model proposals to
  literal source-bound atomic anchors before ordinary retrieval.
- Candidate v6 failed only the synthetic exact-runtime gate and has no protected
  ledger. Candidate v7 deterministically traverses unseen authorized-evidence
  anchors and binds an exact-CID, resolved/unresolved XOR reader schema.
- Candidate v7 failed its synthetic exact-runtime reader gate and has no
  protected ledger. Candidate v8 uses claims-only exact-CID generation and
  derives unresolved state application-side.
- Historical candidate v8 (retired) failed its synthetic reader quality gate through copied-text
  corruption and has no protected ledger. Candidate v9 uses exact raw evidence
  spans with application-side reconstruction.
- Candidate v9 rejects non-string or empty evidence without coercion, renders
  ordered spans with one ASCII space, and hashes each raw slice as UTF-8.
  Public verification independently reconstructs claim text and hashes from
  benchmark capture custody and the exact authorized CID mapping.
- Candidate v9's authored-offset selector failed synthetic exact-answer quality
  and has no protected ledger. Candidate v10 uses `qwen3:8b` at manifest digest
  `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`.
  The model selects exact `{cid, quote}` substrings; application code derives
  the lowest raw occurrence, offsets, UTF-8 hash, and rendering without repair.
- Candidates v10-v16 were rejected or consumed under the documented immutable
  one-shot protocol while hardening answer-only quote selection, batch timeout
  custody, lowercase literal anchors, and evidence-only bridge traversal.
- Candidate v17 passed the expanded repeated synthetic gate and answered 2/24
  frozen QA items; 22 abstained before hop 0. Candidate v18 added a longest
  shared literal-token fallback and reproduced the same aggregate exactly.
  No protected question, answer, trace content, or per-ID failure was inspected.
  At that checkpoint no v19 candidate existed, so synthetic-only hop-0 redesign
  was required. Candidate v19 source custody now exists, but its external
  post-commit manifest and exact-scale receipt remain required before another
  protected action.
- Phase 12 already invokes host Ollama 0.24.0 directly at `127.0.0.1:11434`
  with `qwen3:8b` on 100% GPU. The production Colima performance apply does not
  accelerate this evaluator and remains outside this capture lane.

## Completion Boundary

Phase 12 completes CAP-001/CAP-002 only with structural trace and grounding
proof. CAP-003 requires both frozen `qa_hard_v2` and all-500 public
LongMemEval-QA point EM and token F1 at least 0.85, with no Phase 11 retrieval
regression. BENCH-005 also requires reader-produced Hippo EM/F1 and positive,
provenance-linked graph/PPR participation; otherwise it remains partial.
