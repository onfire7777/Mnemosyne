# External Integrations

**Analysis Date:** 2026-07-08

## APIs & External Services

**Model Providers:**
- HTTP embedding provider - dense embeddings for retrieval in `src/mnemosyne/retrieval.py`.
  - SDK/Client: stdlib HTTP through `HttpEmbeddingProvider`
  - Auth: `MNEMOSYNE_EMBEDDING_API_KEY`
- HTTP reranker provider - cross-encoder reranking for retrieval in `src/mnemosyne/retrieval.py`.
  - SDK/Client: stdlib HTTP through `HttpReranker`
  - Auth: `MNEMOSYNE_RERANKER_API_KEY`
- Embedding/reranker microservice - self-hosted `/health`, `/embed`, and `/rerank` routes in `services/embedding/app.py`.
  - SDK/Client: FastAPI + uvicorn when installed, stdlib `http.server` fallback
  - Auth: Not built into the service; expected to sit behind controlled network/ingress
- Rust provider sidecar - Axum/FastEmbed provider server in `rust/mneme-providers/`.
  - SDK/Client: `axum`, `tokio`, optional `fastembed`
  - Auth: `MNEMOSYNE_EMBEDDING_API_KEY` / `MNEMOSYNE_RERANKER_API_KEY` when backend uses remote APIs
- Role and parametric providers - command/HTTP provider surfaces in `infra/providers/role-llm.py`, `infra/providers/role-http.py`, `infra/providers/parametric-trainer.py`, and `infra/providers/parametric-http.py`.
  - SDK/Client: command adapters plus hosted HTTP behind `roles.mnemo.local` in `infra/caddy/Caddyfile`
  - Auth: provider-specific env refs and command custody; secrets are externalized

**Identity, KMS, and Provenance:**
- Keycloak OIDC/JWKS - production IdP for session exchange in `infra/docker-compose.providers.yml`, `infra/keycloak/`, `src/mnemosyne/security.py`, and `src/mnemosyne/mcp_server.py`.
  - SDK/Client: custom `OidcJwtVerifier`
  - Auth: `MNEMOSYNE_MCP_IDP_*`, `MNEMOSYNE_IDP_*`
- HashiCorp Vault - transit/KV-backed object keys, session secrets, and audit HMACs in `infra/vault/` and `src/mnemosyne/storage.py`.
  - SDK/Client: command providers using stdlib HTTP in `infra/vault/vault-object-key-provider.py`, `infra/vault/vault-session-secret-provider.py`, and `infra/vault/audit-hmac-adapter.py`
  - Auth: `VAULT_TOKEN` or `VAULT_TOKEN_FILE`
- C2PA/c2patool - provenance verification in `src/mnemosyne/provenance.py` and `infra/c2pa/`.
  - SDK/Client: shell-free subprocess adapter `C2paToolVerifier`
  - Auth: trusted issuer/root policy via `MNEMOSYNE_TRUSTED_PROVENANCE_ISSUERS`, `MNEMOSYNE_TRUSTED_PROVENANCE_ROOTS`, and `MNEMOSYNE_PROVENANCE_TRUST_POLICY`

**Infrastructure Services:**
- Caddy + step-ca - TLS ingress, mTLS for MCP, and non-loopback service hostnames in `infra/caddy/Caddyfile`.
  - SDK/Client: Docker Compose services in `infra/docker-compose.prod.yml`
  - Auth: client certificate files and external secret files mounted by Compose
- Ollama - optional/local role-LLM backend in `infra/docker-compose.prod.yml` and `infra/providers/role-llm.py`.
  - SDK/Client: HTTP endpoint configured through `OLLAMA_URL`
  - Auth: Not detected in code; network/profile isolation is used
- VictoriaMetrics, vmalert, Grafana, blackbox-exporter - observability stack in `infra/docker-compose.prod.yml` and `infra/observability/`.
  - SDK/Client: HTTP services and CLI checks
  - Auth: Grafana admin password via external Docker secret file

## Data Storage

**Databases:**
- Local in-memory/JSON store
  - Connection: `MNEME_STORE` or `--store`
  - Client: `LocalMemoryEngine` in `src/mnemosyne/engine.py`
