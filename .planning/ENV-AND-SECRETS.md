# Environment And Secrets Guidance

**No secret values belong in this file.** This document names environment
variables, purposes, and custody sources only. Do not add bearer tokens, private
keys, passwords, copied provider credentials, raw DSNs, or decrypted secret
material.

## Production Evidence Inputs

Use `infra/templates/production-soak-manifest.template.json` as the command
shape. Prefer starting from the external custody packet created by
`infra/scripts/prepare-production-evidence-custody.py`; it includes a
`production-render.env` copied from the template. Fill the blank non-secret
values there, then render with
`RUNTIME_ENV_FILE=/secure/path/to/mnemosyne-production-runtime.env` and
`infra/scripts/render-production-soak-manifest.sh --env-file /secure/path/to/mnemosyne-tier-b-custody/production-render.env --runtime-env-file "$RUNTIME_ENV_FILE" --check-environment`
and
`infra/scripts/render-production-soak-manifest.sh --env-file /secure/path/to/mnemosyne-tier-b-custody/production-render.env --runtime-env-file "$RUNTIME_ENV_FILE" --output /secure/path/to/production-soak-manifest.json`
before running `infra/scripts/capture-production-evidence.sh`. The renderer
parses `--env-file` through `infra/scripts/load-env.py`, rejects unsafe dotenv
syntax, unexpected keys, symlinks, group/world-readable files, and repo-local
env-file paths, and still accepts already-exported environment variables when
`--env-file` is omitted for legacy operator shells.
Copy `infra/templates/provider-manifest.production.template.json` to
`$MNEMOSYNE_PROD_EVIDENCE_DIR/provider-manifest.production.json` outside the
repository and fill that external copy with production provider values or
environment-variable references before rendering. The provider manifest is a
retained production input artifact shared across B1, B2, B4, B6, B7, B9, and
B10; keep `forbid_local: true` and do not split provider-check subchecks into
row-local manifests.
`infra/scripts/render-production-soak-manifest.sh --check-environment` parses
that external provider manifest when present, reports the referenced provider
environment-variable names under `provider_manifest_env_refs`, and fails before
capture if any referenced provider env var is unset in either the process
environment or the strict external `--runtime-env-file`. Use
`--runtime-env-file "$RUNTIME_ENV_FILE"` for the same secret-bearing
runtime/provider values later passed to
`capture-production-evidence.sh --env-file "$RUNTIME_ENV_FILE"`; the renderer allowlist-loads those
names for validation only and does not write values or the env-file path into
the manifest or report. Values remain redacted.
Provider manifest `command` env vars must resolve to a single absolute,
external, non-symlinked executable path with no arguments after `argv[0]`;
production capture records that executable's size and SHA-256 digest in
`preflight.json.executable_tool_references`, copies it into
`OUT_ROOT/tool-artifacts/`, and rewrites the retained provider manifest
snapshot to execute the retained copy.
The check command prints key names only; it also verifies the production input
directory exists outside the repo and `MNEMOSYNE_PROD_C2PA_TOOL` resolves to an
absolute external executable outside the repository without a symlink or
non-canonical wrapper path. Production preflight records the executable's size
and SHA-256 digest in `preflight.json` under `executable_tool_references`,
copies the executable into `OUT_ROOT/tool-artifacts/`, and rewrites direct
`--c2pa-tool` plus retained suite tool references to the retained copy. When
the `MNEMOSYNE_C2PA_TOOL` fallback is needed, capture emits `tool-env.sh` with
the retained path and sources it before `deployment-soak`. A green check also means
every manifest-referenced file or directory under `MNEMOSYNE_PROD_EVIDENCE_DIR`
exists. Missing production inputs are reported by relative artifact name only,
with redacted detail entries that show the check/command/option requiring each
artifact; configured absolute path values remain redacted.

