# Mnemosyne Runbook Index

This directory indexes operator runbooks for Mnemosyne production parity. It does
not define new release gates; the canonical gate binaries remain the existing
CLI commands consumed by `deployment-soak` and `release-audit`.

## Production Evidence

- `infra/README.md` - local infra stack and evidence capture entry points.
- `infra/PRODUCTION-EVIDENCE.md` - Tier B production evidence runbook.
- `infra/templates/production-soak-manifest.template.json` - secret-free
  manifest template covering the production release command profile.
- `infra/templates/production-render.env.example` - blank non-secret input
  template operators copy outside the repo before filling render values.
- `infra/scripts/render-production-soak-manifest.sh` - canonical renderer for
  non-secret `MNEMOSYNE_PROD_*` placeholders; refuses repo-local output by
  default and validates the production command profile before writing.
- `infra/scripts/capture-production-evidence.sh` - operator capture wrapper
  that validates the rendered manifest, rejects unresolved production
  placeholders, runs `deployment-soak --evidence-dir`, and then runs
  `release-audit --require-production-validated --require-provider-forbid-local`.

## Row Runbooks

- `row-01-production-postgres-retrieval.md`
- `row-02-tenant-isolation-and-auth.md`
- `row-03-cli-mcp-runtime-coverage.md`
- `row-04-consolidation-role-pipeline.md`
- `row-05-signed-provenance.md`
- `row-06-multimodal-retrieval.md`
- `row-07-privacy-and-erasure.md`
- `row-08-observability-dashboards.md`
- `row-09-parametric-tier.md`
- `row-10-live-parity-suite.md`

## Scope Rules

- Local and compose evidence can prove gate mechanics, but cannot satisfy Tier B.
- Production evidence must be operator-captured against real production or
  production-equivalent IdP, Postgres/retrieval, provider, MCP, dashboard,
  worker, object-store, KMS/residency, C2PA, and trainer surfaces.
- Secrets must be supplied through environment variables, provider files, Vault,
  Keycloak, KMS, or equivalent runtime custody. Do not place raw secrets in the
  soak manifest or committed docs.
