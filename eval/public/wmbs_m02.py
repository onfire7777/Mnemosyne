"""Deterministic M02 retrieval-development fixture and pure scorer.

This stdlib-only module is a development oracle. It runs no system, makes no
quality or publication claim, and does not measure latency, tokens, calls, or
storage.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import string
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

MODULE_ID = "M02"
ADMISSION_STATE = "PROPOSED"
FIXTURE_ID = "wmbs-m02-retrieval-development"
FIXTURE_SCHEMA_ID = "wmbs-m02-retrieval-development/fixture/0.1"
GENERATOR_ID = "wmbs_m02.generate_fixture"
GENERATOR_VERSION = "1.0.0"
DEFAULT_SEED = 20260801
PROFILE = "wmbs-m02-retrieval-v1"
PROFILE_VERSION = 1
FAMILY = "whole-memory-development"
LICENSE = "CC0-1.0"

CORPUS_SIZE = 240
QUESTIONS_PER_FAMILY = 10
QUERY_FAMILIES = frozenset(
    {"exact", "paraphrase", "entity", "relation", "multi-hop", "unanswerable"}
)
FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "wmbs-m02-retrieval-development.json"
)

_TOP_LEVEL_KEYS = frozenset(
    {
        "fixture_id",
        "schema_id",
        "generator_id",
        "generator_version",
        "seed",
        "license",
        "corpus",
        "questions",
        "fixture_sha256",
    }
)
_DOCUMENT_KEYS = frozenset({"stable_item_id", "content"})
_QUESTION_KEYS = frozenset({"question_id", "family", "text", "gold_doc_ids", "answers"})
_TRACE_KEYS = frozenset(
    {"case_id", "question_id", "ranked_hits", "answer", "abstained"}
)


class WmbsM02Error(ValueError):
    """The fixture or scorer input violated the closed M02 contract."""


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _fixture_digest(fixture: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {key: value for key, value in fixture.items() if key != "fixture_sha256"}
    )


def generate_fixture(seed: int = DEFAULT_SEED) -> dict[str, Any]:
    """Build the bounded 240-document, 60-question development fixture."""
    if type(seed) is not int:
        raise WmbsM02Error("seed must be an int")
    rng = random.Random(seed)
    used_tokens: set[str] = set()

    def opaque_token(prefix: str, index: int) -> str:
        ordinal = f"{index:03d}"
        while True:
            token = f"{prefix}-{rng.getrandbits(96):024x}"
            if token not in used_tokens and ordinal not in token:
                used_tokens.add(token)
                return token

    retrieval_keys = [opaque_token("key", index) for index in range(240)]
    payloads = [opaque_token("payload", index) for index in range(240)]
    corpus = [
        {
            "stable_item_id": f"m02-doc-{index:03d}",
            "content": (
                f"Record {index:03d} contains retrieval key {retrieval_key} "
                f"and answer payload {payload}."
            ),
        }
        for index, (retrieval_key, payload) in enumerate(
            zip(retrieval_keys, payloads, strict=True)
        )
    ]

    prompts = {
        "exact": "Which record contains retrieval key {key}?",
        "paraphrase": "Find the document associated with retrieval key {key}.",
        "entity": "Which document describes entity retrieval key {key}?",
        "relation": "Which records establish the relation for retrieval key {key}?",
        "multi-hop": "Which records connect the path for retrieval key {key}?",
    }
    questions: list[dict[str, Any]] = []
    for family_index, family in enumerate(sorted(QUERY_FAMILIES - {"unanswerable"})):
        for index in range(QUESTIONS_PER_FAMILY):
            primary = family_index * 20 + index * 2
            gold = [f"m02-doc-{primary:03d}"]
            if family in {"relation", "multi-hop"}:
                gold.append(f"m02-doc-{primary + 1:03d}")
            retrieval_key = retrieval_keys[primary]
            payload = payloads[primary]
            if len(gold) > 1:
                corpus[primary + 1]["content"] += (
                    f" Linked retrieval key {retrieval_key} confirms answer payload "
                    f"{payload}."
                )
            questions.append(
                {
                    "question_id": f"m02-{family}-{index:02d}",
                    "family": family,
                    "text": prompts[family].format(key=retrieval_key),
                    "gold_doc_ids": gold,
                    "answers": [payload],
                }
            )
    for index in range(QUESTIONS_PER_FAMILY):
        questions.append(
            {
                "question_id": f"m02-unanswerable-{index:02d}",
                "family": "unanswerable",
                "text": f"Which record contains absent retrieval key {seed}-{index}?",
                "gold_doc_ids": [],
                "answers": [],
            }
        )

    fixture: dict[str, Any] = {
        "fixture_id": FIXTURE_ID,
        "schema_id": FIXTURE_SCHEMA_ID,
        "generator_id": GENERATOR_ID,
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "license": LICENSE,
        "corpus": corpus,
        "questions": questions,
    }
    fixture["fixture_sha256"] = _fixture_digest(fixture)
    validate_fixture(fixture)
    return fixture


def _closed_mapping(
    value: object, keys: frozenset[str], label: str
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise WmbsM02Error(f"{label} must have the closed fields {sorted(keys)}")
    return value


def _nonempty_strings(
    value: object, label: str, *, allow_empty: bool = False
) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise WmbsM02Error(
            f"{label} must be a {'possibly empty' if allow_empty else 'non-empty'} list"
        )
    if any(not isinstance(item, str) or not item for item in value):
        raise WmbsM02Error(f"{label} must contain non-empty strings")
    if len(value) != len(set(value)):
        raise WmbsM02Error(f"{label} must contain unique strings")
    return value


def validate_fixture(fixture: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate identity, closed fields, counts, query rules, and self-digest."""
    fixture = _closed_mapping(fixture, _TOP_LEVEL_KEYS, "fixture")
    identities = {
        "fixture_id": FIXTURE_ID,
        "schema_id": FIXTURE_SCHEMA_ID,
        "generator_id": GENERATOR_ID,
        "generator_version": GENERATOR_VERSION,
        "license": LICENSE,
    }
    for field, expected in identities.items():
        if fixture[field] != expected:
            raise WmbsM02Error(f"fixture {field} does not match {expected!r}")
    if type(fixture["seed"]) is not int:
        raise WmbsM02Error("fixture seed must be an int")

    corpus = fixture["corpus"]
    if not isinstance(corpus, list) or len(corpus) != CORPUS_SIZE:
        raise WmbsM02Error(f"fixture corpus must contain {CORPUS_SIZE} documents")
    doc_ids: list[str] = []
    for index, raw in enumerate(corpus):
        doc = _closed_mapping(raw, _DOCUMENT_KEYS, f"corpus[{index}]")
        for field in _DOCUMENT_KEYS:
            if not isinstance(doc[field], str) or not doc[field]:
                raise WmbsM02Error(f"corpus[{index}].{field} must be non-empty")
        doc_ids.append(doc["stable_item_id"])
    if len(doc_ids) != len(set(doc_ids)):
        raise WmbsM02Error("corpus stable_item_id values must be unique")

    questions = fixture["questions"]
    if (
        not isinstance(questions, list)
        or len(questions) != len(QUERY_FAMILIES) * QUESTIONS_PER_FAMILY
    ):
        raise WmbsM02Error("fixture questions must contain 60 rows")
    question_ids: list[str] = []
    family_counts = {family: 0 for family in QUERY_FAMILIES}
    for index, raw in enumerate(questions):
        question = _validate_question(raw, label=f"questions[{index}]")
        if any(doc_id not in doc_ids for doc_id in question["gold_doc_ids"]):
            raise WmbsM02Error("question gold_doc_ids must reference the corpus")
        question_ids.append(question["question_id"])
        family_counts[question["family"]] += 1
    if len(question_ids) != len(set(question_ids)):
        raise WmbsM02Error("question_id values must be unique")
    if set(family_counts.values()) != {QUESTIONS_PER_FAMILY}:
        raise WmbsM02Error("each query family must contain exactly 10 questions")
    if fixture["fixture_sha256"] != _fixture_digest(fixture):
        raise WmbsM02Error("fixture digest mismatch")
    return fixture


