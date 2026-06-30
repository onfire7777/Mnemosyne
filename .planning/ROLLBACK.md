# Rollback Guidance

**Lane F owns recovery and abort only.** Forward deploy steps live in
`.planning/runbooks/`. This document describes how to revert, abort canaries,
and capture rollback drills without authoring new gates.

Forward deployment follows the external `gstack land-and-deploy` workflow
tooling: dry-run -> pre-merge gate -> deploy strategy -> canary verification ->
deploy report. Rollback starts from that deploy report and the previous known
good release artifact.

## General Revert Procedure

1. Identify the failing surface and the last known good release fingerprint.
2. Freeze new promotions for the affected tenant or deployment surface.
3. Preserve the failing deploy report, canary report, and relevant gate output.
4. Restore the previous release artifact, config bundle, or provider pointer.
5. Re-run the surface-specific gate listed in `.planning/runbooks/`.
6. Stage redacted rollback input artifacts in the absolute external directory
   referenced by `MNEMOSYNE_PROD_EVIDENCE_DIR`; it must not point inside the
   repository.
7. Run
   `infra/scripts/capture-production-evidence.sh --env-file "$RUNTIME_ENV_FILE" --preflight-only "$SOAK_MANIFEST" "$PRECHECK_OUTPUT_ROOT"`
   as setup proof only; `PRECHECK_OUTPUT_ROOT` must be a new absolute external
   custody path outside the repository and `RUNTIME_ENV_FILE` must be the
   strict external mode-`0600` runtime/provider env file.
8. Run `infra/scripts/capture-production-evidence.sh --env-file "$RUNTIME_ENV_FILE" --fingerprint-record-output "$FINGERPRINT_RECORD" "$SOAK_MANIFEST" "$OUT_ROOT"`;
   `OUT_ROOT` must be a new absolute external custody path outside the
   repository and must not already exist; the capture wrapper writes the
   production bundle there.
9. Require `release-audit --evidence-manifest "$OUT_ROOT/evidence/manifest.json" --require-production-validated --require-provider-forbid-local` to pass.
10. Retain `summary.json`, `preflight.json`, `redaction-scan.json`,
   `bundle-manifest.json`, `source-soak-manifest.json`,
   `operator-soak-manifest.json`, and `input-artifacts/` so
   `production-evidence-verify` can recheck rollback custody offline with
   `--expected-bundle-fingerprint` set from an independently retained
   out-of-band rollback capture record.

## Canary-Abort Procedure

1. Stop promotion immediately when a canary tripwire fires.
2. Keep canary traffic or tenant scope isolated from `main` promotion paths.
3. Record the triggered tripwire, threshold, affected surface, and timestamp.
4. Discard the canary branch, model artifact, provider config, or deploy slice.
5. Verify the prior stable surface still passes its frozen gate.
6. Store only redacted canary evidence; do not include tokens, raw prompts, raw
   tenant content, credentials, private keys, or unredacted documents.
7. File the abort evidence under the same production evidence bundle consumed by
   `deployment-soak`.

## Rollback Surfaces

- Branch rollback: canary/scratch branches must be discardable without leaking
  assertions, relations, preferences, or evidence into `main`.
- Projection rollback: derived evidence erasure and projection recompute must
  preserve surviving source evidence and record recompute fingerprints.
- Parametric rollback: trainer evidence must bind protected-suite, artifact,
  rollback, and deployment fingerprints, and must prove rollback drill execution
  through `parametric-trainer-check`.
- Operations rollback: hosted MCP, dashboard, worker, provider, object-store,
  IdP, TLS, and residency failures must fail closed and leave auditable evidence.

## Row 02 Auth Rollback Drill

Trigger: candidate IdP/JWKS/authz/TLS rollout fails simulation, token exchange,
rotation, or tenant isolation checks.

Steps:

1. Keep current Keycloak realm and TLS material active.
2. Reject the candidate policy fingerprint or certificate rotation plan.
3. Re-run `auth-ops-check`, `idp-jwks-live-check`,
   `idp-authz-policy-rollout-check`, and the TLS checks against the stable
   deployment.
4. Capture redacted issuer/audience/fingerprint, policy simulation, certificate,
   and tenant-RLS outcomes.

Expected post-state: no candidate auth policy is promoted, tenant isolation
continues to deny cross-tenant access, and the stable JWKS/TLS path remains
valid.

## Row 04 Consolidation Worker Rollback Drill

Trigger: worker supervision, provider output shape, projection recompute, or
protected-suite validation fails.

Steps:

1. Stop or drain the candidate worker.
2. Restore the prior worker image, provider command, or model endpoint pointer.
3. Re-run `worker-run`, `worker-ops-check`, `consolidation-ops-check`,
   `projection-recompute-once`, and `gate-suite-check`.
4. Capture redacted queue metrics, provider status, recompute fingerprints, and
   protected-suite metadata.

Expected post-state: duplicate side effects are absent, recompute fingerprints
are stable, and protected cases still pass.

## Row 07 Privacy And Erasure Rollback Drill

Trigger: residency, policy, forgetting, hard-delete, or key-shred evidence
fails.

Steps:

1. Fail closed on the affected write/delete path.
2. Restore the previous residency policy or KMS/object-key provider config.
3. Re-run `privacy-ops-check`, `policy-ops-check`, and
   `forgetting-policy-check`.
4. Capture redacted tombstone, key-shred, residency, and deletion evidence.

Expected post-state: no deleted data is resurrected, legal-delete key custody is
preserved, and residency transfers remain explicitly allowed or denied.

## Row 09 Parametric Rollback Drill

Trigger: trainer canary, protected-suite, calibration, deployment health, or
rollback provider evidence fails.

Steps:

1. Block promotion of the candidate LoRA/TTT artifact.
2. Restore the prior artifact pointer or disable the candidate adapter.
3. Run `parametric-trainer-check` with rollback-drill evidence enabled.
4. Run `hosted-llm-check` and `calibration-tune` against the stable path.
5. Cross-link the evidence to `.planning/runbooks/row-09-parametric-tier.md`.

Expected post-state: authorized rollback is verified, the rollback drill is
recorded, no rollback branch is promoted, and protected-suite/artifact/rollback
fingerprints stay bound.

## Evidence Path

Rollback drills are accepted only when captured by
`infra/scripts/capture-production-evidence.sh` and accepted by
`release-audit --evidence-manifest "$OUT_ROOT/evidence/manifest.json" --require-production-validated --require-provider-forbid-local`,
then rechecked by `production-evidence-verify "$BUNDLE_DIR"
--expected-bundle-fingerprint "$EXPECTED_BUNDLE_FINGERPRINT"
--report-output "$VERIFY_REPORT"` with the expected fingerprint from an
independently retained out-of-band rollback capture record and a new external
verifier report path outside the bundle under review.

Local tests and compose smoke runs can prove mechanics, but they do not replace
operator-captured production rollback evidence.

## Evidence Checklist

- Failing surface named.
- Last known good release fingerprint recorded.
- Canary or rollback trigger recorded.
- Gate commands rerun after the revert.
- Redaction applied to tokens, keys, raw prompts, documents, queries, and
  credentials.
- `release-audit --evidence-manifest "$OUT_ROOT/evidence/manifest.json" --require-production-validated --require-provider-forbid-local` passes over the bundle.
- `production-evidence-verify` passes with `--expected-bundle-fingerprint`
  sourced from the out-of-band rollback capture record.
