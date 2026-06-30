# Row 08 - Observability Dashboards

## Objective

Prove hosted production dashboard availability, metrics taxonomy, alert
routing, and production ops reporting.

## Real-Infra Dependency

Hosted production dashboard URL plus live ops report inputs. Local dashboard
packages are preflight/development artifacts only; production release evidence
must come from `ops-dashboard-check --dashboard-url` and must not use
`--dashboard-package-dir` or generate one with `ops-report --dashboard-package-dir`.

## Gate Commands

Run in the production soak profile:

- `ops-dashboard-check`
- `ops-report`

## Required Production Input Artifacts

Place this file in the external `MNEMOSYNE_PROD_EVIDENCE_DIR` before rendering:

- `ops-dashboard-bundle.json`

## Redaction Requirement

Evidence must not include private tenant data, raw queries, raw memory content,
or dashboard secrets. Store hosted URL metadata, optional retained external
package metadata, metrics taxonomy, redacted counters, alert-route
verification, and findings.

## Production Capture

Use the universal Tier B production capture flow in `infra/PRODUCTION-EVIDENCE.md`:
render the production soak manifest to `SOAK_MANIFEST`, run
`infra/scripts/capture-production-evidence.sh --env-file "$RUNTIME_ENV_FILE" --preflight-only "$SOAK_MANIFEST" "$PRECHECK_OUTPUT_ROOT"`
as setup proof only, then run
`infra/scripts/capture-production-evidence.sh --env-file "$RUNTIME_ENV_FILE" --fingerprint-record-output "$FINGERPRINT_RECORD" "$SOAK_MANIFEST" "$OUT_ROOT"` for the real
`deployment-soak` + `release-audit` capture. The preflight output does not flip this row to Done.
Use absolute external paths outside the repo for `SOAK_MANIFEST`, `PRECHECK_OUTPUT_ROOT`, `OUT_ROOT`, `FINGERPRINT_RECORD`, `RUNTIME_ENV_FILE`, and the `MNEMOSYNE_PROD_EVIDENCE_DIR` input-artifact directory.
After capture, reviewers must run `"$PYTHON" -m mnemosyne.cli production-evidence-verify` with
`--expected-bundle-fingerprint` set from the independently retained out-of-band fingerprint record, plus retained `preflight.json`, `redaction-scan.json`,
`bundle-manifest.json`, `source-soak-manifest.json`, `operator-soak-manifest.json`,
`input-artifacts/`, `tool-artifacts/`, `summary.json.offline_verify`,
`summary.json.parity_row_readiness`,
`summary.json.row_review_source=preflight.json.parity_row_readiness`,
verifier `row_review.rows[]`, and source/operator command-profile agreement;
offline custody verification with an external `--report-output` artifact must pass
before this row can flip Done.

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
