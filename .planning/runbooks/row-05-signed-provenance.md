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
After capture, reviewers may run `"$PYTHON" -m mnemosyne.cli production-evidence-verify` with the retained
`summary.json` `bundle_fingerprint`; this is custody review only and does not
flip this row.

## Acceptance

Operator runs the gates against real infra, evidence is redacted, the outputs
are included in `deployment-soak --evidence-dir` with production scope and
operator attestation, and `release-audit --require-production-validated --require-provider-forbid-local` passes
with required output shapes present and empty findings.

Done when verifier, trust-root rotation, and quarantine evidence are in the
bundle and `release-audit` is ok.
