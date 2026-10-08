"""Where the gold passages land: retrieval misses versus ranking misses.

For DEVELOPMENT splits only - never use held-out results to choose settings. For every
question it records the 1-based position of each gold passage in the passage-graph ranking
(top 100) and, with --rerank N, after the chat model reorders the top N. A gold passage
outside the top 100 is a retrieval miss; one inside it but below 5 is a ranking miss.

    python -m eval.miss_analysis <dataset dir> --out report.json [--rerank 10]

The dataset dir holds <name>.json and <name>_corpus.json in the HippoRAG layout. Evidence is
appended exactly as the public adapter captures it, so the CIDs match a warm passage index.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from eval.public.adapters.hipporag_multihop import normalize
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence
from mnemosyne.passages import ChatModel, PassageGraphIndex, PassageIndexStore
from mnemosyne.retrieval import HttpEmbeddingProvider

BUCKETS = (("top 2", 2), ("3-5", 5), ("6-10", 10), ("11-30", 30), ("31-100", 100))


def bucket(position: int | None) -> str:
    for name, limit in BUCKETS:
        if position is not None and position <= limit:
            return name
    return "not in top 100"


def question_types(dataset_dir: Path) -> dict[str, str]:
    """Question type by id: 2Wiki and HotpotQA carry 'type'; MuSiQue encodes hops in the id."""
    raw = next(p for p in dataset_dir.glob("*.json") if not p.name.endswith("_corpus.json"))
    types = {}
    for row in json.loads(raw.read_text(encoding="utf-8")):
        qid = row.get("_id") or row.get("id")
        types[qid] = row.get("type") or str(qid).split("__")[0]
    return types


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dataset_dir", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--index", default=r"C:\Users\Onfire\MnemetricData\passage-index.sqlite")
    ap.add_argument("--chat", default="qwen3:4b-instruct")
    ap.add_argument("--chat-url", default="http://127.0.0.1:11434/v1/chat/completions")
    ap.add_argument("--embed", default="qwen3-embedding:8b")
    ap.add_argument("--embed-url", default="http://127.0.0.1:11434/v1/embeddings")
    ap.add_argument("--dims", type=int, default=1024)
    ap.add_argument("--rerank", type=int, default=0)
    ap.add_argument("--query-vectors", type=Path, help="JSON cache of query vectors (read and extended)")
    args = ap.parse_args()

    assets = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in args.dataset_dir.glob("*.json")}
    bench = normalize({"assets": assets})
    dataset = bench["dataset"]
    tenant = f"public-hipporag-{dataset}"
    engine = LocalMemoryEngine()
    doc_of: dict[str, str] = {}
    for doc in bench["corpus"]:
        cid = engine.append_evidence(Evidence(
            tenant_id=tenant, user_id="benchmark-corpus", actor="user", source_type=f"hipporag:{dataset}",
            source_identity=doc["doc_id"], content=f"{doc['title']}\n{doc['content']}", access_policy={"tenant": tenant},
        ))
        doc_of[cid] = doc["doc_id"]
    filt = {"tenant_id": tenant, "tenant": tenant, "role": "reader", "branch": "main", "query_mode": "passages"}
    passages = engine.passage_candidates(filt)
    embedder = HttpEmbeddingProvider(url=args.embed_url, model=args.embed, dims=args.dims, query_prefix="",
                                     cache_size=0, timeout_seconds=600)
    graph = PassageGraphIndex(store=PassageIndexStore(args.index, read_only=True), extractor=args.chat,
                              chat=ChatModel(url=args.chat_url, model=args.chat), embedder=embedder)
    queries = [q["question"] for q in bench["questions"]]
    if args.query_vectors and args.query_vectors.exists():
        graph._query_vectors.update(json.loads(args.query_vectors.read_text(encoding="utf-8")))
    graph.prepare(queries, embedder)
    if args.query_vectors:
        args.query_vectors.write_text(json.dumps(graph._query_vectors), encoding="utf-8")
    types = question_types(args.dataset_dir)

    rows, started = [], time.perf_counter()
    for q in bench["questions"]:
        hits, explain = graph.rank(q["question"], passages, embedder, 100)
        ranked = [doc_of[h.id] for h in hits]
        final = ranked
        if args.rerank:
            head = hits[: args.rerank]
            chosen = graph._rerank(q["question"], head)
            first = [doc_of[head[j].id] for j in chosen]
            final = first + [d for d in ranked if d not in set(first)]
        rows.append({
            "question_id": q["question_id"],
            "type": types.get(q["question_id"], "?"),
            "graph": [ranked.index(g) + 1 if g in ranked else None for g in q["gold_references"]],
            "final": [final.index(g) + 1 if g in final else None for g in q["gold_references"]],
            "route": explain.get("route"),
        })

    def summary(key: str) -> dict:
        golds = [p for row in rows for p in row[key]]
        by_type: dict[str, list] = {}
        for row in rows:
            by_type.setdefault(row["type"], []).extend(row[key])
        recall5 = lambda ps: round(sum(1 for p in ps if p is not None and p <= 5) / max(len(ps), 1), 4)  # noqa: E731
        return {
            "recall_at_5_per_gold": recall5(golds),
            "buckets": dict(Counter(bucket(p) for p in golds)),
            "by_type": {t: {"golds": len(ps), "recall_at_5": recall5(ps)} for t, ps in sorted(by_type.items())},
        }

    report = {
        "dataset_dir": str(args.dataset_dir), "questions": len(rows), "rerank": args.rerank,
        "chat": args.chat, "embed": args.embed, "seconds": round(time.perf_counter() - started, 1),
        "graph": summary("graph"), "final": summary("final"), "rows": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=1))


if __name__ == "__main__":
    main()
