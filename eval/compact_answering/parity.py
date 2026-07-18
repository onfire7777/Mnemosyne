"""Byte-exact output parity for compact-answering providers."""

from __future__ import annotations

import base64
import binascii
import math
from dataclasses import dataclass

ANSWER_TYPES = frozenset({"span", "yes", "no"})
_ROW_FIELDS = {
    "decoded_span_b64",
    "answer_type",
    "supporting_facts",
    "null_margin",
    "abstained",
}


class ParityValidationError(ValueError):
    """A provider row is not the exact supported parity schema."""


class ParityMismatchError(AssertionError):
    """Two valid provider rows differ on a parity field."""


@dataclass(frozen=True)
class SupportingFact:
    """One ordered supporting-fact coordinate."""

    source_id: str
    sentence_index: int


@dataclass(frozen=True)
class ParityRow:
    """Decoded, strictly validated output from one answering provider."""

    decoded_span_bytes: bytes
    answer_type: str
    supporting_facts: tuple[SupportingFact, ...]
    null_margin: float
    abstained: bool


def _parse_span(value: object) -> bytes:
    if not isinstance(value, str):
        raise ParityValidationError("decoded_span_b64 must be a Base64 string")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ParityValidationError("decoded_span_b64 must be valid padded Base64") from exc
    if base64.b64encode(decoded).decode("ascii") != value:
        raise ParityValidationError("decoded_span_b64 must use canonical padded Base64")
    return decoded


def _parse_supporting_facts(value: object) -> tuple[SupportingFact, ...]:
    if not isinstance(value, list):
        raise ParityValidationError("supporting_facts must be an ordered JSON array")
    parsed: list[SupportingFact] = []
    for index, fact in enumerate(value):
        if not isinstance(fact, dict) or set(fact) != {"source_id", "sentence_index"}:
            raise ParityValidationError(
                f"supporting_facts[{index}] must contain only source_id and sentence_index"
            )
        source_id = fact["source_id"]
        sentence_index = fact["sentence_index"]
        if not isinstance(source_id, str) or not source_id or source_id != source_id.strip():
            raise ParityValidationError(
                f"supporting_facts[{index}].source_id must be a non-empty exact string"
            )
        if (
            not isinstance(sentence_index, int)
            or isinstance(sentence_index, bool)
            or sentence_index < 0
        ):
            raise ParityValidationError(
                f"supporting_facts[{index}].sentence_index must be a non-negative integer"
            )
        parsed.append(SupportingFact(source_id, sentence_index))
    return tuple(parsed)


def parse_parity_row(document: object) -> ParityRow:
    """Parse one provider row using the closed, fail-closed parity schema."""
    if not isinstance(document, dict):
        raise ParityValidationError("parity row must be a JSON object")
    if set(document) != _ROW_FIELDS:
        missing = sorted(_ROW_FIELDS - set(document))
        unsupported = sorted(set(document) - _ROW_FIELDS)
        raise ParityValidationError(
            f"parity row fields must be exact; missing={missing}, unsupported={unsupported}"
        )

    answer_type = document["answer_type"]
    if not isinstance(answer_type, str) or answer_type not in ANSWER_TYPES:
        raise ParityValidationError(f"unsupported answer_type: {answer_type!r}")

    null_margin = document["null_margin"]
    if not isinstance(null_margin, float) or not math.isfinite(null_margin):
        raise ParityValidationError("null_margin must be a finite JSON float")

    abstained = document["abstained"]
    if not isinstance(abstained, bool):
        raise ParityValidationError("abstained must be a JSON boolean")

    decoded_span_bytes = _parse_span(document["decoded_span_b64"])
    if abstained and decoded_span_bytes:
        raise ParityValidationError("abstained rows must have empty decoded span bytes")
    if not abstained and not decoded_span_bytes:
        raise ParityValidationError("answered rows must have non-empty decoded span bytes")
    if not abstained and answer_type in {"yes", "no"}:
        expected = answer_type.encode("ascii")
        if decoded_span_bytes != expected:
            raise ParityValidationError(
                f"{answer_type} rows must use canonical decoded bytes {answer_type!r}"
            )

    return ParityRow(
        decoded_span_bytes=decoded_span_bytes,
        answer_type=answer_type,
        supporting_facts=_parse_supporting_facts(document["supporting_facts"]),
        null_margin=null_margin,
        abstained=abstained,
    )


def compare_parity_rows(reference: object, candidate: object) -> None:
    """Require exact agreement between two valid compact-answering rows."""
    expected = parse_parity_row(reference)
    actual = parse_parity_row(candidate)
    for field in (
        "answer_type",
        "abstained",
        "decoded_span_bytes",
        "supporting_facts",
        "null_margin",
    ):
        if getattr(expected, field) != getattr(actual, field):
            raise ParityMismatchError(f"parity mismatch: {field}")
