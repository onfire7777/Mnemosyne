import hashlib
import io
import json
from pathlib import Path
import shutil
import zipfile

import pytest

from leaderboard.development import CAPTURES, evidence_pages


def test_evidence_downloads_preserve_all_manifest_bytes_and_limits():
    body, pages = evidence_pages()
    assert 'not admitted leaderboard results' in body
    assert '98 were not attempted' in body
    assert 'No overall improvement established' in body
    assert evidence_pages() == (body, pages)
    for name, *_ in CAPTURES:
        prefix = 'data/development/' + name
        manifest = json.loads(pages[Path(prefix + '.json')])
        with zipfile.ZipFile(io.BytesIO(pages[Path(prefix + '.zip')])) as archive:
            assert set(archive.namelist()) == {*manifest['files'], 'manifest.json'}
            assert archive.read('manifest.json') == pages[Path(prefix + '.json')]
            for relative, digest in manifest['files'].items():
                assert hashlib.sha256(archive.read(relative)).hexdigest() == digest


@pytest.mark.parametrize('damage', ['bytes', 'escape'])
def test_modified_or_escaping_evidence_cannot_be_exported(tmp_path, damage):
    source = Path(__file__).resolve().parents[1] / 'eval/reports'
    name = CAPTURES[0][0]
    shutil.copytree(source / name, tmp_path / name)
    root = tmp_path / name
    if damage == 'bytes':
        (root / 'README.md').write_text('altered')
    else:
        manifest = json.loads((root / 'manifest.json').read_text())
        manifest['files']['../outside.txt'] = '0' * 64
        (root / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        evidence_pages(tmp_path)


@pytest.mark.parametrize('damage', ['large_manifest', 'duplicate_key', 'alias_path', 'manifest_symlink'])
def test_manifest_bounds_and_unambiguous_archive_paths(tmp_path, damage):
    source = Path(__file__).resolve().parents[1] / 'eval/reports'
    name = CAPTURES[0][0]
    shutil.copytree(source / name, tmp_path / name)
    path = tmp_path / name / 'manifest.json'
    if damage == 'large_manifest':
        path.write_bytes(b' ' * (1024 * 1024 + 1))
    elif damage == 'duplicate_key':
        path.write_text('{"files":{},"files":{"README.md":"x"}}')
    elif damage == 'alias_path':
        manifest = json.loads(path.read_text())
        manifest['files']['./README.md'] = manifest['files']['README.md']
        path.write_text(json.dumps(manifest))
    else:
        target = tmp_path / 'outside.json'
        path.rename(target)
        try:
            path.symlink_to(target)
        except OSError:
            pytest.skip('symlinks unavailable')
    with pytest.raises(ValueError):
        evidence_pages(tmp_path)
