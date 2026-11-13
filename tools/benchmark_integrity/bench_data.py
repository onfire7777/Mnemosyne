"""Shared loading for memory-benchmark datasets (stdlib only).

Every item becomes a dict with: id, type, question, answer, evidence (list of
gold evidence strings, may be empty), context (list of all haystack strings).

Supported formats:
  longmemeval  LongMemEval json (s/m/oracle): list of questions with
               haystack_sessions; gold evidence = turns with has_answer, or
               sessions listed in answer_session_ids.
  locomo       LoCoMo json: list of samples with conversation + qa; evidence
               = dialogue turns named in qa[].evidence.
  jsonl        one object per line with fields id, question, answer and
               optional type, evidence (list[str]), context (list[str]).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


def load(path: str | Path, fmt: str) -> list[dict]:
    path = Path(path)
    if fmt == "longmemeval":
        return [_lme(row) for row in json.loads(path.read_text(encoding="utf-8"))]
    if fmt == "locomo":
        items = []
        for sample in json.loads(path.read_text(encoding="utf-8")):
            items.extend(_locomo(sample))
        return items
    if fmt == "jsonl":
        items = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                items.append({
                    "id": str(row["id"]), "type": str(row.get("type", "")),
                    "question": str(row["question"]), "answer": str(row.get("answer", "")),
                    "evidence": [str(x) for x in row.get("evidence", [])],
                    "context": [str(x) for x in row.get("context", [])],
                })
        return items
    raise SystemExit(f"unknown format {fmt!r} (longmemeval, locomo, jsonl)")


def _lme(row: dict) -> dict:
    gold_sessions = set(row.get("answer_session_ids") or [])
    evidence, context = [], []
    for sid, session in zip(row.get("haystack_session_ids") or [], row.get("haystack_sessions") or []):
        for turn in session:
            text = str(turn.get("content", ""))
            context.append(text)
            if turn.get("has_answer") or (sid in gold_sessions and turn.get("role") == "user"):
                evidence.append(text)
    qid = str(row["question_id"])
    qtype = str(row.get("question_type", "")) + ("/abstention" if qid.endswith("_abs") else "")
    return {"id": qid, "type": qtype, "question": str(row["question"]),
            "answer": str(row.get("answer", "")), "evidence": evidence, "context": context}


def _locomo(sample: dict) -> list[dict]:
    turns = {}
    conv = sample.get("conversation", {})
    for key, value in conv.items():
        if isinstance(value, list):
            for turn in value:
                if isinstance(turn, dict) and "dia_id" in turn:
                    turns[turn["dia_id"]] = str(turn.get("text", ""))
    out = []
    for i, qa in enumerate(sample.get("qa", [])):
        out.append({
            "id": f"{sample.get('sample_id', 'sample')}:{i}", "type": str(qa.get("category", "")),
            "question": str(qa.get("question", "")),
            "answer": str(qa.get("answer", qa.get("adversarial_answer", ""))),
            "evidence": [turns[d] for d in qa.get("evidence", []) if d in turns],
            "context": list(turns.values()),
        })
    return out


def split(items: list[dict], dev_size: int) -> tuple[set[str], set[str]]:
    """Deterministic split: the dev_size ids with the lowest sha256(id) are development."""
    ranked = sorted(items, key=lambda item: hashlib.sha256(item["id"].encode()).hexdigest())
    dev = {item["id"] for item in ranked[:dev_size]}
    return dev, {item["id"] for item in items} - dev


def normalize(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def shingles(text: str, n: int = 8) -> set[str]:
    words = normalize(text).split()
    return {" ".join(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