def _validate_question(raw: object, *, label: str) -> Mapping[str, Any]:
    question = _closed_mapping(raw, _QUESTION_KEYS, label)
    if not isinstance(question["question_id"], str) or not question["question_id"]:
        raise WmbsM02Error(f"{label}.question_id must be non-empty")
    if not isinstance(question["text"], str) or not question["text"]:
        raise WmbsM02Error(f"{label}.text must be non-empty")
    family = question["family"]
    if family not in QUERY_FAMILIES:
        raise WmbsM02Error(f"{label}.family is outside the closed enum")
    gold = _nonempty_strings(
        question["gold_doc_ids"],
        f"{label}.gold_doc_ids",
        allow_empty=family == "unanswerable",
    )
    answers = _nonempty_strings(
        question["answers"], f"{label}.answers", allow_empty=family == "unanswerable"
    )
    if family == "unanswerable" and (gold or answers):
        raise WmbsM02Error("unanswerable questions require empty gold and answers")
    if family != "unanswerable" and not gold:
        raise WmbsM02Error("non-unanswerable questions require non-empty gold_doc_ids")
    return question


def load_fixture(path: Path = FIXTURE_PATH) -> dict[str, Any]:
    raw = Path(path).read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise WmbsM02Error("fixture payload must be an object")
    validate_fixture(payload)
    if raw != canonical_json(payload):
        raise WmbsM02Error("fixture file must use canonical bytes")
    return payload


