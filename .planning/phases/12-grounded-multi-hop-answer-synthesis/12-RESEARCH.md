# Phase 12 Research

## Existing Seams to Reuse

- `run_retrieval_pipeline` already composes dense, lexical, graph/PPR, fusion,
  rerank/MMR, budget, provenance, Standing, grounding floor, confidence, and
  retrieval abstention across Local/Postgres/SQLite engines.
- All three engines already implement tenant/branch/access-filtered `graph_ppr`.
- Evidence models already carry CID, session, source identity, metadata,
  validity, trust, sensitivity, and provenance fields.
- `infra/providers/role-llm.py` already provides a shell-free, JSON-mode,
  temperature-zero, SSRF-checked Ollama command boundary with schema retries and
  data-not-instructions framing.
- `infra/providers/role-ladder.py` plus `infra/profiles/self-hosted.env` provide
  the installed command transport/configuration seam. Phase 12 extends that
  transport with bounded `query_decomposer` and `grounded_reader` roles rather
  than hardwiring a repo-relative executable.
- `qa-em-f1-v1` scoring exists, but public runner/verifier registration and
  disclosed reader/judge bundle metadata do not.
- LongMemEval source assets contain answers for all 500 questions, while the
  Phase 11 retrieval adapter intentionally omits answer text.

## Current Evidence

- `qa_hard_v2` has 24 frozen internal cases. Current retrieval is Recall@5 1.0
  and nDCG@5 1.0, but the context-presence judge scores 0.25; no reader answer is
  produced, so this is not CAP-003 evidence.
- Phase 11 frozen retrieval points are recorded in
  `eval/reports/phase-11-evidence.md` and must not regress.
- All three HippoRAG retrieval tracks currently report zero positive graph/PPR
  participation, so BENCH-005 remains partial independently of EM/F1.

## Primary Risks

- Caller-context loss across hops can bypass purpose, capability, sensitivity,
  residency, tenant, or branch boundaries.
- Unknown-versus-filtered CID errors can leak protected existence.
- Reader-supplied citations can launder unsupported claims unless validated
  outside the model against the authorized assembled evidence set.
- Raw `get_evidence` is not an authorization check. Validation must use an
  immutable authorized-CID map created from hop results, then re-run the same
  authorized retrieval context and compare an active-evidence fingerprint
  before emission to fail closed on concurrent validity/access changes.
- Oracle answer/session/turn labels can leak into prompts if scoring and runtime
  records are not separated.
- Temperature zero does not make a reader byte-deterministic; model revision,
  prompt digest, decoding config, and output custody must be disclosed.
- The original v1 preregistration hashed only a short reader instruction and a
  serializer identifier. Before any held-out attempt, v2 replaced it with
  complete role custody for both decomposition and reading, including the
  injection boundary, schema, DATA framing, and concrete serializer behavior.
- Ollama tag strings are insufficient identity. Provider preflight must resolve
  and bind the local model content digest; the prompt digest covers system/user
  templates plus evidence serialization, and the decoding digest covers every
  generation option.
- Iterative held-out error inspection would violate RAIL-004 even though the
  local assets are readable.
