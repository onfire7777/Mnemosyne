"""Local diagnostic samples, not an enforced or signed resource admission receipt."""

import os
from pathlib import Path
import stat
import subprocess


def process_group_rss_bytes(group_id: int) -> int:
    """Sum current RSS in one POSIX process group; short-lived peaks can be missed."""
    if type(group_id) is not int or group_id <= 0:
        raise ValueError('positive process group required')
    result = subprocess.run(
        ['/bin/ps', '-axo', 'pgid=,rss='], check=True, capture_output=True,
        text=True, timeout=2,
    )
    total = 0
    for line in result.stdout.splitlines():
        group, kib = map(int, line.split())
        if kib < 0:
            raise ValueError('negative RSS sample')
        if group == group_id:
            total += kib * 1024
    return total


def regular_file_bytes(roots: list[Path]) -> int:
    """Logical regular-file bytes, deduplicated by inode; never follow symlinks.

    This is a live snapshot, not peak allocation or a disk quota. Missing files
    during a concurrent removal are ignored; permission and other errors fail.
    """
    seen = set()
    total = 0
    pending = list(roots)
    while pending:
        path = pending.pop()
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        identity = (info.st_dev, info.st_ino)
        if identity in seen:
            continue
        seen.add(identity)
        if stat.S_ISREG(info.st_mode):
            total += info.st_size
        elif stat.S_ISDIR(info.st_mode):
            try:
                with os.scandir(path) as entries:
                    pending.extend(Path(entry.path) for entry in entries)
            except FileNotFoundError:
                continue
    return total
