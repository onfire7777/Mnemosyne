"""Reader-QA LongMemEval adapter with scorer-only answer-label custody."""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from eval.harness.cli_driver import MnemoCLI
from eval.public.adapters import longmemeval
from eval.public.scoring import score_profile
from eval.public.custody import capture_cid, first_hop_rows


def normalize(value: dict[str, Any]) -> dict[str, Any]:
    retrieval = longmemeval.normalize(value)
    cleaned = value["assets"]["longmemeval_s_cleaned.json"]
    answers = {
        row["question_id"]: _answers(row)
        for row in cleaned
        if isinstance(row, dict)
    }
    question_ids = {row["question_id"] for row in retrieval["questions"]}
    if set(answers) != question_ids:
        raise ValueError("LongMemEval QA answer question set does not match retrieval custody")
    corpus = []
    for document in retrieval["corpus"]:
        tenant = f"longmemeval-qa:{document['question_id']}"
        capture = {
            "actor": "user",
            "content": document["content"],
            "content_pointer": None,
            "modality": "text",
            "sensitivity": 0,
            "source_identity": document["session_id"],
            "source_type": f"longmemeval:{document['session_id']}",
            "tenant_id": tenant,
            "user_id": "longmemeval",
        }
        corpus.append(
            {
                **document,
                "capture": capture,
                "doc_id": capture_cid(capture),
            }
        )
    return {
        **retrieval,
        "corpus": corpus,
        "family": "qa",
        "questions": [
            {**row, "answers": answers[row["question_id"]]}
            for row in retrieval["questions"]
        ],
    }


def run(
    value: dict[str, Any], cli: MnemoCLI
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    benchmark = normalize(value) if "assets" in value else _validate(value)
    by_question: dict[str, list[dict[str, Any]]] = {}
    for document in benchmark["corpus"]:
        by_question.setdefault(document["question_id"], []).append(document)
    traces: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="mneme-longmemeval-qa-") as temp:
        for index, question in enumerate(benchmark["questions"]):
            tenant = f"longmemeval-qa:{question['question_id']}"
            question_cli = (
                replace(cli, store=str(Path(temp) / f"{index}.store.json"))
                if isinstance(cli, MnemoCLI)
                else cli
            )
            runtime_rows = [
                {
                    "tenant": document["capture"]["tenant_id"],
                    "user": document["capture"]["user_id"],
                    "source_type": document["capture"]["source_type"],
                    "source_identity": document["capture"]["source_identity"],
                    "content": document["capture"]["content"],
                }
                for document in by_question[question["question_id"]]
            ]
            capture_path = Path(temp) / f"{index}-capture.jsonl"
            capture_path.write_text(_jsonl(runtime_rows), encoding="utf-8")
            captured = question_cli.capture_batch(capture_path).get("results")
            if not isinstance(captured, list) or len(captured) != len(runtime_rows):
                raise ValueError("LongMemEval QA capture count mismatch")
            captures: dict[str, dict[str, Any]] = {}
            for runtime, result, document in zip(
                runtime_rows,
                captured,
                by_question[question["question_id"]],
                strict=True,
            ):
                cid = result.get("cid") if isinstance(result, dict) else None
                if not isinstance(cid, str) or not cid or cid in captures:
                    raise ValueError("LongMemEval QA capture CID custody is invalid")
                if cid != document["doc_id"]:
                    raise ValueError("LongMemEval QA capture CID does not match corpus anchor")
                captures[cid] = document["capture"]
            answer_input = {
                "question_id": question["question_id"],
                "question": question["query"],
                "context": {"tenant_id": tenant, "user_id": "longmemeval", "role": "reader"},
            }
            answer_path = Path(temp) / f"{index}-answer.jsonl"
            answer_path.write_text(_jsonl([answer_input]), encoding="utf-8")
            answer_cli = (
                replace(question_cli, global_flags=[*question_cli.global_flags, "--evaluation-read-only"])
                if isinstance(question_cli, MnemoCLI)
                else question_cli
            )
            payload = answer_cli.eval_answer_batch(answer_path)
            results = payload.get("results")
            if not isinstance(results, list) or len(results) != 1 or results[0].get("question_id") != question["question_id"]:
                raise ValueError("LongMemEval QA answer result mismatch")
            result = results[0]
            cited = list(dict.fromkeys(
                cid
                for hop in result.get("hops", [])
                for cid in hop.get("retrieved_cids", [])
                if cid in captures
            ))
            traces.append(
                {
                    "abstained": result.get("abstained"),
                    "answer": result.get("answer"),
                    "authorized_evidence_fingerprint": _fingerprint(cited),
                    "authorized_retrieval_hops": first_hop_rows(
                        result.get("hops", []), captures
                    ),
                    "claims": result.get("claims"),
                    "question_id": question["question_id"],
                    "reader": result.get("reader"),
                    "scoring_family": "qa",
                }
            )
    labels = [
        {"answers": question["answers"], "question_id": question["question_id"]}
        for question in benchmark["questions"]
    ]
    return benchmark, traces, score_profile("qa-em-f1-v1", labels, traces)


def _validate(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("family") != "qa" or not value.get("corpus") or not value.get("questions"):
        raise ValueError("normalized LongMemEval QA benchmark is invalid")
    for question in value["questions"]:
        _answers(question)
    return value


def _answers(row: dict[str, Any]) -> list[str]:
    answer = row.get("answer")
    aliases = row.get("answers", row.get("answer_aliases", []))
    if not isinstance(aliases, list) or any(not isinstance(item, str) or not item for item in aliases):
        raise ValueError("LongMemEval QA answer aliases are invalid")
    values = ([answer] if isinstance(answer, str) and answer else []) + aliases
    if not values:
        raise ValueError("LongMemEval QA answer is missing")
    return list(dict.fromkeys(values))


def _fingerprint(cids: list[str]) -> str:
    return hashlib.sha256((json.dumps(sorted(cids), separators=(",", ":")) + "\n").encode()).hexdigest()


def _jsonl(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)
