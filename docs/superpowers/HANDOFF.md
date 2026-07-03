# Native Acceleration Program — Agent Handoff

**As of:** 2026-07-03 · **main @ `ec6f404`** (pushed to `origin`) · Phases 0, 1, 2 complete; Phases 3, 4 + final claims remain.

You are taking over an in-progress, multi-phase engineering program on the Mnemosyne codebase.
Work from the repo root. Read the on-disk artifacts below FIRST — they are the source of truth;
this file is only a map.

## Project

Mnemosyne = a local-first memory compiler for AI agents (Python 3.12, ~50k LOC, `uv`-managed).
The "Native Acceleration" program adds a Rust kernel layer + a SQLite engine + a provider sidecar
+ an MCP front-end, **without** rewriting the authoritative Python core and **without** any behavior
change (byte-parity discipline).

## Authoritative docs (read in this order)

1. **Spec:** `docs/superpowers/specs/2026-07-01-native-acceleration-design.md` (the contract; §-numbered).
2. **Program map:** `docs/superpowers/plans/2026-07-01-native-acceleration-program.md` (phase status table).
3. **Ledger:** `.superpowers/sdd/progress.md` — *gitignored, local-only* — per-task record: every commit
   SHA, review verdict, cross-task handoff, and accepted spec>shipped gap. **Read fully.** If working
   from a fresh clone where this is absent, reconstruct state from the spec + plans + `git log`.
4. **Phase plans:** `docs/superpowers/plans/2026-07-0*-phase*.md`.
5. **Grounding** (*gitignored*, verified file:line facts): `.superpowers/sdd/phase2-grounding.md`,
   `.superpowers/sdd/phase3-grounding.md`. Re-grep anchors before editing — line numbers drift.

## Done (merged + pushed to origin/main @ ec6f404)

- **Phase 0** (seam hardening): `src/mnemosyne/{algorithms,journal,projections,honeytokens}.py`;
  `retrieve()` pipeline extracted to `src/mnemosyne/pipeline.py` (`RetrievalPipelineOps`).
- **Phase 1** (Rust kernels): crate `rust/mnemosyne-native/` (PyO3, optional `native` extra);
  byte-parity kernels dispatched via `mnemosyne.text.NATIVE`, toggled off by `MNEMOSYNE_PURE=1`.
  Measured: lexical 40.5×, packed dense 82.5× (both 10×-gated); CLI import <100ms.
- **Phase 2** (SqliteEngine): `src/mnemosyne/{sqlite_engine,sqlite_schema}.py` + `SqliteQueue` in
  `queue.py`; the 3rd `MemoryEngine` backend, one SQLite file per tenant; validated as the 3rd
  param in `tests/test_shared_engine_contract.py`. retrieve p-mean 9ms/10k-tenant vs §22.5 400ms;
  packed-BLOB dense 43×; L4 poison corpus 100% block; 191-test chaos harness + differential oracle.

Suite on main: **1578 passed / 127 skipped** native; **1575 / 130** pure; DSN parity **394 / 6**.

## Remaining work

- **Phase 3 (providers + consolidation ladder):** write `docs/superpowers/plans/phase3-providers.md`
  from `phase3-grounding.md`, then execute it. Per spec §4.3/§4.5:
  - **C3** — a Rust `mneme-providers` sidecar serving the **existing** `HttpEmbeddingProvider`/
    `HttpReranker` contracts. The production embedder speaks Mnemosyne's **own compact** `POST /embed`
    + `POST /rerank` + `GET /health` API (**not** the HuggingFace TEI API); mirror
    `infra/docker-compose.prod.yml`'s `embedder` service shape.
  - **A3** — the consolidation role-LLM ladder. The 5 proposal roles already have `Command*` adapters,
    but the `MNEMOSYNE_*_PROVIDER=command` switches are unset in infra and 3/5 `Command` payloads omit
    `prompt_boundary`. The spec-required **proposal-ledger** (record frontier outputs as replayable
    proposals) is **unimplemented**; **disclosure invariants** (S3+ never verbatim to an external model,
    per-disclosure salting) are **unimplemented**. These are the Phase-3 tasks.
