from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


HELPER = (
    Path(__file__).resolve().parents[1]
    / "infra"
    / "scripts"
    / "runtime-exclusive-lock.sh"
)


def test_successful_child_releases_runtime_lock(tmp_path: Path) -> None:
    custody_dir = tmp_path / "custody"
    locks_dir = custody_dir / "locks"
    locks_dir.mkdir(parents=True, mode=0o700)
    locks_dir.chmod(0o700)

    completed = subprocess.run(
        [
            str(HELPER),
            "test-success",
            "--",
            sys.executable,
            "-c",
            "print('child-ran')",
        ],
        check=False,
        capture_output=True,
        env={**os.environ, "MNEMO_CUSTODY_DIR": str(custody_dir)},
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "child-ran\n"
    assert not (locks_dir / "runtime-exclusive").exists()
