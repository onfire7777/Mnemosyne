# Environment And Secrets Guidance

**No secret values belong in this file.** This document names environment
variables, purposes, and custody sources only. Do not add bearer tokens, private
keys, passwords, copied provider credentials, raw DSNs, or decrypted secret
material.

## Production Evidence Inputs

Use `infra/templates/production-soak-manifest.template.json` as the command
shape. Copy `infra/templates/production-render.env.example` outside the
repository, fill the blank non-secret values there, then render with
`infra/scripts/render-production-soak-manifest.sh --check-environment` and
`infra/scripts/render-production-soak-manifest.sh --output /secure/path/to/production-soak-manifest.json`
before running `infra/scripts/capture-production-evidence.sh`.

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
| `MNEMOSYNE_PROD_MCP_HTTP_BASE_URL` | Hosted JSON-RPC MCP base URL | Deployment metadata | MCP ops gate |
| `MNEMOSYNE_PROD_MCP_HTTP_HEALTH_URL` | Hosted JSON-RPC MCP health URL | Deployment metadata | MCP HTTP soak |
| `MNEMOSYNE_PROD_MCP_HTTP_RPC_URL` | Hosted JSON-RPC MCP RPC URL | Deployment metadata | MCP HTTP soak |
| `MNEMOSYNE_PROD_MCP_STREAMABLE_HTTP_BASE_URL` | Hosted SDK StreamableHTTP base URL | Deployment metadata | MCP ops gate |
| `MNEMOSYNE_PROD_MCP_STREAMABLE_HTTP_HEALTH_URL` | Hosted SDK StreamableHTTP health URL | Deployment metadata | StreamableHTTP soak |
| `MNEMOSYNE_PROD_MCP_STREAMABLE_HTTP_URL` | Hosted SDK StreamableHTTP endpoint URL | Deployment metadata | StreamableHTTP soak |
| `MNEMOSYNE_PROD_OPERATOR_NAME` | Human operator display name | Release metadata | operator attestation |
| `MNEMOSYNE_PROD_OPERATOR_USER` | Human operator account id | Release metadata | operator attestation |
| `MNEMOSYNE_PROD_RECOMPUTE_CID` | Production evidence CID for recompute probe | Prior production ingestion evidence | projection recompute gate |
| `MNEMOSYNE_PROD_TENANT` | Production tenant id used for evidence capture | Deployment metadata | tenant-scoped production checks |
| `MNEMOSYNE_PROD_TLS_HOSTNAME` | Production TLS hostname | Certificate/deployment metadata | TLS gates |
| `MNEMOSYNE_PROD_TLS_URL` | Production TLS endpoint URL | Certificate/deployment metadata | TLS gates |

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
`--queue-backend`, `--queue-tenant`, `--runtime-state`, `--object-store`, and
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
2. `infra/scripts/capture-production-evidence.sh` run against that manifest.
3. `release-audit` reports `ok: true` with
   `--require-production-validated --require-provider-forbid-local`.

## Hard Rules

- Never commit real environment files or provider credential files.
- Never put secrets into soak-manifest `args` or `global_args`.
- Never paste Keycloak tokens, Vault tokens, JWKS private material, KMS keys,
  bearer tokens, or provider API keys into Markdown evidence.
- If a secret appears in committed history, rotate it; deleting the line in a
  later commit is not enough.
