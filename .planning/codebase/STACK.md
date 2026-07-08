# Technology Stack

**Analysis Date:** 2026-07-08

## Languages

**Primary:**
- Python >=3.12 - core package and CLI/MCP runtime in `src/mnemosyne/`; requirement declared in `pyproject.toml`.
- Rust 2021 - optional native kernels in `rust/mnemosyne-native/` and provider sidecar in `rust/mneme-providers/`.

**Secondary:**
- SQL - Postgres schema, roles, and audit/RLS support in `sql/` and `infra/postgres/`.
- Shell - operational scripts in `infra/scripts/` and stack entrypoints in `infra/entrypoint.sh`.
- Dockerfile/Compose YAML - local and production infrastructure in `docker-compose.yml`, `infra/docker-compose.providers.yml`, and `infra/docker-compose.prod.yml`.

## Runtime

**Environment:**
- CPython >=3.12 for `mnemosyne-memory`; local shell reports Python 3.14.5.
- Container runtime uses `python:3.12-slim` in `infra/Dockerfile` and `services/embedding/Dockerfile`.
- Rust toolchains are declared as `rust-version = "1.85"` in `rust/mnemosyne-native/Cargo.toml` and `rust-version = "1.88"` in `rust/mneme-providers/Cargo.toml`; local shell reports rustc/cargo 1.95.0.

**Package Manager:**
- `uv` 0.11.16 is the documented Python environment manager in `README.md`.
- `pip` is used inside Docker images in `infra/Dockerfile` and `services/embedding/Dockerfile`.
- `cargo` manages Rust crates in `rust/mnemosyne-native/` and `rust/mneme-providers/`.
- Lockfiles: `uv.lock`, `rust/mnemosyne-native/Cargo.lock`, and `rust/mneme-providers/Cargo.lock` are present.

## Frameworks

**Core:**
- setuptools - Python packaging backend in `pyproject.toml`.
- MCP Python SDK (`mcp>=1.28,<2`) - optional MCP server mode exposed by `mneme-mcp` in `src/mnemosyne/mcp_server.py`.
- FastAPI + uvicorn - optional production ASGI layer for the embedding/reranker service in `services/embedding/app.py` and `services/embedding/requirements.txt`.
- Starlette + uvicorn - optional MCP SDK StreamableHTTP transport in `src/mnemosyne/mcp_server.py`.
- PostgreSQL 16 + pgvector + pgaudit - production retrieval/audit database in `docker-compose.yml`, `infra/postgres/Dockerfile`, and `infra/docker-compose.prod.yml`.
- SQLite - local per-tenant SQL backend in `src/mnemosyne/sqlite_engine.py` and `src/mnemosyne/sqlite_schema.py`.
- PyO3 + maturin - optional Python extension build for native kernels in `rust/mnemosyne-native/pyproject.toml` and `rust/mnemosyne-native/Cargo.toml`.

**Testing:**
- pytest 9.1.1 - test runner configured in `pyproject.toml`.
- Hypothesis >=6.100 - property-based tests declared in `pyproject.toml`.
- pytest-benchmark >=5.1 - benchmark tests declared in `pyproject.toml`.

**Build/Dev:**
- Ruff 0.15.20 - dev lint tool declared in `pyproject.toml`.
- Docker Compose v2 - local Postgres, provider, and production stacks in `docker-compose.yml`, `infra/docker-compose.providers.yml`, and `infra/docker-compose.prod.yml`.
- Caddy 2.8 + step-ca - production ingress and ACME CA in `infra/caddy/Caddyfile` and `infra/docker-compose.prod.yml`.

## Key Dependencies

**Critical:**
- `cryptography>=42` - only required Python runtime dependency, used for signing, encryption, sessions, and OIDC verification across `src/mnemosyne/`.
- `psycopg[binary]>=3.2` - optional Postgres backend dependency declared by the `postgres` extra in `pyproject.toml`.
- `mcp>=1.28,<2` - optional official MCP SDK dependency declared by the `mcp` extra in `pyproject.toml`.
- `sqlite-vec>=0.1.9` - optional SQLite vector index accelerator declared by the `sqlitevec` extra in `pyproject.toml`.
- `pyo3`, `blake2`, and `rayon` - native kernel dependencies in `rust/mnemosyne-native/Cargo.toml`.
- `axum`, `tokio`, `serde`, and optional `fastembed` - Rust provider sidecar dependencies in `rust/mneme-providers/Cargo.toml`.

