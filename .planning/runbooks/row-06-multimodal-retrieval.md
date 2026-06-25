# Row 06 - Multimodal Retrieval

## Objective

Prove production multimodal extraction, media embeddings, encrypted object
storage, and retrieval evidence.

## Real-Infra Dependency

Non-local media extractor, media embedding provider, and encrypted object store.

## Gate Commands

Run in the production soak profile:

- `multimodal-ops-check`

## Redaction Requirement

Evidence must not include raw media, transcripts, captions, extracted private
text, object-store credentials, or encryption keys. Store hashes, object
metadata, provider contract status, redacted extraction summaries, embedding
shape, and retrieval result metadata.

## Scope Note

This row is the operator-evidence side of FR-20 multimodal breadth. Local seams
and storage mechanics do not replace production extractor, embedder, and object
store evidence.

## Production Capture

Use the universal Tier B production capture flow in `infra/PRODUCTION-EVIDENCE.md`:
render the production soak manifest, run
`infra/scripts/capture-production-evidence.sh --preflight-only` as setup proof only, then run
`infra/scripts/capture-production-evidence.sh` for the real `deployment-soak` +
`release-audit` capture. The preflight output does not flip this row to Done.

## Acceptance

Operator runs the gate against real infra, evidence is redacted, the output is
included in `deployment-soak --evidence-dir` with production scope and operator
attestation, and `release-audit --require-production-validated --require-provider-forbid-local` passes with the
required output shape present and empty findings.

Done when extraction and media-vector retrieval evidence is in the bundle and
`release-audit` is ok.
