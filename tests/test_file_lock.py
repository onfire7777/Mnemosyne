from __future__ import annotations

import errno
import multiprocessing
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from mnemosyne._file_lock import exclusive_file_lock


def _acquire_then_release(path: str, attempting: Any, acquired: Any, release: Any) -> None:
    lock_path = Path(path)
    attempting.set()
    with exclusive_file_lock(lock_path):
        acquired.set()
        release.wait()


def _exit_while_locked(path: str, acquired: Any) -> None:
    with exclusive_file_lock(Path(path)):
        acquired.set()
        os._exit(0)


def test_windows_empty_file_locks_byte_zero_and_retries_only_eacces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mnemosyne import _file_lock

    calls: list[tuple[int, int, int]] = []
    failures = [OSError(errno.EACCES, "busy")] * 126

    def locking(fd: int, operation: int, length: int) -> None:
        calls.append((fd, operation, length))
        if failures:
            raise failures.pop()

    fake_msvcrt = SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=locking)
    sleeps: list[float] = []
    monkeypatch.setattr(_file_lock.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    monkeypatch.setattr(_file_lock.time, "sleep", sleeps.append)
    lock_path = tmp_path / "empty.lock"

    with exclusive_file_lock(lock_path):
        assert lock_path.read_bytes() == b""

    assert lock_path.read_bytes() == b""
    assert [call[1:] for call in calls[:-1]] == [(1, 1)] * 127
    assert calls[-1][1:] == (2, 1)
    assert sleeps == [0.1] * 126


@pytest.mark.parametrize("failure", [OSError(errno.EPERM, "denied"), KeyboardInterrupt()])
def test_windows_propagates_noncontention_and_interrupts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: BaseException
) -> None:
    from mnemosyne import _file_lock

    def locking(_fd: int, _operation: int, _length: int) -> None:
        raise failure

    fake_msvcrt = SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=locking)
    monkeypatch.setattr(_file_lock.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)

    with pytest.raises(type(failure)):
        with exclusive_file_lock(tmp_path / "error.lock"):
            pass


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows msvcrt byte locks")
def test_windows_child_waits_beyond_lk_lock_timeout_then_acquires(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    attempting = context.Event()
    acquired = context.Event()
    release = context.Event()
    process = context.Process(
        target=_acquire_then_release,
        args=(str(tmp_path / "contention.lock"), attempting, acquired, release),
    )

    with exclusive_file_lock(tmp_path / "contention.lock"):
        process.start()
        assert attempting.wait(timeout=5)
        assert not acquired.wait(timeout=12.5)
        assert process.is_alive()
    assert acquired.wait(timeout=5)
    release.set()
    process.join(timeout=5)
    assert process.exitcode == 0


def test_process_exit_releases_file_lock(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    acquired = context.Event()
    crashed = context.Process(
        target=_exit_while_locked,
        args=(str(tmp_path / "crash.lock"), acquired),
    )
    crashed.start()
    assert acquired.wait(timeout=5)
    crashed.join(timeout=5)
    assert crashed.exitcode == 0

    recovered = context.Event()
    attempting = context.Event()
    release = context.Event()
    contender = context.Process(
        target=_acquire_then_release,
        args=(str(tmp_path / "crash.lock"), attempting, recovered, release),
    )
    contender.start()
    assert attempting.wait(timeout=5)
    assert recovered.wait(timeout=5)
    release.set()
    contender.join(timeout=5)
    assert contender.exitcode == 0
