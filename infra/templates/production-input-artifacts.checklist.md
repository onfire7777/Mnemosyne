# Production Input Artifacts Checklist

This is a non-secret operator checklist for the external directory referenced by
`MNEMOSYNE_PROD_EVIDENCE_DIR`. It is not evidence by itself and must not contain
credentials, tokens, DSNs, API keys, or raw secrets.

Place these files in an absolute external custody directory outside the
repository before rendering or checking the production soak manifest:

To generate the external directory skeleton plus a row-scoped gap report, run:

```bash
infra/scripts/prepare-production-evidence-custody.py \
  /secure/path/to/mnemosyne-tier-b-custody
```

The generated `reports/tier-b-gap-report.{json,md}` files are an operator
worklist only. They are not production evidence and cannot flip any row.
After filling `production-render.env`, `input-artifacts/provider-manifest.production.json`,
or any row artifact, recompute the worklist without overwriting operator inputs:

```bash
infra/scripts/prepare-production-evidence-custody.py \
  --refresh \
  /secure/path/to/mnemosyne-tier-b-custody
```

Render and check the production soak manifest with the packet env file instead
of shell-sourcing it:

```bash
infra/scripts/render-production-soak-manifest.sh \
  --env-file /secure/path/to/mnemosyne-tier-b-custody/production-render.env \
  --check-environment
```

- [ ] `auth-ops-bundle.json`
- [ ] `belief-revision-cases.json`
- [ ] `calibration-dataset.json`
- [ ] `consolidation-ops-bundle.json`
- [ ] `forgetting-policy-cases.json`
- [ ] `hosted-llm-manifest.json`
- [ ] `idp-authz-policy-simulation.json`
- [ ] `idp-authz-policy.candidate.json`
- [ ] `idp-authz-policy.current.json`
- [ ] `mcp-ops-bundle.json`
- [ ] `multimodal-ops-bundle.json`
- [ ] `ops-dashboard-bundle.json`
- [ ] `parametric-trainer-bundle.json`
- [ ] `policy-ops-bundle.json`
- [ ] `privacy-ops-bundle.json`
- [ ] `provenance-ops-bundle.json`
- [ ] `provenance-trust-suite.json`
- [ ] `provider-manifest.production.json`
- [ ] `retrieval-ops-bundle.json`
- [ ] `row-10-full-suite-evidence.json`
- [ ] `tls-candidate.pem`
- [ ] `tls-current.pem`
- [ ] `tls-lifecycle-bundle.json`
- [ ] `worker-ops-bundle.json`

Row routing:

| Row | Runbook | Input artifacts |
| --- | --- | --- |
| B1 production Postgres retrieval | `.planning/runbooks/row-01-production-postgres-retrieval.md` | `retrieval-ops-bundle.json`, `provider-manifest.production.json` |
| B2 tenant isolation and auth | `.planning/runbooks/row-02-tenant-isolation-and-auth.md` | `auth-ops-bundle.json`, `idp-authz-policy-simulation.json`, `idp-authz-policy.candidate.json`, `idp-authz-policy.current.json`, `policy-ops-bundle.json`, `provider-manifest.production.json`, `tls-candidate.pem`, `tls-current.pem`, `tls-lifecycle-bundle.json` |
| B3 CLI/MCP runtime coverage | `.planning/runbooks/row-03-cli-mcp-runtime-coverage.md` | `mcp-ops-bundle.json` |
| B4 consolidation role pipeline | `.planning/runbooks/row-04-consolidation-role-pipeline.md` | `consolidation-ops-bundle.json`, `provider-manifest.production.json`, `worker-ops-bundle.json` |
| B5 signed provenance | `.planning/runbooks/row-05-signed-provenance.md` | `provenance-ops-bundle.json`, `provenance-trust-suite.json`, plus nested suite assets |
| B6 multimodal retrieval | `.planning/runbooks/row-06-multimodal-retrieval.md` | `multimodal-ops-bundle.json`, `provider-manifest.production.json` |
| B7 privacy and erasure | `.planning/runbooks/row-07-privacy-and-erasure.md` | `forgetting-policy-cases.json`, `privacy-ops-bundle.json`, `provider-manifest.production.json` |
| B8 observability dashboards | `.planning/runbooks/row-08-observability-dashboards.md` | `ops-dashboard-bundle.json` |
| B9 parametric tier | `.planning/runbooks/row-09-parametric-tier.md` | `calibration-dataset.json`, `hosted-llm-manifest.json`, `parametric-trainer-bundle.json`, `provider-manifest.production.json` |
| B10 live parity suite | `.planning/runbooks/row-10-live-parity-suite.md` | `belief-revision-cases.json`, `provider-manifest.production.json`, `row-10-full-suite-evidence.json` |

`provider-manifest.production.json` is intentionally shared by B1, B2, B4, B6,
B7, B9, and B10. Start from
`infra/templates/provider-manifest.production.template.json`, copy it into the
external `MNEMOSYNE_PROD_EVIDENCE_DIR`, and fill it with production provider
values or environment-variable references. It must keep `forbid_local: true` and
must cover the exact production-required provider subchecks: `embedding`,
`reranker`, `retrieval_backends`, `media_extractor`, `media_embedding`,
`object_key_manager`, `parametric`, `candidate_extractor`, `summarizer`,
`entity_resolver`, `lesson_distiller`, `skill_inducer`, `oidc`,
`session_secret`, and `residency_policy`. Do not split those into row-local
copies; one retained provider manifest keeps the shared infrastructure evidence
consistent across the parity rows.

Rules:

- Keep this directory outside the repo. The renderer and capture wrapper reject
  repo-local input custody paths.
- Use relative artifact references in the production manifest through
  `MNEMOSYNE_PROD_EVIDENCE_DIR/<name>`.
- For `provenance-trust-suite.json`, nested `asset_path` and `c2pa_asset_path`
  values are also treated as input artifacts and must resolve inside this same
  external directory.
- Run `infra/scripts/render-production-soak-manifest.sh --env-file /secure/path/to/mnemosyne-tier-b-custody/production-render.env --check-environment`
  before capture. Without render values, it reports this static
  artifact inventory, the readiness files to use next, and
  `parity_row_readiness` grouped by Tier-B row/runbook. With render values
  present, it reports missing relative artifact names and row-local validation
  errors without printing the external custody path. The row grouping is for
  operator assignment only; production evidence still requires the full capture
  and release-audit runbook.
- For secret-bearing provider/runtime variables, prefer passing a separate
  external mode-`0600` env file to
  `infra/scripts/capture-production-evidence.sh --env-file /secure/path/to/mnemosyne-production-runtime.env`;
  do not put those values in this no-secret input-artifact checklist or the
  custody packet docs.
