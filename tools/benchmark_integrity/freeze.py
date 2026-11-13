#!/usr/bin/env python3
"""Freeze a benchmark run before it starts, and verify the freeze afterwards.

freeze  refuses a dirty git tree, optionally runs the fingerprint leak check,
        hashes the dataset, split, prompts and configs, records models and
        decoding settings, and appends the attempt to a ledger. Every attempt
        on held-out data is visible in the ledger; a second held-out attempt
        needs --rerun-reason, which is recorded and must be disclosed.
verify  checks the code and hashed files still match the manifest.

  python freeze.py freeze --repo . --data longmemeval_s_cleaned.json --split split.json \
      --scope heldout --reader anthropic/claude-haiku-5.5 --judge openai/gpt-4o-2024-08-06 \
      --hash eval/prompts/reader.txt --param temperature=0 --command "python run.py ..." \
      --fp .benchmark-guard/longmemeval_s.fp.json \
      --ledger benchmark-runs.jsonl --out runs/final/manifest.json
  python freeze.py verify --manifest runs/final/manifest.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_data import sha256_file  # noqa: E402


def git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True).stdout.strip()


def freeze(a: argparse.Namespace) -> None:
    if git(a.repo, "status", "--porcelain", "--untracked-files=no"):
        raise SystemExit("refused: uncommitted changes. Commit first so the run is tied to an exact commit.")
    if a.fp:
        guard = Path(__file__).with_name("fingerprints.py")
        if subprocess.run([sys.executable, str(guard), "check", "--fp", a.fp, "--repo", a.repo]).returncode:
            raise SystemExit("refused: held-out material found in the repo (see above). Remove it first.")
    ledger = Path(a.ledger)
    earlier = [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()] if ledger.exists() else []
    dataset_sha = sha256_file(a.data)
    if a.scope in ("heldout", "all"):
        prior = [r for r in earlier if r["dataset_sha256"] == dataset_sha and r["scope"] in ("heldout", "all")]
        if prior and not a.rerun_reason:
            raise SystemExit(f"refused: {len(prior)} earlier held-out attempt(s) in {ledger}. A rerun needs "
                             "--rerun-reason (e.g. provider outage) and every attempt must be reported.")
    manifest = {
        "run_id": uuid.uuid4().hex[:12], "frozen_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "repo_commit": git(a.repo, "rev-parse", "HEAD"),
        "repo_remote": subprocess.run(["git", "-C", a.repo, "config", "--get", "remote.origin.url"],
                                      capture_output=True, text=True).stdout.strip(),
        "dataset": Path(a.data).name, "dataset_sha256": dataset_sha,
        "split_sha256": sha256_file(a.split) if a.split else None, "scope": a.scope,
        "reader": a.reader, "judge": a.judge,
        "params": dict(p.split("=", 1) for p in a.param),
        "hashed_files": {f: sha256_file(Path(a.repo) / f) for f in a.hash},
        "command": a.command, "leak_check": "passed" if a.fp else "not run",
        "attempt_number_on_this_scope": 1 + sum(r["scope"] == a.scope and r["dataset_sha256"] == dataset_sha for r in earlier),
        "rerun_reason": a.rerun_reason,
    }
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    with ledger.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(manifest) + "\n")
    print(f"frozen run {manifest['run_id']} at {manifest['repo_commit'][:10]} -> {out}")


def verify(a: argparse.Namespace) -> None:
    m = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
    problems = []
    if git(a.repo, "rev-parse", "HEAD") != m["repo_commit"]:
        problems.append("HEAD is not the frozen commit")
    if git(a.repo, "status", "--porcelain", "--untracked-files=no"):
        problems.append("tree has uncommitted changes")
    for f, digest in m["hashed_files"].items():
        if sha256_file(Path(a.repo) / f) != digest:
            problems.append(f"{f} changed since freeze")
    print("\n".join(problems) if problems else f"ok: run {m['run_id']} matches its freeze")
    sys.exit(1 if problems else 0)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("freeze")
    f.add_argument("--repo", default=".")
    f.add_argument("--data", required=True)
    f.add_argument("--split")
    f.add_argument("--scope", required=True, choices=("dev", "heldout", "all"))
    f.add_argument("--reader", required=True)
    f.add_argument("--judge", required=True)
    f.add_argument("--param", action="append", default=[], help="key=value decoding/config setting")
    f.add_argument("--hash", action="append", default=[], help="repo-relative prompt/config file to pin")
    f.add_argument("--command", default="")
    f.add_argument("--fp", help="fingerprint file; the leak check must pass")
    f.add_argument("--ledger", required=True, help="append-only list of every attempt (commit it)")
    f.add_argument("--rerun-reason")
    f.add_argument("--out", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--repo", default=".")
    v.add_argument("--manifest", required=True)
    a = ap.parse_args()
    freeze(a) if a.cmd == "freeze" else verify(a)


if __name__ == "__main__":
    main()
