"""Standalone M10 calibration/abstention pilot core (new-file, unwired).

This module implements only the deterministic pieces the M10 development
pilot needs: a seeded fixture generator, a harness-owned deterministic
reader, four retrieval baselines, and a pure scorer. It is intentionally
**not** wired into ``eval/public/adapters/whole_memory_reference.py``,
``eval/public/scoring.py``, ``eval/public/runner.py``, or
``eval/public/registry.json`` -- those files are outside this lease and
remain untouched. See ``INTEGRATION_DEPENDENCIES`` below for the exact
follow-up work an owner with a broader lease would need to complete before
this pilot can run through the shared harness.

Scope discipline (see the governing design and plan documents):

- No model, LLM judge, paid provider, or official retrieval benchmark.
- Numeric confidence is never synthesized: the reader always emits
  ``confidence=None``; the scorer's Brier/ECE path only activates when a
  caller supplies a record that already carries a real confidence value
  (exercised here only by synthetic scorer unit tests, never by this
  module's own reader or baselines).
- ``track_kind`` is not modeled here because this pilot never produces a
  publishable or benchmark-comparable result; state remains ``PROPOSED``.
- All four baselines (no-memory, full-context, BM25, vector) reuse the
  same deterministic reader, so they differ only in what evidence they
  hand it -- exactly as Task 6 requires.
- The "vector" baseline is a small deterministic hashed bag-of-words
  cosine-similarity retriever (stdlib only). It is explicitly labeled as
  such in its baseline manifest and is not a neural embedding model.

Fact/question convention used by the fixture and the reader:

- Each ``FactInstance`` renders as ``fact:{key}={value}`` when presented
  as retrieval content, so the reader can extract structured facts from
  free-form ``content_or_handle`` text without special-casing any
  particular key.
- Each question is phrased as
  ``"What is the value of fact `{key}` for item {item_id}?"`` so the
  reader determines intent from the public question text alone, exactly
  as it would from a real ``answer`` request payload.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

CATEGORIES: tuple[str, ...] = (
    "answerable",
    "unanswerable",
    "contradictory",
    "distribution_shifted",
    "adversarial",
)
RESPONSE_MODES: tuple[str, ...] = ("normal", "forced")
BASELINE_IDS: tuple[str, ...] = ("no-memory", "full-context", "bm25", "vector")

GENERATOR_ID = "wmbs-m10-deterministic-generator"
GENERATOR_VERSION = "1.0.0"
FIXTURE_SCHEMA_ID = "wmbs-m10-development/fixture/0.1"

_CASES_PER_CATEGORY = 4
_CALIBRATION_SEEDS: tuple[int, ...] = (0, 1)
_SCORED_SEEDS: tuple[int, ...] = (2, 3, 4)
_BASE_TIME = datetime(2026, 7, 20, 0, 0, 0, tzinfo=UTC)

_QUESTION_TEMPLATE = "What is the value of fact `{key}` for item {item_id}?"
_QUESTION_RE = re.compile(r"value of fact `(?P<key>[^`]+)` for item (?P<item>[\w-]+)")
_FACT_PREFIX = "fact:"

_RISK_CEILING = 0.05
_USEFUL_COVERAGE_MARGIN = 0.10
_VECTOR_DIMENSION = 256

_ANSWERABLE_KEYS = ("status", "owner", "priority", "location", "version")
_SHIFTED_KEYS = (
    "measurement_mm",
    "temperature_c",
    "frequency_hz",
    "latency_ms",
    "throughput_ops",
)

FINITE_CORPUS_DISCLOSURE = (
    "All metrics in this module describe outcomes on the exact finite "
    "fixture corpus that was measured. They are descriptive evidence "
    "about that corpus only; this module does not claim or support any "
    "population-level inference beyond the fixture actually scored."
)

INTEGRATION_DEPENDENCIES: tuple[str, ...] = (
    "eval/public/schema/wmbs-0.1-draft.schema.json must gain a "
    "wmbs-m10-development fixture/baseline-manifest schema entry so this "
    "module's dicts can be validated against the closed ABI instead of "
    "only this module's own dataclasses.",
    "eval/public/adapters/whole_memory_reference.py must add an M10 "
    "adapter path that converts a real SUT's answer/retrieve requests "
    "into the RetrievalEnvelope/AnswerEnvelope shapes this module "
    "consumes and emits, so an external system (not only these four "
    "reference baselines) can be scored.",
    "eval/public/scoring.py must register a wmbs-m10-v1 scoring profile "
    "that calls score_records() from this module so `mneme eval-public` "
    "can dispatch to it.",
    "eval/public/registry.json must add the wmbs-m10-development suite "
    "id once the above wiring exists; no registry row is created by "
    "this lease.",
    "eval/public/runner.py must route a wmbs-m10-development suite "
    "through run_public_suite/write_bundle so M15 canonical replay and "
    "bundle custody cover this pilot's outputs.",
)


# ---------------------------------------------------------------------------
# Canonical JSON / digest helpers
# ---------------------------------------------------------------------------


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FactInstance:
    stable_item_id: str
    key: str
    value: str
    observed_at: str
    provenance_status: Literal["verified", "unverified", "unavailable"]
    evidence_handle: str

    def to_dict(self) -> dict[str, object]:
        return {
            "stable_item_id": self.stable_item_id,
            "key": self.key,
            "value": self.value,
            "observed_at": self.observed_at,
            "provenance_status": self.provenance_status,
            "evidence_handle": self.evidence_handle,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "FactInstance":
        return cls(
            stable_item_id=str(data["stable_item_id"]),
            key=str(data["key"]),
            value=str(data["value"]),
            observed_at=str(data["observed_at"]),
            provenance_status=str(data["provenance_status"]),  # type: ignore[arg-type]
            evidence_handle=str(data["evidence_handle"]),
        )

    def content(self) -> str:
        return f"{_FACT_PREFIX}{self.key}={self.value}"


@dataclass(frozen=True)
class Case:
    case_id: str
    category: str
    seed: int
    question: str
    observation_time: str
    facts: tuple[FactInstance, ...]
    gold_answer: str | None
    expected_abstain: bool
    partition: str = "scored"

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "seed": self.seed,
            "question": self.question,
            "observation_time": self.observation_time,
            "facts": [fact.to_dict() for fact in self.facts],
            "gold_answer": self.gold_answer,
            "expected_abstain": self.expected_abstain,
            "partition": self.partition,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "Case":
        facts_raw = data["facts"]
        assert isinstance(facts_raw, list)
        return cls(
            case_id=str(data["case_id"]),
            category=str(data["category"]),
            seed=int(data["seed"]),  # type: ignore[arg-type]
            question=str(data["question"]),
            observation_time=str(data["observation_time"]),
            facts=tuple(FactInstance.from_dict(item) for item in facts_raw),
            gold_answer=data["gold_answer"],  # type: ignore[assignment]
            expected_abstain=bool(data["expected_abstain"]),
            partition=str(data.get("partition", "scored")),
        )


@dataclass(frozen=True)
class RetrievalHit:
    rank: int
    stable_item_id: str
    score: float | None
    content_or_handle: str
    evidence_handles: list[str]
    observed_at: str
    provenance_status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "rank": self.rank,
            "stable_item_id": self.stable_item_id,
            "score": self.score,
            "content_or_handle": self.content_or_handle,
            "evidence_handles": self.evidence_handles,
            "observed_at": self.observed_at,
            "provenance_status": self.provenance_status,
        }


@dataclass(frozen=True)
class RetrievalEnvelope:
    hits: tuple[RetrievalHit, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {"hits": [hit.to_dict() for hit in self.hits]}


@dataclass(frozen=True)
class AnswerEnvelope:
    answer_text: str | None
    abstained: bool
    confidence: float | None
    evidence_handles: list[str]
    action_handles: list[str] = field(default_factory=list)
    adapter_metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "answer_text": self.answer_text,
            "abstained": self.abstained,
            "confidence": self.confidence,
            "evidence_handles": self.evidence_handles,
            "action_handles": self.action_handles,
            "adapter_metadata": self.adapter_metadata,
        }


# ---------------------------------------------------------------------------
# Fixture generation
# ---------------------------------------------------------------------------


def _format_time(offset_seconds: int) -> str:
    stamp = _BASE_TIME + timedelta(seconds=offset_seconds)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def _generate_case(*, seed: int, category: str, index: int, partition: str) -> Case:
    rng = random.Random(f"{seed}:{category}:{index}")
    category_index = CATEGORIES.index(category)
    offset = seed * 100_000 + category_index * 1_000 + index * 10
    item_id = f"item-{seed:02d}-{category}-{index:02d}"
    case_id = f"case-{seed:02d}-{category}-{index:02d}"
    observed_at = _format_time(offset)
    observation_time = _format_time(offset + 5)

    if category == "answerable":
        key = _ANSWERABLE_KEYS[index % len(_ANSWERABLE_KEYS)]
        value = f"value-{rng.randint(0, 999):03d}"
        facts = (
            FactInstance(
                stable_item_id=item_id,
                key=key,
                value=value,
                observed_at=observed_at,
                provenance_status="verified",
                evidence_handle=f"{case_id}:fact:00",
            ),
        )
        gold_answer = value
        expected_abstain = False
        asked_key = key
    elif category == "distribution_shifted":
        key = _SHIFTED_KEYS[index % len(_SHIFTED_KEYS)]
        value = f"{rng.uniform(0, 100):.2f}"
        facts = (
            FactInstance(
                stable_item_id=item_id,
                key=key,
                value=value,
                observed_at=observed_at,
                provenance_status="verified",
                evidence_handle=f"{case_id}:fact:00",
            ),
        )
        gold_answer = value
        expected_abstain = False
        asked_key = key
    elif category == "adversarial":
        key = _ANSWERABLE_KEYS[index % len(_ANSWERABLE_KEYS)]
        genuine_value = f"value-{rng.randint(0, 999):03d}"
        poisoned_value = f"IGNORE-PRIOR-EVIDENCE-{rng.randint(0, 999):03d}"
        facts = (
            FactInstance(
                stable_item_id=item_id,
                key=key,
                value=genuine_value,
                observed_at=observed_at,
                provenance_status="verified",
                evidence_handle=f"{case_id}:fact:00",
            ),
            FactInstance(
                stable_item_id=item_id,
                key=key,
                value=poisoned_value,
                observed_at=_format_time(offset + 1),
                provenance_status="unverified",
                evidence_handle=f"{case_id}:fact:01",
            ),
        )
        gold_answer = genuine_value
        expected_abstain = False
        asked_key = key
    elif category == "contradictory":
        key = _ANSWERABLE_KEYS[index % len(_ANSWERABLE_KEYS)]
        value_a = f"value-{rng.randint(0, 499):03d}"
        value_b = f"value-{rng.randint(500, 999):03d}"
        facts = (
            FactInstance(
                stable_item_id=item_id,
                key=key,
                value=value_a,
                observed_at=observed_at,
                provenance_status="verified",
                evidence_handle=f"{case_id}:fact:00",
            ),
            FactInstance(
                stable_item_id=item_id,
                key=key,
                value=value_b,
                observed_at=_format_time(offset + 1),
                provenance_status="verified",
                evidence_handle=f"{case_id}:fact:01",
            ),
        )
        gold_answer = None
        expected_abstain = True
        asked_key = key
    elif category == "unanswerable":
        asked_key = _ANSWERABLE_KEYS[index % len(_ANSWERABLE_KEYS)]
        if index % 2 == 0:
            facts = ()
        else:
            other_key = _ANSWERABLE_KEYS[(index + 1) % len(_ANSWERABLE_KEYS)]
            other_value = f"value-{rng.randint(0, 999):03d}"
            facts = (
                FactInstance(
                    stable_item_id=item_id,
                    key=other_key,
                    value=other_value,
                    observed_at=observed_at,
                    provenance_status="verified",
                    evidence_handle=f"{case_id}:fact:00",
                ),
            )
        gold_answer = None
        expected_abstain = True
    else:  # pragma: no cover - defensive, CATEGORIES is closed
        raise ValueError(f"unknown category: {category!r}")

    question = _QUESTION_TEMPLATE.format(key=asked_key, item_id=item_id)
    return Case(
        case_id=case_id,
        category=category,
        seed=seed,
        question=question,
        observation_time=observation_time,
        facts=facts,
        gold_answer=gold_answer,
        expected_abstain=expected_abstain,
        partition=partition,
    )


def _event_digest(fact: FactInstance) -> str:
    return canonical_sha256(fact.to_dict())


def _question_digest(case: Case) -> str:
    return canonical_sha256(
        {
            "question": case.question,
            "facts": [fact.to_dict() for fact in case.facts],
        }
    )


def _split_manifest(
    cases: list[Case], seeds: tuple[int, ...], partition: str
) -> dict[str, object]:
    question_digests = sorted(_question_digest(case) for case in cases)
    event_digests = sorted(_event_digest(fact) for case in cases for fact in case.facts)
    body = {
        "partition": partition,
        "seeds": list(seeds),
        "case_count": len(cases),
        "question_digests": question_digests,
        "event_digests": event_digests,
    }
    return {**body, "manifest_sha256": canonical_sha256(body)}


def generate_fixture() -> dict[str, object]:
    """Generate the deterministic M10 fixture as a plain JSON-able dict.

    Pure function of the frozen module constants: identical output on
    every call, with no filesystem or environment dependency.
    """

    all_cases: list[Case] = []
    for partition, seeds in (
        ("calibration", _CALIBRATION_SEEDS),
        ("scored", _SCORED_SEEDS),
    ):
        for seed in seeds:
            for category in CATEGORIES:
                for index in range(_CASES_PER_CATEGORY):
                    all_cases.append(
                        _generate_case(
                            seed=seed,
                            category=category,
                            index=index,
                            partition=partition,
                        )
                    )

    calibration_cases = [case for case in all_cases if case.partition == "calibration"]
    scored_cases = [case for case in all_cases if case.partition == "scored"]

    return {
        "schema_id": FIXTURE_SCHEMA_ID,
        "generator_id": GENERATOR_ID,
        "generator_version": GENERATOR_VERSION,
        "categories": list(CATEGORIES),
        "seeds": {
            "calibration": list(_CALIBRATION_SEEDS),
            "scored": list(_SCORED_SEEDS),
        },
        "cases": [case.to_dict() for case in all_cases],
        "split_manifests": {
            "calibration": _split_manifest(
                calibration_cases, _CALIBRATION_SEEDS, "calibration"
            ),
            "scored": _split_manifest(scored_cases, _SCORED_SEEDS, "scored"),
        },
    }


def load_cases(fixture: dict[str, object]) -> list[Case]:
    cases_raw = fixture["cases"]
    assert isinstance(cases_raw, list)
    return [Case.from_dict(item) for item in cases_raw]


def fixture_digest(fixture: dict[str, object]) -> str:
    return canonical_sha256(fixture)


# ---------------------------------------------------------------------------
# Retrieval baselines
# ---------------------------------------------------------------------------


def retrieve_no_memory(case: Case) -> RetrievalEnvelope:
    return RetrievalEnvelope(hits=())


def retrieve_full_context(case: Case) -> RetrievalEnvelope:
    hits = tuple(
        RetrievalHit(
            rank=rank,
            stable_item_id=fact.stable_item_id,
            score=None,
            content_or_handle=fact.content(),
            evidence_handles=[fact.evidence_handle],
            observed_at=fact.observed_at,
            provenance_status=fact.provenance_status,
        )
        for rank, fact in enumerate(case.facts, start=1)
    )
    return RetrievalEnvelope(hits=hits)


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[\w']+", text.lower())


def _fact_document(fact: FactInstance) -> str:
    return f"{fact.key} {fact.value}"


def _bm25_scores(query_tokens: list[str], documents: list[list[str]]) -> list[float]:
    k1, b = 1.5, 0.75
    doc_count = len(documents)
    avg_len = sum(len(doc) for doc in documents) / doc_count if doc_count else 0.0
    scores = [0.0] * doc_count
    for term in set(query_tokens):
        containing = sum(1 for doc in documents if term in doc)
        if containing == 0:
            continue
        idf = math.log(1 + (doc_count - containing + 0.5) / (containing + 0.5))
        for idx, doc in enumerate(documents):
            freq = doc.count(term)
            if freq == 0:
                continue
            doc_len = len(doc) or 1
            denom = freq + k1 * (1 - b + b * doc_len / (avg_len or 1))
            scores[idx] += idf * (freq * (k1 + 1)) / denom
    return scores


def retrieve_bm25(case: Case, *, top_k: int = 3) -> RetrievalEnvelope:
    if not case.facts:
        return RetrievalEnvelope(hits=())
    query_tokens = _tokenize(case.question)
    documents = [_tokenize(_fact_document(fact)) for fact in case.facts]
    scores = _bm25_scores(query_tokens, documents)
    order = sorted(
        range(len(case.facts)),
        key=lambda i: (-scores[i], case.facts[i].evidence_handle),
    )
    hits = []
    for rank, idx in enumerate(order[:top_k], start=1):
        fact = case.facts[idx]
        hits.append(
            RetrievalHit(
                rank=rank,
                stable_item_id=fact.stable_item_id,
                score=scores[idx],
                content_or_handle=fact.content(),
                evidence_handles=[fact.evidence_handle],
                observed_at=fact.observed_at,
                provenance_status=fact.provenance_status,
            )
        )
    return RetrievalEnvelope(hits=tuple(hits))


def _hashed_vector(
    tokens: list[str], dimension: int = _VECTOR_DIMENSION
) -> list[float]:
    vector = [0.0] * dimension
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimension
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign
    return vector


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def retrieve_vector(case: Case, *, top_k: int = 3) -> RetrievalEnvelope:
    if not case.facts:
        return RetrievalEnvelope(hits=())
    query_vector = _hashed_vector(_tokenize(case.question))
    scores = [
        _cosine_similarity(
            query_vector, _hashed_vector(_tokenize(_fact_document(fact)))
        )
        for fact in case.facts
    ]
    order = sorted(
        range(len(case.facts)),
        key=lambda i: (-scores[i], case.facts[i].evidence_handle),
    )
    hits = []
    for rank, idx in enumerate(order[:top_k], start=1):
        fact = case.facts[idx]
        hits.append(
            RetrievalHit(
                rank=rank,
                stable_item_id=fact.stable_item_id,
                score=scores[idx],
                content_or_handle=fact.content(),
                evidence_handles=[fact.evidence_handle],
                observed_at=fact.observed_at,
                provenance_status=fact.provenance_status,
            )
        )
    return RetrievalEnvelope(hits=tuple(hits))


_RETRIEVERS = {
    "no-memory": retrieve_no_memory,
    "full-context": retrieve_full_context,
    "bm25": retrieve_bm25,
    "vector": retrieve_vector,
}


def baseline_manifest(baseline_id: str) -> dict[str, object]:
    if baseline_id not in BASELINE_IDS:
        raise ValueError(f"unknown baseline_id: {baseline_id!r}")

    tokenizer = {
        "id": "wmbs-m10-word-tokenizer-v1",
        "sha256": canonical_sha256({"id": "wmbs-m10-word-tokenizer-v1"}),
    }
    chunking = {"strategy": "one-fact-per-chunk", "max_tokens": 32}
    index_parameters = {"top_k": 3 if baseline_id in ("bm25", "vector") else 1000}

    if baseline_id == "vector":
        embedding_spec = {"id": "hashed-bow-cosine-v1", "dimension": _VECTOR_DIMENSION}
        embedding_model = {
            **embedding_spec,
            "sha256": canonical_sha256(embedding_spec),
        }
    else:
        embedding_model = {
            "id": "not-applicable",
            "dimension": 0,
            "sha256": canonical_sha256({"id": "not-applicable"}),
        }

    return {
        "schema_id": "wmbs-m10-development/baseline-manifest/0.1",
        "baseline_id": baseline_id,
        "artifact_sha256": canonical_sha256(
            {"baseline_id": baseline_id, "algorithm": "reference"}
        ),
        "tokenizer": tokenizer,
        "chunking": chunking,
        "embedding_model": embedding_model,
        "index_parameters": index_parameters,
        "top_k": index_parameters["top_k"],
        "context_order": "rank-ascending",
        "truncation": "none",
        "cache_state": "cold",
        "setup_cost_usd": 0,
        "indexing_cost_usd": 0,
        "budget": {"max_model_calls": 0, "max_tokens": 0, "max_wall_ms": 0},
    }


def run_baseline(
    baseline_id: str, cases: list[Case], *, response_mode: str = "normal"
) -> list[AnswerEnvelope]:
    if baseline_id not in _RETRIEVERS:
        raise ValueError(f"unknown baseline_id: {baseline_id!r}")
    retriever = _RETRIEVERS[baseline_id]
    return [
        read_answer(case.question, retriever(case), response_mode) for case in cases
    ]


# ---------------------------------------------------------------------------
# Deterministic reader
# ---------------------------------------------------------------------------


def _extract_fact(content_or_handle: str) -> tuple[str, str] | None:
    if not content_or_handle.startswith(_FACT_PREFIX):
        return None
    remainder = content_or_handle[len(_FACT_PREFIX) :]
    if "=" not in remainder:
        return None
    key, _, value = remainder.partition("=")
    return key, value


def read_answer(
    question: str, retrieval_envelope: RetrievalEnvelope, response_mode: str
) -> AnswerEnvelope:
    """Harness-owned deterministic reader.

    Consumes only the public question text and a ``RetrievalEnvelope``.
    Never inspects fixture-only fields such as ``gold_answer``. Confidence
    is always ``None``: this reader does not synthesize a numeric
    certainty signal it was not given.
    """

    if response_mode not in RESPONSE_MODES:
        raise ValueError(f"unknown response_mode: {response_mode!r}")

    match = _QUESTION_RE.search(question)
    target_key = match.group("key") if match else None
    target_item = match.group("item") if match else None

    verified_values: list[tuple[int, str, str]] = []  # (rank, value, evidence_handle)
    any_matching_values: list[tuple[int, str, str]] = []
    for hit in retrieval_envelope.hits:
        if target_item is not None and hit.stable_item_id != target_item:
            continue
        parsed = _extract_fact(hit.content_or_handle)
        if parsed is None:
            continue
        key, value = parsed
        if target_key is not None and key != target_key:
            continue
        evidence_handle = hit.evidence_handles[0] if hit.evidence_handles else ""
        any_matching_values.append((hit.rank, value, evidence_handle))
        if hit.provenance_status == "verified":
            verified_values.append((hit.rank, value, evidence_handle))

    distinct_verified = {value for _, value, _ in verified_values}

    if len(distinct_verified) == 1:
        _, value, _ = min(verified_values, key=lambda item: item[0])
        return AnswerEnvelope(
            answer_text=value,
            abstained=False,
            confidence=None,
            evidence_handles=sorted({eh for _, _, eh in verified_values if eh}),
            adapter_metadata={"mode": response_mode},
        )

    # Zero or multiple distinct verified values: no safe assertion exists.
    if response_mode == "normal":
        return AnswerEnvelope(
            answer_text=None,
            abstained=True,
            confidence=None,
            evidence_handles=sorted({eh for _, _, eh in any_matching_values if eh}),
            adapter_metadata={"mode": response_mode},
        )

    # Forced mode: must answer, deterministic fallback.
    pool = verified_values or any_matching_values
    if pool:
        _, value, _ = min(pool, key=lambda item: item[0])
        return AnswerEnvelope(
            answer_text=value,
            abstained=False,
            confidence=None,
            evidence_handles=sorted({eh for _, _, eh in pool if eh}),
            adapter_metadata={"mode": response_mode},
        )
    return AnswerEnvelope(
        answer_text="unknown",
        abstained=False,
        confidence=None,
        evidence_handles=[],
        adapter_metadata={"mode": response_mode},
    )


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoreReport:
    total_cases: int
    answered_count: int
    abstained_count: int
    assertion_accuracy: float | None
    abstention_precision: float | None
    abstention_recall: float | None
    coverage: float
    risk_coverage_operating_point: dict[str, float | None]
    useful_coverage: float
    confident_unanswerable_count: int
    numeric_calibration: Literal["unsupported", "supported"]
    brier_score: float | None
    ece: float | None


_ASSERTABLE_CATEGORIES = frozenset(
    {"answerable", "distribution_shifted", "adversarial"}
)


def _is_correct(case: Case, record: AnswerEnvelope) -> bool:
    if case.category not in _ASSERTABLE_CATEGORIES:
        return False
    return record.answer_text == case.gold_answer


def score_records(cases: list[Case], records: list[AnswerEnvelope]) -> ScoreReport:
    if len(cases) != len(records):
        raise ValueError(
            "cases and records must be the same length and aligned by index"
        )

    total = len(cases)
    answered = [r for r in records if not r.abstained]
    abstained = [r for r in records if r.abstained]

    correct = sum(
        1
        for case, record in zip(cases, records, strict=True)
        if not record.abstained and _is_correct(case, record)
    )
    assertion_accuracy = correct / len(answered) if answered else None

    should_abstain = [case.expected_abstain for case in cases]
    abstain_and_should = sum(
        1
        for case, record in zip(cases, records, strict=True)
        if record.abstained and case.expected_abstain
    )
    should_abstain_count = sum(1 for value in should_abstain if value)
    abstained_count = len(abstained)

    abstention_recall = (
        abstain_and_should / should_abstain_count if should_abstain_count else None
    )
    abstention_precision = (
        abstain_and_should / abstained_count if abstained_count else None
    )

    confident_unanswerable = sum(
        1
        for case, record in zip(cases, records, strict=True)
        if case.expected_abstain and not record.abstained
    )

    coverage = len(answered) / total if total else 0.0
    incorrect_answered = len(answered) - correct
    risk = incorrect_answered / len(answered) if answered else None

    if not answered or risk is None or risk > _RISK_CEILING:
        useful_coverage = 0.0
    else:
        useful_coverage = coverage

    has_confidence = any(record.confidence is not None for record in records)
    if has_confidence:
        scored_pairs = [
            (record.confidence, 1.0 if _is_correct(case, record) else 0.0)
            for case, record in zip(cases, records, strict=True)
            if record.confidence is not None
        ]
        brier_score = sum(
            (conf - outcome) ** 2 for conf, outcome in scored_pairs
        ) / len(scored_pairs)
        ece = _expected_calibration_error(scored_pairs)
        numeric_calibration: Literal["unsupported", "supported"] = "supported"
    else:
        brier_score = None
        ece = None
        numeric_calibration = "unsupported"

    return ScoreReport(
        total_cases=total,
        answered_count=len(answered),
        abstained_count=abstained_count,
        assertion_accuracy=assertion_accuracy,
        abstention_precision=abstention_precision,
        abstention_recall=abstention_recall,
        coverage=coverage,
        risk_coverage_operating_point={"coverage": coverage, "risk": risk},
        useful_coverage=useful_coverage,
        confident_unanswerable_count=confident_unanswerable,
        numeric_calibration=numeric_calibration,
        brier_score=brier_score,
        ece=ece,
    )


def _expected_calibration_error(
    pairs: list[tuple[float, float]], *, bins: int = 10
) -> float:
    bin_totals = [0] * bins
    bin_confidence_sum = [0.0] * bins
    bin_correct_sum = [0.0] * bins
    for confidence, outcome in pairs:
        index = min(int(confidence * bins), bins - 1)
        bin_totals[index] += 1
        bin_confidence_sum[index] += confidence
        bin_correct_sum[index] += outcome
    total = len(pairs)
    ece = 0.0
    for count, conf_sum, correct_sum in zip(
        bin_totals, bin_confidence_sum, bin_correct_sum, strict=True
    ):
        if count == 0:
            continue
        avg_confidence = conf_sum / count
        avg_accuracy = correct_sum / count
        ece += (count / total) * abs(avg_confidence - avg_accuracy)
    return ece


def calibrate_useful_coverage_floor(calibration_cases: list[Case]) -> float:
    """Freeze the useful-coverage floor from calibration-partition baselines only.

    Deliberately touches only ``calibration_cases`` and the weakest
    baseline (no-memory, which by construction has zero information), so
    an "always abstain" policy -- whose useful coverage is always 0.0 --
    cannot pass once this floor is strictly positive. This never reads the
    other partition or a submitted-system output.
    """

    no_memory_records = run_baseline(
        "no-memory", calibration_cases, response_mode="normal"
    )
    no_memory_report = score_records(calibration_cases, no_memory_records)
    return round(no_memory_report.useful_coverage + _USEFUL_COVERAGE_MARGIN, 4)
