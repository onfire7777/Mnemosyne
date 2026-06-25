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
  placeholders, rejects duplicate or unknown production commands, rejects
  high-confidence secret material, rejects unscannable retained artifacts,
  rejects non-empty output roots, supports `--preflight-only` setup validation,
  runs `deployment-soak --evidence-dir`, and then runs `release-audit
  --require-production-validated --require-provider-forbid-local`. Successful
  preflight and capture runs write `redaction-scan.json`; successful full
  captures bind the deployment report/check artifacts with manifest SHA-256
  digests, reject path escape and report/check divergence during release audit,
  and also write `bundle-manifest.json` with SHA-256 hashes for retained
  artifacts.

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
- `--preflight-only` output is setup proof only; it does not flip any row to
  Done.
- Production evidence must be operator-captured against real production or
  production-equivalent IdP, Postgres/retrieval, provider, MCP, dashboard,
  worker, object-store, KMS/residency, C2PA, and trainer surfaces.
- Secrets must be supplied through environment variables, provider files, Vault,
  Keycloak, KMS, or equivalent runtime custody. Do not place raw secrets in the
  soak manifest or committed docs; production bundles must keep
  `redaction-scan.json` at `ok: true` with no skipped files and retain
  `bundle-manifest.json` plus the `summary.json` `bundle_fingerprint` for
  handoff custody.
- After capture, `python -m mnemosyne.cli production-evidence-verify
  /secure/path/to/mnemosyne-production-evidence --expected-bundle-fingerprint
  '<summary.json bundle_fingerprint>'` can recheck the completed bundle offline.
  This is custody review only; it does not contact production, rerun
  `deployment-soak`, create evidence, or replace operator capture.
