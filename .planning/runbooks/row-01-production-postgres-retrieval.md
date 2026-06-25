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

## Production Capture

Use the universal Tier B production capture flow in `infra/PRODUCTION-EVIDENCE.md`:
render the production soak manifest, run
`infra/scripts/capture-production-evidence.sh --preflight-only` as setup proof only, then run
`infra/scripts/capture-production-evidence.sh` for the real `deployment-soak` +
`release-audit` capture. The preflight output does not flip this row to Done.
After capture, reviewers may run `"$PYTHON" -m mnemosyne.cli production-evidence-verify` with the retained
`summary.json` `bundle_fingerprint`; this is custody review only and does not
flip this row.

## Acceptance

Operator runs the gates against real infra, evidence is redacted, the outputs
are included in `deployment-soak --evidence-dir` with production scope and
operator attestation, and `release-audit --require-production-validated --require-provider-forbid-local` passes
with required output shapes present and empty findings.

Done when gate evidence over deployed adapters is in the bundle and
`release-audit` is ok.
