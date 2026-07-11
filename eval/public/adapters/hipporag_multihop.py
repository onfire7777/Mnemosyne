"""HippoRAG 2 sampled multi-hop retrieval through the public CLI seam."""

from __future__ import annotations

import json
import math
import tempfile
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

from eval.harness.cli_driver import MnemoCLI
from eval.public.scoring import score_profile


class HippoRAGSchemaError(ValueError):
    """Pinned HippoRAG assets cannot be normalized without ambiguity."""


_QUERY_SHARD_SIZE = 50


def run(
    value: dict[str, Any], cli: MnemoCLI
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    benchmark = normalize(value) if "assets" in value else value
    _validate_canonical(benchmark)
    if isinstance(cli, MnemoCLI):
        read_only_flag = "--evaluation-read-only"
        capture_cli = replace(
            cli,
            timeout_s=max(cli.timeout_s, 600.0),
            global_flags=[flag for flag in cli.global_flags if flag != read_only_flag],
        )
        eval_cli = replace(
            capture_cli,
            timeout_s=max(capture_cli.timeout_s, 1_800.0),
            global_flags=[*capture_cli.global_flags, read_only_flag],
        )
    else:
        capture_cli = eval_cli = cli
    corpus = benchmark["corpus"]
    tenant = f"public-hipporag-{benchmark['dataset']}"
    with tempfile.TemporaryDirectory(prefix="mneme-hipporag-") as temp:
        batch = Path(temp) / "corpus.jsonl"
        batch.write_text(
            "".join(
                json.dumps(
                    {
                        "content": f"{document['title']}\n{document['content']}",
                        "source_identity": document["doc_id"],
                        "source_type": f"hipporag:{benchmark['dataset']}",
                        "tenant": tenant,
                        "user": "benchmark-corpus",
                    },
                    sort_keys=True,
                )
                + "\n"
                for document in corpus
            ),
            encoding="utf-8",
        )
        captured = capture_cli.capture_batch(batch)
    results = captured.get("results", [])
    if len(results) != len(corpus):
        raise HippoRAGSchemaError("capture batch count does not match corpus")
    cid_to_doc: dict[str, str] = {}
    for result, document in zip(results, corpus, strict=True):
        cid = result.get("cid") if isinstance(result, Mapping) else None
        if not isinstance(cid, str) or not cid:
            raise HippoRAGSchemaError("capture batch result is missing a CID")
        if cid in cid_to_doc:
            raise HippoRAGSchemaError("capture batch returned a duplicate CID")
        cid_to_doc[cid] = document["doc_id"]
    stored = [document["doc_id"] for document in corpus]

    def make_trace(
        question: dict[str, Any],
        search: Mapping[str, Any],
        explanation: Mapping[str, Any],
    ) -> dict[str, Any]:
        ranked = [
            cid_to_doc[hit["id"]]
            for hit in search.get("hits", [])
            if hit.get("id") in cid_to_doc
        ]
        return {
            "answer": None,
            "gold_references": question["gold_references"],
            "graph_evidence": _graph_evidence(search, explanation),
            "question_id": question["question_id"],
            "ranked_retrieved_hits": ranked,
            "scoring_family": "deterministic-retrieval",
            "stored_records": stored,
        }

    if isinstance(eval_cli, MnemoCLI):
        questions = benchmark["questions"]
        chunk_size = _QUERY_SHARD_SIZE
        with tempfile.TemporaryDirectory(prefix="mneme-hipporag-queries-") as temp:
            batches: list[Path] = []
            expected_counts: list[int] = []
            for index, start in enumerate(range(0, len(questions), chunk_size)):
                chunk = questions[start : start + chunk_size]
                path = Path(temp) / f"{index}.jsonl"
                path.write_text(
                    "".join(
                        json.dumps(
                            {
                                "question_id": question["question_id"],
                                "query": question["question"],
                                "tenant": tenant,
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        + "\n"
                        for question in chunk
                    ),
                    encoding="utf-8",
                )
                batches.append(path)
                expected_counts.append(len(chunk))
            with ThreadPoolExecutor(max_workers=4) as executor:
                payloads = list(executor.map(eval_cli.eval_query_batch, batches))
        evaluated: list[dict[str, Any]] = []
        for payload, expected_count in zip(payloads, expected_counts, strict=True):
            if not isinstance(payload, Mapping):
                raise HippoRAGSchemaError("evaluation query batch payload is invalid")
            rows = payload.get("results")
            if (
                payload.get("ok") is not True
                or payload.get("count") != expected_count
                or not isinstance(rows, list)
                or len(rows) != expected_count
                or any(
                    not isinstance(row, dict)
                    or not isinstance(row.get("question_id"), str)
                    or not row["question_id"]
                    or not isinstance(row.get("search"), Mapping)
                    or not isinstance(row.get("explanation"), Mapping)
                    for row in rows
                )
            ):
                raise HippoRAGSchemaError("evaluation query batch payload is invalid")
            evaluated.extend(rows)
        if [row.get("question_id") for row in evaluated] != [
            question["question_id"] for question in questions
        ]:
            raise HippoRAGSchemaError("evaluation query batch order or count drift")
        traces = [
            make_trace(question, row.get("search", {}), row.get("explanation", {}))
            for question, row in zip(questions, evaluated, strict=True)
        ]
    else:
        traces = [
            make_trace(
                question,
                eval_cli.search(tenant, question["question"]),
                eval_cli.explain(tenant, question["question"]),
            )
            for question in benchmark["questions"]
        ]
    labels = [
        {
            "question_id": question["question_id"],
            "gold_references": question["gold_references"],
        }
        for question in benchmark["questions"]
    ]
    return benchmark, traces, score_profile("hipporag-retrieval-v1", labels, traces)


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


def score_predictions(
    questions: list[dict[str, Any]], predictions: Mapping[str, str]
) -> dict[str, Any]:
    labels, traces = [], []
    for question in questions:
        question_id = question["question_id"]
        if question_id not in predictions:
            raise HippoRAGSchemaError(f"missing prediction: {question_id}")
        labels.append({"answers": question["answers"], "question_id": question_id})
        traces.append(
            {
                "answer": predictions[question_id],
                "question_id": question_id,
                "scoring_family": "qa",
            }
        )
    return score_profile("qa-em-f1-v1", labels, traces)


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


def _graph_evidence(
    search: Mapping[str, Any], explanation: Mapping[str, Any]
) -> dict[str, Any]:
    evidence: dict[str, Any] = {"observed": False}
    search_metadata = search.get("metadata")
    if isinstance(search_metadata, Mapping) and "channel_scores" in search_metadata:
        scores = search_metadata["channel_scores"]
        evidence["search_channel_scores"] = scores
        if isinstance(scores, Mapping) and any(
            _is_graph_channel(channel) and _positive_finite(score)
            for channel, score in scores.items()
        ):
            evidence["observed"] = True
    channels = explanation.get("channels")
    if channels is not None:
        evidence["explain_channels"] = channels
        if isinstance(channels, Mapping):
            observed = any(
                _is_graph_channel(channel) and _positive_finite(value)
                for channel, value in channels.items()
            )
        else:
            observed = isinstance(channels, (list, tuple, set)) and any(
                _is_graph_channel(channel) for channel in channels
            )
        if observed:
            evidence["observed"] = True
    if "graph_backend" in explanation:
        evidence["graph_backend"] = explanation["graph_backend"]
    adapters = explanation.get("adapters")
    if "graph_backend" not in evidence and isinstance(adapters, Mapping):
        graph_backend = adapters.get("graph_backend")
        if isinstance(graph_backend, str) and graph_backend:
            evidence["graph_backend"] = graph_backend
    return evidence


def _is_graph_channel(channel: Any) -> bool:
    name = str(channel).lower()
    return "graph" in name or "ppr" in name


def _positive_finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


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
