"""LongMemEval-S session recall@5, in-process, with a fixed development / held-out split.

Each question gets its own engine holding only its haystack sessions (as the public adapter
does), and recall@5 is |gold sessions in the top five| / |gold sessions|. The split is fixed
by question id before any score is seen: the 100 questions with the lowest sha256(id) are the
development set used for tuning; the other 400 are held out and are only ever measured.

    python -m eval.longmemeval_recall --data <dir with longmemeval_s_cleaned.json and
        longmemeval_oracle.json> --out report.json [--split dev|heldout|all] [--modes default,passages]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import defaultdict
from pathlib import Path

from eval.public.adapters.longmemeval import normalize
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence
from mnemosyne.policy import OperatingPolicy

DEV_SIZE = 100


def split_of(question_ids: list[str]) -> dict[str, str]:
    ordered = sorted(question_ids, key=lambda qid: hashlib.sha256(qid.encode("utf-8")).hexdigest())
    return {qid: ("dev" if rank < DEV_SIZE else "heldout") for rank, qid in enumerate(ordered)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--split", choices=("dev", "heldout", "all"), default="all")
    ap.add_argument("--modes", default="default,passages")
    args = ap.parse_args()
    modes = [mode.strip() for mode in args.modes.split(",") if mode.strip()]

    assets = {
        name: json.loads((args.data / name).read_text(encoding="utf-8"))
        for name in ("longmemeval_s_cleaned.json", "longmemeval_oracle.json")
    }
    bench = normalize({"assets": assets})
    del assets
    by_question: dict[str, list[dict]] = defaultdict(list)
    for document in bench["corpus"]:
        by_question[document["question_id"]].append(document)
    splits = split_of([q["question_id"] for q in bench["questions"]])

    rows, started = [], time.perf_counter()
    for number, question in enumerate(bench["questions"], 1):
        qid = question["question_id"]
        if args.split != "all" and splits[qid] != args.split:
            continue
        tenant = f"longmemeval:{qid}"
        engine = LocalMemoryEngine(policy=OperatingPolicy(top_k=24, token_budget=262_144))
        session_of: dict[str, str] = {}
        for document in by_question[qid]:
            cid = engine.append_evidence(Evidence(
                tenant_id=tenant, user_id="longmemeval", actor="user",
                source_type=f"longmemeval:{document['session_id']}", source_identity=document["session_id"],
                content=document["content"], access_policy={"tenant": tenant},
            ))
            session_of[cid] = document["session_id"]
        row = {"question_id": qid, "split": splits[qid], "sessions": len(session_of)}
        gold = set(question["answer_session_ids"])
        for mode in modes:
            filt = {"role": "reader"} | ({"query_mode": "passages"} if mode == "passages" else {})
            result = engine.retrieve(question["query"], tenant_id=tenant, filt=filt, record_access=False)
            ranked: list[str] = []
            for hit in result.hits:
                session = session_of.get(hit.id)
                if session is not None and session not in ranked:
                    ranked.append(session)
            row[mode] = round(len(gold & set(ranked[:5])) / len(gold), 4)
        rows.append(row)
        if number % 50 == 0:
            print(f"{number}/{len(bench['questions'])} {time.perf_counter() - started:.0f}s", flush=True)

    summary = {}
    for split in sorted({row["split"] for row in rows}):
        part = [row for row in rows if row["split"] == split]
        summary[split] = {"questions": len(part)} | {
            f"{mode}_recall_at_5": round(sum(row[mode] for row in part) / len(part), 4) for mode in modes
        }
    report = {"summary": summary, "seconds": round(time.perf_counter() - started, 1), "rows": rows}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}))


if __name__ == "__main__":
    main()
