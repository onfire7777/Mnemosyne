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
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
EVAL_DIR = HERE.parents[1]
REPO_ROOT = HERE.parents[2]
LATENCY_WARM_DIR = EVAL_DIR / "latency_warm"
for p in (str(HERE.parent), str(LATENCY_WARM_DIR), str(REPO_ROOT / "src"), str(EVAL_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import bench  # noqa: E402  the module under test

CAP006_SCHEMA = "mnemosyne.cap006.latency-receipt/v1"
WARM_REPORT = HERE.parent / "reports" / "phase15-s4-warm.json"
CONCURRENT_REPORT = HERE.parent / "reports" / "phase15-s4-concurrent.json"
LATEST_JSON = HERE.parent / "reports" / "latency_bench_latest.json"
WARM_LATEST_JSON = LATENCY_WARM_DIR / "reports" / "warm_latency_latest.json"


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


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_canonical(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _assert_receipt_abi(receipt: dict, *, distribution: str, declared_concurrency: int) -> None:
    assert receipt["schema"] == CAP006_SCHEMA
    assert receipt["receipt_class"] == "synthetic-development"
    assert receipt["official_claim"] is False
    assert receipt["admitted_measurement"] is False
    assert receipt["claim_status"] == "synthetic-development-receipt-only"
    identity = receipt["identity"]
    assert isinstance(identity["repository_sha"], str) and len(identity["repository_sha"]) == 40
    assert isinstance(identity["clean_tree"], bool)
    assert isinstance(identity["command"], list) and identity["command"]
    assert isinstance(identity["arguments"], dict)
    assert identity["utc_start"]
    assert identity["utc_end"]
    assert identity["monotonic_end"] >= identity["monotonic_start"]
    host = identity["host"]
    for field in ("os", "os_release", "kernel", "architecture", "cpu_flags", "accelerator", "runtime_versions"):
        assert field in host, f"host missing {field}"
    assert isinstance(host["cpu_flags"], list)
    assert isinstance(host["runtime_versions"], dict)
    digests = identity["digests"]
    for field in (
        "dataset",
        "fixture",
        "config",
        "model",
        "tokenizer",
        "provider",
        "container_image",
        "schema",
        "result_contract",
    ):
        assert field in digests, f"digest missing {field}"
        assert isinstance(digests[field], str) and digests[field].startswith("sha256:")
    sut = receipt["sut_boundary"]
    for field in (
        "included_processes",
        "containers",
        "databases",
        "proxies",
        "caches",
        "indexes",
        "filesystems",
        "background_workers",
        "benchmark_process_count",
        "host_workload_count",
    ):
        assert field in sut, f"sut_boundary missing {field}"
    assert sut["benchmark_process_count"] == 1
    assert sut["host_workload_count"] == 1
    workload = receipt["workload"]
    assert workload["order"], "workload order must be bound"
    assert workload["order"] == sorted(workload["order"], key=workload["order"].index)
    assert workload["order_digest"].startswith("sha256:")
    assert _sha256_canonical(workload["order"]) == workload["order_digest"].removeprefix("sha256:")
    warmup = workload["warmup"]
    assert warmup["explicit"] is True
    assert warmup["count"] >= 1
    assert warmup["excluded_from_distribution"] is True
    assert len(warmup["operation_ids"]) == warmup["count"]
    concurrency = receipt["concurrency"]
    assert concurrency["declared_max_in_flight"] == declared_concurrency
    assert concurrency["observed_max_in_flight"] >= 1
    assert "declared_overlap" in concurrency
    assert "observed_overlap" in concurrency
    assert isinstance(concurrency["overlap_evidence"], list)
    assert "matches_declaration" in concurrency
    assert concurrency["worker_count"] >= 1
    assert concurrency["total_model_request_count"] >= 0
    resources = receipt["resources"]
    for sample in (resources["before"], resources["after"]):
        for field in (
            "total_memory_bytes",
            "free_memory_bytes",
            "available_memory_bytes",
            "swap_bytes",
            "process_rss_bytes",
            "process_pss_or_working_set_bytes",
            "vram_bytes",
            "disk_bytes",
            "network_bytes",
            "load_averages",
            "cpu_seconds",
        ):
            assert field in sample, f"resource sample missing {field}"
    assert resources["during"], "resource samples during the run are required"
    for sample in resources["during"]:
        assert "sampled_monotonic" in sample
        assert sample["sampled_monotonic"] >= identity["monotonic_start"]
        assert sample["sampled_monotonic"] <= identity["monotonic_end"]
    assert "memory_pressure" in resources
    assert "swap_pagefile_delta" in resources
    assert "disk_index_growth" in resources
    assert "first_abort" in resources
    assert concurrency["total_model_request_count"] == 0
    assert "cap006-synthetic" not in identity["command"]
    command_leaf = Path(str(identity["command"][-1])).name
    assert command_leaf in {"bench.py", "bench_concurrent.py", "bench_warm.py"}
    observations = receipt["observations"]
    assert observations, "per-request observations are required"
    previous_issue = None
    for obs in observations:
        for field in ("op_id", "issue_monotonic", "start_monotonic", "end_monotonic"):
            assert field in obs, f"observation missing {field}"
        assert obs["issue_monotonic"] <= obs["start_monotonic"] <= obs["end_monotonic"]
        if previous_issue is not None:
            assert obs["issue_monotonic"] >= previous_issue
        previous_issue = obs["issue_monotonic"]
        assert obs["outcome"] in {"success", "timeout", "error"}
        assert "excluded" in obs
        assert "excluded_reason" in obs
    denominators = receipt["denominators"]
    assert denominators["issued"] == len(observations)
    assert denominators["successes"] + denominators["timeouts"] + denominators["errors"] == denominators["issued"]
    assert denominators["failed_remain_in_denominator"] is True
    assert denominators["slow_samples_retained"] is True
    rows = receipt["distributions"]
    assert len(rows) == 1
    assert rows[0]["name"] == distribution
    assert rows[0]["sample_count"] >= 1
    assert rows[0]["official_claim"] is False
    assert rows[0]["asserted"] is False
    for stat in ("p50_ms", "p95_ms", "p99_ms", "throughput_qps", "confidence_interval"):
        assert stat in rows[0], f"distribution missing {stat}"
    raw = receipt["raw_artifacts"]
    for field in ("observations_sha256", "workload_sha256", "result_digest"):
        assert raw[field].startswith("sha256:")
    assert raw["observations_sha256"] == "sha256:" + _sha256_canonical(observations)
    assert raw["workload_sha256"] == "sha256:" + _sha256_canonical(workload)
    complete = json.loads(_canonical_json(receipt))
    complete["raw_artifacts"].pop("result_digest", None)
    assert raw["result_digest"] == "sha256:" + _sha256_canonical(complete)
    rewritten = json.loads(_canonical_json(receipt))
    rewritten["identity"]["repository_sha"] = "0" * 40
    rewritten["raw_artifacts"].pop("result_digest", None)
    assert raw["result_digest"] != "sha256:" + _sha256_canonical(rewritten)


def test_cap006_abi_helpers_exist():
    for name in (
        "RECEIPT_SCHEMA",
        "DISTRIBUTION_WARM_SERIAL",
        "DISTRIBUTION_CONCURRENT",
        "pinned_workload",
        "execute_pinned_workload",
        "write_phase15_s4_receipt",
    ):
        assert hasattr(bench, name), f"bench.py is missing CAP-006 helper {name}"
    assert bench.RECEIPT_SCHEMA == CAP006_SCHEMA
    assert bench.DISTRIBUTION_WARM_SERIAL == "warm-serial"
    assert bench.DISTRIBUTION_CONCURRENT == "concurrent"


def test_pinned_workload_order_is_deterministic():
    first = bench.pinned_workload()
    second = bench.pinned_workload()
    assert first["order"] == second["order"]
    assert first["order"]
    assert first["order"] == [op["op_id"] for op in first["operations"]]
    assert first["order_digest"] == "sha256:" + _sha256_canonical(first["order"])
    assert len(first["operations"]) >= 2


def test_warm_serial_receipt_binds_identity_warmup_and_hashes():
    receipt = bench.execute_pinned_workload(
        distribution=bench.DISTRIBUTION_WARM_SERIAL,
        declared_concurrency=1,
        warmup_count=2,
        timeout_seconds=1.0,
    )
    _assert_receipt_abi(receipt, distribution="warm-serial", declared_concurrency=1)
    assert receipt["concurrency"]["declared_overlap"] is False
    assert receipt["concurrency"]["observed_overlap"] is False
    assert receipt["concurrency"]["observed_max_in_flight"] == 1
    assert receipt["concurrency"]["matches_declaration"] is True
    warmup_ids = set(receipt["workload"]["warmup"]["operation_ids"])
    measured = [obs for obs in receipt["observations"] if not obs["excluded"]]
    excluded = [obs for obs in receipt["observations"] if obs["excluded"]]
    assert excluded
    assert all(obs["excluded_reason"] == "warmup" for obs in excluded)
    assert {obs["op_id"] for obs in excluded} == warmup_ids
    assert receipt["distributions"][0]["sample_count"] == len(measured)
    assert receipt["validity"]["valid"] is True


def test_failures_remain_in_denominator_and_slow_samples_are_kept():
    receipt = bench.execute_pinned_workload(
        distribution=bench.DISTRIBUTION_WARM_SERIAL,
        declared_concurrency=1,
        warmup_count=1,
        timeout_seconds=0.02,
        inject_outcomes={
            "q_capital_france": "timeout",
            "q_capital_germany": "error",
        },
    )
    outcomes = {obs["op_id"]: obs["outcome"] for obs in receipt["observations"] if not obs["excluded"]}
    assert "timeout" in outcomes.values()
    assert "error" in outcomes.values()
    assert receipt["denominators"]["timeouts"] >= 1
    assert receipt["denominators"]["errors"] >= 1
    assert receipt["denominators"]["issued"] == (
        receipt["denominators"]["successes"]
        + receipt["denominators"]["timeouts"]
        + receipt["denominators"]["errors"]
    )
    latencies = [obs["end_monotonic"] - obs["start_monotonic"] for obs in receipt["observations"]]
    assert max(latencies) >= min(latencies)
    assert receipt["denominators"]["slow_samples_retained"] is True


def test_late_callback_is_timeout_observation_not_runner_hang():
    block_s = 1.0
    timeout_s = 0.03

    def _block(_op: dict) -> None:
        time.sleep(block_s)

    started = time.perf_counter()
    serial = bench.execute_pinned_workload(
        distribution=bench.DISTRIBUTION_WARM_SERIAL,
        declared_concurrency=1,
        warmup_count=1,
        timeout_seconds=timeout_s,
        execute=_block,
    )
    serial_elapsed = time.perf_counter() - started
    assert serial_elapsed < block_s, (
        f"serial runner waited for late callback ({serial_elapsed:.3f}s >= {block_s}s)"
    )
    measured = [obs for obs in serial["observations"] if not obs["excluded"]]
    assert measured
    assert all(obs["outcome"] == "timeout" for obs in measured)
    assert serial["denominators"]["timeouts"] >= len(measured)
    assert all((obs["end_monotonic"] - obs["start_monotonic"]) < block_s for obs in measured)

    started = time.perf_counter()
    concurrent = bench.execute_pinned_workload(
        distribution=bench.DISTRIBUTION_CONCURRENT,
        declared_concurrency=3,
        warmup_count=1,
        timeout_seconds=timeout_s,
        execute=_block,
    )
    concurrent_elapsed = time.perf_counter() - started
    assert concurrent_elapsed < block_s, (
        f"concurrent runner waited for late callback ({concurrent_elapsed:.3f}s >= {block_s}s)"
    )
    concurrent_measured = [obs for obs in concurrent["observations"] if not obs["excluded"]]
    assert concurrent_measured
    assert all(obs["outcome"] == "timeout" for obs in concurrent_measured)
    assert concurrent["denominators"]["timeouts"] >= len(concurrent_measured)


def test_warm_driver_emits_the_same_serial_abi():
    import bench_warm

    assert hasattr(bench_warm, "run_warm_serial_receipt")
    receipt = bench_warm.run_warm_serial_receipt(warmup_count=2, timeout_seconds=1.0)
    _assert_receipt_abi(receipt, distribution="warm-serial", declared_concurrency=1)
    assert receipt["workload"]["order"] == bench.pinned_workload()["order"]


def test_concurrent_driver_records_declared_observed_overlap():
    concurrent_path = HERE.parent / "bench_concurrent.py"
    assert concurrent_path.is_file(), "eval/latency/bench_concurrent.py must exist"
    import bench_concurrent

    receipt = bench_concurrent.run_concurrent_receipt(
        declared_concurrency=3,
        warmup_count=1,
        timeout_seconds=1.0,
    )
    _assert_receipt_abi(receipt, distribution="concurrent", declared_concurrency=3)
    assert receipt["concurrency"]["declared_overlap"] is True
    assert receipt["concurrency"]["observed_overlap"] is True
    assert receipt["concurrency"]["observed_max_in_flight"] == 3
    assert receipt["concurrency"]["matches_declaration"] is True
    assert receipt["validity"]["valid"] is True
    assert receipt["concurrency"]["overlap_evidence"]
    for pair in receipt["concurrency"]["overlap_evidence"]:
        assert len(pair["op_ids"]) == 2
        assert pair["overlap_monotonic"] > 0
    assert receipt["workload"]["order"] == bench.pinned_workload()["order"]


def test_concurrent_latency_excludes_overlap_scaffolding():
    import bench_concurrent

    receipt = bench_concurrent.run_concurrent_receipt(
        declared_concurrency=3,
        warmup_count=1,
        timeout_seconds=1.0,
    )
    measured = [
        obs for obs in receipt["observations"] if not obs["excluded"] and obs["outcome"] == "success"
    ]
    assert measured
    assert max(obs["latency_ms"] for obs in measured) < 15.0
    assert receipt["concurrency"]["observed_overlap"] is True
    assert receipt["concurrency"]["observed_max_in_flight"] == 3
    assert receipt["validity"]["valid"] is True


def test_resource_samples_are_taken_while_requests_are_active():
    def _hold_op(_op: dict) -> None:
        time.sleep(0.03)

    receipt = bench.execute_pinned_workload(
        distribution=bench.DISTRIBUTION_WARM_SERIAL,
        declared_concurrency=1,
        warmup_count=1,
        timeout_seconds=1.0,
        execute=_hold_op,
    )
    measured = [obs for obs in receipt["observations"] if not obs["excluded"]]
    window_start = min(obs["start_monotonic"] for obs in measured)
    window_end = max(obs["end_monotonic"] for obs in measured)
    during = receipt["resources"]["during"]
    assert during
    assert any(window_start <= sample["sampled_monotonic"] <= window_end for sample in during)


def test_swap_bytes_measure_consumption_not_capacity():
    receipt = bench.execute_pinned_workload(
        distribution=bench.DISTRIBUTION_WARM_SERIAL,
        declared_concurrency=1,
        warmup_count=1,
        timeout_seconds=1.0,
    )
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return
    parsed: dict[str, int] = {}
    for line in meminfo.read_text(encoding="utf-8", errors="replace").splitlines():
        name, _, rest = line.partition(":")
        token = rest.strip().split()
        if token:
            parsed[name] = int(token[0]) * 1024
    expected = parsed.get("SwapTotal", 0) - parsed.get("SwapFree", 0)
    assert receipt["resources"]["before"]["swap_bytes"] == expected
    assert receipt["resources"]["before"]["swap_bytes"] <= parsed.get("SwapTotal", 0)


def test_concurrent_receipt_invalid_when_overlap_or_inflight_mismatch():
    import bench_concurrent

    receipt = bench_concurrent.run_concurrent_receipt(
        declared_concurrency=3,
        warmup_count=1,
        timeout_seconds=1.0,
        executor_workers=1,
    )
    assert receipt["concurrency"]["declared_max_in_flight"] == 3
    assert receipt["concurrency"]["observed_max_in_flight"] == 1
    assert receipt["concurrency"]["declared_overlap"] is True
    assert receipt["concurrency"]["observed_overlap"] is False
    assert receipt["concurrency"]["matches_declaration"] is False
    assert receipt["validity"]["valid"] is False
    reasons = receipt["validity"]["invalid_reasons"]
    assert "observed_max_in_flight_mismatch" in reasons
    assert "observed_overlap_mismatch" in reasons


def test_phase15_reports_are_separate_synthetic_receipts():
    assert WARM_REPORT.is_file()
    assert CONCURRENT_REPORT.is_file()
    warm = json.loads(WARM_REPORT.read_text(encoding="utf-8"))
    concurrent = json.loads(CONCURRENT_REPORT.read_text(encoding="utf-8"))
    _assert_receipt_abi(warm, distribution="warm-serial", declared_concurrency=1)
    _assert_receipt_abi(
        concurrent,
        distribution="concurrent",
        declared_concurrency=concurrent["concurrency"]["declared_max_in_flight"],
    )
    assert concurrent["concurrency"]["declared_max_in_flight"] >= 2
    assert warm["distributions"][0]["name"] == "warm-serial"
    assert concurrent["distributions"][0]["name"] == "concurrent"
    assert warm["distributions"][0]["name"] != concurrent["distributions"][0]["name"]
    assert warm["raw_artifacts"]["result_digest"] != concurrent["raw_artifacts"]["result_digest"]
    assert warm["official_claim"] is False
    assert concurrent["official_claim"] is False
    stale_sha = "c3a16b7e0d1e593f6957a291f2ae61cd469a7359"
    assert warm["identity"]["clean_tree"] is True
    assert concurrent["identity"]["clean_tree"] is True
    assert warm["identity"]["repository_sha"] != stale_sha
    assert concurrent["identity"]["repository_sha"] != stale_sha
    for receipt in (warm, concurrent):
        sha = receipt["identity"]["repository_sha"]
        shown = subprocess.check_output(
            ["git", "rev-parse", "--verify", sha],
            cwd=REPO_ROOT,
            text=True,
        ).strip()
        assert shown == sha
        tree = subprocess.check_output(
            ["git", "cat-file", "-p", f"{sha}:eval/latency/bench.py"],
            cwd=REPO_ROOT,
            text=True,
        )
        assert "execute_pinned_workload" in tree
        assert "_execute_with_deadline" in tree


def test_phase15_write_does_not_relabel_historical_latest():
    latest_before = LATEST_JSON.read_bytes() if LATEST_JSON.exists() else None
    warm_latest_before = WARM_LATEST_JSON.read_bytes() if WARM_LATEST_JSON.exists() else None
    receipt = bench.execute_pinned_workload(
        distribution=bench.DISTRIBUTION_WARM_SERIAL,
        declared_concurrency=1,
        warmup_count=1,
        timeout_seconds=1.0,
    )
    target = HERE.parent / "reports" / "phase15-s4-warm.write-test.json"
    try:
        bench.write_phase15_s4_receipt(receipt, target)
        assert target.is_file()
        assert json.loads(target.read_text(encoding="utf-8"))["schema"] == CAP006_SCHEMA
        if latest_before is not None:
            assert LATEST_JSON.read_bytes() == latest_before
        if warm_latest_before is not None:
            assert WARM_LATEST_JSON.read_bytes() == warm_latest_before
        assert target.name != "latency_bench_latest.json"
        assert target.name != "warm_latency_latest.json"
    finally:
        target.unlink(missing_ok=True)


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
