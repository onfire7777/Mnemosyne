# Codebase Structure

**Analysis Date:** 2026-07-08

## Directory Layout

```text
Mnemosyne/
├── src/mnemosyne/          # Python package: engines, pipelines, security, providers, CLI, MCP
├── tests/                  # Pytest suite for contract, parity, runtime, infra, security, SQLite/Postgres
├── eval/                   # Evaluation harnesses, datasets, calibration, latency and benchmark reports
├── services/embedding/     # Optional Python embedding/reranker HTTP service
├── rust/                   # Rust native Python extension and provider sidecar crates
├── infra/                  # Docker, production profiles, provider scripts, Keycloak, Vault, C2PA, observability
├── sql/                    # PostgreSQL schema
├── docs/                   # Architecture, engine contract, roadmap, blueprint mirror, ADRs
├── config/                 # Drift/config baselines
├── bin/                    # Checked-in utility binaries/scripts
├── production-inputs/      # Ignored local preflight scratch; real production inputs live outside the repo
├── .planning/              # GSD planning, milestone, runbook, and generated codebase-map docs
├── .mnemosyne/             # Ignored local runtime store/object data
├── pyproject.toml          # Python package metadata, entry points, dependency groups, pytest config
├── uv.lock                 # Locked Python dependency graph
├── docker-compose.yml      # Local compose entry point
└── README.md               # User-facing overview and quick start
```

## Directory Purposes

**`src/mnemosyne/`:**
- Purpose: Main installable Python package.
- Contains: Engine contract/backends, model dataclasses, CLI/MCP surfaces, ingestion/retrieval/consolidation pipelines, security/privacy/provenance, queues, storage, learning, user model, observability.
- Key files: `src/mnemosyne/engine.py`, `src/mnemosyne/postgres_engine.py`, `src/mnemosyne/sqlite_engine.py`, `src/mnemosyne/pipeline.py`, `src/mnemosyne/cli.py`, `src/mnemosyne/mcp_server.py`, `src/mnemosyne/mcp_tools.py`.

**`src/mnemosyne/providers/`:**
- Purpose: Provider registry and specialist module configuration for runtime integrations.
- Contains: Python package file `src/mnemosyne/providers/__init__.py`.
- Key files: `src/mnemosyne/providers/__init__.py`.

**`tests/`:**
- Purpose: Primary verification surface.
- Contains: Pytest tests for engine contract, backend parity, CLI/MCP runtime surfaces, infra hardening, security sessions, retrieval, SQLite/Postgres behavior, native parity, provider manifests, production evidence, and completion criteria.
- Key files: `tests/test_shared_engine_contract.py`, `tests/test_engine_contract.py`, `tests/test_runtime_surfaces.py`, `tests/test_cli_runtime_tools.py`, `tests/test_postgres_engine_live.py`, `tests/test_sqlite_engine_core.py`, `tests/test_native_parity.py`.

**`eval/`:**
- Purpose: Evaluation harnesses and benchmark inputs/outputs.
- Contains: G0 suites, calibration runners, latency benches, replay fidelity checks, provider bake-off fixtures, curated datasets, reports.
- Key files: `eval/README.md`, `eval/harness/cli_driver.py`, `eval/harness/suites.py`, `eval/provider_bakeoff/run.py`, `eval/calibration/runner.py`, `eval/benches/run_benches.py`.

**`services/embedding/`:**
- Purpose: Optional embedding/reranker provider service.
- Contains: FastAPI/stdlib service, selftest, Dockerfile, requirements.
- Key files: `services/embedding/app.py`, `services/embedding/selftest.py`, `services/embedding/Dockerfile`, `services/embedding/requirements.txt`.

**`rust/mnemosyne-native/`:**
- Purpose: Optional native Python extension for retrieval kernels.
- Contains: Rust/PyO3 implementations of hashing, tokenize, lexical, dense scan, MMR, and PPR functions.
- Key files: `rust/mnemosyne-native/src/lib.rs`, `rust/mnemosyne-native/src/dense.rs`, `rust/mnemosyne-native/src/lexical.rs`, `rust/mnemosyne-native/Cargo.toml`.

**`rust/mneme-providers/`:**
- Purpose: Rust provider sidecar for embedding/reranker HTTP contracts.
- Contains: Axum app and binary entry point.
- Key files: `rust/mneme-providers/src/lib.rs`, `rust/mneme-providers/src/main.rs`, `rust/mneme-providers/Cargo.toml`.

**`infra/`:**
- Purpose: Production/self-hosted deployment assets and validation scripts.
- Contains: Compose manifests, Dockerfiles, provider scripts, Keycloak realm, Vault policies/providers, Caddy, observability, production templates, setup/capture/validation scripts.
- Key files: `infra/docker-compose.prod.yml`, `infra/docker-compose.providers.yml`, `infra/scripts/setup-all.sh`, `infra/scripts/capture-production-evidence.sh`, `infra/templates/provider-manifest.production.template.json`, `infra/vault/providers.json`.

