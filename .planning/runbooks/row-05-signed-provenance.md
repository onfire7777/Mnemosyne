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

## Production Capture

Use the universal Tier B production capture flow in `infra/PRODUCTION-EVIDENCE.md`:
render the production soak manifest, run
`infra/scripts/capture-production-evidence.sh --preflight-only` as setup proof only, then run
`infra/scripts/capture-production-evidence.sh` for the real `deployment-soak` +
`release-audit` capture. The preflight output does not flip this row to Done.

## Acceptance

Operator runs the gates against real infra, evidence is redacted, the outputs
are included in `deployment-soak --evidence-dir` with production scope and
operator attestation, and `release-audit --require-production-validated --require-provider-forbid-local` passes
with required output shapes present and empty findings.

Done when verifier, trust-root rotation, and quarantine evidence are in the
bundle and `release-audit` is ok.
