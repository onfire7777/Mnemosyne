# Mnemosyne

**A local-first memory compiler for AI agents.** Content-addressed evidence ledger, rebuildable typed projections, bitemporal beliefs, hybrid retrieval, calibrated abstention, and hard invariant rails — runs in memory, on per-tenant SQLite, or on PostgreSQL, and speaks the Model Context Protocol.

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![License](https://img.shields.io/badge/license-Apache--2.0-green)
![Status](https://img.shields.io/badge/SLOs-6%2F6%20proven-success)
![Completion](https://img.shields.io/badge/strict%20parity-Tier--B%20evidence%20verified-success)
![Backend](https://img.shields.io/badge/backends-local%20%7C%20sqlite%20%7C%20postgres-informational)
![Protocol](https://img.shields.io/badge/MCP-stdio%20%7C%20HTTP%20%7C%20SDK-blueviolet)

Mnemosyne (`mnemosyne-memory`, v0.1.0) implements the **Mnemosyne v2 build blueprint**: agent memory as a *compiler*, not a vector dump. Every write lands first in an append-only, content-addressed **evidence** ledger; typed **projections** (assertions, entities, relations, preferences, procedures, lessons) are derived from that ledger and can be rebuilt deterministically. Beliefs are **bitemporal** (valid-time + transaction-time), retrieval is **hybrid** (lexical + dense + graph, reranked), confidence is **conformally calibrated** so the system *abstains* rather than guess, and a warm-loop **consolidation** pipeline promotes new beliefs only through a protected regression gate guarded by seven non-negotiable invariant rails.

---

## Source Blueprint

The implementation target is the Mnemosyne v2 blueprint. The repo keeps a
self-contained documentation mirror under [`docs/blueprint/`](docs/blueprint/)
so GitHub, CI, and future agents can audit implementation claims without
depending on a local desktop path. That in-repo mirror is the authoritative
source for this repository and depends on no external local path.

---

## Why Mnemosyne

- **Evidence is immutable; projections are rebuildable.** Beliefs are *compiled* from content-addressed evidence, so retraction, erasure, and re-derivation are first-class — not bolt-ons.
- **Bitemporal by construction.** Supersession, contradiction handling, and `as-of` time travel are native; you can ask what the agent believed *at any point in the past*.
- **Hybrid retrieval, not just cosine.** Postgres FTS + pgvector (HNSW, 1024-dim) + recursive graph/PPR, fused and reranked — with shell-free command adapters to swap in ParadeDB/BM25 or Apache AGE without touching engine code.
- **Calibrated abstention.** Conformal calibration drives a measured **ECE of 0.0063** (target ≤0.05). Mnemosyne says "I don't know" instead of hallucinating.
- **Hard invariant rails.** Seven §31 rails (bounded supersession, corroborated deletion, bounded pruning, monotonic trust, external-only reward, retrieved-text-is-data, bounded cadence) are enforced and regression-tested.
- **Capability-mediated, fail-closed writes.** Trust tiers, sensitivity ceilings, signed CLI/MCP sessions, OIDC→role mapping, and prompt-injection sanitization on every retrieved span.
- **Branchable memory.** Fork a tenant's memory, experiment, then `merge` or `discard` — like git for beliefs.
- **Three backends, proven equivalent.** A zero-dependency in-memory engine, a PostgreSQL-backed engine, and a per-tenant SQLite engine pass the shared contract + parity test suite; the Tier-B operator production evidence is now captured and offline-verified (2026-07-07 — 29/29 production deployment-soak green, `release-audit` `ok:true`, `production-evidence-verify` `ok:true`; see `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md`).
- **Local-first.** Single core dependency (`cryptography`). No network, no Postgres, and no model server required to start.

---

## Architecture at a glance

```mermaid
flowchart TD
    subgraph Clients
      CLI["mneme CLI<br/>(91 subcommands)"]
      MCP["mneme-mcp<br/>(48 MCP tools)"]
    end
    CLI --> SEC
    MCP --> SEC
    SEC["Security gate<br/>trust tiers · capabilities · sessions · sanitize"] --> ING["Ingestion<br/>content-addressed · signed provenance · media extract"]
    ING --> EV[("Evidence ledger<br/>append-only · CID-keyed")]
    EV --> CONS["Consolidation worker<br/>11-role ordered pipeline → promotion gate"]
    CONS --> PROJ[("Typed projections<br/>assertions · entities · relations<br/>preferences · procedures · lessons")]
    Q["Job queue<br/>queued→running→{complete|retry|dead}"] -.drives.-> CONS
    PROJ --> RET["Hybrid retrieval<br/>FTS + pgvector + graph/PPR → rerank → calibrate"]
    EV --> RET
    RET --> ANS["Answer + confidence<br/>or calibrated abstention"]
    ENGINE{{"MemoryEngine contract"}} -.backs.-> EV
    ENGINE -.implemented by.-> LOCAL["LocalMemoryEngine<br/>in-memory"]
    ENGINE -.implemented by.-> PG["PostgresEngine<br/>RLS · HNSW · recursive PPR · as-of"]
    ENGINE -.implemented by.-> SQLITE["SqliteEngine<br/>per-tenant WAL file · FTS5 · parity oracle"]
```

---

## Quick Start

```bash
# 1. Environment
python3 -m pip install --user pip==26.1.2 uv==0.11.16

# 2. Sync the locked editable environment. Extras: mcp = MCP server,
# postgres = PG backend.
uv sync --locked --extra mcp --group dev
# uv sync --locked --extra mcp --extra postgres --group dev

# 3. Run the local test suite (no Postgres DSN → live-DB tests skip)
uv run --locked python -m pytest

# 4. Capture a memory and search it (in-memory backend, no services needed)
uv run --locked mneme capture --tenant tenant-a --user user-a --source-type chat \
  --content "The preferred database is Postgres." --trust-tier 0
uv run --locked mneme search --tenant tenant-a --query "preferred database"
```

After `uv sync`, the two console-script entry points are available through
`uv run`:

| Command    | Entry point                  | Purpose                |
| ---------- | ---------------------------- | ---------------------- |
| `mneme`    | `mnemosyne.cli:main`         | Memory CLI (91 subcommands) |
| `mneme-mcp`| `mnemosyne.mcp_server:main`  | MCP server (48 tools)  |

> The module form `uv run --locked python -m mnemosyne.cli …` is equivalent to `uv run --locked mneme …`.

### PostgreSQL backend

Requires the `postgres` extra (`uv sync --locked --extra mcp --extra postgres --group dev`). The Postgres engine adds tenant **row-level security**, SQL **FTS**, **pgvector** assertion/evidence search, recursive **graph/PPR**, `as-of` time travel, and durable queue leasing.

```bash
docker compose up -d postgres
export MNEMOSYNE_POSTGRES_DSN=postgresql://mnemosyne:mnemosyne-local-dev@127.0.0.1:54329/mnemosyne

uv run --locked mneme --backend postgres search --tenant tenant-a --query "preferred database"

# Durable queue + bounded consolidation worker
mneme --backend postgres --queue-backend postgres \
  --postgres-dsn "$MNEMOSYNE_POSTGRES_DSN" --queue-tenant tenant-a \
  worker-run --max-cycles 20 --idle-exit-after 2 --fail-on-dead
```

> `--trust-tier 0` means **most trusted** (direct user / operator). Trust tiers are a monotonic 0–5 ladder with **0 = most trusted** and **5 = least trusted**; the default for new agent writes is `3` (`NORMAL`) — see [Core concepts](#core-concepts).

### SQLite backend

The SQLite backend is the local-first third engine: one WAL-backed database file
per tenant, SQL-backed ledger/projection scans, durable branch/merge/discard
copies, queue leases, and the shared retrieval pipeline with SQL predicate
pushdown. It is a development/local backend only; production profiles remain
Postgres-only.

```bash
uv run --locked mneme --backend sqlite --store .mnemosyne/sqlite search \
  --tenant tenant-a --query "preferred database"
```

### MCP server

```bash
# Default: deterministic stdio JSON-RPC shim (no SDK dependency)
mneme-mcp --store .mnemosyne/mcp-store.json

# Official Python MCP SDK over stdio, or SDK StreamableHTTP at /mcp (+ /healthz)
mneme-mcp --store .mnemosyne/mcp-store.json --sdk
mneme-mcp --store .mnemosyne/mcp-store.json --sdk-streamable-http --http-host 127.0.0.1 --http-port 8765

# Hosted HTTP JSON-RPC at /mcp (+ /healthz, + POST /session/exchange), TLS + bearer + signed session
mneme-mcp --http --http-host 127.0.0.1 --http-port 8765 \
  --auth-token "$MNEMOSYNE_MCP_TOKEN" --require-session
```

---

## Core concepts

| Concept | What it is |
| --- | --- |
| **Evidence** | Append-only, content-addressed (`content_cid` = SHA-256 over canonical JSON) record of everything ingested. Immutable; the single source of truth. |
| **Assertion / projection** | Typed beliefs (`subject–predicate–object`) *derived* from evidence and rebuildable from it. Projections also cover entities, relations, preferences, procedures, and lessons. |
| **Bitemporal** | Every belief carries valid-time (`valid_from`/`valid_to`) and transaction-time, enabling supersession and `as-of` queries. |
| **Hybrid retrieval** | Lexical (FTS/BM25) + dense (pgvector HNSW, 1024-dim in production; a BLAKE2b hashing embedder, dims=256, is the offline fallback) + graph (recursive PPR / Apache AGE), fused and reranked. |
| **Calibrated abstention** | Conformal calibration per tenant/memory-type yields a confidence the system can *abstain* on rather than answer (measured ECE 0.0063). |
| **Trust tiers** | `TrustTier` (IntEnum), a monotonic **0–5 ladder, lower = more trusted**: `0` = direct-user / user-authored / operator, `1` verified, `2` authenticated, `3` normal (default), `4` low, `5` untrusted-external. A write may never raise its own trust (§31 Rail 4); belief and branch writes require ≥ `3` (`NORMAL`). |
| **Sensitivity** | Per-row `SMALLINT` (default `0`); the read path enforces role ceilings first (`reader` S1, `agent` S2, `consolidator` S3, `operator` raw S2+ only with break-glass), then applies `policy.max_sensitivity` / request ceilings as further narrowing. |
| **Fidelity tiers** | Lifecycle demotion order: `VERBATIM` → `EXTRACTIVE_SUMMARY` → `ABSTRACTIVE_GIST` → `STATISTICAL_TRACE`. Demotion is gated by a gist-risk abstention hook. |
| **Consolidation** | Warm-loop worker that runs an ordered 11-role pass pipeline through the promotion gate (see below). |
| **Promotion gate** | Protected regression cases must pass before any candidate belief is promoted; failures roll back on a branch. |
| **Branchable memory** | Fork (`branch`), experiment, then `merge` or `discard` — bitemporal, tenant-isolated. |

### Roles (OIDC → Mnemosyne)

`session-exchange` validates an external OIDC/JWT token against a configured JWKS and mints a bounded signed session. An authz policy maps verified IdP claims to exactly one of the four write roles; unknown roles (e.g. `writer`) are rejected and the verifier never falls back to raw IdP claims.

| Role | Capability |
| --- | --- |
| `reader` | Read-only retrieval within its sensitivity ceiling. |
| `agent` | Capture + read; standard agent write authority. |
| `consolidator` | Run consolidation / promotion-gate writes. |
| `operator` | Operator-grade authority (e.g. parametric trainer, hard-delete corroboration). |

### Consolidation pipeline (`DEFAULT_CONSOLIDATION_PASSES`)

Eleven roles run **in this order**, bounded by the mutation-rail budget and the §31 cadence rail:

`replayer` → `extractor` → `resolver` → `belief_reviser` → `skill_inducer` → `lesson_distiller` → `summarizer` → `forgetter` → `embedder` → `promotion_gate` → `user_model_updater`

`extractor` and `resolver` run **once** over the prioritized evidence set to produce candidates; `belief_reviser` then gates **each candidate individually** through `run_job()` and the promotion gate. Default role providers: `replayer` = deterministic priority replay, `belief_reviser` = promotion gate, `forgetter` = fidelity lifecycle policy, `embedder` = deterministic hashing embedding, `promotion_gate` = protected regression gate, `user_model_updater` = latent user-model updater. The `extractor`, `resolver`, `summarizer`, `lesson_distiller`, and `skill_inducer` roles use pluggable strategy providers (deterministic by default, or shell-free command/HTTP adapters).

> Tenant-scoped one-shot: `mneme --queue-tenant tenant-a consolidate-once` (the `consolidate-once` subcommand takes no arguments; pass the tenant via the global `--queue-tenant`).

### Invariant rails (§31)

All seven are enforced and regression-tested:

| Rail | Invariant |
| --- | --- |
| R1 | `max_supersession_rate` ≤ 0.05 per pass |
| R2 | ≥ 2 corroborations required to delete (`min_corroboration_for_delete`) |
| R3 | `max_prune_fraction_per_pass` ≤ 0.02 |
| R4 | Monotonic trust tiers (a write may not raise its own trust) |
| R5 | Reward is external-only |
| R6 | Retrieved text is **data, not instructions** (`security.sanitize_retrieved_text`) |
| R7 | Consolidation cadence bounded to `[5 steps, 24h]` |

### Background job kinds

The runtime queue moves jobs through a non-linear lifecycle — `queued → running → {complete | retry | dead}`, where `retry` re-enters the queue until `max_attempts` is reached (then `dead`). Seven job kinds run on it:

`consolidate_evidence` · `calibrate` · `lifecycle_sweep` · `eval_suite` · `observability_snapshot` · `projection_recompute` · `media_extract`

### Providers (shell-free command adapters)

All command adapters are shell-free: JSON on stdin, JSON on stdout, **no secret-bearing argv**. Core provider boundaries keep deterministic local defaults so nothing external is required to start; model-backed providers are explicit configuration choices, not silent runtime fallbacks.

| Boundary | Default / fallback | Pluggable adapter |
| --- | --- | --- |
| Embedding | `HashingEmbeddingProvider` (BLAKE2b, dims=256) | `HttpEmbeddingProvider`, `CommandMediaEmbeddingProvider` |
| Reranker | `LocalSimilarityReranker` | `HttpReranker` |
| Lexical | native Postgres FTS | `CommandLexicalRetriever` (e.g. ParadeDB/BM25) |
| Graph | native recursive PPR | `CommandGraphRetriever` (e.g. Apache AGE) |
| Object key / KMS | local AES-GCM keystore | `CommandKeyManager` → Vault transit |
| Provenance | `SignedProvenanceVerifier` | `C2paToolVerifier` (C2PA) |

`rust/mneme-providers/` is the local provider sidecar for the compact
`/embed`, `/rerank`, and `/health` HTTP contracts. Consolidation proposal roles
can use shell-free command adapters with prompt boundaries, disclosure-axis
gates, replayable low-trust `provider-proposal` records, and deterministic
fallbacks when explicitly configured.

### MCP transports

| Transport | Flag | Endpoint(s) | Notes |
| --- | --- | --- | --- |
| Deterministic stdio JSON-RPC shim | *(default)* | stdio | No SDK dependency |
| Official SDK stdio | `--sdk` | stdio | Official Python MCP SDK |
| Official SDK StreamableHTTP | `--sdk-streamable-http` | `/mcp` + `/healthz` | Stateless unless `--sdk-streamable-stateful` |
| Hosted HTTP JSON-RPC | `--http` | `/mcp` + `/healthz` + `POST /session/exchange` | Reuses stdio's tool schema + enforcement |
| Legacy SSE | *(validated via `mcp-sse-soak`)* | SSE stream + `endpoint` event | Legacy compatibility |

Auth: static bearer (`Authorization` header / `--auth-token` / `MNEMOSYNE_MCP_TOKEN`) and/or a signed Mnemosyne session (`X-Mnemosyne-Session-Token`). `--require-session` enforces signed sessions; TLS via `--tls-cert-file`/`--tls-key-file`, with optional mTLS via `--tls-client-ca-file --tls-require-client-cert`.

---

## Documentation

Full reference lives in the [project wiki](https://github.com/onfire7777/Mnemosyne/wiki):

- [Architecture Overview](https://github.com/onfire7777/Mnemosyne/wiki/Architecture-Overview) — component layers, write/read flows, deployment topology
- [Getting Started](https://github.com/onfire7777/Mnemosyne/wiki/Getting-Started) — install, first capture, Postgres setup
- [CLI Reference](https://github.com/onfire7777/Mnemosyne/wiki/CLI-Reference) — all 91 subcommands incl. the operations/preflight suite
- [MCP Server and Tools](https://github.com/onfire7777/Mnemosyne/wiki/MCP-Server-and-Tools) — transports, auth, all 48 tools
- [Data Model](https://github.com/onfire7777/Mnemosyne/wiki/Data-Model) — the 24-table schema, RLS, and bitemporal design
- [Security, Privacy and Provenance](https://github.com/onfire7777/Mnemosyne/wiki/Security-Privacy-and-Provenance) — trust tiers, capabilities, residency, C2PA
- [Operations and Production Preflight](https://github.com/onfire7777/Mnemosyne/wiki/Operations-and-Production-Preflight) — `provider-check`, `deployment-soak`, `release-audit`, the `*-ops-check` family

### MCP tools (illustrative)

`mcp_tools.py` exposes **48** tools. A representative slice: `capture`, `ingest`, `assert_fact`, `search`, `deep_search`, `get`, `explain`, `correct`, `supersede`, `forget`, `export`, `branch` / `merge` / `discard`, `graph_neighbors` / `graph_as_of`, `trajectory_record`, `lesson_induce` / `procedure_promote`, `outcome_evaluate`, `parametric_propose`, and the `profile_*` user-model tools.

### Data model (24 tables)

`sql/schema.sql` defines the canonical Postgres schema (extensions `pgcrypto` + `vector`). Vectors are `VECTOR(1024)` with HNSW indexes (`vector_cosine_ops`) on `evidence.embedding` and `assertions.embedding`; every tenant-scoped table enforces RLS via `mnemosyne_current_tenant()`.

`tenants` · `branches` · `evidence` · `assertions` · `justifications` · `entities` · `entity_aliases` · `relations` · `graph_ppr_cache` · `contradictions` · `procedures` · `lessons` · `preferences` · `user_latent` · `trajectories` · `self_model` · `eval_cases` · `resources` · `merges` · `deletion_log` · `conformal_calibration` · `audit_log` · `runtime_jobs` · `runtime_state`

---

## Project layout

```
Mnemosyne/
├── src/mnemosyne/
│   ├── engine.py            # MemoryEngine contract + LocalMemoryEngine; route() + RoutePlan
│   ├── postgres_engine.py   # PostgresEngine: RLS, FTS, pgvector, recursive PPR, as-of
│   ├── sqlite_engine.py     # SqliteEngine: per-tenant WAL file, shared retrieval pipeline
│   ├── mcp_tools.py         # 48 MCP tool definitions (the TOOL_SPEC facade)
│   ├── mcp_server.py        # stdio shim · SDK stdio · SDK StreamableHTTP · hosted HTTP
│   ├── cli.py               # 91-subcommand CLI (mneme)
│   ├── ingestion.py         # content-addressed ingest, signed provenance, media extract
│   ├── retrieval.py         # embedding/reranker/lexical/graph adapter classes + fallbacks
│   ├── consolidation.py     # 11-role warm-loop pipeline → promotion gate
│   ├── gate.py              # promotion gate: protected regression cases, branch rollback
│   ├── guard.py             # §25 anti-degradation guard (no_degradation_guard)
│   ├── lifecycle.py         # fidelity tiers + gist-risk abstention
│   ├── security.py          # trust tiers, capabilities, sessions, sanitization
│   ├── self_optimization.py # shadow-first policy variants under §31 rails
│   ├── queue.py / jobs.py / media.py   # durable queue + 7 job kinds
│   └── providers/           # ProviderRegistry + adapter plumbing (adapter classes live in retrieval.py)
├── sql/schema.sql           # canonical 24-table PostgreSQL schema
├── tests/                   # invariant, parity, contract, and completion suites
├── eval/                    # §33 eval harness: recall@k / nDCG / ECE / latency SLOs
├── infra/                   # Keycloak (OIDC), Vault, C2PA, provider compose stack
├── rust/mneme-providers/    # Provider sidecar for compact embed/rerank contracts
├── rust/mnemosyne-native/   # Optional PyO3 native retrieval kernels
├── services/embedding/      # standalone embedding provider service
├── docs/ROADMAP-TO-100.md   # sequenced path to 1:1 blueprint parity
└── .github/workflows/ci.yml # ruff + pytest + Postgres integration job
```

---

## Status

Exact 1:1 blueprint parity's Tier-B production-evidence rows are now CLOSED (2026-07-07): a genuine operator-run production capture yields a fully green 29-command `deployment-soak`, `release-audit` `ok:true`, and offline `production-evidence-verify` `ok:true` (bundle fingerprint `sha256:6dc117d6bb95e7a683915d432b2d2b21997133e9bfbd53624427a7317eeb2271`), flipping all 10 strict-parity audit rows Partial→Done. The headline guarantees remain proven: as of 2026-06-25, **all six headline §16 SLOs PASS** on the real retrieval/calibration paths:

| SLO | Measured | Target | Result |
| --- | --- | --- | --- |
| recall@k | 0.977 | ≥ 0.80 | ✅ |
| nDCG@k | 0.983 | ≥ 0.80 | ✅ |
| G2 token-efficiency lift | +0.208 @ 7% tokens | ≥ +0.15 | ✅ |
| Poison-block rate | 1.0 | ≥ 0.95 | ✅ |
| Calibration error (ECE) | 0.0063 | ≤ 0.05 | ✅ |
| Fast-path P95 (warm + serial) | 149.5 ms | ≤ 300–400 ms | ✅ |

> SLO evidence is the Wave-5 definitive run summarized in [`docs/ROADMAP-TO-100.md`](docs/ROADMAP-TO-100.md) and `eval/calibration/report.json` (`ece.policy_threshold.meets_target: true`). Hard-QA multi-hop answer-synthesis (recall/nDCG 0.625/0.594) is a known, non-headline gap, tracked separately.

The local implementation surface has moved past the original two-engine
posture: the native retrieval kernels, per-tenant SQLite engine, provider
sidecar, and proposal-role consolidation ladder are locally gate-proven on the
active Phase 3 branch. The latest Phase 3 exit record reports **1592 passed /
127 skipped** native, **1589 / 130** with `MNEMOSYNE_PURE=1`, **434 / 6**
DSN-armed parity plus `postgres_live`, and clean Rust/ruff/diff checks. These
are local engineering gates, not production sign-off.

Future Tier-B recaptures must use the same operator-owned production evidence
path: real IdP/Keycloak, Vault/KMS, ParadeDB/Apache AGE, hosted
embedding/reranker/trainer endpoints, C2PA trust roots, and hosted
MCP/dashboard surfaces captured via `deployment-soak`, `release-audit`, and
offline `production-evidence-verify`. Local code, tests, or regenerated docs
must not replace that custody path.

Controlling artifacts: [`docs/ROADMAP-TO-100.md`](docs/ROADMAP-TO-100.md) (blended figure + sequenced path), `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md` (status), and `infra/PRODUCTION-EVIDENCE.md` (capture/offline-custody handoff).

---

## Testing & CI

- `.github/workflows/ci.yml` installs the committed `uv.lock` environment and runs **ruff** lint, the full **pytest** suite (configuration / invariant-rail drift checks included), and a **Postgres integration** job on pushes to `main` and pull requests.
- With `MNEMOSYNE_POSTGRES_DSN` **unset**, the suite runs the local deterministic tests and skips live-DB integration tests — this no-DSN run is one required CI gate and must stay green.
- With Docker-compose Postgres running and the DSN set, the local full suite additionally runs live coverage in `tests/test_postgres_engine_live.py` and `tests/test_shared_engine_contract.py`, covering tenant RLS, FTS, pgvector search, recursive graph/PPR, bitemporal supersession, branch/merge/discard, tombstone + hard-delete forget modes, command-backed KMS, and **local↔Postgres parity** of the engine contract. CI runs the dedicated `tests/test_postgres_engine_live.py` Postgres job as the always-on live-DB gate.

```bash
uv sync --locked --extra mcp --group dev
uv run --locked python -m pytest          # local gate (live-DB tests skip without a DSN)
```

---

## Security

- **Capability-mediated, fail-closed writes** gated by trust tiers and sensitivity ceilings.
- **Signed sessions** for CLI (`--session-token`) and MCP (`X-Mnemosyne-Session-Token`), minted from OIDC tokens via `session-exchange`; secret custody through shell-free `--session-secret-command` adapters.
- **Retrieved text is data, not instructions** — every retrieved span is sanitized (§31 Rail 6) to defend against prompt injection. The poison corpus under `tests/completion/security/` is fixture data, never executable.
- **Tenant isolation** via Postgres RLS keyed on `mnemosyne_current_tenant()` on every tenant-scoped table.
- **Crypto-shred erasure**: encrypted object storage and KMS/Vault-backed key-custody adapters support legal hard-delete once production custody is configured and evidenced.
- **Provenance**: C2PA verification with scoped trust roots; manifests that match no trust rule are quarantined, not trusted.

Please report vulnerabilities privately to the maintainers rather than opening a public issue.

---

## License

Licensed under the [Apache License 2.0](LICENSE).
