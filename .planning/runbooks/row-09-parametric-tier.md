# Row 09 - Parametric Tier

## Objective

Prove deployed LoRA/test-time-training boundaries, protected-suite gating, and
rollback orchestration.

## Real-Infra Dependency

Deployed LoRA/TTT trainer plus rollback orchestration.

## Gate Commands

Run in the production soak profile:

- `parametric-trainer-check`
- `hosted-llm-check`
- `calibration-tune`

## Required Production Input Artifacts

Place these files in the external `MNEMOSYNE_PROD_EVIDENCE_DIR` before
rendering:

- `parametric-trainer-bundle.json`
- `provider-manifest.production.json`

## Redaction Requirement

Evidence must not include training data, model secrets, raw prompts, bearer
tokens, private artifacts, or rollback provider credentials. Store artifact
fingerprints, protected-suite fingerprints, deployment health, canary status,
rollback-drill summaries, calibration metrics, and findings.

## Scope Note

This row is the operator-evidence side of FR-21 LoRA/TTT. Local command-provider
rails do not replace deployed trainer and production rollback evidence. Rollback
expectations are indexed in `.planning/ROLLBACK.md`.

## Production Capture

Use the universal Tier B production capture flow in `infra/PRODUCTION-EVIDENCE.md`:
render the production soak manifest to `SOAK_MANIFEST`, run
`infra/scripts/capture-production-evidence.sh --preflight-only "$SOAK_MANIFEST" "$PRECHECK_OUTPUT_ROOT"`
as setup proof only, then run
`infra/scripts/capture-production-evidence.sh "$SOAK_MANIFEST" "$OUT_ROOT"` for the real
`deployment-soak` + `release-audit` capture. The preflight output does not flip this row to Done.
Use absolute external paths outside the repo for `SOAK_MANIFEST`, `PRECHECK_OUTPUT_ROOT`, `OUT_ROOT`, and the `MNEMOSYNE_PROD_EVIDENCE_DIR` input-artifact directory.
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

Done when trainer deploy, protected-suite, and rollback-drill evidence is in the
bundle and `release-audit` is ok.
The full wrapper summary must have `release_audit_ok=true`,
`redaction_scan_ok=true`, no redaction findings or skipped files, a retained
`bundle-manifest.json`/fingerprint, and passing `production-evidence-verify`.

## Operator Resume Signal

After `release-audit --evidence-manifest "$OUT_ROOT/evidence/manifest.json" --require-production-validated --require-provider-forbid-local`
passes for row 9 and `production-evidence-verify` passes for the retained
bundle, resume the parity handoff with `row-9 evidence captured`.
Use `skip operator gates` only to explicitly defer this production evidence pass.