- SQLite per-tenant store
  - Connection: `--backend sqlite --store <dir>` or MCP `MNEME_BACKEND=sqlite`
  - Client: `SqliteEngine` in `src/mnemosyne/sqlite_engine.py`
- PostgreSQL 16
  - Connection: `MNEMOSYNE_POSTGRES_DSN`
  - Client: `PostgresEngine`, `PostgresQueue`, and `PostgresRuntimeState` in `src/mnemosyne/postgres_engine.py`, `src/mnemosyne/queue.py`, and `src/mnemosyne/postgres_runtime_state.py`
  - Extensions/roles: pgvector and pgaudit in `infra/postgres/Dockerfile`; role separation in `infra/postgres/roles.sql`

**File Storage:**
- Local content-addressed object store in `.mnemosyne/objects` through `LocalObjectStore` in `src/mnemosyne/storage.py`.
- AES-GCM local object store through `EncryptedLocalObjectStore` in `src/mnemosyne/storage.py`.
- S3-compatible object store, implemented for SeaweedFS, through `S3ObjectStore` and `EncryptedS3ObjectStore` in `src/mnemosyne/storage.py`.
- Production SeaweedFS service is declared in `infra/docker-compose.prod.yml`.

**Caching:**
- No Redis or Memcached service detected.
- Model/provider caches use `HF_HOME` and `FASTEMBED_CACHE_DIR` in `services/embedding/Dockerfile` and `rust/mneme-providers/Dockerfile`.
- OIDC JWKS caching is handled in `OidcJwtVerifier` and MCP session exchange config in `src/mnemosyne/security.py` and `src/mnemosyne/mcp_server.py`.

## Authentication & Identity

**Auth Provider:**
- Custom signed sessions with optional OIDC exchange.
  - Implementation: `SessionTokenVerifier` and `OidcJwtVerifier` in `src/mnemosyne/security.py`
  - MCP HTTP session exchange: `/session/exchange` in `src/mnemosyne/mcp_server.py`
  - Bearer auth: `MNEMOSYNE_MCP_TOKEN`
  - Signed-session custody: `MNEMOSYNE_MCP_SESSION_SECRET`, `MNEMOSYNE_MCP_SESSION_KEYRING`, or `MNEMOSYNE_MCP_SESSION_SECRET_COMMAND`
  - Production ingress mTLS: `mcp.mnemo.local` in `infra/caddy/Caddyfile`

## Monitoring & Observability

**Error Tracking:**
- Dedicated SaaS error tracking is not detected.

**Logs:**
- Application logs use stdout/stderr from CLI, MCP, workers, and containers.
- Security/audit events are represented by the audit chain in `src/mnemosyne/audit_chain.py`, Postgres audit support in `sql/schema.sql`, and pgaudit-enabled Postgres in `infra/postgres/Dockerfile`.
- Metrics/dashboard checks use `ops-report`, `ops-metrics-push`, and `ops-dashboard-check` commands in `src/mnemosyne/cli.py` with VictoriaMetrics/Grafana services in `infra/docker-compose.prod.yml`.

## CI/CD & Deployment

**Hosting:**
- Local development uses `uv` and optional Docker Compose services from `docker-compose.yml` and `infra/docker-compose.providers.yml`.
- Production hosting is self-hosted Docker Compose via `infra/docker-compose.prod.yml`, `infra/Dockerfile`, `infra/caddy/Caddyfile`, and `infra/prod/README.md`.

**CI Pipeline:**
- `.github/workflows/ci.yml` gates pushes and pull requests with ruff, locked Python test runs, config drift checks, G0 preregistration replay, and Postgres-backed live tests.
- Native wheel builds and built-wheel install/import smoke are merge-gating for the current macOS arm64 / Linux x86_64 matrix; DST/chaos remains a non-gating nightly/manual soak until that suite is ratcheted.
- Supply-chain and production evidence gates are also available as operator scripts: `infra/scripts/verify-supply-chain.sh`, `infra/scripts/capture-production-evidence.sh`, and `infra/scripts/render-production-soak-manifest.sh`.
- Provider bake-off evidence packaging is local/CI-runnable through `eval/provider_bakeoff/run.py`; it consumes retained SLO reports plus `provider-check` output and does not authorize default flips.

## Environment Configuration

