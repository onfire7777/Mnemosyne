"""Keep the A6 benchmark suite out of plain CI runs (spec §4.6).

Mechanism: a plain ``pytest`` invocation must stay fast, so every test under
``tests/benchmarks/`` is skipped at collection time unless the run opted in via
either

* ``--benchmark-only`` (pytest-benchmark's mode; runs the timed kernels and the
  relative-regression gate), or
* ``MNEMOSYNE_BENCH_ABSOLUTE=1`` (reference-Mac nightly; additionally runs the
  absolute §22.5 budget test, which pytest-benchmark's ``--benchmark-only``
  would deselect because it does not use the ``benchmark`` fixture).

This is scoped to this directory only — the hook filters by item path, so the
rest of the suite is untouched.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_BENCH_DIR = Path(__file__).parent


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--benchmark-only", default=False):
        return
    if os.environ.get("MNEMOSYNE_BENCH_ABSOLUTE") == "1":
        return
    skip = pytest.mark.skip(
        reason="benchmark suite: opt in with --benchmark-only (or MNEMOSYNE_BENCH_ABSOLUTE=1)"
    )
    for item in items:
        if _BENCH_DIR in item.path.parents:
            item.add_marker(skip)
