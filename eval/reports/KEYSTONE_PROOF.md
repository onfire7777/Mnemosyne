# Mnemosyne Keystone Proof — Real Embedding Service wired to the §33 Eval Harness

Generated: 2026-06-21T23:57:26.142055+00:00

> **Historical/superseded report.** This file is preserved as the 2026-06-21
> keystone run that exposed the local embedding seam and ECE/G2 gaps. It is not
> the current parity status. The local embedding seam was closed on 2026-06-24,
> and current controlling evidence in
> `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md`, `docs/ROADMAP-TO-100.md`, and
> `eval/calibration/report.json` records 6/6 headline SLOs proven, including ECE
> 0.0063 against the ≤0.05 target. Remaining strict-parity work is Tier B
> operator production evidence.

## What was proven

- Real embedding+reranker service stood up from `services/embedding/app.py` on `127.0.0.1:8000`.
- **REAL backend confirmed live** via `/health`: embedding=`BAAI/bge-small-en-v1.5` (backend `sentence-transformers`), reranker=`cross-encoder/ms-marco-MiniLM-L-6-v2` (backend `cross-encoder`), in `.venv-eval` (Python 3.11, torch 2.12.1, sentence-transformers 5.6.0).
- LLM judge wired via `MNEMO_EVAL_JUDGE_CMD` -> `eval/judge_claude.py` (local `claude -p` CLI). 18 real judge calls executed in the G2 suite.
- Request counters (instrumented launcher) proved the wired path fired: **226 POST /embed + 138 POST /rerank** during the Postgres run.

## CRITICAL FINDING — local backend ignores HTTP retrieval adapters (Codex `src` bug)

With `--backend local`, the CLI builds the HttpEmbeddingProvider/HttpReranker but **never passes them to the engine**: `src/mnemosyne/cli.py::load_engine` returns `LocalMemoryEngine(store_path=Path(args.store))` with NO `adapters=` argument (the Postgres branch DOES pass `adapters=load_retrieval_adapters(args)`). `LocalMemoryEngine.__init__(self, store_path, policy)` has no embedding-provider seam at all. Result: the AFTER-local run made **0** `/embed` calls and produced numbers byte-identical to the deterministic floor.

The wired path is the **Postgres backend**, which genuinely calls the service (`postgres_engine.py:137` -> `self.adapters.embedding.embed(...)`). The real moved numbers below come from there.

## Results — BEFORE (deterministic floor) vs AFTER-local vs AFTER-postgres (real wired)

| Metric | §16 target | BEFORE floor | AFTER local* | AFTER postgres (REAL) |
|---|---|---|---|---|
| recall@k | >=0.80 (seed) | 0.7222 | 0.7222 | 0.9444 |
| nDCG@k | >=0.80 (seed) | 0.6667 | 0.6667 | 0.9570 |
| ECE | <=0.05 | 0.2000 | 0.2000 | 0.2000 |
| G2 lift | >=+0.15 | -0.3333 | -0.3333 | 0.0000 |
| G2 token-eff | >=0.95 | 0.6667 | 0.6667 | 1.0000 |
| poison block | >=0.95 | 1.0000 | 1.0000 | 1.0000 |
| fast_path P95 raw (ms) | <=300-400 | 4450 | 1806 | 2804 |
| fast_path P95 engine-only (ms) | <=300-400 | 2308 | 1458 | 2562 |

\* AFTER-local = HTTP flags forwarded but silently ignored by LocalMemoryEngine (proves the bug).

## Headline real movement (AFTER-postgres vs floor)

- recall@k **0.7222 -> 0.9444** (PASS >=0.80) — real BGE fixed `q_lang_pref` (0->1) and `q_seine` (0->1).
- nDCG@k **0.6667 -> 0.9570** (PASS >=0.80) — cross-encoder rerank lifted `q_oncall` nDCG 0.39->1.00.
- ECE **0.20 -> 0.20** (unchanged; calibration is policy/threshold-driven, independent of embedding quality — still fails <=0.05).
- G2 lift **-0.3333 -> 0.0000** (memory answer-rate rose to 1.0 == full-context ceiling; token-efficiency now PASS 1.0 at 8.3% tokens; the +15% lift over a perfect ceiling is unreachable on this tiny curated corpus regardless of judge).
- poison block **1.000** (PASS, unchanged).
- One mandatory class (`rollback_crossing_supersession`) FAILS under the Postgres backend (`branch_had_tokyo:false`) — a Postgres-engine behavioral gap, unrelated to embeddings; recorded for reconciliation.

## Latency caveat (honest)

P95 cannot meet 300-400ms in this harness: every search is a fresh `python -m mnemosyne.cli` subprocess (interpreter+import cold-start), and the Postgres+HTTP path additionally pays a real model-inference round-trip per call. Engine-only P95 ~2562ms is still subprocess-dominated. True server-side P95 needs a long-lived server backend, which this harness design does not host.
