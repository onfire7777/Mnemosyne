# Warm-Server Fast-Path P95 Latency Harness (Postgres real-provider path)

Generated: 2026-06-22T05:14:29.124198+00:00
Blueprint: §15 fast-path P95 NFR, FR-3, §16 SLO

## What this fixes (subprocess-per-query artifact)

- Subprocess/query: ELIMINATED: engine built ONCE per client via cli.build_parser->load_tools->MemoryTools; queries run in-process (no per-query python -m mnemosyne.cli).
- Cold model round-trip/query: ELIMINATED: real embedding service started ONCE on the specified port, models loaded ONCE, warmed before measurement.

## Warm-server setup (paid ONCE, NOT per request)

- Engine build + corpus capture: **1750.02 ms** (once)
- Embedding service start + model load: **13201.05 ms** (once)
- Embedding backend: **sentence-transformers** (REAL model), reranker: **cross-encoder**
- Wired path proved: POST /embed=True, POST /rerank=True (counters: {"GET /health": 2, "POST /embed": 440, "POST /rerank": 208})

## Store / isolation

- Backend: **postgres** (127.0.0.1:54329/mnemosyne), reused running container
- Distinct tenant: **`warm-latency-eval-cae210d7`** -> uuid `ba4b0ff4-44e7-5bd4-b62a-d6159a042719` (prefix `warm-latency-eval`)
- Shared tables truncated: **False** (only this tenant's rows seeded/cleaned)
- Lexical provider: **postgres**, graph provider: **postgres**

## Load

- 8 concurrent clients x 25 queries = **200 calls** (in-process, no subprocess)
- Corpus: 12 docs, 9 unique queries (`eval/datasets/retrieval_curated.json`)
- Throughput: **11.74 qps** over 17035.09 ms wall
- Errors: 0

## Results — warm per-request latency (ms)

| component | P50 | P95 | P99 | mean | max | P95 95% CI |
|---|---|---|---|---|---|---|
| embed_call_only | 174.98 | 250.52 | 298.56 | 182.02 | 348.5 | [235.2171, 269.964] |
| engine_fast_path_total | 491.82 | 606.16 | 686.61 | 494.26 | 704.08 | [578.9686, 661.7001] |
| engine_minus_embed | 311.28 | 442.84 | 512.78 | 312.25 | 523.89 | [410.3101, 463.9505] |

Component meaning:
- **embed_call_only** — isolated warm HTTP round-trip to the real embedding service (model-inference cost), via the production `HttpEmbeddingProvider`.
- **engine_fast_path_total** — one warm in-process `MemoryTools.search()`: the TRUE warm fast path (query embed + dense pgvector search + lexical FTS + RRF fuse + cross-encoder rerank + MMR + calibrate + budget). This is the SLO number. It already INCLUDES its own internal embed/rerank HTTP calls.
- **engine_minus_embed** — `engine - embed` per call: approximate non-embed engine work (SQL retrieve + fuse + rerank orchestration + MMR + calibrate). Transparency only.

## Verdict vs §15/§16 budget (P95 <= 300-400 ms)

**engine_fast_path_total P95 = 606.16 ms -> FAIL (> 400 ms budget) / FAIL (>300 ms)**

- embed_call_only P95 = 250.52 ms (<= 400 ms)
- engine_minus_embed P95 = 442.84 ms

## Honest reading + what would close the gap

Even warm and in-process, the **Postgres fast-path P95 is 606.16 ms** (> 300 ms; > 400 ms) — a genuine end-to-end cost, NOT a subprocess artifact. This is reported honestly against the §15/§16 budget.

Decomposition (real BGE + cross-encoder): isolated **embed call** P95 250.52 ms; **non-embed engine work** (SQL dense+lexical retrieve, RRF, MMR, calibrate, budget) P95 442.84 ms. The full `search()` also re-embeds rerank candidates via the cross-encoder, so engine_total > embed + (single) non-embed in general.

Gap-closers, in priority order:
  1. **Query-embedding cache + persisted doc vectors.** Doc vectors are already written at capture time (pgvector); caching query->vector turns repeat/near-repeat embeds into single-digit-ms cache hits and removes the synchronous model round-trip from the hot path.
  2. **In-process / co-located embedder.** Co-locate BGE-small in the server process (no HTTP/JSON hop); on GPU, query embedding is sub-10 ms vs the measured HTTP round-trip.
  3. **Cross-encoder off the hot path.** Rerank only a small ANN+lexical candidate set (or use a cheaper reranker / cache rerank scores) so model cost scales with N, not corpus size.
  4. **Connection pooling / prepared statements.** Reuse pgvector query plans and pooled connections to shave per-call SQL setup.