Secrets and credentials must be supplied outside manifest `args` and
`global_args`, using runtime environment variables or provider custody files.
The capture wrapper rejects secret-bearing options such as `--token`,
`--password`, `--client-secret`, `--private-key`, and `--key`.

## Production Manifest Placeholders

The production soak template contains these non-secret placeholders. Render
them outside the repository with
`infra/scripts/render-production-soak-manifest.sh` before running
`infra/scripts/capture-production-evidence.sh`.

| Placeholder | Purpose | Source | Consumed by |
|---|---|---|---|
| `MNEMOSYNE_PROD_C2PA_TOOL` | Production C2PA verifier command/path | Deployment image/config | provenance gates |
| `MNEMOSYNE_PROD_CHANGE_TICKET` | Operator change or release ticket id | Release metadata | production validation scope |
| `MNEMOSYNE_PROD_DASHBOARD_URL` | Hosted ops dashboard URL | Deployment metadata | dashboard gate |
| `MNEMOSYNE_PROD_EVIDENCE_DIR` | Prepared absolute external production input-artifact directory outside the repo | Operator workstation or secure artifact store | soak manifest gate commands; capture output is passed separately as `OUT_ROOT` |
| `MNEMOSYNE_PROD_IDP_AUDIENCE` | Production IdP token audience | IdP client config | IdP/JWKS gates |
| `MNEMOSYNE_PROD_IDP_ISSUER` | Production IdP issuer URL | IdP realm config | IdP/JWKS gates |
| `MNEMOSYNE_PROD_IDP_JWKS_URL` | Production JWKS endpoint | IdP realm config | IdP/JWKS gates |
| `MNEMOSYNE_PROD_MCP_HTTP_BASE_URL` | Hosted JSON-RPC MCP base URL | Deployment metadata | `mcp-http-soak`; `mcp-ops-check` consumes `mcp-ops-bundle.json` |
| `MNEMOSYNE_PROD_MCP_HTTP_HEALTH_URL` | Hosted JSON-RPC MCP health URL | Deployment metadata | MCP HTTP soak |
| `MNEMOSYNE_PROD_MCP_HTTP_RPC_URL` | Hosted JSON-RPC MCP RPC URL | Deployment metadata | MCP HTTP soak |
| `MNEMOSYNE_PROD_MCP_STREAMABLE_HTTP_BASE_URL` | Hosted SDK StreamableHTTP base URL | Deployment metadata | `mcp-streamable-http-soak`; `mcp-ops-check` consumes `mcp-ops-bundle.json` |
| `MNEMOSYNE_PROD_MCP_STREAMABLE_HTTP_HEALTH_URL` | Hosted SDK StreamableHTTP health URL | Deployment metadata | StreamableHTTP soak |
| `MNEMOSYNE_PROD_MCP_STREAMABLE_HTTP_URL` | Hosted SDK StreamableHTTP endpoint URL | Deployment metadata | StreamableHTTP soak |
| `MNEMOSYNE_PROD_OPERATOR_NAME` | Human operator display name | Release metadata | operator attestation |
| `MNEMOSYNE_PROD_OPERATOR_USER` | Human operator account id | Release metadata | operator attestation |
| `MNEMOSYNE_PROD_RECOMPUTE_CID` | Production evidence CID for recompute probe | Prior production ingestion evidence | projection recompute gate |
| `MNEMOSYNE_PROD_TENANT` | Production tenant id used for evidence capture | Deployment metadata | tenant-scoped production checks |
| `MNEMOSYNE_PROD_TLS_HOSTNAME` | Production TLS hostname | Certificate/deployment metadata | TLS gates |
| `MNEMOSYNE_PROD_TLS_URL` | Production TLS endpoint URL | Certificate/deployment metadata | TLS gates |

## Production Provider Manifest Environment References

`infra/templates/provider-manifest.production.template.json` may reference these
runtime variables through `{ "env": "..." }` objects. Their values stay outside
the committed template and outside soak-manifest `args`.