- **Phase 4 (rmcp front-end):** **evidence-gated** — do not build until you have measured proof that
  per-session MCP spawn latency actually matters (spec §4.4). Ship A4-style wins first otherwise.
- **Final:** README/claims pass using **measured numbers only**. Public benchmark sets (LongMemEval,
  LoCoMo, …) are internal sanity gates ONLY, never headline claims (spec §9).

## Non-negotiable constraints (violating these = wrong)

- **Parity oracle = `LocalMemoryEngine`.** Every new engine/path must byte-match Local via
  `tests/test_shared_engine_contract.py` (3 engine params) and `tests/test_parity_*`. If a new
  behavior would diverge from Local, that is a bug — fix it to match the oracle; if the spec genuinely
  wants more than the oracle offers, escalate rather than silently diverge.
- Runtime deps stay exactly `["cryptography>=42"]`. New deps go under **optional extras only**.
- **Do NOT touch:** gates/rails logic, `sql/schema.sql`, `infra/`, CID computation, `mcp_tools.py`.
- Both kernel modes must stay green: default (native) **and** `MNEMOSYNE_PURE=1`.
- Production topology stays Postgres-only (SqliteEngine in a prod profile = config-drift check D).
- The accepted spec>shipped gaps are recorded in the ledger + `docs/adr/0001-sqlite-per-tenant-file-isolation.md`;
  don't re-open them without cause. (Summary: erase-all-branches matches Local's single-branch scope;
  `_record_retrieval_access` synchronous — async would break parity; `branches.created_at` Z-format is
  export-only and oracle-normalized.)

## Workflow (how each task was done — keep it)

TDD + oracle-comparison. Per task: write characterization/parity tests **first** → implement → run the
**full** suite (zero regressions) → **independent code review** → fix findings → commit
`type(scope): summary` → append a one-line record to `.superpowers/sdd/progress.md`. Reviews scrutinized
security/privacy claims adversarially (privacy rails, erasure invariant-13, poison-corpus floors) and
**caught real bugs** (an invariant-13 plaintext-cid leak; 4 latent engine bugs surfaced by the acceptance
run). Do not skip the review step.

## Operational

- **Tests:** `uv run --locked python -m pytest` (pyproject already sets `-q`; don't add another `-q`;
  never edit source while a suite is running — some tests use `inspect.getsource`).
- **Pure mode:** prefix `MNEMOSYNE_PURE=1`. **Chaos** (gated): `MNEMOSYNE_CHAOS=1 pytest tests/chaos`.
  **Benchmarks:** `pytest tests/benchmarks --benchmark-only` (absolute budgets: `MNEMOSYNE_BENCH_ABSOLUTE=1`).
- **DSN parity** (dev Postgres on port 54329; `docker compose up -d postgres` if down):
  ```
  MNEMOSYNE_POSTGRES_DSN='postgresql://mnemosyne:mnemosyne-local-dev@127.0.0.1:54329/mnemosyne' \
    uv run --locked python -m pytest tests/test_parity_* tests/test_shared_engine_contract.py
  ```
- **Native rebuild after Rust edits:**
  `uv sync --reinstall-package mnemosyne-native --locked --extra mcp --extra postgres --extra native --group dev`
  (plain `uv sync` does NOT pick up `.rs` changes).
- Full suite ~2.5 min; run long suites with `nohup` + a done-marker + a polling loop, not a foreground wait.
- `.superpowers/sdd/` is gitignored (ledger + per-task reports + grounding live there, uncommitted).

## Start here

Read the ledger end-to-end, then `phase3-grounding.md`, then write the Phase 3 plan and begin executing
it task-by-task with the oracle-parity + independent-review discipline above. Confirm your understanding
of the parity-oracle rule before writing code.
