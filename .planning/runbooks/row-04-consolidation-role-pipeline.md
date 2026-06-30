# Row 04 - Consolidation Role Pipeline

## Objective

Prove supervised consolidation workers and role providers execute against the
production Postgres/runtime state.

## Real-Infra Dependency

Supervised Postgres worker plus model-backed extractor, summarizer, entity
resolver, lesson distiller, and skill inducer providers.

## Gate Commands

Run in the production soak profile:

- `consolidation-ops-check`
- `worker-run`
- `worker-ops-check`
- `projection-recompute-once`
- `gate-suite-check`
- `provider-check` for `candidate_extractor`, `summarizer`,
  `entity_resolver`, `lesson_distiller`, and `skill_inducer`

## Required Production Input Artifacts

Place these files in the external `MNEMOSYNE_PROD_EVIDENCE_DIR` before
rendering:

- `consolidation-ops-bundle.json`
- `provider-manifest.production.json`
- `worker-ops-bundle.json`

`provider-check` runs once from `provider-manifest.production.json` in the full
production profile. This row consumes the shared consolidation role-provider
subchecks for candidate extraction, summarization, entity resolution, lesson
distillation, and skill induction; do not create a row-local provider manifest.

## Redaction Requirement

Evidence must not include raw documents, raw prompts, private extracted text, or
provider credentials. Store job IDs, redacted role outputs, queue metrics,
provider contract status, recompute fingerprints, and protected-suite metadata.

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
