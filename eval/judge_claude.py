#!/usr/bin/env python3
"""Strict LLM-as-judge for the Mnemosyne §33 G2 answer-quality SLO.

Contract (consumed by ``eval/harness/answer_quality.py::make_llm_judge``):

    stdin  : {"question": str, "context": str, "gold": str}
    stdout : {"score": <float in [0,1]>}

This wraps the local ``claude`` CLI (``claude -p``) as the judge model. It asks
the model to decide whether ``context`` actually supports answering ``question``
with the ``gold`` answer — the "strict judge + adversarial-answer screening"
the blueprint calls for. A strict judge is the point: under the deterministic
substring judge, full-context is always a 1.0 ceiling so the memory layer can
only tie or lose; a real judge can recognize that a focused retrieved slice
answers the question *as well or better* than a noisy full-context dump.

Scoring rubric handed to the judge:
  * gold is non-empty  -> score 1.0 iff the context unambiguously supports the
    gold answer to the question, else 0.0. Partial credit allowed (0..1).
  * gold is empty (unanswerable / abstain case) -> score 1.0 iff the context
    does NOT assert a confident answer (i.e. correctly abstains), else 0.0.

Robustness: on any failure (CLI missing, timeout, unparseable output) we exit
non-zero with a diagnostic on stderr; the harness treats a judge crash as fatal
for that run, which is the honest behavior (no silent fallback to a weaker
judge that would corrupt the reported G2 number).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

CLAUDE_BIN = os.environ.get("MNEMO_JUDGE_CLAUDE_BIN", "claude")
TIMEOUT_S = float(os.environ.get("MNEMO_JUDGE_TIMEOUT_S", "90"))

PROMPT_TEMPLATE = """You are a STRICT answer-quality judge for a memory-retrieval system.

You are given a QUESTION, a CONTEXT (the only text a model is allowed to read to
answer), and a GOLD answer. Decide how well the CONTEXT supports answering the
QUESTION correctly.

Rules:
- If GOLD is non-empty: output 1.0 only if the CONTEXT unambiguously contains or
  directly supports the GOLD answer to the QUESTION. Output 0.0 if the CONTEXT
  does not support it. You may output a value between 0 and 1 for partial support.
- If GOLD is empty: the question is unanswerable / should be abstained on. Output
  1.0 only if the CONTEXT does NOT assert a confident answer (correctly abstains);
  output 0.0 if the CONTEXT confidently asserts an answer anyway.
- Judge ONLY what the CONTEXT supports. Do not use outside knowledge.

QUESTION:
{question}

GOLD:
{gold}

CONTEXT:
{context}

Respond with ONLY a JSON object on a single line, no prose, no code fences:
{{"score": <number between 0 and 1>}}"""


def _extract_score(text: str) -> float:
    text = text.strip()
    # Strip code fences if the model added them.
    text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text.strip())
    # First try a clean JSON parse.
    try:
        obj = json.loads(text)
        return float(obj["score"])
    except Exception:
        pass
    # Find the first {...} span containing "score".
    for m in re.finditer(r"\{[^{}]*\}", text):
        try:
            obj = json.loads(m.group(0))
            if "score" in obj:
                return float(obj["score"])
        except Exception:
            continue
    # Last resort: a bare number.
    m = re.search(r"-?\d+(?:\.\d+)?", text)
    if m:
        return float(m.group(0))
    raise ValueError(f"could not parse score from judge output: {text!r}")


def main() -> int:
    raw = sys.stdin.read()
    try:
        req = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"judge: bad stdin JSON: {exc}", file=sys.stderr)
        return 2
    question = str(req.get("question", ""))
    context = str(req.get("context", ""))
    gold = str(req.get("gold", "") or "")

    prompt = PROMPT_TEMPLATE.format(question=question, gold=gold, context=context)
    try:
        proc = subprocess.run(
            [CLAUDE_BIN, "-p", prompt, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
        )
    except FileNotFoundError:
        print(f"judge: claude binary not found: {CLAUDE_BIN}", file=sys.stderr)
        return 3
    except subprocess.TimeoutExpired:
        print("judge: claude timed out", file=sys.stderr)
        return 4
    if proc.returncode != 0:
        print(f"judge: claude exited {proc.returncode}: {proc.stderr[-400:]}", file=sys.stderr)
        return 5
    try:
        score = _extract_score(proc.stdout)
    except ValueError as exc:
        print(f"judge: {exc}", file=sys.stderr)
        return 6
    score = max(0.0, min(1.0, score))
    sys.stdout.write(json.dumps({"score": score}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
