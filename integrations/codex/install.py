"""Atomically update an already configured local Codex host; keep credentials external."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime

FILES = {"runtime_template.py": "runtime.py", "hook.py": "hook.py", "worker.py": "worker.py",
         "automatic_learning.py": "automatic_learning.py", "parametric.py": "parametric.py",
         "backfill.py": "backfill.py"}


def install_release(destination, wheel):
    """Unpack a built package before atomically activating its content hash."""
    wheel = Path(wheel)
    fingerprint = hashlib.sha256(wheel.read_bytes()).hexdigest()
    releases = destination.parent / 'releases'
    releases.mkdir(parents=True, exist_ok=True, mode=0o700)
    release = releases / fingerprint
    if not release.exists():
        with tempfile.TemporaryDirectory(prefix='.install-', dir=releases) as temporary:
            stage = Path(temporary) / 'package'
            stage.mkdir()
            with zipfile.ZipFile(wheel) as archive:
                for member in archive.infolist():
                    target = (stage / member.filename).resolve()
                    if not target.is_relative_to(stage.resolve()):
                        raise ValueError('wheel contains an invalid member path')
                    if member.filename.startswith('mnemosyne/') or '.dist-info/' in member.filename:
                        archive.extract(member, stage)
            if not (stage / 'mnemosyne/__init__.py').is_file():
                raise ValueError('wheel does not contain the memory package')
            stage.rename(release)
    manifest = {'path': str(release.resolve()), 'wheel_sha256': fingerprint}
    descriptor, temporary = tempfile.mkstemp(prefix='active-release.', dir=destination)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(manifest, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, destination / 'active-release.json')
    return manifest


def install(destination, backup, *, wheel=None):
    destination, backup = Path(destination), Path(backup)
    if not (destination / "reader.json").is_file() or not (destination / "retrieval_config.py").is_file():
        raise ValueError("configure reader.json and retrieval_config.py before installing the host")
    backup.mkdir(parents=True, mode=0o700, exist_ok=False)
    if (destination / 'active-release.json').exists():
        shutil.copy2(destination / 'active-release.json', backup / 'active-release.json')
    manifest = {"installed_at": datetime.now(UTC).isoformat(), "files": {}}
    for source, name in FILES.items():
        path = destination / name
        if path.exists():
            shutil.copy2(path, backup / name)
        content = Path(__file__).with_name(source).read_bytes()
        descriptor, temporary = tempfile.mkstemp(prefix=name, dir=destination)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        manifest["files"][name] = hashlib.sha256(content).hexdigest()
    if wheel is not None:
        manifest['release'] = install_release(destination, wheel)
    (backup / "installation.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=Path.home() / ".local/share/mnemosyne/codex")
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, help="activate an isolated built package snapshot")
    args = parser.parse_args()
    print(json.dumps(install(args.destination, args.backup, wheel=args.wheel), indent=2))
