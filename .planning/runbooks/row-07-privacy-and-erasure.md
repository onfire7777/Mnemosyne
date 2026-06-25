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
render the production soak manifest to `SOAK_MANIFEST`, run
`infra/scripts/capture-production-evidence.sh --preflight-only "$SOAK_MANIFEST" "$PREFLIGHT_OUT_ROOT"`
as setup proof only, then run
`infra/scripts/capture-production-evidence.sh "$SOAK_MANIFEST" "$OUT_ROOT"` for the real
`deployment-soak` + `release-audit` capture. The preflight output does not flip this row to Done.
Use absolute external paths outside the repo for `SOAK_MANIFEST`, `PREFLIGHT_OUT_ROOT`, `OUT_ROOT`, and the `MNEMOSYNE_PROD_EVIDENCE_DIR` input-artifact directory.
After capture, reviewers must run `"$PYTHON" -m mnemosyne.cli production-evidence-verify` with the retained
`summary.json` `bundle_fingerprint`; offline custody verification must pass before this row can flip Done.

## Acceptance

Operator runs the gates against real infra, evidence is redacted, the outputs
are included in `deployment-soak --evidence-dir` with production scope and
operator attestation, and `release-audit --require-production-validated --require-provider-forbid-local` passes
with required output shapes present and empty findings.

Done when KMS lifecycle/shred, residency, tombstone, and hard-delete evidence is
in the bundle and `release-audit` is ok.
The full wrapper summary must have `release_audit_ok=true`,
`redaction_scan_ok=true`, no redaction findings or skipped files, a retained
`bundle-manifest.json`/fingerprint, and passing `production-evidence-verify`.

## Operator Resume Signal

After `release-audit --require-production-validated --require-provider-forbid-local`
passes for row 7 and `production-evidence-verify` passes for the retained
bundle, resume the parity handoff with `row-7 evidence captured`.
Use `skip operator gates` only to explicitly defer this production evidence pass.
