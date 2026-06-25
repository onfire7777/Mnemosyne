# Production Evidence Capture Runbook

This runbook is the operator handoff for flipping the remaining Tier B parity rows from Partial to Done. It does not add a new gate; it uses the existing `deployment-soak` plus `release-audit --require-production-validated --require-provider-forbid-local` path.

## Preconditions

- Copy `infra/templates/production-render.env.example` outside the repo, fill the blank non-secret `MNEMOSYNE_PROD_*` values there, and source the external copy before rendering.
- Render `infra/templates/production-soak-manifest.template.json` outside the repo with `infra/scripts/render-production-soak-manifest.sh --output /secure/path/to/production-soak-manifest.json`. Manual edits are only a fallback and must still leave no unresolved `MNEMOSYNE_PROD_*` placeholders; the capture wrapper rejects unresolved placeholders before running production checks.
- Keep raw secrets out of `args` and `global_args`. The production wrapper rejects secret-bearing options such as `--idp-token`, `--session-secret`, `--auth-token`, and `--password`, and it fails closed on high-confidence secret material such as JWTs, private-key blocks, GitHub tokens, AWS access keys, and `sk-*` API keys.
- Provide secrets through environment variables or command/provider files. Required examples include `MNEMOSYNE_POSTGRES_DSN`, `MNEMOSYNE_IDP_TOKEN`, `MNEMOSYNE_MCP_TOKEN`, and `MNEMOSYNE_MCP_SESSION_TOKEN` where the selected checks need them.
- The manifest must include:
  - `validation_scope.production_validated: true`
  - `validation_scope.target_environment: "production"`
  - `validation_scope.operator_asserted: true`
- The manifest must include the exact production release profile: every command in the current 28-command set from `src/mnemosyne/cli.py`, with no duplicate or unknown commands.

## Capture

Run the production wrapper from the repository root:

```bash
cp infra/templates/production-render.env.example \
  /secure/path/to/production-render.env
# Fill /secure/path/to/production-render.env outside this repository.
set -a
. /secure/path/to/production-render.env
set +a
infra/scripts/render-production-soak-manifest.sh \
  --output /secure/path/to/production-soak-manifest.json
infra/scripts/capture-production-evidence.sh \
  --preflight-only \
  /secure/path/to/production-soak-manifest.json \
  /secure/path/to/mnemosyne-production-preflight
infra/scripts/capture-production-evidence.sh \
  /secure/path/to/production-soak-manifest.json \
  /secure/path/to/mnemosyne-production-evidence
```

The `--preflight-only` command validates production scope, exact command
coverage, absence of unresolved placeholders, absence of secret-bearing CLI
options, and a high-confidence redaction scan over the rendered manifest. It writes
`preflight.json`, `redaction-scan.json`, and a copied operator manifest, then
exits before `deployment-soak` or `release-audit` runs. A passing preflight is
setup proof only; it does not flip any strict-audit row to Done.

The wrapper performs these steps:

1. Validates the operator manifest is explicitly production-scoped.
2. Runs `deployment-soak --evidence-dir`.
3. Runs `release-audit --evidence-manifest ... --require-production-validated --require-provider-forbid-local`, which verifies the deployment evidence manifest's report and check SHA-256 digests before auditing.
4. Scans the generated evidence bundle for high-confidence secret material.
5. Writes `bundle-manifest.json` with SHA-256 hashes for every retained artifact before writing the final summary.

## Acceptance

The resulting `release-audit.json` must report `ok: true` with no findings, and
`redaction-scan.json` must report `ok: true`. Retain `bundle-manifest.json`
and the `summary.json` `bundle_fingerprint` as the handoff chain-of-custody
record for the captured files. A passing local or compose-only bundle is useful
staging evidence, but it does not satisfy Tier B unless the manifest is
operator asserted and the checks use production infrastructure.

The current strict audit remains incomplete until the production evidence bundle proves:

- Deployed ParadeDB/BM25, Apache AGE, pgvector, embedding, reranker, multimodal, and trainer providers are non-local.
- Live IdP/JWKS, TLS, session-secret custody, KMS/object-key, and residency controls are production-backed.
- Hosted MCP, worker supervision, dashboards, privacy erasure, C2PA trust roots, consolidation providers, and parametric rollback drills pass their existing ops checks.
