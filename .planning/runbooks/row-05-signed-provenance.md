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
render the production soak manifest to `SOAK_MANIFEST`, run
`infra/scripts/capture-production-evidence.sh --preflight-only "$SOAK_MANIFEST" "$PREFLIGHT_OUT_ROOT"`
as setup proof only, then run
`infra/scripts/capture-production-evidence.sh "$SOAK_MANIFEST" "$OUT_ROOT"` for the real
`deployment-soak` + `release-audit` capture. The preflight output does not flip this row to Done.
Use absolute external paths outside the repo for `SOAK_MANIFEST`, `PREFLIGHT_OUT_ROOT`, `OUT_ROOT`, and the `MNEMOSYNE_PROD_EVIDENCE_DIR` input-artifact directory.
After capture, reviewers must run `"$PYTHON" -m mnemosyne.cli production-evidence-verify` with the retained
`summary.json` `bundle_fingerprint`, retained `preflight.json`, `redaction-scan.json`,
`bundle-manifest.json`, `source-soak-manifest.json`, `operator-soak-manifest.json`,
and `input-artifacts/` custody, plus source/operator command-profile agreement;
offline custody verification must pass before this row can flip Done.

## Acceptance

Operator runs the gates against real infra, evidence is redacted, the outputs
are included in `deployment-soak --evidence-dir` with production scope and
operator attestation, and `release-audit --evidence-manifest "$OUT_ROOT/evidence/manifest.json" --require-production-validated --require-provider-forbid-local` passes
with required output shapes present and empty findings.

Done when verifier, trust-root rotation, and quarantine evidence are in the
bundle and `release-audit` is ok.
The full wrapper summary must have `release_audit_ok=true`,
`redaction_scan_ok=true`, no redaction findings or skipped files, a retained
`bundle-manifest.json`/fingerprint, and passing `production-evidence-verify`.

## Operator Resume Signal

After `release-audit --evidence-manifest "$OUT_ROOT/evidence/manifest.json" --require-production-validated --require-provider-forbid-local`
passes for row 5 and `production-evidence-verify` passes for the retained
bundle, resume the parity handoff with `row-5 evidence captured`.
Use `skip operator gates` only to explicitly defer this production evidence pass.
