"""Strict, model-free mirror of the versioned embedder ABI."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

ABI = "mnemosyne.embedder.v1"
ABI_VERSION = 1
NATIVE_DIMENSIONS = 768
PADDED_DIMENSIONS = 1024
IDENTITY_FIELDS = frozenset({"artifact", "tokenizer", "preprocessing", "model_space"})
SPACES = frozenset({"native_768", "padded_1024"})


class EmbedderValidationError(ValueError):
    """An embedder request, response, identity, or vector is invalid."""


@dataclass(frozen=True)
class EmbedderIdentity:
    artifact: str
    tokenizer: str
    preprocessing: str
    model_space: str

    @classmethod
    def from_mapping(cls, value: object) -> "EmbedderIdentity":
        if not isinstance(value, dict) or set(value) != IDENTITY_FIELDS:
            raise EmbedderValidationError("identity fields must be exact")
        fields = {field: value[field] for field in IDENTITY_FIELDS}
        if any(
            not isinstance(item, str)
            or not item
            or item != item.strip()
            or any(ord(character) < 32 or ord(character) == 127 for character in item)
            for item in fields.values()
        ):
            raise EmbedderValidationError("identity values must be exact non-empty strings")
        return cls(**fields)

    def as_mapping(self) -> dict[str, str]:
        return {
            "artifact": self.artifact,
            "tokenizer": self.tokenizer,
            "preprocessing": self.preprocessing,
            "model_space": self.model_space,
        }

    def require_match(self, expected: "EmbedderIdentity") -> None:
        if self != expected:
            for field in IDENTITY_FIELDS:
                if getattr(self, field) != getattr(expected, field):
                    raise EmbedderValidationError(f"identity mismatch: {field}")
            raise EmbedderValidationError("identity mismatch")


@dataclass(frozen=True)
class EmbedRequest:
    abi_version: int
    identity: EmbedderIdentity
    inputs: tuple[str, ...]
    space: str


@dataclass(frozen=True)
class EmbedResponse:
    abi_version: int
    identity: EmbedderIdentity
    vectors: tuple[tuple[float, ...], ...]
    space: str


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise EmbedderValidationError(f"duplicate key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_json(value: str) -> None:
    raise EmbedderValidationError(f"unsupported JSON constant: {value}")


def _parse_json(payload: str | bytes | bytearray) -> object:
    if not isinstance(payload, (str, bytes, bytearray)):
        raise EmbedderValidationError("payload must be JSON text or bytes")
    try:
        return json.loads(
            payload,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_json,
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise EmbedderValidationError("payload must be valid JSON") from exc


def _validate_version(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value != ABI_VERSION:
        raise EmbedderValidationError("unsupported ABI version")
    return value


def _validate_space(value: object) -> str:
    if not isinstance(value, str) or value not in SPACES:
        raise EmbedderValidationError("unsupported embedding space")
    return value


def _validate_input(value: object, index: int) -> str:
    if not isinstance(value, str) or any(character in value for character in "\r\n\t"):
        raise EmbedderValidationError(f"invalid input at index {index}")
    return value


def validate_request(document: object, expected: EmbedderIdentity) -> EmbedRequest:
    """Validate a decoded request against custody and the exact v1 schema."""
    if not isinstance(document, dict) or set(document) != {
        "abi_version",
        "identity",
        "inputs",
        "space",
    }:
        raise EmbedderValidationError("request fields must be exact")
    identity = EmbedderIdentity.from_mapping(document["identity"])
    identity.require_match(expected)
    inputs = document["inputs"]
    if not isinstance(inputs, list) or not inputs:
        raise EmbedderValidationError("inputs must be a non-empty array")
    parsed_inputs = tuple(_validate_input(item, index) for index, item in enumerate(inputs))
    return EmbedRequest(
        abi_version=_validate_version(document["abi_version"]),
        identity=identity,
        inputs=parsed_inputs,
        space=_validate_space(document["space"]),
    )


def _dimensions(space: str) -> int:
    return NATIVE_DIMENSIONS if space == "native_768" else PADDED_DIMENSIONS


def validate_vector(vector: object, space: str, *, index: int = 0) -> tuple[float, ...]:
    """Validate finite, nonzero vectors and enforce zero-padding custody."""
    if not isinstance(vector, (list, tuple)):
        raise EmbedderValidationError(f"vector {index} must be an array")
    expected = _dimensions(space)
    if len(vector) != expected:
        raise EmbedderValidationError(f"vector {index} has wrong dimensions")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in vector):
        raise EmbedderValidationError(f"vector {index} contains a non-number")
    parsed = tuple(float(value) for value in vector)
    if any(not math.isfinite(value) for value in parsed):
        raise EmbedderValidationError(f"vector {index} is non-finite")
    if not any(value != 0.0 for value in parsed):
        raise EmbedderValidationError(f"vector {index} is zero")
    if space == "padded_1024" and any(value != 0.0 for value in parsed[NATIVE_DIMENSIONS:]):
        raise EmbedderValidationError(f"vector {index} is not zero-padded")
    return parsed


def validate_response(
    document: object,
    request: EmbedRequest,
    expected: EmbedderIdentity,
) -> EmbedResponse:
    """Validate response identity, dimensions, count, and every vector."""
    if not isinstance(document, dict) or set(document) != {
        "abi_version",
        "identity",
        "vectors",
        "space",
    }:
        raise EmbedderValidationError("response fields must be exact")
    identity = EmbedderIdentity.from_mapping(document["identity"])
    identity.require_match(expected)
    space = _validate_space(document["space"])
    if space != request.space:
        raise EmbedderValidationError("response space mismatch")
    vectors = document["vectors"]
    if not isinstance(vectors, list) or len(vectors) != len(request.inputs):
        raise EmbedderValidationError("response vector count mismatch")
    parsed_vectors = tuple(
        validate_vector(vector, space, index=index) for index, vector in enumerate(vectors)
    )
    return EmbedResponse(
        abi_version=_validate_version(document["abi_version"]),
        identity=identity,
        vectors=parsed_vectors,
        space=space,
    )


def parse_request(payload: str | bytes | bytearray, expected: EmbedderIdentity) -> EmbedRequest:
    return validate_request(_parse_json(payload), expected)


def parse_response(
    payload: str | bytes | bytearray,
    request: EmbedRequest,
    expected: EmbedderIdentity,
) -> EmbedResponse:
    return validate_response(_parse_json(payload), request, expected)


def pad_native_to_1024(vector: object) -> tuple[float, ...]:
    native = validate_vector(vector, "native_768")
    return native + (0.0,) * (PADDED_DIMENSIONS - NATIVE_DIMENSIONS)


def cosine_similarity(left: object, right: object) -> float:
    if not isinstance(left, (list, tuple)) or not isinstance(right, (list, tuple)):
        raise EmbedderValidationError("cosine operands must be vectors")
    if len(left) != len(right):
        raise EmbedderValidationError("cosine dimensions must match")
    space = "native_768" if len(left) == NATIVE_DIMENSIONS else "padded_1024"
    left_values = validate_vector(left, space)
    right_values = validate_vector(right, space)
    dot = math.fsum(a * b for a, b in zip(left_values, right_values, strict=True))
    left_norm = math.sqrt(math.fsum(value * value for value in left_values))
    right_norm = math.sqrt(math.fsum(value * value for value in right_values))
    return dot / (left_norm * right_norm)


def rank_by_cosine(
    query: object,
    candidates: list[tuple[str, object]],
    *,
    limit: int | None = None,
) -> list[str]:
    """Rank by cosine, breaking equal scores by candidate ID."""
    if limit == 0 or (limit is not None and limit < 0):
        raise EmbedderValidationError("rank limit must be greater than zero")
    if not isinstance(query, (list, tuple)):
        raise EmbedderValidationError("query must be a vector")
    space = "native_768" if len(query) == NATIVE_DIMENSIONS else "padded_1024"
    query_values = validate_vector(query, space)
    seen: set[str] = set()
    scored: list[tuple[str, float]] = []
    for candidate_id, vector in candidates:
        if not isinstance(candidate_id, str) or not candidate_id:
            raise EmbedderValidationError("candidate IDs must be non-empty strings")
        if candidate_id in seen:
            raise EmbedderValidationError("candidate IDs must be unique")
        seen.add(candidate_id)
        scored.append((candidate_id, cosine_similarity(query_values, vector)))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return [candidate_id for candidate_id, _ in scored[:limit]]
