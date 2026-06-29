# Row 02 - Tenant Isolation And Auth

## Objective

Prove tenant isolation, authorization policy, JWKS rotation, TLS lifecycle, and
session/secret custody against live identity infrastructure.

## Real-Infra Dependency

Keycloak IdP/JWKS, Vault secrets, real TLS certificates, and rotation evidence.

## Gate Commands

Run in the production soak profile:

- `auth-ops-check`
- `provider-check` for `oidc` and `session_secret`
- `idp-jwks-live-check`
- `idp-authz-policy-rollout-check`
- `policy-ops-check`
- `tls-cert-check`
- `tls-rotation-plan-check`
- `tls-lifecycle-ops-check`

## Required Production Input Artifacts

Place these files in the external `MNEMOSYNE_PROD_EVIDENCE_DIR` before
rendering:

- `auth-ops-bundle.json`
- `idp-authz-policy-simulation.json`
- `idp-authz-policy.candidate.json`
- `idp-authz-policy.current.json`
- `policy-ops-bundle.json`
- `provider-manifest.production.json`
- `tls-candidate.pem`
- `tls-current.pem`
- `tls-lifecycle-bundle.json`

`provider-check` runs once from `provider-manifest.production.json` in the full
production profile. This row consumes the shared OIDC and session-secret
subchecks; do not create a row-local provider manifest.

## Redaction Requirement

Evidence must not include raw tokens, private keys, session secrets, passwords,
or tenant data. Keep issuer/audience/fingerprint summaries, policy simulation
results, certificate metadata, and redacted denial/allow outcomes.

## Production Capture

Use the universal Tier B production capture flow in `infra/PRODUCTION-EVIDENCE.md`:
render the production soak manifest to `SOAK_MANIFEST`, run
`infra/scripts/capture-production-evidence.sh --preflight-only "$SOAK_MANIFEST" "$PRECHECK_OUTPUT_ROOT"`
as setup proof only, then run
`infra/scripts/capture-production-evidence.sh "$SOAK_MANIFEST" "$OUT_ROOT"` for the real
`deployment-soak` + `release-audit` capture. The preflight output does not flip this row to Done.
Use absolute external paths outside the repo for `SOAK_MANIFEST`, `PRECHECK_OUTPUT_ROOT`, `OUT_ROOT`, and the `MNEMOSYNE_PROD_EVIDENCE_DIR` input-artifact directory.
After capture, reviewers must run `"$PYTHON" -m mnemosyne.cli production-evidence-verify` with
`--expected-bundle-fingerprint` set from the independently retained out-of-band
capture record, plus retained `preflight.json`, `redaction-scan.json`,
`bundle-manifest.json`, `source-soak-manifest.json`, `operator-soak-manifest.json`,
and `input-artifacts/` custody, plus source/operator command-profile agreement;
offline custody verification must pass before this row can flip Done.

## Acceptance

Operator runs the gates against real infra, evidence is redacted, the outputs
are included in `deployment-soak --evidence-dir` with production scope and
operator attestation, and `release-audit --evidence-manifest "$OUT_ROOT/evidence/manifest.json" --require-production-validated --require-provider-forbid-local` passes
with required output shapes present and empty findings.

Done when live IdP/JWKS/TLS evidence plus tenant-RLS cases are in the bundle and
`release-audit` is ok.
The full wrapper summary must have `release_audit_ok=true`,
`redaction_scan_ok=true`, no redaction findings or skipped files, a retained
`bundle-manifest.json`/fingerprint, and passing `production-evidence-verify`.

## Operator Resume Signal

After `release-audit --evidence-manifest "$OUT_ROOT/evidence/manifest.json" --require-production-validated --require-provider-forbid-local`
passes for row 2 and `production-evidence-verify` passes for the retained
bundle, resume the parity handoff with `row-2 evidence captured`.
Use `skip operator gates` only to explicitly defer this production evidence pass.