**`sql/`:**
- Purpose: PostgreSQL schema.
- Contains: `sql/schema.sql`.
- Key files: `sql/schema.sql`.

**`docs/`:**
- Purpose: Human-facing architecture, contracts, roadmap, blueprint mirror, and ADRs.
- Contains: `docs/ARCHITECTURE-OVERVIEW.md`, `docs/ENGINE-CONTRACT.md`, `docs/blueprint/`, `docs/adr/`, `docs/decisions/`.
- Key files: `docs/ARCHITECTURE-OVERVIEW.md`, `docs/ENGINE-CONTRACT.md`, `docs/SELF-HOSTED-PRODUCTION-ARCHITECTURE.md`.

**`.planning/`:**
- Purpose: GSD project planning and generated analysis outputs.
- Contains: Milestones, phases, runbooks, state/roadmap docs, codebase maps under `.planning/codebase/`.
- Key files: `.planning/PROJECT.md`, `.planning/STATE.md`, `.planning/codebase/ARCHITECTURE.md`, `.planning/codebase/STRUCTURE.md`.

## Key File Locations

**Entry Points:**
- `src/mnemosyne/cli.py`: `mneme` console script and operator command implementation.
- `src/mnemosyne/mcp_server.py`: `mneme-mcp` console script and MCP transport implementation.
- `services/embedding/app.py`: Python provider service entry point and `/health`, `/embed`, `/rerank` route definitions.
- `rust/mneme-providers/src/main.rs`: Rust provider sidecar binary entry.
- `eval/benches/run_benches.py`: Benchmark runner entry.

**Configuration:**
- `pyproject.toml`: Python package metadata, optional extras, dev group, console scripts, pytest config.
- `uv.lock`: Locked dependency graph for `uv`.
- `docker-compose.yml`: Local compose root.
- `infra/docker-compose.prod.yml`: Production compose topology.
- `infra/docker-compose.providers.yml`: Provider-side compose topology.
- `config/drift-baseline.toml`: Drift baseline configuration.
- `sql/schema.sql`: PostgreSQL DDL and RLS/schema contract.

**Core Logic:**
- `src/mnemosyne/models.py`: Typed data records crossing all layers.
- `src/mnemosyne/engine.py`: `MemoryEngine`, `LocalMemoryEngine`, routing.
- `src/mnemosyne/postgres_engine.py`: PostgreSQL backend.
- `src/mnemosyne/sqlite_engine.py`: SQLite backend.
- `src/mnemosyne/pipeline.py`: Shared retrieval path.
- `src/mnemosyne/ingestion.py`: Evidence ingestion path.
- `src/mnemosyne/consolidation.py`: Warm-loop consolidation.
- `src/mnemosyne/retrieval.py`: Retrieval providers/adapters and local fallbacks.
- `src/mnemosyne/security.py`: Trust/session/capability security.
- `src/mnemosyne/access_policy.py`: Read filtering and sensitivity policy helpers.
- `src/mnemosyne/storage.py`: Object storage and key manager abstractions.

**Testing:**
- `tests/test_shared_engine_contract.py`: Shared contract and runtime surface assertions.
- `tests/test_engine_contract.py`: Local engine contract tests.
- `tests/test_postgres_engine_live.py`: Live PostgreSQL backend tests.
- `tests/test_sqlite_engine_core.py`: SQLite core tests.
- `tests/test_runtime_surfaces.py`: MCP/provider/runtime surface tests.
- `tests/test_cli_runtime_tools.py`: CLI/runtime commands and checks.
- `eval/tests/`: Evaluation harness integration tests.

## Naming Conventions

**Files:**
- Python modules use lowercase `snake_case.py`: `src/mnemosyne/postgres_engine.py`, `src/mnemosyne/runtime_state.py`.
- Test files use `test_*.py`: `tests/test_shared_engine_contract.py`.
- Rust modules use lowercase names under crate `src/`: `rust/mnemosyne-native/src/dense.rs`.
- Markdown docs use descriptive uppercase or kebab/capitalized names depending on folder convention: `docs/ENGINE-CONTRACT.md`, `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md`.
- Shell scripts use lower-kebab verbs: `infra/scripts/capture-production-evidence.sh`.

**Directories:**
- Python package code lives under `src/mnemosyne/`.
- Infrastructure domains are grouped by service under `infra/<service>/`: `infra/vault/`, `infra/keycloak/`, `infra/c2pa/`, `infra/observability/`.
- Eval subdomains are grouped by purpose under `eval/<suite>/`: `eval/calibration/`, `eval/latency/`, `eval/replay_fidelity/`.
- Rust crates live under `rust/<crate-name>/`: `rust/mnemosyne-native/`, `rust/mneme-providers/`.

## Where to Add New Code

