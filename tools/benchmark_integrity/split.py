#!/usr/bin/env python3
"""Write a deterministic development / held-out split for a benchmark.

The rule is public and reproducible: rank items by sha256(id) and take the
lowest --dev-size as development. Everything else is held out and must not be
run, read or inspected before the frozen final run.

  python split.py --data longmemeval_s_cleaned.json --format longmemeval \
      --dev-size 100 --out split.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_data import load, sha256_file, split  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True)
    ap.add_argument("--format", required=True, choices=("longmemeval", "locomo", "jsonl"))
    ap.add_argument("--dev-size", type=int, help="number of development items (default: 20%% of the set)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    items = load(args.data, args.format)
    dev_size = args.dev_size if args.dev_size is not None else max(1, len(items) // 5)
    if not 0 < dev_size < len(items):
        raise SystemExit(f"--dev-size must be between 1 and {len(items) - 1}")
    dev, heldout = split(items, dev_size)
    record = {
        "dataset": Path(args.data).name,
        "dataset_sha256": sha256_file(args.data),
        "rule": f"lowest {dev_size} sha256(id) hex digests are development; the rest are held out",
        "dev": sorted(dev),
        "heldout": sorted(heldout),
    }
    Path(args.out).write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    print(f"{len(dev)} development, {len(heldout)} held out -> {args.out}")


if __name__ == "__main__":
    main()
