"""Atomically update an already configured local Codex host; keep credentials external."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from datetime import UTC, datetime

FILES = {"runtime_template.py": "runtime.py", "hook.py": "hook.py", "worker.py": "worker.py",
         "automatic_learning.py": "automatic_learning.py", "parametric.py": "parametric.py",
         "backfill.py": "backfill.py"}


def install(destination, backup):
    destination, backup = Path(destination), Path(backup)
    if not (destination / "reader.json").is_file() or not (destination / "retrieval_config.py").is_file():
        raise ValueError("configure reader.json and retrieval_config.py before installing the host")
    backup.mkdir(parents=True, mode=0o700, exist_ok=False)
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
    (backup / "installation.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=Path.home() / ".local/share/mnemosyne/codex")
    parser.add_argument("--backup", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(install(args.destination, args.backup), indent=2))
