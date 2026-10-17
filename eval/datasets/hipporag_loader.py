"""Dataset loading copied from Mnemetric's eval/public/adapters/hipporag_multihop.py (17 Oct 2026), for Mnemosyne's own recall research."""

from __future__ import annotations
import hashlib
import json
import math
import tempfile
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any


class HippoRAGSchemaError(ValueError):
    """Pinned HippoRAG assets cannot be normalized without ambiguity."""


def normalize(value: Mapping[str, Any]) -> dict[str, Any]:
    assets = value.get("assets")
    if not isinstance(assets, Mapping) or len(assets) != 2:
        raise HippoRAGSchemaError(
            "HippoRAG adapter requires one query and one corpus asset"
        )
    corpus_name = next((name for name in assets if name.endswith("_corpus.json")), None)
    if corpus_name is None:
        raise HippoRAGSchemaError("HippoRAG corpus asset is missing")
    query_name = next(name for name in assets if name != corpus_name)
    dataset = _dataset_name(query_name)
    raw_corpus, raw_questions = assets[corpus_name], assets[query_name]
    if not isinstance(raw_corpus, list) or not isinstance(raw_questions, list):
        raise HippoRAGSchemaError("HippoRAG assets must be JSON arrays")
    corpus: list[dict[str, str]] = []
    exact: dict[tuple[str, str], str] = {}
    titles: dict[str, list[str]] = {}
    for index, item in enumerate(raw_corpus):
        title, text = _corpus_fields(item)
        key = (title, text)
        if key in exact:
            raise HippoRAGSchemaError("duplicate corpus title/text is ambiguous")
        doc_id = f"{dataset}:p{index:05d}"
        exact[key] = doc_id
        titles.setdefault(title, []).append(doc_id)
        corpus.append({"content": text, "doc_id": doc_id, "title": title})
    questions = [
        _normalize_question(dataset, item, exact, titles) for item in raw_questions
    ]
    benchmark = {"corpus": corpus, "dataset": dataset, "questions": questions}
    _validate_canonical(benchmark)
    return benchmark


def _dataset_name(filename: str) -> str:
    names = {
        "musique.json": "musique",
        "2wikimultihopqa.json": "2wiki",
        "hotpotqa.json": "hotpot",
    }
    try:
        return names[filename]
    except KeyError as exc:
        raise HippoRAGSchemaError(
            f"unsupported HippoRAG query asset: {filename}"
        ) from exc


def _corpus_fields(item: Any) -> tuple[str, str]:
    if not isinstance(item, Mapping):
        raise HippoRAGSchemaError("corpus row must be an object")
    title, text = item.get("title"), item.get("text")
    if not isinstance(title, str) or not title or not isinstance(text, str) or not text:
        raise HippoRAGSchemaError("corpus row requires title and text")
    return title, text


def _normalize_question(
    dataset: str,
    item: Any,
    exact: Mapping[tuple[str, str], str],
    titles: Mapping[str, list[str]],
) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        raise HippoRAGSchemaError("question row must be an object")
    question_id = item.get("id") if dataset == "musique" else item.get("_id")
    question, answer = item.get("question"), item.get("answer")
    if not all(
        isinstance(field, str) and field for field in (question_id, question, answer)
    ):
        raise HippoRAGSchemaError("question requires stable ID, question, and answer")
    gold: list[str] = []
    if dataset == "musique":
        for paragraph in item.get("paragraphs", []):
            if paragraph.get("is_supporting") is True:
                key = (
                    paragraph.get("title"),
                    paragraph.get("paragraph_text", paragraph.get("text")),
                )
                if key not in exact:
                    raise HippoRAGSchemaError(
                        "MuSiQue support paragraph has no exact corpus match"
                    )
                gold.append(exact[key])
    else:
        support_titles = list(
            dict.fromkeys(
                fact[0]
                for fact in item.get("supporting_facts", [])
                if isinstance(fact, list) and len(fact) >= 2
            )
        )
        for title in support_titles:
            matches = titles.get(title, [])
            if len(matches) != 1:
                raise HippoRAGSchemaError(
                    "supporting title does not map uniquely to corpus"
                )
            gold.append(matches[0])
    if not gold:
        raise HippoRAGSchemaError("question has no mapped gold passages")
    aliases = item.get("answer_aliases", [])
    if not isinstance(aliases, list) or any(
        not isinstance(alias, str) or not alias for alias in aliases
    ):
        raise HippoRAGSchemaError("answer aliases must be non-empty strings")
    answers = list(dict.fromkeys([answer, *aliases]))
    return {
        "answers": answers,
        "gold_references": gold,
        "question": question,
        "question_id": question_id,
    }


def _validate_canonical(benchmark: Mapping[str, Any]) -> None:
    if benchmark.get("dataset") not in {"musique", "2wiki", "hotpot"}:
        raise HippoRAGSchemaError("canonical benchmark has invalid dataset")
    if not isinstance(benchmark.get("corpus"), list) or not benchmark["corpus"]:
        raise HippoRAGSchemaError("canonical benchmark corpus is empty")
    if not isinstance(benchmark.get("questions"), list) or not benchmark["questions"]:
        raise HippoRAGSchemaError("canonical benchmark questions are empty")
    doc_ids = [
        row.get("doc_id") for row in benchmark["corpus"] if isinstance(row, Mapping)
    ]
    if len(doc_ids) != len(benchmark["corpus"]) or any(
        not isinstance(doc_id, str) or not doc_id for doc_id in doc_ids
    ):
        raise HippoRAGSchemaError("canonical corpus has invalid document IDs")
    if len(doc_ids) != len(set(doc_ids)):
        raise HippoRAGSchemaError("canonical corpus has duplicate document IDs")
    question_ids: list[str] = []
    for question in benchmark["questions"]:
        if not isinstance(question, Mapping):
            raise HippoRAGSchemaError("canonical question must be an object")
        question_id = question.get("question_id")
        if not isinstance(question_id, str) or not question_id:
            raise HippoRAGSchemaError("canonical question has invalid ID")
        question_ids.append(question_id)
        gold = question.get("gold_references")
        answers = question.get("answers")
        if (
            not isinstance(gold, list)
            or not gold
            or any(item not in set(doc_ids) for item in gold)
        ):
            raise HippoRAGSchemaError("canonical question has invalid gold references")
        if (
            not isinstance(answers, list)
            or not answers
            or any(not isinstance(answer, str) or not answer for answer in answers)
        ):
            raise HippoRAGSchemaError("canonical question has invalid answers")
    if len(question_ids) != len(set(question_ids)):
        raise HippoRAGSchemaError("canonical benchmark has duplicate question IDs")
