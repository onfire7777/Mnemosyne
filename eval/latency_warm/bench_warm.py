#!/usr/bin/env python3
"""WARM-SERVER fast-path P95 latency harness (Postgres real-provider path).

WHY THIS EXISTS
---------------
The prior fast-path latency bench (`eval/latency/bench.py`, and the even older
Wave-2 suite) measured a **subprocess-per-query artifact**: every query cold-started
a fresh ``python -m mnemosyne.cli`` process (interpreter + import + engine build,
~200-300 ms each) and/or paid a cold model round-trip with no warm-up. Those are
one-time startup costs a long-lived server pays ONCE, not per request. Charging
them to every call makes the §15/§16 fast-path P95 NFR (~300-400 ms) un-measurable.

This harness fixes that. It is an **in-process, warm, long-lived-server** harness
on the **real-provider Postgres path** that the production design actually uses:

  * The real embedding service (``services/embedding/app.py`` via the instrumented
    launcher) is started ONCE on ``EMBEDDING_SERVICE_PORT`` (default 8099) under
    ``.venv-eval`` so the REAL torch / sentence-transformers (BGE) + cross-encoder
    models load ONCE. We assert ``/health`` reports the real backend (not the
    deterministic fallback) unless ``--allow-fallback`` is given.

  * The Mnemosyne engine is built ONCE per client via the EXACT public CLI seam
    (``mnemosyne.cli.build_parser`` -> ``load_tools`` -> ``MemoryTools``) with
    ``--backend postgres``. Unlike the local engine, ``PostgresEngine`` genuinely
    uses the HTTP embedding + HTTP reranker adapters on BOTH capture (writes a
    real pgvector embedding) and retrieve (embeds the query, dense vector search,
    cross-encoder rerank). So the warm number here is the real wired fast path.

  * The curated corpus is captured ONCE into Postgres under a DISTINCT, run-unique
    tenant prefix (``<prefix>-<runid>``). The tenant string maps to a dedicated
    ``uuid5`` tenant id, so the seed never collides with shared data and shared
    tables are NEVER truncated. The harness deletes only its own tenant's rows at
    the end (``--keep-data`` to retain them).

Then it issues MANY warm retrieval calls IN-PROCESS (no per-query subprocess) under
concurrent load (N clients x M queries) and reports true warm percentiles,
SEPARATING embed-call latency from engine latency:

  * ``embed_ms``  — an isolated warm HTTP round-trip to the real embedding service
    for the query, via the production ``HttpEmbeddingProvider`` adapter. This is
    the model-inference cost in isolation.
  * ``engine_ms`` — one in-process ``MemoryTools.search()``: the TRUE warm fast
    path (embed query + dense pgvector search + lexical FTS + RRF fuse + cross-
    encoder rerank + MMR + calibrate + budget). No subprocess, no cold start.
    NOTE: ``engine_ms`` already CONTAINS its own internal embed/rerank HTTP calls
    (the engine embeds the query and the reranker re-embeds candidates); it is the
    real end-to-end fast-path latency to compare to the §15/§16 budget.
  * ``engine_minus_embed_ms`` — ``engine_ms - embed_ms`` per call: an approximate
    decomposition isolating the non-embed engine work (SQL retrieve + fuse + rerank
    orchestration + MMR + calibrate). Reported for transparency, not as the SLO.

The harness reports the real warm ``engine_ms`` P95 honestly against the
300-400 ms budget — pass or fail.

Run (under the eval venv, which has psycopg + torch):
    .venv-eval/bin/python eval/latency_warm/bench_warm.py
    .venv-eval/bin/python eval/latency_warm/bench_warm.py --clients 8 --queries 25
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

HERE = Path(__file__).resolve()
LATENCY_WARM_DIR = HERE.parent                       # .../eval/latency_warm
EVAL_DIR = HERE.parents[1]                            # .../eval
REPO_ROOT = HERE.parents[2]                           # .../Mnemosyne-completion
LATENCY_DIR = EVAL_DIR / "latency"
SRC = REPO_ROOT / "src"
SERVICE_INSTRUMENTED = REPO_ROOT / "services" / "embedding" / "serve_instrumented.py"
SERVICE_PLAIN = REPO_ROOT / "services" / "embedding" / "app.py"
DATASET = EVAL_DIR / "datasets" / "retrieval_curated.json"
REPORTS_DIR = LATENCY_WARM_DIR / "reports"
VENV_EVAL_PY = REPO_ROOT / ".venv-eval" / "bin" / "python"

# Make the in-repo package + the Wave-1 harness importable without an install.
for p in (str(SRC), str(EVAL_DIR), str(LATENCY_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from harness import metrics  # noqa: E402  (path set above)
import bench as latency_bench  # noqa: E402  shared CAP-006 ABI

# §15 fast-path NFR / §16 SLO: P95 <= ~300-400 ms. We report against both the
# tight (300 ms) and loose (400 ms) bounds so "pass" is the generous read.
BUDGET_P95_MS_LOOSE = 400.0
BUDGET_P95_MS_TIGHT = 300.0

DEFAULT_DSN = "postgresql://mnemosyne:mnemosyne-local-dev@127.0.0.1:54329/mnemosyne"


def run_warm_serial_receipt(
    *,
    warmup_count: int = 2,
    timeout_seconds: float = 1.0,
    inject_outcomes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Emit a schema-stable CAP-006 warm-serial synthetic development receipt."""
    return latency_bench.execute_pinned_workload(
        distribution=latency_bench.DISTRIBUTION_WARM_SERIAL,
        declared_concurrency=1,
        warmup_count=warmup_count,
        timeout_seconds=timeout_seconds,
        inject_outcomes=inject_outcomes,
        command=[sys.executable, str(HERE.relative_to(REPO_ROOT))],
        arguments={
            "warmup_count": warmup_count,
            "timeout_seconds": timeout_seconds,
            "workload": latency_bench.SYNTHETIC_WORKLOAD_ID,
        },
        model_request_count=0,
    )


