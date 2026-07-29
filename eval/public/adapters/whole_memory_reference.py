from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

PROTOCOL_VERSION = "wmbs/0.1-draft"
VOLATILE_FIELDS = {
    "wall_time_ms",
    "rss_samples_bytes",
    "signature",
    "path",
    "runtime_timestamp_utc",
}

_SCHEMA_PATH = Path(__file__).parents[1] / "schema" / "wmbs-0.1-draft.schema.json"
_SCHEMA = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
_DEFINITIONS: dict[str, dict[str, Any]] = _SCHEMA["$defs"]
_OPERATIONS = ("negotiate", "create_run", "ingest", "retrieve", "answer", "finalize")
_UTC_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_MAX_REQUESTS = 10_000
_MAX_REQUEST_BYTES = 16 * 1024 * 1024
_MAX_RETAINED_BYTES = 64 * 1024 * 1024
_MAX_JSON_DEPTH = 64
_STRING_CHUNK_SIZE = 64 * 1024


class WholeMemoryValidationError(ValueError):
    def __init__(self, message: str, *, code: str = "INVALID_REQUEST") -> None:
        super().__init__(message)
        self.code = code


def _fail(message: str, *, code: str = "INVALID_REQUEST") -> NoReturn:
    raise WholeMemoryValidationError(message, code=code)


def _resolve(schema: Mapping[str, Any]) -> Mapping[str, Any]:
    reference = schema.get("$ref")
    if reference is None:
        return schema
    prefix = "#/$defs/"
    if not isinstance(reference, str) or not reference.startswith(prefix):
        _fail("schema contains an unsupported reference")
    resolved = _DEFINITIONS.get(reference.removeprefix(prefix))
    if resolved is None:
        _fail("schema references an unknown definition")
    return resolved


