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

## Acceptance

Operator runs the gate against real infra, evidence is redacted, the output is
included in `deployment-soak --evidence-dir` with production scope and operator
attestation, and `release-audit --require-production-validated` passes with the
required output shape present and empty findings.

Done when extraction and media-vector retrieval evidence is in the bundle and
`release-audit` is ok.
