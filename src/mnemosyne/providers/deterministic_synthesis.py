"""Standalone deterministic synthesis over authorized extracted spans."""

from __future__ import annotations

import re
from collections.abc import Mapping
from fractions import Fraction
from functools import reduce
from operator import add, mul, sub

_ARITHMETIC = {"add", "subtract", "multiply", "divide"}
_DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.([0-9]+))?")
_MAX_SPANS = 16
_MAX_CID_LENGTH = 256
_MAX_QUOTE_LENGTH = 128
_MAX_DIGITS = 64
_MAX_SCALE = 18


class DeterministicSynthesisError(ValueError):
    """Raised when deterministic synthesis cannot safely resolve a request."""


def _fail() -> DeterministicSynthesisError:
    return DeterministicSynthesisError("deterministic synthesis request is invalid")


def _validate_spans(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list) or not 2 <= len(value) <= _MAX_SPANS:
        raise _fail()
    spans: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"cid", "quote"}:
            raise _fail()
        cid, quote = item["cid"], item["quote"]
        if (
            not isinstance(cid, str)
            or not isinstance(quote, str)
            or not cid
            or not quote
            or len(cid) > _MAX_CID_LENGTH
            or len(quote) > _MAX_QUOTE_LENGTH
        ):
            raise _fail()
        identity = (cid, quote)
        if identity in seen:
            raise _fail()
        seen.add(identity)
        spans.append({"cid": cid, "quote": quote})
    return spans


def _parse_decimal(value: str) -> Fraction:
    match = _DECIMAL.fullmatch(value)
    if match is None:
        raise _fail()
    digits = value.removeprefix("-").replace(".", "")
    scale = len(match.group(1) or "")
    if len(digits) > _MAX_DIGITS or scale > _MAX_SCALE:
        raise _fail()
    return Fraction(int(digits) * (-1 if value.startswith("-") else 1), 10**scale)


def _canonical_decimal(value: Fraction) -> str:
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    scale = max(twos, fives)
    if denominator != 1 or scale > _MAX_SCALE:
        raise _fail()

    scaled = abs(value.numerator) * 10**scale // value.denominator
    digits = str(scaled)
    integer_digits = max(1, len(digits) - scale)
    if integer_digits + scale > _MAX_DIGITS:
        raise _fail()
    if scale:
        digits = digits.zfill(scale + 1)
        text = f"{digits[:-scale]}.{digits[-scale:]}".rstrip("0").rstrip(".")
    else:
        text = digits
    if value < 0 and scaled:
        text = f"-{text}"
    return text


def _arithmetic(operation: str, spans: list[dict[str, str]]) -> str:
    values = [_parse_decimal(span["quote"]) for span in spans]
    if operation == "add":
        result = reduce(add, values)
    elif operation == "subtract":
        result = reduce(sub, values)
    elif operation == "multiply":
        result = reduce(mul, values)
    else:
        if any(value == 0 for value in values[1:]):
            raise _fail()
        result = reduce(lambda left, right: left / right, values)
    return _canonical_decimal(result)


class DeterministicSynthesizer:
    """Resolve allowlisted operations without models, I/O, or code execution."""

    def synthesize(self, payload: Mapping[str, object]) -> dict[str, object]:
        if not isinstance(payload, Mapping) or set(payload) != {"operation", "spans"}:
            raise _fail()
        operation = payload["operation"]
        if not isinstance(operation, str) or operation not in _ARITHMETIC:
            raise _fail()
        spans = _validate_spans(payload["spans"])
        return {
            "answer": _arithmetic(operation, spans),
            "operation": operation,
            "provenance": spans,
            "unresolved": False,
        }
