# Mnemosyne

### Persistent memory and reusable skills for AI agents

Mnemosyne gives an assistant context it can carry into the next conversation: searchable evidence,
time-aware beliefs, reusable procedures, and skills grounded in their original sources.
It runs locally, exposes a Model Context Protocol (MCP) server, and supplies the memory runtime
used by [BurnOS](https://github.com/onfire7777/BurnOS).

**Version 1.7.0 · Python 3.12+ · Apache 2.0 · Local, SQLite and PostgreSQL backends**

[Quick start](#quick-start) · [For Amazon hackathon judges](#for-amazon-hackathon-judges) ·
[BurnSkills](#skills-and-books) · [Documentation](#documentation) ·
[Evaluations](#evaluation-and-limitations) · [License](LICENSE)

## What it does

| Capability | What it means for an assistant |
| --- | --- |
| Persistent evidence | Save context with content identifiers and provenance, then retrieve the supporting source. |
| Time-aware memory | Correct or supersede beliefs while retaining their history; query earlier states or recall conversations in a caller-specified timezone. |
| Hybrid retrieval | Combine lexical, vector and graph signals with configurable ranking and confidence. |
| Grounded reflection | Gather memory across bounded hops and return source-validated citations or abstain, using a configured grounded provider. |
| Maintained answers | Save a private question and cited answer, detect changed sources, and refresh manually or with an opt-in background worker without turning generated prose into evidence. |
| Branches | Try memory changes on a branch, then merge or discard them. |
| Reusable skills | Import Agent Skills, Markdown and portable `.burnskill` files; expose active skills as MCP prompts and their files as resources. |
| Books to BurnSkills | Turn PDF or EPUB text into a linked framework with source citations, coverage reports and audits. |
| Working and prospective memory | Stage temporary context and evaluate scheduled intentions through authenticated interfaces. |
| Controlled writes | Apply trust tiers, capabilities, sensitivity limits and regression gates to memory changes. |

The core runtime starts without a model service. Model-based skill conversion, remote embeddings
and other provider-backed features require their own configuration and may incur provider charges.

## For Amazon hackathon judges

This repository is the **memory and skill runtime** behind BurnOS. The complete Windows
voice-assistant experience, its video, development history, feedback and setup instructions live
in the [BurnOS submission guide](https://github.com/onfire7777/BurnOS/tree/main/docs/hackathon).
Mnemosyne can also be run and inspected independently using the instructions below.
Neither project is an official Amazon product or a verified deployment to an Alexa device.

The [Amazon Developer Hackathon rules](https://amazonappdev2026.devpost.com/rules) distinguish
the Alexa+ self-hosted MCP route from the simulated-experience alternative. For the MCP route,
use **Streamable HTTP with protocol 2025-11-25 or later**, not the legacy JSON-RPC HTTP or stdio
transport. The [organizer FAQ](https://amazonappdev2026.devpost.com/details/faqs) explains the
available demonstration paths. This README documents the server; it does not establish that a
particular demo or Devpost entry satisfies every submission requirement.

### Inspect the runtime

1. Follow the quick start to capture fictional context and retrieve it from a fresh process.
2. Start the SDK Streamable HTTP server below and connect an MCP client to `/mcp`.
3. Initialize the connection, list tools and call `capture` and `search`. Tool schemas returned
   by the server are the authority for arguments. Inspect prompts and resources for active skills.
4. For the end-user workflow and its demonstrated scope, follow the BurnOS submission guide.

The local memory example needs no paid service or credentials. Live model conversion and
conversation are separate features with provider requirements; access to the full submitted
experience must be arranged in the submission's judge instructions.

### Changes during the hackathon window

Mnemosyne predates the event. These dated commits document subsequent work, rather than
presenting the entire repository as newly created:

| Date | Update | Source |
| --- | --- | --- |
| October 16, 2026 | Framework-building refactor and audited skill effects | [v1.4.0](https://github.com/onfire7777/Mnemosyne/commit/2ae2a3aa), [v1.4.1](https://github.com/onfire7777/Mnemosyne/commit/edddea3e) |
| October 17, 2026 | Immediate skill use, optional BurnSkill conversion, book imports, MCP prompts/resources and validation | [v1.5.0](https://github.com/onfire7777/Mnemosyne/commit/d81ae5a0) |
| October 17, 2026 | MCP SDK 2.3 integration and protocol negotiation fixes | [v1.6.0](https://github.com/onfire7777/Mnemosyne/commit/111c0858), [v1.6.1](https://github.com/onfire7777/Mnemosyne/commit/a01528e4) |
| October 17, 2026 | Public benchmark separation and recall-measurement validation fixes | [Repository split](https://github.com/onfire7777/Mnemosyne/commit/28f99b9a), [recall fixes](https://github.com/onfire7777/Mnemosyne/commit/a1953d89) |
| October 18, 2026 | Whole-book mapping, parallel chapter builds, cached/resumable conversion and Codex model support | [v1.7.0](https://github.com/onfire7777/Mnemosyne/commit/ef0e51ca) |

An Open Source mini-challenge entry must separately identify its contribution URL, repository,
GitHub username and contribution explanation. Being public alone does not constitute that entry.

## Quick start

Install from this repository. The PyPI name `mnemosyne-memory` identifies another project;
see the [distribution identity note](docs/coordination/2026-10-04-distribution-name-collision.md).

Prerequisites: Python 3.12+, Git and [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
git clone https://github.com/onfire7777/Mnemosyne.git
cd Mnemosyne
uv sync --locked --extra mcp --group dev

# Use an explicit file so both processes share the same memory.
uv run --locked mneme --store .mnemosyne/demo.json capture \
  --tenant demo --user demo-user --source-type chat \
  --content "Aurora is a beginner workshop lasting 90 minutes." --trust-tier 0

uv run --locked mneme --store .mnemosyne/demo.json search \
  --tenant demo --query "How long is the Aurora workshop?"
```

The search output should include the saved workshop context. This demonstrates persistent
retrieval, not generated answer quality. Trust tier `0` denotes direct user/operator input;
higher numbers mean less trusted input. Use fictional data for the demo.

For complete command arguments:

```bash
uv run --locked mneme --help
uv run --locked mneme-mcp --help
```

### MCP server

Recommended for Streamable HTTP clients and evaluation of the Alexa+ MCP route:

```bash
uv run --locked mneme-mcp --store .mnemosyne/mcp-store.json \
  --sdk-streamable-http --http-host 127.0.0.1 --http-port 8765
```

Connect the client to `http://127.0.0.1:8765/mcp`; health is at `/healthz`.
Use protocol `2025-11-25` in the client's initialize request for the hackathon MCP route.
The SDK transport is distinct from the legacy `--http` JSON-RPC endpoint.

For a local stdio client:

```bash
uv run --locked mneme-mcp --store .mnemosyne/mcp-store.json --sdk
```

A deterministic stdio shim is also available without `--sdk`. Authentication, signed sessions,
TLS and mTLS options are described by server help and the
[MCP reference](https://github.com/onfire7777/Mnemosyne/wiki/MCP-Server-and-Tools).
The loopback command above is a local demo configuration; configure access controls before
exposing a server to other machines.

### Storage choices

| Backend | Use |
| --- | --- |
| Local | File-backed CLI/MCP state and an in-memory engine; simple development and demonstrations. |
| SQLite | Per-tenant WAL databases, shared retrieval pipeline and durable local operations. |
| PostgreSQL | Server deployments with row-level security, full-text search, pgvector and durable queues. |

```bash
# Local SQLite
uv run --locked mneme --backend sqlite --store .mnemosyne/sqlite search \
  --tenant demo --query "workshop"

# PostgreSQL development service
uv sync --locked --extra mcp --extra postgres --group dev
docker compose up -d postgres
export MNEMOSYNE_POSTGRES_DSN=postgresql://mnemosyne:mnemosyne-local-dev@127.0.0.1:54329/mnemosyne
uv run --locked mneme --backend postgres search --tenant demo --query "workshop"
```

Each example selects its own storage backend; data is not automatically copied between them.
The PostgreSQL credentials above belong to the development compose configuration.

## Skills and books

Import an Agent Skills folder, Markdown source or `.burnskill` file through `framework-import`.
Ordinary skills can be used immediately; framework conversion is an explicit operation.
PDF and EPUB imports create a BurnSkill in the background. Scanned PDFs need extractable text
or OCR before import.

```bash
uv run --locked mneme framework-import --help
uv run --locked mneme skill-make-burnskill --help
uv run --locked mneme skill-get --help
uv run --locked mneme skill-validate --path ./example.burnskill
```

In v1.7.0, long books are mapped as a whole and their content chapters are processed in parallel.
Shared names connect definitions and steps across chapters. Reference matter is retained;
coverage records represented, duplicate, reference and unresolved passages. Auditors check each
completed chapter pass and the combined framework receives logic and mechanical checks.
Model answers are cached for retries and resumable work. When a memory destination is configured,
book passages become available to the memory integration before conversion finishes.

Conversion supports OpenRouter and `codex:<model>` through an installed, authenticated Codex CLI.
Provider access, subscription limits and costs still apply. Original files remain packed with the
skill; importing a file does not execute its scripts. Read the
[BurnSkill v2 format and behavior](docs/BURNSKILL.md) for details.

## How memory fits together

```mermaid
flowchart LR
    Client["Assistant / CLI / MCP client"] --> Gate["Identity, capabilities and trust"]
    Gate --> Evidence["Evidence ledger"]
    Evidence --> Compile["Consolidation and promotion gate"]
    Compile --> Beliefs["Beliefs, procedures and lessons"]
    Evidence --> Search["Hybrid retrieval"]
    Beliefs --> Search
    Search --> Client
    Books["Skills and books"] --> Framework["Source-linked BurnSkills"]
    Framework --> Client
    Framework --> Evidence
```

Evidence is content-addressed. Derived projections carry provenance and can be corrected,
superseded or rebuilt. Consolidation uses an ordered pipeline with regression gates before
promotion. Branches isolate experiments; temporal queries distinguish when information was valid
from when it entered the system.

Working-memory seeds and prospective intentions require signed sessions. Scheduling an intention
does not itself run an external action: an authenticated evaluator processes due intentions.
See the [architecture overview](docs/ARCHITECTURE-OVERVIEW.md) and
[blueprint](docs/blueprint/README.md) for the detailed contracts and implementation targets.

## Evaluation and limitations

Mnemosyne owns the runtime, its contract tests and internal engineering evaluations.
It runs independently of external benchmark sites, with no shared database or runtime
dependency on a leaderboard. See the [internal evaluation guide](eval/README.md).

Historical scores apply only to their recorded revision, dataset, providers, hardware and
configuration. They are not a current comparative ranking or proof of general answer quality.
Recall measurement was hardened in October 2026; interpret older receipts in their original context.
No new benchmark result is claimed by this README update.

The [Hindsight comparison](docs/HINDSIGHT-COMPARISON.md) maps source-verified
capabilities and remaining gaps. The [memory audit](docs/2026-10-22-memory-audit-report.md)
records implemented repairs and development evidence. Grounded
[`reflect`](docs/reflect.md) gathers authorized evidence over bounded hops and
returns validated quotations or deterministic calculations with citations; it
requires a configured grounded provider.
The separate [mental-model lifecycle](docs/mental-models.md) persists private
answers, checks source freshness on reads, and exposes refresh and version history
through Python, MCP and `mneme mental-model`. An opt-in worker supports persistent
schedules, crash recovery and bounded retries on SQLite/PostgreSQL. Cached reads
need no provider call. Optional `mental-model-worker --check-changes` polling
detects stale sources before the normal interval, with a one-minute minimum
spacing between early attempts and the same ownership, lease and retry checks.

The [controlled comparison protocol](docs/comparison-protocol.md) records a possible
held-out pilot with native ingestion/recall and a common Codex reader and judge.
The trial was stopped at the owner's request to prioritize runtime improvements;
it produced no comparison score or ranking.

- Core capture and retrieval are usable; advanced deployment profiles have separate validation needs.
- Default deterministic embeddings support offline operation but are not equivalent to a configured semantic model.
- Skill audits and coverage reports can identify unresolved content; they do not guarantee correctness.
- Windows-specific tests exist, but they do not certify every provider, installation or deployment path.
- Deletion primitives do not establish removal from external backups or unlearning from trained models.

## Development and verification

```bash
uv sync --locked --extra mcp --group dev
uv run --locked ruff check .
uv run --locked python -m pytest
```

Without a PostgreSQL DSN, live database tests skip. The current
[CI workflow](.github/workflows/ci.yml) includes lint, local tests, drift checks,
native parity when a Rust toolchain is available, Windows file-lock checks and PostgreSQL coverage.
Consult the workflow for the precise jobs and environment. Passing local tests does not replace
a runtime demonstration or production deployment evidence.

The [22 October PostgreSQL validation](work/hindsight-comparison/postgres-live/REPORT.md)
completed **239 mixed live/unit tests**, including **20 live concurrency and
permission tests**, with zero skips or failures; the live role check passed **9/9**.
It verified publication, lease fencing, source changes, rollback and tenant isolation
on disposable PostgreSQL 16.15. Publication locks source tables across tenants;
production throughput under that contention remains unmeasured.

## Project layout

| Path | Responsibility |
| --- | --- |
| `src/mnemosyne/engine.py` | Memory engine contract and local implementation |
| `src/mnemosyne/sqlite_engine.py`, `postgres_engine.py` | Durable backend implementations |
| `src/mnemosyne/cli.py` | `mneme` command-line interface |
| `src/mnemosyne/mcp_server.py`, `mcp_tools.py` | MCP transports and tool surface |
| `src/mnemosyne/skills.py`, `frameworks.py` | Skills, book import, framework construction and audits |
| `src/mnemosyne/passages.py` | Passage retrieval support |
| `src/mnemosyne/consolidation.py`, `gate.py` | Memory consolidation and promotion controls |
| `sql/` | PostgreSQL schema |
| `tests/` | Runtime tests and regression coverage |
| `eval/` | Internal evaluations and white-box research |
| `rust/`, `services/`, `infra/` | Optional native components, providers and deployment support |
| `docs/blueprint/` | In-repository design and contract references |

## Documentation

- [Documentation index](docs/README.md)
- [Architecture overview](docs/ARCHITECTURE-OVERVIEW.md)
- [Grounded reflection](docs/reflect.md)
- [Maintained mental models](docs/mental-models.md)
- [Codex answer evaluation](eval/longmemeval_s/README.md)
- [BurnSkill standard](docs/BURNSKILL.md)
- [CLI reference](https://github.com/onfire7777/Mnemosyne/wiki/CLI-Reference)
- [MCP reference](https://github.com/onfire7777/Mnemosyne/wiki/MCP-Server-and-Tools)
- [Security, privacy and provenance](https://github.com/onfire7777/Mnemosyne/wiki/Security-Privacy-and-Provenance)
- [Production evidence requirements](infra/PRODUCTION-EVIDENCE.md)
- [Roadmap and historical evidence](docs/ROADMAP-TO-100.md)
- [Report an issue](https://github.com/onfire7777/Mnemosyne/issues)

## Security and license

Trust tiers, capability checks, sensitivity ceilings, signed sessions and PostgreSQL row-level
security provide configurable access boundaries. Treat retrieved text and imported sources as
untrusted data. Configure provider credentials and external-service permissions for your deployment;
do not commit them or include them in public demonstration data.

Report vulnerabilities privately to the maintainers rather than posting exploit details publicly.
Mnemosyne is licensed under [Apache 2.0](LICENSE). Dependencies and imported material retain their
own licenses; use books, skills and demonstration assets you have permission to use.