# --------------------------------------------------------------------------- #
# Warm embedding service lifecycle (started ONCE, models loaded ONCE)
# --------------------------------------------------------------------------- #
def _http_get_json(url: str, timeout: float = 5.0) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 local only
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return None


def _port_in_use(host: str, port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


class WarmEmbeddingService:
    """Start the real embedding service ONCE on the specified port and keep it warm.

    Uses the instrumented launcher so /embed and /rerank are counted (PROVES the
    wired path fired). Started under ``.venv-eval`` so real torch + BGE +
    cross-encoder are available.
    """

    def __init__(self, *, host: str, port: int, force_fallback: bool, counter_file: Path):
        self.host = host
        self.port = port
        self.force_fallback = force_fallback
        self.counter_file = counter_file
        self.base_url = f"http://{host}:{port}"
        self.proc: subprocess.Popen | None = None
        self.health: dict[str, Any] = {}
        self.started_here = False

    @property
    def embed_url(self) -> str:
        return f"{self.base_url}/embed"

    @property
    def rerank_url(self) -> str:
        return f"{self.base_url}/rerank"

    def start(self, *, model_load_timeout: float = 600.0) -> None:
        # If something is already serving on the port and is healthy, reuse it.
        if _port_in_use(self.host, self.port):
            h = _http_get_json(f"{self.base_url}/health", timeout=10.0)
            if h and h.get("status") == "ok":
                self.health = h
                self.started_here = False
                return
            raise RuntimeError(
                f"port {self.host}:{self.port} is occupied but not a healthy embedding service"
            )

        env = dict(os.environ)
        env["EMBEDDING_SERVICE_HOST"] = self.host
        env["EMBEDDING_SERVICE_PORT"] = str(self.port)
        env["EMBEDDING_COUNTER_FILE"] = str(self.counter_file)
        env["PYTHONPATH"] = os.pathsep.join(p for p in (str(SRC), env.get("PYTHONPATH", "")) if p)
        if self.force_fallback:
            env["EMBEDDING_SERVICE_FORCE_FALLBACK"] = "1"

        py = str(VENV_EVAL_PY) if VENV_EVAL_PY.exists() else sys.executable
        launcher = SERVICE_INSTRUMENTED if SERVICE_INSTRUMENTED.exists() else SERVICE_PLAIN
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
                raise RuntimeError(f"embedding service exited early (rc={self.proc.returncode})")
            h = _http_get_json(f"{self.base_url}/health", timeout=10.0)
            if h and h.get("status") == "ok":
                self.health = h
                return
            time.sleep(1.0)
        raise RuntimeError(f"embedding service did not become healthy in {model_load_timeout}s")

    def warm(self, sample_texts: list[str]) -> None:
        for t in sample_texts[:12]:
            try:
                data = json.dumps({"input": t}).encode("utf-8")
                req = urllib.request.Request(
                    self.embed_url, data=data, headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=60.0):  # noqa: S310 local only
                    pass
            except (urllib.error.URLError, OSError, TimeoutError):
                pass

    def backend_kind(self) -> str:
        return str((self.health or {}).get("embedding", {}).get("backend", "unknown"))

    def reranker_kind(self) -> str:
        return str((self.health or {}).get("reranker", {}).get("backend", "unknown"))

    def counters(self) -> dict[str, int]:
        if self.counter_file.exists():
            try:
                return json.loads(self.counter_file.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return _http_get_json(f"{self.base_url}/_counters") or {}

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
# Warm in-process Postgres engine (built ONCE via the exact CLI seam)
# --------------------------------------------------------------------------- #
def build_warm_tools(args_namespace_argv: list[str]):
    """Build a warm ``MemoryTools`` exactly as the CLI does, once."""
    from mnemosyne import cli as mnemo_cli

    parser = mnemo_cli.build_parser()
    args = parser.parse_args(args_namespace_argv)
    return mnemo_cli.load_tools(args)


def _cli_argv(*, dsn: str, embed_url: str, rerank_url: str, model: str, reranker_model: str, dims: int) -> list[str]:
    """The exact CLI argv that selects the real-provider Postgres path."""
    return [
        "--backend", "postgres",
        "--postgres-dsn", dsn,
        "--embedding-provider", "http",
        "--embedding-url", embed_url,
        "--embedding-model", model,
        "--embedding-dims", str(dims),
        "--reranker-provider", "http",
        "--reranker-url", rerank_url,
        "--reranker-model", reranker_model,
        "--lexical-provider", "postgres",
        "--graph-provider", "postgres",
        # The trailing subcommand is required for the parser; values unused by load_tools.
        "search", "--tenant", "x", "--query", "x",
    ]


def build_engine_pool(n: int, argv: list[str]) -> list[Any]:
    """Build N warm, corpus-loaded ``MemoryTools`` clients on the shared Postgres.

    Postgres runtime state is concurrent-safe (row-level, transactional) so all N
    clients share the SAME tenant/corpus in the SAME database. Each client is its
    own ``MemoryTools`` (own connection lifecycle) to mirror N independent server
    workers hitting one shared store — the real long-lived deployment shape.
    """
    return [build_warm_tools(argv) for _ in range(n)]


def load_dataset() -> dict[str, Any]:
    return json.loads(DATASET.read_text())


def capture_corpus(tools, dataset: dict[str, Any], tenant: str) -> int:
    user = dataset.get("user", "eval-user")
    n = 0
    for doc in dataset["corpus"]:
        tools.capture(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type=f"seed:{doc['doc_id']}",
            content=doc["content"],
            trust_tier=int(doc.get("trust_tier", 0)),
        )
        n += 1
    return n


def _tenant_uuid(tenant: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"mnemosyne:tenant:{tenant}"))


def cleanup_tenant(dsn: str, tenant: str) -> dict[str, int]:
    """Delete ONLY this run's tenant rows. Never truncates shared tables."""
    import psycopg

    tid = _tenant_uuid(tenant)
    deleted: dict[str, int] = {}
    # Order: children before parents where FKs exist; evidence is the seeded table.
    # (table_name, tenant_key_column) — the `tenants` parent keys on `id`, not tenant_id.
    targets = [
        ("assertions", "tenant_id"),
        ("relations", "tenant_id"),
        ("justifications", "tenant_id"),
        ("contradictions", "tenant_id"),
        ("preferences", "tenant_id"),
        ("evidence", "tenant_id"),
        ("runtime_state", "tenant_id"),
        ("branches", "tenant_id"),
        ("tenants", "id"),
    ]
    for table, key_col in targets:
        try:
            with psycopg.connect(dsn, connect_timeout=10) as conn, conn.cursor() as cur:
                cur.execute(f"DELETE FROM {table} WHERE {key_col} = %s", (tid,))
                deleted[table] = cur.rowcount
                conn.commit()
        except Exception as exc:  # noqa: BLE001 - best-effort cleanup, report what happened
            deleted[table] = -1
            deleted[f"{table}_error"] = str(exc)[:120]  # type: ignore[assignment]
    return deleted


# --------------------------------------------------------------------------- #
# The bench
# --------------------------------------------------------------------------- #
def run_bench(args: argparse.Namespace) -> dict[str, Any]:
    from mnemosyne.retrieval import HttpEmbeddingProvider

    dataset = load_dataset()
    run_id = secrets.token_hex(4)
    tenant = f"{args.tenant_prefix}-{run_id}"
    queries = [q["query"] for q in dataset["queries"] if q.get("answerable", True)] or [
        q["query"] for q in dataset["queries"]
    ]

    counter_file = Path("/tmp") / f"mnemo_warm_counters_{os.getpid()}.json"

    # --- warm the embedding service (ONCE; models load ONCE) ---
    svc = WarmEmbeddingService(
        host=args.embed_host,
        port=args.embed_port,
        force_fallback=args.force_fallback,
        counter_file=counter_file,
    )
    s0 = time.perf_counter()
    svc.start(model_load_timeout=args.model_load_timeout)
    svc.warm(queries + [doc["content"] for doc in dataset["corpus"]])
    svc_start_ms = (time.perf_counter() - s0) * 1000.0

    backend_kind = svc.backend_kind()
    is_real = backend_kind in ("sentence-transformers", "cross-encoder")
    if not is_real and not args.allow_fallback:
        svc.stop()
        raise SystemExit(
            f"embedding service came up as '{backend_kind}' (deterministic fallback), not the real "
            f"model. Re-run under .venv-eval without --force-fallback, or pass --allow-fallback to "
            f"accept fallback numbers."
        )

    argv = _cli_argv(
        dsn=args.postgres_dsn,
        embed_url=svc.embed_url,
        rerank_url=svc.rerank_url,
        model=args.embedding_model,
        reranker_model=args.reranker_model,
        dims=int(args.embedding_dims),
    )

    # --- build the warm engine pool (ONCE) and seed the corpus (ONCE) ---
    t0 = time.perf_counter()
    engine_pool = build_engine_pool(args.clients, argv)
    n_docs = capture_corpus(engine_pool[0], dataset, tenant)  # seed once on shared store
    engine_warm_ms = (time.perf_counter() - t0) * 1000.0

    # Production HTTP embedding adapter (exact src adapter) -> warm service, for the
    # isolated embed-call measurement.
    embedder = HttpEmbeddingProvider(
        url=svc.embed_url,
        model=args.embedding_model,
        dims=int(args.embedding_dims),
        timeout_seconds=float(args.retrieval_timeout),
    )

    # --- warm-up rounds (JIT / page cache / pgvector plan cache / conn reuse) ---
    for idx, q in enumerate(queries[: max(2, args.clients)]):
        try:
            embedder.embed(q)
        except Exception:  # noqa: BLE001
            pass
        try:
            engine_pool[idx % len(engine_pool)].search(tenant_id=tenant, query=q)
        except Exception:  # noqa: BLE001
            pass

    # --- the measured concurrent load: N clients x M queries ---
    n_clients = args.clients
    m_queries = args.queries
    tasks = [(i % n_clients, queries[i % len(queries)]) for i in range(n_clients * m_queries)]

    embed_ms: list[float] = []
    engine_ms: list[float] = []
    derived_minus: list[float] = []
    errors: list[str] = []

    def _one(item: tuple[int, str]) -> tuple[float, float, str | None]:
        client_idx, query = item
        client_tools = engine_pool[client_idx]
        err: str | None = None
        # Isolated embed-call latency (warm model-inference HTTP round-trip).
        e0 = time.perf_counter()
        try:
            embedder.embed(query)
            e = (time.perf_counter() - e0) * 1000.0
        except Exception as exc:  # noqa: BLE001
            e = (time.perf_counter() - e0) * 1000.0
            err = f"embed: {type(exc).__name__}: {exc}"
        # TRUE warm fast-path: full in-process MemoryTools.search() (the SLO number).
        g0 = time.perf_counter()
        try:
            client_tools.search(tenant_id=tenant, query=query)
            g = (time.perf_counter() - g0) * 1000.0
        except Exception as exc:  # noqa: BLE001
            g = (time.perf_counter() - g0) * 1000.0
            err = (err + " | " if err else "") + f"engine: {type(exc).__name__}: {exc}"
        return e, g, err

    wall0 = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=n_clients) as pool:
        for e, g, err in pool.map(_one, tasks):
            embed_ms.append(e)
            engine_ms.append(g)
            derived_minus.append(max(0.0, g - e))
            if err:
                errors.append(err)
    wall_ms = (time.perf_counter() - wall0) * 1000.0

    counters = svc.counters()
    health = svc.health
    reranker_kind = svc.reranker_kind()
    svc.stop()

    # --- cleanup our own tenant rows (never truncate shared tables) ---
    cleanup: dict[str, int] = {}
    if not args.keep_data:
        cleanup = cleanup_tenant(args.postgres_dsn, tenant)

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
    engine_block = _component("engine_fast_path_total", engine_ms)
    minus_block = _component("engine_minus_embed", derived_minus)

    throughput_qps = (len(engine_ms) / (wall_ms / 1000.0)) if wall_ms > 0 else 0.0

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
        "bench": "warm_server_fast_path_latency_postgres",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "blueprint_refs": ["§15 fast-path P95 NFR", "FR-3", "§16 SLO"],
        "fixes_prior_artifact": {
            "subprocess_per_query": (
                "ELIMINATED: engine built ONCE per client via cli.build_parser->load_tools->"
                "MemoryTools; queries run in-process (no per-query python -m mnemosyne.cli)."
            ),
            "cold_model_roundtrip_per_query": (
                "ELIMINATED: real embedding service started ONCE on the specified port, models "
                "loaded ONCE, warmed before measurement."
            ),
            "prior_bench_reference": "eval/latency/bench.py (local backend) + Wave-2 fast_path suite",
        },
        "config": {
            "backend": "postgres",
            "postgres_dsn_host": args.postgres_dsn.split("@")[-1] if "@" in args.postgres_dsn else "n/a",
            "tenant": tenant,
            "tenant_uuid": _tenant_uuid(tenant),
            "distinct_tenant_prefix": args.tenant_prefix,
            "shared_tables_truncated": False,
            "clients": n_clients,
            "queries_per_client": m_queries,
            "total_calls": len(engine_ms),
            "embedding_url": svc.embed_url,
            "reranker_url": svc.rerank_url,
            "embedding_model": args.embedding_model,
            "reranker_model": args.reranker_model,
            "embedding_dims": int(args.embedding_dims),
            "lexical_provider": "postgres",
            "graph_provider": "postgres",
            "force_fallback": args.force_fallback,
            "dataset": str(DATASET.relative_to(REPO_ROOT)),
            "n_corpus_docs": n_docs,
            "n_unique_queries": len(queries),
            "venv": str(VENV_EVAL_PY),
        },
        "warm_costs_paid_once_ms": {
            "engine_build_and_corpus_capture": round(engine_warm_ms, 2),
            "embedding_service_start_and_model_load": round(svc_start_ms, 2),
            "note": "Paid ONCE for a long-lived server, NOT per request.",
        },
        "embedding_service": {
            "backend": backend_kind,
            "reranker_backend": reranker_kind,
            "is_real_model": is_real,
            "health": health,
            "request_counters": counters,
            "proved_wired_embed": bool(counters.get("POST /embed", 0) > 0),
            "proved_wired_rerank": bool(counters.get("POST /rerank", 0) > 0),
        },
        "wall_clock_ms": round(wall_ms, 2),
        "throughput_qps": round(throughput_qps, 2),
        "components": {
            "embed_call_only": embed_block,
            "engine_fast_path_total": engine_block,
            "engine_minus_embed": minus_block,
        },
        "verdicts": [
            _verdict("engine_fast_path_total_p95", engine_block["p95_ms"], engine_block["p95_ci"]),
            _verdict("embed_call_only_p95", embed_block["p95_ms"], embed_block["p95_ci"]),
        ],
        "tenant_cleanup": cleanup,
        "errors": errors[:20],
        "n_errors": len(errors),
    }
    return report


