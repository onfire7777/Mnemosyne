"""LongMemEval-S session recall@5, in-process, with a fixed development / held-out split.

Each question gets its own engine holding only its haystack sessions (as the public adapter
does), and recall@5 is |gold sessions in the top five| / |gold sessions|. The split is fixed
by question id before any score is seen: the 100 questions with the lowest sha256(id) are the
development set used for tuning; the other 400 are held out and are only ever measured.
Unanswerable (_abs) questions are excluded from retrieval scoring after the split is fixed.
Session dates and the question clock are preserved; naive benchmark dates mean UTC.

    python -m eval.longmemeval_recall --data <dir with longmemeval_s_cleaned.json and
        longmemeval_oracle.json> --out report.json [--split dev|heldout|all]
        [--modes default,passages] [--limit 5]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from eval.datasets.longmemeval_loader import normalize
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence
from mnemosyne.policy import OperatingPolicy

DEV_SIZE = 100


def split_of(question_ids: list[str]) -> dict[str, str]:
    ordered = sorted(question_ids, key=lambda qid: hashlib.sha256(qid.encode("utf-8")).hexdigest())
    return {qid: ("dev" if rank < DEV_SIZE else "heldout") for rank, qid in enumerate(ordered)}


def benchmark_timestamp(value: object, field: str) -> datetime:
    """Parse official calendar dates or ISO instants without using the host timezone."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"LongMemEval {field} must be a timestamp string")
    calendar = re.fullmatch(r"(\d{4}/\d{2}/\d{2}) \([A-Za-z]{3}\) (\d{2}:\d{2}(?::\d{2})?)", value)
    normalized = f"{calendar[1].replace('/', '-')}T{calendar[2]}" if calendar else value
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"LongMemEval {field} is not a valid benchmark or ISO timestamp") from exc
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _question_index(rows: object, label: str) -> dict[str, dict]:
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"LongMemEval {label} must be a non-empty list")
    indexed = {}
    for row in rows:
        qid = row.get("question_id") if isinstance(row, dict) else None
        if not isinstance(qid, str) or not qid.strip():
            raise ValueError(f"LongMemEval {label} question_id must be a non-empty string")
        if qid in indexed:
            raise ValueError(f"duplicate LongMemEval {label} question_id: {qid}")
        indexed[qid] = row
    return indexed


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--split", choices=("dev", "heldout", "all"), default="all")
    ap.add_argument("--modes", default="default,passages")
    ap.add_argument("--limit", type=int, default=0,
                    help="evaluate at most N answerable questions after fixing the split (0 means all)")
    args = ap.parse_args()
    modes = [mode.strip() for mode in args.modes.split(",") if mode.strip()]
    if not modes or any(mode not in {"default", "passages"} for mode in modes):
        ap.error("--modes must contain default and/or passages")
    if args.limit < 0:
        ap.error("--limit must be non-negative")

    assets, hashes = {}, {}
    for name in ("longmemeval_s_cleaned.json", "longmemeval_oracle.json"):
        raw = (args.data / name).read_bytes()
        hashes[name] = hashlib.sha256(raw).hexdigest()
        assets[name] = json.loads(raw)
    cleaned = _question_index(assets["longmemeval_s_cleaned.json"], "cleaned")
    oracle = _question_index(assets["longmemeval_oracle.json"], "oracle")
    if cleaned.keys() != oracle.keys():
        raise ValueError("LongMemEval oracle question set does not match cleaned asset")
    splits = split_of(list(cleaned))
    partition = [qid for qid in cleaned if args.split == "all" or splits[qid] == args.split]
    excluded = [qid for qid in partition if qid.endswith("_abs")]
    eligible = [qid for qid in partition if not qid.endswith("_abs")]
    selected = eligible[:args.limit] if args.limit else eligible
    question_dates, session_dates = {}, {}
    for qid in selected:
        row = cleaned[qid]
        question_dates[qid] = benchmark_timestamp(row.get("question_date"), f"{qid} question_date")
        dates, sessions = row.get("haystack_dates"), row.get("haystack_sessions")
        if not isinstance(dates, list) or not isinstance(sessions, list) or len(dates) != len(sessions):
            raise ValueError(f"LongMemEval {qid} haystack_dates must align with haystack_sessions")
        session_dates[qid] = [
            benchmark_timestamp(date, f"{qid} haystack_dates[{index}]") for index, date in enumerate(dates)
        ]
    bench = normalize({"assets": {
        "longmemeval_s_cleaned.json": [cleaned[qid] for qid in selected],
        "longmemeval_oracle.json": [oracle[qid] for qid in selected],
    }}) if selected else {"corpus": [], "questions": []}
    del cleaned, oracle, raw
    del assets
    by_question: dict[str, list[dict]] = defaultdict(list)
    for document in bench["corpus"]:
        by_question[document["question_id"]].append(document)
    rows, started = [], time.perf_counter()
    for number, question in enumerate(bench["questions"], 1):
        qid = question["question_id"]
        tenant = f"longmemeval:{qid}"
        engine = LocalMemoryEngine(policy=OperatingPolicy(top_k=24, token_budget=262_144))
        session_of: dict[str, str] = {}
        for document, created_at in zip(by_question[qid], session_dates[qid], strict=True):
            cid = engine.append_evidence(Evidence(
                tenant_id=tenant, user_id="longmemeval", actor="user",
                source_type=f"longmemeval:{document['session_id']}", source_identity=document["session_id"],
                content=document["content"], created_at=created_at, access_policy={"tenant": tenant},
            ))
            session_of[cid] = document["session_id"]
        question_date = question_dates[qid].isoformat()
        row = {"question_id": qid, "split": splits[qid], "sessions": len(session_of),
               "question_date": question_date}
        gold = set(question["answer_session_ids"])
        for mode in modes:
            filt = {"role": "reader", "evaluated_at": question_date, "query_timezone": "UTC"}
            if mode == "passages":
                filt["query_mode"] = "passages"
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
    report = {
        "summary": summary, "seconds": round(time.perf_counter() - started, 1), "rows": rows,
        "split": args.split, "limit": args.limit, "modes": modes, "timestamp_timezone": "UTC",
        "dataset_sha256": hashes, "eligible_questions": len(eligible), "evaluated_questions": len(rows),
        "excluded_question_ids": excluded, "exclusion_reason": "unanswerable (_abs) questions have no retrieval gold",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}))


if __name__ == "__main__":
    main()
