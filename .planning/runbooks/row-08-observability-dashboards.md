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

## Acceptance

Operator runs the gates against real infra, evidence is redacted, the outputs
are included in `deployment-soak --evidence-dir` with production scope and
operator attestation, and `release-audit --require-production-validated` passes
with required output shapes present and empty findings.

Done when hosted-dashboard ops evidence is in the bundle and `release-audit` is
ok.
