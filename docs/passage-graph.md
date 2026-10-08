# Passage graph (HippoRAG 2): how Mnemosyne ranks memories with local models

Mnemosyne can rank source passages with the HippoRAG 2 recipe: an LLM extracts facts
(OpenIE triples) from every passage once, an embedding model embeds passages, facts and
entity phrases, and a query is answered by Personalized PageRank seeded with the facts
closest to the question. This is what lets a two-hop question ("When did Lothair II's
mother die?") reach the passage about the mother, which never names Lothair II.

It is off unless configured. When it is configured:

- `query_mode=passages` returns the graph ranking alone (what the benchmarks measure);
- ordinary `search` and `deep_search` rank source passages with the graph too, and fuse them
  with facts, preferences, summaries, working memory and intentions from the other channels.
  Extracted facts get at most `top_k / 4` result slots, and the hashing dense channel, the local
  hashing reranker, MMR and activation no longer re-sort the passages;
- a long-running MCP server indexes every new capture or ingest in a background thread
  (debounced by a second), so a new memory joins the graph within seconds. Until it does, BM25
  finds it.

If a model is down or slow, search falls back to BM25 (`explain.passage_graph.fallback`) and a
capture never fails; `/healthz` reports `passage_graph` with the last indexing run and error.
Without the graph, every path behaves exactly as before.

## What it is, and what it is not

- An **index of what passages say**, kept in a SQLite sidecar next to the store. Triples
  never become assertions, never pass the promotion gate and are never returned as hits.
- It only **reorders passages the caller may already read**: the graph is rebuilt from the
  engine's authorized passage set (`passage_candidates`) for every scope, so tenant
  isolation, access policy and redaction apply unchanged.
- Passages above the disclosure ceiling (sensitivity > 1, or `embedding_partition=none`) are
  never sent to a model; they are still found, by BM25, and merged into the ranking.
- `forget` purges a passage's triples and vector, and every fact or entity vector no other
  passage of the tenant still derives (`passage_index_purge` in the forget report).

## Configure

Any OpenAI-compatible endpoints work. Our runs use local Ollama, so nothing leaves the
machine:

```
MNEMOSYNE_PASSAGE_INDEX=C:\Users\me\MnemetricData\passage-index.sqlite
MNEMOSYNE_PASSAGE_CHAT_URL=http://127.0.0.1:11434/v1/chat/completions
MNEMOSYNE_PASSAGE_CHAT_MODEL=qwen3:4b-instruct
MNEMOSYNE_PASSAGE_EMBEDDING_URL=http://127.0.0.1:11434/v1/embeddings
MNEMOSYNE_PASSAGE_EMBEDDING_MODEL=qwen3-embedding:8b
MNEMOSYNE_PASSAGE_EMBEDDING_DIMS=1024
# optional: one extra chat call per query that drops linked facts which do not help
MNEMOSYNE_PASSAGE_RECOGNITION_FILTER=1
```

Each has a `--passage-...` flag. A hosted endpoint needs `--passage-chat-api-key-env NAME`
(the name of the variable holding the key, never the key itself). Install numpy with the
`graph` extra: `uv sync --extra graph`.

Ollama: `ollama pull qwen3:4b-instruct` and `ollama pull qwen3-embedding:8b`. Set
`OLLAMA_NUM_PARALLEL=8` so OpenIE requests run eight at a time (models of the `qwen35`
architecture do not support parallel requests; `qwen3` does).

## Index, then query

```
mneme index-passages --tenant T          # OpenIE + embeddings for new passages only
mneme --evaluation-read-only eval-query-batch --input-jsonl q.jsonl --retrieval-mode passages
```

From Python, `MemoryTools.search(tenant, query, query_mode="passages")`.

Indexing is incremental and keyed by evidence CID: only passages never seen before cost a
model call. The public HippoRAG adapter runs `index-passages` after `capture-batch`; it is a
no-op when no index is configured.

## Ranking

The five facts nearest the question (fact-instruction query embedding) seed their subject
and object entities, each weighted by the fact's min-max normalised score divided by how
many passages mention the entity; every passage is also seeded with its min-max dense score
times 0.05; PageRank damping 0.5 - all HippoRAG 2's values. Two differ, both chosen on a
2Wiki development split (never on held-out data): synonym edges join entity phrases at
cosine >= 0.95 (HippoRAG 2: 0.8, which with qwen3-embedding joined ~17 phrases per entity
and diluted the walk), and the final score adds 0.1 x the min-max dense score to the min-max
PageRank score. Without linked facts the route falls back to dense passage scores.

Optional, one chat call per query each: `--passage-recognition-filter` drops linked facts
that do not help the question; `--passage-rerank-top N` lets the chat model reorder the top
N passages.

## Results (7-8 Oct 2026, this PC: i9-9900K, RTX 3080 10 GB, local Ollama)

Every setting was chosen on a 2Wiki development split built from 2WikiMultihopQA dev
questions outside the HippoRAG sample (`_scratch/recall90/prepare_dev.py`: 400 questions,
2,771 passages). The three held-out HippoRAG samples (1,000 questions each) were scored only
with those fixed settings, through the public adapter end to end (capture-batch with
consolidation, index-passages, eval-query-batch). HotpotQA and MuSiQue were never tuned on.
Raw reports: `C:\Users\Onfire\MnemetricData\runs\final-*.json`.

2Wiki development split (recall@5): BM25 0.665, dense (qwen3-embedding:8b) 0.761, passage
graph 0.914, passage graph + `--passage-rerank-top 10` 0.932.

Held-out, recall@5 (95% bootstrap interval) and recall@2:

| Held-out set | passages | BM25 passages | passage graph | graph + rerank top 10 | recall@2 (graph + rerank) |
|---|---:|---:|---:|---:|---:|
| 2Wiki | 6,119 | 0.664 | 0.880 (0.867-0.892) | **0.917 (0.906-0.927)** | 0.766 |
| HotpotQA | 9,811 | 0.728 | 0.882 (0.867-0.897) | **0.935 (0.924-0.945)** | 0.808 |
| MuSiQue | 11,656 | 0.428 | 0.619 (0.600-0.638) | **0.667 (0.649-0.686)** | 0.475 |

Before this work the 2Wiki suite scored 0.140. The graph alone generalised less well than the
dev split suggested (0.914 -> 0.880 on 2Wiki); the rerank of the top ten passages by the chat
model is what carries 2Wiki and HotpotQA over 0.90. MuSiQue (two to four hops) stays far
below; it needs a second retrieval hop.

Cost: OpenIE ran at about one passage a second on the local GPU (qwen3:4b-instruct, eight
parallel requests, about 10 triples per passage): 90 minutes for 2Wiki, about four hours
each for HotpotQA and MuSiQue including embeddings. It is paid once per passage and kept in the
index.

## Acceptance status against `recall-90-fix-prompt.md`

- Recall@5 >= 0.90: met on 2Wiki and HotpotQA with the rerank; not met on MuSiQue.
- Whole suite <= 600 s: met for 2Wiki without the rerank (253 s); not met with it (612 s), nor
  for HotpotQA (801 s / 1,176 s) or MuSiQue (614 s / 956 s), where capture with
  consolidation and the index check alone take 300-545 s.
- Query latency p50 <= 100 ms / p95 <= 300 ms: not measured per query. Batch averages, including
  process start and graph build, are 0.16-0.27 s per question for the graph and 0.52-0.65 s
  with the rerank.
- Reproducibility: two 2Wiki runs gave identical recall@5 (0.87975 and 0.917); the graph run's
  recall@2 moved by 0.0005 (0.65575 -> 0.65625) after queries switched to batched embedding,
  which changes floating-point ties. Byte-identical metrics across shard sizes are not shown.
- Scorer peak memory: not measured.
- Self-generation rolling budget: not done; only source-backed summaries are exempt.
