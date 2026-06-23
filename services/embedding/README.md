# Mnemosyne Embedding + Cross-Encoder Reranker Service

A standalone HTTP microservice that provides **real dense embeddings** and
**real cross-encoder reranking** to Mnemosyne over the exact contract its
`HttpEmbeddingProvider` / `HttpReranker` adapters speak
(`src/mnemosyne/retrieval.py`).

This is the **FR-3 hybrid-retrieval keystone** (real embeddings + reranker) and
supplies the dense-similarity signal used for **FR-6 calibration inputs**.

- `POST /embed` — real embeddings, batch-capable, projected/padded to Mnemosyne's
  `VECTOR(1024)` dimension.
- `POST /rerank` — real cross-encoder relevance scoring.
- `GET /health` — readiness + active model/backend report.

The service runs **with zero third-party packages** today (stdlib `http.server`
+ a deterministic, contract-correct fallback encoder) so it is runnable and
testable offline right now. Installing `requirements.txt` activates the real
FastAPI + torch model path with no code changes.

---

## Contract (must match Mnemosyne exactly)

### `POST /embed`

Request (single):
```json
{ "input": "text to embed", "model": "optional-model-id" }
```
Request (batch):
```json
{ "input": ["text one", "text two"] }
```

Response (single — consumed by `HttpEmbeddingProvider`):
```json
{ "embedding": [0.0123, -0.0456, ...], "model": "BAAI/bge-small-en-v1.5", "dimensions": 1024 }
```
Response (batch — OpenAI-style):
```json
{ "object": "list", "model": "...", "dimensions": 1024,
  "data": [ { "object": "embedding", "index": 0, "embedding": [ ... ] }, ... ] }
```

Mnemosyne's adapter accepts either `embedding` (compact) or `data[0].embedding`
(OpenAI-style), Matryoshka-truncates / zero-pads to `--embedding-dims` (default
**1024**), L2-normalizes, and **rejects an all-zero vector**. This service always
returns a dense, non-zero vector of exactly `EMBEDDING_SERVICE_DIMS` (default 1024).

### `POST /rerank`

Request:
```json
{ "query": "user query", "documents": ["doc 0", "doc 1", ...], "top_n": 10, "model": "optional" }
```

Response (consumed by `HttpReranker`):
```json
{ "results": [ { "index": 1, "score": 8.42 }, { "index": 0, "score": -3.1 } ], "model": "..." }
```

Mnemosyne accepts `score` or Cohere-style `relevance_score`, sorts by score
descending, and re-projects onto the original hits — so the only semantic
requirement is that more relevant documents receive higher scores.

### `GET /health`
```json
{ "status": "ok",
  "embedding": { "model": "...", "dimensions": 1024, "backend": "sentence-transformers|fallback" },
  "reranker":  { "model": "...", "backend": "cross-encoder|fallback" } }
```

---

## Run

### Now, offline (zero dependencies, deterministic fallback)

```bash
python services/embedding/app.py
# -> serves on http://127.0.0.1:8000  (stdlib http.server)
```

Override host/port/dims via env:
```bash
EMBEDDING_SERVICE_HOST=0.0.0.0 EMBEDDING_SERVICE_PORT=8000 \
EMBEDDING_SERVICE_DIMS=1024 python services/embedding/app.py
```

### Production: real models (FastAPI + torch + sentence-transformers)

```bash
pip install -r services/embedding/requirements.txt
python services/embedding/app.py            # auto-detects FastAPI + uvicorn

# or run under uvicorn directly:
uvicorn app:build_fastapi_app --factory --host 0.0.0.0 --port 8000 \
  --app-dir services/embedding
```

The first request downloads the models from Hugging Face. Pre-warm with
`GET /health`. Models:

| Role        | Default model                              | Env override                 |
|-------------|--------------------------------------------|------------------------------|
| Embedding   | `BAAI/bge-small-en-v1.5` (384-d → 1024)    | `EMBEDDING_SERVICE_MODEL`    |
| Embedding   | `sentence-transformers/all-MiniLM-L6-v2`   | (set the env var to this id) |
| Reranker    | `cross-encoder/ms-marco-MiniLM-L-6-v2`     | `RERANKER_SERVICE_MODEL`     |

