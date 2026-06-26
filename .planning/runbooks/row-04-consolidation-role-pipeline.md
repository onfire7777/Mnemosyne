# Row 04 - Consolidation Role Pipeline

## Objective

Prove supervised consolidation workers and role providers execute against the
production Postgres/runtime state.

## Real-Infra Dependency

Supervised Postgres worker plus model-backed extractor, summarizer, and entity
resolver providers.

## Gate Commands

Run in the production soak profile:

- `consolidation-ops-check`
- `worker-run`
- `worker-ops-check`
- `projection-recompute-once`
- `gate-suite-check`

## Redaction Requirement

Evidence must not include raw documents, raw prompts, private extracted text, or
provider credentials. Store job IDs, redacted role outputs, queue metrics,
provider contract status, recompute fingerprints, and protected-suite metadata.

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
operator attestation, and `release-audit --evidence-manifest "$OUT_ROOT/evidence/manifest.json" --require-production-validated --require-provider-forbid-local` passes
with required output shapes present and empty findings.

Done when supervised worker, provider, and projection evidence is in the bundle
and `release-audit` is ok.
The full wrapper summary must have `release_audit_ok=true`,
`redaction_scan_ok=true`, no redaction findings or skipped files, a retained
`bundle-manifest.json`/fingerprint, and passing `production-evidence-verify`.

## Operator Resume Signal

After `release-audit --evidence-manifest "$OUT_ROOT/evidence/manifest.json" --require-production-validated --require-provider-forbid-local`
passes for row 4 and `production-evidence-verify` passes for the retained
bundle, resume the parity handoff with `row-4 evidence captured`.
Use `skip operator gates` only to explicitly defer this production evidence pass.
