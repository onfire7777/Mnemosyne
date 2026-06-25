# Row 02 - Tenant Isolation And Auth

## Objective

Prove tenant isolation, authorization policy, JWKS rotation, TLS lifecycle, and
session/secret custody against live identity infrastructure.

## Real-Infra Dependency

Keycloak IdP/JWKS, Vault secrets, real TLS certificates, and rotation evidence.

## Gate Commands

Run in the production soak profile:

- `auth-ops-check`
- `idp-jwks-live-check`
- `idp-authz-policy-rollout-check`
- `tls-cert-check`
- `tls-rotation-plan-check`
- `tls-lifecycle-ops-check`

## Redaction Requirement

Evidence must not include raw tokens, private keys, session secrets, passwords,
or tenant data. Keep issuer/audience/fingerprint summaries, policy simulation
results, certificate metadata, and redacted denial/allow outcomes.

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

Done when live IdP/JWKS/TLS evidence plus tenant-RLS cases are in the bundle and
`release-audit` is ok.
