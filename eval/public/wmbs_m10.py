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
# Full canonical grammar match (Finding 3): the entire question string must
# match this template exactly, anchored start-to-end. A question that only
# *contains* the pattern as a substring (e.g. with garbage prefix/suffix) is
# malformed and must not be treated as if it were well-formed -- see
# `read_answer` for the fail-closed handling this enables.
_QUESTION_GRAMMAR_RE = re.compile(
    r"\AWhat is the value of fact `(?P<key>[^`]+)` for item (?P<item>[\w-]+)\?\Z"
)
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
    "This module's fixture generator (generate_fixture) is a fully "
    "self-contained, deterministic, standalone generator: it does not "
    "call, import, or otherwise depend on the shared M02-M04 event "
    "generator used elsewhere in the harness. Wiring this pilot so its "
    "facts/questions are drawn from that shared event generator (instead "
    "of this module's own synthetic fixture) is an unresolved external "
    "integration gate outside this lease -- it is not attempted, faked, "
    "or partially wired here, and this pilot's PROPOSED/development-only "
    "status reflects that gap.",
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


class WmbsM10Error(ValueError):
    """Base error for every local wmbs-m10 contract/ABI violation.

    All validation failures this module raises -- answer-envelope shape,
    confidence bounds, and calibration-split-manifest integrity -- are (or
    subclass) this error, so a caller that wants to catch "this local
    record/artifact violates the wmbs-m10 contract" has a single type to
    catch. It subclasses ``ValueError`` so existing ``pytest.raises
    (ValueError)`` call sites for this module's more specific error
    subclasses remain valid.
    """


class AnswerEnvelopeValidationError(WmbsM10Error):
    """A local answer record violates the closed AnswerEnvelope contract.

    Enforced at two trust boundaries: ``AnswerEnvelope.from_dict`` (loading
    a raw local record, e.g. from a JSON results file) and
    ``score_records`` (scoring an already-constructed envelope, which a
    caller can build directly with a coercive or contradictory shape since
    dataclasses do not validate field types at construction time). Neither
    boundary relies on ``bool()``/``str()`` coercion or a bare ``assert``:
    every violation raises this error before any metric computation runs.
    """


_REQUIRED_ANSWER_ENVELOPE_FIELDS = frozenset(
    {"answer_text", "abstained", "confidence", "evidence_handles"}
)
_OPTIONAL_ANSWER_ENVELOPE_FIELDS = frozenset({"action_handles", "adapter_metadata"})
_ALLOWED_ANSWER_ENVELOPE_FIELDS = (
    _REQUIRED_ANSWER_ENVELOPE_FIELDS | _OPTIONAL_ANSWER_ENVELOPE_FIELDS
)

# The closed vocabulary of ``adapter_metadata`` keys this module's own
# reader (``read_answer``) ever emits. A local record's metadata is
# validated against this same closed set rather than accepted as an
# arbitrary str-to-str bag, so an adapter cannot smuggle unbounded or
# unvetted keys through a field this module treats as diagnostic-only.
_ALLOWED_ADAPTER_METADATA_KEYS = frozenset({"mode", "abstain_reason", "fallback_reason"})


def _validate_adapter_metadata(metadata: object) -> None:
    if not isinstance(metadata, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in metadata.items()
    ):
        raise AnswerEnvelopeValidationError(
            "local answer record adapter_metadata must be a dict of str "
            "to str"
        )
    unknown_keys = set(metadata) - _ALLOWED_ADAPTER_METADATA_KEYS
    if unknown_keys:
        raise AnswerEnvelopeValidationError(
            "local answer record adapter_metadata has unknown key(s) "
            f"{sorted(unknown_keys)}; allowed keys are "
            f"{sorted(_ALLOWED_ADAPTER_METADATA_KEYS)}"
        )
    mode = metadata.get("mode")
    if mode is not None and mode not in RESPONSE_MODES:
        raise AnswerEnvelopeValidationError(
            "local answer record adapter_metadata['mode'] must be one of "
            f"{RESPONSE_MODES}, got {mode!r}"
        )


