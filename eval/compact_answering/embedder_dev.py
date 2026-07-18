"""Strict, model-free mirror of the versioned embedder ABI."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ABI = "mnemosyne.embedder.v1"
ABI_VERSION = 1
NATIVE_DIMENSIONS = 768
PADDED_DIMENSIONS = 1024
IDENTITY_FIELDS = frozenset({"artifact", "tokenizer", "preprocessing", "model_space"})
SPACES = frozenset({"native_768", "padded_1024"})
SELECTION_FIXTURE_SCHEMA = "mnemosyne.embedder-selection-fixture.v1"
BAKEOFF_RECEIPT_SCHEMA = "mnemosyne.embedder-bakeoff-receipt.v1"
SELECTION_FIXTURE_STATUS = "synthetic-unmeasured"
SELECTION_SPLIT = "TRAIN"
SELECTION_FIXTURE_PATH = (
    Path(__file__).with_name("fixtures") / "embedder-selection-dev.json"
)
_DIGEST_HEX_LENGTH = 64
_UNMEASURED_RECEIPT_FIELDS = (
    "artifact_bytes",
    "quality",
    "latency_ms",
    "peak_memory_mib",
    "resource_envelope",
)


class EmbedderValidationError(ValueError):
    """An embedder request, response, identity, or vector is invalid."""


class EmbedderSelectionValidationError(EmbedderValidationError):
    """A synthetic TRAIN-only selection fixture or receipt is invalid."""


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
        raise EmbedderSelectionValidationError("document is not canonical JSON") from exc
    return (encoded + "\n").encode("utf-8")


def _sha256(document: object) -> str:
    return hashlib.sha256(_canonical_bytes(document)).hexdigest()


def _without_field(document: dict[str, Any], field: str) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key != field}


def _validate_digest(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _DIGEST_HEX_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise EmbedderSelectionValidationError(
            f"{field} must be {_DIGEST_HEX_LENGTH} lowercase hex characters"
        )
    return value


def identity_digest(identity: EmbedderIdentity | dict[str, object]) -> str:
    """Return the canonical digest for an exact embedder identity mapping."""
    parsed = identity if isinstance(identity, EmbedderIdentity) else EmbedderIdentity.from_mapping(identity)
    return _sha256(parsed.as_mapping())


def receipt_digest(receipt: dict[str, Any]) -> str:
    """Return the digest over a receipt excluding its self-authenticating field."""
    if not isinstance(receipt, dict):
        raise EmbedderSelectionValidationError("receipt must be an object")
    return _sha256(_without_field(receipt, "receipt_sha256"))


def fixture_digest(fixture: dict[str, Any]) -> str:
    """Return the digest over a fixture excluding its self-authenticating field."""
    if not isinstance(fixture, dict):
        raise EmbedderSelectionValidationError("fixture must be an object")
    return _sha256(_without_field(fixture, "fixture_sha256"))


def _selection_error(message: str) -> EmbedderSelectionValidationError:
    return EmbedderSelectionValidationError(message)


def _validate_exact_object(value: object, fields: set[str], *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise _selection_error(f"{label} fields must be exact")
    return value


def _validate_sparse_vector(value: object, space: str, *, label: str) -> tuple[float, ...]:
    sparse = _validate_exact_object(
        value,
        {"dimensions", "coordinates"},
        label=label,
    )
    dimensions = sparse["dimensions"]
    expected_dimensions = _dimensions(space)
    if (
        not isinstance(dimensions, int)
        or isinstance(dimensions, bool)
        or dimensions != expected_dimensions
    ):
        raise _selection_error(f"{label} dimensions do not match {space}")
    coordinates = sparse["coordinates"]
    if not isinstance(coordinates, list) or not coordinates:
        raise _selection_error(f"{label} coordinates must be non-empty")
    vector = [0.0] * dimensions
    previous_index = -1
    for coordinate_index, coordinate in enumerate(coordinates):
        if not isinstance(coordinate, list) or len(coordinate) != 2:
            raise _selection_error(f"{label} coordinate {coordinate_index} is malformed")
        index, raw_value = coordinate
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or index < 0
            or index >= dimensions
            or index <= previous_index
        ):
            raise _selection_error(f"{label} coordinate indexes must be sorted and in range")
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            raise _selection_error(f"{label} coordinate {coordinate_index} is not numeric")
        try:
            numeric_value = float(raw_value)
        except (OverflowError, ValueError) as exc:
            raise _selection_error(f"{label} coordinate {coordinate_index} is invalid") from exc
        if not math.isfinite(numeric_value):
            raise _selection_error(f"{label} coordinate {coordinate_index} is non-finite")
        vector[index] = numeric_value
        previous_index = index
    try:
        return validate_vector(vector, space)
    except EmbedderValidationError as exc:
        raise _selection_error(f"{label}: {exc}") from exc


def _validate_space_vectors(value: object, *, label: str) -> dict[str, tuple[float, ...]]:
    vectors = _validate_exact_object(value, set(SPACES), label=label)
    return {
        space: _validate_sparse_vector(vectors[space], space, label=f"{label}.{space}")
        for space in sorted(SPACES)
    }


def validate_bakeoff_receipt(
    document: object,
    *,
    expected_candidate_id: str | None = None,
    expected_identity: EmbedderIdentity | None = None,
) -> dict[str, Any]:
    """Validate a self-digest, synthetic-only, TRAIN bakeoff receipt."""
    receipt = _validate_exact_object(
        document,
        {
            "schema",
            "candidate_id",
            "split",
            "identity",
            "identity_sha256",
            "artifact_custody",
            "artifact_sha256",
            "status",
            "dimensions",
            "unmeasured",
            "parity",
            "receipt_sha256",
        },
        label="receipt",
    )
    if receipt["schema"] != BAKEOFF_RECEIPT_SCHEMA:
        raise _selection_error("unsupported bakeoff receipt schema")
    candidate_id = receipt["candidate_id"]
    if (
        not isinstance(candidate_id, str)
        or not candidate_id
        or candidate_id != candidate_id.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in candidate_id)
    ):
        raise _selection_error("receipt candidate_id must be an exact non-empty string")
    if expected_candidate_id is not None and candidate_id != expected_candidate_id:
        raise _selection_error("receipt candidate identity mismatch")
    if receipt["split"] != SELECTION_SPLIT:
        raise _selection_error("bakeoff receipt must be TRAIN-only")
    identity = EmbedderIdentity.from_mapping(receipt["identity"])
    if expected_identity is not None:
        try:
            identity.require_match(expected_identity)
        except EmbedderValidationError as exc:
            raise _selection_error(str(exc)) from exc
    identity_hash = _validate_digest(receipt["identity_sha256"], field="identity_sha256")
    if identity_hash != identity_digest(identity):
        raise _selection_error("receipt identity digest mismatch")
    if receipt["artifact_custody"] != "synthetic-fixture-no-artifact":
        raise _selection_error("receipt artifact custody must be synthetic-only")
    if receipt["artifact_sha256"] is not None:
        raise _selection_error("synthetic receipt cannot contain an artifact digest")
    if receipt["status"] != "unmeasured":
        raise _selection_error("synthetic receipt must remain unmeasured")
    dimensions = receipt["dimensions"]
    if dimensions != {"native_768": NATIVE_DIMENSIONS, "padded_1024": PADDED_DIMENSIONS}:
        raise _selection_error("receipt dimensions do not match the embedder ABI")
    unmeasured = receipt["unmeasured"]
    if unmeasured != list(_UNMEASURED_RECEIPT_FIELDS):
        raise _selection_error("receipt must enumerate all unmeasured fields")
    parity = _validate_exact_object(receipt["parity"], {"cosine", "ranking"}, label="receipt parity")
    if parity != {"cosine": True, "ranking": True}:
        raise _selection_error("receipt parity must be explicitly true")
    digest = _validate_digest(receipt["receipt_sha256"], field="receipt_sha256")
    if digest != receipt_digest(receipt):
        raise _selection_error("receipt digest mismatch")
    return receipt


def _mean_cosine_scores(
    probe_scores: list[dict[str, float]], candidate_ids: list[str]
) -> dict[str, float]:
    if not probe_scores:
        raise _selection_error("at least one probe is required")
    return {
        candidate_id: math.fsum(scores[candidate_id] for scores in probe_scores) / len(probe_scores)
        for candidate_id in candidate_ids
    }


def validate_selection_fixture(document: object) -> dict[str, Any]:
    """Validate source-owned synthetic receipts, vectors, parity, and selection."""
    fixture = _validate_exact_object(
        document,
        {
            "schema",
            "split",
            "source",
            "fixture_status",
            "dimensions",
            "candidates",
            "probes",
            "selection",
            "fixture_sha256",
        },
        label="selection fixture",
    )
    if fixture["schema"] != SELECTION_FIXTURE_SCHEMA:
        raise _selection_error("unsupported selection fixture schema")
    if fixture["split"] != SELECTION_SPLIT:
        raise _selection_error("embedder selection fixture must be TRAIN-only")
    if fixture["source"] != "source-owned":
        raise _selection_error("selection fixture source must be source-owned")
    if fixture["fixture_status"] != SELECTION_FIXTURE_STATUS:
        raise _selection_error("selection fixture must be explicitly unmeasured")
    if fixture["dimensions"] != {"native_768": NATIVE_DIMENSIONS, "padded_1024": PADDED_DIMENSIONS}:
        raise _selection_error("selection fixture dimensions do not match the ABI")
    candidates = fixture["candidates"]
    if not isinstance(candidates, list) or not candidates:
        raise _selection_error("selection fixture candidates must be non-empty")
    candidate_ids: list[str] = []
    for candidate_index, candidate in enumerate(candidates):
        parsed_candidate = _validate_exact_object(
            candidate,
            {"id", "identity", "receipt"},
            label=f"candidate {candidate_index}",
        )
        candidate_id = parsed_candidate["id"]
        if (
            not isinstance(candidate_id, str)
            or not candidate_id
            or candidate_id != candidate_id.strip()
            or any(ord(character) < 32 or ord(character) == 127 for character in candidate_id)
        ):
            raise _selection_error("candidate IDs must be exact non-empty strings")
        if candidate_id in candidate_ids:
            raise _selection_error("candidate IDs must be unique")
        identity = EmbedderIdentity.from_mapping(parsed_candidate["identity"])
        validate_bakeoff_receipt(
            parsed_candidate["receipt"],
            expected_candidate_id=candidate_id,
            expected_identity=identity,
        )
        candidate_ids.append(candidate_id)

    probes = fixture["probes"]
    if not isinstance(probes, list) or not probes:
        raise _selection_error("selection fixture probes must be non-empty")
    probe_ids: set[str] = set()
    probe_scores: list[dict[str, float]] = []
    for probe_index, probe in enumerate(probes):
        parsed_probe = _validate_exact_object(
            probe,
            {"id", "query", "vectors", "expected_native_ranking", "expected_padded_ranking"},
            label=f"probe {probe_index}",
        )
        probe_id = parsed_probe["id"]
        if not isinstance(probe_id, str) or not probe_id or probe_id in probe_ids:
            raise _selection_error("probe IDs must be unique non-empty strings")
        probe_ids.add(probe_id)
        query_vectors = _validate_space_vectors(parsed_probe["query"], label=f"probe {probe_id} query")
        vectors = parsed_probe["vectors"]
        if not isinstance(vectors, dict) or set(vectors) != set(candidate_ids):
            raise _selection_error(f"probe {probe_id} candidate vectors must be exact")
        expected_native = parsed_probe["expected_native_ranking"]
        expected_padded = parsed_probe["expected_padded_ranking"]
        if (
            not isinstance(expected_native, list)
            or not isinstance(expected_padded, list)
            or not all(isinstance(candidate_id, str) for candidate_id in expected_native)
            or not all(isinstance(candidate_id, str) for candidate_id in expected_padded)
            or expected_native != expected_padded
            or set(expected_native) != set(candidate_ids)
            or len(expected_native) != len(candidate_ids)
        ):
            raise _selection_error(f"probe {probe_id} expected rankings are invalid")
        native_candidates: list[tuple[str, tuple[float, ...]]] = []
        padded_candidates: list[tuple[str, tuple[float, ...]]] = []
        scores_for_probe: dict[str, float] = {}
        for candidate_id in candidate_ids:
            candidate_vectors = _validate_space_vectors(
                vectors[candidate_id],
                label=f"probe {probe_id} candidate {candidate_id}",
            )
            native = candidate_vectors["native_768"]
            padded = candidate_vectors["padded_1024"]
            native_score = cosine_similarity(query_vectors["native_768"], native)
            padded_score = cosine_similarity(query_vectors["padded_1024"], padded)
            if not math.isclose(native_score, padded_score, rel_tol=1e-12, abs_tol=1e-12):
                raise _selection_error(f"probe {probe_id} cosine parity mismatch")
            native_candidates.append((candidate_id, native))
            padded_candidates.append((candidate_id, padded))
            scores_for_probe[candidate_id] = native_score
        native_ranking = rank_by_cosine(query_vectors["native_768"], native_candidates)
        padded_ranking = rank_by_cosine(query_vectors["padded_1024"], padded_candidates)
        if native_ranking != padded_ranking or native_ranking != expected_native:
            raise _selection_error(f"probe {probe_id} ranking parity mismatch")
        probe_scores.append(scores_for_probe)

    selection = _validate_exact_object(
        fixture["selection"],
        {"method", "expected_candidate_id"},
        label="selection",
    )
    if selection["method"] != "mean_cosine_then_id_v1":
        raise _selection_error("unsupported selection method")
    means = _mean_cosine_scores(probe_scores, candidate_ids)
    selected = min(candidate_ids, key=lambda candidate_id: (-means[candidate_id], candidate_id))
    if selection["expected_candidate_id"] != selected:
        raise _selection_error("selection result mismatch")
    digest = _validate_digest(fixture["fixture_sha256"], field="fixture_sha256")
    if digest != fixture_digest(fixture):
        raise _selection_error("selection fixture digest mismatch")
    return fixture


def parse_selection_fixture(payload: str | bytes | bytearray) -> dict[str, Any]:
    """Parse and validate fixture JSON with duplicate/non-finite rejection."""
    return validate_selection_fixture(_parse_json(payload))


def load_selection_fixture(path: str | Path = SELECTION_FIXTURE_PATH) -> dict[str, Any]:
    """Load the source-owned selection fixture without accepting drift."""
    fixture_path = Path(path)
    try:
        payload = fixture_path.read_bytes()
    except (OSError, UnicodeError) as exc:
        raise EmbedderSelectionValidationError(
            f"cannot read selection fixture {fixture_path}"
        ) from exc
    return parse_selection_fixture(payload)


def select_synthetic_embedder(document: object) -> str:
    """Return the deterministic dev-only winner after full fixture validation."""
    fixture = validate_selection_fixture(document)
    return fixture["selection"]["expected_candidate_id"]


def select_embedder(document: object) -> str:
    """Compatibility alias for the explicit synthetic selector."""
    return select_synthetic_embedder(document)


validate_receipt = validate_bakeoff_receipt
