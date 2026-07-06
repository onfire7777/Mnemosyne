# P0 Perf Baseline — 2026-07-05 (lane A)

Pre-change numbers every later perf lane is judged against. Branch `perf/runtime-and-kernels` @ base `ee30b5b`. Machine: macOS-26.5-arm64-arm-64bit-Mach-O, Python 3.13.13.

Machine-readable twin: [`perf-baseline-20260705.json`](perf-baseline-20260705.json).

## 1. Micro benches (`tests/benchmarks --benchmark-only`), mean per round

The three pure baselines call the `_*_pure` bodies directly and the `native_*` benches call `mnemosyne_native` directly, so both columns measure the same kernels — `MNEMOSYNE_PURE` flips only the *dispatchers* (visible in the e2e section, not here). Differences between columns are run-to-run noise.

| bench | native run (us) | MNEMOSYNE_PURE=1 run (us) |
|---|---|---|
| test_bench_cosine_1024 | 31.9 | 31.4 |
| test_bench_hashing_embedding_cold | 78.2 | 74.8 |
| test_bench_lexical_scan_2k | 50,766.8 | 52,056.7 |
| test_bench_native_lexical_scan_2k | 1,147.4 | 1,231.8 |
| test_bench_native_hashing_embedding_cold | 15.3 | 15.8 |
| test_bench_native_dense_scan_2k_256d | 3,247.4 | 3,771.3 |
| test_bench_native_dense_scan_prepacked | 197.9 | 349.8 |
| test_bench_sqlite_dense_scan_end_to_end | 386.6 | 445.6 |

Headline kernel ratios (this capture): pure lexical_scan_2k ~50.8 ms vs native ~1.15 ms (~44x); pure-body hashing_embedding ~78 us vs native ~15 us (~5.1x); dense list-FFI seam ~3.2 ms vs prepacked kernel ~0.20 ms vs sqlite packed-BLOB end-to-end ~0.39 ms.

## 2. E2E `engine.retrieve()` p50/p95 (ms) — warm, in-process

`eval/latency/perf_e2e_bench.py`, seed 20260705, 30 calls/cell after 2 warm-ups. `shallow` = fast path (`deep=False`); `deep` adds the graph-PPR channel.

| engine | corpus | shape | native p50 | native p95 | pure p50 | pure p95 |
|---|---|---|---|---|---|---|
| local | 1000 | shallow | 24.072 | 33.082 | 47.833 | 49.49 |
| local | 1000 | deep | 28.259 | 36.15 | 153.419 | 227.474 |
| sqlite | 1000 | shallow | 46.865 | 59.576 | 58.276 | 63.316 |
| sqlite | 1000 | deep | 62.577 | 73.415 | 162.407 | 182.095 |
| local | 10000 | shallow | 345.016 | 484.591 | 906.437 | 1100.452 |
| local | 10000 | deep | 362.667 | 462.251 | 1024.71 | 1147.518 |
| sqlite | 10000 | shallow | 640.184 | 841.097 | 1070.088 | 1173.427 |
| sqlite | 10000 | deep | 788.645 | 1007.577 | 1319.823 | 1504.668 |

One-time corpus build cost (`seed_ms`, public `append_evidence` path, native run): local/1000 96 ms; sqlite/1000 724 ms; local/10000 3125 ms; sqlite/10000 40574 ms.

## 3. Cold start (`python -X importtime`, median of 3)

| import | median total (sum of self, ms) | runs (ms) |
|---|---|---|
| `mnemosyne.mcp_server` | 112.6 | 204.1, 110.2, 112.6 |
| `mnemosyne.cli` | 65.9 | 194.2, 65.9, 53.3 |

Top-5 importtime contributors for `mnemosyne.mcp_server` (median run):

| by self time | ms | by cumulative | ms |
|---|---|---|---|
| `mnemosyne.models` | 4.6 | `mnemosyne.mcp_server` | 107.5 |
| `mnemosyne.workspace` | 4.0 | `mnemosyne.engine` | 37.3 |
| `mnemosyne.retrieval` | 3.9 | `asyncio` | 22.9 |
| `mnemosyne.consolidation` | 3.5 | `mnemosyne.algorithms` | 20.7 |
| `cryptography.hazmat.bindings._rust` | 2.8 | `mnemosyne.retrieval` | 20.5 |

Self-time is flat (no single hot module >5 ms): mcp_server cold import cost is spread across ~290 modules, dominated by the mnemosyne package graph itself (engine 37 ms cumulative) plus asyncio. Run-1 of each triple was FS-cache-cold (~194-204 ms) — medians absorb it.

## Method notes

- Micro: tests/benchmarks --benchmark-only, run once per mode. The three pure baseline benches (cosine_1024 / hashing_embedding_cold / lexical_scan_2k) call the _*_pure bodies DIRECTLY, so they measure the pure kernels in both modes by design; the native_* benches call mnemosyne_native directly in both modes. MNEMOSYNE_PURE only flips the dispatchers, which the e2e bench (not the micro benches) exercises. Units: microseconds (mean over rounds).
- E2E: eval/latency/perf_e2e_bench.py: warm in-process engine.retrieve() over synthetic corpora (seed 20260705), 30 measured calls per cell after 2 warm-ups, 30 distinct queries cycled. shallow = deep=False fast path; deep = deep=True adds graph PPR. seed_ms is the one-time public append_evidence corpus build, not a per-call cost. Units: milliseconds.
- Cold start: uv run --locked python -X importtime -c 'import <module>', 3 runs each; total = sum of all importtime self-times per run (ms); median across runs. Run 1 of each triple was FS-cache-cold and visibly slower - the median absorbs it. top5 lists are from the median-total run.
