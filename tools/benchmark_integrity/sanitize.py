#!/usr/bin/env python3
"""Split a benchmark file into what the system may see and what only the scorer may see.

Memory benchmarks ship their labels next to their inputs. LongMemEval marks
evidence turns with has_answer, lists answer_session_ids, names evidence
sessions with an "answer_" prefix, tags abstention questions with an "_abs"
id suffix and states question_type. LoCoMo stores answers, evidence dialogue
ids and categories beside each question. Any of these reaching ingestion,
retrieval or the reader is an answer key.

public.json  inputs only, with opaque question and session ids
key.json     opaque id -> original id, answer, type, evidence (scorer only)

  python sanitize.py --data longmemeval_s_cleaned.json --format longmemeval --out-dir run-inputs/
"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
from pathlib import Path


def opaque(salt: str, value: str) -> str:
    return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()[:16]


def longmemeval(rows: list[dict], salt: str) -> tuple[list[dict], dict]:
    public, key = [], {}
    for row in rows:
        qid = opaque(salt, row["question_id"])
        sessions = [[{"role": t.get("role"), "content": t.get("content")} for t in session]
                    for session in row.get("haystack_sessions", [])]
        sid_map = {sid: opaque(salt, f"{row['question_id']}/{sid}") for sid in row.get("haystack_session_ids", [])}
        public.append({
            "id": qid, "question": row["question"], "question_date": row.get("question_date"),
            "haystack_session_ids": [sid_map[s] for s in row.get("haystack_session_ids", [])],
            "haystack_dates": row.get("haystack_dates"), "haystack_sessions": sessions,
        })
        key[qid] = {"question_id": row["question_id"], "question_type": row.get("question_type"),
                    "question": row["question"], "answer": row.get("answer"),
                    "answer_session_ids": [sid_map.get(s, s) for s in row.get("answer_session_ids", [])]}
    return public, key


def locomo(samples: list[dict], salt: str) -> tuple[list[dict], dict]:
    public, key = [], {}
    for sample in samples:
        questions = []
        for i, qa in enumerate(sample.get("qa", [])):
            qid = opaque(salt, f"{sample.get('sample_id')}:{i}")
            questions.append({"id": qid, "question": qa.get("question")})
            key[qid] = {"sample_id": sample.get("sample_id"), "index": i, **qa}
        public.append({"sample_id": opaque(salt, str(sample.get("sample_id"))),
                       "conversation": sample.get("conversation"), "questions": questions})
    return public, key


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True)
    ap.add_argument("--format", required=True, choices=("longmemeval", "locomo"))
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    salt = secrets.token_hex(8)
    rows = json.loads(Path(args.data).read_text(encoding="utf-8"))
    public, key = (longmemeval if args.format == "longmemeval" else locomo)(rows, salt)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "public.json").write_text(json.dumps(public) + "\n", encoding="utf-8")
    (out / "key.json").write_text(json.dumps(key) + "\n", encoding="utf-8")
    text = (out / "public.json").read_text(encoding="utf-8")
    for marker in ('"has_answer"', '"answer_session_ids"', '"question_type"', '"answer_', '_abs"', '"evidence"', '"category"'):
        if marker in text:
            raise SystemExit(f"label marker {marker} still present in public.json")
    print(f"{len(key)} question(s): {out / 'public.json'} (system) and {out / 'key.json'} (scorer only)")


if __name__ == "__main__":
    main()
