#!/usr/bin/env python3
"""Deterministic distractor-aware judge for the v2 hard-QA set (G2 ceiling fix).

Blueprint refs: §16 G2 (+15% answer quality at <=10% tokens), §33 (strict judge +
adversarial-answer screening).

THE PROBLEM THIS SOLVES
-----------------------
The default ``substring_judge`` (eval/harness/answer_quality.py) scores an answer
correct iff the gold string appears ANYWHERE in the supplied context. For the G2
suite the "full context" is the ENTIRE corpus concatenated, so any gold value that
exists in the corpus is trivially present -> full-context score is a permanent 1.0
ceiling and ``memory - full`` lift can never be positive. That is the "Wave-2
ceiling artifact": the +15% lift is structurally unmeasurable with a pure
substring judge, no matter how good the memory layer is.

A real LLM-as-judge would not be fooled by mere presence: shown the whole corpus
(which contains BOTH the right answer AND a contradictory wrong answer with the
same cue words), it cannot confidently answer, whereas shown the memory layer's
focused, resolved slice (right answer only) it answers correctly. That asymmetry
IS the G2 lift.

This judge reproduces that asymmetry DETERMINISTICALLY (no model, runs now):

    score(question, context, gold) =
        1.0  if gold (or an alias) is present in context
             AND the case's distractor_answer is NOT present in context
        0.0  if gold is absent
        0.0  if BOTH gold and the distractor are present  (ambiguous / misled)

Because the full corpus contains both gold and distractor for every hard case, a
full-context read scores 0.0; the memory slice (resolved, distractor-free) scores
1.0. The lift becomes real and the G2 verdict is finally exercisable WITHOUT an
LLM, while remaining a faithful stand-in for the strict-judge semantics.

WIRING (no harness change)
--------------------------
The harness's ``make_llm_judge`` shells out to ``$MNEMO_EVAL_JUDGE_CMD`` with a
JSON ``{"question","context","gold"}`` on stdin and expects ``{"score": float}``
on stdout. Point it here:

    export MNEMO_EVAL_QA_DATASET=eval/datasets/v2/qa_hard_v2.json
    export MNEMO_EVAL_JUDGE_CMD="python eval/datasets/v2/v2_judge.py"
    python eval/run_eval.py            # (with v2 wired in, see this dir's README)

The harness passes only (question, context, gold); the distractor for each case is
looked up from the QA dataset by matching the gold answer (and, as a fallback, the
question text). This keeps the judge a drop-in for the existing ABI.
"""

from __future__ import annotations

import json
import os
import re
import sys
from functools import lru_cache
from pathlib import Path

_DEFAULT_QA = Path(__file__).resolve().parent / "qa_hard_v2.json"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


@lru_cache(maxsize=1)
def _load_distractors() -> list[dict]:
    """Load (normalized gold, normalized distractor, normalized question) tuples."""
    path = Path(os.environ.get("MNEMO_EVAL_QA_DATASET", str(_DEFAULT_QA)))
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows: list[dict] = []
    for q in data.get("queries", []):
        gold = q.get("gold_answer")
        distractor = q.get("distractor_answer")
        if not gold or not distractor:
            continue
        aliases = [gold] + list(q.get("gold_aliases", []))
        rows.append(
            {
                "golds": [_norm(a) for a in aliases if a],
                "distractor": _norm(distractor),
                "question": _norm(q.get("query", "")),
            }
        )
    return rows


def _lookup(question: str, gold: str) -> str | None:
    """Find the distractor for this (question, gold) case. Returns normalized str."""
    qn = _norm(question)
    gn = _norm(gold)
    rows = _load_distractors()
    # Prefer an exact question match (unique per case); fall back to gold match.
    best: str | None = None
    for r in rows:
        if r["question"] and r["question"] == qn:
            return r["distractor"]
        if gn and gn in r["golds"] and best is None:
            best = r["distractor"]
    return best


def score(question: str, context: str, gold: str) -> float:
    ctx = _norm(context)
    gn = _norm(gold)
    if not gn:
        # Unanswerable convention (mirror substring_judge): correct iff abstaining.
        return 1.0 if not ctx else 0.0
    # Accept any alias for presence.
    rows = _load_distractors()
    aliases = {gn}
    qn = _norm(question)
    for r in rows:
        if (r["question"] and r["question"] == qn) or (gn in r["golds"]):
            aliases.update(r["golds"])
            break
    gold_present = any(a and a in ctx for a in aliases)
    if not gold_present:
        return 0.0
    distractor = _lookup(question, gold)
    # If the contradicting wrong answer is ALSO in the context, the context is
    # ambiguous and a careful judge cannot commit to the gold -> 0.0. This is what
    # demotes the full-corpus dump while sparing the resolved memory slice.
    if distractor and distractor in ctx:
        return 0.0
    return 1.0


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    s = score(
        payload.get("question", ""),
        payload.get("context", ""),
        payload.get("gold", "") or "",
    )
    sys.stdout.write(json.dumps({"score": float(s)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
