# Production Input Artifacts Checklist

This is a non-secret operator checklist for the external directory referenced by
`MNEMOSYNE_PROD_EVIDENCE_DIR`. It is not evidence by itself and must not contain
credentials, tokens, DSNs, API keys, or raw secrets.

Place these files in an absolute external custody directory outside the
repository before rendering or checking the production soak manifest:

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

Rules:

- Keep this directory outside the repo. The renderer and capture wrapper reject
  repo-local input custody paths.
- Use relative artifact references in the production manifest through
  `MNEMOSYNE_PROD_EVIDENCE_DIR/<name>`.
- For `provenance-trust-suite.json`, nested `asset_path` and `c2pa_asset_path`
  values are also treated as input artifacts and must resolve inside this same
  external directory.
- Run `infra/scripts/render-production-soak-manifest.sh --check-environment`
  before capture. Without sourced environment values, it reports this static
  artifact inventory, the readiness files to use next, and
  `parity_row_readiness` grouped by Tier-B row/runbook. With environment values
  present, it reports missing relative artifact names and row-local validation
  errors without printing the external custody path. The row grouping is for
  operator assignment only; production evidence still requires the full capture
  and release-audit runbook.
