"""Bounded host locks, separate from storage transactions."""
from contextlib import contextmanager
from pathlib import Path
from mnemosyne._file_lock import exclusive_file_lock


@contextmanager
def bounded_lock(path, timeout=1.0):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with exclusive_file_lock(path, timeout=timeout):
        path.chmod(0o600)
        yield
