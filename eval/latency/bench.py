#!/usr/bin/env python3
"""Long-lived-server fast-path P95 latency bench (Wave-3).

Fixes the Wave-2 measurement artifact. Wave-2's `fast_path_latency` suite spawned
a fresh `python -m mnemosyne.cli` subprocess **per call** (paying interpreter +
import cold-start, ~200-300 ms each) and, on the wired Postgres+HTTP path, paid a
**model-inference HTTP round-trip per call** with no warm-up. Both confounds were
documented honestly in `eval/reports/KEYSTONE_PROOF.md` ("Latency caveat") — the
~2.5 s "engine-only" P95 it reported is dominated by per-process startup, NOT by
the engine. That number cannot be compared to the §15/§16 fast-path NFR.

This bench measures the thing the SLO is actually about: **a warm, long-lived
server's per-request fast-path latency**, with startup paid ONCE.

What is paid once (warm), not per call:
  * The real embedding service (`services/embedding/app.py`) is started ONE time in
    `.venv-eval` (torch + sentence-transformers); models load once. We confirm via
    `GET /health` that the REAL backend is live (`sentence-transformers` /
    `cross-encoder`), not the deterministic fallback. If the real models are
    unavailable the bench still runs and labels the backend `fallback`.
  * The Mnemosyne engine is built ONCE in-process via the exact public seam the CLI
    uses (`mnemosyne.cli.load_tools` -> `MemoryTools`), and the curated corpus is
    captured ONCE.

What is measured per call, under concurrent load (N clients x M queries):
  * ``embed_ms``  — a warm HTTP round-trip to the real embedding service for the
    query, via the production ``HttpEmbeddingProvider`` adapter from
    ``src/mnemosyne/retrieval.py``. This is the *isolated embed-call latency* — the
    model-inference cost the §15 fast path must absorb.
  * ``engine_ms`` — one in-process ``MemoryTools.search()`` call: the pure engine
    fast-path latency (hybrid dense+lexical retrieve, fuse, MMR, calibrate, budget).
    No subprocess, no per-call model round-trip.
  * ``total_ms``  — ``embed_ms + engine_ms``: the intended long-lived fast-path
    (embed the query, then retrieve), the number to compare to the §15/§16 budget.

Current seam note. With ``--backend local`` the CLI now passes the configured
retrieval adapters into ``LocalMemoryEngine`` and vector search embeds through
``self.adapters.embedding``. This bench still reports ``embed_ms`` separately so a
provider-backed run can distinguish model/provider latency from pure engine
latency. If ``fast_path_total`` is over budget, the remaining gap is provider
latency mitigation (cache, colocate, batch, or reduce rerank scope), not a missing
local-engine adapter seam.

Reuses: the Wave-1 metrics module (percentiles + bootstrap CIs), the Wave-1
embedding service, the curated retrieval dataset, and the production HTTP adapter.

Run:
    .venv-eval/bin/python eval/latency/bench.py            # full bench
    .venv-eval/bin/python eval/latency/bench.py --clients 8 --queries 25
    .venv-eval/bin/python eval/latency/bench.py --force-fallback   # CI / offline
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import platform
import resource as resource_mod
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve()
EVAL_DIR = HERE.parents[1]              # .../eval
REPO_ROOT = HERE.parents[2]            # .../Mnemosyne-completion
SRC = REPO_ROOT / "src"
SERVICE_APP = REPO_ROOT / "services" / "embedding" / "serve_instrumented.py"
SERVICE_APP_PLAIN = REPO_ROOT / "services" / "embedding" / "app.py"
DATASET = EVAL_DIR / "datasets" / "retrieval_curated.json"
REPORTS_DIR = HERE.parent / "reports"
VENV_EVAL_PY = REPO_ROOT / ".venv-eval" / "bin" / "python"

# Make the in-repo package + the Wave-1 harness importable without an install.
for p in (str(SRC), str(EVAL_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Reuse the Wave-1 metrics (percentiles + deterministic bootstrap CIs).
from harness import metrics  # noqa: E402  (path set above)

# §15 fast-path NFR / §16 SLO: P95 <= ~300-400 ms. We report against the looser
# 400 ms bound (and also show the tighter 300 ms) so "pass" is the generous read.
BUDGET_P95_MS_LOOSE = 400.0
BUDGET_P95_MS_TIGHT = 300.0

RECEIPT_SCHEMA = "mnemosyne.cap006.latency-receipt/v1"
DISTRIBUTION_WARM_SERIAL = "warm-serial"
DISTRIBUTION_CONCURRENT = "concurrent"
RECEIPT_CLASS_SYNTHETIC_DEV = "synthetic-development"
CLAIM_STATUS_SYNTHETIC_DEV = "synthetic-development-receipt-only"
SYNTHETIC_WORKLOAD_ID = "phase15-s4-synthetic-dev-v1"
PHASE15_S4_WARM_REPORT = REPORTS_DIR / "phase15-s4-warm.json"
PHASE15_S4_CONCURRENT_REPORT = REPORTS_DIR / "phase15-s4-concurrent.json"


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_canonical(payload: object) -> str:
    return _sha256_text(_canonical_json(payload))


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_identity() -> tuple[str, bool]:
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        text=True,
    ).strip()
    porcelain = subprocess.check_output(
        ["git", "status", "--porcelain"],
        cwd=REPO_ROOT,
        text=True,
    )
    return sha, porcelain.strip() == ""


def _cpu_flags() -> list[str]:
    cpuinfo = Path("/proc/cpuinfo")
    if not cpuinfo.exists():
        return []
    for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("flags") or line.startswith("Features"):
            return line.split(":", 1)[1].split()
    return []


def _host_identity() -> dict[str, Any]:
    uname = platform.uname()
    return {
        "os": uname.system,
        "os_release": uname.version,
        "kernel": uname.release,
        "architecture": uname.machine,
        "cpu_flags": _cpu_flags(),
        "accelerator": "none",
        "runtime_versions": {"python": platform.python_version()},
    }


def _pss_or_working_set_bytes(rss_bytes: int) -> int:
    rollup = Path("/proc/self/smaps_rollup")
    if rollup.exists():
        for line in rollup.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("Pss:"):
                parts = line.split()
                return int(parts[1]) * 1024
    return rss_bytes


def _meminfo_bytes() -> dict[str, int]:
    parsed: dict[str, int] = {}
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return parsed
    for line in meminfo.read_text(encoding="utf-8", errors="replace").splitlines():
        name, _, rest = line.partition(":")
        token = rest.strip().split()
        if not token:
            continue
        try:
            parsed[name] = int(token[0]) * 1024
        except ValueError:
            continue
    return parsed


def sample_resources() -> dict[str, Any]:
    mem = _meminfo_bytes()
    usage = resource_mod.getrusage(resource_mod.RUSAGE_SELF)
    rss_bytes = int(usage.ru_maxrss) * 1024
    load = list(os.getloadavg()) if hasattr(os, "getloadavg") else [0.0, 0.0, 0.0]
    return {
        "total_memory_bytes": mem.get("MemTotal", 0),
        "free_memory_bytes": mem.get("MemFree", 0),
        "available_memory_bytes": mem.get("MemAvailable", 0),
        "swap_bytes": mem.get("SwapTotal", 0),
        "process_rss_bytes": rss_bytes,
        "process_pss_or_working_set_bytes": _pss_or_working_set_bytes(rss_bytes),
        "vram_bytes": 0,
        "disk_bytes": 0,
        "network_bytes": 0,
        "load_averages": load,
        "cpu_seconds": usage.ru_utime + usage.ru_stime,
    }


def pinned_workload(dataset: dict[str, Any] | None = None) -> dict[str, Any]:
    data = dataset if dataset is not None else json.loads(DATASET.read_text(encoding="utf-8"))
    operations: list[dict[str, str]] = []
    for query in data["queries"]:
        if not query.get("answerable", True):
            continue
        operations.append(
            {
                "op_id": str(query["qid"]),
                "kind": "synthetic-dev-retrieve",
                "query": str(query["query"]),
            }
        )
    order = [op["op_id"] for op in operations]
    return {
        "dataset_id": str(data.get("dataset_id", "retrieval_curated_v1")),
        "operations": operations,
        "order": order,
        "order_digest": f"sha256:{_sha256_canonical(order)}",
    }


def _synthetic_execute(
    op: dict[str, str],
    *,
    inject_outcomes: dict[str, str],
    timeout_seconds: float,
    hold: Callable[[], None],
) -> None:
    hold()
    injected = inject_outcomes.get(op["op_id"])
    if injected == "timeout":
        time.sleep(timeout_seconds + 0.005)
        raise TimeoutError("injected timeout")
    if injected == "error":
        raise RuntimeError("injected error")
    if injected is not None:
        raise ValueError(f"unsupported injected outcome: {injected}")
    hashlib.sha256(op["query"].encode("utf-8")).hexdigest()


def _run_one_observation(
    op: dict[str, str],
    *,
    execute: Callable[[dict[str, str]], None],
    timeout_seconds: float,
    excluded: bool,
    excluded_reason: str | None,
    issue_monotonic: float,
    issue_utc: str,
) -> dict[str, Any]:
    start_monotonic = time.perf_counter()
    start_utc = datetime.now(timezone.utc).isoformat()
    error: str | None = None
    outcome = "success"
    try:
        execute(op)
        if time.perf_counter() - start_monotonic > timeout_seconds:
            outcome = "timeout"
    except TimeoutError as exc:
        outcome = "timeout"
        error = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001 - measurement must retain failures
        outcome = "error"
        error = f"{type(exc).__name__}: {exc}"
    end_monotonic = time.perf_counter()
    return {
        "op_id": op["op_id"],
        "issue_monotonic": issue_monotonic,
        "start_monotonic": start_monotonic,
        "end_monotonic": end_monotonic,
        "issue_utc": issue_utc,
        "start_utc": start_utc,
        "end_utc": datetime.now(timezone.utc).isoformat(),
        "latency_ms": (end_monotonic - start_monotonic) * 1000.0,
        "outcome": outcome,
        "error": error,
        "excluded": excluded,
        "excluded_reason": excluded_reason,
    }


def _overlap_evidence(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    measured = [obs for obs in observations if not obs["excluded"]]
    evidence: list[dict[str, Any]] = []
    for index, left in enumerate(measured):
        for right in measured[index + 1 :]:
            start = max(left["start_monotonic"], right["start_monotonic"])
            end = min(left["end_monotonic"], right["end_monotonic"])
            if start < end:
                evidence.append(
                    {
                        "op_ids": [left["op_id"], right["op_id"]],
                        "overlap_monotonic": end - start,
                    }
                )
    return evidence


def _observed_max_in_flight(observations: list[dict[str, Any]]) -> int:
    measured = [obs for obs in observations if not obs["excluded"]]
    events: list[tuple[float, int]] = []
    for obs in measured:
        events.append((obs["start_monotonic"], 1))
        events.append((obs["end_monotonic"], -1))
    events.sort(key=lambda item: (item[0], item[1]))
    current = 0
    peak = 0
    for _, delta in events:
        current += delta
        if current > peak:
            peak = current
    return peak


def _apply_concurrency_validity(receipt: dict[str, Any]) -> None:
    concurrency = receipt["concurrency"]
    reasons: list[str] = []
    if concurrency["declared_max_in_flight"] != concurrency["observed_max_in_flight"]:
        reasons.append("observed_max_in_flight_mismatch")
    if concurrency["declared_overlap"] != concurrency["observed_overlap"]:
        reasons.append("observed_overlap_mismatch")
    concurrency["matches_declaration"] = not reasons
    receipt["validity"] = {"valid": not reasons, "invalid_reasons": reasons}


def _bind_raw_artifacts(receipt: dict[str, Any]) -> None:
    bindable = {
        "schema": receipt["schema"],
        "identity_digests": receipt["identity"]["digests"],
        "workload": receipt["workload"],
        "concurrency": receipt["concurrency"],
        "observations": receipt["observations"],
        "denominators": receipt["denominators"],
        "distributions": receipt["distributions"],
    }
    receipt["raw_artifacts"] = {
        "observations_sha256": f"sha256:{_sha256_canonical(receipt['observations'])}",
        "workload_sha256": f"sha256:{_sha256_canonical(receipt['workload'])}",
        "result_digest": f"sha256:{_sha256_canonical(bindable)}",
    }


def write_phase15_s4_receipt(receipt: dict[str, Any], path: Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return target


def execute_pinned_workload(
    *,
    distribution: str,
    declared_concurrency: int,
    warmup_count: int,
    timeout_seconds: float,
    inject_outcomes: dict[str, str] | None = None,
    executor_workers: int | None = None,
    execute: Callable[[dict[str, str]], None] | None = None,
) -> dict[str, Any]:
    if distribution not in {DISTRIBUTION_WARM_SERIAL, DISTRIBUTION_CONCURRENT}:
        raise ValueError(f"unsupported distribution: {distribution}")
    if declared_concurrency < 1:
        raise ValueError("declared_concurrency must be >= 1")
    if warmup_count < 1:
        raise ValueError("warmup_count must be >= 1")
    if distribution == DISTRIBUTION_WARM_SERIAL and declared_concurrency != 1:
        raise ValueError("warm-serial receipts declare concurrency 1")

    pinned = pinned_workload()
    if warmup_count > len(pinned["operations"]):
        raise ValueError("warmup_count exceeds pinned workload size")
    injected = dict(inject_outcomes or {})
    workers = declared_concurrency if executor_workers is None else executor_workers
    if workers < 1:
        raise ValueError("executor_workers must be >= 1")
    declared_overlap = distribution == DISTRIBUTION_CONCURRENT
    hold_gate = threading.Event()
    in_flight = 0
    in_flight_lock = threading.Lock()

    def _hold() -> None:
        nonlocal in_flight
        if declared_concurrency <= 1 or workers <= 1:
            return
        with in_flight_lock:
            in_flight += 1
            if in_flight >= declared_concurrency:
                hold_gate.set()
        hold_gate.wait(timeout=1.0)
        time.sleep(0.02)

    def _execute(op: dict[str, str], *, hold_overlap: bool) -> None:
        hold_fn = _hold if hold_overlap else (lambda: None)
        if execute is not None:
            hold_fn()
            execute(op)
            return
        _synthetic_execute(
            op,
            inject_outcomes=injected,
            timeout_seconds=timeout_seconds,
            hold=hold_fn,
        )

    def _execute_warmup(op: dict[str, str]) -> None:
        _execute(op, hold_overlap=False)

    def _execute_measured(op: dict[str, str]) -> None:
        _execute(op, hold_overlap=True)

    command = ["eval/latency/bench.py", "cap006-synthetic"]
    arguments = {
        "distribution": distribution,
        "declared_concurrency": declared_concurrency,
        "warmup_count": warmup_count,
        "timeout_seconds": timeout_seconds,
        "executor_workers": workers,
        "workload": SYNTHETIC_WORKLOAD_ID,
    }
    repository_sha, clean_tree = _git_identity()
    utc_start = datetime.now(timezone.utc).isoformat()
    monotonic_start = time.perf_counter()
    before = sample_resources()

    warmup_ops = pinned["operations"][:warmup_count]
    warmup_observations: list[dict[str, Any]] = []
    for op in warmup_ops:
        issue_monotonic = time.perf_counter()
        warmup_observations.append(
            _run_one_observation(
                op,
                execute=_execute_warmup,
                timeout_seconds=timeout_seconds,
                excluded=True,
                excluded_reason="warmup",
                issue_monotonic=issue_monotonic,
                issue_utc=datetime.now(timezone.utc).isoformat(),
            )
        )

    during = sample_resources()
    measured_observations: list[dict[str, Any]] = []
    wall0 = time.perf_counter()
    if workers <= 1:
        for op in pinned["operations"]:
            issue_monotonic = time.perf_counter()
            measured_observations.append(
                _run_one_observation(
                    op,
                    execute=_execute_measured,
                    timeout_seconds=timeout_seconds,
                    excluded=False,
                    excluded_reason=None,
                    issue_monotonic=issue_monotonic,
                    issue_utc=datetime.now(timezone.utc).isoformat(),
                )
            )
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures: list[concurrent.futures.Future[dict[str, Any]]] = []
            for op in pinned["operations"]:
                issue_monotonic = time.perf_counter()
                issue_utc = datetime.now(timezone.utc).isoformat()
                futures.append(
                    pool.submit(
                        _run_one_observation,
                        op,
                        execute=_execute_measured,
                        timeout_seconds=timeout_seconds,
                        excluded=False,
                        excluded_reason=None,
                        issue_monotonic=issue_monotonic,
                        issue_utc=issue_utc,
                    )
                )
            measured_observations = [future.result() for future in futures]
    wall_s = time.perf_counter() - wall0
    after = sample_resources()
    utc_end = datetime.now(timezone.utc).isoformat()
    monotonic_end = time.perf_counter()

    observations = warmup_observations + measured_observations
    overlap = _overlap_evidence(observations)
    observed_max = _observed_max_in_flight(observations)
    successes = sum(1 for obs in observations if obs["outcome"] == "success")
    timeouts = sum(1 for obs in observations if obs["outcome"] == "timeout")
    errors = sum(1 for obs in observations if obs["outcome"] == "error")
    measured = [obs for obs in observations if not obs["excluded"]]
    samples = [obs["latency_ms"] for obs in measured]
    summary = metrics.latency_summary(samples)
    p95_ci = metrics.bootstrap_percentile_interval(samples, 0.95)
    throughput = (len(measured) / wall_s) if wall_s > 0 else 0.0
    workload = {
        "order": pinned["order"],
        "order_digest": pinned["order_digest"],
        "operations": pinned["operations"],
        "warmup": {
            "explicit": True,
            "count": warmup_count,
            "operation_ids": [op["op_id"] for op in warmup_ops],
            "excluded_from_distribution": True,
        },
        "repetitions": 1,
        "timeouts_seconds": timeout_seconds,
        "retries": 0,
        "cold_warm_state": "warm",
    }
    digests = {
        "dataset": f"sha256:{_sha256_file(DATASET)}",
        "fixture": f"sha256:{_sha256_canonical({'workload': SYNTHETIC_WORKLOAD_ID})}",
        "config": f"sha256:{_sha256_canonical(arguments)}",
        "model": f"sha256:{_sha256_canonical('synthetic-dev-none')}",
        "tokenizer": f"sha256:{_sha256_canonical('synthetic-dev-none')}",
        "provider": f"sha256:{_sha256_canonical('synthetic-dev-none')}",
        "container_image": f"sha256:{_sha256_canonical('none')}",
        "schema": f"sha256:{_sha256_canonical(RECEIPT_SCHEMA)}",
        "result_contract": f"sha256:{_sha256_canonical('cap006-latency-receipt-v1-synthetic')}",
    }
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "receipt_class": RECEIPT_CLASS_SYNTHETIC_DEV,
        "official_claim": False,
        "admitted_measurement": False,
        "claim_status": CLAIM_STATUS_SYNTHETIC_DEV,
        "identity": {
            "repository_sha": repository_sha,
            "clean_tree": clean_tree,
            "command": command,
            "arguments": arguments,
            "utc_start": utc_start,
            "utc_end": utc_end,
            "monotonic_start": monotonic_start,
            "monotonic_end": monotonic_end,
            "host": _host_identity(),
            "digests": digests,
        },
        "sut_boundary": {
            "included_processes": ["synthetic-dev-harness"],
            "containers": [],
            "databases": [],
            "proxies": [],
            "caches": [],
            "indexes": [],
            "filesystems": ["workspace"],
            "background_workers": [],
            "benchmark_process_count": 1,
            "host_workload_count": 1,
        },
        "workload": workload,
        "concurrency": {
            "declared_max_in_flight": declared_concurrency,
            "observed_max_in_flight": observed_max,
            "declared_overlap": declared_overlap,
            "observed_overlap": bool(overlap),
            "overlap_evidence": overlap,
            "worker_count": workers,
            "total_model_request_count": len(measured),
        },
        "resources": {
            "before": before,
            "during": [during],
            "after": after,
            "memory_pressure": (
                "none"
                if after["available_memory_bytes"] == 0
                else after["available_memory_bytes"] / max(after["total_memory_bytes"], 1)
            ),
            "swap_pagefile_delta": after["swap_bytes"] - before["swap_bytes"],
            "disk_index_growth": 0,
            "network_bytes": 0,
            "first_abort": None,
        },
        "observations": observations,
        "denominators": {
            "issued": len(observations),
            "successes": successes,
            "timeouts": timeouts,
            "errors": errors,
            "failed_remain_in_denominator": True,
            "excluded": sum(1 for obs in observations if obs["excluded"]),
            "slow_samples_retained": True,
        },
        "distributions": [
            {
                "name": distribution,
                "sample_count": len(measured),
                "p50_ms": summary.p50,
                "p95_ms": summary.p95,
                "p99_ms": summary.p99,
                "throughput_qps": throughput,
                "confidence_interval": p95_ci.as_dict(),
                "official_claim": False,
                "asserted": False,
            }
        ],
    }
    _apply_concurrency_validity(receipt)
    _bind_raw_artifacts(receipt)
    return receipt


# --------------------------------------------------------------------------- #
# Warm embedding service lifecycle
# --------------------------------------------------------------------------- #
def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _http_get_json(url: str, timeout: float = 5.0) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 local only
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return None


class WarmEmbeddingService:
    """Start the real embedding service ONCE (models loaded once) and keep it warm.

    Prefers the instrumented launcher (counts /embed + /rerank so we can PROVE the
    wired path fired). Started under ``.venv-eval`` so the real torch /
    sentence-transformers models are available.
    """

    def __init__(self, *, force_fallback: bool, port: int | None = None, reuse_url: str | None = None):
        self.force_fallback = force_fallback
        self.reuse_url = reuse_url
        self.port = port or _free_port()
        self.proc: subprocess.Popen | None = None
        self.counter_file = Path(tempfile.gettempdir()) / f"mnemo_latency_counters_{os.getpid()}.json"
        self.base_url = reuse_url.rstrip("/") if reuse_url else f"http://127.0.0.1:{self.port}"
        self.health: dict[str, Any] = {}
        self.started_here = False
        self._local_counters: dict[str, int] = {}

    @property
    def embed_url(self) -> str:
        return f"{self.base_url}/embed"

    @property
    def rerank_url(self) -> str:
        return f"{self.base_url}/rerank"

    def start(self, *, model_load_timeout: float = 600.0) -> None:
        if self.reuse_url:
            h = _http_get_json(f"{self.base_url}/health")
            if not h:
                raise RuntimeError(f"--reuse-service {self.base_url} is not reachable at /health")
            self.health = h
            return

        env = dict(os.environ)
        env["EMBEDDING_SERVICE_HOST"] = "127.0.0.1"
        env["EMBEDDING_SERVICE_PORT"] = str(self.port)
        env["EMBEDDING_COUNTER_FILE"] = str(self.counter_file)
        env["PYTHONPATH"] = os.pathsep.join(p for p in (str(SRC), env.get("PYTHONPATH", "")) if p)
        if self.force_fallback:
            env["EMBEDDING_SERVICE_FORCE_FALLBACK"] = "1"

        # Prefer the instrumented launcher (needs fastapi+uvicorn, present in
        # .venv-eval). Fall back to plain app.py (stdlib server) if that import
        # path is unavailable.
        py = str(VENV_EVAL_PY) if VENV_EVAL_PY.exists() else sys.executable
        launchers = []
        if SERVICE_APP.exists():
            launchers.append(SERVICE_APP)
        if SERVICE_APP_PLAIN.exists() and SERVICE_APP_PLAIN not in launchers:
            launchers.append(SERVICE_APP_PLAIN)
        if not launchers:
            raise RuntimeError("no embedding service launcher is available")

        last_err: str = "no response"
        for index, launcher in enumerate(launchers):
            self.proc = subprocess.Popen(
                [py, str(launcher)],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.started_here = True
            deadline = time.time() + model_load_timeout
            while time.time() < deadline:
                if self.proc.poll() is not None:
                    last_err = f"{launcher.name} exited early (rc={self.proc.returncode})"
                    if index + 1 < len(launchers):
                        break
                    raise RuntimeError(f"embedding service exited early (rc={self.proc.returncode})")
                h = _http_get_json(f"{self.base_url}/health", timeout=10.0)
                if h and h.get("status") == "ok":
                    self.health = h
                    return
                last_err = "health not ok yet"
                time.sleep(1.0)
            else:
                raise RuntimeError(
                    f"embedding service did not become healthy in {model_load_timeout}s ({last_err})"
                )
        raise RuntimeError(f"embedding service did not become healthy ({last_err})")

    def warm(self, sample_texts: list[str]) -> None:
        """Fire warm-up embed calls so the first measured call is not cold."""
        for t in sample_texts[:8]:
            try:
                data = json.dumps({"input": t}).encode("utf-8")
                req = urllib.request.Request(self.embed_url, data=data, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=60.0):  # noqa: S310 local only
                    self.note_request("POST /embed")
            except (urllib.error.URLError, OSError, TimeoutError):
                pass

    def note_request(self, key: str) -> None:
        self._local_counters[key] = int(self._local_counters.get(key, 0)) + 1

    def backend_kind(self) -> str:
        emb = (self.health or {}).get("embedding", {})
        return str(emb.get("backend", "unknown"))

    def counters(self) -> dict[str, int]:
        if self.counter_file.exists():
            try:
                file_counts = json.loads(self.counter_file.read_text())
                if file_counts:
                    return file_counts
            except (json.JSONDecodeError, OSError):
                pass
        http_counts = _http_get_json(f"{self.base_url}/_counters")
        if http_counts:
            return http_counts
        return dict(self._local_counters)

    def stop(self) -> None:
        if self.proc and self.started_here:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        try:
            self.counter_file.unlink(missing_ok=True)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# Warm in-process engine (built ONCE via the exact CLI seam)
# --------------------------------------------------------------------------- #
def build_warm_tools(store_path: Path):
    """Build a warm ``MemoryTools`` exactly as the CLI does, once.

    We construct the same argparse namespace the CLI parser produces (defaults +
    local backend + our temp store) and call ``load_tools``. This is the public
    in-process equivalent of one ``python -m mnemosyne.cli ... search`` process,
    but the import + engine construction is paid a single time for the whole run.
    """
    from mnemosyne import cli as mnemo_cli

    parser = mnemo_cli.build_parser()
    args = parser.parse_args(["--backend", "local", "--store", str(store_path), "search", "--tenant", "x", "--query", "x"])
    tools = mnemo_cli.load_tools(args)
    return tools


def build_engine_pool(n: int, dataset: dict[str, Any]) -> list[Any]:
    """Build N warm, corpus-loaded ``MemoryTools`` — one per concurrent client.

    Why one per client, not one shared engine: on the local single-file backend
    every ``search()`` persists runtime metrics via atomic-replace to
    ``<store>.runtime.json`` (``_record_retrieval`` -> ``_save_metrics`` ->
    ``RuntimeState.save``). Concurrent threads sharing one store race on that
    rename — a single-writer property of the local backend, NOT a fast-path
    latency cost. A production server avoids it with the concurrent-safe Postgres
    runtime state (or per-tenant serialization). To measure the engine fast-path
    faithfully WITHOUT manufacturing single-file write contention, each client
    gets its own warm engine + store + pre-loaded corpus (the same isolation the
    Wave-1 latency suite uses). The embedding SERVICE is shared (it is a real,
    concurrent-safe server). This mirrors a sharded long-lived deployment.
    """
    pool: list[Any] = []
    base = Path(tempfile.gettempdir())
    run_token = f"{os.getpid()}_{time.time_ns()}"
    for i in range(n):
        store = base / f"mnemo_latency_{run_token}_w{i}.json"
        # Clean any stale state so each engine is fresh.
        for suffix in ("", ".runtime.json", ".runtime.json.tmp"):
            try:
                (base / f"{store.name}{suffix}").unlink(missing_ok=True)
            except OSError:
                pass
        tools = build_warm_tools(store)
        capture_corpus(tools, dataset)
        pool.append(tools)
    return pool


def load_dataset() -> dict[str, Any]:
    return json.loads(DATASET.read_text())


def capture_corpus(tools, dataset: dict[str, Any]) -> None:
    tenant = dataset["tenant"]
    user = dataset.get("user", "eval-user")
    for doc in dataset["corpus"]:
        tools.capture(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type=f"seed:{doc['doc_id']}",
            content=doc["content"],
            trust_tier=int(doc.get("trust_tier", 0)),
        )


# --------------------------------------------------------------------------- #
# The bench
# --------------------------------------------------------------------------- #
def run_bench(args: argparse.Namespace) -> dict[str, Any]:
    from mnemosyne.retrieval import HttpEmbeddingProvider

    dataset = load_dataset()
    tenant = dataset["tenant"]
    queries = [q["query"] for q in dataset["queries"] if q.get("answerable", True)]
    if not queries:
        queries = [q["query"] for q in dataset["queries"]]

    # --- warm the engine pool (once): one warm engine per concurrent client ---
    t0 = time.perf_counter()
    engine_pool = build_engine_pool(args.clients, dataset)
    engine_warm_ms = (time.perf_counter() - t0) * 1000.0

    # --- warm the embedding service (once) ---
    svc = WarmEmbeddingService(force_fallback=args.force_fallback, reuse_url=args.reuse_service)
    svc_start_ms = 0.0
    s0 = time.perf_counter()
    svc.start(model_load_timeout=args.model_load_timeout)
    svc.warm(queries + [doc["content"] for doc in dataset["corpus"]])
    svc_start_ms = (time.perf_counter() - s0) * 1000.0

    # Production HTTP embedding adapter (the exact src adapter) -> warm service.
    embedder = HttpEmbeddingProvider(
        url=svc.embed_url,
        model=args.embedding_model,
        dims=int(args.embedding_dims),
        timeout_seconds=float(args.retrieval_timeout),
    )

    # --- warm-up rounds (JIT / page cache / connection reuse) ---
    for idx, q in enumerate(queries[: max(1, args.clients)]):
        try:
            embedder.embed(q)
            svc.note_request("POST /embed")
        except Exception:  # noqa: BLE001 - warm-up is best-effort
            pass
        engine_pool[idx % len(engine_pool)].search(tenant_id=tenant, query=q)

    # --- the measured concurrent load: N clients x M queries ---
    n_clients = args.clients
    m_queries = args.queries
    # task = (client_index, query); client_index selects that client's own warm engine.
    tasks = [(i % n_clients, queries[i % len(queries)]) for i in range(n_clients * m_queries)]

    embed_ms: list[float] = []
    engine_ms: list[float] = []
    total_ms: list[float] = []
    errors: list[str] = []

    def _one(item: tuple[int, str]) -> tuple[float, float, float, str | None]:
        client_idx, query = item
        client_tools = engine_pool[client_idx]
        err: str | None = None
        # Isolated embed-call latency (warm model-inference HTTP round-trip).
        e0 = time.perf_counter()
        try:
            embedder.embed(query)
            e_ms = (time.perf_counter() - e0) * 1000.0
            svc.note_request("POST /embed")
        except Exception as exc:  # noqa: BLE001
            e_ms = (time.perf_counter() - e0) * 1000.0
            err = f"embed: {type(exc).__name__}: {exc}"
        # Pure engine fast-path latency (in-process, no subprocess/model round-trip).
        g0 = time.perf_counter()
        try:
            client_tools.search(tenant_id=tenant, query=query)
            g_ms = (time.perf_counter() - g0) * 1000.0
        except Exception as exc:  # noqa: BLE001
            g_ms = (time.perf_counter() - g0) * 1000.0
            err = (err + " | " if err else "") + f"engine: {type(exc).__name__}: {exc}"
        return e_ms, g_ms, e_ms + g_ms, err

    wall0 = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=n_clients) as pool:
        for e_ms, g_ms, t_ms, err in pool.map(_one, tasks):
            embed_ms.append(e_ms)
            engine_ms.append(g_ms)
            total_ms.append(t_ms)
            if err:
                errors.append(err)
    wall_ms = (time.perf_counter() - wall0) * 1000.0

    counters = svc.counters()
    backend_kind = svc.backend_kind()
    health = svc.health
    svc.stop()

    def _component(label: str, samples: list[float]) -> dict[str, Any]:
        summ = metrics.latency_summary(samples)
        p95_ci = metrics.bootstrap_percentile_interval(samples, 0.95)
        p50_ci = metrics.bootstrap_percentile_interval(samples, 0.50)
        return {
            "label": label,
            "p50_ms": round(summ.p50, 2),
            "p95_ms": round(summ.p95, 2),
            "p99_ms": round(summ.p99, 2),
            "mean_ms": round(summ.mean, 2),
            "max_ms": round(summ.maximum, 2),
            "min_ms": round(min(samples), 2) if samples else 0.0,
            "p95_ci": p95_ci.as_dict(),
            "p50_ci": p50_ci.as_dict(),
        }

    embed_block = _component("embed_call_only", embed_ms)
    engine_block = _component("engine_only", engine_ms)
    total_block = _component("fast_path_total", total_ms)

    throughput_qps = (len(total_ms) / (wall_ms / 1000.0)) if wall_ms > 0 else 0.0

    def _verdict(name: str, p95: float, ci: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": name,
            "p95_ms": round(p95, 2),
            "target_ms_loose": BUDGET_P95_MS_LOOSE,
            "target_ms_tight": BUDGET_P95_MS_TIGHT,
            "op": "<=",
            "pass_loose": bool(p95 <= BUDGET_P95_MS_LOOSE),
            "pass_tight": bool(p95 <= BUDGET_P95_MS_TIGHT),
            "p95_ci": ci,
        }

    report = {
        "bench": "long_lived_fast_path_latency",
        "wave": 3,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "blueprint_refs": ["§15 fast-path P95 NFR", "FR-3", "§16 SLO"],
        "fixes_wave2_artifact": {
            "confound_1_subprocess_per_call": "ELIMINATED: engine built once in-process via cli.load_tools (no per-call python startup)",
            "confound_2_per_call_model_roundtrip_cold": "ELIMINATED: embedding service started once, models loaded once, warmed before measurement; embed-call latency measured in isolation",
            "wave2_reference": "eval/reports/KEYSTONE_PROOF.md (Latency caveat)",
        },
        "config": {
            "clients": n_clients,
            "queries_per_client": m_queries,
            "total_calls": len(total_ms),
            "store_backend": "local (in-process LocalMemoryEngine)",
            "concurrency_model": (
                "one warm engine + store + corpus per client (local single-file backend is "
                "single-writer: every search persists runtime metrics via atomic-replace, so a "
                "shared engine races; a production server uses Postgres runtime state or per-tenant "
                "serialization). The embedding SERVICE is a single shared concurrent-safe server."
            ),
            "embedding_url": svc.embed_url,
            "embedding_model": args.embedding_model,
            "embedding_dims": int(args.embedding_dims),
            "force_fallback": args.force_fallback,
            "reuse_service": args.reuse_service,
            "dataset": str(DATASET.relative_to(REPO_ROOT)),
            "n_corpus_docs": len(dataset["corpus"]),
            "n_unique_queries": len(queries),
        },
        "warm_costs_paid_once_ms": {
            "engine_build_and_corpus_capture": round(engine_warm_ms, 2),
            "embedding_service_start_and_model_load": round(svc_start_ms, 2),
            "note": "These are paid ONCE for a long-lived server, NOT per request — exactly what Wave-2 wrongly charged to every call.",
        },
        "embedding_service": {
            "backend": backend_kind,
            "is_real_model": backend_kind in ("sentence-transformers", "cross-encoder"),
            "health": health,
            "request_counters": counters,
            "proved_wired": bool(counters.get("POST /embed", 0) > 0),
        },
        "wall_clock_ms": round(wall_ms, 2),
        "throughput_qps": round(throughput_qps, 2),
        "components": {
            "embed_call_only": embed_block,
            "engine_only": engine_block,
            "fast_path_total": total_block,
        },
        "verdicts": [
            _verdict("fast_path_total_p95", total_block["p95_ms"], total_block["p95_ci"]),
            _verdict("engine_only_p95", engine_block["p95_ms"], engine_block["p95_ci"]),
            _verdict("embed_call_only_p95", embed_block["p95_ms"], embed_block["p95_ci"]),
        ],
        "errors": errors[:20],
        "n_errors": len(errors),
    }
    return report


def write_reports(report: dict[str, Any]) -> tuple[Path, Path]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = REPORTS_DIR / f"latency_bench_{stamp}.json"
    json_path.write_text(json.dumps(report, indent=2))
    (REPORTS_DIR / "latency_bench_latest.json").write_text(json.dumps(report, indent=2))
    md = render_markdown(report)
    md_path = REPORTS_DIR / f"latency_bench_{stamp}.md"
    md_path.write_text(md)
    (REPORTS_DIR / "latency_bench_latest.md").write_text(md)
    return json_path, md_path


def render_markdown(r: dict[str, Any]) -> str:
    c = r["config"]
    comp = r["components"]
    svc = r["embedding_service"]
    warm = r["warm_costs_paid_once_ms"]

    def row(b: dict[str, Any]) -> str:
        ci = b["p95_ci"]
        return (
            f"| {b['label']} | {b['p50_ms']} | {b['p95_ms']} | {b['p99_ms']} | "
            f"{b['mean_ms']} | {b['max_ms']} | [{ci['ci_low']}, {ci['ci_high']}] |"
        )

    total = comp["fast_path_total"]
    pass_loose = total["p95_ms"] <= BUDGET_P95_MS_LOOSE
    pass_tight = total["p95_ms"] <= BUDGET_P95_MS_TIGHT
    verdict_line = (
        "PASS (<=400 ms)" if pass_loose else "FAIL (> 400 ms budget)"
    ) + (" / PASS (<=300 ms)" if pass_tight else " / FAIL (>300 ms)")

    lines = [
        "# Wave-3 Long-Lived-Server Fast-Path P95 Latency Bench",
        "",
        f"Generated: {r['generated_at']}",
        f"Blueprint: {', '.join(r['blueprint_refs'])}",
        "",
        "## What this fixes (Wave-2 artifact)",
        "",
        "Wave-2's latency suite charged **per-process Python cold-start (~200-300 ms)** "
        "and a **cold per-call model HTTP round-trip** to every single request. Those are "
        "startup costs a long-lived server pays ONCE. This bench pays them once and "
        "measures warm per-request latency under concurrent load.",
        "",
        f"- Confound 1 (subprocess/call): {r['fixes_wave2_artifact']['confound_1_subprocess_per_call']}",
        f"- Confound 2 (cold model round-trip/call): {r['fixes_wave2_artifact']['confound_2_per_call_model_roundtrip_cold']}",
        "",
        "## Warm-server setup (paid once, NOT per request)",
        "",
        f"- Engine build + corpus capture: **{warm['engine_build_and_corpus_capture']} ms** (once)",
        f"- Embedding service start + model load: **{warm['embedding_service_start_and_model_load']} ms** (once)",
        f"- Embedding backend: **{svc['backend']}** "
        f"({'REAL model' if svc['is_real_model'] else 'deterministic fallback'})",
        f"- Wired path proved (POST /embed counted): **{svc['proved_wired']}** "
        f"(counters: {json.dumps(svc['request_counters'])})",
        "",
        "## Load",
        "",
        f"- {c['clients']} concurrent clients x {c['queries_per_client']} queries "
        f"= **{c['total_calls']} calls**",
        f"- Corpus: {c['n_corpus_docs']} docs, {c['n_unique_queries']} unique queries "
        f"(`{c['dataset']}`)",
        f"- Throughput: **{r['throughput_qps']} qps** over {r['wall_clock_ms']} ms wall",
        f"- Errors: {r['n_errors']}",
        "",
        "## Results — warm per-request latency (ms)",
        "",
        "| component | P50 | P95 | P99 | mean | max | P95 95% CI |",
        "|---|---|---|---|---|---|---|",
        row(comp["embed_call_only"]),
        row(comp["engine_only"]),
        row(comp["fast_path_total"]),
        "",
        "Component meaning:",
        "- **embed_call_only** — isolated warm HTTP round-trip to the real embedding "
        "service (model-inference cost), via the production `HttpEmbeddingProvider`.",
        "- **engine_only** — one warm in-process `MemoryTools.search()` (pure engine "
        "fast path: hybrid retrieve + fuse + MMR + calibrate + budget). No subprocess, "
        "no per-call model round-trip.",
        "- **fast_path_total** — `embed + engine`: the intended long-lived fast path.",
        "",
        f"## Verdict vs §15/§16 budget (P95 <= {int(BUDGET_P95_MS_TIGHT)}-{int(BUDGET_P95_MS_LOOSE)} ms)",
        "",
        f"**fast_path_total P95 = {total['p95_ms']} ms -> {verdict_line}**",
        "",
        f"- engine_only P95 = {comp['engine_only']['p95_ms']} ms "
        f"({'<=' if comp['engine_only']['p95_ms'] <= BUDGET_P95_MS_LOOSE else '>'} 400 ms)",
        f"- embed_call_only P95 = {comp['embed_call_only']['p95_ms']} ms "
        f"({'<=' if comp['embed_call_only']['p95_ms'] <= BUDGET_P95_MS_LOOSE else '>'} 400 ms)",
        "",
        "## Honest reading + what would close the gap",
        "",
        _honest_narrative(r),
        "",
    ]
    return "\n".join(lines)


def _honest_narrative(r: dict[str, Any]) -> str:
    comp = r["components"]
    svc = r["embedding_service"]
    engine_p95 = comp["engine_only"]["p95_ms"]
    embed_p95 = comp["embed_call_only"]["p95_ms"]
    total_p95 = comp["fast_path_total"]["p95_ms"]
    real = svc["is_real_model"]

    parts: list[str] = []
    # Engine verdict.
    if engine_p95 <= BUDGET_P95_MS_LOOSE:
        parts.append(
            f"The **engine fast path alone is within budget** (P95 {engine_p95} ms <= 400 ms) once "
            f"warm and in-process — this is the real Wave-2 correction: the multi-second Wave-2 "
            f"'engine-only' number was per-process Python startup, not the engine."
        )
    else:
        parts.append(
            f"Even warm and in-process the **engine fast path P95 is {engine_p95} ms** (> 400 ms) — "
            f"a genuine engine-side cost, not a measurement artifact."
        )
    # Embed verdict.
    backend = "real BGE/cross-encoder model" if real else "deterministic fallback (no torch path active)"
    if embed_p95 <= BUDGET_P95_MS_LOOSE:
        parts.append(
            f"The **warm embed call** ({backend}) adds P95 {embed_p95} ms — within budget on its own."
        )
    else:
        parts.append(
            f"The **warm embed call** ({backend}) is the dominant cost at P95 {embed_p95} ms (> 400 ms) "
            f"even warm: each query still pays a full model-inference HTTP round-trip per request."
        )
    # Total verdict + gap-closers.
    if total_p95 <= BUDGET_P95_MS_LOOSE:
        parts.append(
            f"**fast_path_total P95 {total_p95} ms meets the §15/§16 budget.** The Wave-2 'fail' was "
            f"a measurement artifact; the warm long-lived server meets the NFR."
        )
    else:
        parts.append(
            f"**fast_path_total P95 {total_p95} ms still exceeds the 300-400 ms budget** even warm. "
            f"This is reported honestly: a per-request synchronous model-inference round-trip does not "
            f"fit a 300-400 ms fast-path budget on this hardware. Gap-closers, in priority order:"
            f"\n  1. **Provider latency mitigation.** The local backend now receives configured "
            f"retrieval adapters through `load_engine(..., adapters=...)`, and vector search embeds "
            f"through `self.adapters.embedding`. The remaining gap is provider cost: use a "
            f"low-latency or colocated provider so the hot path does not pay a slow HTTP/CPU round-trip."
            f"\n  2. **Embedding cache.** Cache query->vector (and persist doc vectors at capture) so "
            f"repeat/near-repeat queries skip the model entirely — turns the embed P95 into a cache-hit "
            f"P95 of single-digit ms."
            f"\n  3. **Batching / in-process model.** Co-locate the embedder in the server process "
            f"(no HTTP/JSON serialization hop) and batch concurrent queries into one forward pass; for "
            f"a server with a GPU, BGE-small query embedding is sub-10 ms in-process vs the HTTP round-"
            f"trip measured here."
            f"\n  4. **ANN prefilter, rerank only top-N.** Keep the cross-encoder off the hot path: ANN "
            f"dense recall + lexical, rerank only a small candidate set, so model cost scales with N not "
            f"corpus size."
        )
    if not real:
        parts.append(
            "NOTE: this run used the **deterministic fallback** encoder (real torch path not active). "
            "Re-run under `.venv-eval` without `--force-fallback` (real BGE + cross-encoder are cached "
            "in `~/.cache/huggingface`) for the production embed-cost numbers."
        )
    return "\n\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clients", type=int, default=8, help="concurrent clients N (default 8)")
    ap.add_argument("--queries", type=int, default=25, help="queries per client M (default 25)")
    ap.add_argument("--embedding-model", default="BAAI/bge-small-en-v1.5")
    ap.add_argument("--embedding-dims", type=int, default=1024)
    ap.add_argument("--retrieval-timeout", type=float, default=30.0)
    ap.add_argument("--model-load-timeout", type=float, default=600.0)
    ap.add_argument("--force-fallback", action="store_true", help="force the deterministic fallback encoder (CI/offline)")
    ap.add_argument("--reuse-service", default=None, help="reuse an already-running service base URL (e.g. http://127.0.0.1:8000)")
    ap.add_argument("--json-only", action="store_true", help="print only the JSON report to stdout")
    args = ap.parse_args()

    report = run_bench(args)
    json_path, md_path = write_reports(report)

    if args.json_only:
        print(json.dumps(report, indent=2))
    else:
        print(render_markdown(report))
        print(f"\n[bench] JSON  -> {json_path}")
        print(f"[bench] MD    -> {md_path}")
        print(f"[bench] latest -> {md_path.parent / 'latency_bench_latest.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
