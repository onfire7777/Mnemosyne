"""Strict, model-free mirror of the compact-answering reader ABI.

This module deliberately stops at the reader boundary.  It validates model
metadata and decoded predictions, reconstructs answers only from source bytes,
and runs a deterministic synthetic TRAIN-only selection fixture.  It never
downloads, loads, or executes a model artifact.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

ABI = "mnemosyne.compact-answering-reader.v1"
ABI_SCHEMA = ABI
SELECTION_FIXTURE_SCHEMA = "mnemosyne.reader-selection-fixture.v1"
BAKEOFF_RECEIPT_SCHEMA = "mnemosyne.reader-bakeoff-receipt.v1"
SELECTION_FIXTURE_STATUS = "synthetic-unmeasured"
SELECTION_SPLIT = "TRAIN"
ARTIFACT_CUSTODY = "synthetic-fixture-no-model-artifact"

WINDOW_TOKENS = 512
WINDOW_STRIDE = 128
MAX_WINDOWS = 64
MAX_FACTS = 20
MAX_REQUEST_BYTES = 64 * 1024
MAX_QUERY_CHARS = 2_000
MAX_CONTEXT_CHARS = 24_000
MAX_CONTEXT_BYTES = 64 * 1024
MAX_ID_CHARS = 256
MAX_SUPPORTING_FACTS = 20
MAX_TOKEN_COUNT = WINDOW_TOKENS + WINDOW_STRIDE * (MAX_WINDOWS - 1)
MAX_FIXTURE_BYTES = 256 * 1024
MAX_FIXTURE_VARIANTS = 8
_DIGEST_HEX_LENGTH = 64
_ANSWER_TYPES = ("span", "yes", "no")
NULL_ANSWER_TYPE = "null"
SUPPORTED_ANSWER_TYPES = frozenset((*_ANSWER_TYPES, NULL_ANSWER_TYPE))
_IDENTITY_FIELDS = frozenset(
    {
        "model_id",
        "artifact_id",
        "artifact_sha256",
        "preprocessing_id",
        "preprocessing_sha256",
    }
)
SELECTION_FIXTURE_PATH = (
    Path(__file__).with_name("fixtures") / "reader-train-dev.json"
)
_UNMEASURED_RECEIPT_FIELDS = (
    "artifact_bytes",
    "quality",
    "latency_ms",
    "peak_memory_mib",
    "resource_envelope",
)
_TOKEN_PATTERN = re.compile(r"\S+")


class ReaderValidationError(ValueError):
    """A reader request, response, identity, offset, or score is invalid."""


class ReaderUnsupportedAnswerError(ReaderValidationError):
    """The model requested an answer type outside the bounded ABI."""


class ReaderOffsetError(ReaderValidationError):
    """A decoded span is not a valid UTF-8 half-open source range."""


class ReaderFixtureValidationError(ReaderValidationError):
    """A synthetic TRAIN fixture or receipt is invalid."""


class ReaderTimeoutError(ReaderFixtureValidationError):
    """A synthetic validation deadline expired before admission."""


def _is_clean_string(value: object, *, max_chars: int = MAX_ID_CHARS) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and len(value) <= max_chars
        and not any(
            ord(character) < 32 or 127 <= ord(character) <= 159
            for character in value
        )
    )


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _DIGEST_HEX_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _as_int(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReaderValidationError(f"{label} must be an integer")
    return value


def _as_finite(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReaderValidationError(f"{label} must be numeric")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ReaderValidationError(f"{label} must fit in a finite float") from exc
    if not math.isfinite(number):
        raise ReaderValidationError(f"{label} must be finite")
    return number


def _as_finite_f32(value: object, *, label: str) -> float:
    number = _as_finite(value, label=label)
    try:
        quantized = struct.unpack("!f", struct.pack("!f", number))[0]
    except OverflowError as exc:
        raise ReaderValidationError(f"{label} must fit in f32") from exc
    if not math.isfinite(quantized):
        raise ReaderValidationError(f"{label} must be finite")
    return quantized


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReaderFixtureValidationError(f"duplicate key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_json(value: str) -> None:
    raise ReaderFixtureValidationError(f"unsupported JSON constant: {value}")


def _parse_json(payload: str | bytes | bytearray) -> object:
    if not isinstance(payload, (str, bytes, bytearray)):
        raise ReaderFixtureValidationError("payload must be JSON text or bytes")
    try:
        return json.loads(
            payload,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_json,
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ReaderFixtureValidationError("payload must be valid JSON") from exc


def _canonical_bytes(document: object) -> bytes:
    try:
        encoded = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ReaderFixtureValidationError("document is not canonical JSON") from exc
    return (encoded + "\n").encode("utf-8")


def _sha256(document: object) -> str:
    return hashlib.sha256(_canonical_bytes(document)).hexdigest()


def _without_field(document: dict[str, Any], field: str) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key != field}


def _exact_object(value: object, fields: set[str], *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ReaderValidationError(f"{label} fields must be exact")
    return value


@dataclass(frozen=True)
class ReaderIdentity:
    """Model, artifact, and preprocessing identity bound to every prediction."""

    model_id: str
    artifact_id: str
    artifact_sha256: str
    preprocessing_id: str
    preprocessing_sha256: str

    @classmethod
    def from_mapping(cls, value: object) -> "ReaderIdentity":
        if not isinstance(value, dict) or set(value) != _IDENTITY_FIELDS:
            raise ReaderValidationError("identity fields must be exact")
        fields = {field: value[field] for field in _IDENTITY_FIELDS}
        for field, item in fields.items():
            if not _is_clean_string(item):
                raise ReaderValidationError(
                    f"identity {field} must be an exact non-empty string"
                )
        for field in ("artifact_sha256", "preprocessing_sha256"):
            if not _is_digest(fields[field]):
                raise ReaderValidationError(
                    f"identity {field} must be {_DIGEST_HEX_LENGTH} lowercase hex characters"
                )
        return cls(**fields)

    def as_mapping(self) -> dict[str, str]:
        return {
            "model_id": self.model_id,
            "artifact_id": self.artifact_id,
            "artifact_sha256": self.artifact_sha256,
            "preprocessing_id": self.preprocessing_id,
            "preprocessing_sha256": self.preprocessing_sha256,
        }

    def require_match(self, expected: "ReaderIdentity") -> None:
        if not isinstance(expected, ReaderIdentity):
            raise ReaderValidationError("identity type is invalid")
        ReaderIdentity.from_mapping(self.as_mapping())
        ReaderIdentity.from_mapping(expected.as_mapping())
        if self == expected:
            return
        for field in _IDENTITY_FIELDS:
            if getattr(self, field) != getattr(expected, field):
                raise ReaderValidationError(f"identity mismatch: {field}")
        raise ReaderValidationError("identity mismatch")


def identity_digest(identity: ReaderIdentity | dict[str, object]) -> str:
    if isinstance(identity, ReaderIdentity):
        parsed = ReaderIdentity.from_mapping(identity.as_mapping())
    else:
        parsed = ReaderIdentity.from_mapping(identity)
    return _sha256(parsed.as_mapping())


@dataclass(frozen=True)
class TokenSpan:
    token: str
    raw_start: int
    raw_end: int

    @classmethod
    def from_mapping(cls, value: object) -> "TokenSpan":
        row = _exact_object(value, {"token", "raw_start", "raw_end"}, label="token")
        token = row["token"]
        if not isinstance(token, str) or not token:
            raise ReaderValidationError("token text must be non-empty")
        raw_start = _as_int(row["raw_start"], label="token raw_start")
        raw_end = _as_int(row["raw_end"], label="token raw_end")
        if raw_start < 0 or raw_end <= raw_start:
            raise ReaderOffsetError("token offsets must be a positive half-open range")
        return cls(token=token, raw_start=raw_start, raw_end=raw_end)

    def as_mapping(self) -> dict[str, object]:
        return {"token": self.token, "raw_start": self.raw_start, "raw_end": self.raw_end}


@dataclass(frozen=True)
class ReaderWindow:
    window_id: str
    token_start: int
    token_end: int
    raw_start: int
    raw_end: int
    tokens: tuple[TokenSpan, ...]

    @classmethod
    def from_mapping(cls, value: object) -> "ReaderWindow":
        row = _exact_object(
            value,
            {"window_id", "token_start", "token_end", "raw_start", "raw_end", "tokens"},
            label="reader window",
        )
        window_id = row["window_id"]
        if not _is_clean_string(window_id):
            raise ReaderValidationError("window_id must be an exact non-empty string")
        token_start = _as_int(row["token_start"], label="window token_start")
        token_end = _as_int(row["token_end"], label="window token_end")
        raw_start = _as_int(row["raw_start"], label="window raw_start")
        raw_end = _as_int(row["raw_end"], label="window raw_end")
        tokens_value = row["tokens"]
        if not isinstance(tokens_value, list) or not tokens_value:
            raise ReaderValidationError("reader window tokens must be non-empty")
        if len(tokens_value) > WINDOW_TOKENS:
            raise ReaderValidationError("reader window exceeds 512 tokens")
        tokens = tuple(TokenSpan.from_mapping(token) for token in tokens_value)
        if token_start < 0 or token_end <= token_start or token_end - token_start != len(tokens):
            raise ReaderValidationError("reader window token shape is invalid")
        if raw_start != tokens[0].raw_start or raw_end != tokens[-1].raw_end:
            raise ReaderOffsetError("window raw offsets must bind to token boundaries")
        if raw_start < 0 or raw_end <= raw_start:
            raise ReaderOffsetError("window raw offsets must be a positive half-open range")
        for previous, current in zip(tokens, tokens[1:]):
            if current.raw_start < previous.raw_end:
                raise ReaderOffsetError("window token offsets must be ordered and non-overlapping")
        return cls(window_id, token_start, token_end, raw_start, raw_end, tokens)

    def as_mapping(self) -> dict[str, object]:
        return {
            "window_id": self.window_id,
            "token_start": self.token_start,
            "token_end": self.token_end,
            "raw_start": self.raw_start,
            "raw_end": self.raw_end,
            "tokens": [token.as_mapping() for token in self.tokens],
        }


@dataclass(frozen=True)
class SupportingFact:
    fact_id: str
    raw_start: int
    raw_end: int
    text: str

    @classmethod
    def from_mapping(cls, value: object) -> "SupportingFact":
        row = _exact_object(value, {"fact_id", "raw_start", "raw_end", "text"}, label="supporting fact")
        fact_id = row["fact_id"]
        text = row["text"]
        if not _is_clean_string(fact_id) or not isinstance(text, str) or not text:
            raise ReaderValidationError("supporting fact identity and text are required")
        raw_start = _as_int(row["raw_start"], label="fact raw_start")
        raw_end = _as_int(row["raw_end"], label="fact raw_end")
        if raw_start < 0 or raw_end <= raw_start:
            raise ReaderOffsetError("supporting fact offsets must be a positive range")
        return cls(fact_id, raw_start, raw_end, text)

    def as_mapping(self) -> dict[str, object]:
        return {
            "fact_id": self.fact_id,
            "raw_start": self.raw_start,
            "raw_end": self.raw_end,
            "text": self.text,
        }


def _utf8_length(text: str) -> int:
    try:
        return len(text.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ReaderOffsetError("source context must be valid UTF-8") from exc


def _byte_offsets(text: str) -> list[int]:
    offsets = [0]
    total = 0
    for character in text:
        total += len(character.encode("utf-8"))
        offsets.append(total)
    return offsets


def build_windows(context: str) -> tuple[ReaderWindow, ...]:
    """Build deterministic whitespace-token windows with byte offsets.

    The production tokenizer may provide an equivalent token map.  This
    tokenizer exists only for the model-free TRAIN fixture and the ABI tests.
    """

    if not isinstance(context, str) or not context:
        raise ReaderValidationError("reader context must be a non-empty string")
    context_bytes = _utf8_length(context)
    if len(context) > MAX_CONTEXT_CHARS or context_bytes > MAX_CONTEXT_BYTES:
        raise ReaderValidationError("reader context exceeds the byte limit")
    offsets = _byte_offsets(context)
    matches = list(_TOKEN_PATTERN.finditer(context))
    if not matches:
        raise ReaderValidationError("reader context must contain at least one token")
    all_tokens = tuple(
        TokenSpan(match.group(0), offsets[match.start()], offsets[match.end()])
        for match in matches
    )
    token_count = len(all_tokens)
    starts = _expected_window_starts(token_count)
    windows: list[ReaderWindow] = []
    for index, token_start in enumerate(starts):
        token_end = min(token_start + WINDOW_TOKENS, token_count)
        tokens = all_tokens[token_start:token_end]
        windows.append(
            ReaderWindow(
                window_id=f"window-{index:03d}",
                token_start=token_start,
                token_end=token_end,
                raw_start=tokens[0].raw_start,
                raw_end=tokens[-1].raw_end,
                tokens=tokens,
            )
        )
    if len(windows) > MAX_WINDOWS:
        raise ReaderValidationError("reader context produces too many windows")
    return tuple(windows)


def _validate_context_offsets(context: str, start: int, end: int, *, label: str) -> None:
    length = _utf8_length(context)
    if start < 0 or end <= start or end > length:
        raise ReaderOffsetError(f"{label} must be a bounded UTF-8 half-open range")
    encoded = context.encode("utf-8")
    try:
        encoded[start:end].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReaderOffsetError(f"{label} must align to UTF-8 boundaries") from exc
    prefix = encoded[:start]
    suffix = encoded[:end]
    try:
        prefix.decode("utf-8")
        suffix.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReaderOffsetError(f"{label} must align to UTF-8 boundaries") from exc


def _expected_window_starts(token_count: int) -> list[int]:
    if token_count <= 0 or token_count > MAX_TOKEN_COUNT:
        raise ReaderValidationError("reader token count exceeds the window limit")
    regular_limit = max(token_count - WINDOW_TOKENS + 1, 1)
    starts = list(range(0, regular_limit, WINDOW_STRIDE))
    final_start = max(token_count - WINDOW_TOKENS, 0)
    if starts[-1] != final_start:
        starts.append(final_start)
    if len(starts) > MAX_WINDOWS:
        raise ReaderValidationError("reader context produces too many windows")
    return starts


@dataclass(frozen=True)
class ReaderRequest:
    schema: str
    identity: ReaderIdentity
    query: str
    context: str
    facts: tuple[SupportingFact, ...]
    windows: tuple[ReaderWindow, ...]
    null_threshold: float

    @classmethod
    def from_mapping(cls, value: object) -> "ReaderRequest":
        row = _exact_object(
            value,
            {"schema", "identity", "query", "context", "facts", "windows", "null_threshold"},
            label="reader request",
        )
        if row["schema"] != ABI_SCHEMA:
            raise ReaderValidationError("unsupported reader ABI schema")
        identity = ReaderIdentity.from_mapping(row["identity"])
        query = row["query"]
        context = row["context"]
        if not _is_clean_string(query, max_chars=MAX_QUERY_CHARS):
            raise ReaderValidationError("reader query must be a bounded non-empty string")
        if not isinstance(context, str) or not context:
            raise ReaderValidationError("reader context must be a non-empty string")
        if len(context) > MAX_CONTEXT_CHARS or _utf8_length(context) > MAX_CONTEXT_BYTES:
            raise ReaderValidationError("reader context exceeds the byte limit")
        facts_value = row["facts"]
        windows_value = row["windows"]
        if not isinstance(facts_value, list) or len(facts_value) > MAX_FACTS:
            raise ReaderValidationError("supporting facts must be a bounded list")
        if not isinstance(windows_value, list) or not windows_value or len(windows_value) > MAX_WINDOWS:
            raise ReaderValidationError("reader windows must be a bounded non-empty list")
        facts = tuple(SupportingFact.from_mapping(fact) for fact in facts_value)
        windows = tuple(ReaderWindow.from_mapping(window) for window in windows_value)
        _validate_request_facts(context, facts)
        _validate_request_windows(context, windows)
        null_threshold = _as_finite_f32(row["null_threshold"], label="null_threshold")
        return cls(row["schema"], identity, query, context, facts, windows, null_threshold)

    def as_mapping(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "identity": self.identity.as_mapping(),
            "query": self.query,
            "context": self.context,
            "facts": [fact.as_mapping() for fact in self.facts],
            "windows": [window.as_mapping() for window in self.windows],
            "null_threshold": self.null_threshold,
        }


def _validate_request_facts(context: str, facts: Iterable[SupportingFact]) -> None:
    seen: set[str] = set()
    evidence_chars = 0
    for fact in facts:
        if fact.fact_id in seen:
            raise ReaderValidationError("supporting fact IDs must be unique")
        seen.add(fact.fact_id)
        _validate_context_offsets(context, fact.raw_start, fact.raw_end, label=f"fact {fact.fact_id}")
        if context.encode("utf-8")[fact.raw_start : fact.raw_end].decode("utf-8") != fact.text:
            raise ReaderOffsetError(f"fact {fact.fact_id} text does not match source bytes")
        evidence_chars += len(fact.text)
        if evidence_chars > MAX_CONTEXT_CHARS:
            raise ReaderValidationError("supporting evidence exceeds the character limit")


def _validate_request_windows(context: str, windows: tuple[ReaderWindow, ...]) -> None:
    context_bytes = context.encode("utf-8")
    token_count = windows[-1].token_end
    expected_starts = _expected_window_starts(token_count)
    if len(expected_starts) != len(windows):
        raise ReaderValidationError("reader windows do not cover the token schedule")
    seen: set[str] = set()
    for index, window in enumerate(windows):
        if window.window_id in seen:
            raise ReaderValidationError("window IDs must be unique")
        seen.add(window.window_id)
        _validate_context_offsets(context, window.raw_start, window.raw_end, label=f"window {window.window_id}")
        context_bytes[window.raw_start : window.raw_end].decode("utf-8")
        for token in window.tokens:
            _validate_context_offsets(context, token.raw_start, token.raw_end, label="window token")
            if context_bytes[token.raw_start : token.raw_end].decode("utf-8") != token.token:
                raise ReaderOffsetError("window token text does not match source bytes")
        expected_start = expected_starts[index]
        expected_end = min(expected_start + WINDOW_TOKENS, token_count)
        if (
            window.token_start != expected_start
            or window.token_end != expected_end
            or len(window.tokens) != expected_end - expected_start
        ):
            raise ReaderValidationError("reader windows must cover the 128-token schedule")
        if index:
            previous = windows[index - 1]
            overlap_start = window.token_start - previous.token_start
            overlap_tokens = previous.token_end - window.token_start
            if (
                overlap_tokens <= 0
                or overlap_start >= len(previous.tokens)
                or overlap_tokens != len(previous.tokens) - overlap_start
                or overlap_tokens > len(window.tokens)
                or previous.tokens[overlap_start:] != window.tokens[:overlap_tokens]
            ):
                raise ReaderOffsetError("reader windows must share one token map")


def validate_request(request: ReaderRequest) -> None:
    """Re-validate directly constructed requests before any reader operation."""

    if not isinstance(request, ReaderRequest):
        raise ReaderValidationError("reader request type is invalid")
    if not isinstance(request.identity, ReaderIdentity):
        raise ReaderValidationError("reader request identity is invalid")
    if not isinstance(request.facts, tuple) or any(
        not isinstance(fact, SupportingFact) for fact in request.facts
    ):
        raise ReaderValidationError("reader request facts shape is invalid")
    if not isinstance(request.windows, tuple) or any(
        not isinstance(window, ReaderWindow) or not isinstance(window.tokens, tuple)
        or any(not isinstance(token, TokenSpan) for token in window.tokens)
        for window in request.windows
    ):
        raise ReaderValidationError("reader request windows shape is invalid")
    try:
        ReaderRequest.from_mapping(request.as_mapping())
    except (AttributeError, TypeError) as exc:
        raise ReaderValidationError("reader request is invalid") from exc


@dataclass(frozen=True)
class ReaderPrediction:
    schema: str
    identity: ReaderIdentity
    window_id: str
    answer_type: str
    start_token: int | None
    end_token: int | None
    raw_start: int | None
    raw_end: int | None
    supporting_facts: tuple[str, ...]
    null_margin: float
    score: float

    @classmethod
    def from_mapping(cls, value: object) -> "ReaderPrediction":
        row = _exact_object(
            value,
            {
                "schema",
                "identity",
                "window_id",
                "answer_type",
                "start_token",
                "end_token",
                "raw_start",
                "raw_end",
                "supporting_facts",
                "null_margin",
                "score",
            },
            label="reader prediction",
        )
        if row["schema"] != ABI_SCHEMA:
            raise ReaderValidationError("unsupported reader prediction schema")
        identity = ReaderIdentity.from_mapping(row["identity"])
        window_id = row["window_id"]
        if not _is_clean_string(window_id):
            raise ReaderValidationError("prediction window_id must be non-empty")
        answer_type = row["answer_type"]
        if not isinstance(answer_type, str) or answer_type not in SUPPORTED_ANSWER_TYPES:
            raise ReaderUnsupportedAnswerError(f"unsupported answer type: {answer_type}")
        start_token = None if row["start_token"] is None else _as_int(row["start_token"], label="start_token")
        end_token = None if row["end_token"] is None else _as_int(row["end_token"], label="end_token")
        raw_start = None if row["raw_start"] is None else _as_int(row["raw_start"], label="raw_start")
        raw_end = None if row["raw_end"] is None else _as_int(row["raw_end"], label="raw_end")
        supporting_value = row["supporting_facts"]
        if not isinstance(supporting_value, list) or len(supporting_value) > MAX_SUPPORTING_FACTS:
            raise ReaderValidationError("supporting_facts shape is invalid")
        supporting_facts = tuple(supporting_value)
        if any(not _is_clean_string(fact_id) for fact_id in supporting_facts):
            raise ReaderValidationError("supporting fact IDs must be exact strings")
        if len(set(supporting_facts)) != len(supporting_facts):
            raise ReaderValidationError("supporting fact IDs must be unique")
        return cls(
            row["schema"],
            identity,
            window_id,
            answer_type,
            start_token,
            end_token,
            raw_start,
            raw_end,
            supporting_facts,
            _as_finite_f32(row["null_margin"], label="null_margin"),
            _as_finite_f32(row["score"], label="score"),
        )

    def as_mapping(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "identity": self.identity.as_mapping(),
            "window_id": self.window_id,
            "answer_type": self.answer_type,
            "start_token": self.start_token,
            "end_token": self.end_token,
            "raw_start": self.raw_start,
            "raw_end": self.raw_end,
            "supporting_facts": list(self.supporting_facts),
            "null_margin": self.null_margin,
            "score": self.score,
        }


@dataclass(frozen=True)
class ReaderAnswer:
    answer_type: str
    answer: str | None
    raw_start: int | None
    raw_end: int | None
    supporting_facts: tuple[str, ...]
    null_margin: float
    window_id: str
    abstained: bool


@dataclass(frozen=True)
class ReaderLogits:
    """Finite model output for one reader window before host decoding."""

    schema: str
    identity: ReaderIdentity
    window_id: str
    start_logits: tuple[float, ...]
    end_logits: tuple[float, ...]
    answer_type_logits: dict[str, float]
    supporting_fact_logits: tuple[float, ...]
    null_logit: float

    @classmethod
    def from_mapping(cls, value: object) -> "ReaderLogits":
        row = _exact_object(
            value,
            {
                "schema",
                "identity",
                "window_id",
                "start_logits",
                "end_logits",
                "answer_type_logits",
                "supporting_fact_logits",
                "null_logit",
            },
            label="reader logits",
        )
        if row["schema"] != ABI_SCHEMA:
            raise ReaderValidationError("unsupported reader logits schema")
        answer_type_logits_value = _exact_object(
            row["answer_type_logits"], set(_ANSWER_TYPES), label="answer type logits"
        )
        window_id = row["window_id"]
        if not _is_clean_string(window_id):
            raise ReaderValidationError("logits window_id must be non-empty")
        start_logits = _finite_float_list(row["start_logits"], label="start_logits")
        end_logits = _finite_float_list(row["end_logits"], label="end_logits")
        supporting_fact_logits = _finite_float_list(
            row["supporting_fact_logits"], label="supporting_fact_logits"
        )
        return cls(
            row["schema"],
            ReaderIdentity.from_mapping(row["identity"]),
            row["window_id"],
            tuple(start_logits),
            tuple(end_logits),
            {
                key: _as_finite_f32(answer_type_logits_value[key], label=f"{key}_logit")
                for key in _ANSWER_TYPES
            },
            tuple(supporting_fact_logits),
            _as_finite_f32(row["null_logit"], label="null_logit"),
        )


def _finite_float_list(value: object, *, label: str) -> list[float]:
    if not isinstance(value, list):
        raise ReaderValidationError(f"{label} shape is invalid")
    return [_as_finite_f32(item, label=label) for item in value]


def validate_prediction(request: ReaderRequest, prediction: ReaderPrediction) -> ReaderPrediction:
    validate_request(request)
    if not isinstance(prediction, ReaderPrediction):
        raise ReaderValidationError("reader prediction type is invalid")
    if not isinstance(prediction.identity, ReaderIdentity):
        raise ReaderValidationError("reader prediction identity is invalid")
    request.identity.require_match(prediction.identity)
    if prediction.schema != ABI_SCHEMA:
        raise ReaderValidationError("unsupported reader prediction schema")
    if not _is_clean_string(prediction.window_id):
        raise ReaderValidationError("prediction window_id must be non-empty")
    if not isinstance(prediction.answer_type, str) or prediction.answer_type not in SUPPORTED_ANSWER_TYPES:
        raise ReaderUnsupportedAnswerError(f"unsupported answer type: {prediction.answer_type}")
    if not isinstance(prediction.supporting_facts, tuple) or len(prediction.supporting_facts) > MAX_SUPPORTING_FACTS:
        raise ReaderValidationError("supporting_facts shape is invalid")
    if any(not _is_clean_string(fact_id) for fact_id in prediction.supporting_facts):
        raise ReaderValidationError("supporting fact IDs must be exact strings")
    if len(set(prediction.supporting_facts)) != len(prediction.supporting_facts):
        raise ReaderValidationError("supporting fact IDs must be unique")
    for value, label in (
        (prediction.start_token, "start_token"),
        (prediction.end_token, "end_token"),
        (prediction.raw_start, "raw_start"),
        (prediction.raw_end, "raw_end"),
    ):
        if value is not None:
            _as_int(value, label=label)
    null_margin = _as_finite_f32(prediction.null_margin, label="null_margin")
    _as_finite_f32(prediction.score, label="score")
    windows = {window.window_id: window for window in request.windows}
    window = windows.get(prediction.window_id)
    if window is None:
        raise ReaderValidationError("prediction window_id is unknown")
    fact_ids = {fact.fact_id for fact in request.facts}
    if not set(prediction.supporting_facts).issubset(fact_ids):
        raise ReaderValidationError("prediction references an unknown supporting fact")
    is_null = prediction.answer_type == NULL_ANSWER_TYPE
    if not is_null and not prediction.supporting_facts:
        raise ReaderValidationError("non-null answers require supporting facts")
    if is_null != (null_margin >= _as_finite_f32(request.null_threshold, label="null_threshold")):
        raise ReaderValidationError("null margin and abstention decision disagree")
    if is_null:
        if any(value is not None for value in (prediction.start_token, prediction.end_token, prediction.raw_start, prediction.raw_end)):
            raise ReaderValidationError("abstentions must not contain span offsets")
        return prediction
    if prediction.answer_type in {"yes", "no"}:
        if any(value is not None for value in (prediction.start_token, prediction.end_token, prediction.raw_start, prediction.raw_end)):
            raise ReaderValidationError("yes/no answers must not contain span offsets")
        return prediction
    if prediction.answer_type != "span":
        raise ReaderUnsupportedAnswerError(f"unsupported answer type: {prediction.answer_type}")
    if prediction.start_token is None or prediction.end_token is None:
        raise ReaderValidationError("span answers require token offsets")
    if not 0 <= prediction.start_token < prediction.end_token <= len(window.tokens):
        raise ReaderValidationError("span token offsets have invalid shape")
    expected_start = window.tokens[prediction.start_token].raw_start
    expected_end = window.tokens[prediction.end_token - 1].raw_end
    if prediction.raw_start != expected_start or prediction.raw_end != expected_end:
        raise ReaderOffsetError("prediction raw offsets do not match token offsets")
    _validate_context_offsets(request.context, prediction.raw_start, prediction.raw_end, label="prediction span")
    return prediction


def decode_prediction(request: ReaderRequest, prediction: ReaderPrediction) -> ReaderAnswer:
    validate_prediction(request, prediction)
    if prediction.answer_type == NULL_ANSWER_TYPE:
        return ReaderAnswer(
            NULL_ANSWER_TYPE,
            None,
            None,
            None,
            prediction.supporting_facts,
            prediction.null_margin,
            prediction.window_id,
            True,
        )
    if prediction.answer_type in {"yes", "no"}:
        return ReaderAnswer(
            prediction.answer_type,
            prediction.answer_type,
            None,
            None,
            prediction.supporting_facts,
            prediction.null_margin,
            prediction.window_id,
            False,
        )
    context_bytes = request.context.encode("utf-8")
    answer = context_bytes[prediction.raw_start : prediction.raw_end].decode("utf-8")
    return ReaderAnswer(
        "span",
        answer,
        prediction.raw_start,
        prediction.raw_end,
        prediction.supporting_facts,
        prediction.null_margin,
        prediction.window_id,
        False,
    )


def select_prediction(request: ReaderRequest, predictions: Iterable[ReaderPrediction]) -> ReaderAnswer:
    """Validate all windows and choose one deterministic answer."""

    validate_request(request)
    rows: list[ReaderPrediction] = []
    seen_window_ids: set[str] = set()
    for prediction in predictions:
        validate_prediction(request, prediction)
        if prediction.window_id in seen_window_ids:
            raise ReaderValidationError("reader prediction windows must be unique")
        if len(rows) >= len(request.windows):
            raise ReaderValidationError("reader predictions exceed the window limit")
        seen_window_ids.add(prediction.window_id)
        rows.append(prediction)
    if not rows:
        raise ReaderValidationError("reader predictions must be non-empty")
    selected = max(
        rows,
        key=lambda row: (
            _as_finite_f32(row.score, label="score"),
            0 if row.answer_type == NULL_ANSWER_TYPE else 1,
            -_as_finite_f32(row.null_margin, label="null_margin"),
            row.window_id,
        ),
    )
    return decode_prediction(request, selected)


def decode_logits(request: ReaderRequest, logits: ReaderLogits) -> ReaderPrediction:
    """Decode one finite window tensor into a source-bound prediction."""

    validate_request(request)
    if not isinstance(logits, ReaderLogits):
        raise ReaderValidationError("reader logits type is invalid")
    if not isinstance(logits.identity, ReaderIdentity):
        raise ReaderValidationError("reader logits identity is invalid")
    request.identity.require_match(logits.identity)
    if logits.schema != ABI_SCHEMA:
        raise ReaderValidationError("unsupported reader logits schema")
    if not _is_clean_string(logits.window_id):
        raise ReaderValidationError("logits window_id must be non-empty")
    if not isinstance(logits.answer_type_logits, dict) or set(logits.answer_type_logits) != set(_ANSWER_TYPES):
        raise ReaderValidationError("answer type logits shape is invalid")
    if not all(isinstance(values, (tuple, list)) for values in (logits.start_logits, logits.end_logits, logits.supporting_fact_logits)):
        raise ReaderValidationError("reader logits shape is invalid")
    windows = {window.window_id: window for window in request.windows}
    window = windows.get(logits.window_id)
    if window is None:
        raise ReaderValidationError("logits window_id is unknown")
    if len(logits.start_logits) != len(window.tokens) or len(logits.end_logits) != len(window.tokens):
        raise ReaderValidationError("reader logits shape is invalid")
    if len(logits.supporting_fact_logits) != len(request.facts):
        raise ReaderValidationError("supporting_fact_logits shape is invalid")
    start_logits = tuple(
        _as_finite_f32(value, label="start_logits") for value in logits.start_logits
    )
    end_logits = tuple(
        _as_finite_f32(value, label="end_logits") for value in logits.end_logits
    )
    supporting_fact_logits = tuple(
        _as_finite_f32(value, label="supporting_fact_logits")
        for value in logits.supporting_fact_logits
    )
    answer_type_logits = {
        answer_type: _as_finite_f32(
            logits.answer_type_logits[answer_type], label=f"{answer_type}_logit"
        )
        for answer_type in _ANSWER_TYPES
    }
    null_logit = _as_finite_f32(logits.null_logit, label="null_logit")
    best_start, best_end, best_span_score = 0, 0, float("-inf")
    for start, start_score in enumerate(start_logits):
        for end in range(start, len(end_logits)):
            score = _as_finite_f32(
                start_score + end_logits[end], label="span score"
            )
            if score > best_span_score or (score == best_span_score and (start, end) < (best_start, best_end)):
                best_start, best_end, best_span_score = start, end, score
    span_score = _as_finite_f32(
        answer_type_logits["span"] + best_span_score, label="span score"
    )
    type_scores = {
        "span": span_score,
        "yes": answer_type_logits["yes"],
        "no": answer_type_logits["no"],
    }
    best_type = max(_ANSWER_TYPES, key=lambda answer_type: type_scores[answer_type])
    best_non_null = type_scores[best_type]
    null_margin = _as_finite_f32(null_logit - best_non_null, label="null margin")
    answer_type = (
        NULL_ANSWER_TYPE
        if null_margin >= _as_finite_f32(request.null_threshold, label="null_threshold")
        else best_type
    )
    if answer_type == "span":
        start_token = best_start
        end_token = best_end + 1
        raw_start = window.tokens[start_token].raw_start
        raw_end = window.tokens[best_end].raw_end
    else:
        start_token = end_token = raw_start = raw_end = None
    prediction = ReaderPrediction(
        ABI_SCHEMA,
        request.identity,
        logits.window_id,
        answer_type,
        start_token,
        end_token,
        raw_start,
        raw_end,
        tuple(
            fact.fact_id
            for fact, score in zip(request.facts, supporting_fact_logits)
            if score > 0.0
        ),
        null_margin,
        best_non_null,
    )
    if len(prediction.supporting_facts) > MAX_SUPPORTING_FACTS:
        raise ReaderValidationError("supporting_facts shape is invalid")
    validate_prediction(request, prediction)
    return prediction


def receipt_digest(receipt: dict[str, Any]) -> str:
    if not isinstance(receipt, dict):
        raise ReaderFixtureValidationError("receipt must be an object")
    return _sha256(_without_field(receipt, "receipt_sha256"))


def fixture_digest(fixture: dict[str, Any]) -> str:
    if not isinstance(fixture, dict):
        raise ReaderFixtureValidationError("fixture must be an object")
    return _sha256(_without_field(fixture, "fixture_sha256"))


def _check_deadline(deadline: float | None) -> None:
    if deadline is None:
        return
    if isinstance(deadline, bool) or not isinstance(deadline, (int, float)):
        raise ReaderTimeoutError("reader deadline must be finite")
    if not math.isfinite(float(deadline)):
        raise ReaderTimeoutError("reader deadline must be finite")
    if time.monotonic() >= deadline:
        raise ReaderTimeoutError("reader validation timed out")


def validate_bakeoff_receipt(
    document: object,
    *,
    expected_candidate_id: str | None = None,
    expected_identity: ReaderIdentity | None = None,
) -> dict[str, Any]:
    receipt = _exact_object(
        document,
        {
            "schema",
            "candidate_id",
            "split",
            "identity",
            "identity_sha256",
            "artifact_custody",
            "status",
            "unmeasured",
            "receipt_sha256",
        },
        label="receipt",
    )
    if receipt["schema"] != BAKEOFF_RECEIPT_SCHEMA:
        raise ReaderFixtureValidationError("unsupported reader receipt schema")
    candidate_id = receipt["candidate_id"]
    if not _is_clean_string(candidate_id):
        raise ReaderFixtureValidationError("receipt candidate_id must be non-empty")
    if expected_candidate_id is not None and candidate_id != expected_candidate_id:
        raise ReaderFixtureValidationError("receipt candidate identity mismatch")
    if receipt["split"] != SELECTION_SPLIT:
        raise ReaderFixtureValidationError("reader receipt must be TRAIN-only")
    identity = ReaderIdentity.from_mapping(receipt["identity"])
    if expected_identity is not None:
        identity.require_match(expected_identity)
    if receipt["identity_sha256"] != identity_digest(identity):
        raise ReaderFixtureValidationError("receipt identity digest mismatch")
    if receipt["artifact_custody"] != ARTIFACT_CUSTODY:
        raise ReaderFixtureValidationError("receipt artifact custody must be synthetic-only")
    if receipt["status"] != "unmeasured":
        raise ReaderFixtureValidationError("synthetic reader receipt must remain unmeasured")
    if receipt["unmeasured"] != list(_UNMEASURED_RECEIPT_FIELDS):
        raise ReaderFixtureValidationError("receipt must enumerate all unmeasured fields")
    digest = receipt["receipt_sha256"]
    if not _is_digest(digest) or digest != receipt_digest(receipt):
        raise ReaderFixtureValidationError("reader receipt digest mismatch")
    return receipt


def _case_request(fixture_identity: ReaderIdentity, case: dict[str, Any]) -> ReaderRequest:
    context = case["context"]
    windows = build_windows(context)
    request_mapping = {
        "schema": ABI_SCHEMA,
        "identity": fixture_identity.as_mapping(),
        "query": case["query"],
        "context": context,
        "facts": case["facts"],
        "windows": [window.as_mapping() for window in windows],
        "null_threshold": case["null_threshold"],
    }
    request = ReaderRequest.from_mapping(request_mapping)
    if case["window_count"] != len(windows):
        raise ReaderFixtureValidationError(f"case {case['id']} window count drift")
    return request


def _expected_prediction(request: ReaderRequest, case: dict[str, Any]) -> ReaderPrediction:
    expected = _exact_object(
        case["expected"],
        {
            "answer_type",
            "window_id",
            "start_token",
            "end_token",
            "supporting_facts",
            "null_margin",
            "score",
        },
        label=f"case {case['id']} expected answer",
    )
    window_ids = {window.window_id for window in request.windows}
    if expected["window_id"] not in window_ids:
        raise ReaderFixtureValidationError(f"case {case['id']} expected unknown window")
    window = next(window for window in request.windows if window.window_id == expected["window_id"])
    start_token = expected["start_token"]
    end_token = expected["end_token"]
    raw_start = raw_end = None
    if expected["answer_type"] == "span":
        if isinstance(start_token, bool) or not isinstance(start_token, int) or isinstance(end_token, bool) or not isinstance(end_token, int):
            raise ReaderFixtureValidationError(f"case {case['id']} span token shape is invalid")
        if not 0 <= start_token < end_token <= len(window.tokens):
            raise ReaderFixtureValidationError(f"case {case['id']} span token range is invalid")
        raw_start = window.tokens[start_token].raw_start
        raw_end = window.tokens[end_token - 1].raw_end
    elif start_token is not None or end_token is not None:
        raise ReaderFixtureValidationError(f"case {case['id']} non-span answer has offsets")
    return ReaderPrediction(
        ABI_SCHEMA,
        request.identity,
        expected["window_id"],
        expected["answer_type"],
        start_token,
        end_token,
        raw_start,
        raw_end,
        tuple(expected["supporting_facts"]),
        _as_finite(expected["null_margin"], label="case null_margin"),
        _as_finite(expected["score"], label="case score"),
    )


def validate_selection_fixture(document: object, *, deadline: float | None = None) -> dict[str, Any]:
    """Validate source-owned synthetic cases and deterministic selection."""

    _check_deadline(deadline)
    fixture = _exact_object(
        document,
        {
            "schema",
            "split",
            "source",
            "fixture_status",
            "artifact_custody",
            "identity",
            "identity_sha256",
            "cases",
            "variants",
            "selection",
            "fixture_sha256",
        },
        label="reader selection fixture",
    )
    if fixture["schema"] != SELECTION_FIXTURE_SCHEMA:
        raise ReaderFixtureValidationError("unsupported reader fixture schema")
    if fixture["split"] != SELECTION_SPLIT:
        raise ReaderFixtureValidationError("reader fixture must be TRAIN-only")
    if fixture["source"] != "source-owned":
        raise ReaderFixtureValidationError("reader fixture source must be source-owned")
    if fixture["fixture_status"] != SELECTION_FIXTURE_STATUS:
        raise ReaderFixtureValidationError("reader fixture must remain unmeasured")
    if fixture["artifact_custody"] != ARTIFACT_CUSTODY:
        raise ReaderFixtureValidationError("reader fixture artifact custody must be synthetic-only")
    identity = ReaderIdentity.from_mapping(fixture["identity"])
    if fixture["identity_sha256"] != identity_digest(identity):
        raise ReaderFixtureValidationError("reader fixture identity digest mismatch")
    cases_value = fixture["cases"]
    if not isinstance(cases_value, list) or not cases_value or len(cases_value) > 24:
        raise ReaderFixtureValidationError("reader fixture cases must be bounded and non-empty")
    case_ids: set[str] = set()
    cases: list[tuple[str, ReaderRequest, ReaderPrediction]] = []
    for case in cases_value:
        _check_deadline(deadline)
        parsed = _exact_object(
            case,
            {"id", "query", "context", "facts", "window_count", "null_threshold", "expected"},
            label="reader fixture case",
        )
        case_id = parsed["id"]
        if not _is_clean_string(case_id) or case_id in case_ids:
            raise ReaderFixtureValidationError("reader fixture case IDs must be unique")
        case_ids.add(case_id)
        if parsed["query"] != parsed["query"].strip() or not _is_clean_string(parsed["query"], max_chars=MAX_QUERY_CHARS):
            raise ReaderFixtureValidationError(f"case {case_id} query is invalid")
        request = _case_request(identity, parsed)
        prediction = _expected_prediction(request, parsed)
        validate_prediction(request, prediction)
        cases.append((case_id, request, prediction))

    variants_value = fixture["variants"]
    if (
        not isinstance(variants_value, list)
        or not variants_value
        or len(variants_value) > MAX_FIXTURE_VARIANTS
    ):
        raise ReaderFixtureValidationError("reader fixture variants must be non-empty")
    variant_ids: set[str] = set()
    variant_scores: list[tuple[str, list[float]]] = []
    for variant_index, variant in enumerate(variants_value):
        _check_deadline(deadline)
        parsed_variant = _exact_object(
            variant,
            {"id", "identity", "receipt", "case_scores"},
            label=f"reader variant {variant_index}",
        )
        variant_id = parsed_variant["id"]
        if not _is_clean_string(variant_id) or variant_id in variant_ids:
            raise ReaderFixtureValidationError("reader variant IDs must be unique")
        variant_ids.add(variant_id)
        variant_identity = ReaderIdentity.from_mapping(parsed_variant["identity"])
        validate_bakeoff_receipt(
            parsed_variant["receipt"],
            expected_candidate_id=variant_id,
            expected_identity=variant_identity,
        )
        if variant_identity.preprocessing_id != identity.preprocessing_id or variant_identity.preprocessing_sha256 != identity.preprocessing_sha256:
            raise ReaderFixtureValidationError("reader preprocessing identity drift")
        scores = parsed_variant["case_scores"]
        if not isinstance(scores, list) or len(scores) != len(cases):
            raise ReaderFixtureValidationError(f"variant {variant_id} case score shape is invalid")
        parsed_scores = [_as_finite(score, label=f"variant {variant_id} case score") for score in scores]
        variant_scores.append((variant_id, parsed_scores))

    selection = _exact_object(
        fixture["selection"],
        {"method", "expected_candidate_id"},
        label="reader selection",
    )
    if selection["method"] != "mean_score_then_id_v1":
        raise ReaderFixtureValidationError("unsupported reader selection method")
    selected = min(variant_scores, key=lambda item: (-math.fsum(item[1]) / len(item[1]), item[0]))[0]
    if selection["expected_candidate_id"] != selected:
        raise ReaderFixtureValidationError("reader selection result mismatch")
    digest = fixture["fixture_sha256"]
    if not _is_digest(digest) or digest != fixture_digest(fixture):
        raise ReaderFixtureValidationError("reader fixture digest mismatch")
    return fixture


def parse_selection_fixture(payload: str | bytes | bytearray) -> dict[str, Any]:
    if isinstance(payload, str):
        raw_payload = payload.encode("utf-8")
    elif isinstance(payload, (bytes, bytearray)):
        raw_payload = bytes(payload)
    else:
        raise ReaderFixtureValidationError("payload must be JSON text or bytes")
    if len(raw_payload) > MAX_FIXTURE_BYTES:
        raise ReaderFixtureValidationError("reader fixture exceeds the byte limit")
    return validate_selection_fixture(_parse_json(raw_payload))


def parse_request(payload: str | bytes | bytearray) -> ReaderRequest:
    if isinstance(payload, str):
        raw_payload = payload.encode("utf-8")
    elif isinstance(payload, (bytes, bytearray)):
        raw_payload = bytes(payload)
    else:
        raise ReaderValidationError("payload must be JSON text or bytes")
    if len(raw_payload) > MAX_REQUEST_BYTES:
        raise ReaderValidationError("reader request exceeds the byte limit")
    return ReaderRequest.from_mapping(_parse_json(raw_payload))


def load_selection_fixture(path: str | Path = SELECTION_FIXTURE_PATH) -> dict[str, Any]:
    fixture_path = Path(path)
    try:
        if fixture_path.stat().st_size > MAX_FIXTURE_BYTES:
            raise ReaderFixtureValidationError("reader fixture exceeds the byte limit")
        payload = fixture_path.read_bytes()
    except ReaderFixtureValidationError:
        raise
    except (OSError, UnicodeError) as exc:
        raise ReaderFixtureValidationError(f"cannot read reader fixture {path}") from exc
    return parse_selection_fixture(payload)


def run_synthetic_bakeoff(
    document: object,
    *,
    deadline: float | None = None,
    timeout_ms: float | None = None,
) -> str:
    if timeout_ms is not None:
        if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, (int, float)):
            raise ReaderTimeoutError("timeout_ms must be a positive finite number")
        if not math.isfinite(float(timeout_ms)) or timeout_ms <= 0:
            raise ReaderTimeoutError("timeout_ms must be a positive finite number")
        deadline = min(deadline, time.monotonic() + timeout_ms / 1000) if deadline is not None else time.monotonic() + timeout_ms / 1000
    fixture = validate_selection_fixture(document, deadline=deadline)
    return fixture["selection"]["expected_candidate_id"]


def select_synthetic_reader(document: object, *, deadline: float | None = None) -> str:
    return run_synthetic_bakeoff(document, deadline=deadline)


validate_receipt = validate_bakeoff_receipt
validate_reader_fixture = validate_selection_fixture
