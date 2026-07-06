#!/usr/bin/env python3
"""MCP client-workflow trace harness (Phase 4 C4 gate evidence).

`docs/superpowers/plans/phase4-front-end.md` gates the C4 `mneme-native` Rust
MCP front-end on a captured client-workflow trace, not a synthetic one-shot
process timer. The gate demands (plan sections "Gate" and "T1. Trace Harness"):

  * p50/p95 for spawn, ``initialize``, ``tools/list``, first read-only tool
    call, warm steady-state read-only call, and process teardown;
  * attribution of where the latency lives: Python import, durable store
    initialization, object/key custody, queue setup, or client orchestration.

What this harness does:

  * COLD sessions (default 20 per spawn mode): a fresh `mneme-mcp` stdio
    subprocess each time, speaking newline-delimited JSON-RPC exactly like the
    production `serve()` loop expects: ``initialize`` ->
    ``notifications/initialized`` -> ``tools/list`` -> one read-only
    ``tools/call`` (``residency_policy``) -> stdin close + wait (teardown).
    Two spawn modes separate client orchestration from server cost:
      - ``uv``   : ``uv run --locked mneme-mcp`` (how a client config that
                   shells through uv would launch it);
      - ``venv`` : the installed ``.venv/bin/mneme-mcp`` console script (the
                   direct entry point a tuned client config would use).
  * WARM session (default 50 calls): one long-lived server, 50 sequential
    read-only calls -> steady-state per-call latency; plus repeated
    ``initialize`` round-trips on the warm server, which isolate the
    initialize *handler* cost (statically-built response) from process spawn.
  * Attribution probes: interpreter-only startup (`python -c pass`), uv
    wrapper overhead (`uv run --locked python -c pass`), and one
    ``-X importtime`` capture of ``import mnemosyne.mcp_server`` broken down
    by module.

Isolation: every server subprocess gets a private temp MNEMOSYNE_HOME-style
directory (store, object store, parametric artifact store) and a child
environment with ALL inherited ``MNEMOSYNE_*``/``MNEME_*`` variables stripped,
so nothing touches real data and the boot is the local no-auth dev profile
(local JSON backend, no production profile, no session requirement). No new
environment variables are introduced or read by this harness.

Run:
    uv run --locked python eval/latency/mcp_trace.py
    uv run --locked python eval/latency/mcp_trace.py --cold-spawns 5 --warm-calls 10
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

HERE = Path(__file__).resolve()
EVAL_DIR = HERE.parents[1]
REPO_ROOT = HERE.parents[2]
SRC = REPO_ROOT / "src"
REPORTS_DIR = HERE.parent / "reports"
VENV_MCP = REPO_ROOT / ".venv" / "bin" / "mneme-mcp"
VENV_PY = REPO_ROOT / ".venv" / "bin" / "python"

# Reuse the Wave-1 metrics helpers (same convention as eval/latency/bench.py).
for _p in (str(SRC), str(EVAL_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from harness.metrics import percentile  # noqa: E402  (path set above)

# Plan reference numbers (docs/superpowers/plans/phase4-front-end.md).
# "Current Evidence": stdio initialize median ~116 ms, which the plan itself
# calls not enough evidence for C4. "Exit Criteria": Rust handshake p95 <= 50ms.
PLAN_REFERENCE_STDIO_INIT_MS = 116.0
PLAN_RUST_HANDSHAKE_TARGET_MS = 50.0
# The plan's own decision rule is qualitative: "If the evidence stays near
# today's local numbers, keep the current Python MCP entry point." We encode
# "near" as within 1.5x of the recorded 116 ms reference for the direct
# (venv) entry point; anything inside that band cannot open the gate.
NEAR_BAND_FACTOR = 1.5

_INITIALIZE_PARAMS = {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": {"name": "mcp-trace-harness", "version": "0.1"},
}
_READ_ONLY_TOOL = "residency_policy"  # no-argument read-only tool (mcp_tools.py)


class _LineReader:
    """Background line reader so response waits can time out without hanging."""

    def __init__(self, stream: TextIO) -> None:
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread = threading.Thread(target=self._pump, args=(stream,), daemon=True)
        self._thread.start()

    def _pump(self, stream: TextIO) -> None:
        for line in stream:
            self._queue.put(line)
        self._queue.put(None)

    def readline(self, timeout: float) -> str:
        try:
            line = self._queue.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError(f"no MCP response within {timeout:.0f}s") from exc
        if line is None:
            raise RuntimeError("MCP server closed stdout before responding")
        return line


def _drain(stream: TextIO, sink: list[str]) -> None:
    for line in stream:
        sink.append(line.rstrip("\n"))


def _child_env(tmp: Path) -> dict[str, str]:
    """Local no-auth dev boot: strip inherited Mnemosyne config, use temp dirs."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("MNEMOSYNE_", "MNEME_"))}
    env.update(
        {
            "MNEME_BACKEND": "local",
            "MNEME_STORE": str(tmp / "mcp-store.json"),
            "MNEMOSYNE_OBJECT_STORE": str(tmp / "objects"),
            "MNEMOSYNE_PARAMETRIC_ARTIFACT_STORE": str(tmp / "parametric"),
        }
    )
    return env