**New CLI Command:**
- Primary code: `src/mnemosyne/cli.py`
- Shared behavior: add to the relevant module under `src/mnemosyne/` instead of embedding logic in the command.
- Tests: `tests/test_cli_runtime_tools.py` or a focused `tests/test_<feature>.py`.

**New MCP Tool:**
- Tool facade and schema: `src/mnemosyne/mcp_tools.py`
- Transport/session behavior: `src/mnemosyne/mcp_server.py`
- Tests: `tests/test_runtime_surfaces.py`, `tests/test_parity_mcp.py`, or focused MCP tests.

**New Engine Behavior:**
- Contract/shared semantics: `src/mnemosyne/engine.py`, `src/mnemosyne/pipeline.py`, `src/mnemosyne/models.py`, or helper modules such as `src/mnemosyne/access_policy.py`.
- Backend storage primitives: `src/mnemosyne/postgres_engine.py` and/or `src/mnemosyne/sqlite_engine.py`.
- Tests: `tests/test_shared_engine_contract.py` plus backend-specific tests such as `tests/test_postgres_engine_live.py` and `tests/test_sqlite_*.py`.

**New Retrieval Provider:**
- Adapter implementation: `src/mnemosyne/retrieval.py` or `src/mnemosyne/providers/__init__.py`.
- CLI wiring: `src/mnemosyne/cli.py`.
- MCP wiring: `src/mnemosyne/mcp_server.py`.
- External/provider assets: `infra/providers/`, `services/embedding/`, or `rust/mneme-providers/` depending on runtime.
- Tests: `tests/test_provider_*.py`, `tests/test_runtime_surfaces.py`, or `tests/test_postgres_engine_live.py` for provider-backed retrieval.

**New Background Job:**
- Job model/handlers: `src/mnemosyne/jobs.py`.
- Queue integration: `src/mnemosyne/queue.py`.
- CLI/MCP command surface: `src/mnemosyne/cli.py` and/or `src/mnemosyne/mcp_tools.py`.
- Tests: `tests/test_runtime_surfaces.py`, `tests/test_cli_runtime_tools.py`, or a focused job test.

**New Security/Privacy Rule:**
- Trust/session/capability logic: `src/mnemosyne/security.py`.
- Read filtering/sensitivity: `src/mnemosyne/access_policy.py`.
- Privacy/erasure/redaction: `src/mnemosyne/privacy.py`, `src/mnemosyne/erasure_ids.py`, `src/mnemosyne/evidence_redaction.py`.
- Tests: `tests/test_access_policy_enforcement.py`, `tests/test_security_sessions.py`, `tests/test_evidence_redaction.py`, `tests/test_erasure_ids.py`.

**New Infrastructure Profile or Production Check:**
- Compose/profile assets: `infra/`, `infra/profiles/`, `infra/templates/`.
- Validation scripts: `infra/validate/` or `infra/scripts/`.
- Production evidence code: `src/mnemosyne/production_parity.py`, `src/mnemosyne/ops_metrics.py`, or CLI command code in `src/mnemosyne/cli.py`.
- Tests: `tests/test_prod_compose_policy.py`, `tests/test_production_*`, `tests/test_infra_*`.

**New Eval or Benchmark:**
- Harness code: `eval/harness/`.
- Provider bake-off evidence wrapper: `eval/provider_bakeoff/run.py`.
- Benchmark script: `eval/benches/`.
- Dataset: `eval/datasets/`.
- Tests: `eval/tests/` or `tests/benchmarks/`.

**Utilities:**
- Shared Python helpers: a focused module under `src/mnemosyne/` matching the domain.
- Test-only helpers: local helpers inside the relevant `tests/test_*.py` unless reused broadly.
- Shell/operator helpers: `infra/scripts/` when tied to deployment/evidence operations.

## Special Directories

**`.mnemosyne/`:**
- Purpose: Local runtime store and object data.
- Generated: Yes.
- Tracked: No; ignored local runtime data.

**`.planning/`:**
- Purpose: GSD workflow state, milestone/phase docs, runbooks, and codebase maps.
- Generated: Mixed; many docs are workflow artifacts.
- Committed: Yes.

**`eval/reports/`, `eval/latency/reports/`, `eval/latency_warm/reports/`:**
- Purpose: Evaluation and benchmark outputs.
- Generated: Yes.
- Committed: Current report artifacts are present; avoid using generated reports as source code locations.

**`rust/*/target/`:**
- Purpose: Rust build output.
- Generated: Yes.
- Committed: No; ignore for code mapping and edits.

**`src/mnemosyne_memory.egg-info/`:**
- Purpose: Python package metadata.
- Generated: Yes.
- Tracked: No; ignored generated package metadata.

**`infra/profiles/`:**
- Purpose: Environment profile templates/files for infrastructure.
- Generated: No.
- Committed: Yes.
- Note: Contains `*.env`-named files; reference paths only and do not read or quote contents.

---

*Structure analysis: 2026-07-08*
