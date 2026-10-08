"""Recall@5 of a real memory store against a hand-written question set.

Runs MemoryTools.search in-process, configured exactly as the CLI configures it (backend,
adapters, MNEMOSYNE_PASSAGE_* from the environment), against a fresh COPY of a SQLite store
directory, so the real store is never touched. Each question scores the share of its gold
evidence CIDs (or CID prefixes) found among the first five ranked records. Keep the question
file outside git when it is built from private conversations:

    [{"id": "name", "kind": "fact", "question": "What is my name?", "gold": ["c9165dc4b830"],
      "now": "2026-10-02T11:13:42-07:00"}, ...]

"now" is the instant the question is asked at; it is passed on where search accepts one.

    python -m eval.store_recall --store <dir> --tenant burnos --user owner \\
        --questions q.json --out r.json [--mode passages] [--index-first]
"""

from __future__ import annotations

import argparse
import inspect
import json
import shutil
import tempfile
import time
from collections import defaultdict
from pathlib import Path


def hit_cids(hit: dict) -> list[str]:
    metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
    return [
        str(cid)
        for cid in [hit.get("id"), *(hit.get("provenance") or []), *(metadata.get("source_evidence_cids") or [])]
        if cid
    ]


def ranked_evidence(hits: list[dict]) -> list[str]:
    """Records in hit order: a hit counts as the first CID it names; a working-memory hit also
    counts the ledger records it cites. Duplicates are dropped."""
    ranked: list[str] = []
    for hit in hits:
        cids = hit_cids(hit)
        for cid in cids if hit.get("kind") == "working" else cids[:1]:
            if cid not in ranked:
                ranked.append(cid)
    return ranked


def main() -> None:
    from mnemosyne import cli

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", type=Path, required=True, help="SQLite store directory (copied, never modified)")
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--user", default=None)
    ap.add_argument("--questions", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--mode", choices=("default", "passages"), default="default")
    ap.add_argument("--index-first", action="store_true", help="index the copy's passages before asking")
    args = ap.parse_args()

    questions = json.loads(args.questions.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="store-recall-", ignore_cleanup_errors=True) as temp:
        store = Path(temp) / "store"
        shutil.copytree(args.store, store)
        cli_args = cli.build_parser().parse_args(
            ["--backend", "sqlite", "--store", str(store), "search", "--tenant", args.tenant, "--query", "-"]
        )
        tools = cli.load_tools(cli_args)
        index_report = tools.index_passages(args.tenant) if args.index_first else None
        accepts = set(inspect.signature(tools.search).parameters)
        graph = getattr(tools.engine.adapters, "passage_graph", None)
        if graph is not None:
            graph.prepare([q["question"] for q in questions], tools.engine.adapters.embedding)
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
            })
        seconds = time.perf_counter() - started
        close = getattr(tools.engine, "close", None)
        if callable(close):
            close()

    scores = [row["recall_at_5"] for row in rows_out]
    known = sorted(latencies)
    report = {
        "store": str(args.store), "tenant": args.tenant, "mode": args.mode, "questions": len(scores),
        "passage_graph": graph is not None, "index_report": index_report,
        "recall_at_5": round(sum(scores) / len(scores), 4),
        "by_kind": {kind: round(sum(v) / len(v), 4) for kind, v in sorted(per_kind.items())},
        "abstained": sum(1 for row in rows_out if row["abstained"]),
        "latency_ms": {"p50": round(known[len(known) // 2], 1), "p95": round(known[int(0.95 * (len(known) - 1))], 1)},
        "seconds": round(seconds, 1), "rows": rows_out,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}))


if __name__ == "__main__":
    main()
