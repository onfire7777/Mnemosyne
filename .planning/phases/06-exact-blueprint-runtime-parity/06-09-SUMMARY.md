# Phase 06 Plan 09 Summary - Operator Evidence Gates

Completed the autonomous executor side of 06-09.

## Scope

Plan 06-09 is non-autonomous. It defines the 10 production evidence gates that
flip strict audit rows from Partial to Done only after an operator runs
production-scoped evidence capture against deployed infrastructure.

No `src/` or `infra/` code was modified for this plan.

## Executor Readiness

Verified present:

- `.planning/runbooks/row-01-production-postgres-retrieval.md`
- `.planning/runbooks/row-02-tenant-isolation-and-auth.md`
- `.planning/runbooks/row-03-cli-mcp-runtime-coverage.md`
- `.planning/runbooks/row-04-consolidation-role-pipeline.md`
- `.planning/runbooks/row-05-signed-provenance.md`
- `.planning/runbooks/row-06-multimodal-retrieval.md`
- `.planning/runbooks/row-07-privacy-and-erasure.md`
- `.planning/runbooks/row-08-observability-dashboards.md`
- `.planning/runbooks/row-09-parametric-tier.md`
- `.planning/runbooks/row-10-live-parity-suite.md`
- `.planning/runbooks/LOCAL-STAGING-DRY-RUN.md`
- `.planning/ENV-AND-SECRETS.md`
- `.planning/ROLLBACK.md`
- `infra/scripts/capture-production-evidence.sh`
- `infra/templates/production-soak-manifest.template.json`

Verified prerequisite summaries present:

- `06-01-SUMMARY.md`
- `06-02-SUMMARY.md`
- `06-03-SUMMARY.md`
- `06-07-SUMMARY.md`
- `06-08-SUMMARY.md`

## Row Readiness

| Row | Gate | Executor state | Operator state |
|---|---|---|---|
| 1 | Production Postgres retrieval | Runbook exists; local-staging dry run proven. | Pending real ParadeDB/BM25, AGE, pgvector, embedding/reranker evidence. |
| 2 | Tenant isolation and auth | Runbook exists; env/secrets catalog exists; local-staging dry run proven. | Pending real IdP/JWKS, Vault/session-secret, TLS, tenant-isolation evidence. |
| 3 | CLI/MCP runtime coverage | Runbook exists; A11 local readiness proven in 06-07. | Pending hosted JSON-RPC/StreamableHTTP/SSE endpoint evidence. |
| 4 | Consolidation role pipeline | Runbook exists; local-staging dry run proven. | Pending production worker, provider, projection, gate-suite, and supervision evidence. |
| 5 | Signed provenance | Runbook exists; local C2PA validation proven. | Pending production verifier, issuer/root, rotation, and quarantine evidence. |
| 6 | Multimodal retrieval | Runbook exists; FR-20 local/live breadth proven. | Pending production extractor, media-embedding, object-store, retrieval, and job evidence. |
| 7 | Privacy and erasure | Runbook exists; env/secrets catalog exists; local-staging dry run proven. | Pending production KMS, residency, tombstone, legal delete, and corroboration evidence. |
| 8 | Observability dashboards | Runbook exists; local-staging dry run proven. | Pending hosted dashboard/package, access-control, freshness, and alert evidence. |
| 9 | Parametric tier | Runbook exists; FR-21 trainer/rollback local validation and rollback plan exist. | Pending deployed LoRA/test-time-training trainer, protected suite, and rollback drill evidence. |
| 10 | Live parity suite | Runbook exists; 06-07 DSN suite green. | Pending production all-row release audit with `--require-production-validated`. |

## Production Boundary

The executor must not mark any row Done from local evidence. Each row flips only
when the operator runs:

```bash
infra/scripts/capture-production-evidence.sh /secure/path/to/production-soak-manifest.json
```

with a manifest whose validation scope contains:

```json
{
  "production_validated": true,
  "target_environment": "production",
  "operator_asserted": true
}
```

and the resulting `release-audit --require-production-validated
--require-provider-forbid-local` output reports `ok=true` and `findings=[]`.

## Production Input Preflight

Checked 2026-06-25 after push `129234a`:

- GitHub remote `onfire7777/Mnemosyne` default branch `main` points at
  `129234ac947145648c058ee06f1dfe36e44eb1c2`.
- GitHub CI for `129234ac947145648c058ee06f1dfe36e44eb1c2` completed
  successfully in run `28142616744`.
- `infra/templates/production-soak-manifest.template.json` is structurally
  production-scoped with `production_validated=true`,
  `target_environment=production`, `operator_asserted=true`, and 28 checks.
- The template contains 19 production placeholders that must be replaced outside
  the repo before operator capture:
  `MNEMOSYNE_PROD_C2PA_TOOL`, `MNEMOSYNE_PROD_CHANGE_TICKET`,
  `MNEMOSYNE_PROD_DASHBOARD_URL`, `MNEMOSYNE_PROD_EVIDENCE_DIR`,
  `MNEMOSYNE_PROD_IDP_AUDIENCE`, `MNEMOSYNE_PROD_IDP_ISSUER`,
  `MNEMOSYNE_PROD_IDP_JWKS_URL`, `MNEMOSYNE_PROD_MCP_HTTP_BASE_URL`,
  `MNEMOSYNE_PROD_MCP_HTTP_HEALTH_URL`, `MNEMOSYNE_PROD_MCP_HTTP_RPC_URL`,
  `MNEMOSYNE_PROD_MCP_STREAMABLE_HTTP_BASE_URL`,
  `MNEMOSYNE_PROD_MCP_STREAMABLE_HTTP_HEALTH_URL`,
  `MNEMOSYNE_PROD_MCP_STREAMABLE_HTTP_URL`, `MNEMOSYNE_PROD_OPERATOR_NAME`,
  `MNEMOSYNE_PROD_OPERATOR_USER`, `MNEMOSYNE_PROD_RECOMPUTE_CID`,
  `MNEMOSYNE_PROD_TENANT`, `MNEMOSYNE_PROD_TLS_HOSTNAME`, and
  `MNEMOSYNE_PROD_TLS_URL`.
- None of those production placeholder environment variables are set in the
  current Codex environment. Production evidence capture cannot honestly run
  here without operator-provided deployed endpoints and evidence paths.

## Current Status

- Executor readiness: complete.
- Operator production evidence: pending for all 10 rows.
- Strict audit rows: remain Partial.
- v1.0 sign-off: pending production evidence pass.
