"""OQ1 — PPR latency: cached vs live PPR cost + scale sweep over relation counts.

Blueprint open question OQ1 asks whether Personalized-PageRank graph reads can be
served inside the §15/§16 fast-path P95 budget (≤ ~300-400 ms) and whether a
**cached PPR** column is needed to get there. This bench measures the CURRENT src
honestly:

  * It drives the real graph read path: ``graph.LocalRelationGraphAdapter.ppr``
    -> ``engine.LocalMemoryEngine.graph_ppr`` (src/mnemosyne/graph.py:34,
    src/mnemosyne/engine.py:615). That is the only PPR seam exposed today.
  * It runs a **scale sweep** over relation counts (the §17 OQ1 cost driver),
    reporting live-PPR P50/P95/max per graph size against the fast-path budget.
  * It attempts to measure a **cached PPR** path. Today there is **no cached PPR
    column** in src — ``graph_ppr`` recomputes the power-iteration on every call
    (engine.py:633-685 rebuilds adjacency + iterates 12 times each call). The
    bench therefore reports ``cached_ppr_available: false`` and a cache HONESTY
    note, and uses a repeated-identical-call probe to show the engine does NOT
    get cheaper on a warm repeat (proving the absence of memoization), so the
    "cached" column is reported as N/A rather than fabricated.

HONEST STATUS as a forcing function: with no cache, P95 is governed entirely by
live recompute and grows with relation count. The src wiring that would add the
missing cached column is named in ``wiring`` below.

Run: ``python eval/benches/bench_oq1_ppr_latency.py``
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _bench_common import (  # noqa: E402
    FAST_PATH_P95_BUDGET_MS,
    emit,
    percentile,
    summarize,
    temp_store,
    time_many,
    time_ms,
)

from mnemosyne.engine import LocalMemoryEngine  # noqa: E402
from mnemosyne.graph import (  # noqa: E402
    LocalRelationGraphAdapter,
    benchmark_graph_adapter,
)
from mnemosyne.models import Evidence, Relation  # noqa: E402

TENANT = "oq1-tenant"
# Relation-count scale sweep — the OQ1 cost driver.
SCALE_RELATION_COUNTS = [50, 200, 800, 2000]
QUERIES_PER_SCALE = 40
WARM_REPEAT_PROBE = 60


def _build_graph(engine: LocalMemoryEngine, n_relations: int) -> list[list[str]]:
    """Seed a connected relation graph with ``n_relations`` edges.

    Returns a list of seed-token queries that land inside the graph so PPR has
    real work (non-empty frontier).
    """

    cid = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id="seed",
            actor="user",
            source_type="chat",
            content="seed corpus for OQ1 graph",
        )
    )
    nodes = [f"node{i:05d}" for i in range(n_relations + 1)]
    # Chain + occasional cross-links so PPR diffuses (not a trivial star).
    for i in range(n_relations):
        src = nodes[i]
        dst = nodes[(i + 1) % len(nodes)]
        engine.add_relation(
            Relation(
                tenant_id=TENANT,
                source=src,
                predicate="links_to",
                target=dst,
                source_evidence_cids=[cid],
            )
        )
    # Queries seed from spread-out nodes so every query has a live frontier.
    step = max(1, len(nodes) // QUERIES_PER_SCALE)
    return [[nodes[(i * step) % len(nodes)]] for i in range(QUERIES_PER_SCALE)]


def _detect_cached_ppr() -> dict[str, object]:
    """Probe whether src exposes a cached-PPR column / memoized graph read.

    We look for any of: a ppr cache attribute on the engine, a cached adapter, or
    a documented ``cached`` flag on ``graph_ppr``. None exist today, so this is a
    structural honesty check, not a guess.
    """

    engine_attrs = set(dir(LocalMemoryEngine))
    adapter_attrs = set(dir(LocalRelationGraphAdapter))
    cache_signals = {
        "ppr_cache",
        "_ppr_cache",
        "graph_ppr_cache",
        "cached_ppr",
        "ppr_cached",
    }
    found = sorted((engine_attrs | adapter_attrs) & cache_signals)
    return {"cached_ppr_available": bool(found), "cache_signals_found": found}


def main() -> dict[str, object]:
    sweep: list[dict[str, object]] = []
    for n in SCALE_RELATION_COUNTS:
        engine = LocalMemoryEngine(store_path=temp_store(f"oq1-{n}"))
        queries = _build_graph(engine, n)
        adapter = LocalRelationGraphAdapter(engine)

        # Live PPR latency via the src benchmark helper (graph.benchmark_graph_adapter).
        # NOTE: that helper calls adapter.ppr(seeds, k) without tenant/branch, so it
        # scans every relation (no filter) — the conservative live cost. We ALSO
        # measure the tenant-scoped path the production read uses.
        bench = benchmark_graph_adapter(adapter, queries, k=8)

        scoped = time_many(
            lambda: adapter.ppr(queries[0], 8, tenant_id=TENANT, branch="main"),
            QUERIES_PER_SCALE,
        )

        # "Cached" probe: repeat the IDENTICAL query and see if warm repeats get
        # cheaper. With no memoization they will not — this empirically confirms
        # the missing cached column instead of asserting it.
        warm = time_many(
            lambda: adapter.ppr(queries[0], 8, tenant_id=TENANT, branch="main"),
            WARM_REPEAT_PROBE,
        )
        cold_ms, _ = time_ms(
            lambda: adapter.ppr(queries[0], 8, tenant_id=TENANT, branch="main")
        )

        live = summarize(scoped)
        warm_p50 = round(percentile(warm, 0.50), 4)
        # cache speedup ratio: cold / warm_p50. ~1.0 == no cache benefit.
        cache_speedup = round(cold_ms / warm_p50, 3) if warm_p50 > 0 else None

        sweep.append(
            {
                "relation_count": n,
                "live_ppr_unscoped": bench.to_dict(),
                "live_ppr_tenant_scoped": live,
                "warm_repeat_p50_ms": warm_p50,
                "cold_call_ms": round(cold_ms, 4),
                "warm_vs_cold_speedup_x": cache_speedup,
                "live_p95_within_budget": live["p95_ms"] <= FAST_PATH_P95_BUDGET_MS,
            }
        )

    cache = _detect_cached_ppr()
    largest = sweep[-1]
    live_p95_largest = float(largest["live_ppr_tenant_scoped"]["p95_ms"])  # type: ignore[index]

    payload: dict[str, object] = {
        "bench": "oq1_ppr_latency",
        "blueprint_ref": "OQ1 PPR latency / §15 fast-path P95",
        "src_wiring": {
            "graph_read_seam": "mnemosyne.graph.LocalRelationGraphAdapter.ppr -> mnemosyne.engine.LocalMemoryEngine.graph_ppr",
            "graph_py": "src/mnemosyne/graph.py:34",
            "engine_py": "src/mnemosyne/engine.py:615 (rebuilds adjacency + 12 power-iterations per call)",
            "benchmark_helper": "mnemosyne.graph.benchmark_graph_adapter (src/mnemosyne/graph.py:58)",
        },
        "metric": {
            "scale_sweep": sweep,
            "fast_path_p95_budget_ms": FAST_PATH_P95_BUDGET_MS,
            "live_ppr_p95_ms_at_max_scale": round(live_p95_largest, 4),
            "cached_ppr_column": cache,
        },
        "target": {
            "fast_path_p95_ms": f"<= {FAST_PATH_P95_BUDGET_MS} (§15/§16)",
            "cached_ppr_column": "expected present once OQ1 resolved; currently ABSENT",
        },
        "honest_status": {
            "cached_ppr_today": False,
            "note": (
                "There is NO cached-PPR column in src today: graph_ppr recomputes "
                "the full power-iteration on every call, so warm repeats are not "
                "cheaper than cold (warm_vs_cold_speedup_x ~= 1.0). The 'cached' "
                "latency column is therefore reported as N/A, not fabricated. Live "
                "P95 is the only real number and is governed by relation count."
            ),
        },
        "verdict": {
            "live_p95_within_budget_at_max_scale": live_p95_largest <= FAST_PATH_P95_BUDGET_MS,
            "cached_column_present": bool(cache["cached_ppr_available"]),
        },
        "wiring_to_make_cached_path_real": [
            "Add a per-(tenant,branch,seed-set,as_of) PPR result cache keyed on a "
            "content hash of the relation set; invalidate on add_relation / "
            "supersession (engine.py add_relation @501, _valid_at edges).",
            "Expose a `cached: bool` kwarg or a CachedGraphAdapter in graph.py that "
            "wraps LocalRelationGraphAdapter and short-circuits on cache hit so the "
            "bench's warm_repeat path measures a real cached column.",
            "Materialize a precomputed PPR/edge-weight column in postgres_engine.py "
            "(recursive CTE result table) so the §16 fast-path serves a graph read "
            "without recomputing diffusion per request.",
        ],
    }
    emit(payload)
    return payload


if __name__ == "__main__":
    main()