**Infrastructure:**
- `fastapi`, `uvicorn[standard]`, `torch`, and `sentence-transformers` - real model path for `services/embedding/`.
- `pgvector/pgvector:pg16` - local and production Postgres base image in `docker-compose.yml` and `infra/postgres/Dockerfile`.
- `quay.io/keycloak/keycloak:25.0` and `hashicorp/vault:1.17` - local provider stack in `infra/docker-compose.providers.yml`.
- `victoriametrics`, `vmalert`, `grafana`, `blackbox-exporter`, `seaweedfs`, `ollama`, `caddy`, and `step-ca` - self-hosted production services in `infra/docker-compose.prod.yml`.

## Configuration

**Environment:**
- Core backend selection uses `MNEME_BACKEND`, `MNEME_STORE`, and `MNEMOSYNE_POSTGRES_DSN` in `src/mnemosyne/mcp_server.py` and `src/mnemosyne/cli.py`.
- Retrieval providers use `MNEMOSYNE_EMBEDDING_PROVIDER`, `MNEMOSYNE_EMBEDDING_URL`, `MNEMOSYNE_RERANKER_PROVIDER`, `MNEMOSYNE_RERANKER_URL`, `MNEMOSYNE_LEXICAL_COMMAND`, and `MNEMOSYNE_GRAPH_COMMAND` in `src/mnemosyne/cli.py`.
- MCP hosted auth/session/TLS uses `MNEMOSYNE_MCP_*` variables in `src/mnemosyne/mcp_server.py`.
- Object storage uses `MNEMOSYNE_OBJECT_STORE*` and `MNEMOSYNE_S3_*` variables in `src/mnemosyne/cli.py` and `src/mnemosyne/storage.py`.
- Checked-in profile files `infra/profiles/self-hosted.env` and `infra/profiles/cloud.env` exist as non-secret production render profiles; their contents were not read.
- `.gitignore` excludes `.env`, `.env.*`, key/certificate files, credential files, local stores, databases, and production input scratch paths.

**Build:**
- Python package config: `pyproject.toml`.
- Rust package config: `rust/mnemosyne-native/Cargo.toml`, `rust/mnemosyne-native/pyproject.toml`, and `rust/mneme-providers/Cargo.toml`.
- Container builds: `infra/Dockerfile`, `services/embedding/Dockerfile`, `rust/mneme-providers/Dockerfile`, `infra/postgres/Dockerfile`, `infra/keycloak/Dockerfile`, and `infra/c2pa/Dockerfile`.
- Compose stacks: `docker-compose.yml`, `infra/docker-compose.providers.yml`, and `infra/docker-compose.prod.yml`.

## Platform Requirements

**Development:**
- Python >=3.12 and `uv` are enough for the local-first in-memory and SQLite paths in `README.md`.
- Docker with Compose v2 is required for local Postgres and provider stacks in `docker-compose.yml` and `infra/README.md`.
- Rust and maturin are required only for optional native wheel work in `rust/mnemosyne-native/`.

**Production:**
- Deployment target is self-hosted Docker Compose via `infra/docker-compose.prod.yml` and `infra/prod/README.md`.
- Production requires external secret files/Vault bindings outside the repository, a non-loopback hostname, Caddy ingress, step-ca certificates, Postgres, Vault, Keycloak, SeaweedFS/S3-compatible storage, and observability services.
- `.github/workflows/ci.yml` runs pinned GitHub Actions for ruff, unit/drift/G0 checks, Postgres live integration, optional native parity/wheel jobs, and scheduled/manual DST-chaos soak jobs.

---

*Stack analysis: 2026-07-08*
