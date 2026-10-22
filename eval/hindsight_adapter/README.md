# Native Hindsight comparison adapter

This adapter imports Hindsight at commit
`0691b504a88480844b2db53384b8c81971b7cf1e` in a separate Python environment. It
uses the upstream `MemoryEngine`, `SyncTaskBackend`, retain extraction,
consolidation, graph, embeddings, fusion and neural reranking. It changes only
the process-local LLM provider factory to call `eval.codex_bridge.complete`
through the existing authenticated Codex CLI. It never reads Codex credentials.
Native reflect/tool calling is deliberately unsupported in this comparison.

The recorded `run-v1` experiment was cancelled at the owner's request during
ingestion. Its temporary database was removed and no comparison score was
produced. This adapter is retained for possible future authorized work; do not
resume that cancelled run. Source changes require a newly prepared manifest
and fresh output directories.

The source archive, virtual environment, model files, database and raw receipts
are local evaluation artifacts. The runtime is under the gitignored
`work/hindsight-comparison/controlled/runtime/`. No global Python environment,
Docker context, or Hindsight configuration is changed. The source archive keeps
Hindsight's MIT license. Its SHA-256 is
`f914adefc7976a50f2925a82caa9135f64676dffe6bea6444b99127c1656591e`.

## Configuration

- PostgreSQL 16 with pgvector and pg_trgm; independent loopback-only container
  `mnemosyne-hindsight-controlled`, port `55433`, Docker context
  `colima-pentestswarm`.
- Local CPU embeddings: `BAAI/bge-small-en-v1.5`.
- Local CPU reranking: `cross-encoder/ms-marco-MiniLM-L-6-v2`.
- Codex `gpt-6-astra`, reasoning `low`, at most three concurrent calls. Each
  bridge invocation makes one CLI attempt; native Hindsight may retry an
  operation. Every invocation has a receipt, including native JSON/schema
  validation status. Temperature and completion token caps are recorded as
  requested but cannot be enforced by this CLI interface.
- Native extraction chunk size **32000 characters**, explicitly changed from
  the upstream 3000-character default to amortize CLI overhead. Full sessions,
  source dates and native prompts are retained. This is a configured comparison,
  not a reproduction of a published vendor score or default deployment.
- Native synchronous consolidation runs before recall. Recall uses the bank's
  default budget, 4096 native fact tokens, default neural reranking, public
  observation preference, and no optional raw chunk expansion.
- Periodic consolidation reconciliation is disabled to prevent a background
  sweep from silently retrying a completed/failed benchmark case. Explicit
  post-retain native consolidation remains enabled.

The frozen runtime fingerprint records package versions, native Python code
hash, exact model revisions/file hashes, database version/extensions, image
digest and adapter settings. Once downloaded, models load from immutable local
snapshot paths. The runner rejects a runtime mismatch before selected inference.
Account quota is consumed; monetary cost is not measured and is recorded null.

## Running

Use the isolated runtime's Python, with the repository as the working directory.
Set `HINDSIGHT_COMPARISON_DSN` to the separate database URL. Bootstrap the native
models/database with `--initialize-only`; its `environment.json` becomes the
frozen environment file. Initialization does not call the LLM.

```sh
work/hindsight-comparison/controlled/runtime/venv/bin/python \
  -m eval.hindsight_adapter.runner \
  --input _scratch/controlled-hindsight/input.json \
  --manifest work/hindsight-comparison/controlled/run-v1/manifest.json \
  --environment work/hindsight-comparison/controlled/hindsight-environment.json \
  --runtime-dir work/hindsight-comparison/controlled/runtime \
  --output-dir work/hindsight-comparison/controlled/run-v1/contexts/hindsight \
  --receipt-dir work/hindsight-comparison/controlled/run-v1/native-receipts/hindsight
```

Input is a list of `question_id`, `question`, `question_date` and `sessions`.
Sessions contain only `session_id`, `date` and `turns`; turns contain only `role`
and `content`. Extra fields, including gold answers and answer-bearing labels,
are rejected. Question IDs remain orchestration metadata; native banks and
document IDs are opaque hashes. Each full session is a document with its real
session date; naive benchmark dates use UTC in both arms.

The runner verifies the common input/configuration/source manifest and its bound
`hindsight_runtime_sha256`. It writes a started marker before inference. A
terminal result can be reused only when its hashes and identity agree; an
interrupted attempt becomes a failed case rather than a silent selective retry.
Backend failures produce failed results and the runner continues to later cases.
Each case has its own receipt directory and known native token-usage aggregate;
failed or interrupted attempts retain their known usage and flag incompleteness.

Returned candidates preserve native rank, text and temporal metadata. The common
comparison runner subsequently applies the same context cap and reader/judge
to both arms. Full native responses and timing/provenance remain in local
receipts. A successful transport with invalid extraction JSON is not counted as
a successful native extraction.

Run the adapter's no-network contract checks with:

```sh
work/hindsight-comparison/controlled/runtime/venv/bin/python \
  -m unittest eval.hindsight_adapter.test_adapter
```