class McpSession:
    """One stdio MCP server subprocess speaking newline-delimited JSON-RPC."""

    def __init__(self, cmd: list[str], env: dict[str, str]) -> None:
        self.cmd = cmd
        self.stderr_lines: list[str] = []
        self.spawn_started = time.perf_counter()
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=REPO_ROOT,
            env=env,
        )
        assert self.proc.stdin and self.proc.stdout and self.proc.stderr
        self._reader = _LineReader(self.proc.stdout)
        self._stderr_thread = threading.Thread(
            target=_drain, args=(self.proc.stderr, self.stderr_lines), daemon=True
        )
        self._stderr_thread.start()
        self._next_id = 0

    def request(self, method: str, params: dict[str, Any] | None = None, timeout: float = 60.0) -> tuple[dict[str, Any], float]:
        """Send one request, wait for its response; returns (response, round-trip ms)."""
        self._next_id += 1
        req: dict[str, Any] = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            req["params"] = params
        started = time.perf_counter()
        self.proc.stdin.write(json.dumps(req, separators=(",", ":")) + "\n")
        self.proc.stdin.flush()
        try:
            line = self._reader.readline(timeout)
        except (TimeoutError, RuntimeError) as exc:
            raise RuntimeError(
                f"{method} failed for {self.cmd!r}: {exc}; stderr tail: {self.stderr_lines[-5:]}"
            ) from exc
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        response = json.loads(line)
        if response.get("id") != self._next_id or "error" in response:
            raise RuntimeError(f"unexpected MCP response to {method}: {response}")
        return response, elapsed_ms

    def notify(self, method: str) -> None:
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}, separators=(",", ":")) + "\n")
        self.proc.stdin.flush()

    def teardown(self, timeout: float = 30.0) -> float:
        """Close stdin, wait for exit; returns wall ms."""
        started = time.perf_counter()
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)
            raise RuntimeError(f"server did not exit on stdin close: {self.cmd!r}")
        return (time.perf_counter() - started) * 1000.0


def _check_initialize(response: dict[str, Any]) -> None:
    info = response.get("result", {}).get("serverInfo", {})
    if info.get("name") != "mnemosyne-memory":
        raise RuntimeError(f"unexpected serverInfo: {info}")


def _check_tools_list(response: dict[str, Any]) -> int:
    tools = response.get("result", {}).get("tools", [])
    names = {tool.get("name") for tool in tools}
    if _READ_ONLY_TOOL not in names:
        raise RuntimeError(f"tools/list missing {_READ_ONLY_TOOL}; got {sorted(names)[:5]}...")
    return len(tools)


def _check_tool_call(response: dict[str, Any]) -> None:
    result = response.get("result", {})
    if result.get("isError") is not False or not result.get("content"):
        raise RuntimeError(f"read-only tool call failed: {result}")


