# Wave-3 — Long-Lived-Server Fast-Path P95 Latency Bench

Fixes the **Wave-2 latency measurement artifact** and measures the §15 fast-path
P95 NFR (FR-3 / §16 SLO) the way the SLO actually means it: against a **warm,
long-lived server**, with startup paid once.

- Bench: [`bench.py`](bench.py)
- Reports: [`reports/latency_bench_latest.md`](reports/latency_bench_latest.md) +
  `latency_bench_latest.json` (timestamped copies alongside).
- Smoke test: [`test_latency_bench.py`](test_latency_bench.py)

---

## The Wave-2 artifact this corrects

Wave-2's `eval/harness/suites.py::latency_suite` (and the keystone run in
`eval/reports/KEYSTONE_PROOF.md`) measured latency by spawning a **fresh
`python -m mnemosyne.cli ... search` subprocess per call**. Two costs were thereby
charged to *every single request* that a real server pays **once**:

1. **Subprocess / interpreter + import cold-start** (~200-300 ms/process).
2. **A cold per-call model HTTP round-trip** (on the wired Postgres+HTTP path),
   with no warm-up.

Wave-2 honestly flagged this ("Latency caveat (honest)") — its ~2.5 s "engine-only"
P95 is subprocess-dominated and is **not** comparable to a 300-400 ms fast-path NFR.

## What this bench does instead

Paid **once** (warm, not per request):

- The real embedding service (`services/embedding/app.py`, via the instrumented
  launcher so `/embed` calls are counted) is started **one time** under
  `.venv-eval`; the real `BAAI/bge-small-en-v1.5` + `cross-encoder/ms-marco-MiniLM-L-6-v2`
  models load once. `/health` confirms the backend is `sentence-transformers`
  (REAL), not the deterministic fallback.
- The Mnemosyne engine is built **once** in-process via the exact CLI seam
  (`mnemosyne.cli.load_tools` → `MemoryTools`), and the curated corpus is captured
  once. One warm engine **per concurrent client** (see Concurrency model).

Measured **per request**, under concurrent load (N clients × M queries):

| component | meaning |
|---|---|
| `embed_call_only` | isolated warm HTTP round-trip to the real embedding service for the query, via the production `HttpEmbeddingProvider` adapter — the model-inference cost, separated out |
| `engine_only` | one warm in-process `MemoryTools.search()` — pure engine fast path (hybrid dense+lexical retrieve, RRF fuse, MMR, calibrate, budget). No subprocess, no per-call model round-trip |
| `fast_path_total` | `embed + engine` — the intended long-lived fast path (embed the query, then retrieve) |

Each component reports P50/P95/P99 + a deterministic bootstrap 95% CI (reusing the
Wave-1 `eval/harness/metrics.py`). Verdict is vs the §15/§16 budget (P95 ≤ 300-400 ms).

---

## Run

```bash
# Real warm-server bench (BGE + cross-encoder, models cached in ~/.cache/huggingface)
.venv-eval/bin/python eval/latency/bench.py --clients 8 --queries 25

# Offline / CI: deterministic fallback encoder (no torch path), fast
.venv-eval/bin/python eval/latency/bench.py --force-fallback --clients 4 --queries 8

# Reuse an already-running service instead of starting one
.venv-eval/bin/python eval/latency/bench.py --reuse-service http://127.0.0.1:8000
```

`PYTHONPATH=src` is set automatically by the bench, but exporting it is harmless.
Reports land in `eval/latency/reports/` (timestamped + `*_latest.*`).

Run the smoke test (fast, fallback path, asserts zero errors + wired path proven):

```bash
.venv-eval/bin/python -m pytest eval/latency/test_latency_bench.py -v
# or, no pytest:
.venv-eval/bin/python eval/latency/test_latency_bench.py
```

---

## Current honest result (real warm models, this machine, CPU)

From `reports/latency_bench_latest.*` — 8 clients × 25 queries = 200 warm calls,
embedding backend `sentence-transformers` (REAL), 216 `POST /embed` counted, 0 errors:

| component | P50 | P95 | P99 | vs 400 ms |
|---|---|---|---|---|
| `engine_only` | ~23 ms | **~68 ms** | ~99 ms | **PASS** |
| `embed_call_only` | ~417 ms | **~798 ms** | ~1225 ms | FAIL |
| `fast_path_total` | ~450 ms | **~849 ms** | ~1258 ms | **FAIL** |

Reading (honest):

- **The engine fast path alone meets the NFR** (P95 ~68 ms ≤ 400 ms) once warm and
  in-process. This is the real Wave-2 correction: the multi-second Wave-2
  "engine-only" number was per-process Python startup, **not** the engine.
- **The warm embed call is the dominant cost** (P95 ~800 ms). Even with the model
  loaded once, every query pays a full synchronous model-inference HTTP round-trip;
  under 8-way concurrency on CPU that is ~0.8 s at P95.
- **`fast_path_total` P95 ~849 ms still exceeds the 300-400 ms budget** even warm —
  reported honestly. A per-request synchronous model round-trip on CPU does not fit
  a 300-400 ms fast-path budget.

Numbers vary by hardware (CPU vs GPU/MPS) and concurrency; re-run to refresh.

## What remains to close the latency gap (priority order)

1. **Provider latency mitigation.** The local backend now receives the configured
   retrieval adapters through `cli.load_engine(..., adapters=...)`, and
   `LocalMemoryEngine.vector_search` embeds through `self.adapters.embedding`. The
   remaining fast-path gap is provider cost: a synchronous CPU HTTP model
   round-trip can still dominate P95 unless the deployed provider is low-latency
   or colocated.
2. **Embedding cache** (query→vector, and persist doc vectors at capture): repeat /
   near-repeat queries skip the model entirely → cache-hit P95 of single-digit ms.
3. **In-process + batched model**: co-locate the embedder in the server process (no
   HTTP/JSON hop) and batch concurrent queries into one forward pass; BGE-small
   query embedding is sub-10 ms in-process on a GPU vs the HTTP round-trip here.
4. **ANN prefilter, rerank only top-N**: keep the cross-encoder off the hot path so
   model cost scales with candidate count, not corpus size.

These are measurement findings, not production-evidence claims. Historical reports
under `eval/latency/reports/` preserve the pre-seam wording from the run date; use
this README and the current `bench.py` generator for present-state guidance.

---

## Concurrency model (why one engine per client)

On the local single-file backend, **every `search()` persists runtime metrics** via
atomic-replace to `<store>.runtime.json` (`MemoryTools._record_retrieval` →
`_save_metrics` → `RuntimeState.save`). Concurrent threads sharing one engine race
on that rename (a single-writer property of the local backend — **not** a fast-path
latency cost). A production server avoids it with the concurrent-safe Postgres
runtime state, or per-tenant serialization. To measure the engine fast path
faithfully **without manufacturing single-file write contention**, each client gets
its own warm engine + store + pre-loaded corpus (the same isolation the Wave-1
latency suite uses). The embedding **service** is a single shared, concurrent-safe
server. This mirrors a sharded long-lived deployment.
