# Passage graph (HippoRAG 2) for `query_mode=passages`

Mnemosyne can rank source passages with the HippoRAG 2 recipe: an LLM extracts facts
(OpenIE triples) from every passage once, an embedding model embeds passages, facts and
entity phrases, and a query is answered by Personalized PageRank seeded with the facts
closest to the question. This is what lets a two-hop question ("When did Lothair II's
mother die?") reach the passage about the mother, which never names Lothair II.

It is off unless configured, and it only changes `query_mode=passages`. Ordinary memory
search, consolidation and capture behave exactly as before.

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