**Required env vars:**
- Runtime/backend: `MNEME_BACKEND`, `MNEME_STORE`, `MNEMOSYNE_POSTGRES_DSN`
- Retrieval: `MNEMOSYNE_EMBEDDING_PROVIDER`, `MNEMOSYNE_EMBEDDING_URL`, `MNEMOSYNE_RERANKER_PROVIDER`, `MNEMOSYNE_RERANKER_URL`, `MNEMOSYNE_LEXICAL_PROVIDER`, `MNEMOSYNE_GRAPH_PROVIDER`
- MCP HTTP/session: `MNEMOSYNE_MCP_HTTP_HOST`, `MNEMOSYNE_MCP_HTTP_PORT`, `MNEMOSYNE_MCP_HTTP_RPC_PATH`, `MNEMOSYNE_MCP_REQUIRE_SESSION`, `MNEMOSYNE_MCP_TOKEN`, `MNEMOSYNE_MCP_SESSION_SECRET_COMMAND`
- OIDC/JWKS: `MNEMOSYNE_MCP_IDP_JWKS_URL`, `MNEMOSYNE_MCP_IDP_ISSUER`, `MNEMOSYNE_MCP_IDP_AUDIENCE`, `MNEMOSYNE_MCP_IDP_AUTHZ_POLICY_FILE`
- Object/key storage: `MNEMOSYNE_OBJECT_STORE`, `MNEMOSYNE_OBJECT_STORE_ENCRYPTION`, `MNEMOSYNE_OBJECT_KEY_COMMAND`, `MNEMOSYNE_S3_ENDPOINT`, `MNEMOSYNE_S3_BUCKET`, `MNEMOSYNE_S3_CREDENTIALS_FILE`
- Vault: `VAULT_ADDR`, `VAULT_TOKEN_FILE`, `VAULT_CACERT`, `MNEMOSYNE_VAULT_WRAP_DIR`
- Provenance/media/parametric: `MNEMOSYNE_C2PA_TOOL`, `MNEMOSYNE_MEDIA_EXTRACTOR_COMMAND`, `MNEMOSYNE_MEDIA_EMBEDDING_COMMAND`, `MNEMOSYNE_PARAMETRIC_COMMAND`

**Secrets location:**
- Checked-in env profiles `infra/profiles/self-hosted.env` and `infra/profiles/cloud.env` are documented as non-secret value profiles; their contents were not read.
- Production secrets are referenced through external files under `${MNEMO_SECRETS_DIR:-/secure/outside/repo}` in `infra/docker-compose.prod.yml`.
- `.gitignore` excludes `.env`, `.env.*`, key files, certificate files, credential JSON, `secrets.json`, local databases, and `.mnemosyne/`.

## Webhooks & Callbacks

**Incoming:**
- MCP JSON-RPC HTTP endpoint: `/mcp` in `src/mnemosyne/mcp_server.py`.
- MCP SDK StreamableHTTP endpoint: `/mcp` plus `/healthz` in `src/mnemosyne/mcp_server.py`; proxied under `/stream` by `infra/caddy/Caddyfile`.
- MCP session exchange: `/session/exchange` in `src/mnemosyne/mcp_server.py`.
- Embedding service: `/health`, `/embed`, and `/rerank` in `services/embedding/app.py`.
- Role/parametric provider HTTP surfaces: `roles.mnemo.local` routes in `infra/caddy/Caddyfile`.
- Alert receiver for vmalert: `infra/observability/alert-sink.py`.

**Outgoing:**
- OIDC/JWKS fetches to the configured IdP in `src/mnemosyne/oidc_jwks.py` and `src/mnemosyne/security.py`.
- Vault transit/KV HTTP calls from `infra/vault/` adapters.
- S3-compatible SeaweedFS calls from `SeaweedS3Client` in `src/mnemosyne/storage.py`.
- HTTP embedding/reranker/model calls from `src/mnemosyne/retrieval.py` and provider scripts in `infra/providers/`.
- C2PA verification subprocess calls from `C2paToolVerifier` in `src/mnemosyne/provenance.py`.
- Internal vmalert notification delivery to `alert-sink` in `infra/docker-compose.prod.yml`.

---

*Integration audit: 2026-07-08*
