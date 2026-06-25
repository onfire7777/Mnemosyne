# Row 05 - Signed Provenance

## Objective

Prove provenance verification, trust-root enforcement, and quarantine behavior
against the real C2PA/provenance deployment.

## Real-Infra Dependency

Real `c2patool` execution and trusted issuer/root deployment.

## Gate Commands

Run in the production soak profile:

- `provenance-ops-check`
- `provenance-trust-check`

## Redaction Requirement

Evidence must not include private media, raw certificate private keys, or
unredacted signed content. Store trust-root fingerprints, validation summaries,
binding results, quarantine outcomes, and rotation evidence.

## Acceptance

Operator runs the gates against real infra, evidence is redacted, the outputs
are included in `deployment-soak --evidence-dir` with production scope and
operator attestation, and `release-audit --require-production-validated` passes
with required output shapes present and empty findings.

Done when verifier, trust-root rotation, and quarantine evidence are in the
bundle and `release-audit` is ok.
