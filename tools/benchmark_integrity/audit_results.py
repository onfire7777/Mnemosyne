#!/usr/bin/env python3
"""Audit a finished benchmark run and write its receipt.

Checks that every in-scope item was answered and graded exactly once, that no
out-of-scope (held-out) item appears in a development run, that the results
were produced after the freeze and by the frozen models, then computes the
score with a Wilson 95% interval, per-type and task-averaged accuracy, and
abstention accuracy. Exit code 1 if any check fails.

  python audit_results.py --manifest runs/final/manifest.json --results runs/final/results.jsonl \
      --data longmemeval_s_cleaned.json --format longmemeval --split split.json \
      --out runs/final/RECEIPT.md [--id-field question_id] [--correct-field autoeval_label]
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_data import load, sha256_file  # noqa: E402


def truthy(value) -> bool | None:
    if isinstance(value, dict):
        for key in ("label", "correct", "passed", "value"):
            if key in value:
                return truthy(value[key])
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("yes", "true", "correct", "1"):
            return True
        if text in ("no", "false", "incorrect", "0"):
            return False
    return None


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if not n:
        return 0.0, 0.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--results", required=True, help="JSONL, one graded row per item")
    ap.add_argument("--data", required=True)
    ap.add_argument("--format", required=True, choices=("longmemeval", "locomo", "jsonl"))
    ap.add_argument("--split")
    ap.add_argument("--id-field", default="question_id")
    ap.add_argument("--correct-field", default="autoeval_label")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    manifest = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
    items = {item["id"]: item for item in load(a.data, a.format)}
    split_record = json.loads(Path(a.split).read_text(encoding="utf-8")) if a.split else None
    scope = manifest["scope"]
    if scope == "all" or not split_record:
        in_scope = set(items)
    else:
        in_scope = set(split_record["dev" if scope == "dev" else "heldout"])
    rows = [json.loads(line) for line in Path(a.results).read_text(encoding="utf-8").splitlines() if line.strip()]

    problems = []
    if sha256_file(a.data) != manifest["dataset_sha256"]:
        problems.append("dataset differs from the frozen dataset")
    if split_record and manifest.get("split_sha256") and sha256_file(a.split) != manifest["split_sha256"]:
        problems.append("split file differs from the frozen split")
    seen = collections.Counter(str(r.get(a.id_field)) for r in rows)
    dupes = [i for i, c in seen.items() if c > 1]
    missing = sorted(in_scope - set(seen))
    outside = sorted(set(seen) - in_scope)
    unknown = sorted(set(seen) - set(items))
    if dupes:
        problems.append(f"{len(dupes)} item(s) graded more than once (keep exactly one attempt per item)")
    if missing:
        problems.append(f"{len(missing)} in-scope item(s) missing; missing items count as wrong, never as excluded")
    if outside:
        problems.append(f"{len(outside)} item(s) outside the frozen '{scope}' scope present"
                        + (" — held-out items were run during development" if scope == "dev" else ""))
    if unknown:
        problems.append(f"{len(unknown)} id(s) not in the dataset")
    frozen = datetime.fromisoformat(manifest["frozen_at"])
    produced = datetime.fromtimestamp(Path(a.results).stat().st_mtime, UTC)
    if produced < frozen:
        problems.append("results file is older than the freeze")
    for field, expected in (("reader", manifest["reader"]), ("judge", manifest["judge"])):
        used = {str(r[field]) if not isinstance(r[field], dict) else str(r[field].get("model"))
                for r in rows if field in r}
        if field == "judge":  # many harnesses record the judge inside the grade object
            used |= {str(r[a.correct_field]["model"]) for r in rows
                     if isinstance(r.get(a.correct_field), dict) and r[a.correct_field].get("model")}
        if used and used != {expected}:
            problems.append(f"{field} in results {sorted(used)} differs from frozen {expected}")
    ungraded = [str(r.get(a.id_field)) for r in rows if truthy(r.get(a.correct_field)) is None]
    if ungraded:
        problems.append(f"{len(ungraded)} row(s) with no readable grade in '{a.correct_field}' (counted wrong)")

    graded = {str(r.get(a.id_field)): truthy(r.get(a.correct_field)) is True for r in rows}
    scored = sorted(in_scope)
    correct = sum(graded.get(i, False) for i in scored)
    n = len(scored)
    lo, hi = wilson(correct, n)
    by_type = collections.defaultdict(lambda: [0, 0])
    for i in scored:
        t = items[i]["type"] or "all"
        by_type[t][0] += graded.get(i, False)
        by_type[t][1] += 1
    base_types = collections.defaultdict(lambda: [0, 0])
    for t, (k, m) in by_type.items():
        base = t.split("/")[0]
        base_types[base][0] += k
        base_types[base][1] += m
    task_avg = sum(k / m for k, m in base_types.values()) / len(base_types) if base_types else 0.0
    abst = [(k, m) for t, (k, m) in by_type.items() if t.endswith("/abstention")]

    lines = [
        f"# Benchmark receipt — {manifest['dataset']} ({scope})", "",
        f"**Score: {correct}/{n} = {correct / n:.1%}** (Wilson 95% CI {lo:.1%}–{hi:.1%}); "
        f"task-averaged {task_avg:.1%}" + (f"; abstention {sum(k for k, _ in abst)}/{sum(m for _, m in abst)}" if abst else ""),
        "", "| Setting | Value |", "| --- | --- |",
        f"| Run id / attempt on this scope | {manifest['run_id']} / {manifest['attempt_number_on_this_scope']}"
        + (f" (rerun reason: {manifest['rerun_reason']})" if manifest.get('rerun_reason') else "") + " |",
        f"| Code | {manifest.get('repo_remote') or 'local'} @ `{manifest['repo_commit']}` |",
        f"| Dataset sha256 | `{manifest['dataset_sha256']}` |",
        f"| Reader / judge | {manifest['reader']} / {manifest['judge']} |",
        f"| Settings | {json.dumps(manifest['params'])} |",
        f"| Pinned files | {', '.join(f'{k} `{v[:12]}`' for k, v in manifest['hashed_files'].items()) or 'none'} |",
        f"| Leak check before run | {manifest['leak_check']} |",
        f"| Command | `{manifest['command']}` |",
        "", "| Type | Correct | Accuracy |", "| --- | --- | --- |",
    ]
    for t, (k, m) in sorted(by_type.items()):
        lines.append(f"| {t} | {k}/{m} | {k / m:.1%} |")
    lines += ["", "## Audit", ""]
    lines += [f"- FAIL: {p}" for p in problems] or ["- PASS: every in-scope item graded once, scope respected, "
                                                     "frozen dataset/models, results after freeze"]
    Path(a.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:3]))
    print("\n".join(f"FAIL: {p}" for p in problems) or "audit passed")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
