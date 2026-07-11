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
- Candidate protocol v2 binds the complete decomposer and reader system/user
  prompt bundles, response schemas, DATA framing, concrete canonical evidence
  serializer, and all decoding options. A short instruction or serializer label
  is not sufficient custody.

## Completion Boundary

Phase 12 completes CAP-001/CAP-002 only with structural trace and grounding
proof. CAP-003 requires both frozen `qa_hard_v2` and all-500 public
LongMemEval-QA point EM and token F1 at least 0.85, with no Phase 11 retrieval
regression. BENCH-005 also requires reader-produced Hippo EM/F1 and positive,
provenance-linked graph/PPR participation; otherwise it remains partial.