def _validate_handle_list(handles: object, *, field_name: str) -> None:
    """Reject a non-list, non-str-item, empty-string, or duplicate handle.

    Applied to both ``evidence_handles`` and ``action_handles``: both are
    lists of opaque identifier handles under the same closed ABI, so both
    must be unique and nonempty-per-entry for the same reason.
    """

    if not isinstance(handles, list) or not all(
        isinstance(item, str) for item in handles
    ):
        raise AnswerEnvelopeValidationError(
            f"local answer record {field_name} must be a list of str"
        )
    if any(item == "" for item in handles):
        raise AnswerEnvelopeValidationError(
            f"local answer record {field_name} must not contain empty "
            "handles"
        )
    if len(handles) != len(set(handles)):
        raise AnswerEnvelopeValidationError(
            f"local answer record {field_name} must not contain "
            "duplicate handles"
        )


def _validate_answer_envelope_shape(
    *, answer_text: object, abstained: object, case_id: str = "<unknown>"
) -> None:
    """Reject a coercive or contradictory ``(answer_text, abstained)`` pair.

    ``isinstance(abstained, bool)`` is checked *before* the
    abstained/answer_text consistency checks below on purpose: a truthy
    non-bool value such as ``"false"`` would otherwise silently satisfy
    ``not abstained and answer_text is None`` under Python's normal
    truthiness rules, which is exactly the ``bool()``-coercion failure
    mode this validator exists to close.
    """

    if not isinstance(abstained, bool):
        raise AnswerEnvelopeValidationError(
            f"case {case_id!r}: abstained must be a bool, not "
            f"{type(abstained).__name__} ({abstained!r})"
        )
    if answer_text is not None and not isinstance(answer_text, str):
        raise AnswerEnvelopeValidationError(
            f"case {case_id!r}: answer_text must be str or None, not "
            f"{type(answer_text).__name__}"
        )
    if abstained and answer_text is not None:
        raise AnswerEnvelopeValidationError(
            f"case {case_id!r}: abstained=True requires answer_text=None, "
            f"got answer_text={answer_text!r}"
        )
    if not abstained and answer_text is None:
        raise AnswerEnvelopeValidationError(
            f"case {case_id!r}: abstained=False requires a non-null "
            "answer_text"
        )
    if not abstained and answer_text == "":
        raise AnswerEnvelopeValidationError(
            f"case {case_id!r}: abstained=False requires a nonempty "
            "answer_text"
        )


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

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "AnswerEnvelope":
        """Validating loader for a local (system-output) answer record.

        This is the harness-side trust boundary for records that were not
        produced by this module's own ``read_answer``: every field is
        checked against the closed contract before an ``AnswerEnvelope``
        is constructed, so a malformed local record fails closed here
        rather than silently coercing into something ``score_records``
        would misinterpret. The contract is closed in both directions:
        every required field must be present (checked below) and no
        field outside ``_ALLOWED_ANSWER_ENVELOPE_FIELDS`` may appear at
        all -- an adapter cannot smuggle an extra key through this
        boundary on the assumption that an unrecognized field is silently
        ignored.
        """

        if not isinstance(data, dict):
            raise AnswerEnvelopeValidationError(
                f"local answer record must be a dict, not "
                f"{type(data).__name__}"
            )
        unknown = set(data) - _ALLOWED_ANSWER_ENVELOPE_FIELDS
        if unknown:
            raise AnswerEnvelopeValidationError(
                "local answer record has unknown field(s) "
                f"{sorted(unknown)}; allowed fields are "
                f"{sorted(_ALLOWED_ANSWER_ENVELOPE_FIELDS)}"
            )
        missing = _REQUIRED_ANSWER_ENVELOPE_FIELDS - set(data)
        if missing:
            raise AnswerEnvelopeValidationError(
                "local answer record is missing required field(s): "
                f"{sorted(missing)}"
            )

        answer_text = data["answer_text"]
        abstained = data["abstained"]
        _validate_answer_envelope_shape(answer_text=answer_text, abstained=abstained)

        confidence = data["confidence"]
        _validate_confidence(confidence, case_id="<from_dict>")

        evidence_handles = data["evidence_handles"]
        _validate_handle_list(evidence_handles, field_name="evidence_handles")

        action_handles = data.get("action_handles", [])
        _validate_handle_list(action_handles, field_name="action_handles")

        adapter_metadata = data.get("adapter_metadata", {})
        _validate_adapter_metadata(adapter_metadata)

        return cls(
            answer_text=answer_text,  # type: ignore[arg-type]
            abstained=abstained,  # type: ignore[arg-type]
            confidence=confidence,  # type: ignore[arg-type]
            evidence_handles=evidence_handles,  # type: ignore[arg-type]
            action_handles=action_handles,  # type: ignore[arg-type]
            adapter_metadata=adapter_metadata,  # type: ignore[arg-type]
        )


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
    """Hash canonical question identity/text alone (Finding 4).

    Deliberately excludes ``case.facts``: fact/event content already has
    its own digest via ``_event_digest``, and conflating the two axes here
    would mean a question's digest changes whenever unrelated evidence
    changes, defeating the split-manifest disjointness check this digest
    exists to support.
    """
    return canonical_sha256({"question": case.question})


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

    fixture: dict[str, object] = {
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
    # Finding 1: freeze the digest-bound calibration artifact as part of the
    # fixture itself, so it is checked into git alongside the cases it was
    # derived from rather than recomputed ad hoc by a gate at scoring time.
    fixture["calibration_artifact"] = build_calibration_artifact(fixture)
    return fixture


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

    A question that does not fully match the canonical grammar is
    malformed. Normal mode abstains immediately, without scanning the
    retrieval envelope at all -- there is no canonical ``target_key``/
    ``target_item`` to filter hits against, so scanning unfiltered hits
    would silently fail open onto unrelated evidence (Finding 3). Forced
    mode must still return an answer, so it falls back to the same
    explicit, deterministic "unknown" sentinel used when there is no
    evidence at all, instead of guessing from unfiltered hits.
    """

    if response_mode not in RESPONSE_MODES:
        raise ValueError(f"unknown response_mode: {response_mode!r}")

    match = _QUESTION_GRAMMAR_RE.fullmatch(question)
    if match is None:
        if response_mode == "normal":
            return AnswerEnvelope(
                answer_text=None,
                abstained=True,
                confidence=None,
                evidence_handles=[],
                adapter_metadata={
                    "mode": response_mode,
                    "abstain_reason": "malformed_question",
                },
            )
        return AnswerEnvelope(
            answer_text="unknown",
            abstained=False,
            confidence=None,
            evidence_handles=[],
            adapter_metadata={
                "mode": response_mode,
                "fallback_reason": "malformed_question",
            },
        )

    target_key = match.group("key")
    target_item = match.group("item")

    verified_values: list[tuple[int, str, str]] = []  # (rank, value, evidence_handle)
    any_matching_values: list[tuple[int, str, str]] = []
    for hit in retrieval_envelope.hits:
        if hit.stable_item_id != target_item:
            continue
        parsed = _extract_fact(hit.content_or_handle)
        if parsed is None:
            continue
        key, value = parsed
        if key != target_key:
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


class ConfidenceValidationError(WmbsM10Error):
    """A record supplied a confidence value outside the closed contract.

    Finding 5: confidence must be a real (non-bool), finite number in the
    closed interval ``[0, 1]``. This is checked for every record before any
    metric computation runs, so an invalid value cannot silently corrupt
    Brier/ECE.
    """


def _validate_confidence(confidence: object, *, case_id: str) -> None:
    if confidence is None:
        return
    if isinstance(confidence, bool):
        raise ConfidenceValidationError(
            f"case {case_id!r}: confidence must be a real number in the "
            f"closed interval [0, 1], not a bool ({confidence!r})"
        )
    if not isinstance(confidence, (int, float)):
        raise ConfidenceValidationError(
            f"case {case_id!r}: confidence must be a real number in the "
            f"closed interval [0, 1], got {type(confidence).__name__}"
        )
    if not math.isfinite(confidence):
        raise ConfidenceValidationError(
            f"case {case_id!r}: confidence must be finite, got {confidence!r}"
        )
    if not (0.0 <= confidence <= 1.0):
        raise ConfidenceValidationError(
            f"case {case_id!r}: confidence must be in the closed interval "
            f"[0, 1], got {confidence!r}"
        )


def _is_correct(case: Case, record: AnswerEnvelope) -> bool:
    if case.category not in _ASSERTABLE_CATEGORIES:
        return False
    return record.answer_text == case.gold_answer


CALIBRATION_COVERAGE_RULE = (
    "Local scoring contract (Finding 2): numeric calibration (Brier score, "
    "ECE) is scored only over the answered (non-abstained) population of a "
    "given score_records() call -- the population that actually asserts an "
    "answer, and therefore the only population a confidence value makes a "
    "claim about. It requires a real `confidence` value on every answered "
    "record in that population. If even one answered record has "
    "`confidence=None`, `numeric_calibration` is 'unsupported' and "
    "brier_score/ece are both None: partial confidence coverage can never "
    "yield a gating-eligible metric, closing the incentive to supply "
    "confidence only on easy/correct answered cases. Confidence values on "
    "abstained records are ignored for this computation: an abstention "
    "makes no assertion, so there is nothing for Brier/ECE to calibrate."
)


def score_records(cases: list[Case], records: list[AnswerEnvelope]) -> ScoreReport:
    if len(cases) != len(records):
        raise ValueError(
            "cases and records must be the same length and aligned by index"
        )

    for case, record in zip(cases, records, strict=True):
        _validate_answer_envelope_shape(
            answer_text=record.answer_text,
            abstained=record.abstained,
            case_id=case.case_id,
        )
        _validate_confidence(record.confidence, case_id=case.case_id)

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

    # Finding 2 / CALIBRATION_COVERAGE_RULE: calibration is only "supported"
    # when every answered record carries a confidence value. Partial
    # coverage (some answered records confident, others None) must not be
    # gameable into a passing calibration metric, so it is treated exactly
    # like no coverage at all.
    complete_answered_confidence = bool(answered) and all(
        record.confidence is not None for record in answered
    )
    if complete_answered_confidence:
        scored_pairs = [
            (record.confidence, 1.0 if _is_correct(case, record) else 0.0)
            for case, record in zip(cases, records, strict=True)
            if not record.abstained
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
    """Derive the useful-coverage floor from calibration-partition baselines only.

    Deliberately touches only ``calibration_cases`` and the weakest
    baseline (no-memory, which by construction has zero information), so
    an "always abstain" policy -- whose useful coverage is always 0.0 --
    cannot pass once this floor is strictly positive. This never reads the
    other partition or a submitted-system output.

    This function is the raw derivation step used once, by
    ``build_calibration_artifact``, to freeze the floor into a digest-bound
    artifact. It is *not* the sanctioned entry point for gating a report's
    ``useful_coverage`` (Finding 1): callers that need the floor for gating
    must use ``useful_coverage_floor_from_fixture`` instead, which verifies
    the frozen artifact's digest before returning a floor, rather than
    trusting a fresh recomputation from whatever this function's code
    currently does.
    """

    no_memory_records = run_baseline(
        "no-memory", calibration_cases, response_mode="normal"
    )
    no_memory_report = score_records(calibration_cases, no_memory_records)
    return round(no_memory_report.useful_coverage + _USEFUL_COVERAGE_MARGIN, 4)


# ---------------------------------------------------------------------------
# Calibration artifact (Finding 1)
# ---------------------------------------------------------------------------

CALIBRATION_ARTIFACT_SCHEMA_ID = "wmbs-m10-development/calibration-artifact/0.1"

USEFUL_COVERAGE_DERIVATION_RULE = (
    "useful_coverage_floor = round(calibration_metrics['no-memory']"
    "['useful_coverage'] + 0.10, 4). The no-memory baseline has zero "
    "retrieval evidence by construction, so its useful_coverage on the "
    "calibration partition is 0.0 unless it both answers and stays under "
    "the fixed risk ceiling -- which it structurally cannot do without "
    "evidence. The fixed +0.10 margin is the only free parameter in this "
    "rule, and it is applied exactly once, here, to freeze the floor into "
    "this artifact; it is never recomputed per scoring run from whatever "
    "the baseline/scorer code currently does."
)


class CalibrationSplitManifestError(WmbsM10Error):
    """The calibration split manifest fails independent recomputation.

    Raised by ``_verify_calibration_split_manifest`` when the calibration
    partition is empty, the scored partition is empty, the stored
    ``fixture["split_manifests"]["calibration"]`` does not exactly match a
    manifest independently recomputed from this fixture's own calibration
    cases (a forged, rehashed, stale, or otherwise inconsistent stored
    manifest), or the calibration and scored partitions are not disjoint
    by question digest or event digest.
    """


def _verify_calibration_split_manifest(
    fixture: dict[str, object],
    *,
    calibration_cases: list[Case],
    scored_cases: list[Case],
) -> dict[str, object]:
    """Independently recompute and validate the calibration split manifest.

    Never trusts ``fixture["split_manifests"]["calibration"]`` as a source
    of the digest embedded in the calibration artifact -- that stored
    manifest is only ever used here as a *claim* to be checked against a
    manifest recomputed from ``calibration_cases`` (loaded from
    ``fixture["cases"]``, the one independent custody anchor) and the
    frozen ``_CALIBRATION_SEEDS`` module constant. ``fixture["seeds"]`` is
    deliberately not consulted: it is exactly as forgeable as
    ``fixture["split_manifests"]`` itself, so using it as an input to the
    recomputation would let an attacker forge both sides of the
    comparison in lockstep.

    Returns the recomputed (trusted) manifest so the caller sources the
    embedded ``calibration_split_manifest_sha256`` from it directly,
    rather than from the untrusted stored copy -- even when the stored
    copy happens to match.
    """

    if not calibration_cases:
        raise CalibrationSplitManifestError(
            "calibration partition is empty: cannot derive a calibration "
            "split manifest or useful-coverage floor from zero "
            "calibration cases"
        )
    if not scored_cases:
        raise CalibrationSplitManifestError(
            "scored partition is empty: cannot verify calibration/scored "
            "partition disjointness"
        )

    recomputed_calibration = _split_manifest(
        calibration_cases, _CALIBRATION_SEEDS, "calibration"
    )
    recomputed_scored = _split_manifest(scored_cases, _SCORED_SEEDS, "scored")

    stored_split_manifests = fixture.get("split_manifests")
    stored_calibration = (
        stored_split_manifests.get("calibration")
        if isinstance(stored_split_manifests, dict)
        else None
    )
    if stored_calibration != recomputed_calibration:
        raise CalibrationSplitManifestError(
            "stored calibration split manifest does not match the "
            "manifest independently recomputed from this fixture's own "
            "calibration cases and the frozen calibration seeds: the "
            "stored manifest (and/or its digest) was forged, is stale "
            "relative to the fixture's cases, or is otherwise "
            "inconsistent"
        )

    calibration_question_digests = set(recomputed_calibration["question_digests"])
    calibration_event_digests = set(recomputed_calibration["event_digests"])
    scored_question_digests = set(recomputed_scored["question_digests"])
    scored_event_digests = set(recomputed_scored["event_digests"])

    if not calibration_question_digests.isdisjoint(scored_question_digests):
        raise CalibrationSplitManifestError(
            "calibration and scored partitions share at least one "
            "question digest: the partitions must be disjoint"
        )
    if not calibration_event_digests.isdisjoint(scored_event_digests):
        raise CalibrationSplitManifestError(
            "calibration and scored partitions share at least one event "
            "digest: the partitions must be disjoint"
        )

    return recomputed_calibration


def _score_report_to_dict(report: ScoreReport) -> dict[str, object]:
    return {
        "total_cases": report.total_cases,
        "answered_count": report.answered_count,
        "abstained_count": report.abstained_count,
        "assertion_accuracy": report.assertion_accuracy,
        "abstention_precision": report.abstention_precision,
        "abstention_recall": report.abstention_recall,
        "coverage": report.coverage,
        "risk_coverage_operating_point": report.risk_coverage_operating_point,
        "useful_coverage": report.useful_coverage,
        "confident_unanswerable_count": report.confident_unanswerable_count,
        "numeric_calibration": report.numeric_calibration,
        "brier_score": report.brier_score,
        "ece": report.ece,
    }


def build_calibration_artifact(fixture: dict[str, object]) -> dict[str, object]:
    """Freeze the full evidence bundle the useful-coverage floor derives from.

    Deterministic, pure function of ``fixture``'s own ``cases``. Touches
    ``calibration_cases`` for the baseline manifests/outputs the floor is
    derived from, and additionally reads ``scored_cases`` -- but only to
    independently recompute and verify the calibration split manifest
    (see ``_verify_calibration_split_manifest``); the scored partition's
    content never contributes to any baseline metric or to the floor
    itself, and a submitted system's output is never touched here.

    The returned dict contains all four baseline manifests, each
    baseline's calibration-partition metrics, the derivation rule, and the
    resulting floor, and is digest-bound (``artifact_sha256``): any caller
    that wants to *use* ``useful_coverage_floor`` for gating must call
    ``verify_calibration_artifact`` (or the convenience wrapper
    ``useful_coverage_floor_from_fixture``) first, rather than trusting an
    unverified or freshly recomputed number.
    """

    all_cases = load_cases(fixture)
    calibration_cases = [case for case in all_cases if case.partition == "calibration"]
    scored_cases = [case for case in all_cases if case.partition == "scored"]

    recomputed_calibration_manifest = _verify_calibration_split_manifest(
        fixture, calibration_cases=calibration_cases, scored_cases=scored_cases
    )

    baseline_manifests = {
        baseline_id: baseline_manifest(baseline_id) for baseline_id in BASELINE_IDS
    }
    calibration_metrics: dict[str, object] = {}
    for baseline_id in BASELINE_IDS:
        records = run_baseline(baseline_id, calibration_cases, response_mode="normal")
        report = score_records(calibration_cases, records)
        calibration_metrics[baseline_id] = _score_report_to_dict(report)

    no_memory_useful_coverage = calibration_metrics["no-memory"]["useful_coverage"]
    assert isinstance(no_memory_useful_coverage, float)
    floor = round(no_memory_useful_coverage + _USEFUL_COVERAGE_MARGIN, 4)

    body = {
        "schema_id": CALIBRATION_ARTIFACT_SCHEMA_ID,
        "calibration_split_manifest_sha256": recomputed_calibration_manifest[
            "manifest_sha256"
        ],
        "baseline_manifests": baseline_manifests,
        "calibration_metrics": calibration_metrics,
        "derivation_rule": USEFUL_COVERAGE_DERIVATION_RULE,
        "useful_coverage_floor": floor,
    }
    return {**body, "artifact_sha256": canonical_sha256(body)}


def verify_calibration_artifact(artifact: dict[str, object]) -> None:
    """Raise ``ValueError`` if ``artifact`` is internally inconsistent.

    This checks only that ``artifact_sha256`` matches the rest of
    ``artifact``'s own contents -- i.e. that the artifact has not been
    edited *without* also rehashing it. That is a necessary sanity check
    but it is **not** authenticity: an attacker who edits
    ``useful_coverage_floor`` (or any other field) and correctly
    recomputes ``artifact_sha256`` over the edited body passes this check
    every time, since the digest is stored inside the same untrusted
    object it is supposed to protect. Callers that need to gate on the
    floor must use ``useful_coverage_floor_from_fixture`` instead, which
    additionally binds the artifact to independently recomputed data from
    the fixture it claims to describe.
    """

    if "artifact_sha256" not in artifact:
        raise ValueError("calibration artifact is missing artifact_sha256")
    body = {key: value for key, value in artifact.items() if key != "artifact_sha256"}
    expected = canonical_sha256(body)
    if artifact["artifact_sha256"] != expected:
        raise ValueError(
            "calibration artifact digest mismatch: artifact has been "
            "tampered with, is stale, or was not produced by "
            "build_calibration_artifact"
        )


def useful_coverage_floor_from_fixture(fixture: dict[str, object]) -> float:
    """Return the frozen useful-coverage floor after verifying its digest.

    This is the sanctioned entry point for gating ``ScoreReport
    .useful_coverage`` against the floor (Finding 1, hardened): the
    artifact's self-digest alone proves only that the artifact was not
    edited without rehashing -- it says nothing about whether the artifact
    actually describes *this* fixture's calibration partition. Two
    exploits pass the self-digest check alone:

    1. Rehashed-floor splice: edit ``useful_coverage_floor`` (or any other
       artifact field) and recompute ``artifact_sha256`` over the edited
       body.
    2. Stale-artifact splice: take a previously valid, still
       self-consistent ``calibration_artifact`` and embed it in a fixture
       whose calibration cases (and therefore whose true calibration split
       manifest, baseline metrics, and floor) have since changed.

    Both are closed here by independently rebuilding the calibration
    artifact from ``fixture``'s own calibration cases -- the calibration
    split manifest digest, the four baseline manifests, every baseline's
    calibration-partition metrics, and the derived floor -- via the exact
    same pure derivation ``build_calibration_artifact`` uses, and requiring
    an exact match against the stored artifact. Nothing inside the
    untrusted ``fixture["calibration_artifact"]`` is trusted as evidence
    of its own authenticity; only ``fixture["cases"]`` (the independent
    custody anchor -- see ``test_fixture_file_on_disk_matches_generator_
    output``, which pins the checked-in fixture file to this same
    deterministic generator) drives the recomputation.
    """

    artifact = fixture["calibration_artifact"]
    assert isinstance(artifact, dict)
    verify_calibration_artifact(artifact)

    rebuilt = build_calibration_artifact(fixture)
    if rebuilt != artifact:
        raise ValueError(
            "calibration artifact does not match independently "
            "recomputed calibration data derived from this fixture's own "
            "calibration cases (split manifest digest, baseline "
            "manifests, calibration metrics, and/or useful_coverage_"
            "floor): the artifact was tampered with, is stale relative "
            "to the fixture's calibration cases, or was not produced by "
            "build_calibration_artifact for this exact fixture"
        )

    floor = artifact["useful_coverage_floor"]
    assert isinstance(floor, float)
    return floor
