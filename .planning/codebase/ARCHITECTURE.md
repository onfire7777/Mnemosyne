<!-- refreshed: 2026-07-08 -->
# Architecture

**Analysis Date:** 2026-07-08

## System Overview

```text
┌─────────────────────────────────────────────────────────────┐
│                    Operator / Agent Interfaces               │
├──────────────────────────────┬──────────────────────────────┤
│ `mneme` CLI                  │ `mneme-mcp` MCP server        │
│ `src/mnemosyne/cli.py`       │ `src/mnemosyne/mcp_server.py` │
└───────────────┬──────────────┴───────────────┬──────────────┘
                │                              │
                ▼                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 MemoryTools + Ingestion Facade               │
│ `src/mnemosyne/mcp_tools.py`, `src/mnemosyne/ingestion.py`   │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                  MemoryEngine Contract Layer                 │
│ `src/mnemosyne/engine.py`, `src/mnemosyne/pipeline.py`       │
├──────────────────┬──────────────────┬───────────────────────┤
│ Local backend    │ SQLite backend   │ PostgreSQL backend     │
│ `engine.py`      │ `sqlite_engine.py`│ `postgres_engine.py`   │
└────────┬─────────┴────────┬─────────┴──────────┬────────────┘
         │                  │                     │
         ▼                  ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│ Ledger, projections, retrieval, queues, object storage       │
│ `.mnemosyne/`, per-tenant SQLite files, `sql/schema.sql`      │
└─────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| CLI | Human/operator command surface, backend/provider wiring, runtime checks, evidence operations, production evidence commands | `src/mnemosyne/cli.py` |
| MCP server | JSON-RPC stdio shim, hosted HTTP transport, optional official MCP SDK stdio/StreamableHTTP transport | `src/mnemosyne/mcp_server.py` |
| MCP tools facade | Agent-facing memory operations over the engine, ingestion, runtime state, learning, user model, metrics, and parametric tier | `src/mnemosyne/mcp_tools.py` |
| Engine contract | Structural `MemoryEngine` protocol, local in-memory implementation, fast/deep route heuristic | `src/mnemosyne/engine.py` |
| Shared retrieval pipeline | Engine-agnostic dense/lexical/graph retrieval orchestration, fusion, reranking, calibration, abstention | `src/mnemosyne/pipeline.py` |
| PostgreSQL backend | Production schema adapter with RLS posture, FTS/vector/graph retrieval, pooled connections, durable state compatibility | `src/mnemosyne/postgres_engine.py` |
| SQLite backend | Local per-tenant WAL backend with SQL ledger/projection scans and parity-oriented delegation | `src/mnemosyne/sqlite_engine.py` |
| Typed model layer | Dataclass records for evidence, assertions, relations, preferences, hits, retrieval results, merge reports | `src/mnemosyne/models.py` |
| Ingestion pipeline | Payload size enforcement, provenance verification, privacy/residency classification, evidence append, job enqueueing | `src/mnemosyne/ingestion.py` |
| Consolidation worker | Warm-loop 11-pass consolidation pipeline and mutation rail budgeting | `src/mnemosyne/consolidation.py` |
| Queue layer | In-process, PostgreSQL, and SQLite job queues with shared `queued -> running -> complete/retry/dead` lifecycle | `src/mnemosyne/queue.py` |
| Security and policy | Trust tiers, session verification, capability decisions, access/sensitivity policy, prompt-sink safety | `src/mnemosyne/security.py`, `src/mnemosyne/access_policy.py` |
| Object storage | Local/S3 object records, optional envelope encryption, JSON or command key managers | `src/mnemosyne/storage.py` |
| Rust native kernels | Optional Python extension for byte-parity retrieval kernels | `rust/mnemosyne-native/src/lib.rs` |
| Provider sidecar | Axum HTTP sidecar for `/health`, `/embed`, and `/rerank` provider contracts | `rust/mneme-providers/src/lib.rs` |
| Python embedding service | Optional FastAPI or stdlib HTTP embedding/reranker service | `services/embedding/app.py` |

## Pattern Overview

**Overall:** Local-first memory compiler with port/adapters and interchangeable storage engines.

**Key Characteristics:**
- Use `MemoryEngine` in `src/mnemosyne/engine.py` as the boundary for storage backends; add shared behavior above it, not inside one backend only.
- Keep interface code thin: `src/mnemosyne/cli.py` and `src/mnemosyne/mcp_server.py` build engines, queues, stores, providers, and then delegate to tool/engine methods.
- Keep retrieval orchestration centralized in `src/mnemosyne/pipeline.py`; storage engines provide primitive searches and helper methods through `RetrievalPipelineOps`.
- Treat evidence as the source of truth and projections as rebuildable data; model records live in `src/mnemosyne/models.py`.
- Keep local defaults deterministic and optional real providers explicit through adapters in `src/mnemosyne/retrieval.py`, `src/mnemosyne/providers/__init__.py`, and `infra/providers/`.

## Layers

**Interface Layer:**
- Purpose: Expose memory operations to shell users and MCP clients.
- Location: `src/mnemosyne/cli.py`, `src/mnemosyne/mcp_server.py`, `src/mnemosyne/mcp_tools.py`
- Contains: Argument parsing, transport setup, tool schema validation, facade methods, output serialization.
- Depends on: Engine factory helpers, queues, object stores, provider adapters, security/session helpers.
- Used by: Console scripts declared in `pyproject.toml` (`mneme`, `mneme-mcp`), tests in `tests/test_cli_runtime_tools.py`, `tests/test_runtime_surfaces.py`, and MCP clients.

**Engine Core Layer:**
- Purpose: Define and implement the memory runtime contract.
- Location: `src/mnemosyne/engine.py`, `src/mnemosyne/postgres_engine.py`, `src/mnemosyne/sqlite_engine.py`
- Contains: `MemoryEngine`, `LocalMemoryEngine`, `PostgresEngine`, `SqliteEngine`, branch/as-of/retrieve/write surfaces.
- Depends on: Models, policy, retrieval adapters, calibration, access policy, security, text algorithms.
- Used by: CLI/MCP surfaces, ingestion, learning, tests, eval harnesses.

**Pipeline Layer:**
- Purpose: Compose primitive engine operations into write/read/background workflows.
- Location: `src/mnemosyne/ingestion.py`, `src/mnemosyne/pipeline.py`, `src/mnemosyne/consolidation.py`, `src/mnemosyne/jobs.py`, `src/mnemosyne/lifecycle.py`
- Contains: Evidence ingestion, retrieval orchestration, consolidation passes, runtime job handlers, demotion/forgetting logic.
- Depends on: Engine contract, model dataclasses, provider adapters, queue implementations, security/policy modules.
- Used by: Engine retrieve methods, MCP tools, CLI commands, queue workers, eval suites.

**Security, Privacy, Provenance Layer:**
- Purpose: Enforce trust tiers, write capabilities, read sensitivity ceilings, provenance validation, erasure, and network safety.
- Location: `src/mnemosyne/security.py`, `src/mnemosyne/access_policy.py`, `src/mnemosyne/privacy.py`, `src/mnemosyne/provenance.py`, `src/mnemosyne/evidence_redaction.py`, `src/mnemosyne/network_safety.py`
- Contains: `TrustTier`, session/JWKS verification, access-policy checks, privacy classification, signed provenance/C2PA verification, redaction helpers.
- Depends on: Model records and configuration/env values.
- Used by: Ingestion, engine read/write paths, CLI provider checks, MCP auth/session transport.

**Provider and Storage Layer:**
- Purpose: Provide pluggable adapters for embeddings, reranking, lexical/graph retrieval, object bytes, KMS, parametric training, and durable runtime state.
- Location: `src/mnemosyne/retrieval.py`, `src/mnemosyne/storage.py`, `src/mnemosyne/parametric.py`, `src/mnemosyne/runtime_state.py`, `src/mnemosyne/postgres_runtime_state.py`, `src/mnemosyne/providers/__init__.py`
- Contains: Local fallbacks, HTTP providers, shell-free command providers, object stores, parametric artifact store, file/Postgres runtime state.
- Depends on: Standard library HTTP/subprocess/JSON primitives, optional external providers, engine/policy records.
- Used by: CLI/MCP load helpers and production/provider validation paths.

**Infrastructure and Evaluation Layer:**
- Purpose: Provide production composition, validation scripts, evidence capture, benchmark/eval harnesses, and operator runbooks.
- Location: `infra/`, `sql/schema.sql`, `eval/`, `services/embedding/`, `rust/`, `docs/`
- Contains: Dockerfiles, compose manifests, provider scripts, Keycloak/Vault/C2PA assets, eval datasets, latency reports, Rust sidecars.
- Depends on: Package entry points and optional extras.
- Used by: Operator workflows, CI/tests, production evidence commands, benchmark scripts.

## Data Flow

### Primary Capture Path

1. Caller invokes `mneme capture` or an MCP `capture`/`ingest` tool (`src/mnemosyne/cli.py:458`, `src/mnemosyne/mcp_tools.py:291`).
2. Interface code builds a backend through `load_engine()` or `MnemosyneMcpServer._build_tools()` (`src/mnemosyne/cli.py:458`, `src/mnemosyne/mcp_server.py:35`).
3. `IngestionPipeline.ingest()` enforces byte limits, provenance, privacy, residency, and trust metadata (`src/mnemosyne/ingestion.py:113`).
4. The selected engine appends immutable evidence (`src/mnemosyne/engine.py:243`, `src/mnemosyne/postgres_engine.py:244`, `src/mnemosyne/sqlite_engine.py`).
5. Optional runtime jobs enter `InProcessQueue`, `PostgresQueue`, or `SqliteQueue` (`src/mnemosyne/queue.py:49`, `src/mnemosyne/queue.py:128`, `src/mnemosyne/queue.py:383`).

### Primary Retrieval Path

1. Caller invokes search/retrieve through CLI/MCP (`src/mnemosyne/cli.py`, `src/mnemosyne/mcp_tools.py`).
2. `route()` decides fast vs deep from the query/context without an LLM call (`src/mnemosyne/engine.py:159`).
3. Engine `retrieve()` delegates to `run_retrieval_pipeline()` (`src/mnemosyne/pipeline.py:130`).
4. The pipeline calls engine primitives for dense vector, lexical, and graph/PPR channels, then fuses with RRF/MMR and reranks (`src/mnemosyne/pipeline.py:130`).
5. Access policy, calibration, grounding, and abstention shape the final `RetrievalResult` (`src/mnemosyne/models.py:205`).

### MCP Transport Path

1. `mneme-mcp` starts `MnemosyneMcpServer.main()` (`src/mnemosyne/mcp_server.py:1383`).
2. The server chooses stdio shim, official SDK stdio, SDK StreamableHTTP, or hosted HTTP (`src/mnemosyne/mcp_server.py:643`, `src/mnemosyne/mcp_server.py:714`, `src/mnemosyne/mcp_server.py:791`).
3. Tool names/schemas are loaded from `TOOL_SPEC` and executed through `MemoryTools` (`src/mnemosyne/mcp_tools.py:291`).
4. Backend, queue, object store, runtime state, and parametric tier are constructed once unless stateless mode rebuilds per call (`src/mnemosyne/mcp_server.py:35`).

### Provider / Sidecar Path

1. CLI/MCP load helpers choose deterministic local providers unless HTTP or command providers are explicitly configured (`src/mnemosyne/cli.py:366`, `src/mnemosyne/retrieval.py`).
2. Python sidecar exposes `/health`, `/embed`, and `/rerank` with FastAPI when installed and stdlib HTTP otherwise (`services/embedding/app.py:383`, `services/embedding/app.py:460`).
3. Rust sidecar exposes the same provider routes via Axum (`rust/mneme-providers/src/lib.rs:83`).
4. Rust native extension exports strict byte-parity kernels for hashing, lexical, dense scan, MMR, and PPR (`rust/mnemosyne-native/src/lib.rs`).

**State Management:**
- Local state uses `LocalMemoryEngine` and file-backed runtime state under `.mnemosyne/` when configured (`src/mnemosyne/engine.py:437`, `src/mnemosyne/runtime_state.py`).
- SQLite state uses a per-tenant WAL database root supplied through `--store` (`src/mnemosyne/sqlite_engine.py`).
- PostgreSQL state uses `sql/schema.sql`, tenant-scoped RLS posture, `PostgresRuntimeState`, and `PostgresQueue` (`src/mnemosyne/postgres_engine.py`, `src/mnemosyne/postgres_runtime_state.py`, `src/mnemosyne/queue.py:128`).
- Package imports are lazy through PEP 562 exports in `src/mnemosyne/__init__.py` to protect CLI/MCP cold start.

## Key Abstractions

**MemoryEngine:**
- Purpose: Runtime storage/search contract for all backends.
- Examples: `src/mnemosyne/engine.py`, `src/mnemosyne/postgres_engine.py`, `src/mnemosyne/sqlite_engine.py`
- Pattern: Structural `typing.Protocol`; implementations must satisfy shared contract and parity tests.

**Evidence / Assertion / Relation / Preference / Hit / RetrievalResult:**
- Purpose: Stable dataclass records that cross backend, CLI, MCP, eval, and test boundaries.
- Examples: `src/mnemosyne/models.py`
- Pattern: Slotted dataclasses with `to_dict()` / `from_dict()` helpers and UTC JSON timestamp normalization.

**RetrievalPipelineOps:**
- Purpose: Minimal engine primitive surface required by shared retrieval orchestration.
- Examples: `src/mnemosyne/pipeline.py`
- Pattern: Protocol over vector, lexical, graph, fusion, budget, calibration, and telemetry helpers.

**RetrievalAdapters:**
- Purpose: Swap embedding, reranker, lexical, and graph providers while keeping engine code stable.
- Examples: `src/mnemosyne/retrieval.py`, `src/mnemosyne/cli.py:366`
- Pattern: Local deterministic fallback by default; HTTP and shell-free command adapters opt in through configuration.

**QueueJob / Queue Backends:**
- Purpose: Durable-shape background work lifecycle shared across local, SQLite, and PostgreSQL modes.
- Examples: `src/mnemosyne/queue.py`
- Pattern: Same enqueue/lease/complete/fail semantics across in-memory, SQL, and SQLite implementations.

**MemoryTools:**
- Purpose: Agent-facing facade that groups engine, ingestion, prefetch, user model, learning, security, parametric, and metrics services.
- Examples: `src/mnemosyne/mcp_tools.py:291`
- Pattern: Thin facade over engine/pipeline modules; do not add storage-specific behavior here.

## Entry Points

**CLI:**
- Location: `src/mnemosyne/cli.py`
- Triggers: Console script `mneme = "mnemosyne.cli:main"` in `pyproject.toml`.
- Responsibilities: Parse commands, build engines/providers/queues/stores, run operator workflows, print JSON/structured reports.

**MCP Server:**
- Location: `src/mnemosyne/mcp_server.py`
- Triggers: Console script `mneme-mcp = "mnemosyne.mcp_server:main"` in `pyproject.toml`.
- Responsibilities: Serve stdio/HTTP/SDK MCP transports, validate sessions and tool arguments, dispatch to `MemoryTools`.

**Embedding Service:**
- Location: `services/embedding/app.py`
- Triggers: Service process or container entry point.
- Responsibilities: Expose `/health`, `/embed`, `/rerank` provider endpoints with FastAPI/uvicorn or stdlib HTTP fallback.

**Rust Provider Sidecar:**
- Location: `rust/mneme-providers/src/main.rs`, `rust/mneme-providers/src/lib.rs`
- Triggers: Rust binary/container provider process.
- Responsibilities: Serve Axum provider endpoints for deterministic or model-backed embedding/reranking.

**Evaluation and Benchmarks:**
- Location: `eval/`, `tests/benchmarks/`
- Triggers: `python`/`pytest`/`uv run` commands and CLI evidence workflows.
- Responsibilities: SLO, calibration, replay, latency, parity, and benchmark reporting.

## Architectural Constraints

- **Threading:** Python runtime is mostly synchronous; `src/mnemosyne/pipeline.py` can opt into a 3-worker channel thread pool with `MNEMOSYNE_PARALLEL_CHANNELS`, and HTTP/MCP servers use stdlib/FastAPI/uvicorn server concurrency as configured.
- **Global state:** Package export cache in `src/mnemosyne/__init__.py`; module-level constants configure consolidation, queue, retrieval, policy, and backend names across `src/mnemosyne/*.py`.
- **Backend parity:** Put cross-backend behavior in shared modules (`src/mnemosyne/pipeline.py`, `src/mnemosyne/algorithms.py`, `src/mnemosyne/models.py`) and keep backend-specific differences behind `MemoryEngine`/`RetrievalPipelineOps`.
- **Secrets:** Do not read or embed `.env`, `*.env`, key, credential, or secret file contents in docs or code generation; repo contains env-profile filenames under `infra/profiles/` that should be referenced by path only.
- **Circular imports:** Interface modules use lazy imports heavily (`src/mnemosyne/cli.py`, `src/mnemosyne/mcp_server.py`, `src/mnemosyne/__init__.py`); preserve lazy import boundaries for cold start and optional extras.
- **External services:** Postgres, Keycloak, Vault, C2PA, S3/SeaweedFS, HTTP providers, and Rust sidecars are optional infrastructure layers; local deterministic behavior remains the default path.

## Anti-Patterns

### Backend-Only Behavior Drift

**What happens:** Adding retrieval, privacy, calibration, or evidence semantics to `src/mnemosyne/postgres_engine.py` or `src/mnemosyne/sqlite_engine.py` without a matching shared contract path.
**Why it's wrong:** The repo relies on local/Postgres/SQLite substitutability and parity tests.
**Do this instead:** Add shared behavior in `src/mnemosyne/pipeline.py`, `src/mnemosyne/algorithms.py`, `src/mnemosyne/access_policy.py`, or `src/mnemosyne/models.py`, then expose only storage primitives in the backend.

### Interface-Layer Storage Logic

**What happens:** Implementing memory semantics in `src/mnemosyne/cli.py`, `src/mnemosyne/mcp_server.py`, or `src/mnemosyne/mcp_tools.py`.
**Why it's wrong:** CLI and MCP must remain alternate surfaces over the same engine and tool contract.
**Do this instead:** Wire options in `load_engine()` / `_build_tools()` and put behavior in engine, pipeline, ingestion, queue, or provider modules.

### Provider as Implicit Dependency

**What happens:** Requiring network/model providers for default engine behavior.
**Why it's wrong:** The package is local-first with deterministic fallbacks and optional extras.
**Do this instead:** Default to local providers in `src/mnemosyne/retrieval.py`; make HTTP/command providers explicit in `src/mnemosyne/cli.py` and `src/mnemosyne/mcp_server.py`.

## Error Handling

**Strategy:** Fail closed at configuration, trust-boundary, provider, backend, and auth/session edges; return structured reports for operator checks.

**Patterns:**
- CLI configuration errors raise `SystemExit` with concrete messages in `src/mnemosyne/cli.py`.
- Optional dependency gaps raise specific errors such as `PostgresUnavailableError` in `src/mnemosyne/postgres_engine.py` and runtime errors in SDK MCP helpers in `src/mnemosyne/mcp_server.py`.
- MCP tool failures are converted to tool error results in SDK mode and JSON-RPC error responses in shim/HTTP paths (`src/mnemosyne/mcp_server.py`).
- Ingestion and provider adapters validate payload size, JSON shape, provenance, residency, and provider contracts before side effects (`src/mnemosyne/ingestion.py`, `src/mnemosyne/retrieval.py`).
- Queue failures move jobs to `retry` or `dead` through shared queue methods (`src/mnemosyne/queue.py`).

## Cross-Cutting Concerns

**Logging:** Library code mostly returns structured dicts/reports and uses quiet defaults; `src/mnemosyne/postgres_engine.py` declares a module logger for backend diagnostics.
**Validation:** Dataclass constructors, explicit helper validation, SQL constraints in `sql/schema.sql`, CLI parser choices, and tool schemas in `src/mnemosyne/mcp_tools.py`.
**Authentication:** MCP bearer/session/OIDC handling in `src/mnemosyne/mcp_server.py` and `src/mnemosyne/security.py`; Postgres role/RLS posture in `src/mnemosyne/postgres_security.py` and `sql/schema.sql`.
**Privacy:** Access-policy checks, sensitivity ceilings, privacy classification, erasure IDs, and evidence redaction in `src/mnemosyne/access_policy.py`, `src/mnemosyne/privacy.py`, `src/mnemosyne/erasure_ids.py`, and `src/mnemosyne/evidence_redaction.py`.
**Observability:** Metrics/report helpers in `src/mnemosyne/observability.py`, ops metrics in `src/mnemosyne/ops_metrics.py`, production evidence flows in `src/mnemosyne/production_parity.py` and `infra/`.

---

*Architecture analysis: 2026-07-08*
