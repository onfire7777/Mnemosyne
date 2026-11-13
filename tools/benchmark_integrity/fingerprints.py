#!/usr/bin/env python3
"""Leak guard that holds no test text: hashed fingerprints of held-out items.

build  makes a fingerprint file from the dataset (salted sha256 of held-out
       questions, multi-word answers and unique 8-word evidence phrases).
       Commit the file; it reveals nothing readable.
check  scans a repo against it without needing the dataset, and exits 1 on
       any hit. Run it in CI and before every benchmark run.

  python fingerprints.py build --data longmemeval_s_cleaned.json --format longmemeval \
      --split split.json --out .benchmark-guard/longmemeval_s.fp.json
  python fingerprints.py check --fp .benchmark-guard/longmemeval_s.fp.json --repo .
"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_data import load, normalize, sha256_file  # noqa: E402
from contamination_scan import N, files_in, probes, readable_text  # noqa: E402


def digest(salt: str, text: str) -> str:
    return hashlib.sha256((salt + text).encode()).hexdigest()[:20]


def build(args: argparse.Namespace) -> None:
    split_record = json.loads(Path(args.split).read_text(encoding="utf-8"))
    items = load(args.data, args.format)
    exact, grams = probes(items, set(split_record["heldout"]), set(split_record["dev"]))
    # probes() already added the development-filtered 8-word shingles of long phrases
    for phrase in [p for p in exact if len(p.split()) >= N]:
        exact.pop(phrase)
    salt = secrets.token_hex(8)
    lengths = sorted({len(p.split()) for p in exact})
    record = {
        "dataset": Path(args.data).name, "dataset_sha256": sha256_file(args.data),
        "split_sha256": sha256_file(args.split), "salt": salt, "shingle_words": N,
        "exact_lengths": lengths,
        "exact": sorted({digest(salt, p) for p in exact}),
        "shingles": sorted({digest(salt, g) for g in grams}),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record) + "\n", encoding="utf-8")
    print(f"{len(record['exact'])} exact + {len(record['shingles'])} phrase fingerprints -> {out}")


def check(args: argparse.Namespace) -> None:
    fp = json.loads(Path(args.fp).read_text(encoding="utf-8"))
    salt, n = fp["salt"], fp["shingle_words"]
    exact, grams, lengths = set(fp["exact"]), set(fp["shingles"]), fp["exact_lengths"]
    repo = Path(args.repo).resolve()
    fp_path = Path(args.fp).resolve()
    bad = {}
    for path in files_in(repo, args.exclude):
        if path.resolve() == fp_path:
            continue
        try:
            words = normalize(readable_text(path)).split()
        except (UnicodeDecodeError, OSError):
            continue
        count = 0
        for i in range(len(words)):
            if i + n <= len(words) and digest(salt, " ".join(words[i:i + n])) in grams:
                count += 1
            for size in lengths:
                if i + size <= len(words) and digest(salt, " ".join(words[i:i + size])) in exact:
                    count += 1
        if count:
            bad[str(path.relative_to(repo))] = count
    for name, count in sorted(bad.items(), key=lambda kv: -kv[1]):
        print(f"{name}: {count} held-out fingerprint match(es)")
    print(f"{len(bad)} file(s) contain held-out material" if bad else "clean: no held-out fingerprints found")
    sys.exit(1 if bad else 0)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--data", required=True)
    b.add_argument("--format", required=True, choices=("longmemeval", "locomo", "jsonl"))
    b.add_argument("--split", required=True)
    b.add_argument("--out", required=True)
    c = sub.add_parser("check")
    c.add_argument("--fp", required=True)
    c.add_argument("--repo", default=".")
    c.add_argument("--exclude", action="append", default=[])
    args = ap.parse_args()
    build(args) if args.cmd == "build" else check(args)


if __name__ == "__main__":
    main()
