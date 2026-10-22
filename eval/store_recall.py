"""Recall@5 of a real memory store against a hand-written question set.

Runs MemoryTools.search in-process, configured exactly as the CLI configures it (backend,
adapters, MNEMOSYNE_PASSAGE_* from the environment), against a temporary SQLite store
snapshot. Each database and its journals are copied during an observed stable file window,
then backed up through a read-only connection to that private copy, including committed
WAL data. Other files are copied. Databases and assets are not captured at one
atomic instant across the whole directory. Each question scores the share of its gold
evidence CIDs (or CID prefixes) found among the first five ranked records. Keep the question
file outside git when it is built from private conversations:

    [{"id": "name", "kind": "fact", "question": "What is my name?", "gold": ["c9165dc4b830"],
      "now": "2026-10-02T11:13:42-07:00"}, ...]

"now" is the instant the question is asked at; it is passed on where search accepts one.
Optional "query_timezone" is an IANA zone for local-day queries (for example,
"America/Los_Angeles") and is forwarded when supported by the search implementation.

    python -m eval.store_recall --store <dir> --tenant burnos --user owner \\
        --questions q.json --out r.json [--mode passages] [--index-first]
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import shutil
import sqlite3
import tempfile
import time
from collections import defaultdict
from contextlib import ExitStack, closing
from pathlib import Path

from eval.harness.metrics import percentile, resolve_retrieved_doc_ids


def hit_cids(hit: dict) -> list[str]:
    metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
    provenance = hit.get("provenance")
    sources = metadata.get("source_evidence_cids")
    return [
        cid
        for cid in [
            hit.get("id"),
            *(provenance if isinstance(provenance, (list, tuple)) else []),
            *(sources if isinstance(sources, (list, tuple)) else []),
        ]
        if isinstance(cid, str) and cid
    ]


def ranked_evidence(hits: list[dict]) -> list[str]:
    """Rank records, never expand a working-memory citation list into retrieved hits."""
    identities = {cid: cid for hit in hits for cid in hit_cids(hit)}
    return resolve_retrieved_doc_ids(hits, identities)


def snapshot_sqlite_database(source: Path, target: Path) -> None:
    """Create a standalone DB without opening the original through SQLite.

    Even mode=ro can create WAL/SHM files beside an original database. Stage the
    data-bearing files first and reject a copy if any file identity, size or change
    timestamp moves. This assumes ordinary filesystem change timestamps; it is not
    an adversarial-filesystem guarantee. Continually changing stores fail closed.
    A hot rollback journal that requires recovery also fails closed in read-only mode.
    """
    source = source.resolve()
    data_files = [source, Path(str(source) + "-wal"), Path(str(source) + "-journal")]

    def signatures() -> list[tuple[int, ...] | None]:
        values = []
        for path in data_files:
            try:
                stat = path.stat()
            except FileNotFoundError:
                values.append(None)
            else:
                values.append((stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
        return values

    for _ in range(3):
        with tempfile.TemporaryDirectory(prefix="sqlite-snapshot-", dir=target.parent) as temp:
            staged = Path(temp) / "source.sqlite"
            before = signatures()
            if before[0] is None:
                raise FileNotFoundError(source)
            try:
                for path, signature, suffix in zip(data_files, before, ("", "-wal", "-journal")):
                    if signature is not None:
                        shutil.copy2(path, Path(str(staged) + suffix))
            except FileNotFoundError:
                continue  # A checkpoint may remove a WAL while it is being staged.
            if signatures() != before:
                continue
            with closing(sqlite3.connect(f"{staged.as_uri()}?mode=ro", uri=True)) as original:
                with closing(sqlite3.connect(target)) as copy:
                    original.backup(copy)
            return
    raise RuntimeError(f"SQLite source changed during three snapshot attempts: {source}")


def snapshot_store(source: Path, target: Path) -> None:
    """Copy assets and take individually consistent backups of the store's databases.

    SqliteEngine stores tenant databases as root-level *.db files. Recognize other
    SQLite files by their header so nested caches/sidecars are also backed up.
    SQLite journals belong to their database snapshot and must not be copied onto it.
    Concurrent changes across different databases or non-database files are not atomic.
    """
    source = source.resolve()

    def is_database(path: Path) -> bool:
        if not path.is_file():
            return False
        if path.parent == source and path.suffix == ".db":
            return True
        with path.open("rb") as stream:
            return stream.read(16) == b"SQLite format 3\x00"

    def ignore_journals(directory: str, names: list[str]) -> set[str]:
        databases = {name for name in names if is_database(Path(directory) / name)}
        return {name + suffix for name in databases for suffix in ("-wal", "-shm", "-journal")}

    def copy_file(src: str, dst: str) -> str:
        if is_database(Path(src)):
            snapshot_sqlite_database(Path(src), Path(dst))
            shutil.copystat(src, dst)
            return dst
        return shutil.copy2(src, dst)

    shutil.copytree(source, target, copy_function=copy_file, ignore=ignore_journals)


def main() -> None:
    from mnemosyne import cli
    from mnemosyne.retrieval import resolve_query_timezone

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", type=Path, required=True, help="SQLite store directory (copied, never modified)")
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--user", default=None)
    ap.add_argument("--questions", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--mode", choices=("default", "passages"), default="default")
    ap.add_argument("--index-first", action="store_true", help="index the copy's passages before asking")
    args = ap.parse_args()

    if args.out.resolve().is_relative_to(args.store.resolve()):
        ap.error("output must be outside the source store")
    if args.out.exists():
        for source_file in args.store.rglob("*"):
            if source_file.is_file() and args.out.samefile(source_file):
                ap.error("output must not alias a source store file")
    passage_path = os.environ.get("MNEMOSYNE_PASSAGE_INDEX")
    source_passage_index = Path(passage_path).resolve() if passage_path else None
    if source_passage_index is not None:
        for suffix in ("", "-wal", "-shm", "-journal"):
            protected = Path(str(source_passage_index) + suffix)
            if args.out.resolve() == protected.resolve() or (
                args.out.exists() and protected.exists() and args.out.samefile(protected)
            ):
                ap.error("output must not replace the source passage index or its SQLite sidecars")

    questions = json.loads(args.questions.read_text(encoding="utf-8"))
    if not isinstance(questions, list) or not questions:
        ap.error("questions must be a non-empty JSON array")
    for question in questions:
        if not isinstance(question, dict):
            ap.error("each question must be a JSON object")
        gold = question.get("gold")
        if not isinstance(gold, list) or not gold or any(
            not isinstance(cid, str) or not cid.strip() for cid in gold
        ):
            ap.error("each question requires a non-empty gold list of non-blank CID strings")
        query = question.get("question")
        if not isinstance(query, str) or not query.strip():
            ap.error("each question requires non-blank question text")
        if "id" not in question:
            ap.error("each question requires an id")
        if "query_timezone" in question:
            try:
                resolve_query_timezone(question["query_timezone"])
            except ValueError as exc:
                ap.error(str(exc))
    with tempfile.TemporaryDirectory(prefix="store-recall-", ignore_cleanup_errors=True) as temp, ExitStack() as cleanup:
        store = Path(temp) / "store"
        snapshot_store(args.store, store)
        cli_args = cli.build_parser().parse_args(
            ["--backend", "sqlite", "--store", str(store), "search", "--tenant", args.tenant, "--query", "-"]
        )
        if source_passage_index is not None:
            passage_copy = Path(temp) / "passage-index.sqlite"
            if source_passage_index.exists():
                snapshot_sqlite_database(source_passage_index, passage_copy)
            cli_args.passage_index = str(passage_copy)
        tools = cli.load_tools(cli_args)
        close = getattr(tools.engine, "close", None)
        if callable(close):
            cleanup.callback(close)
        accepts = set(inspect.signature(tools.search).parameters)
        graph = getattr(tools.engine.adapters, "passage_graph", None)
        graph_close = getattr(getattr(graph, "store", None), "close", None)
        if callable(graph_close):
            cleanup.callback(graph_close)
        index_report = tools.index_passages(args.tenant) if args.index_first else None
        query_preparation_seconds = 0.0
        if graph is not None:
            preparation_started = time.perf_counter()
            graph.prepare([q["question"] for q in questions], tools.engine.adapters.embedding)
            query_preparation_seconds = time.perf_counter() - preparation_started
        rows_out: list[dict] = []
        latencies: list[float] = []
        per_kind: dict[str, list[float]] = defaultdict(list)
        started = time.perf_counter()
        for q in questions:
            kwargs: dict = {"lean": True}
            if args.user:
                kwargs["user_id"] = args.user
            if args.mode == "passages":
                kwargs["query_mode"] = "passages"
            if q.get("now") and "evaluated_at" in accepts:
                kwargs["evaluated_at"] = q["now"]
            if "query_timezone" in q and "query_timezone" in accepts:
                kwargs["query_timezone"] = q["query_timezone"]
            asked = time.perf_counter()
            result = tools.search(tenant_id=args.tenant, query=q["question"], **kwargs)
            latencies.append((time.perf_counter() - asked) * 1000.0)
            top5 = ranked_evidence(result.get("hits", []))[:5]
            found = [g for g in q["gold"] if any(cid.startswith(g) for cid in top5)]
            score = len(found) / len(q["gold"])
            per_kind[q.get("kind", "?")].append(score)
            rows_out.append({
                "id": q["id"], "kind": q.get("kind"), "recall_at_5": score,
                "abstained": result.get("abstained"), "top5": [cid[:12] for cid in top5],
                "top5_evidence_cids": top5,
            })
        seconds = time.perf_counter() - started

    scores = [row["recall_at_5"] for row in rows_out]
    report = {
        "store": str(args.store), "tenant": args.tenant, "mode": args.mode, "questions": len(scores),
        "passage_graph": graph is not None, "index_report": index_report,
        "recall_at_5": round(sum(scores) / len(scores), 4),
        "by_kind": {kind: round(sum(v) / len(v), 4) for kind, v in sorted(per_kind.items())},
        "abstained": sum(1 for row in rows_out if row["abstained"]),
        "latency_ms": {"p50": round(percentile(latencies, 0.5), 1), "p95": round(percentile(latencies, 0.95), 1)},
        "latency_scope": "search_calls_excluding_setup_and_query_preparation",
        "query_vectors_prepared": graph is not None,
        "query_preparation_seconds": round(query_preparation_seconds, 3),
        "seconds": round(seconds, 1), "rows": rows_out,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}))


if __name__ == "__main__":
    main()
