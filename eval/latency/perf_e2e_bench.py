#!/usr/bin/env python3
"""P0 end-to-end retrieve() baseline bench (perf lane A, 2026-07-05).

Standalone (stdlib + mnemosyne only). Builds a ``LocalMemoryEngine`` and a
``SqliteEngine`` with synthetic corpora (deterministic seed, fixed texts),
then times warm in-process ``engine.retrieve()`` calls per
(engine, corpus_size, query shape) cell and prints p50/p95 ms.

Shapes:
  * ``shallow`` — ``retrieve(query, deep=False)``: dense + lexical + fuse +
    rerank + MMR + calibrate + budget (the §15 fast path).
  * ``deep``    — ``retrieve(query, deep=True)``: adds the graph PPR channel
    (``graph_ppr``) to the fused set (the deep/graph shape).

Run it in BOTH kernel modes and compare:

    uv run --locked python eval/latency/perf_e2e_bench.py --json out-native.json
    MNEMOSYNE_PURE=1 uv run --locked python eval/latency/perf_e2e_bench.py --json out-pure.json

Conventions follow the existing benches: engine construction as in
``tests/benchmarks/test_retrieval_baselines.py`` (in-memory LocalMemoryEngine,
temp-dir SqliteEngine), seeding through the public ``append_evidence`` path,
and the word-list corpus generator style of that module. Percentiles use the
same index convention as ``mnemosyne.benchmarks.retrieval_latency_benchmark``.

No new env vars: the only environment read is the already-registered
``MNEMOSYNE_PURE`` (reported, never set here) — see CONFIG-DRIFT-CHECKS.md.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[2]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mnemosyne.engine import LocalMemoryEngine  # noqa: E402  (path set above)
from mnemosyne.models import Evidence  # noqa: E402
from mnemosyne.sqlite_engine import SqliteEngine  # noqa: E402

SEED = 20260705
_WORDS = ["postgres", "memory", "belief", "evidence", "tenant", "branch", "vector", "graph"]
TENANT = "perf-baseline"


def _make_texts(rng: random.Random, n: int, words_per_doc: int = 30) -> list[str]:
    """Deterministic fixed texts, same word-distribution style as tests/benchmarks."""
    return [
        f"doc {i}: " + " ".join(rng.choice(_WORDS) + str(rng.randint(0, 500)) for _ in range(words_per_doc))
        for i in range(n)
    ]


def _make_queries(rng: random.Random, n: int) -> list[str]:
    return [" ".join(rng.choice(_WORDS) + str(rng.randint(0, 500)) for _ in range(12)) for _ in range(n)]


def _percentile_ms(samples: list[float], q: float) -> float:
    """Same index convention as mnemosyne.benchmarks.retrieval_latency_benchmark."""
    ordered = sorted(samples)
    if not ordered:
        return 0.0
    return ordered[min(len(ordered) - 1, int(len(ordered) * q))]


def _seed_engine(engine: Any, texts: list[str]) -> float:
    """Seed via the public append_evidence path; returns seed wall time in ms."""
    t0 = time.perf_counter()
    for text in texts:
        engine.append_evidence(
            Evidence(
                tenant_id=TENANT,
                user_id="perf-user",
                actor="user",
                source_type="chat",
                content=text,
                trust_tier=0,
                access_policy={"tenant": TENANT},
            )
        )
    return (time.perf_counter() - t0) * 1000.0


def _bench_cell(engine: Any, queries: list[str], *, deep: bool, calls: int, warmup: int) -> dict[str, Any]:
    for i in range(warmup):
        engine.retrieve(queries[i % len(queries)], tenant_id=TENANT, deep=deep)
    samples: list[float] = []
    for i in range(calls):
        query = queries[i % len(queries)]
        t0 = time.perf_counter()
        engine.retrieve(query, tenant_id=TENANT, deep=deep)
        samples.append((time.perf_counter() - t0) * 1000.0)
    return {
        "calls": calls,
        "warmup": warmup,
        "p50_ms": round(_percentile_ms(samples, 0.50), 3),
        "p95_ms": round(_percentile_ms(samples, 0.95), 3),
        "mean_ms": round(sum(samples) / len(samples), 3),
        "max_ms": round(max(samples), 3),
    }


def _kernel_mode() -> dict[str, Any]:
    from mnemosyne import text as text_kernels

    return {
        "MNEMOSYNE_PURE": os.environ.get("MNEMOSYNE_PURE", ""),
        "native_active": text_kernels.NATIVE is not None,
        "mode": "pure" if text_kernels.NATIVE is None else "native",
    }


def run(sizes: list[int], calls: int, warmup: int, queries_n: int) -> dict[str, Any]:
    rng = random.Random(SEED)
    corpora = {size: _make_texts(rng, size) for size in sizes}
    queries = _make_queries(rng, queries_n)

    results: dict[str, Any] = {
        "bench": "perf_e2e_retrieve_baseline",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "kernel": _kernel_mode(),
        "config": {"sizes": sizes, "calls": calls, "warmup": warmup, "n_queries": queries_n},
        "cells": {},
    }

    for size in sizes:
        texts = corpora[size]

        engines: dict[str, Any] = {"local": LocalMemoryEngine()}
        tmp = tempfile.TemporaryDirectory(prefix=f"mnemo_perf_sqlite_{size}_")
        engines["sqlite"] = SqliteEngine(Path(tmp.name) / "engine")

        for engine_name, engine in engines.items():
            seed_ms = _seed_engine(engine, texts)
            for shape, deep in (("shallow", False), ("deep", True)):
                cell = _bench_cell(engine, queries, deep=deep, calls=calls, warmup=warmup)
                cell["seed_ms"] = round(seed_ms, 1)
                key = f"{engine_name}/{size}/{shape}"
                results["cells"][key] = cell
                print(
                    f"{engine_name:>6} n={size:<6} {shape:<7} "
                    f"p50={cell['p50_ms']:>9.3f} ms  p95={cell['p95_ms']:>9.3f} ms  "
                    f"mean={cell['mean_ms']:>9.3f} ms  (seed {cell['seed_ms']:.0f} ms once)",
                    flush=True,
                )
        engines["sqlite"].close()
        tmp.cleanup()

    return results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sizes", type=int, nargs="+", default=[1000, 10000], help="corpus sizes (default: 1000 10000)")
    ap.add_argument("--calls", type=int, default=30, help="measured retrieve() calls per cell (default 30)")
    ap.add_argument("--warmup", type=int, default=2, help="warm-up calls per cell, unmeasured (default 2)")
    ap.add_argument("--queries", type=int, default=30, help="distinct deterministic queries to cycle (default 30)")
    ap.add_argument("--json", type=Path, default=None, help="write the machine-readable report to this path")
    args = ap.parse_args()

    mode = _kernel_mode()
    print(f"[perf-e2e] kernel mode: {mode['mode']} (MNEMOSYNE_PURE={mode['MNEMOSYNE_PURE'] or 'unset'})", flush=True)
    results = run(args.sizes, args.calls, args.warmup, args.queries)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(results, indent=2))
        print(f"[perf-e2e] JSON -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
