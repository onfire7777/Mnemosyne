# Row 04 - Consolidation Role Pipeline

## Objective

Prove supervised consolidation workers and role providers execute against the
production Postgres/runtime state.

## Real-Infra Dependency

Supervised Postgres worker plus model-backed extractor, summarizer, and entity
resolver providers.

## Gate Commands

Run in the production soak profile:

- `consolidation-ops-check`
- `worker-run`
- `worker-ops-check`
- `projection-recompute-once`
- `gate-suite-check`

## Redaction Requirement

Evidence must not include raw documents, raw prompts, private extracted text, or
provider credentials. Store job IDs, redacted role outputs, queue metrics,
provider contract status, recompute fingerprints, and protected-suite metadata.

## Acceptance

Operator runs the gates against real infra, evidence is redacted, the outputs
are included in `deployment-soak --evidence-dir` with production scope and
operator attestation, and `release-audit --require-production-validated --require-provider-forbid-local` passes
with required output shapes present and empty findings.

Done when supervised worker, provider, and projection evidence is in the bundle
and `release-audit` is ok.
