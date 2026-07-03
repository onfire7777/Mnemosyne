"""Keep the DST/chaos suite out of plain CI runs (spec §8, Task 11).

Mechanism mirrors ``tests/benchmarks/conftest.py``: a path-scoped,
collection-time gate keyed off an environment variable so a plain ``pytest``
invocation stays fast and deterministic. Every test under ``tests/chaos/`` is
gated out unless the run opted in via ``MNEMOSYNE_CHAOS=1`` (the nightly chaos
job sets it; see ``.github/workflows/ci.yml``).

Difference from the benchmark gate — DESELECT, not skip-mark
------------------------------------------------------------
The benchmark conftest ``add_marker(skip)``s its items, so they show up in the
plain-run summary as *skipped* (they are part of that suite's baseline skip
count). The Task-11 exit gate is stricter: the gated chaos dir must add **zero**
to a normal run so the native baseline (``1555 passed / 127 skipped``) is
**unchanged**. Skip-marking would push the skip count to ``127 + N``. So this
hook DESELECTS the chaos items instead — they are removed from collection
entirely (reported as ``deselected``, which counts toward neither *passed* nor
*skipped*). Same env-gated, collection-time, path-scoped shape; outcome tuned to
the Task-11 gate.

Scoped to this directory only — the hook filters by item path, so the rest of
the suite is untouched.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

_CHAOS_DIR = Path(__file__).parent


def _chaos_enabled() -> bool:
    return os.environ.get("MNEMOSYNE_CHAOS") == "1"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _chaos_enabled():
        return
    kept: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    for item in items:
        if _CHAOS_DIR in item.path.parents:
            deselected.append(item)
        else:
            kept.append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = kept
