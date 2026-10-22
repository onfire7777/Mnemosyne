"""Nonblocking, process-held locks for local benchmark output directories.

Lock files are permanent coordination objects, not evidence of a live process.
Never unlink them: a new inode would let two processes hold different locks.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import errno
import os
from pathlib import Path
import sys
from typing import Iterator


class RunnerBusy(RuntimeError):
    """Another runner owns a requested output/runtime directory."""


@contextmanager
def _lock_path(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        # Provider subprocesses must not keep the lock alive after our crash.
        os.set_inheritable(handle.fileno(), False)
        try:
            if sys.platform == "win32":
                import msvcrt

                handle.seek(0)
                # Windows permits byte-range locks beyond EOF; no racy seed write.
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise RunnerBusy(f"benchmark runner already active for {path.parent}") from None
            raise
        try:
            yield
        finally:
            if sys.platform == "win32":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def exclusive_runner(*directories: Path) -> Iterator[None]:
    """Own all resources before reading claims or changing benchmark state.

    A busy resource fails immediately. Partially acquired locks are released.
    Only lock-directory/file creation precedes complete acquisition. The OS
    releases locks on process exit; existing files need no stale-file cleanup.
    """
    roots = {Path(directory).resolve() for directory in directories}
    if not roots:
        raise ValueError("at least one runner resource is required")
    with ExitStack() as stack:
        for root in sorted(roots, key=lambda value: os.path.normcase(str(value))):
            stack.enter_context(_lock_path(root / ".benchmark-runner.lock"))
        yield
