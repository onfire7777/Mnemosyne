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
render the production soak manifest, run
`infra/scripts/capture-production-evidence.sh --preflight-only` as setup proof only, then run
`infra/scripts/capture-production-evidence.sh` for the real `deployment-soak` +
`release-audit` capture. The preflight output does not flip this row to Done.

## Acceptance

Operator runs the gates against real infra, evidence is redacted, the outputs
are included in `deployment-soak --evidence-dir` with production scope and
operator attestation, and `release-audit --require-production-validated --require-provider-forbid-local` passes
with required output shapes present and empty findings.

Done when trainer deploy, protected-suite, and rollback-drill evidence is in the
bundle and `release-audit` is ok.
