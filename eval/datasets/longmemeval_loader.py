"""Dataset loading copied from Mnemetric's eval/public/adapters/longmemeval.py (17 Oct 2026), for Mnemosyne's own recall research."""

from __future__ import annotations
import re
from collections import Counter
from typing import Any


_CLEANED = "longmemeval_s_cleaned.json"


_ORACLE = "longmemeval_oracle.json"


_REDACTION = "[REDACTED_SECRET]"


_SECRET = re.compile(
    r"(?:-----BEGIN (?P<label>[A-Z ]*PRIVATE KEY)-----[\s\S]{0,65536}?"
    r"-----END (?P=label)-----|gh[pousr]_[A-Za-z0-9]{20,}|"
    r"sk_(?:live|test)_[A-Za-z0-9]{16,}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|-----END [A-Z ]*PRIVATE KEY-----)"
)


def normalize(value: dict[str, Any]) -> dict[str, Any]:
    """Normalize pinned raw assets before any CLI evaluation side effect."""
    assets = value.get("assets")
    if not isinstance(assets, dict) or set(assets) != {_CLEANED, _ORACLE}:
        raise ValueError("LongMemEval requires the exact cleaned and oracle assets")
    cleaned, oracle = assets[_CLEANED], assets[_ORACLE]
    if not isinstance(cleaned, list) or not cleaned:
        raise ValueError("LongMemEval cleaned asset must be a non-empty list")
    oracle_by_id = _index_questions(oracle, "oracle")
    corpus: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
    redaction_count = 0
    seen: set[str] = set()
    for row in cleaned:
        if not isinstance(row, dict):
            raise ValueError("LongMemEval cleaned rows must be objects")
        question_id = _string(row.get("question_id"), "question_id")
        if question_id in seen:
            raise ValueError(f"duplicate LongMemEval question_id: {question_id}")
        seen.add(question_id)
        query = _string(row.get("question"), "question")
        session_ids = _strings(
            row.get("haystack_session_ids"),
            "haystack_session_ids",
            allow_duplicates=True,
        )
        sessions = row.get("haystack_sessions")
        if not isinstance(sessions, list) or len(sessions) != len(session_ids):
            raise ValueError(
                f"LongMemEval question {question_id} has misaligned sessions"
            )
        gold = _strings(row.get("answer_session_ids"), "answer_session_ids")
        if not set(gold) <= set(session_ids):
            raise ValueError(
                f"LongMemEval question {question_id} has unknown answer sessions"
            )
        counts = Counter(session_ids)
        if any(counts[session_id] != 1 for session_id in gold):
            raise ValueError(
                f"LongMemEval question {question_id} has ambiguous answer sessions"
            )
        oracle_row = oracle_by_id.get(question_id)
        if oracle_row is None:
            raise ValueError(f"LongMemEval oracle is missing question {question_id}")
        turns = _oracle_turns(oracle_row, session_ids)
        occurrences: Counter[str] = Counter()
        for session_id, session in zip(session_ids, sessions, strict=True):
            occurrence = occurrences[session_id]
            occurrences[session_id] += 1
            record_id = (
                session_id
                if counts[session_id] == 1
                else f"{session_id}#occurrence-{occurrence}"
            )
            content, matched = _render_session(session)
            redaction_count += matched
            corpus.append(
                {
                    "content": content,
                    "question_id": question_id,
                    "session_id": record_id,
                    "source_session_id": session_id,
                }
            )
        questions.append(
            {
                "answer_session_ids": gold,
                "oracle_has_answer_turns": turns,
                "query": query,
                "question_id": question_id,
            }
        )
    if set(oracle_by_id) != seen:
        raise ValueError("LongMemEval oracle question set does not match cleaned asset")
    return {
        "corpus": corpus,
        "k": 5,
        "questions": questions,
        "redactions": {
            "replacement": _REDACTION,
            "secret_like_matches": redaction_count,
        },
    }


def _index_questions(value: Any, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"LongMemEval {label} asset must be a list")
    indexed: dict[str, dict[str, Any]] = {}
    for row in value:
        if not isinstance(row, dict):
            raise ValueError(f"LongMemEval {label} rows must be objects")
        question_id = _string(row.get("question_id"), "question_id")
        if question_id in indexed:
            raise ValueError(
                f"duplicate LongMemEval {label} question_id: {question_id}"
            )
        indexed[question_id] = row
    return indexed


def _oracle_turns(row: dict[str, Any], cleaned_ids: list[str]) -> dict[str, list[int]]:
    sessions = row.get("haystack_sessions")
    if not isinstance(sessions, list):
        raise ValueError("LongMemEval oracle sessions must be a list")
    raw_ids = row.get("haystack_session_ids", cleaned_ids)
    session_ids = _strings(
        raw_ids,
        "oracle haystack_session_ids",
        allow_duplicates=True,
    )
    if len(sessions) != len(session_ids) or not set(session_ids) <= set(cleaned_ids):
        raise ValueError(
            "LongMemEval oracle sessions do not align with cleaned sessions"
        )
    answer_turns: dict[str, list[int]] = {session_id: [] for session_id in cleaned_ids}
    for session_id, session in zip(session_ids, sessions, strict=True):
        if not isinstance(session, list) or not session:
            raise ValueError("LongMemEval oracle session must contain turns")
        answer_turns[session_id] = [
            index
            for index, turn in enumerate(session)
            if isinstance(turn, dict) and turn.get("has_answer") is True
        ]
    return answer_turns


def _render_session(session: Any) -> tuple[str, int]:
    if not isinstance(session, list) or not session:
        raise ValueError("LongMemEval session must contain turns")
    rendered: list[str] = []
    for turn in session:
        if not isinstance(turn, dict):
            raise ValueError("LongMemEval turns must be objects")
        role = _string(turn.get("role"), "turn role")
        content = turn.get("content")
        if not isinstance(content, str):
            raise ValueError("LongMemEval turn content must be a string")
        rendered.append(f"{role}: {content}")
    return _SECRET.subn(_REDACTION, "\n".join(rendered))


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"LongMemEval {label} must be a non-empty string")
    return value


def _strings(value: Any, label: str, *, allow_duplicates: bool = False) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise ValueError(f"LongMemEval {label} must be a non-empty string list")
    if not allow_duplicates and len(value) != len(set(value)):
        raise ValueError(f"LongMemEval {label} contains duplicates")
    return value
