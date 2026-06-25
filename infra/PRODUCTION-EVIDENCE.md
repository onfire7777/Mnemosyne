# Production Evidence Capture Runbook

This runbook is the operator handoff for flipping the remaining Tier B parity rows from Partial to Done. It does not add a new gate; it uses the existing `deployment-soak` plus `release-audit --require-production-validated` path.

## Preconditions

- Copy `infra/templates/production-soak-manifest.template.json` outside the repo and replace every `MNEMOSYNE_PROD_*` placeholder with production evidence paths, production URLs, or non-secret identifiers.
- Keep raw secrets out of `args` and `global_args`. The production wrapper rejects secret-bearing options such as `--idp-token`, `--session-secret`, `--auth-token`, and `--password`.
- Provide secrets through environment variables or command/provider files. Required examples include `MNEMOSYNE_POSTGRES_DSN`, `MNEMOSYNE_IDP_TOKEN`, `MNEMOSYNE_MCP_TOKEN`, and `MNEMOSYNE_MCP_SESSION_TOKEN` where the selected checks need them.
- The manifest must include:
  - `validation_scope.production_validated: true`
  - `validation_scope.target_environment: "production"`
  - `validation_scope.operator_asserted: true`
- The manifest must include every command in the production release profile. The template tracks the current 28-command set from `src/mnemosyne/cli.py`.

## Capture

Run the production wrapper from the repository root:

```bash
infra/scripts/capture-production-evidence.sh \
  /secure/path/to/production-soak-manifest.json \
  /secure/path/to/mnemosyne-production-evidence
```

The wrapper performs three steps:

1. Validates the operator manifest is explicitly production-scoped.
2. Runs `deployment-soak --evidence-dir`.
3. Runs `release-audit --evidence-manifest ... --require-production-validated --require-provider-forbid-local`.

## Acceptance

The resulting `release-audit.json` must report `ok: true` with no findings. A passing local or compose-only bundle is useful staging evidence, but it does not satisfy Tier B unless the manifest is operator asserted and the checks use production infrastructure.

The current strict audit remains incomplete until the production evidence bundle proves:

- Deployed ParadeDB/BM25, Apache AGE, pgvector, embedding, reranker, multimodal, and trainer providers are non-local.
- Live IdP/JWKS, TLS, session-secret custody, KMS/object-key, and residency controls are production-backed.
- Hosted MCP, worker supervision, dashboards, privacy erasure, C2PA trust roots, consolidation providers, and parametric rollback drills pass their existing ops checks.
