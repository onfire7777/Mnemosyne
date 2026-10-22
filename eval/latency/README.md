# Latency evaluation

This directory contains local latency diagnostics and synthetic concurrency
receipts. These runs do not establish a memory-accuracy score or a leaderboard
rank. Keep the command, environment, backend, errors, and report together when
comparing results.

## Warm service diagnostic

[`bench.py`](bench.py) loads the curated retrieval corpus from
[`retrieval_curated.json`](../datasets/retrieval_curated.json), builds a warm
`MemoryTools` instance and temporary local store per client, and starts or reuses
one embedding service. Construction, corpus capture, and service startup are
recorded separately from the measured requests. Defaults are eight clients and
25 queries per client.

Run from the repository root with the evaluation environment and service
dependencies installed:

```sh
.venv-eval/bin/python eval/latency/bench.py --clients 8 --queries 25
.venv-eval/bin/python eval/latency/bench.py --force-fallback --clients 2 --queries 4
.venv-eval/bin/python eval/latency/bench.py --reuse-service http://127.0.0.1:8000
```

The launcher prefers `.venv-eval/bin/python` for its service subprocess, falling
back to the invoking interpreter if that environment is absent. Model loading
can take time; `--model-load-timeout` defaults to 600 seconds. Inspect
`embedding_service.backend`, `is_real_model`, and the captured health response:
`--force-fallback` exercises a deterministic encoder and does not measure real
model inference. The force flag applies to a service started by this run; when
reusing a service, its existing backend controls inference.

The local backend now receives the configured retrieval adapters through the
CLI's `load_tools` / `load_engine` path. Environment-configured providers can
therefore affect capture and search, including their network calls and costs.
The separate service selected by `--reuse-service` supplies the standalone
embedding measurement; that option does not configure the engine's adapters.

| Report component | Measured operation |
| --- | --- |
| `embed_call_only` | A separate `HttpEmbeddingProvider.embed(query)` call to the warm service. |
| `engine_only` | An in-process `MemoryTools.search()` call, including any providers used by its configured adapters. |
| `fast_path_total` | The sum of those two measured durations for each sample. |

The standalone embedding result is not passed into `search()`. With an HTTP
embedding adapter configured for the engine, search can embed the query again;
the summed total then includes both calls. Treat this as a component diagnostic,
not an isolated engine CPU measurement or a direct production request trace.
Each client has its own corpus and store, so this run also does not establish
shared-store concurrent-writer safety.

Reports include P50/P95/P99, mean/min/max, bootstrap confidence intervals for
P50/P95, throughput, startup costs, service counters, and errors. The reported
P95 checks use 300 ms and 400 ms thresholds; inspect `n_errors` and the backend
before interpreting those checks. The command writes timestamped JSON and
Markdown under `eval/latency/reports/` and replaces
`latency_bench_latest.json` and `latency_bench_latest.md`. `--json-only` changes
stdout formatting but still writes those files.

## Synthetic concurrency receipts

[`bench_concurrent.py`](bench_concurrent.py) uses the pinned synthetic workload
defined in `bench.py`, with declared concurrency, observed overlap, in-flight
counts, and request timestamps. A receipt is invalid when those observations do
not satisfy its declaration. These are development receipts with zero model
requests, not measured production model performance.

```sh
.venv/bin/python eval/latency/bench_concurrent.py --json-only
.venv/bin/python eval/latency/bench_concurrent.py --emit-phase15-s4
```

The second command writes separate `phase15-s4-warm.json` and
`phase15-s4-concurrent.json` reports without relabeling the historical
`latency_bench_latest.json` report.

## Local retrieval baseline and checks

[`perf_e2e_bench.py`](perf_e2e_bench.py) measures warm `retrieve()` calls on
deterministic synthetic corpora for local and SQLite engines, with shallow and
deep graph retrieval. It records the active native/pure kernel mode so the two
modes can be compared:

```sh
uv run --locked python eval/latency/perf_e2e_bench.py --json out-native.json
MNEMOSYNE_PURE=1 uv run --locked python eval/latency/perf_e2e_bench.py --json out-pure.json
.venv/bin/python -m pytest tests/test_latency_docs_consistency.py -q
.venv/bin/python -m pytest eval/latency/test_latency_bench.py -q
```

The latency bench tests exercise fallback-service smoke checks and receipt
contracts. Passing them verifies those contracts; it does not prove that a
deployment meets the latency thresholds.
