"""Deterministic retrieval adapter for the cleaned LongMemEval release."""

from __future__ import annotations

import json
import tempfile
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

from eval.harness.cli_driver import MnemoCLI
from eval.public.scoring import score_profile

_CLEANED = "longmemeval_s_cleaned.json"
_ORACLE = "longmemeval_oracle.json"
_PROFILE = "longmemeval-retrieval-v1"


def run(
    benchmark: dict[str, Any], cli: MnemoCLI
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Normalize LongMemEval, run isolated CLI retrieval, and score session recall."""
    normalized = (
        _normalize_assets(benchmark["assets"])
        if "assets" in benchmark
        else _validate_normalized(benchmark)
    )
    by_question: dict[str, list[dict[str, Any]]] = {}
    for document in normalized["corpus"]:
        by_question.setdefault(document["question_id"], []).append(document)

    traces: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="mneme-longmemeval-") as temp:
        for question_index, question in enumerate(normalized["questions"]):
            question_id = question["question_id"]
            tenant = _tenant(question_id)
            question_cli = (
                replace(cli, store=str(Path(temp) / f"{question_index}.store.json"))
                if isinstance(cli, MnemoCLI)
                else cli
            )
            rows = [
                {
                    "tenant": tenant,
                    "user": "longmemeval",
                    "source_type": f"longmemeval:{document['session_id']}",
                    "source_identity": document["session_id"],
                    "content": document["content"],
                }
                for document in by_question[question_id]
            ]
            batch = Path(temp) / f"{question_index}.jsonl"
            batch.write_text(
                "".join(
                    json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                    for row in rows
                ),
                encoding="utf-8",
            )
            captured = question_cli.capture_batch(batch)
            results = captured.get("results")
            if not isinstance(results, list) or len(results) != len(rows):
                raise ValueError(
                    "LongMemEval batch capture returned an invalid result count"
                )
            cid_to_session: dict[str, str] = {}
            for row, result in zip(rows, results, strict=True):
                cid = result.get("cid") if isinstance(result, dict) else None
                if not isinstance(cid, str) or not cid:
                    raise ValueError("LongMemEval batch capture omitted a CID")
                if cid in cid_to_session:
                    raise ValueError(
                        "LongMemEval batch capture returned a duplicate CID"
                    )
                cid_to_session[cid] = row["source_identity"]
            result = question_cli.search(tenant, question["query"])
            ranked: list[str] = []
            for hit in result.get("hits", []):
                session_id = cid_to_session.get(hit.get("id"))
                if session_id is not None and session_id not in ranked:
                    ranked.append(session_id)
            if not ranked:
                raise ValueError(
                    f"LongMemEval question {question_id} returned no mapped sessions"
                )
            gold = question["answer_session_ids"]
            labels.append({"question_id": question_id, "gold_references": gold})
            traces.append(
                {
                    "answer": ranked[0],
                    "answer_session_ids": gold,
                    "gold_references": gold,
                    "oracle_has_answer_turns": question["oracle_has_answer_turns"],
                    "question_id": question_id,
                    "ranked_retrieved_hits": ranked[:5],
                    "scoring_family": "deterministic-retrieval",
                    "stored_records": [
                        document["session_id"] for document in by_question[question_id]
                    ],
                }
            )
    return normalized, traces, score_profile(_PROFILE, labels, traces)


def _normalize_assets(assets: Any) -> dict[str, Any]:
    if not isinstance(assets, dict) or set(assets) != {_CLEANED, _ORACLE}:
        raise ValueError("LongMemEval requires the exact cleaned and oracle assets")
    cleaned, oracle = assets[_CLEANED], assets[_ORACLE]
    if not isinstance(cleaned, list) or not cleaned:
        raise ValueError("LongMemEval cleaned asset must be a non-empty list")
    oracle_by_id = _index_questions(oracle, "oracle")
    corpus: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
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
            corpus.append(
                {
                    "content": _render_session(session),
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
    return {"corpus": corpus, "k": 5, "questions": questions}


def _validate_normalized(benchmark: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(benchmark, dict) or benchmark.get("k") != 5:
        raise ValueError("invalid normalized LongMemEval benchmark")
    corpus, questions = benchmark.get("corpus"), benchmark.get("questions")
    if (
        not isinstance(corpus, list)
        or not corpus
        or not isinstance(questions, list)
        or not questions
    ):
        raise ValueError("normalized LongMemEval benchmark is empty")
    question_ids = {
        _string(row.get("question_id"), "question_id")
        for row in questions
        if isinstance(row, dict)
    }
    if len(question_ids) != len(questions):
        raise ValueError("normalized LongMemEval questions are invalid or duplicated")
    for row in corpus:
        if not isinstance(row, dict) or row.get("question_id") not in question_ids:
            raise ValueError("normalized LongMemEval corpus has an unknown question")
        _string(row.get("session_id"), "session_id")
        _string(row.get("content"), "content")
    for row in questions:
        _string(row.get("query"), "query")
        _strings(row.get("answer_session_ids"), "answer_session_ids")
        if not isinstance(row.get("oracle_has_answer_turns"), dict):
            raise ValueError("normalized LongMemEval oracle turns are missing")
    return benchmark


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


def _render_session(session: Any) -> str:
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
    return "\n".join(rendered)


def _tenant(question_id: str) -> str:
    return f"longmemeval:{question_id}"


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
