# Local Staging Dry Run

## Scope

This runbook records the 2026-06-25 local real-services staging proof for the
Tier B evidence path. It is not production validation.

Literal staging marker:

```json
{
  "production_validated": false,
  "target_environment": "local-real-services",
  "surface": "local_cli_orchestrator"
}
```

The generated evidence uses local Keycloak, Vault transit, retrieval-provider
metadata, and the local C2PA helper. It does not flip any strict audit row from
Partial to Done.

The local staging output root must be a new, non-symlinked directory outside
the repository. This keeps the local proof aligned with the production custody
contract without treating local evidence as production validation.

## Production Harness Verification

Result: verified-as-is.

The production wrapper help/path check passed:

```bash
infra/scripts/capture-production-evidence.sh --help 2>&1 | grep -q "deployment-soak"
grep -q "require-production-validated" infra/scripts/capture-production-evidence.sh
grep -q "require-provider-forbid-local" infra/scripts/capture-production-evidence.sh
```

The wrapper enforces the sanctioned operator path:

- requires `validation_scope.production_validated=true`
- requires `validation_scope.target_environment="production"`
- requires `validation_scope.operator_asserted=true`
- rejects secret-bearing manifest args such as auth tokens, session secrets, and
  passwords
- verifies manifest coverage for `PRODUCTION_RELEASE_REQUIRED_COMMANDS`
- runs `deployment-soak --soak-manifest <manifest> --evidence-dir <dir>`
- runs `release-audit --evidence-manifest "$OUT_ROOT/evidence/manifest.json" --require-production-validated --require-provider-forbid-local`

## Commands Run

```bash
infra/scripts/setup-all.sh
infra/validate/validate-all.sh
infra/scripts/capture-local-evidence.sh
```

Fingerprint recheck:

```bash
OUT_ROOT=/tmp/mnemosyne-tierb-local-evidence-20260625T021718Z
FP=75f5e348930a0310a6a4c26ea22980bbb60d11d324bfef18a5f870c6e0a36a01
.venv/bin/python -m mnemosyne.cli --store "$OUT_ROOT/store.json" release-audit \
  --evidence-manifest "$OUT_ROOT/evidence/manifest.json" \
  --require-command idp-jwks-live-check \
  --require-command provider-check \
  --require-command provenance-trust-check \
  --require-provider-check object_key_manager \
  --require-provider-check retrieval_backends \
  --allow-provider-local \
  --expected-fingerprint "$FP"
```

## Captured Evidence

- Output root: `/tmp/mnemosyne-tierb-local-evidence-20260625T021718Z`
- Evidence manifest: `/tmp/mnemosyne-tierb-local-evidence-20260625T021718Z/evidence/manifest.json`
- Deployment-soak report: `/tmp/mnemosyne-tierb-local-evidence-20260625T021718Z/evidence/deployment-soak-report.json`
- Release audit: `/tmp/mnemosyne-tierb-local-evidence-20260625T021718Z/release-audit.json`
- Release-audit fingerprint: `75f5e348930a0310a6a4c26ea22980bbb60d11d324bfef18a5f870c6e0a36a01`

## Results

- `setup-all.sh`: passed.
- `validate-all.sh`: passed.
- `deployment-soak`: `ok=true`.
- `release-audit --allow-provider-local`: `ok=true`.
- `release-audit --expected-fingerprint`: `ok=true`.
- Findings: `[]`.
- Commands covered: `idp-jwks-live-check`, `provider-check`, `provenance-trust-check`.
- Checks covered: `keycloak-live-jwks`, `vault-kms-provider`, `c2pa-real-trust`.

## Production Boundary

This run proves the evidence mechanics against real local services only. The
operator still must run the production manifest through
`infra/scripts/capture-production-evidence.sh` against deployed infrastructure,
with `production_validated=true`, `target_environment="production"`, non-local
providers, and `release-audit --evidence-manifest "$OUT_ROOT/evidence/manifest.json" --require-production-validated --require-provider-forbid-local`.
