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

Done when supervised worker, provider, and projection evidence is in the bundle
and `release-audit` is ok.