def normalize_fixture(fixture: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    validate_fixture(fixture)
    return {
        question["question_id"]: dict(question) for question in fixture["questions"]
    }


def _normalized_answer(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKC", value).lower()
    normalized = "".join(
        " "
        if char in string.punctuation or unicodedata.category(char).startswith("P")
        else char
        for char in normalized
    )
    return " ".join(
        token for token in normalized.split() if token not in {"a", "an", "the"}
    )


def _token_f1(answer: object, gold_answers: Sequence[str]) -> float:
    predicted = _normalized_answer(answer).split()
    best = 0.0
    for gold in gold_answers:
        expected = _normalized_answer(gold).split()
        common = sum((Counter(predicted) & Counter(expected)).values())
        if not predicted or not expected:
            best = max(best, float(predicted == expected))
            continue
        if common:
            precision = common / len(predicted)
            recall = common / len(expected)
            best = max(best, 2 * precision * recall / (precision + recall))
    return best


def _ndcg(ids: Sequence[str], gold: set[str], k: int) -> float:
    dcg = sum(
        1 / math.log2(rank + 2)
        for rank, stable_item_id in enumerate(ids[:k])
        if stable_item_id in gold
    )
    ideal = sum(1 / math.log2(rank + 2) for rank in range(min(len(gold), k)))
    return dcg / ideal


def score_retrieval(
    fixture: Mapping[str, Any], traces: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Score caller-supplied traces over fixed labels; execute no retrieval."""
    validate_fixture(fixture)
    corpus_ids = {document["stable_item_id"] for document in fixture["corpus"]}
    raw_questions = fixture["questions"]
    questions = {}
    for index, raw in enumerate(raw_questions):
        question = _validate_question(raw, label=f"questions[{index}]")
        question_id = question["question_id"]
        if question_id in questions:
            raise WmbsM02Error("question_id values must be unique")
        questions[question_id] = question
    if not isinstance(traces, Sequence) or isinstance(traces, (str, bytes)):
        raise WmbsM02Error("traces must be a sequence")
    if len(traces) != len(questions):
        raise WmbsM02Error("trace count must equal question count")

    bound: dict[str, tuple[Mapping[str, Any], list[str]]] = {}
    evidence_scores: list[float] = []
    evidence_id_count = 0
    for raw_trace in traces:
        trace_keys = _TRACE_KEYS | (
            {"evidence_ids"}
            if isinstance(raw_trace, Mapping) and "evidence_ids" in raw_trace
            else set()
        )
        raw_trace = _closed_mapping(raw_trace, frozenset(trace_keys), "trace")
        case_id = raw_trace.get("case_id")
        question_id = raw_trace.get("question_id")
        if not isinstance(case_id, str) or case_id != question_id:
            raise WmbsM02Error("every trace must carry case_id == question_id")
        if question_id not in questions or question_id in bound:
            raise WmbsM02Error("traces must bind each question exactly once")
        if "abstained" in raw_trace and type(raw_trace["abstained"]) is not bool:
            raise WmbsM02Error("trace abstained must be a bool when present")
        if raw_trace["answer"] is not None and not isinstance(raw_trace["answer"], str):
            raise WmbsM02Error("trace answer must be a string or null")
        if raw_trace["abstained"] and raw_trace["answer"] is not None:
            raise WmbsM02Error("abstained trace answer must be null")
        if not raw_trace["abstained"] and raw_trace["answer"] is None:
            raise WmbsM02Error("non-abstained trace answer must be a string")
        hits = raw_trace.get("ranked_hits")
        if not isinstance(hits, list):
            raise WmbsM02Error("ranked_hits must be a list")
        ranked_ids: list[str] = []
        ranks: list[int] = []
        for hit in hits:
            if not isinstance(hit, Mapping):
                raise WmbsM02Error("each ranked hit must be an object")
            rank = hit.get("rank")
            stable_item_id = hit.get("stable_item_id")
            if (
                type(rank) is not int
                or not isinstance(stable_item_id, str)
                or not stable_item_id
            ):
                raise WmbsM02Error(
                    "ranked hits require integer rank and stable_item_id"
                )
            ranks.append(rank)
            ranked_ids.append(stable_item_id)
        if ranks != list(range(1, len(ranks) + 1)):
            raise WmbsM02Error("ranked hit ranks must be contiguous 1..N")
        if len(ranked_ids) != len(set(ranked_ids)):
            raise WmbsM02Error("duplicate ranked stable_item_id")
        if not set(ranked_ids).issubset(corpus_ids):
            raise WmbsM02Error("ranked stable_item_id values must reference the corpus")
        question = questions[question_id]
        if question["family"] != "unanswerable" and not ranked_ids:
            raise WmbsM02Error(
                "non-unanswerable questions require non-empty ranked_hits"
            )
        evidence_ids = raw_trace.get("evidence_ids")
        if evidence_ids is not None:
            evidence = _nonempty_strings(
                evidence_ids, "trace.evidence_ids", allow_empty=True
            )
            gold = set(question["gold_doc_ids"])
            if gold:
                evidence_id_count += len(evidence)
                evidence_scores.append(len(gold.intersection(evidence)) / len(gold))
        bound[question_id] = (raw_trace, ranked_ids)

    answerable = [q for q in questions.values() if q["family"] != "unanswerable"]
    unanswerable = [q for q in questions.values() if q["family"] == "unanswerable"]
    metrics: dict[str, float | str] = {}
    for k in (1, 3, 5, 10):
        metrics[f"recall_at_{k}"] = (
            sum(
                len(set(bound[q["question_id"]][1][:k]).intersection(q["gold_doc_ids"]))
                / len(q["gold_doc_ids"])
                for q in answerable
            )
            / len(answerable)
            if answerable
            else 0.0
        )
    for k in (5, 10):
        metrics[f"ndcg_at_{k}"] = (
            sum(
                _ndcg(bound[q["question_id"]][1], set(q["gold_doc_ids"]), k)
                for q in answerable
            )
            / len(answerable)
            if answerable
            else 0.0
        )
    metrics["evidence_recall"] = (
        sum(evidence_scores) / len(evidence_scores)
        if len(evidence_scores) == len(answerable) and evidence_id_count
        else "unsupported"
    )
    metrics["unanswerable_correct_rate"] = (
        sum(
            bool(bound[q["question_id"]][0]["abstained"])
            or (
                not bound[q["question_id"]][1]
                and not _normalized_answer(bound[q["question_id"]][0]["answer"])
            )
            for q in unanswerable
        )
        / len(unanswerable)
        if unanswerable
        else 0.0
    )
    exact_scores: list[float] = []
    token_scores: list[float] = []
    for question in answerable:
        trace, ranked_ids = bound[question["question_id"]]
        answer = trace.get("answer")
        normalized = _normalized_answer(answer)
        gold_answers = {_normalized_answer(value) for value in question["answers"]}
        exact_scores.append(float(normalized in gold_answers))
        token_scores.append(_token_f1(answer, question["answers"]))
    unsupported_claims = 0
    answered_count = 0
    for question in questions.values():
        trace, ranked_ids = bound[question["question_id"]]
        if trace["answer"] not in (None, "") and not trace["abstained"]:
            answered_count += 1
            unsupported_claims += not (
                bool(set(ranked_ids).intersection(question["gold_doc_ids"]))
                and _normalized_answer(trace["answer"])
                in {_normalized_answer(answer) for answer in question["answers"]}
            )
    metrics["unsupported_claim_rate"] = (
        unsupported_claims / answered_count if answered_count else 0.0
    )
    metrics["exact_match"] = (
        sum(exact_scores) / len(exact_scores) if exact_scores else 0.0
    )
    metrics["token_f1"] = sum(token_scores) / len(token_scores) if token_scores else 0.0
    metrics.update(
        {name: "unsupported" for name in ("latency", "tokens", "calls", "storage")}
    )
    interval = {"method": "descriptive"}
    passed = (
        metrics["recall_at_10"] == 1.0
        and metrics["ndcg_at_10"] == 1.0
        and metrics["evidence_recall"] in {"unsupported", 1.0}
        and metrics["unanswerable_correct_rate"] == 1.0
        and metrics["unsupported_claim_rate"] == 0.0
        and metrics["exact_match"] == 1.0
        and metrics["token_f1"] == 1.0
    )
    return {
        "family": FAMILY,
        "finite_corpus_only": True,
        "interval": interval,
        "intervals": {name: dict(interval) for name in metrics},
        "metrics": metrics,
        "passed": passed,
        "profile": PROFILE,
        "profile_version": PROFILE_VERSION,
        "total": len(questions),
        "trace_count": len(traces),
    }