| Variable | Purpose | Source | Consumed by |
|---|---|---|---|
| `MNEMOSYNE_CANDIDATE_EXTRACTOR_COMMAND` | Command-backed candidate extractor | Provider custody file or deployment env | `provider-check` candidate_extractor |
| `MNEMOSYNE_CANDIDATE_EXTRACTOR_PROVIDER` | Enables command-backed candidate extractor | Provider profile/runtime env | CLI consolidation/provider-check |
| `MNEMOSYNE_ENTITY_RESOLVER_COMMAND` | Command-backed entity resolver | Provider custody file or deployment env | `provider-check` entity_resolver |
| `MNEMOSYNE_ENTITY_RESOLVER_PROVIDER` | Enables command-backed entity resolver | Provider profile/runtime env | CLI consolidation/provider-check |
| `MNEMOSYNE_LESSON_DISTILLER_COMMAND` | Command-backed lesson distiller | Provider custody file or deployment env | `provider-check` lesson_distiller |
| `MNEMOSYNE_LESSON_DISTILLER_PROVIDER` | Enables command-backed lesson distiller | Provider profile/runtime env | CLI consolidation/provider-check |
| `MNEMOSYNE_PROVIDER_OIDC_AUDIENCE` | Provider-check OIDC audience | IdP provider config | `provider-check` oidc |
| `MNEMOSYNE_PROVIDER_OIDC_AUTHZ_POLICY_FILE` | Provider-check OIDC authz policy artifact | Versioned deployment artifact | `provider-check` oidc |
| `MNEMOSYNE_PROVIDER_OIDC_ISSUER` | Provider-check OIDC issuer | IdP provider config | `provider-check` oidc |
| `MNEMOSYNE_PROVIDER_OIDC_JWKS_URL` | Provider-check OIDC JWKS endpoint | IdP provider config | `provider-check` oidc |
| `MNEMOSYNE_SKILL_INDUCER_COMMAND` | Command-backed skill/procedure inducer | Provider custody file or deployment env | `provider-check` skill_inducer |
| `MNEMOSYNE_SKILL_INDUCER_PROVIDER` | Enables command-backed skill/procedure inducer | Provider profile/runtime env | CLI consolidation/provider-check |
| `MNEMOSYNE_SUMMARIZER_COMMAND` | Command-backed evidence summarizer | Provider custody file or deployment env | `provider-check` summarizer |
| `MNEMOSYNE_SUMMARIZER_PROVIDER` | Enables command-backed evidence summarizer | Provider profile/runtime env | CLI consolidation/provider-check |

## Environment Catalog

