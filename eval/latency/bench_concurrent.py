#!/usr/bin/env python3
"""CAP-006 concurrent latency driver for the same pinned synthetic operations.

This module does not invent a second workload. It issues the pinned operations
from ``eval/latency/bench.py`` at a declared bounded concurrency and records
issue/start/end timestamps, observed overlap, and observed max in-flight. A
receipt is invalid when those observations do not match the declaration.

Synthetic/development receipts only. No official or admitted performance claim.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
EVAL_DIR = HERE.parents[1]
REPO_ROOT = HERE.parents[2]
for path in (str(HERE.parent), str(REPO_ROOT / "src"), str(EVAL_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

import bench  # noqa: E402


def run_concurrent_receipt(
    *,
    declared_concurrency: int = 3,
    warmup_count: int = 1,
    timeout_seconds: float = 1.0,
    executor_workers: int | None = None,
    inject_outcomes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Issue the pinned workload at declared concurrency and bind a receipt."""
    return bench.execute_pinned_workload(
        distribution=bench.DISTRIBUTION_CONCURRENT,
        declared_concurrency=declared_concurrency,
        warmup_count=warmup_count,
        timeout_seconds=timeout_seconds,
        executor_workers=executor_workers,
        inject_outcomes=inject_outcomes,
    )


def emit_phase15_s4_receipts() -> tuple[Path, Path]:
    """Write separate synthetic warm-serial and concurrent development receipts."""
    warm = bench.execute_pinned_workload(
        distribution=bench.DISTRIBUTION_WARM_SERIAL,
        declared_concurrency=1,
        warmup_count=2,
        timeout_seconds=1.0,
    )
    concurrent = run_concurrent_receipt(
        declared_concurrency=3,
        warmup_count=1,
        timeout_seconds=1.0,
    )
    return (
        bench.write_phase15_s4_receipt(warm, bench.PHASE15_S4_WARM_REPORT),
        bench.write_phase15_s4_receipt(concurrent, bench.PHASE15_S4_CONCURRENT_REPORT),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--declared-concurrency", type=int, default=3)
    parser.add_argument("--warmup-count", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=1.0)
    parser.add_argument("--executor-workers", type=int, default=None)
    parser.add_argument("--emit-phase15-s4", action="store_true")
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()
    if args.emit_phase15_s4:
        warm_path, concurrent_path = emit_phase15_s4_receipts()
        print(f"[cap006] warm       -> {warm_path}")
        print(f"[cap006] concurrent -> {concurrent_path}")
        return 0
    receipt = run_concurrent_receipt(
        declared_concurrency=args.declared_concurrency,
        warmup_count=args.warmup_count,
        timeout_seconds=args.timeout_seconds,
        executor_workers=args.executor_workers,
    )
    if args.json_only:
        print(json.dumps(receipt, indent=2))
    else:
        print(json.dumps({"valid": receipt["validity"]["valid"], "digest": receipt["raw_artifacts"]["result_digest"]}, indent=2))
    return 0 if receipt["validity"]["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
