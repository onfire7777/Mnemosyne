# Row 07 - Privacy And Erasure

## Objective

Prove production privacy controls, policy enforcement, forgetting behavior, KMS
custody, residency operations, and hard-delete evidence.

## Real-Infra Dependency

Real KMS or Vault-backed key custody plus residency policy operations.

## Gate Commands

Run in the production soak profile:

- `privacy-ops-check`
- `policy-ops-check`
- `forgetting-policy-check`

## Redaction Requirement

Evidence must not include user data, raw deletion targets, key material,
passwords, or provider credentials. Store redacted erasure requests, tombstone
IDs, key-shred attestations, residency policy summaries, and denial/allow
outcomes.

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

Done when KMS lifecycle/shred, residency, tombstone, and hard-delete evidence is
in the bundle and `release-audit` is ok.
