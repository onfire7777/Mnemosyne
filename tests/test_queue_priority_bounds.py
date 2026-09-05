"""Unbounded JSON integers must not break local queue selection."""

import pytest

from mnemosyne.queue import InProcessQueue, SqliteQueue


@pytest.mark.parametrize("backend", ["local", "sqlite"])
@pytest.mark.parametrize("priority,expected", [(10**400, "huge"), (-(10**400), "normal")])
def test_huge_integer_priority_is_clamped_without_float_overflow(tmp_path, backend, priority, expected):
    queue = InProcessQueue() if backend == "local" else SqliteQueue(tmp_path, "tenant")
    try:
        queue.enqueue("work", {"label": "normal", "write_priority": {"score": 0.5}})
        queue.enqueue("work", {"label": "huge", "write_priority": {"score": priority}})
        assert queue.lease().payload["label"] == expected
    finally:
        if isinstance(queue, SqliteQueue):
            queue.close()
