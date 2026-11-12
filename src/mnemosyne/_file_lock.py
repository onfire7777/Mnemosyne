"""Small cross-platform exclusive file lock for persistent lock paths."""

from __future__ import annotations

import errno
import os
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace

_process_holds: dict[str, SimpleNamespace] = {}
_process_holds_lock = threading.Lock()


@contextmanager
def process_shared_file_lock(path: Path) -> Iterator[None]:
    """exclusive_file_lock taken once per process: nested and concurrent entries by its threads share it.

    Two descriptors of one file conflict even inside one process, so a plain nested
    exclusive_file_lock on the same path would wait on itself.
    """
    with _process_holds_lock:
        hold = _process_holds.setdefault(
            os.path.realpath(path), SimpleNamespace(gate=threading.Lock(), count=0, release=None)
        )
    with hold.gate:
        if not hold.count:
            release = ExitStack()
            release.enter_context(exclusive_file_lock(path))
            hold.release = release
        hold.count += 1
    try:
        yield
    finally:
        with hold.gate:
            hold.count -= 1
            if not hold.count:
                hold.release.close()
                hold.release = None


@contextmanager
def exclusive_file_lock(path: Path, timeout: float | None = None) -> Iterator[None]:
    """Hold an exclusive lock on a persistent path until this context exits."""
    deadline = time.monotonic() + timeout if timeout is not None else None
    with path.open("a+b") as lock_file:
        if sys.platform == "win32":
            import msvcrt

            lock_file.seek(0)
            while True:
                try:
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if exc.errno != errno.EACCES:
                        raise
                    if deadline is not None and time.monotonic() >= deadline:
                        raise TimeoutError("file lock deadline exceeded") from None
                    time.sleep(0.025)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            if deadline is None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            else:
                while True:
                    try:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            raise TimeoutError("file lock deadline exceeded") from None
                        time.sleep(0.025)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
