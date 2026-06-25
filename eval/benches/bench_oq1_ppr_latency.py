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
  * It probes for the default-off Postgres cached-PPR seam. Without a Postgres
    DSN this bench still measures the local live recompute path, but reports the
    cached seam as structurally present instead of fabricating a cache latency.
  * Repeated warm calls are still timed, but they are explicitly labelled as
    live recompute repeats. Cached latency must be measured against an explicit
    Postgres cache refresh/read path, not inferred from local warm repeats.

HONEST STATUS as a forcing function: live local P95 is governed by recompute and
grows with relation count. The Postgres cache seam is named in ``wiring`` below,
and DSN-backed cache latency should be measured separately.

Run: ``python eval/benches/bench_oq1_ppr_latency.py``
"""

from __future__ import annotations

import inspect
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
from mnemosyne.postgres_engine import PostgresEngine  # noqa: E402

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

    We look for the default-off Postgres refresh path plus an explicit
    ``use_cache`` flag on ``graph_ppr``. This keeps the local benchmark honest:
    it can say the seam exists without pretending local warm-repeat timings are
    cached reads.
    """

    engine_attrs = set(dir(LocalMemoryEngine))
    postgres_attrs = set(dir(PostgresEngine))
    adapter_attrs = set(dir(LocalRelationGraphAdapter))
    cache_signals = {
        "ppr_cache",
        "_ppr_cache",
        "graph_ppr_cache",
        "cached_ppr",
        "ppr_cached",
        "refresh_graph_ppr_cache",
    }
    graph_params = set(inspect.signature(PostgresEngine.graph_ppr).parameters)
    found = sorted((engine_attrs | postgres_attrs | adapter_attrs) & cache_signals)
    has_default_off_flag = "use_cache" in graph_params
    has_refresh_path = "refresh_graph_ppr_cache" in postgres_attrs
    return {
        "cached_ppr_available": bool(has_default_off_flag and has_refresh_path),
        "cache_signals_found": found,
        "postgres_graph_ppr_use_cache_flag": has_default_off_flag,
        "postgres_refresh_path": has_refresh_path,
        "latency_measured": False,
        "latency_note": (
            "Postgres cached-read latency requires a refreshed Postgres cache path; "
            "local warm repeats are live recompute repeats."
        ),
    }


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
            "cached_ppr_column": (
                "default-off Postgres cache seam expected present; latency requires "
                "DSN-backed cache refresh/read measurement"
            ),
        },
        "honest_status": {
            "cached_ppr_today": bool(cache["cached_ppr_available"]),
            "note": (
                "Local warm repeats still exercise live recompute. The default-off "
                "Postgres cached-PPR seam is detected structurally; cached latency "
                "must be measured only after an explicit Postgres cache refresh/read."
            ),
        },
        "verdict": {
            "live_p95_within_budget_at_max_scale": live_p95_largest <= FAST_PATH_P95_BUDGET_MS,
            "cached_column_present": bool(cache["cached_ppr_available"]),
        },
        "wiring_to_make_cached_path_real": [
            "PostgresEngine.refresh_graph_ppr_cache materializes per-(tenant,branch,seed-set,as_of) PPR hits keyed by a relation-set fingerprint.",
            "PostgresEngine.graph_ppr(..., use_cache=True) reads the refreshed cache only when the fingerprint matches; default graph_ppr remains recursive.",
            "Next benchmark step: run a DSN-backed cache refresh/read timing path instead of treating local warm repeats as cached latency.",
        ],
    }
    emit(payload)
    return payload


if __name__ == "__main__":
    main()