def write_reports(report: dict[str, Any]) -> tuple[Path, Path]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = REPORTS_DIR / f"warm_latency_{stamp}.json"
    json_path.write_text(json.dumps(report, indent=2))
    (REPORTS_DIR / "warm_latency_latest.json").write_text(json.dumps(report, indent=2))
    md = render_markdown(report)
    md_path = REPORTS_DIR / f"warm_latency_{stamp}.md"
    md_path.write_text(md)
    (REPORTS_DIR / "warm_latency_latest.md").write_text(md)
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

    engine = comp["engine_fast_path_total"]
    pass_loose = engine["p95_ms"] <= BUDGET_P95_MS_LOOSE
    pass_tight = engine["p95_ms"] <= BUDGET_P95_MS_TIGHT
    verdict_line = ("PASS (<=400 ms)" if pass_loose else "FAIL (> 400 ms budget)") + (
        " / PASS (<=300 ms)" if pass_tight else " / FAIL (>300 ms)"
    )

    lines = [
        "# Warm-Server Fast-Path P95 Latency Harness (Postgres real-provider path)",
        "",
        f"Generated: {r['generated_at']}",
        f"Blueprint: {', '.join(r['blueprint_refs'])}",
        "",
        "## What this fixes (subprocess-per-query artifact)",
        "",
        f"- Subprocess/query: {r['fixes_prior_artifact']['subprocess_per_query']}",
        f"- Cold model round-trip/query: {r['fixes_prior_artifact']['cold_model_roundtrip_per_query']}",
        "",
        "## Warm-server setup (paid ONCE, NOT per request)",
        "",
        f"- Engine build + corpus capture: **{warm['engine_build_and_corpus_capture']} ms** (once)",
        f"- Embedding service start + model load: **{warm['embedding_service_start_and_model_load']} ms** (once)",
        f"- Embedding backend: **{svc['backend']}** "
        f"({'REAL model' if svc['is_real_model'] else 'deterministic fallback'}), "
        f"reranker: **{svc['reranker_backend']}**",
        f"- Wired path proved: POST /embed={svc['proved_wired_embed']}, "
        f"POST /rerank={svc['proved_wired_rerank']} (counters: {json.dumps(svc['request_counters'])})",
        "",
        "## Store / isolation",
        "",
        f"- Backend: **postgres** ({c['postgres_dsn_host']}), reused running container",
        f"- Distinct tenant: **`{c['tenant']}`** -> uuid `{c['tenant_uuid']}` "
        f"(prefix `{c['distinct_tenant_prefix']}`)",
        f"- Shared tables truncated: **{c['shared_tables_truncated']}** "
        f"(only this tenant's rows seeded/cleaned)",
        f"- Lexical provider: **{c['lexical_provider']}**, graph provider: **{c['graph_provider']}**",
        "",
        "## Load",
        "",
        f"- {c['clients']} concurrent clients x {c['queries_per_client']} queries "
        f"= **{c['total_calls']} calls** (in-process, no subprocess)",
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
        row(comp["engine_fast_path_total"]),
        row(comp["engine_minus_embed"]),
        "",
        "Component meaning:",
        "- **embed_call_only** — isolated warm HTTP round-trip to the real embedding service "
        "(model-inference cost), via the production `HttpEmbeddingProvider`.",
        "- **engine_fast_path_total** — one warm in-process `MemoryTools.search()`: the TRUE "
        "warm fast path (query embed + dense pgvector search + lexical FTS + RRF fuse + "
        "cross-encoder rerank + MMR + calibrate + budget). This is the SLO number. It already "
        "INCLUDES its own internal embed/rerank HTTP calls.",
        "- **engine_minus_embed** — `engine - embed` per call: approximate non-embed engine work "
        "(SQL retrieve + fuse + rerank orchestration + MMR + calibrate). Transparency only.",
        "",
        f"## Verdict vs §15/§16 budget (P95 <= {int(BUDGET_P95_MS_TIGHT)}-{int(BUDGET_P95_MS_LOOSE)} ms)",
        "",
        f"**engine_fast_path_total P95 = {engine['p95_ms']} ms -> {verdict_line}**",
        "",
        f"- embed_call_only P95 = {comp['embed_call_only']['p95_ms']} ms "
        f"({'<=' if comp['embed_call_only']['p95_ms'] <= BUDGET_P95_MS_LOOSE else '>'} 400 ms)",
        f"- engine_minus_embed P95 = {comp['engine_minus_embed']['p95_ms']} ms",
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
    engine_p95 = comp["engine_fast_path_total"]["p95_ms"]
    embed_p95 = comp["embed_call_only"]["p95_ms"]
    minus_p95 = comp["engine_minus_embed"]["p95_ms"]
    real = svc["is_real_model"]
    parts: list[str] = []

    if engine_p95 <= BUDGET_P95_MS_LOOSE:
        parts.append(
            f"The **warm Postgres fast path meets the budget**: engine P95 {engine_p95} ms <= 400 ms "
            f"once the server is warm and queries run in-process. The prior multi-second 'engine' "
            f"number was per-process Python cold-start, not the engine."
        )
    else:
        parts.append(
            f"Even warm and in-process, the **Postgres fast-path P95 is {engine_p95} ms** "
            f"({'<=' if engine_p95 <= BUDGET_P95_MS_TIGHT else '>'} 300 ms; "
            f"{'<=' if engine_p95 <= BUDGET_P95_MS_LOOSE else '>'} 400 ms) — a genuine end-to-end cost, "
            f"NOT a subprocess artifact. This is reported honestly against the §15/§16 budget."
        )

    backend = "real BGE + cross-encoder" if real else "deterministic fallback (no torch path active)"
    parts.append(
        f"Decomposition ({backend}): isolated **embed call** P95 {embed_p95} ms; **non-embed engine "
        f"work** (SQL dense+lexical retrieve, RRF, MMR, calibrate, budget) P95 {minus_p95} ms. The full "
        f"`search()` also re-embeds rerank candidates via the cross-encoder, so engine_total > "
        f"embed + (single) non-embed in general."
    )

    if engine_p95 > BUDGET_P95_MS_LOOSE:
        parts.append(
            "Gap-closers, in priority order:\n"
            "  1. **Query-embedding cache + persisted doc vectors.** Doc vectors are already written at "
            "capture time (pgvector); caching query->vector turns repeat/near-repeat embeds into "
            "single-digit-ms cache hits and removes the synchronous model round-trip from the hot path.\n"
            "  2. **In-process / co-located embedder.** Co-locate BGE-small in the server process (no "
            "HTTP/JSON hop); on GPU, query embedding is sub-10 ms vs the measured HTTP round-trip.\n"
            "  3. **Cross-encoder off the hot path.** Rerank only a small ANN+lexical candidate set (or "
            "use a cheaper reranker / cache rerank scores) so model cost scales with N, not corpus size.\n"
            "  4. **Connection pooling / prepared statements.** Reuse pgvector query plans and pooled "
            "connections to shave per-call SQL setup."
        )
    if not real:
        parts.append(
            "NOTE: this run used the **deterministic fallback** encoder (real torch path not active). "
            "Re-run under .venv-eval without --force-fallback for production embed-cost numbers."
        )
    return "\n\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clients", type=int, default=8, help="concurrent clients N (default 8)")
    ap.add_argument("--queries", type=int, default=25, help="queries per client M (default 25)")
    ap.add_argument("--postgres-dsn", default=os.environ.get("MNEMOSYNE_POSTGRES_DSN", DEFAULT_DSN))
    ap.add_argument("--tenant-prefix", default="warm-latency-eval",
                    help="distinct tenant prefix; a random run-id is appended (default warm-latency-eval)")
    ap.add_argument("--embed-host", default="127.0.0.1")
    ap.add_argument("--embed-port", type=int, default=int(os.environ.get("EMBEDDING_SERVICE_PORT", "8099")))
    ap.add_argument("--embedding-model", default="BAAI/bge-small-en-v1.5")
    ap.add_argument("--reranker-model", default="cross-encoder/ms-marco-MiniLM-L-6-v2")
    ap.add_argument("--embedding-dims", type=int, default=1024)
    ap.add_argument("--retrieval-timeout", type=float, default=30.0)
    ap.add_argument("--model-load-timeout", type=float, default=600.0)
    ap.add_argument("--force-fallback", action="store_true", help="force the deterministic fallback encoder")
    ap.add_argument("--allow-fallback", action="store_true",
                    help="do not abort if the real model is unavailable (accept fallback numbers)")
    ap.add_argument("--keep-data", action="store_true", help="do not delete this run's tenant rows afterward")
    ap.add_argument("--json-only", action="store_true")
    args = ap.parse_args()

    report = run_bench(args)
    json_path, md_path = write_reports(report)

    if args.json_only:
        print(json.dumps(report, indent=2))
    else:
        print(render_markdown(report))
        print(f"\n[warm-bench] JSON  -> {json_path}")
        print(f"[warm-bench] MD    -> {md_path}")
        print(f"[warm-bench] latest -> {md_path.parent / 'warm_latency_latest.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