def _type_matches(value: object, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def _validate(value: object, raw_schema: Mapping[str, Any], path: str) -> None:
    schema = _resolve(raw_schema)
    if "anyOf" in schema:
        for option in schema["anyOf"]:
            try:
                _validate(value, option, path)
            except WholeMemoryValidationError:
                continue
            return
        _fail(f"{path} does not match any allowed shape")

    expected = schema.get("type")
    if isinstance(expected, list):
        if not any(_type_matches(value, item) for item in expected):
            _fail(f"{path} has the wrong type")
    elif isinstance(expected, str) and not _type_matches(value, expected):
        _fail(f"{path} must be {expected}")

    if "const" in schema and value != schema["const"]:
        _fail(f"{path} must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        _fail(f"{path} is not in the closed enum")

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            _fail(f"{path} is too short")
        if len(value) > schema.get("maxLength", len(value)):
            _fail(f"{path} is too long")
        pattern = schema.get("pattern")
        if pattern is not None and re.fullmatch(pattern, value) is None:
            _fail(f"{path} has an invalid format")
        if schema.get("format") == "utc-timestamp":
            _parse_utc_timestamp(value, path)

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            _fail(f"{path} must be finite")
        if value < schema.get("minimum", value):
            _fail(f"{path} is below its minimum")
        if value > schema.get("maximum", value):
            _fail(f"{path} is above its maximum")

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            _fail(f"{path} has too few items")
        if len(value) > schema.get("maxItems", len(value)):
            _fail(f"{path} has too many items")
        if schema.get("uniqueItems"):
            encoded = [canonical_json(item) for item in value]
            if len(encoded) != len(set(encoded)):
                _fail(f"{path} must contain unique items")
        for index, item in enumerate(value):
            _validate(item, schema.get("items", {}), f"{path}[{index}]")

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        missing = set(schema.get("required", ())) - value.keys()
        if missing:
            _fail(f"{path} is missing {', '.join(sorted(missing))}")
        if schema.get("additionalProperties") is False:
            unknown = value.keys() - properties.keys()
            if unknown:
                _fail(f"{path} has unknown fields: {', '.join(sorted(unknown))}")
        for key, nested in value.items():
            if key in properties:
                _validate(nested, properties[key], f"{path}.{key}")
        if schema is _DEFINITIONS["portable_event"]:
            valid_from = value["valid_from"]
            valid_to = value["valid_to"]
            if (
                isinstance(valid_from, str)
                and isinstance(valid_to, str)
                and _parse_utc_timestamp(valid_to, f"{path}.valid_to")
                < _parse_utc_timestamp(valid_from, f"{path}.valid_from")
            ):
                _fail(f"{path}.valid_to precedes valid_from")
        elif schema is _DEFINITIONS["retrieval_envelope"]:
            hits = value["hits"]
            assert isinstance(hits, list)
            ranks = [hit["rank"] for hit in hits]
            stable_item_ids = [hit["stable_item_id"] for hit in hits]
            if ranks != list(range(1, len(hits) + 1)):
                _fail(f"{path}.hits must have contiguous ascending ranks")
            if len(stable_item_ids) != len(set(stable_item_ids)):
                _fail(f"{path}.hits must have unique stable item IDs")
        elif schema is _DEFINITIONS["ingest_status"]:
            outcome = value["outcome"]
            if outcome == "rejected":
                if (
                    value["durability"] != "not_acknowledged"
                    or value["evidence_handle"] is not None
                    or value["error"] is None
                ):
                    _fail(f"{path} has contradictory rejected-event status")
            elif value["durability"] != "acknowledged" or value["error"] is not None:
                _fail(f"{path} has contradictory accepted-event status")


def _parse_utc_timestamp(value: str, path: str) -> datetime:
    if _UTC_TIMESTAMP.fullmatch(value) is None:
        _fail(f"{path} must be canonical UTC with a Z suffix")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        _fail(f"{path} is not a valid timestamp")
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        _fail(f"{path} is not canonical")
    return parsed


def _reject_non_finite(value: object) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        _fail("canonical JSON cannot contain non-finite numbers")
    if isinstance(value, Mapping):
        for key, nested in value.items():
            _reject_non_finite(key)
            _reject_non_finite(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_non_finite(nested)


def canonical_json(value: object) -> bytes:
    _reject_non_finite(value)
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            ensure_ascii=False,
        )
    except (TypeError, ValueError) as exc:
        _fail(f"value is not canonical JSON: {exc}")
    return (encoded + "\n").encode()


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _enforce_canonical_size(value: object, maximum: int) -> None:
    active: set[int] = set()
    frames: list[tuple[object, int, int]] = []
    current = value
    depth = 0
    minimum_size = 1  # canonical_json appends one newline

    while True:
        if isinstance(current, float) and not math.isfinite(current):
            _fail("canonical JSON cannot contain non-finite numbers")
        if isinstance(current, str):
            try:
                for start in range(0, len(current), _STRING_CHUNK_SIZE):
                    minimum_size += len(
                        current[start : start + _STRING_CHUNK_SIZE].encode()
                    )
                    if minimum_size > maximum:
                        _fail(
                            "request exceeds the byte limit",
                            code="RESOURCE_LIMIT",
                        )
            except UnicodeEncodeError as exc:
                _fail(f"value is not canonical JSON: {exc}")
        elif isinstance(current, dict):
            if depth >= _MAX_JSON_DEPTH:
                _fail("request exceeds the nesting limit", code="RESOURCE_LIMIT")
            identity = id(current)
            if identity in active:
                _fail("value is not canonical JSON: circular reference")
            active.add(identity)
            children = (item for pair in current.items() for item in pair)
            frames.append((children, depth + 1, identity))
        elif isinstance(current, list):
            if depth >= _MAX_JSON_DEPTH:
                _fail("request exceeds the nesting limit", code="RESOURCE_LIMIT")
            identity = id(current)
            if identity in active:
                _fail("value is not canonical JSON: circular reference")
            active.add(identity)
            frames.append((iter(current), depth + 1, identity))
        elif current is not None and not isinstance(current, (bool, int, float)):
            _fail(f"value is not canonical JSON: unsupported {type(current).__name__}")

        while frames:
            children, child_depth, identity = frames[-1]
            try:
                current = next(children)  # type: ignore[arg-type]
                depth = child_depth
                break
            except StopIteration:
                active.remove(identity)
                frames.pop()
        else:
            break

    size = 1  # canonical_json appends one newline
    try:
        chunks = json.JSONEncoder(
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            ensure_ascii=False,
        ).iterencode(value)
        for chunk in chunks:
            size += len(chunk.encode())
            if size > maximum:
                break
    except (RecursionError, TypeError, UnicodeEncodeError, ValueError) as exc:
        _fail(f"value is not canonical JSON: {exc}")
    if size > maximum:
        _fail("request exceeds the byte limit", code="RESOURCE_LIMIT")


def canonical_projection(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            key: canonical_projection(nested)
            for key, nested in value.items()
            if key not in VOLATILE_FIELDS
        }
    if isinstance(value, list):
        return [canonical_projection(nested) for nested in value]
    return deepcopy(value)


def validate_definition(definition: str, value: object) -> object:
    schema = _DEFINITIONS.get(definition)
    if schema is None:
        _fail(f"unknown definition: {definition}")
    _validate(value, schema, "$")
    return deepcopy(value)


class ProtocolValidator:
    def __init__(self, *, now: Callable[[], datetime] | None = None) -> None:
        self._now = now or (lambda: datetime.now(UTC))
        self._request_ids: set[str] = set()
        self._replays: dict[str, tuple[bytes, object]] = {}
        self._scope: tuple[str, str, str] | None = None
        self._retained_bytes = 0
        self._phase = "new"
        self.last_sequence = 0

    def validate_request(self, request: object) -> object:
        if not isinstance(request, dict):
            _fail("request must be an object")
        _enforce_canonical_size(request, _MAX_REQUEST_BYTES)
        operation = request.get("operation")
        if operation not in _OPERATIONS:
            _fail("unsupported operation", code="UNSUPPORTED_OPERATION")

        validated = validate_definition(f"{operation}_request", request)
        assert isinstance(validated, dict)
        context = validated["context"]
        assert isinstance(context, dict)
        scope = tuple(str(context[key]) for key in ("tenant_id", "run_id", "attempt_id"))
        if self._scope is not None and scope != self._scope:
            _fail("request scope changed", code="CONFLICT")
        deadline = _parse_utc_timestamp(str(context["deadline_utc"]), "$.context.deadline_utc")
        if deadline <= self._now():
            _fail("request deadline has elapsed", code="DEADLINE_EXCEEDED")

        request_bytes = canonical_json(validated)
        idempotency_key = str(context["idempotency_key"])
        replay = self._replays.get(idempotency_key)
        if replay is not None:
            if replay[0] != request_bytes:
                _fail("idempotency key was reused for different content", code="CONFLICT")
            return deepcopy(replay[1])

        request_id = str(context["request_id"])
        if request_id in self._request_ids:
            _fail("request ID was reused", code="CONFLICT")
        sequence = int(context["sequence"])
        if sequence <= self.last_sequence:
            _fail("request sequence did not advance", code="ORDER_VIOLATION")
        if not self._operation_allowed(str(operation)):
            _fail("operation is invalid in the current phase", code="ORDER_VIOLATION")
        if len(self._replays) >= _MAX_REQUESTS:
            _fail("request retention limit reached", code="RESOURCE_LIMIT")
        if self._retained_bytes + len(request_bytes) > _MAX_RETAINED_BYTES:
            _fail("request retention byte limit reached", code="RESOURCE_LIMIT")

        self._request_ids.add(request_id)
        self._replays[idempotency_key] = (request_bytes, deepcopy(validated))
        self._retained_bytes += len(request_bytes)
        if self._scope is None:
            self._scope = scope
        self.last_sequence = sequence
        if operation == "negotiate":
            self._phase = "negotiated"
        elif operation == "create_run":
            self._phase = "active"
        elif operation == "finalize":
            self._phase = "finalized"
        return deepcopy(validated)

    def validate_response(self, request: object, response: object) -> object:
        if not isinstance(request, dict):
            _fail("request must be an object")
        operation = request.get("operation")
        if operation not in _OPERATIONS:
            _fail("unsupported operation", code="UNSUPPORTED_OPERATION")
        _enforce_canonical_size(request, _MAX_REQUEST_BYTES)
        validated_request = validate_definition(f"{operation}_request", request)
        assert isinstance(validated_request, dict)
        context = validated_request["context"]
        assert isinstance(context, dict)
        replay = self._replays.get(str(context["idempotency_key"]))
        request_bytes = canonical_json(validated_request)
        if replay is None or replay[0] != request_bytes:
            _fail("response does not match an accepted request", code="CONFLICT")

        validated_response = validate_definition(f"{operation}_response", response)
        assert isinstance(validated_response, dict)
        payload = validated_response["payload"]
        assert isinstance(payload, dict)
        if operation == "ingest":
            request_payload = validated_request["payload"]
            assert isinstance(request_payload, dict)
            event_ids = [
                event["event_id"] for event in request_payload["ordered_events"]
            ]
            status_ids = [status["event_id"] for status in payload["statuses"]]
            if status_ids != event_ids:
                _fail("ingest statuses do not match request event order")
        elif operation in {"create_run", "finalize"}:
            for key in ("run_id", "attempt_id"):
                if payload[key] != context[key]:
                    _fail(f"response {key} does not match request context")
        return deepcopy(validated_response)

    def _operation_allowed(self, operation: str) -> bool:
        if self._phase == "new":
            return operation == "negotiate"
        if self._phase == "negotiated":
            return operation == "create_run"
        if self._phase == "active":
            return operation in {"ingest", "retrieve", "answer", "finalize"}
        return False
