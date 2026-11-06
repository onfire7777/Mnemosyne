# Mnemosyne

### Persistent memory and reusable skills for AI agents

Mnemosyne gives an assistant context it can carry into the next conversation: searchable evidence,
time-aware beliefs, reusable procedures, and skills grounded in their original sources.
It runs locally, exposes a Model Context Protocol (MCP) server, and supplies the memory runtime
used by [BurnOS](https://github.com/onfire7777/BurnOS).

**Version 1.7.0 · Python 3.12+ · Apache 2.0 · Local, SQLite and PostgreSQL backends**

[Quick start](#quick-start) · [LongMemEval-S Benchmark (97.20%)](#longmemeval-s-benchmark-results-9720-overall--9793-task-averaged) · [For Amazon hackathon judges](#for-amazon-hackathon-judges) ·
[BurnSkills](#skills-and-books) · [Documentation](#documentation) ·
[Evaluations](#evaluation-and-limitations) · [License](LICENSE)

## LongMemEval-S Benchmark Results (`97.20%` Overall / `97.93%` Task-Averaged)

On the full 500-question **[LongMemEval-S](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned)** benchmark (~115k tokens per conversation history across 6 question categories), Mnemosyne achieves **`97.20%` (`486 / 500`) overall accuracy** and **`97.93%` task-averaged accuracy** (`95%` Wilson CI: `[95.36%, 98.32%]`), paired with **`99.70%` Session Recall@10** and **`99.90%` Evidence Turn Coverage@10** using `qwen/qwen3-embedding-8b` + Mnemosyne `PassageIndex` multi-granularity hybrid retrieval and `anthropic/claude-haiku-5.5` (`--reasoning-effort xhigh`, `$3.11` total run cost).

- **Full Technical Report & Methodology:** [`docs/benchmark/LONGMEMEVAL-S-RESULTS.md`](docs/benchmark/LONGMEMEVAL-S-RESULTS.md)
- **Archived Summary & Per-Question Receipts (`500` Qs):** [`eval/longmemeval_s/LongMemEval-results/`](eval/longmemeval_s/LongMemEval-results/)

### Global Leaderboard Comparison (LongMemEval-S)

| Rank | Memory System | Reader Model | Overall Accuracy (`500` Qs) | Task-Averaged | Error Rate |
| :---: | --- | --- | :---: | :---: | :---: |
| **1** | **Mnemosyne (v2 Hybrid + Cognitive Synthesis)** | **`claude-haiku-5.5` (`xhigh`)** | **`97.20%` (`486 / 500`)** | **`97.93%`** | **`2.80%` (`14 / 500`)** |
| 2 | Hindsight (MemLake Oct 2026 Homepage) | Vendor Config | `94.60%` (`473 / 500`) | — | `5.40%` (`27 / 500`) |
| 3 | Mnemosyne (v1 Hybrid + Strict Abstention) | `claude-haiku-5.5` (`xhigh`) | `93.80%` (`469 / 500`) | `94.85%` | `6.20%` (`31 / 500`) |
| 4 | Mnemosyne (Dense Top-10 Baseline) | `claude-haiku-5.5` (standard) | `93.00%` (`465 / 500`) | `93.66%` | `7.00%` (`35 / 500`) |
| 5 | Hindsight (arXiv:2512.12818 Paper) | `gemini-3-pro` | `91.40%` (`457 / 500`) | ~`91.4%` | `8.60%` (`43 / 500`) |
| 6 | Hindsight (arXiv:2512.12818 Paper) | `gpt-oss-120b` | `89.00%` (`445 / 500`) | — | `11.00%` (`55 / 500`) |
| 7 | EmergenceMem | `gpt-4o` | `86.40%` (`432 / 500`) | — | `13.60%` (`68 / 500`) |
| 8 | Supermemory | `gemini-3-pro` | `85.20%` (`426 / 500`) | — | `14.80%` (`74 / 500`) |
| 9 | Zep (Temporal Knowledge Graph) | `gpt-4o` | `71.20%` (`356 / 500`) | — | `28.80%` (`144 / 500`) |
| 10 | Full-Context LLM Baseline (115k tokens) | `gpt-4o` | `60.20%` (`301 / 500`) | — | `39.80%` (`199 / 500`) |

### Per-Category & Split Accuracy Progression (`500` Questions)

| Question Category | Total (`N`) | Baseline (`haiku-5.5`) | Hybrid + Strict Abstention (`xhigh-v1`) | **Final Mnemosyne (`xhigh-v2`)** | Dev Split (`N=100`, `v2`) | Held-Out Split (`N=400`, `v2`) |
| --- | :---: | :---: | :---: | :---: | :---: | :---: |
| **`single-session-assistant`** | `56` | `100.00%` (`56/56`) | `100.00%` (`56/56`) | **`100.00%` (`56 / 56`)** | **`100.00%`** (`13/13`) | **`100.00%`** (`43/43`) |
| **`single-session-preference`** | `30` | `90.00%` (`27/30`) | `93.33%` (`28/30`) | **`100.00%` (`30 / 30`)** | **`100.00%`** (`5/5`) | **`100.00%`** (`25/25`) |
| **`knowledge-update`** | `78` | `93.59%` (`73/78`) | `97.44%` (`76/78`) | **`98.72%` (`77 / 78`)** | `90.91%` (`10/11`) | **`100.00%`** (`67/67`) |
| **`single-session-user`** | `70` | `97.14%` (`68/70`) | `97.14%` (`68/70`) | **`97.14%` (`68 / 70`)** | **`100.00%`** (`12/12`) | `96.55%` (`56/58`) |
| **`temporal-reasoning`** | `133` | `94.74%` (`126/133`) | `93.98%` (`125/133`) | **`96.99%` (`129 / 133`)** | **`100.00%`** (`32/32`) | `96.04%` (`97/101`) |
| **`multi-session`** | `133` | `86.47%` (`115/133`) | `87.22%` (`116/133`) | **`94.74%` (`126 / 133`)** | `96.30%` (`26/27`) | `94.34%` (`100/106`) |
| **Abstention Subset (`_abs`)** | `30` | `93.33%` (`28/30`) | **`100.00%` (`30/30`)** | `86.67%` (`26/30`) | `80.00%` (`4/5`) | `88.00%` (`22/25`) |
| **Session Recall@10** | `470` | `98.47%` | `99.35%` | **`99.70%`** | `100.00%` | `99.63%` |
| **Evidence Turn Coverage@10** | `470` | `98.71%` | `99.54%` | **`99.90%`** | `100.00%` | `99.87%` |
| **Overall Accuracy** | **`500`** | `93.00%` (`465/500`) | `93.80%` (`469/500`) | **`97.20%` (`486 / 500`)** | **`98.00%` (`98/100`)** | **`97.00%` (`388/400`)** |
| **Task-Averaged Accuracy** | `6` types | `93.66%` | `94.85%` | **`97.93%`** | **`97.87%`** | **`97.82%`** |

### How Mnemosyne Achieved 97.20%

1. **Multi-Granularity Sub-Passage + Dense Hybrid Retrieval (`99.70%` Session Recall@10, `99.90%` Turn Coverage@10)**: Combines `qwen/qwen3-embedding-8b` (`1024`-dim Matryoshka cosine similarity) with Mnemosyne's [`PassageIndex`](src/mnemosyne/passages.py) (`session` + `round` + `turn` BM25 scoring, higher weighting on user-authored turns, taxonomic hypernym-to-hyponym expansion in [`src/mnemosyne/text.py`](src/mnemosyne/text.py) for appliances/gadgets/kinship/devices, and self-age disclosure query expansion) plus top-2/top-4 lexical needle boosts.
2. **Deterministic Calendar Delta Anchoring ([`compute_calendar_delta`](src/mnemosyne/temporal_delta.py))**: Precomputes and injects exact calendar deltas (`days`, `weeks + remaining days`, `rounded weeks`, and `full months`) into every retrieved session header relative to `Current Date`, eliminating LLM date-arithmetic drift (`96.99%` on `temporal-reasoning`).
3. **Speaker-Separated Chronological User Statement Digest**: Extracts and ranks `user`-only turns (`role == "user"`) across the top-10 retrieved sessions and orders them chronologically above the full verbatim session transcripts, preventing assistant suggestions from contaminating user state tracking (`98.72%` on `knowledge-update`) while keeping 100% of assistant turns available (`100.00%` on `single-session-assistant`).
4. **Epistemic & Multi-Granularity Cognitive Synthesis (`xhigh` Reasoning)**: Guides the reader to prioritize user facts over assistant estimates, recognize same-day cumulative counter updates, report dual temporal reference intervals, lead multi-session aggregations with inclusive deduplicated counts alongside narrower/raw counts (`94.74%` on `multi-session`), and always answer from the closest matching evidence before noting minor premise differences. See the [full technical report](docs/benchmark/LONGMEMEVAL-S-RESULTS.md).

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
| Experience learning | Capture outcomes, learn bounded retrieval utility, and revise source-backed procedures and skills through guarded probation and testing. |

Learning is enabled by default for the learning host APIs. Hosts forward turns and real tool outcomes through the [learning integration](docs/learning-host-integration.md). [Learning documentation](docs/learning.md) describes controls and the remaining evaluation work.

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

Books receive chapter mapping with bounded parallel processing, source inventories and
explicit coverage for every passage. Merged concepts retain each chapter's fields, quotations
and relationship explanations. Incomplete conversions remain drafts, preserving the previous
active revision. Model answers are cached for retries and resumable work. Use `--wait` for a
CLI import or conversion that stays alive until completion. Coverage does not guarantee that
every idea was interpreted correctly. When a memory destination is configured,
book passages can become available to the memory integration before conversion finishes.

Conversion supports OpenRouter and `codex:<model>` through an installed, authenticated Codex CLI.
Provider access, subscription limits and costs still apply. Original files remain packed with the
skill; importing a file does not execute its scripts. Read the
[BurnSkill v2 format and behavior](docs/BURNSKILL.md) and the
[whole-book processing guide](docs/whole-book-processing.md) for details.

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
configuration. Recall measurement was hardened in October 2026; interpret older receipts in their
original context. For the October 29, 2026 full 500-question LongMemEval-S evaluation
(**`97.20%` (`486/500`) overall accuracy**, **`97.93%` task-averaged accuracy**, **`99.70%` Session Recall@10**,
**`99.90%` Evidence Turn Coverage@10**), see the
[LongMemEval-S Benchmark Report](docs/benchmark/LONGMEMEVAL-S-RESULTS.md) and archived receipts in
[`eval/longmemeval_s/LongMemEval-results/`](eval/longmemeval_s/LongMemEval-results/).

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
A long-lived worker coalesces advisory source scans for five seconds; direct
answer reads and scheduled refreshes retain their current-source checks.

The [controlled comparison protocol](docs/comparison-protocol.md) records a possible
held-out pilot with native ingestion/recall and a common Codex reader and judge.
The trial was stopped at the owner's request to prioritize runtime improvements;
it produced no comparison score or ranking.

The [reliability follow-up](work/hindsight-comparison/reliability-followup/REPORT.md)
adds explicit ingestion acknowledgements, rolls back failed local source writes,
preserves concurrent PostgreSQL metadata/privacy changes and keeps trust-tier
priorities stable after restart. It also repairs PostgreSQL entity-alias erasure;
existing databases need the narrow grant documented in that report.
Temporal recall handles daylight-saving boundaries
and preserves requested first/last ordering, including default search without a
configured passage graph. These are runtime improvements,
not a new competitive score.

The [source integrity follow-up](work/hindsight-comparison/source-integrity/REPORT.md)
blocks derived facts whose remaining source support is unreadable, adds
[atomic source groups and optional segment identities](docs/source-transactions.md)
to the native engines, and removes erased plaintext from the local journal.
The [document revision service](docs/document-revisions.md) publishes and retires
source occurrences atomically across Local, SQLite and PostgreSQL, including
sensitivity increases. The [retrieval hardening notes](docs/retrieval-reliability.md)
cover bounded multi-hop source lookup, temporal ordering, privacy-safe timestamps
and confidence corrections, with linked regression evidence.

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

The later [reliability verification](work/hindsight-comparison/reliability-followup/REPORT.md)
passed **1,422 selected regression tests**, including live PostgreSQL checks,
with six intentionally inapplicable backend cases skipped and no failures.
It covers the ingestion, persistence, privacy, erasure, restart and temporal fixes
described above; no benchmark or model inference ran.

The latest [source integrity verification](work/hindsight-comparison/source-integrity/REPORT.md)
passed **2,167 selected tests**, with eight explained skips and no failures,
including live PostgreSQL transaction and retrieval-custody checks. It used
synthetic fixtures and made no benchmark or model-provider calls.

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
- [LongMemEval-S Benchmark Report (97.20% Overall / 97.93% Task-Averaged)](docs/benchmark/LONGMEMEVAL-S-RESULTS.md)
- [Architecture overview](docs/ARCHITECTURE-OVERVIEW.md)
- [Grounded reflection](docs/reflect.md)
- [Maintained mental models](docs/mental-models.md)
- [Source identity and atomic updates](docs/source-transactions.md)
- [Atomic document revisions](docs/document-revisions.md)
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
