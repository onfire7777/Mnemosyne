"""Shared scaffolding for the §17 open-question measurement benches.

These benches measure the **CURRENT** ``src/mnemosyne`` tree *honestly*. They
import the real engine / job handlers / lifecycle / security modules in-process
(no mocks, no CLI subprocess) and report a JSON metric block plus the blueprint
target. Where a feature the bench measures is **not yet wired** in src (e.g. a
cached-PPR column, a projection dirty-check, a separated read-path mediation
seam), the bench still runs end-to-end and reports the honest current status as
a forcing function, naming the precise src wiring that would change the verdict.

Design rules honored here:
  * Net-new files only, under ``eval/benches/`` — never edit ``src/mnemosyne``.
  * Reuse ``.venv-eval`` (torch + sentence-transformers ready). These benches
    do not require torch; they exercise the deterministic local engine, which is
    what "CURRENT src" exposes today.
  * Each bench is independently runnable: ``python eval/benches/<name>.py``.

The benches add ``<repo>/src`` to ``sys.path`` exactly like the CLI does, so the
``mnemosyne`` package resolves without an editable install.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Path wiring: make ``import mnemosyne`` resolve against the completion src tree.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# §16 / §15 budget: fast-path P95 ≤ ~300-400 ms. The eval harness
# (``eval/harness/suites.py`` SLO_TARGETS["fast_path_p95_ms"]) uses the looser
# 400 ms bound; we mirror it so the benches agree with the SLO scorecard.
FAST_PATH_P95_BUDGET_MS = 400.0


@dataclass(slots=True)
class Timer:
    """Monotonic perf timer returning elapsed milliseconds."""

    _t0: float = 0.0

    def __enter__(self) -> "Timer":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:  # noqa: D401
        self.elapsed_ms = (time.perf_counter() - self._t0) * 1000.0


def time_ms(fn: Callable[[], Any]) -> tuple[float, Any]:
    """Run ``fn`` once and return (elapsed_ms, result)."""

    t0 = time.perf_counter()
    result = fn()
    return (time.perf_counter() - t0) * 1000.0, result


def time_many(fn: Callable[[], Any], iters: int) -> list[float]:
    """Run ``fn`` ``iters`` times, returning per-call elapsed milliseconds."""

    out: list[float] = []
    for _ in range(iters):
        t0 = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t0) * 1000.0)
    return out


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile (matches ``graph.benchmark_graph_adapter``)."""

    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(len(ordered) * pct))
    return ordered[idx]


def summarize(values: list[float]) -> dict[str, float]:
    if not values:
        return {"count": 0, "p50_ms": 0.0, "p95_ms": 0.0, "mean_ms": 0.0, "max_ms": 0.0}
    return {
        "count": len(values),
        "p50_ms": round(percentile(values, 0.50), 4),
        "p95_ms": round(percentile(values, 0.95), 4),
        "mean_ms": round(statistics.fmean(values), 4),
        "max_ms": round(max(values), 4),
    }


def emit(payload: dict[str, Any]) -> None:
    """Print the bench result as a single-line + pretty JSON block.

    Convention shared by all four benches and the runner: the FINAL line printed
    to stdout is a compact JSON object with the bench's ``metric`` and ``target``
    so a wrapper can ``json.loads(last_line)``.
    """

    print(json.dumps(payload, indent=2, sort_keys=True))
    print("BENCH_JSON " + json.dumps(payload, sort_keys=True))


def temp_store(prefix: str) -> str:
    import tempfile

    return os.path.join(tempfile.mkdtemp(prefix=f"mnemo-bench-{prefix}-"), "store")
