"""Step-4 baseline capture for the A6 harness (spec §4.6).

Runs the benchmark suite in --benchmark-only mode, extracts each benchmark's
mean, and (re)writes tests/benchmarks/baselines.json. Baselines are
machine-specific by design: capture them on the reference machine and commit
the result. Usage:

    uv run --locked python tests/benchmarks/capture_baselines.py
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import tempfile

NAMES = {
    "test_bench_cosine_1024": "cosine_1024",
    "test_bench_hashing_embedding_cold": "hashing_embedding",
    "test_bench_lexical_scan_2k": "lexical_scan_2k",
}


def main() -> None:
    out = pathlib.Path(__file__).parent / "baselines.json"
    tmp = tempfile.mktemp(suffix=".json")
    subprocess.run(
        [
            "uv", "run", "--locked", "python", "-m", "pytest", "tests/benchmarks",
            # Capture is PURE-baselines-only by design: the native gate tests
            # compare against the file this script writes, so they must not run
            # (and must not be able to abort the capture) while re-capturing.
            "-k", "not native",
            "--benchmark-only", f"--benchmark-json={tmp}",
        ],
        check=True,
    )
    data = json.loads(pathlib.Path(tmp).read_text())
    baselines = {
        NAMES[b["name"].split("[")[0]]: b["stats"]["mean"]
        for b in data["benchmarks"]
        if b["name"].split("[")[0] in NAMES
    }
    missing = set(NAMES.values()) - set(baselines)
    if missing:
        raise SystemExit(f"capture incomplete, missing baselines: {sorted(missing)}")
    out.write_text(json.dumps(baselines, indent=2, sort_keys=True) + "\n")
    print(out.read_text())


if __name__ == "__main__":
    main()
