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
from mnemosyne.deletion import SQLiteDeletionLedger


def _acquire_then_release(path: str, acquired: Any, release: Any) -> None:
    with exclusive_file_lock(Path(path)):
        acquired.set()
        release.wait()


def _exit_while_locked(path: str, acquired: Any) -> None:
    with exclusive_file_lock(Path(path)):
        acquired.set()
        os._exit(0)


def _hold_deletion_ledger_lock(path: str, acquired: Any, release: Any) -> None:
    with SQLiteDeletionLedger(path).operation_lock():
        acquired.set()
        release.wait()


def test_windows_empty_file_locks_byte_zero_and_retries_only_eacces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mnemosyne import _file_lock

    calls: list[tuple[int, int, int]] = []
    failures = [OSError(errno.EACCES, "busy")]

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
    assert [call[1:] for call in calls] == [(1, 1), (1, 1), (2, 1)]
    assert sleeps


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
    acquired = context.Event()
    release = context.Event()
    process = context.Process(
        target=_acquire_then_release,
        args=(str(tmp_path / "contention.lock"), acquired, release),
    )

    with exclusive_file_lock(tmp_path / "contention.lock"):
        process.start()
        assert not acquired.wait(timeout=12.5)
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
    release = context.Event()
    contender = context.Process(
        target=_acquire_then_release,
        args=(str(tmp_path / "crash.lock"), recovered, release),
    )
    contender.start()
    assert recovered.wait(timeout=5)
    release.set()
    contender.join(timeout=5)
    assert contender.exitcode == 0


def test_sqlite_deletion_ledger_serializes_spawned_processes(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    lock_path = str(tmp_path / "deletion.sqlite")
    first_acquired = context.Event()
    first_release = context.Event()
    second_acquired = context.Event()
    second_release = context.Event()
    first = context.Process(
        target=_hold_deletion_ledger_lock,
        args=(lock_path, first_acquired, first_release),
    )
    second = context.Process(
        target=_hold_deletion_ledger_lock,
        args=(lock_path, second_acquired, second_release),
    )
    first.start()
    assert first_acquired.wait(timeout=5)
    second.start()
    assert not second_acquired.wait(timeout=0.5)
    first_release.set()
    assert second_acquired.wait(timeout=5)
    second_release.set()
    first.join(timeout=5)
    second.join(timeout=5)
    assert first.exitcode == second.exitcode == 0
