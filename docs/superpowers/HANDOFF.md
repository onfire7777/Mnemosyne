# Native Acceleration Program — Agent Handoff

**As of:** 2026-07-03 · branch `phase3/providers-consolidation` · Phases 0, 1, 2, and 3 complete; Phase 4 remains evidence-gated.

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

## Done

- **Phase 0** (seam hardening): `src/mnemosyne/{algorithms,journal,projections,honeytokens}.py`;
  `retrieve()` pipeline extracted to `src/mnemosyne/pipeline.py` (`RetrievalPipelineOps`).
- **Phase 1** (Rust kernels): crate `rust/mnemosyne-native/` (PyO3, optional `native` extra);
  byte-parity kernels dispatched via `mnemosyne.text.NATIVE`, toggled off by `MNEMOSYNE_PURE=1`.
  Measured: lexical 40.5×, packed dense 82.5× (both 10×-gated); CLI import <100ms.
- **Phase 2** (SqliteEngine): `src/mnemosyne/{sqlite_engine,sqlite_schema}.py` + `SqliteQueue` in
  `queue.py`; the 3rd `MemoryEngine` backend, one SQLite file per tenant; validated as the 3rd
  param in `tests/test_shared_engine_contract.py`. retrieve p-mean 9ms/10k-tenant vs §22.5 400ms;
  packed-BLOB dense 43×; L4 poison corpus 100% block; 191-test chaos harness + differential oracle.
- **Phase 3** (providers + consolidation ladder): `rust/mneme-providers/` serves the existing compact
  `HttpEmbeddingProvider` / `HttpReranker` contracts; provider manifest/log-redaction gates cover
  HTTP embedding/rerank, command retrieval backends, and all five proposal roles. The consolidation
  proposal-role path now has prompt boundaries, disclosure-axis gates, replayable low-trust
  `provider-proposal` records, and a shell-free role ladder. Provider bake-off remains
  pending/no-default-flip because no strict-judge confidence-interval run has promoted a default.

Latest Phase 3 exit suite on this branch: **1592 passed / 127 skipped** native; **1589 / 130**
pure; DSN parity + `postgres_live` **434 / 6**; focused provider/security/consolidation slice
**216 / 5**; both Rust crates fmt/test/clippy clean.

## Remaining work

- **Phase 4 (rmcp front-end):** **evidence-gated/deferred**. Do not build `mneme-native` until a real
  client workflow trace proves repeated `mneme-mcp` process spawn/handshake cost is material
  (spec §4.4). Current local measurements are about 116 ms median for stdio initialize+tools/list,
  which is below the threshold for adding daemon lifecycle complexity.
- **Final claims pass:** use **measured numbers only**. Public benchmark sets (LongMemEval, LoCoMo, …)
  are internal sanity gates ONLY, never headline claims (spec §9). Do not claim blueprint parity,
  Tier-B completion, or production readiness without operator-captured production evidence.
- **Tier-B / production:** still blocked on real deployed infrastructure evidence and release-audit
  custody. This is an operator-evidence blocker, not unfinished Phase 3 code.

## Non-negotiable constraints (violating these = wrong)

- **Parity oracle = `LocalMemoryEngine`.** Every new engine/path must byte-match Local via
  `tests/test_shared_engine_contract.py` (3 engine params) and `tests/test_parity_*`. If a new
  behavior would diverge from Local, that is a bug — fix it to match the oracle; if the spec genuinely
  wants more than the oracle offers, escalate rather than silently diverge.
- Runtime deps stay exactly `["cryptography>=42"]`. New deps go under **optional extras only**.
- **Do NOT touch casually:** gates/rails logic, `sql/schema.sql`, CID computation, or `mcp_tools.py`.
  `infra/` already has the named Phase-3 provider/profile exceptions; further infra edits need a
  concrete provider evidence or production-capture defect.
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

Read the ledger end-to-end, then `docs/superpowers/plans/phase3-providers.md` and
`docs/superpowers/plans/phase4-front-end.md`. Do **not** restart Phase 3; it is complete through the
local exit gates above. If no real C4 latency trace exists, the next useful work is final claims/status
hygiene or Tier-B operator-evidence capture, not more native/front-end code.