The real embedding model emits 384-dim vectors; the service lifts them to
Mnemosyne's 1024-dim space with a **deterministic seeded random projection**
(an information-preserving linear map), then L2-normalizes. Set
`EMBEDDING_SERVICE_DIMS` to match any non-default `--embedding-dims`.

### Docker

```bash
docker build -t mnemosyne-embedding services/embedding
docker run --rm -p 8000:8000 -e EMBEDDING_SERVICE_HOST=0.0.0.0 mnemosyne-embedding
```

---

## Wire it into Mnemosyne

Point Mnemosyne's HTTP retrieval adapters at this service. The endpoints are
`/embed` and `/rerank` on the same host:port.

### Via CLI flags (exact)

```bash
python -m mnemosyne.cli --backend postgres \
  --embedding-provider http --embedding-url http://127.0.0.1:8000/embed \
  --embedding-dims 1024 \
  --reranker-provider http --reranker-url http://127.0.0.1:8000/rerank \
  search --tenant tenant-a --query "preferred database"
```

Optional flags: `--embedding-model`, `--reranker-model` (forwarded as the
request `model` field), `--embedding-api-key`, `--reranker-api-key` (sent as
`Authorization: Bearer ...`).

### Via environment variables

```bash
export MNEMOSYNE_EMBEDDING_PROVIDER=http
export MNEMOSYNE_EMBEDDING_URL=http://127.0.0.1:8000/embed
export MNEMOSYNE_EMBEDDING_DIMS=1024
export MNEMOSYNE_RERANKER_PROVIDER=http
export MNEMOSYNE_RERANKER_URL=http://127.0.0.1:8000/rerank
```

### Deployment smoke check (provider-check)

Mnemosyne's `provider-check` calls `embed(...)` and `rerank(query, [a, b], k=2)`
through these exact adapters and fails closed if the embedding dimension is wrong
or the reranker can't order hits:

```bash
python -m mnemosyne.cli \
  --embedding-provider http --embedding-url http://127.0.0.1:8000/embed --embedding-dims 1024 \
  --reranker-provider http --reranker-url http://127.0.0.1:8000/rerank \
  provider-check
```

---

## Self-test

Boots the service on a free port and asserts the response shapes **and** drives
the real Mnemosyne adapters (`HttpEmbeddingProvider`, `HttpReranker`) end-to-end,
reproducing the `provider-check` flow. Uses the deterministic fallback so it
passes offline with no torch/models:

```bash
python services/embedding/selftest.py
# -> [selftest] ALL CONTRACT CHECKS PASSED (mnemosyne adapter mode)   (exit 0)
```

---

## Real path vs. fallback — what's needed for production

| Path                | Activated by                                  | Embedding                              | Reranker                                   |
|---------------------|-----------------------------------------------|----------------------------------------|--------------------------------------------|
| **Real** (preferred)| `pip install -r requirements.txt` + net access| `BAAI/bge-small-en-v1.5` / MiniLM      | `cross-encoder/ms-marco-MiniLM-L-6-v2`     |
| **Fallback** (now)  | default; no extra deps; offline               | deterministic dense hashed bag-of-tokens| lexical + dense-overlap ordering           |

The fallback is **clearly marked** (`"backend": "fallback"` in `/health`) and is
contract-correct: it returns dense non-zero 1024-dim vectors and ranks relevant
documents above irrelevant ones, so Mnemosyne and the self-test pass immediately.
Force it explicitly (e.g. in CI) with `EMBEDDING_SERVICE_FORCE_FALLBACK=1`.

To go fully real in production you need: the packages in `requirements.txt`
(notably a `torch` wheel for your platform/accelerator) and outbound access to
download the Hugging Face models (or a pre-populated `HF_HOME` cache).