def _run_cold_session(cmd: list[str], timeout: float) -> dict[str, float]:
    """One fresh spawn -> initialize -> tools/list -> tool call -> teardown."""
    tmp = Path(tempfile.mkdtemp(prefix="mnemo-mcp-trace-"))
    try:
        session = McpSession(cmd, _child_env(tmp))
        try:
            response, _ = session.request("initialize", _INITIALIZE_PARAMS, timeout=timeout)
            spawn_initialize_ms = (time.perf_counter() - session.spawn_started) * 1000.0
            _check_initialize(response)
            session.notify("notifications/initialized")
            response, tools_list_ms = session.request("tools/list", timeout=timeout)
            _check_tools_list(response)
            response, first_call_ms = session.request(
                "tools/call", {"name": _READ_ONLY_TOOL, "arguments": {}}, timeout=timeout
            )
            _check_tool_call(response)
        finally:
            teardown_ms = session.teardown()
        return {
            "spawn_initialize_ms": spawn_initialize_ms,
            "tools_list_ms": tools_list_ms,
            "first_tool_call_ms": first_call_ms,
            "teardown_ms": teardown_ms,
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run_warm_session(cmd: list[str], warm_calls: int, timeout: float) -> dict[str, Any]:
    """One long-lived server; steady-state calls + warm initialize round-trips."""
    tmp = Path(tempfile.mkdtemp(prefix="mnemo-mcp-trace-warm-"))
    try:
        session = McpSession(cmd, _child_env(tmp))
        try:
            response, _ = session.request("initialize", _INITIALIZE_PARAMS, timeout=timeout)
            _check_initialize(response)
            session.notify("notifications/initialized")
            response, _ = session.request("tools/list", timeout=timeout)
            tool_count = _check_tools_list(response)
            response, first_call_ms = session.request(
                "tools/call", {"name": _READ_ONLY_TOOL, "arguments": {}}, timeout=timeout
            )
            _check_tool_call(response)
            warm_call_ms: list[float] = []
            for _ in range(warm_calls):
                response, elapsed = session.request(
                    "tools/call", {"name": _READ_ONLY_TOOL, "arguments": {}}, timeout=timeout
                )
                _check_tool_call(response)
                warm_call_ms.append(elapsed)
            # Repeated initialize on the warm server: the handler builds a
            # static response, so this round-trip bounds the non-spawn share
            # of the cold "initialize" stage.
            warm_initialize_ms: list[float] = []
            for _ in range(10):
                response, elapsed = session.request("initialize", _INITIALIZE_PARAMS, timeout=timeout)
                _check_initialize(response)
                warm_initialize_ms.append(elapsed)
        finally:
            teardown_ms = session.teardown()
        return {
            "tool_count": tool_count,
            "first_tool_call_ms": first_call_ms,
            "warm_call_ms": warm_call_ms,
            "warm_initialize_rpc_ms": warm_initialize_ms,
            "teardown_ms": teardown_ms,
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _time_command(cmd: list[str], runs: int) -> list[float]:
    samples = []
    for _ in range(runs):
        started = time.perf_counter()
        subprocess.run(cmd, cwd=REPO_ROOT, check=True, capture_output=True)
        samples.append((time.perf_counter() - started) * 1000.0)
    return samples


_IMPORTTIME_RE = re.compile(r"import time:\s+(\d+)\s+\|\s+(\d+)\s+\|(\s*)(\S+)")


def _capture_importtime(runs: int = 3) -> dict[str, Any]:
    """-X importtime attribution for the MCP server import graph.

    Takes the minimum-total run of ``runs`` captures: importtime adds
    instrumentation overhead and single captures are noisy under host load,
    so the minimum is the cleanest attribution of the import graph itself.
    """
    best: subprocess.CompletedProcess[str] | None = None
    best_total = float("inf")
    for _ in range(runs):
        proc = subprocess.run(
            [str(VENV_PY), "-X", "importtime", "-c", "import mnemosyne.mcp_server"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        total = sum(
            int(match.group(1)) for match in map(_IMPORTTIME_RE.match, proc.stderr.splitlines()) if match
        )
        if total < best_total:
            best_total = total
            best = proc
    assert best is not None
    proc = best
    rows = []
    for line in proc.stderr.splitlines():
        match = _IMPORTTIME_RE.match(line)
        if match:
            self_us, cumulative_us, indent, name = match.groups()
            rows.append(
                {
                    "module": name,
                    "self_ms": int(self_us) / 1000.0,
                    "cumulative_ms": int(cumulative_us) / 1000.0,
                    "depth": len(indent) // 2,
                }
            )
    total_ms = sum(row["self_ms"] for row in rows)
    top = sorted(rows, key=lambda row: row["self_ms"], reverse=True)[:12]
    roots = [row for row in rows if row["depth"] == 1]
    return {
        "total_import_ms": total_ms,
        "runs": runs,
        "selection": "min-total",
        "top_self": top,
        "top_level": roots,
        "module_count": len(rows),
    }


def _summary(samples: list[float]) -> dict[str, float]:
    return {
        "n": len(samples),
        "p50_ms": percentile(samples, 0.50),
        "p95_ms": percentile(samples, 0.95),
        "mean_ms": sum(samples) / len(samples),
        "min_ms": min(samples),
        "max_ms": max(samples),
    }


def _fmt(summary: dict[str, float]) -> str:
    return (
        f"| {summary['p50_ms']:.1f} | {summary['p95_ms']:.1f} | {summary['mean_ms']:.1f} "
        f"| {summary['min_ms']:.1f} | {summary['max_ms']:.1f} | {summary['n']} |"
    )


def _gate_verdict(report: dict[str, Any]) -> dict[str, Any]:
    """Apply the plan's own decision rule to the measured trace."""
    venv = report["cold"]["venv"]["spawn_initialize_ms"]
    uv = report["cold"]["uv"]["spawn_initialize_ms"]
    warm = report["warm"]["warm_call_ms"]
    near_band_ms = PLAN_REFERENCE_STDIO_INIT_MS * NEAR_BAND_FACTOR
    reasons = []
    stays_near = venv["p50_ms"] <= near_band_ms
    if stays_near:
        reasons.append(
            f"direct-entry spawn+initialize p50 {venv['p50_ms']:.1f} ms is within the plan's "
            f"'near today's local numbers' band (<= {near_band_ms:.0f} ms vs the recorded "
            f"{PLAN_REFERENCE_STDIO_INIT_MS:.0f} ms median)"
        )
    orchestration_ms = uv["p50_ms"] - venv["p50_ms"]
    if orchestration_ms > venv["p50_ms"] * 0.25:
        reasons.append(
            f"uv-wrapper launch adds {orchestration_ms:.1f} ms p50 over the direct entry point: "
            "client orchestration, fixable by pointing the client at .venv/bin/mneme-mcp, not by a Rust front-end"
        )
    reasons.append(
        f"warm steady-state read-only call p95 is {warm['p95_ms']:.2f} ms: spawn cost is a "
        "once-per-session cost, not a per-call tax"
    )
    justified = not stays_near
    return {
        "justified": justified,
        "verdict": "GATE STAYS CLOSED - do not build the C4 Rust front-end" if not justified else "GATE CANDIDATE OPEN - escalate to operator with this trace",
        "plan_reference_median_ms": PLAN_REFERENCE_STDIO_INIT_MS,
        "near_band_ms": near_band_ms,
        "rust_handshake_target_ms": PLAN_RUST_HANDSHAKE_TARGET_MS,
        "reasons": reasons,
    }


def run(cold_spawns: int, warm_calls: int, timeout: float) -> dict[str, Any]:
    uv_cmd = ["uv", "run", "--locked", "mneme-mcp"]
    venv_cmd = [str(VENV_MCP)]

    cold: dict[str, Any] = {}
    for label, cmd in (("uv", uv_cmd), ("venv", venv_cmd)):
        stage_samples: dict[str, list[float]] = {}
        for _ in range(cold_spawns):
            stages = _run_cold_session(cmd, timeout)
            for stage, value in stages.items():
                stage_samples.setdefault(stage, []).append(value)
        cold[label] = {stage: _summary(values) for stage, values in stage_samples.items()}

    warm_raw = _run_warm_session(uv_cmd, warm_calls, timeout)
    warm = {
        "tool_count": warm_raw["tool_count"],
        "first_tool_call_ms": warm_raw["first_tool_call_ms"],
        "warm_call_ms": _summary(warm_raw["warm_call_ms"]),
        "warm_initialize_rpc_ms": _summary(warm_raw["warm_initialize_rpc_ms"]),
        "teardown_ms": warm_raw["teardown_ms"],
    }

    interpreter_ms = _summary(_time_command([str(VENV_PY), "-c", "pass"], 10))
    uv_python_ms = _summary(_time_command(["uv", "run", "--locked", "python", "-c", "pass"], 5))
    importtime = _capture_importtime()

    venv_p50 = cold["venv"]["spawn_initialize_ms"]["p50_ms"]
    attribution = {
        "interpreter_startup": interpreter_ms,
        "uv_run_python_startup": uv_python_ms,
        "uv_wrapper_overhead_p50_ms": uv_python_ms["p50_ms"] - interpreter_ms["p50_ms"],
        "importtime": importtime,
        # Residual after interpreter startup and imports: argparse + server
        # construction (temp-store engine build, object store, queue setup)
        # + one initialize round-trip. The warm initialize RPC bounds the
        # handler share of that round-trip.
        "post_import_residual_p50_ms": venv_p50
        - interpreter_ms["p50_ms"]
        - importtime["total_import_ms"],
        "initialize_handler_bound_p50_ms": warm["warm_initialize_rpc_ms"]["p50_ms"],
    }

    report: dict[str, Any] = {
        "report": "mcp-client-workflow-trace",
        "plan": "docs/superpowers/plans/phase4-front-end.md",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
        },
        "config": {
            "cold_spawns_per_mode": cold_spawns,
            "warm_calls": warm_calls,
            "read_only_tool": _READ_ONLY_TOOL,
            "spawn_commands": {"uv": uv_cmd, "venv": venv_cmd},
            # Redacted env metadata: the child env strips every inherited
            # MNEMOSYNE_*/MNEME_* variable and sets only these keys, each
            # pointing into a per-session private temp directory.
            "child_env_keys_set": [
                "MNEME_BACKEND=local",
                "MNEME_STORE=<per-session tmpdir>/mcp-store.json",
                "MNEMOSYNE_OBJECT_STORE=<per-session tmpdir>/objects",
                "MNEMOSYNE_PARAMETRIC_ARTIFACT_STORE=<per-session tmpdir>/parametric",
            ],
            "inherited_mnemosyne_env": "stripped",
        },
        "cold": cold,
        "warm": warm,
        "attribution": attribution,
    }
    report["gate"] = _gate_verdict(report)
    return report


def _render_markdown(report: dict[str, Any]) -> str:
    gate = report["gate"]
    lines = [
        "# MCP Client-Workflow Trace (Phase 4 C4 Gate Evidence)",
        "",
        f"Generated: {report['generated_utc']}  ",
        f"Host: {report['host']['platform']} / Python {report['host']['python']} / {report['host']['cpu_count']} CPUs  ",
        f"Plan: `{report['plan']}`",
        "",
        f"Workload: {report['config']['cold_spawns_per_mode']} cold spawns per mode "
        f"(fresh process, fresh temp store each) + 1 warm session with "
        f"{report['config']['warm_calls']} sequential read-only `{report['config']['read_only_tool']}` calls. "
        "Newline JSON-RPC over stdio against the production `serve()` loop; local no-auth dev boot "
        "(local JSON backend in a per-session temp dir, all inherited `MNEMOSYNE_*`/`MNEME_*` env stripped).",
        "",
        "## Cold-session stages (per fresh spawn)",
        "",
        "| Mode | Stage | p50 ms | p95 ms | mean ms | min ms | max ms | n |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    stage_order = ["spawn_initialize_ms", "tools_list_ms", "first_tool_call_ms", "teardown_ms"]
    stage_names = {
        "spawn_initialize_ms": "spawn -> initialize response",
        "tools_list_ms": "tools/list",
        "first_tool_call_ms": "first tool call",
        "teardown_ms": "teardown (stdin close -> exit)",
    }
    for mode in ("uv", "venv"):
        for stage in stage_order:
            lines.append(f"| {mode} | {stage_names[stage]} {_fmt(report['cold'][mode][stage])}")
    warm = report["warm"]
    lines += [
        "",
        "`uv` mode launches via `uv run --locked mneme-mcp`; `venv` mode launches the installed "
        "`.venv/bin/mneme-mcp` console script directly. The delta between them is pure client "
        "orchestration cost.",
        "",
        "## Warm session (one long-lived server)",
        "",
        "| Stage | p50 ms | p95 ms | mean ms | min ms | max ms | n |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| steady-state read-only call {_fmt(warm['warm_call_ms'])}",
        f"| initialize RPC on warm server {_fmt(warm['warm_initialize_rpc_ms'])}",
        "",
        f"First tool call in the warm session: {warm['first_tool_call_ms']:.2f} ms; "
        f"teardown: {warm['teardown_ms']:.2f} ms; tools listed: {warm['tool_count']}.",
        "",
        "## Attribution",
        "",
    ]
    attr = report["attribution"]
    it = attr["importtime"]
    lines += [
        "| Component | p50 ms | Note |",
        "|---|---:|---|",
        f"| Interpreter startup (`python -c pass`) | {attr['interpreter_startup']['p50_ms']:.1f} | venv python |",
        f"| uv wrapper overhead | {attr['uv_wrapper_overhead_p50_ms']:.1f} | `uv run --locked python -c pass` minus interpreter startup |",
        f"| `import mnemosyne.mcp_server` | {it['total_import_ms']:.1f} | -X importtime cumulative "
        f"(min of {it['runs']} captures), {it['module_count']} modules |",
        f"| Post-import residual | {attr['post_import_residual_p50_ms']:.1f} | approximate: argparse + "
        "engine/object-store/queue construction + initialize round-trip; importtime instrumentation "
        "overhead can push this slightly negative |",
        f"| initialize handler share | {attr['initialize_handler_bound_p50_ms']:.2f} | warm initialize RPC round-trip (bounds the non-spawn share) |",
        "",
        "Top import-time contributors (self time):",
        "",
        "| Module | self ms | cumulative ms |",
        "|---|---:|---:|",
    ]
    for row in it["top_self"][:10]:
        lines.append(f"| `{row['module']}` | {row['self_ms']:.1f} | {row['cumulative_ms']:.1f} |")
    lines += [
        "",
        "## Gate decision",
        "",
        f"Plan reference: stdio initialize median ~{gate['plan_reference_median_ms']:.0f} ms, which the plan "
        "already labels as below the bar for building C4. Plan rule: \"If the evidence stays near today's "
        "local numbers, keep the current Python MCP entry point.\" This harness encodes 'near' as p50 within "
        f"{NEAR_BAND_FACTOR}x of that reference ({gate['near_band_ms']:.0f} ms) for the direct venv entry point.",
        "",
    ]
    for reason in gate["reasons"]:
        lines.append(f"- {reason}")
    lines += [
        "",
        f"**GATE VERDICT: {gate['verdict']}** "
        f"(measured direct-entry spawn+initialize p50 "
        f"{report['cold']['venv']['spawn_initialize_ms']['p50_ms']:.1f} ms / p95 "
        f"{report['cold']['venv']['spawn_initialize_ms']['p95_ms']:.1f} ms vs the plan's ~116 ms "
        "below-the-bar reference; the 50 ms Rust handshake target remains an unopened optimization).",
        "",
        f"Honesty note: this is a scripted client loop ({report['config']['cold_spawns_per_mode']} cold "
        f"sessions per mode + a {report['config']['warm_calls']}-call warm session), which satisfies the "
        "trace-shape requirement (T1) but is still not an organic third-party client capture. "
        "Gate item 4 (operator acceptance of daemon lifecycle surface) is an operator decision and is NOT "
        "granted by this report.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Trace MCP stdio client workflow for the Phase 4 C4 gate")
    parser.add_argument("--cold-spawns", type=int, default=20, help="fresh spawns per mode")
    parser.add_argument("--warm-calls", type=int, default=50, help="sequential warm read-only calls")
    parser.add_argument("--timeout", type=float, default=60.0, help="per-response timeout seconds")
    parser.add_argument(
        "--out-prefix",
        default=None,
        help="report basename (default mcp-trace-<UTC yyyymmdd>)",
    )
    args = parser.parse_args()

    if not VENV_MCP.exists():
        raise SystemExit(f"missing {VENV_MCP}; run 'uv sync --locked' first")

    report = run(args.cold_spawns, args.warm_calls, args.timeout)

    prefix = args.out_prefix or f"mcp-trace-{datetime.now(timezone.utc):%Y%m%d}"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORTS_DIR / f"{prefix}.json"
    md_path = REPORTS_DIR / f"{prefix}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(_render_markdown(report), encoding="utf-8")

    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    print(f"GATE VERDICT: {report['gate']['verdict']}")
    for mode in ("uv", "venv"):
        stage = report["cold"][mode]["spawn_initialize_ms"]
        print(f"  {mode} spawn+initialize p50={stage['p50_ms']:.1f}ms p95={stage['p95_ms']:.1f}ms")
    warm = report["warm"]["warm_call_ms"]
    print(f"  warm call p50={warm['p50_ms']:.3f}ms p95={warm['p95_ms']:.3f}ms")


if __name__ == "__main__":
    main()