| Variable or option | Purpose | Source | Consumed by |
|---|---|---|---|
| `MNEMOSYNE_POSTGRES_DSN` | Production Postgres connection | Secret manager or shell env | Postgres backend, live suite, retrieval gates |
| `MNEME_BACKEND` | CLI backend selector | Deployment env | CLI runtime |
| `MNEME_STORE` | Local store path when using local backend | Deployment env | CLI runtime |
| `MNEMOSYNE_QUEUE_BACKEND` | Worker queue backend | Deployment env | worker gates, `deployment-soak` |
| `MNEMOSYNE_QUEUE_TENANT` | Queue tenant scope | Deployment env | worker gates |
| `MNEMOSYNE_RUNTIME_RESIDENCY` | Runtime residency label | Deployment env | policy/privacy gates |
| `MNEMOSYNE_REQUIRE_RUNTIME_RESIDENCY` | Fail-closed residency enforcement | Deployment env | runtime policy |
| `MNEMOSYNE_ALLOWED_RESIDENCIES` | Allowed residency set | Deployment env | policy/privacy gates |
| `MNEMOSYNE_ALLOWED_RESIDENCY_TRANSFERS` | Allowed source-to-target residency transfers | Deployment env | policy/privacy gates |
| `MNEMOSYNE_EMBEDDING_PROVIDER` | Embedding provider selector | Deployment env | provider-check, retrieval gates |
| `MNEMOSYNE_EMBEDDING_URL` | Embedding endpoint | Secret manager or env | provider-check, retrieval gates |
| `MNEMOSYNE_EMBEDDING_MODEL` | Embedding model id | Deployment env | provider-check |
| `MNEMOSYNE_EMBEDDING_DIMS` | Embedding dimensionality | Deployment env | provider-check, vector retrieval |
| `MNEMOSYNE_EMBEDDING_API_KEY` | Embedding provider credential | Secret manager or provider file | provider-check |
| `MNEMOSYNE_RERANKER_PROVIDER` | Reranker provider selector | Deployment env | provider-check, retrieval gates |
| `MNEMOSYNE_RERANKER_URL` | Reranker endpoint | Secret manager or env | provider-check, retrieval gates |
| `MNEMOSYNE_RERANKER_MODEL` | Reranker model id | Deployment env | provider-check |
| `MNEMOSYNE_RERANKER_API_KEY` | Reranker provider credential | Secret manager or provider file | provider-check |
| `MNEMOSYNE_LEXICAL_PROVIDER` | Lexical retrieval provider selector | Deployment env | retrieval gates |
| `MNEMOSYNE_LEXICAL_COMMAND` | Command-backed lexical adapter | Command provider file | retrieval gates |
| `MNEMOSYNE_GRAPH_PROVIDER` | Graph retrieval provider selector | Deployment env | graph/PPR gates |
| `MNEMOSYNE_GRAPH_COMMAND` | Command-backed graph adapter | Command provider file | graph/PPR gates |
| `MNEMOSYNE_MEDIA_EXTRACTOR_COMMAND` | Media extractor command provider | Command provider file | multimodal gate |
| `MNEMOSYNE_MEDIA_EMBEDDING_COMMAND` | Media embedding command provider | Command provider file | multimodal gate |
| `MNEMOSYNE_MEDIA_EMBEDDING_PROVIDER` | Media embedding provider selector | Deployment env | multimodal gate |
| `MNEMOSYNE_OBJECT_STORE` | Object store backend/path | Deployment env or provider config | object evidence, multimodal gate |
| `MNEMOSYNE_OBJECT_STORE_ENCRYPTION` | Object encryption mode | Deployment env | privacy/object gates |
| `MNEMOSYNE_OBJECT_KEY_PROVIDER` | Object key provider selector | Deployment env | privacy/object gates |
| `MNEMOSYNE_OBJECT_KEY_COMMAND` | Command-backed object key provider | Command provider file | privacy/object gates |
| `MNEMOSYNE_OBJECT_KEY_STORE` | Object key store location | Secret manager or encrypted file | privacy/object gates |
| `MNEMOSYNE_SESSION_SECRET` | Session signing secret | Secret manager only | CLI/MCP auth |
| `MNEMOSYNE_SESSION_SECRET_COMMAND` | Command-backed session secret provider | Command provider file | CLI/MCP auth |
| `MNEMOSYNE_SESSION_KEY_ID` | Active session key id | Deployment env | CLI/MCP auth |
| `MNEMOSYNE_SESSION_KEYRING` | Session keyring source | Secret manager or file | CLI/MCP auth |
| `MNEMOSYNE_MCP_SESSION_SECRET` | MCP session secret | Secret manager only | hosted MCP |
| `MNEMOSYNE_MCP_SESSION_SECRET_COMMAND` | MCP session secret command provider | Command provider file | hosted MCP |
| `MNEMOSYNE_MCP_TOKEN` | Hosted MCP bearer token | Secret manager only | MCP soak checks |
| `MNEMOSYNE_MCP_SESSION_TOKEN` | Hosted MCP session token | Secret manager only | MCP soak checks |
| `MNEMOSYNE_MCP_HTTP_AUTH_TOKEN` | HTTP MCP bearer token | Secret manager only | `mcp-http-soak` |
| `MNEMOSYNE_MCP_HTTP_BASE_URL` | HTTP MCP base URL | Deployment env | `mcp-http-soak` |
| `MNEMOSYNE_MCP_HTTP_RPC_URL` | HTTP MCP RPC URL | Deployment env | `mcp-http-soak` |
| `MNEMOSYNE_MCP_HTTP_HEALTH_URL` | HTTP MCP health URL | Deployment env | `mcp-http-soak` |
| `MNEMOSYNE_MCP_STREAMABLE_HTTP_URL` | StreamableHTTP MCP URL | Deployment env | `mcp-streamable-http-soak` |
| `MNEMOSYNE_MCP_STREAMABLE_HTTP_BASE_URL` | StreamableHTTP MCP base URL | Deployment env | `mcp-streamable-http-soak` |
| `MNEMOSYNE_MCP_STREAMABLE_HTTP_SESSION_TOKEN` | StreamableHTTP session token | Secret manager only | `mcp-streamable-http-soak` |
| `MNEMOSYNE_MCP_TLS_CERT_FILE` | Hosted MCP cert file | Secret manager or cert volume | TLS gates |
| `MNEMOSYNE_MCP_TLS_KEY_FILE` | Hosted MCP key file | Secret manager or cert volume | TLS gates |
| `MNEMOSYNE_MCP_TLS_CLIENT_CA_FILE` | Client CA bundle | Secret manager or cert volume | TLS gates |
| `MNEMOSYNE_IDP_ISSUER` | OIDC issuer | Keycloak config | IdP gates |
| `MNEMOSYNE_IDP_AUDIENCE` | OIDC audience | Keycloak config | IdP gates |
| `MNEMOSYNE_IDP_JWKS_URL` | JWKS endpoint | Keycloak config | JWKS live gate |
| `MNEMOSYNE_IDP_JWKS_FILE` | Offline JWKS fallback | Secret manager or config volume | IdP gates |
| `MNEMOSYNE_IDP_TOKEN` | Operator-scoped IdP token | Secret manager only | JWKS/policy gates |
| `MNEMOSYNE_IDP_AUTHZ_POLICY_FILE` | Authz policy file | Versioned deployment artifact | policy rollout gate |
| `MNEMOSYNE_EXPECTED_CURRENT_IDP_AUTHZ_POLICY_FINGERPRINT` | Current policy fingerprint | Release metadata | policy rollout gate |
| `MNEMOSYNE_EXPECTED_CANDIDATE_IDP_AUTHZ_POLICY_FINGERPRINT` | Candidate policy fingerprint | Release metadata | policy rollout gate |
| `MNEMOSYNE_C2PA_TOOL` | C2PA verifier path | Deployment image/config | provenance gates |
| `MNEMOSYNE_PROVENANCE_TRUST_POLICY` | C2PA trust policy | Versioned deployment artifact | provenance trust gate |
| `MNEMOSYNE_PARAMETRIC_PROVIDER` | Parametric provider selector | Deployment env | trainer gate |
| `MNEMOSYNE_PARAMETRIC_COMMAND` | Command-backed trainer provider | Command provider file | trainer gate |
| `MNEMOSYNE_PARAMETRIC_ARTIFACT_STORE` | Trainer artifact store | Deployment env or object store | trainer gate |
| `MNEMOSYNE_HOSTED_LLM_TEST_KEY` | Hosted LLM probe key | Secret manager only | hosted-LLM gate |
| `MNEMOSYNE_OPS_DASHBOARD_CHECK_TIMEOUT` | Dashboard gate timeout | Deployment env | dashboard gate |
| `MNEMOSYNE_PRODUCTION_SOAK_CHECK_TIMEOUT` | Production soak command timeout | Deployment env | capture wrapper |
| `MNEMOSYNE_DEPLOYMENT_SOAK_CHECK_TIMEOUT` | Deployment soak command timeout | Deployment env | deployment soak |
| `MNEMOSYNE_EXPECTED_RELEASE_FINGERPRINT` | Expected release/evidence fingerprint | Release metadata | capture wrapper |

