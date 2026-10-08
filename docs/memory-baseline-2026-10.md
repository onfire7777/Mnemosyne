# Memory baseline, 8 October 2026

Where Mnemosyne stood before the memory upgrade (local models only: Ollama on an RTX 3080 -
`qwen3:4b-instruct` for OpenIE and rerank, `qwen3-embedding:8b` at 1,024 dimensions). Every
later change is measured against these numbers. Held-out sets are never used to choose a
setting; development splits are.

## 1. BurnOS's own memory (the yardstick that matters most)

45 hand-written questions about the real BurnOS store (765 voice lines, 30 Sep - 6 Oct 2026),
each with the line(s) that answer it. The questions and the store copy stay in
`C:\Users\Onfire\MnemetricData` and are never committed; the harness is `eval/store_recall.py`,
which searches a fresh copy so the real store is never touched.

| Search | recall@5 | facts | events | conversation | overheard | two-hop | time ("yesterday") | abstained | p50 / p95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| default (what BurnOS uses today) | **0.319** | 0.67 | 0.29 | 0.33 | 0.30 | 0.33 | 0.00 | 17 of 45 | 145 / 161 ms |
| passages, BM25 | 0.593 | 0.67 | 0.62 | 0.67 | 0.60 | 0.83 | 0.00 | 6 of 45 | 49 / 64 ms |

No search answers a time question: nothing turns "yesterday" or "on Tuesday" into a date range.

After the default search started ranking with the local passage graph (live indexing, same
questions, same store copy): **recall@5 0.782** (facts 1.00, events 0.94, conversation 0.81,
overheard 0.70, two-hop 0.83, time 0.00), 7 abstentions, p50 / p95 97 / 123 ms. Indexing the
742 lines from scratch took 20 minutes on the local GPU (OpenIE, then embeddings), shared with
another indexing job.

## 2. LongMemEval-S (chat memory, 500 questions, about 50 sessions each)

`eval/longmemeval_recall.py`, in-process, one engine per question as the public adapter does.
The split is fixed by sha256 of the question id: 100 development, 400 held out.

| Search | dev recall@5 | held-out recall@5 |
|---|---:|---:|
| default | 0.566 | 0.561 |
| passages, BM25 | 0.922 | 0.896 |

The 0.281 in `eval/reports/m1.2-longmemeval-retrieval.md` (July 2026) predates the retrieval
integrity fixes (batch-wide provenance, U-curve reordering, wall-clock activation).

## 3. HippoRAG multi-hop (held-out, from `docs/passage-graph.md`)

| recall@5 | BM25 passages | passage graph | graph + rerank top 10 |
|---|---:|---:|---:|
| 2Wiki | 0.664 | 0.880 | 0.917 |
| HotpotQA | 0.728 | 0.882 | 0.935 |
| MuSiQue | 0.428 | 0.619 | 0.667 |

## 4. Where the 2Wiki misses are (development split, `eval/miss_analysis.py`)

400 questions, 984 gold passages; position of each gold passage in the ranking.

| | top 2 | 3-5 | 6-10 | 11-30 | 31-100 | not in top 100 | recall@5 per gold |
|---|---:|---:|---:|---:|---:|---:|---:|
| passage graph | 628 | 257 | 34 | 21 | 8 | 36 | 0.899 |
| + rerank top 10 | 716 | 190 | 13 | 21 | 8 | 36 | 0.921 |

- **Retrieval misses dominate what is left:** 36 gold passages are not in the top 100 at all,
  and 33 of the 35 questions they belong to are *bridge comparison* questions ("whose director
  was born first, film A's or film B's?"). The director's passage never names the film, so only
  a second retrieval step can reach it. This is the case for a second hop.
- **Ranking misses:** 29 gold passages sit at 11-100, out of reach of a top-10 rerank, and 13 at
  6-10 that the rerank did not promote. This is the case for a wider rerank pool.
- By question type, recall@5 after rerank: comparison 1.00, compositional 0.955, inference
  0.90, bridge comparison 0.859.

HotpotQA and MuSiQue development splits are being indexed for the same analysis.

## 5. Measurement added

`eval-query-batch --compact` now reports each query's latency and the query process's peak
resident memory; `_scratch/recall90/run_suite.py` turns them into p50 / p95 per suite.
