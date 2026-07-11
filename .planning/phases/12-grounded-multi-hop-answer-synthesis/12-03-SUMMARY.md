---
phase: 12-grounded-multi-hop-answer-synthesis
plan: 03
status: complete
completed: 2026-07-11
requirements-completed: []
---

# Phase 12 Plan 03 Summary: Grounded Reader and Public Answer Surface

## Outcome

Mnemosyne now exposes bounded, ephemeral `answer` and ordered
`eval-answer-batch` commands over the existing authorization-preserving answer
orchestrator. The command ABI supports local-only, one-attempt query
decomposition and grounded reading; model output can propose claims but cannot
approve its own citations.

## Security and Custody

- Every non-abstained answer passes a second complete authorization replay and
  application-side validation against the replayed active CID set.
- Provider model identity is resolved before generation and confirmed unchanged
  afterward. Command/model/profile selectors and exact digests fail closed.
- Provider stdout/stderr are consumed with bounded streaming, so oversized
  command output is rejected before unbounded capture can occur.
- Candidate protocol v2 binds both complete role prompt bundles, schemas, DATA
  framing/render layout, the concrete canonical evidence serializer, all
  decoding options, and the complete generation request envelope.
- Evaluation mode disables durable HTTP embedding caches and rejects command
  lexical/graph retrievers. Store files and runtime sidecars remain byte-stable.
- Batch rows are fully prevalidated before provider execution, remain ordered,
  and expose only queries, channels, retrieved CIDs, claims, abstention, and
  validated reader custody—never evidence content, caller context, or denial
  reasons.

## Verification

- Focused orchestration/provider/public-QA suites passed.
- The broader CLI/runtime/security/parity/provider gate passed to 100% with five
  expected environment-gated skips.
- Ruff and `git diff --check` passed.
- Local Ollama exposes `qwen3:4b` with exact content SHA-256
  `359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`.

## Open Runtime Evidence

The production installed commands `/opt/mnemosyne/bin/role-llm` and
`/opt/mnemosyne/bin/role-ladder` are absent on this checkout. A direct local
Ollama decomposer smoke resolved the correct model but timed out, so no live
reader success or provider readiness is claimed. Plan 12-04 must retain this as
an explicit runtime evidence gate before any frozen or held-out attempt.

## Boundary

CAP-001, CAP-002, CAP-003, and BENCH-005 remain open until Plan 12-04 proves the
end-to-end grounding, live-provider, frozen QA, and non-regression gates. No
held-out QA attempt or external number was produced.
