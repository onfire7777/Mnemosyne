import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from eval.public import resource_usage


def test_rss_counts_only_selected_group_and_converts_kib(monkeypatch):
    monkeypatch.setattr(resource_usage.subprocess, 'run', lambda *a, **k:
                        SimpleNamespace(stdout=' 12 100\n12 23\n15 999\n'))
    assert resource_usage.process_group_rss_bytes(12) == 123 * 1024
    assert resource_usage.process_group_rss_bytes(99) == 0


@pytest.mark.parametrize('value', [True, 0, -1, '12'])
def test_invalid_group_rejected(value):
    with pytest.raises(ValueError):
        resource_usage.process_group_rss_bytes(value)


def test_disk_snapshot_deduplicates_roots_and_hardlinks_without_following_symlinks(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    nested = root / 'nested'
    nested.mkdir()
    (nested / 'data').write_bytes(b'12345')
    os.link(nested / 'data', root / 'hardlink')
    outside = tmp_path / 'outside'
    outside.write_bytes(b'x' * 100)
    (root / 'symlink').symlink_to(outside)
    (root / 'loop').symlink_to(root, target_is_directory=True)
    assert resource_usage.regular_file_bytes([root, nested, root / 'missing']) == 5


def test_disk_permission_error_is_not_zero_usage(tmp_path, monkeypatch):
    def denied(*args):
        raise PermissionError('unreadable')
    monkeypatch.setattr(Path, 'lstat', denied)
    with pytest.raises(PermissionError):
        resource_usage.regular_file_bytes([tmp_path])
