"""Curated development evidence, deliberately separate from admitted results."""

from html import escape
import hashlib
import io
import json
import os
import stat
from pathlib import Path, PurePosixPath
import zipfile

CAPTURES = (
    ('m12-dependency-attempt-2026-10-04', 'Dependency formation', 'Failed full-corpus attempt',
     '1 of 100 cases completed. The next case failed on task-ID reuse; 98 were not attempted. '
     'The completed case missed one expected firing. No full-corpus score.'),
    ('m12-formation-decoding-diagnostic-2026-10-04', 'JSON versus schema', 'Completed development diagnostic',
     '22 first-turn responses across 11 inputs. All 11 plain-JSON outputs failed format checks; '
     'all 11 schema outputs passed them. Semantic failures remain. No tasks were executed.'),
    ('m12-formation-semantic-diagnostic-2026-10-04', 'Prompt semantics', 'Completed development diagnostic',
     '22 first-turn responses across 11 inputs. Added instructions corrected one recurrence proposal, '
     'but event and condition errors remained and an unrelated task was introduced. No overall improvement established.'),
)


def _read_regular(path, limit):
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError('development evidence must be a regular file')
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as handle:
        opened = os.fstat(handle.fileno())
        if (not stat.S_ISREG(opened.st_mode)
                or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)):
            raise ValueError('development evidence file changed while opening')
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('development evidence file exceeds limit')
    return raw


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate development manifest key')
        result[key] = value
    return result


def evidence_pages(report_root=None):
    root = Path(report_root) if report_root is not None else Path(__file__).resolve().parents[1] / 'eval/reports'
    pages, cards = {}, []
    total = 0
    for name, title, status, summary in CAPTURES:
        capture = root / name
        manifest_raw = _read_regular(capture / 'manifest.json', 1024 * 1024)
        total += len(manifest_raw)
        manifest = json.loads(manifest_raw, object_pairs_hook=_unique_object)
        files = manifest['files']
        if not isinstance(files, dict) or not 1 <= len(files) <= 500:
            raise ValueError('invalid development evidence manifest')
        payloads = {'manifest.json': manifest_raw}
        for relative, digest in files.items():
            path = PurePosixPath(relative)
            if (path.is_absolute() or '..' in path.parts or '\\' in relative
                    or not path.parts or path.as_posix() != relative or relative == 'manifest.json'):
                raise ValueError('unsafe development evidence path')
            source = capture.joinpath(*path.parts)
            if not source.resolve().is_relative_to(capture.resolve()) or source.is_symlink() or not source.is_file():
                raise ValueError('development evidence must be a contained regular file')
            raw = _read_regular(source, 4 * 1024 * 1024)
            total += len(raw)
            if total > 20 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError('development evidence hash or size differs')
            payloads[relative] = raw
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
            for relative, raw in sorted(payloads.items()):
                info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                bundle.writestr(info, raw)
        destination = 'data/development/' + name
        pages[Path(destination + '.zip')] = archive.getvalue()
        pages[Path(destination + '.json')] = manifest_raw
        cards.append('<article class="scope-card"><p class="eyebrow">' + escape(status) + '</p>'
                     '<h2>' + escape(title) + '</h2><p>' + escape(summary) + '</p>'
                     '<div class="section-links"><a href="' + destination + '.zip" download>Download complete evidence ZIP</a>'
                     '<a href="' + destination + '.json" download>File hashes</a></div></article>')
    body = ('<p class="eyebrow">DEVELOPMENT EVIDENCE</p><h1>Experiments, including the failures.</h1>'
            '<p class="intro">Trace what ran, what failed, and what remains unknown. '
            'These operator-run development captures are not admitted leaderboard results.</p>'
            '<div class="callout"><p><strong>No ranking or superiority claim.</strong> '
            'Format validity, stored-state accuracy and firing behavior are different checks. '
            'A completed diagnostic is not a completed benchmark. ZIPs include raw records, methodology and file hashes; '
            'hashes bind files but do not independently attest execution.</p></div>'
            '<div class="scope-grid">' + ''.join(cards) + '</div>'
            '<p class="section-links"><a href="benchmarks.html">Benchmark library</a>'
            '<a href="methods.html">Methodology</a><a href="attempts.html">Registered attempt history</a></p>')
    return body, pages
