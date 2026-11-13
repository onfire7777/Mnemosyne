#!/usr/bin/env python3
"""Find held-out benchmark material inside a code base.

Looks for held-out question text, multi-word answers and 8-word passages of
the gold evidence (phrases unique to held-out items) in every tracked text
file: code, prompts, tests, fixtures, docs, configs. Prints ids and kinds
only, never the held-out text, so the report itself does not leak.

  python contamination_scan.py --data longmemeval_s_cleaned.json \
      --format longmemeval --split split.json --repo /path/to/repo \
      [--exclude 'eval/results/**'] [--json report.json]

Exit code 1 when anything is found, so it can gate CI or a final run.
"""
from __future__ import annotations

import argparse
import collections
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_data import load, normalize, shingles  # noqa: E402

N = 8
COMMON = set("""what when where which how many much did does have were was this that there their they then
from with your about after before first last next today yesterday tomorrow week month year monday tuesday wednesday
thursday friday saturday sunday january february march april may june july august september october november december
can could would should will also just yes the and but for not you are can i my me we our""".split())
GENERIC_ANSWERS = ("the information provided is not enough", "the user would prefer")
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".gz", ".zip", ".sqlite", ".db", ".bin",
                 ".pt", ".onnx", ".safetensors", ".ico", ".woff", ".woff2", ".mp3", ".mp4", ".wav"}


def probes(items: list[dict], heldout: set[str], dev: set[str]) -> tuple[dict, dict]:
    """Return (exact phrases -> (id, kind), shingles -> (id, kind)) for held-out items."""
    dev_context, dev_text = set(), []
    for item in items:
        if item["id"] in dev:
            for text in item["context"]:
                dev_context |= shingles(text, N)
            dev_context |= shingles(" ".join(item["context"]), N)  # phrases spanning adjacent turns
            dev_context |= shingles(item["question"], N) | shingles(item["answer"], N)
            dev_text.append(normalize(" ".join([item["question"], item["answer"], *item["context"]])))
    # Text that development material also contains is allowed (shared filler sessions, question
    # wording reused by an abstention twin), so it cannot be evidence of a held-out leak.
    dev_blob = " " + " ".join(dev_text) + " "
    owners = collections.defaultdict(set)
    for item in items:
        for text in item["evidence"]:
            for sh in shingles(text, N):
                owners[sh].add(item["id"])
    exact, grams = {}, {}
    for item in items:
        if item["id"] not in heldout:
            continue
        q = normalize(item["question"])
        if len(q.split()) >= 5 and f" {q} " not in dev_blob:
            exact[q] = (item["id"], "question")
            for sh in shingles(item["question"], N):
                if sh not in dev_context:
                    grams[sh] = (item["id"], "question")
        a = normalize(item["answer"])
        if len(a.split()) >= 3 and not a.startswith(GENERIC_ANSWERS) and f" {a} " not in dev_blob:
            exact[a] = (item["id"], "answer")
            for sh in shingles(item["answer"], N):
                if sh not in dev_context:
                    grams[sh] = (item["id"], "answer")
        for text in item["evidence"]:
            for sh in shingles(text, N):
                # Phrases shared with other items or with development haystacks are ordinary chat, not leaks.
                if owners[sh] == {item["id"]} and sh not in dev_context:
                    grams.setdefault(sh, (item["id"], "evidence"))
    return exact, grams


CODE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".mjs", ".rs", ".go", ".java", ".kt", ".rb", ".cs", ".php",
                 ".txt", ".jinja", ".j2", ".prompt", ".yaml", ".yml", ".toml"}
NAME = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\b")


def rare_names(items: list[dict], heldout: set[str], dev: set[str]) -> dict:
    """Capitalised names that occur in at most two held-out questions/answers and in no development one."""
    seen_dev, owners, lower_words = set(), collections.defaultdict(set), set()
    for item in items:
        if item["id"] in dev:
            for text in item["context"]:
                lower_words |= set(re.findall(r"\b[a-z][a-z]+\b", text))
    for item in items:
        names = set(NAME.findall(item["question"] + " " + item["answer"]))
        if item["id"] in dev:
            seen_dev |= names
        elif item["id"] in heldout:
            for name in names:
                owners[name].add(item["id"])
    return {n: sorted(ids) for n, ids in owners.items()
            if len(ids) <= 2 and n not in seen_dev and len(n) >= 4 and n.lower() not in COMMON
            # a word also written in lower case in ordinary conversation is a common word, not a name
            and not (" " not in n and n.lower() in lower_words)}


