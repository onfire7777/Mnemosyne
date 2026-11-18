# Opt-in local semantic retrieval

The default `local` providers are unchanged: deterministic offline hashing and
local similarity reranking. Setting a discovery URL or a cached model name alone
does **not** enable discovery. Embedding and reranker selection are independent.

## Enable discovery

For the environment adapter factory and MCP, opt in explicitly:

```sh
MNEMOSYNE_EMBEDDING_PROVIDER=auto \
MNEMOSYNE_RERANKER_PROVIDER=auto \
MNEMOSYNE_LOCAL_EMBEDDING_URL=http://127.0.0.1:8765/v1/embeddings \
MNEMOSYNE_LOCAL_RERANKER_URL=http://127.0.0.1:8766/rerank \
mneme-mcp --store /path/to/dedicated/memory.json
```

The shown URLs are the discovery defaults. Use `MNEMOSYNE_LOCAL_*_URL` for `auto`;
`MNEMOSYNE_EMBEDDING_URL` and `MNEMOSYNE_RERANKER_URL` configure explicit `http`
providers instead. Both the CLI parser and its adapter factory support
`--embedding-provider auto` and `--reranker-provider auto`. Evaluation-read-only
mode disables discovered HTTP embedding caches just as it does explicit HTTP
caches; the ordinary CLI cache scope, TTL and timeout remain caller-controlled.

Embedding discovery first tries `MNEMOSYNE_FASTEMBED_MODEL`, if explicitly named,
through optional FastEmbed with `local_files_only=True`. An unavailable or invalid
cached model falls through to HTTP discovery, never a download retry. Without
NumPy, cached in-process models are skipped; HTTP discovery and the offline
hashing fallback still work in the minimal installation. Quantized indexing
continues to require NumPy. No packages are installed by discovery.

HTTP discovery requests only `GET /health` on the endpoint's origin. It does not
send memory text or issue an inference request. Provision models beforehand and
configure the daemon's own offline policy: a daemon may independently initialize
models inside its health handler; the client cannot enforce that policy remotely.

## Health contract

Return HTTP 200, `Content-Type: application/json`, and a JSON object such as:

```json
{
  "status": "ok",
  "embedding": {
    "model": "your-cached-embedding-model",
    "dimensions": 384,
    "backend": "sentence-transformers"
  },
  "reranker": {
    "model": "your-cached-cross-encoder",
    "backend": "cross-encoder"
  }
}
```

- Embeddings require a nonblank string model, backend `sentence-transformers` or
  `fastembed`, and a positive integer `dimensions` (legacy `dims` is accepted).
  If both width fields exist, they must agree. Strings, booleans, zero, and
  fractional widths are rejected, not coerced or replaced by `1024`.
- Rerankers require a nonblank string model and backend `cross-encoder`. Queries
  are sent without an E5 prefix, and logits are converted to similarity scores.
- `fallback`, `uninitialized`, unknown backends, and generic `{"status":"ok"}`
  pages do not establish semantic capability. Other services can use explicit
  `http` configuration rather than claiming an incompatible discovery contract.
- The health model is sent to the provider and included in the discovered
  adapter name; unrelated explicit-HTTP model/dimension settings cannot replace
  its identity. Health widths describe the semantic model; configured default
  dimensions apply only to hashing fallback.

## Safety and fallback

Only `127.0.0.1`, `localhost`, and `::1` HTTP(S) endpoints are discoverable. Original
URLs are validated before deriving `/health`; userinfo, malformed ports, control
characters, and fragments are rejected. Discovery bounds the health body to
64 KiB and uses a 0.25-second default socket timeout. Discovery failures yield
deterministic hashing and local similarity; reranker fallback reuses the selected
embedding provider.

The discovered `HttpEmbeddingProvider`/`HttpReranker` retains a **loopback-only
transport policy for every inference POST**, including sensitive embeddings,
batches, and per-item batch fallback. Both health and inference requests:

- Require every resolved address to be loopback, revalidate on each request,
  and pin the checked address for the connection. Rebound or mixed
  loopback/nonloopback DNS answers are rejected before sending content.
- Bypass environment/system proxies with a request-local opener, even when
  `http_proxy`/`https_proxy` is set and `no_proxy` is empty.
- Reject all redirects, including same-origin redirects, and retain HTTPS
  certificate and hostname verification.

CLI timeout/cache replacements preserve this policy. Explicit `http` providers
keep their existing proxy and URL-validation behavior; their internal-host
allowlist cannot widen an `auto` provider's loopback-only policy. Inference
transport failures raise an error rather than selecting an unprobed endpoint.
Discovery does not change global openers, environment allowlists, installed
configuration, or stores. A successful health response is capability metadata,
not authentication or an embedding-quality benchmark. The client confines its
own connection; it cannot prevent a local daemon from forwarding content itself.

Use a dedicated store when changing embedding models or widths. Auto selection
can change between starts when service availability changes; it does not migrate
or re-embed stored vectors. Pin an explicit provider for reproducible indexing.

Regression suite (owned ephemeral HTTP servers and fake cached-model loaders;
no personal services or downloaded models):

```sh
.venv/bin/python -m pytest tests/test_local_provider_discovery.py tests/test_local_provider_transport.py tests/test_quantized_vectors.py
```
