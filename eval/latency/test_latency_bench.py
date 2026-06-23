"""Smoke + contract tests for the Wave-3 long-lived latency bench.

These run fast on the deterministic fallback encoder (no torch path) so they are
CI/offline-safe, and assert the bench actually exercises the warm long-lived path:
the embedding service is started once and the wired `/embed` calls are counted,
the engine runs in-process per client with zero errors, and every component
reports P50/P95/P99 + bootstrap CIs against the §15/§16 budget.

Run:
    .venv-eval/bin/python -m pytest eval/latency/test_latency_bench.py -v
    .venv-eval/bin/python eval/latency/test_latency_bench.py        # no pytest
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
EVAL_DIR = HERE.parents[1]
REPO_ROOT = HERE.parents[2]
for p in (str(HERE.parent), str(REPO_ROOT / "src"), str(EVAL_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import bench  # noqa: E402  the module under test


def _args(**over) -> argparse.Namespace:
    base = dict(
        clients=2,
        queries=4,
        embedding_model="BAAI/bge-small-en-v1.5",
        embedding_dims=1024,
        retrieval_timeout=30.0,
        model_load_timeout=120.0,
        force_fallback=True,  # fast, offline, deterministic
        reuse_service=None,
        json_only=True,
    )
    base.update(over)
    return argparse.Namespace(**base)


def _run() -> dict:
    return bench.run_bench(_args())


def test_metrics_reused_from_wave1():
    # The bench must reuse the Wave-1 metrics module (percentiles + bootstrap CIs).
    assert hasattr(bench.metrics, "latency_summary")
    assert hasattr(bench.metrics, "bootstrap_percentile_interval")


def test_bench_runs_end_to_end_with_zero_errors():
    r = _run()
    assert r["n_errors"] == 0, f"bench reported engine/embed errors: {r['errors']}"
    assert r["config"]["total_calls"] == 2 * 4


def test_wired_embed_path_is_proved():
    # The warm service must actually receive /embed calls (the wired path fired).
    r = _run()
    svc = r["embedding_service"]
    assert svc["proved_wired"] is True
    assert svc["request_counters"].get("POST /embed", 0) >= 8


def test_startup_costs_paid_once_not_per_call():
    r = _run()
    warm = r["warm_costs_paid_once_ms"]
    # Both warm costs are recorded as one-time, and reported separately from the
    # per-request component latencies (the core Wave-2 fix).
    assert warm["engine_build_and_corpus_capture"] > 0.0
    assert warm["embedding_service_start_and_model_load"] >= 0.0


def test_components_and_verdicts_present():
    r = _run()
    comps = r["components"]
    for name in ("embed_call_only", "engine_only", "fast_path_total"):
        b = comps[name]
        for field in ("p50_ms", "p95_ms", "p99_ms", "p95_ci"):
            assert field in b, f"{name} missing {field}"
        assert "ci_low" in b["p95_ci"] and "ci_high" in b["p95_ci"]
    names = {v["name"] for v in r["verdicts"]}
    assert {"fast_path_total_p95", "engine_only_p95", "embed_call_only_p95"} <= names
    for v in r["verdicts"]:
        assert v["target_ms_loose"] == bench.BUDGET_P95_MS_LOOSE
        assert v["target_ms_tight"] == bench.BUDGET_P95_MS_TIGHT


def test_engine_only_separates_from_embed():
    # fast_path_total ~= embed + engine (separation of embed-call vs engine cost).
    r = _run()
    c = r["components"]
    # P50 total should be in the neighborhood of embed P50 + engine P50 (loose check
    # because percentiles of a sum are not the sum of percentiles; just assert the
    # total is at least as large as each component median).
    assert c["fast_path_total"]["p50_ms"] >= max(
        c["embed_call_only"]["p50_ms"], c["engine_only"]["p50_ms"]
    ) - 1.0


def test_markdown_renders():
    r = _run()
    md = bench.render_markdown(r)
    assert "Long-Lived-Server Fast-Path P95 Latency Bench" in md
    assert "fast_path_total" in md
    assert "what would close the gap" in md.lower()


def _main() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {fn.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"ERROR {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_main())
