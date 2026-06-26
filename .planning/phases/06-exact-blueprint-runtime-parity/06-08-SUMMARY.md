# Phase 06 Plan 08 Summary - Local Staging Evidence

Completed the 06-08 local-staging dry-run checkpoint.

## Files

- `.planning/runbooks/LOCAL-STAGING-DRY-RUN.md`
- `.planning/phases/06-exact-blueprint-runtime-parity/06-08-SUMMARY.md`

## Implementation

- Verified `infra/scripts/capture-production-evidence.sh` implements the
  sanctioned production evidence path and rejects secret-bearing manifest args.
- Ran the local real-services setup and validation path through
  `infra/scripts/setup-all.sh` and `infra/validate/validate-all.sh`.
- Ran `infra/scripts/capture-local-evidence.sh`, which executes
  `deployment-soak --evidence-dir` and scoped `release-audit --allow-provider-local`
  against local Keycloak, Vault transit, retrieval-provider metadata, and C2PA
  trust evidence.
- Recorded the exact commands, output paths, local staging scope, and fingerprint
  in `.planning/runbooks/LOCAL-STAGING-DRY-RUN.md`.

## Verification

- `infra/scripts/capture-production-evidence.sh --help` contains
  `deployment-soak`, and the wrapper contains both
  `require-production-validated` and `require-provider-forbid-local`.
- `infra/scripts/setup-all.sh` passed.
- `infra/validate/validate-all.sh` passed.
- `infra/scripts/capture-local-evidence.sh` passed with:
  - output root `/tmp/mnemosyne-tierb-local-evidence-20260625T021718Z`
  - `deployment_soak_ok=true`
  - `release_audit_ok=true`
  - `production_validated=false`
  - `target_environment=local-real-services`
  - fingerprint `75f5e348930a0310a6a4c26ea22980bbb60d11d324bfef18a5f870c6e0a36a01`
- Re-running `release-audit` with `--expected-fingerprint
  75f5e348930a0310a6a4c26ea22980bbb60d11d324bfef18a5f870c6e0a36a01` passed
  with `ok=true` and `findings=[]`.

## Remaining

- This is staging proof only. The 10 strict audit rows remain Partial until the
  operator runs production evidence capture against deployed infrastructure with
  `production_validated=true` and `release-audit --evidence-manifest "$OUT_ROOT/evidence/manifest.json" --require-production-validated --require-provider-forbid-local`.