def name_review(paths: list[Path], repo: Path, names: dict) -> dict:
    """Code/prompt files naming a rare held-out entity: not proof of a leak, a person must look."""
    pattern = re.compile(r"\b(" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + r")\b") if names else None
    found = {}
    for path in paths:
        if not pattern or path.suffix.lower() not in CODE_SUFFIXES:
            continue
        try:
            hits = set(pattern.findall(path.read_text(encoding="utf-8")))
        except (UnicodeDecodeError, OSError):
            continue
        if hits:
            found[str(path.relative_to(repo))] = {h: names[h] for h in sorted(hits)}
    return found


def files_in(repo: Path, excludes: list[str]) -> list[Path]:
    try:
        listed = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True, check=True).stdout
        names = [n for n in listed.decode().split("\0") if n]
    except (subprocess.CalledProcessError, FileNotFoundError):
        names = [str(p.relative_to(repo)) for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts]
    return [repo / n for n in names
            if Path(n).suffix.lower() not in SKIP_SUFFIXES and not any(fnmatch.fnmatch(n, g) for g in excludes)]


def readable_text(path: Path) -> str:
    """File text as a reader sees it: JSON strings are decoded so escapes (\\u2019, \\n) and keys
    do not glue neighbouring turns into phrases that match by accident."""
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() not in (".json", ".jsonl"):
        return raw
    def strings(node):
        if isinstance(node, str):
            yield node
        elif isinstance(node, dict):
            for value in node.values():
                yield from strings(value)
        elif isinstance(node, list):
            for value in node:
                yield from strings(value)
    try:
        docs = [json.loads(raw)] if path.suffix.lower() == ".json" else [json.loads(l) for l in raw.splitlines() if l.strip()]
    except ValueError:
        return raw
    return "\n".join(s for doc in docs for s in strings(doc))


def scan(paths: list[Path], repo: Path, exact: dict, grams: dict, data_path: Path) -> dict:
    found = {}
    for path in paths:
        try:
            if path.resolve() == data_path.resolve() or path.stat().st_size > 500_000_000:
                continue
            text = normalize(readable_text(path))
        except (UnicodeDecodeError, OSError):
            continue
        hits = {}
        padded = f" {text} "
        for phrase, owner in exact.items():
            if f" {phrase} " in padded:
                hits.setdefault(owner, 0)
                hits[owner] += 1
        words = text.split()
        for i in range(max(0, len(words) - N + 1)):
            owner = grams.get(" ".join(words[i:i + N]))
            if owner:
                hits.setdefault(owner, 0)
                hits[owner] += 1
        if hits:
            found[str(path.relative_to(repo))] = sorted(
                ({"id": i, "kind": k, "matches": c} for (i, k), c in hits.items()), key=lambda h: h["id"])
    return found


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True)
    ap.add_argument("--format", required=True, choices=("longmemeval", "locomo", "jsonl"))
    ap.add_argument("--split", required=True, help="split.json written by split.py")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--exclude", action="append", default=[], help="glob of repo paths to skip (e.g. a results folder)")
    ap.add_argument("--names", action="store_true",
                    help="also list code/prompt files naming rare held-out entities (for human review; no exit failure)")
    ap.add_argument("--json", help="write the full report here")
    args = ap.parse_args()
    split_record = json.loads(Path(args.split).read_text(encoding="utf-8"))
    items = load(args.data, args.format)
    exact, grams = probes(items, set(split_record["heldout"]), set(split_record["dev"]))
    repo = Path(args.repo).resolve()
    found = scan(files_in(repo, args.exclude), repo, exact, grams, Path(args.data))
    names = rare_names(items, set(split_record["heldout"]), set(split_record["dev"]))
    review = name_review(files_in(repo, args.exclude), repo, names) if args.names else {}
    report = {"held_out_items": len(split_record["heldout"]), "files_with_hits": len(found), "hits": found,
              "name_review": review}
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    for name, hits in sorted(found.items(), key=lambda kv: -len(kv[1])):
        kinds = collections.Counter(h["kind"] for h in hits)
        print(f"{name}: {len(hits)} held-out item(s) {dict(kinds)}  e.g. {hits[0]['id']}")
    for name, hits in sorted(review.items()):
        print(f"REVIEW {name}: names {', '.join(hits)} from held-out item(s) {sorted({i for ids in hits.values() for i in ids})[:4]}")
    print(f"{len(found)} file(s) contain held-out material" if found else "clean: no held-out material found")
    if review:
        print(f"{len(review)} code/prompt file(s) name rare held-out entities: read each and remove any rule built for that question")
    sys.exit(1 if found else 0)


if __name__ == "__main__":
    main()
