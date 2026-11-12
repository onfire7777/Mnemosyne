#!/usr/bin/env python3
"""Rebuild the quality-gate QA files from the LongMemEval-S development split only.

The development split is the 100 question_ids with the lowest sha256(question_id)
hex digest (eval/longmemeval_s/README.md); the other 400 are held out and never
enter the gate. Category mapping of development questions:

  temporal-reasoning                      -> temporal_reasoning
  multi-session                           -> multi_session_aggregation
  knowledge-update (2+ evidence sessions) -> knowledge_updates_supersession
      superseded = earliest evidence session, current = latest (by date, then position)
  *_abs (native LongMemEval abstention)   -> abstention
  single-session-user / -assistant        -> abstention, with every gold evidence
      session removed from the haystack (qid suffix "_gold_removed", no gold refs)
  single-session-preference               -> not used

The 24 non-LongMemEval multi_hop cases are carried over unchanged from the current
files. Each category's cases are ordered by sha256(qid); the first half (rounded up)
is the gate's dev partition, the rest its held-out partition. Answers are not stored.

Usage: python eval/datasets/quality_gate/build_quality_gate.py --data longmemeval_s_cleaned.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
CATEGORIES = ["temporal_reasoning", "multi_session_aggregation",
              "knowledge_updates_supersession", "abstention", "multi_hop"]
SECURITY_FILES = ["integrity_cases.json", "poison_guard.json"]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _iso(lme_date: str) -> str:
    # LongMemEval dates look like "2023/05/30 (Tue) 23:40"; the gate stores UTC ISO-8601.
    return datetime.strptime(lme_date[:10] + lme_date[-5:], "%Y/%m/%d%H:%M").replace(tzinfo=UTC).isoformat()


def _case(row: dict, category: str, *, qid: str | None = None, drop: set[str] = frozenset(),
          gold: list[str] | None = None, superseded: str | None = None, current: str | None = None) -> dict:
    kept = [i for i, sid in enumerate(row["haystack_session_ids"]) if sid not in drop]
    return {
        "category": category,
        "current_session_id": current,
        "distractor_answer": None,
        "gold_answer": None,
        "gold_references": list(row["answer_session_ids"]) if gold is None else gold,
        "haystack_dates": [_iso(row["haystack_dates"][i]) for i in kept],
        "haystack_session_ids": [row["haystack_session_ids"][i] for i in kept],
        "haystack_sessions": [row["haystack_sessions"][i] for i in kept],
        "qid": qid or row["question_id"],
        "query": row["question"],
        "question_date": _iso(row["question_date"]),
        "superseded_session_id": superseded,
    }


def development_cases(data: list[dict]) -> list[dict]:
    dev_ids = {q for _, q in sorted((_sha(r["question_id"]), r["question_id"]) for r in data)[:100]}
    cases = []
    for row in sorted((r for r in data if r["question_id"] in dev_ids), key=lambda r: r["question_id"]):
        kind, gold = row["question_type"], row["answer_session_ids"]
        if row["question_id"].endswith("_abs"):
            cases.append(_case(row, "abstention"))
        elif kind == "temporal-reasoning":
            cases.append(_case(row, "temporal_reasoning"))
        elif kind == "multi-session":
            cases.append(_case(row, "multi_session_aggregation"))
        elif kind == "knowledge-update" and len(gold) >= 2:
            position = {sid: i for i, sid in enumerate(row["haystack_session_ids"])}
            when = dict(zip(row["haystack_session_ids"], row["haystack_dates"]))
            ordered = sorted(gold, key=lambda sid: (_iso(when[sid]), position[sid]))
            cases.append(_case(row, "knowledge_updates_supersession",
                               superseded=ordered[0], current=ordered[-1]))
        elif kind in {"single-session-user", "single-session-assistant"}:
            cases.append(_case(row, "abstention", qid=row["question_id"] + "_gold_removed",
                               drop=set(gold), gold=[]))
    return cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, required=True, help="longmemeval_s_cleaned.json")
    args = parser.parse_args(argv)
    raw = args.data.read_bytes()
    data = json.loads(raw)
    if len(data) != 500:
        raise SystemExit(f"expected the 500-question LongMemEval-S file, got {len(data)} rows")

    old = [q for name in ("quality_gate_dev.json", "quality_gate_heldout.json")
           for q in json.loads((HERE / name).read_text(encoding="utf-8"))["queries"]]
    multi_hop = [q for q in old if q["category"] == "multi_hop"]
    if len(multi_hop) != 24:
        raise SystemExit(f"expected 24 carried-over multi_hop cases, got {len(multi_hop)}")

    partitions: dict[str, list[dict]] = {"dev": [], "heldout": []}
    counts: dict[str, dict[str, int]] = {}
    lme = development_cases(data)
    for category in CATEGORIES:
        if category == "multi_hop":
            rows = sorted(multi_hop, key=lambda q: (q["split"] != "dev", q["qid"]))
            dev_n = sum(q["split"] == "dev" for q in rows)
        else:
            rows = sorted((q for q in lme if q["category"] == category), key=lambda q: _sha(q["qid"]))
            dev_n = (len(rows) + 1) // 2
        for i, case in enumerate(rows):
            part = "dev" if i < dev_n else "heldout"
            partitions[part].append({**case, "split": "dev" if part == "dev" else "held-out"})
        counts[category] = {"dev": dev_n, "heldout": len(rows) - dev_n, "total": len(rows)}

    files = {}
    for part, queries in partitions.items():
        name = f"quality_gate_{part}.json"
        body = json.dumps({"queries": queries, "schema_version": "1.0.0",
                           "split": "dev" if part == "dev" else "held-out",
                           "total_queries": len(queries)}, indent=2, sort_keys=True)
        (HERE / name).write_text(body, encoding="utf-8")
        files[name] = _sha(body)
    for name in SECURITY_FILES:
        files[name] = hashlib.sha256((HERE / name).read_bytes()).hexdigest()

    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    for category, block in counts.items():
        manifest["categories"][category] = block
    qa_dev, qa_held = len(partitions["dev"]), len(partitions["heldout"])
    manifest["counts"].update(qa_dev=qa_dev, qa_heldout=qa_held, qa_total=qa_dev + qa_held,
                              total_evaluation_items=qa_dev + qa_held + manifest["counts"]["security_total"])
    manifest["files"] = dict(sorted(files.items()))
    manifest["generated_at"] = datetime.now(UTC).isoformat()
    manifest["source"] = {
        "builder": "build_quality_gate.py",
        "longmemeval_s_cleaned_sha256": hashlib.sha256(raw).hexdigest(),
        "longmemeval_split": "development only: 100 lowest sha256(question_id); held-out questions excluded",
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    held = {q for _, q in sorted((_sha(r["question_id"]), r["question_id"]) for r in data)[100:]}
    leaked = [q["qid"] for q in partitions["dev"] + partitions["heldout"]
              if q["qid"].removesuffix("_gold_removed") in held]
    assert not leaked, f"held-out LongMemEval questions in gate: {leaked}"
    print(json.dumps({"counts": counts, "qa_dev": qa_dev, "qa_heldout": qa_held}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
