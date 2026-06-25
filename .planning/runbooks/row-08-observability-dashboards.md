# Row 08 - Observability Dashboards

## Objective

Prove hosted dashboard packaging, metrics taxonomy, alert routing, and
production ops reporting.

## Real-Infra Dependency

Hosted production dashboard URL or hosted dashboard package plus live ops report
inputs.

## Gate Commands

Run in the production soak profile:

- `ops-dashboard-check`
- `ops-report`

## Redaction Requirement

Evidence must not include private tenant data, raw queries, raw memory content,
or dashboard secrets. Store hosted URL/package metadata, metrics taxonomy,
redacted counters, alert-route verification, and findings.

## Production Capture

Use the universal Tier B production capture flow in `infra/PRODUCTION-EVIDENCE.md`:
render the production soak manifest, run
`infra/scripts/capture-production-evidence.sh --preflight-only` as setup proof only, then run
`infra/scripts/capture-production-evidence.sh` for the real `deployment-soak` +
`release-audit` capture. The preflight output does not flip this row to Done.
After capture, reviewers may run `production-evidence-verify` with the retained
`summary.json` `bundle_fingerprint`; this is custody review only and does not
flip this row.

## Acceptance

Operator runs the gates against real infra, evidence is redacted, the outputs
are included in `deployment-soak --evidence-dir` with production scope and
operator attestation, and `release-audit --require-production-validated --require-provider-forbid-local` passes
with required output shapes present and empty findings.

Done when hosted-dashboard ops evidence is in the bundle and `release-audit` is
ok.
