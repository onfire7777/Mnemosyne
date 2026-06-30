# Row 01 - Production Postgres Retrieval

## Objective

Prove production retrieval over deployed Postgres adapters, not local fallback
paths.

## Real-Infra Dependency

ParadeDB BM25, Apache AGE, pgvector, and non-local embedding/reranker providers.

## Gate Commands

Run in the production soak profile:

- `retrieval-ops-check`
- `provider-check` for `retrieval_backends`

## Required Production Input Artifacts

Place these files in the external `MNEMOSYNE_PROD_EVIDENCE_DIR` before
rendering:

- `retrieval-ops-bundle.json`
- `provider-manifest.production.json`

`provider-check` runs once from `provider-manifest.production.json` in the full
production profile. This row consumes the shared retrieval backend subcheck;
do not create a row-local provider manifest.

## Redaction Requirement

Evidence must not include raw tokens, keys, queries, documents, credentials, or
tenant-private retrieved text. Store only redacted summaries, provider names,
shape validation, latency, and pass/fail details.

## Production Capture

Use the universal Tier B production capture flow in `infra/PRODUCTION-EVIDENCE.md`:
render the production soak manifest to `SOAK_MANIFEST`, run
`infra/scripts/capture-production-evidence.sh --preflight-only "$SOAK_MANIFEST" "$PRECHECK_OUTPUT_ROOT"`
as setup proof only, then run
`infra/scripts/capture-production-evidence.sh --fingerprint-record-output "$FINGERPRINT_RECORD" "$SOAK_MANIFEST" "$OUT_ROOT"` for the real
`deployment-soak` + `release-audit` capture. The preflight output does not flip this row to Done.
Use absolute external paths outside the repo for `SOAK_MANIFEST`, `PRECHECK_OUTPUT_ROOT`, `OUT_ROOT`, `FINGERPRINT_RECORD`, and the `MNEMOSYNE_PROD_EVIDENCE_DIR` input-artifact directory.
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

Done when gate evidence over deployed adapters is in the bundle and
`release-audit` is ok.
The full wrapper summary must have `release_audit_ok=true`,
`redaction_scan_ok=true`, no redaction findings or skipped files, a retained
`bundle-manifest.json`/fingerprint, and passing `production-evidence-verify`.

## Operator Resume Signal

After `release-audit --evidence-manifest "$OUT_ROOT/evidence/manifest.json" --require-production-validated --require-provider-forbid-local`
passes for row 1 and `production-evidence-verify` passes for the retained
bundle, resume the parity handoff with `row-1 evidence captured`.
Use `skip operator gates` only to explicitly defer this production evidence pass.