## Deployment-Soak Global Placement Options

These are manifest placement options, not secrets: `--backend`,
`--queue-backend`, `--queue-tenant`, `--object-store`, and
`--parametric-artifact-store`. Put only non-secret selectors and store names in
the manifest. Secret-bearing values stay in environment, mounted files, Vault,
Keycloak, KMS, or command providers.

## Keycloak Wiring

Use `infra/keycloak/realm-mnemosyne.json` and
`infra/scripts/setup-keycloak.sh` as the provisioning references. The operator
sets issuer, audience, JWKS URL, role claim, tenant claim, user claim, trust
claim, session-id claim, timeout, and policy simulation files through the
environment or mounted config. Do not paste realm JSON secrets or tokens here.

## Vault And Session-Secret Custody

Use `infra/vault/providers.json`,
`infra/vault/mnemosyne-transit-policy.hcl`,
`infra/vault/vault-object-key-provider.py`, and
`infra/scripts/setup-vault.sh` as the provisioning references. Session secrets
and object keys should be retrieved through command providers or mounted secret
files, with key ids and keyring metadata recorded separately from values.

## KMS And Object-Key Boundary

Object evidence encryption must use the configured object-key provider boundary.
Legal hard-delete evidence must prove key shredding through the provider without
printing key bytes. The production evidence bundle should contain redacted
attestations, fingerprints, key ids, and provider status only.

