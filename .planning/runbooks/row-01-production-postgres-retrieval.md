# Row 01 - Production Postgres Retrieval

## Objective

Prove production retrieval over deployed Postgres adapters, not local fallback
paths.

## Real-Infra Dependency

ParadeDB BM25, Apache AGE, pgvector, and non-local embedding/reranker providers.

## Gate Commands

Run in the production soak profile:

- `retrieval-ops-check`
- `provider-check` for `retrieval_backends`

## Redaction Requirement

Evidence must not include raw tokens, keys, queries, documents, credentials, or
tenant-private retrieved text. Store only redacted summaries, provider names,
shape validation, latency, and pass/fail details.

## Acceptance

Operator runs the gates against real infra, evidence is redacted, the outputs
are included in `deployment-soak --evidence-dir` with production scope and
operator attestation, and `release-audit --require-production-validated` passes
with required output shapes present and empty findings.

Done when gate evidence over deployed adapters is in the bundle and
`release-audit` is ok.
