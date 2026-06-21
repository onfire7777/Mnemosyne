"""Answer-quality scoring for the G2 SLO (blueprint §16 / §33).

G2 target: **≥ +15% answer quality vs full-context at ≤10% tokens.** This proves
the memory layer lets a host model answer *better* using a tiny retrieved slice
than by stuffing the whole corpus into context.

Two configurations are compared, both deriving an answer span from text the model
would actually see:

  * **full_context**: concatenate the ENTIRE corpus (every captured doc). Token
    budget = the full corpus token count.
  * **memory**: use only the top-k hits from a single ``mneme search`` call. Token
    budget = tokens in those hits (must be ≤ 10% of the full-context tokens for the
    G2 condition to hold).

Answer scoring — TWO interchangeable judges behind one interface:

  * ``substring_judge`` (default, deterministic, RUNS NOW): an answer is correct if
    the gold answer string appears in the supplied context (case-insensitive,
    whitespace-normalised). This is contract-correct: it measures whether the
    *retrieved slice actually contained the answer*, which is precisely what the
    memory layer is responsible for. It needs no model and gives real numbers
    immediately.

  * ``llm_judge`` (real path, gated): delegates to an external command (an
    LLM-as-judge) that reads (question, context, gold) and returns a 0/1 (or
    graded) verdict. Wire it via ``MNEMO_EVAL_JUDGE_CMD``. This is where the
    blueprint's "strict judge + adversarial-answer screening" sharpens — see
    ``make_judge``. Until then the substring judge is the honest, runnable
    stand-in and the report labels which judge produced the numbers.

Token counting: a real tokenizer (tiktoken) is used if importable; otherwise a
deterministic whitespace+punctuation word count, clearly labelled in the report.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from typing import Callable, Sequence

# (question, context, gold) -> score in [0,1]
Judge = Callable[[str, str, str], float]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def count_tokens(text: str) -> tuple[int, str]:
    """Return (token_count, method). Uses tiktoken if available, else word count."""
    try:  # pragma: no cover - depends on optional dep
        import tiktoken  # type: ignore

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text)), "tiktoken:cl100k_base"
    except Exception:
        return len(re.findall(r"\w+|[^\w\s]", text)), "wordcount"


def substring_judge(question: str, context: str, gold: str) -> float:
    """1.0 if the gold answer appears verbatim (normalised) in the context."""
    if not gold:
        # Unanswerable: "correct" means the context does NOT assert a confident
        # answer. We score 1.0 only when the context is empty/abstaining.
        return 1.0 if not context.strip() else 0.0
    return 1.0 if _normalize(gold) in _normalize(context) else 0.0


def make_llm_judge(command: str) -> Judge:
    """Build a judge that shells out to an external LLM-as-judge command.

    The command receives a JSON object on stdin:
        {"question": ..., "context": ..., "gold": ...}
    and must print a JSON object on stdout: {"score": <float 0..1>}.
    This is the real, strict-judge path (blueprint §33 methodology guardrails).
    """

    def _judge(question: str, context: str, gold: str) -> float:
        payload = json.dumps({"question": question, "context": context, "gold": gold})
        proc = subprocess.run(
            shlex.split(command),
            input=payload,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"llm judge failed: {proc.stderr[-500:]}")
        data = json.loads(proc.stdout.strip())
        return float(data["score"])

    return _judge


def make_judge() -> tuple[Judge, str]:
    """Select the judge: real LLM judge if MNEMO_EVAL_JUDGE_CMD is set, else substring."""
    cmd = os.environ.get("MNEMO_EVAL_JUDGE_CMD")
    if cmd:
        return make_llm_judge(cmd), f"llm_judge:{cmd.split()[0]}"
    return substring_judge, "substring_judge"


@dataclass(slots=True)
class AnswerCase:
    qid: str
    question: str
    gold: str | None
    full_context: str
    memory_context: str
    answerable: bool


@dataclass(slots=True)
class AnswerScore:
    qid: str
    full_score: float
    memory_score: float
    full_tokens: int
    memory_tokens: int
    token_fraction: float
    within_budget: bool  # memory_tokens <= 10% of full_tokens


def score_answer_cases(
    cases: Sequence[AnswerCase],
    judge: Judge,
    *,
    token_budget_fraction: float = 0.10,
) -> list[AnswerScore]:
    scores: list[AnswerScore] = []
    for case in cases:
        gold = case.gold or ""
        full_tokens, _ = count_tokens(case.full_context)
        mem_tokens, _ = count_tokens(case.memory_context)
        frac = (mem_tokens / full_tokens) if full_tokens else 0.0
        scores.append(
            AnswerScore(
                qid=case.qid,
                full_score=judge(case.question, case.full_context, gold),
                memory_score=judge(case.question, case.memory_context, gold),
                full_tokens=full_tokens,
                memory_tokens=mem_tokens,
                token_fraction=frac,
                within_budget=frac <= token_budget_fraction,
            )
        )
    return scores