## Required Custody Surfaces

- Postgres/retrieval: production DSN and provider endpoints for ParadeDB/BM25,
  AGE, pgvector, embedding, and reranker validation.
- IdP and authz: Keycloak/OIDC issuer, audience, JWKS, rollout fingerprint, and
  operator-scoped token custody.
- MCP: hosted HTTP and StreamableHTTP endpoints plus bearer/session-token
  custody.
- Object and provenance: object store, KMS/key-provider custody, C2PA trust
  roots, and residency-policy configuration.
- Learning providers: model-backed consolidation providers, hosted trainer,
  protected-suite artifact store, rollback provider, and dashboard/alert
  endpoints.
- C2PA/provenance: trusted issuer/root assets from `infra/c2pa/`, verifier tool
  path, trust-policy artifact, rotation metadata, and quarantine output shape.
- Deployment wrapper: `MNEMOSYNE_EXPECTED_RELEASE_FINGERPRINT` and
  `MNEMOSYNE_PRODUCTION_SOAK_CHECK_TIMEOUT` for
  `infra/scripts/capture-production-evidence.sh`.

## Acceptance

The only production acceptance path is:

1. Operator-owned production manifest with `validation_scope.production_validated`
   set to `true`, `target_environment` set to `production`, and
   `operator_asserted` set to `true`.
2. `infra/scripts/capture-production-evidence.sh --env-file "$RUNTIME_ENV_FILE" --fingerprint-record-output`
   run against that manifest, writing the external fingerprint record outside
   the evidence bundle under review.
3. `release-audit` reports `ok: true` with
   `--require-production-validated --require-provider-forbid-local`.
4. `production-evidence-verify` passes offline against the retained output
   bundle with `--fingerprint-record` pointing to the independently retained
   out-of-band fingerprint record, not `summary.json` inside the bundle under
   review. The retained bundle must include a non-empty
   `preflight.json.required_input_artifacts` list, matching
   `preflight.json.parity_row_readiness`, and the retained `input-artifacts/`
   directory.

## Hard Rules

- Never commit real environment files or provider credential files.
- Never put secrets into soak-manifest `args` or `global_args`.
- Never paste Keycloak tokens, Vault tokens, JWKS private material, KMS keys,
  bearer tokens, or provider API keys into Markdown evidence.
- If a secret appears in committed history, rotate it; deleting the line in a
  later commit is not enough.
