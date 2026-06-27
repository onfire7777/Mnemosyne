# Row 08 - Observability Dashboards

## Objective

Prove hosted production dashboard availability, metrics taxonomy, alert
routing, and production ops reporting.

## Real-Infra Dependency

Hosted production dashboard URL plus live ops report inputs. A dashboard
package can appear only as retained pre-existing external input evidence for
`ops-dashboard-check`; production capture must not generate one with
`ops-report --dashboard-package-dir`.

## Gate Commands

Run in the production soak profile:

- `ops-dashboard-check`
- `ops-report`

## Redaction Requirement

Evidence must not include private tenant data, raw queries, raw memory content,
or dashboard secrets. Store hosted URL metadata, optional retained external
package metadata, metrics taxonomy, redacted counters, alert-route
verification, and findings.

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

Done when hosted-dashboard ops evidence is in the bundle and `release-audit` is
ok.
The full wrapper summary must have `release_audit_ok=true`,
`redaction_scan_ok=true`, no redaction findings or skipped files, a retained
`bundle-manifest.json`/fingerprint, and passing `production-evidence-verify`.

## Operator Resume Signal

After `release-audit --evidence-manifest "$OUT_ROOT/evidence/manifest.json" --require-production-validated --require-provider-forbid-local`
passes for row 8 and `production-evidence-verify` passes for the retained
bundle, resume the parity handoff with `row-8 evidence captured`.
Use `skip operator gates` only to explicitly defer this production evidence pass.
