from __future__ import annotations

import hashlib
import ipaddress
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
_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
_MAX_RETAINED_BYTES = 64 * 1024 * 1024
_MAX_JSON_DEPTH = 64
_STRING_CHUNK_SIZE = 64 * 1024
_EVIDENCE_DEFINITIONS = {
    "BaselineManifest",
    "PowerPlan",
    "SoftwareDataBOM",
    "SandboxReceipt",
    "ResourceReceipt",
    "FeasibilityRecord",
}
_FEASIBILITY_REFERENCE_FIELDS = (
    "adapter_contract_ref",
    "data_source_ref",
    "scorer_ref",
    "baseline_manifest_ref",
    "power_plan_ref",
    "sandbox_receipt_ref",
    "resource_receipt_ref",
    "software_data_bom_ref",
)
_TYPED_FEASIBILITY_REFERENCES = {
    "baseline_manifest_ref": "BaselineManifest",
    "power_plan_ref": "PowerPlan",
    "sandbox_receipt_ref": "SandboxReceipt",
    "resource_receipt_ref": "ResourceReceipt",
    "software_data_bom_ref": "SoftwareDataBOM",
}
_CONTRACT_REFERENCE_FIELDS = tuple(
    field
    for field in _FEASIBILITY_REFERENCE_FIELDS
    if field != "resource_receipt_ref"
)
_READINESS_STATES = {
    "PILOT-READY-DEV",
    "RUN-READY-OFFICIAL-LOCAL",
    "RUN-READY-HOSTED-X",
    "RUN-READY-P32-OPS",
}
_RUN_READINESS_STATES = _READINESS_STATES - {"PILOT-READY-DEV"}
_ADMISSION_STATES = _READINESS_STATES | {"CONTRACT-READY"}


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
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            or isinstance(value, float)
            and math.isfinite(value)
            and value.is_integer()
        )
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def _json_equal(left: object, right: object) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _json_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _json_equal(left[key], right[key]) for key in left
        )
    return type(left) is type(right) and left == right


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
    if "oneOf" in schema:
        matches = 0
        for option in schema["oneOf"]:
            try:
                _validate(value, option, path)
            except WholeMemoryValidationError:
                continue
            matches += 1
        if matches != 1:
            _fail(f"{path} must match exactly one allowed shape")

    expected = schema.get("type")
    if isinstance(expected, list):
        if not any(_type_matches(value, item) for item in expected):
            _fail(f"{path} has the wrong type")
    elif isinstance(expected, str) and not _type_matches(value, expected):
        _fail(f"{path} must be {expected}")

    if "const" in schema and not _json_equal(value, schema["const"]):
        _fail(f"{path} must equal {schema['const']!r}")
    if "enum" in schema and not any(
        _json_equal(value, option) for option in schema["enum"]
    ):
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
            for index, item in enumerate(value):
                if any(_json_equal(item, prior) for prior in value[:index]):
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
            valid_from = value.get("valid_from")
            valid_to = value.get("valid_to")
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
                    or value.get("evidence_handle") is not None
                    or value.get("error") is None
                ):
                    _fail(f"{path} has contradictory rejected-event status")
            elif (
                value["durability"] != "acknowledged" or value.get("error") is not None
            ):
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


def canonical_json(value: object) -> bytes:
    _enforce_canonical_size(value, _MAX_RETAINED_BYTES, label="value")
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


def canonical_artifact_sha256(value: Mapping[str, object]) -> str:
    return canonical_sha256(
        {key: item for key, item in value.items() if key != "artifact_sha256"}
    )


def _sandbox_profile_sha256(receipt: Mapping[str, object]) -> str:
    return canonical_sha256(
        {
            key: item
            for key, item in receipt.items()
            if key not in {"schema_id", "artifact_sha256", "profile_ref"}
        }
    )


def _validate_artifact_digest(definition: str, value: object) -> None:
    if definition not in _EVIDENCE_DEFINITIONS:
        return
    if not isinstance(value, Mapping):
        _fail("evidence artifact must be an object")
    if value["artifact_sha256"] != canonical_artifact_sha256(value):
        _fail("$.artifact_sha256 does not bind the canonical artifact")


def _feasibility_dispositions(value: Mapping[str, object]) -> set[object]:
    dispositions = value["feasibility_disposition"]
    if not isinstance(dispositions, Mapping):
        _fail("$.feasibility_disposition must be an object")
    return set(dispositions.values())


def _enforce_canonical_size(
    value: object, maximum: int, *, label: str = "request"
) -> None:
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
                minimum_size += 2
                for start in range(0, len(current), _STRING_CHUNK_SIZE):
                    minimum_size += len(
                        current[start : start + _STRING_CHUNK_SIZE].encode()
                    )
                    if minimum_size > maximum:
                        _fail(
                            f"{label} exceeds the byte limit",
                            code="RESOURCE_LIMIT",
                        )
            except UnicodeEncodeError as exc:
                _fail(f"value is not canonical JSON: {exc}")
        elif isinstance(current, dict):
            if any(not isinstance(key, str) for key in current):
                _fail("value is not canonical JSON: object keys must be strings")
            minimum_size += 2 + len(current) + max(0, len(current) - 1)
            if minimum_size > maximum:
                _fail(f"{label} exceeds the byte limit", code="RESOURCE_LIMIT")
            if depth >= _MAX_JSON_DEPTH:
                _fail(f"{label} exceeds the nesting limit", code="RESOURCE_LIMIT")
            identity = id(current)
            if identity in active:
                _fail("value is not canonical JSON: circular reference")
            active.add(identity)
            children = (item for pair in current.items() for item in pair)
            frames.append((children, depth + 1, identity))
        elif isinstance(current, list):
            minimum_size += 2 + max(0, len(current) - 1)
            if minimum_size > maximum:
                _fail(f"{label} exceeds the byte limit", code="RESOURCE_LIMIT")
            if depth >= _MAX_JSON_DEPTH:
                _fail(f"{label} exceeds the nesting limit", code="RESOURCE_LIMIT")
            identity = id(current)
            if identity in active:
                _fail("value is not canonical JSON: circular reference")
            active.add(identity)
            frames.append((iter(current), depth + 1, identity))
        elif current is not None and not isinstance(current, (bool, int, float)):
            _fail(f"value is not canonical JSON: unsupported {type(current).__name__}")
        else:
            minimum_size += 1
            if minimum_size > maximum:
                _fail(f"{label} exceeds the byte limit", code="RESOURCE_LIMIT")

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
        _fail(f"{label} exceeds the byte limit", code="RESOURCE_LIMIT")


def canonical_projection(value: object) -> object:
    _enforce_canonical_size(value, _MAX_RETAINED_BYTES, label="projection")

    def project(nested: object) -> object:
        if isinstance(nested, Mapping):
            return {
                key: project(item)
                for key, item in nested.items()
                if key not in VOLATILE_FIELDS
            }
        if isinstance(nested, list):
            return [project(item) for item in nested]
        return deepcopy(nested)

    return project(value)


def validate_definition(definition: str, value: object) -> object:
    schema = _DEFINITIONS.get(definition)
    if schema is None:
        _fail(f"unknown definition: {definition}")
    _enforce_canonical_size(value, _MAX_RETAINED_BYTES, label="value")
    _validate(value, schema, "$")
    _validate_artifact_digest(definition, value)
    if definition == "SandboxReceipt":
        assert isinstance(value, Mapping)
        egress = value["egress"]
        assert isinstance(egress, Mapping)
        endpoints = egress["endpoints"]
        assert isinstance(endpoints, list)
        if (egress["mode"] == "deny") != (not endpoints):
            _fail("$.egress mode does not match its endpoint allowlist")
        for endpoint in endpoints:
            assert isinstance(endpoint, Mapping)
            ip_ranges = endpoint["ip_ranges"]
            assert isinstance(ip_ranges, list)
            for item in ip_ranges:
                assert isinstance(item, str)
                try:
                    network = ipaddress.ip_network(item, strict=False)
                except ValueError:
                    _fail("$.egress IP ranges must be valid CIDR networks")
                if not network.is_global:
                    _fail("$.egress IP ranges must be globally routable")
    if definition == "FeasibilityRecord":
        assert isinstance(value, Mapping)
        dispositions = _feasibility_dispositions(value)
        if dispositions & _ADMISSION_STATES:
            _fail("admission requires resolved evidence via validate_evidence_bundle")
        if "PROPOSED" in dispositions and dispositions.isdisjoint(
            _ADMISSION_STATES
        ) and all(
            value[field] is not None for field in _FEASIBILITY_REFERENCE_FIELDS
        ):
            _fail("PROPOSED requires at least one absent feasibility artifact")
    return deepcopy(value)


def validate_evidence_bundle(
    record: Mapping[str, object], artifacts: Mapping[str, object]
) -> object:
    schema = _DEFINITIONS["FeasibilityRecord"]
    _enforce_canonical_size(record, _MAX_RETAINED_BYTES, label="value")
    _validate(record, schema, "$")
    _validate_artifact_digest("FeasibilityRecord", record)
    dispositions = _feasibility_dispositions(record)
    if "PROPOSED" in dispositions and dispositions.isdisjoint(
        _ADMISSION_STATES
    ) and all(
        record[field] is not None for field in _FEASIBILITY_REFERENCE_FIELDS
    ):
        _fail("PROPOSED requires at least one absent feasibility artifact")

    resolved: dict[str, object] = {}
    for field in _FEASIBILITY_REFERENCE_FIELDS:
        reference = record[field]
        if reference is None:
            continue
        assert isinstance(reference, str)
        artifact = artifacts.get(reference)
        if artifact is None:
            _fail(f"$.{field} does not resolve to a supplied artifact")
        schema_id, separator, expected_digest = reference.rpartition("@sha256:")
        if not separator:
            _fail(f"$.{field} is not a digest reference")
        if isinstance(artifact, Mapping) and "artifact_sha256" in artifact:
            actual_digest = canonical_artifact_sha256(artifact)
        else:
            actual_digest = canonical_sha256(artifact)
        if actual_digest != expected_digest:
            _fail(f"$.{field} does not match the supplied artifact")
        expected_definition = _TYPED_FEASIBILITY_REFERENCES.get(field)
        if expected_definition is not None:
            expected_schema_id = f"urn:wmbs:0.1-draft#{expected_definition}"
            if schema_id != expected_schema_id:
                _fail(f"$.{field} does not reference {expected_definition}")
            validate_definition(expected_definition, artifact)
        resolved[field] = artifact

    required_fields: tuple[str, ...] = ()
    if dispositions & _READINESS_STATES:
        required_fields = _FEASIBILITY_REFERENCE_FIELDS
    elif "CONTRACT-READY" in dispositions:
        required_fields = _CONTRACT_REFERENCE_FIELDS
    if required_fields:
        missing = [
            field
            for field in required_fields
            if field not in resolved
        ]
        if missing:
            _fail(f"admission is missing resolved artifacts: {', '.join(missing)}")
    if dispositions & _READINESS_STATES:
        if dispositions & _RUN_READINESS_STATES:
            _fail("run readiness requires profile-specific signed evidence")
        sandbox_receipt = resolved["sandbox_receipt_ref"]
        resource_receipt = resolved["resource_receipt_ref"]
        if (
            not isinstance(sandbox_receipt, Mapping)
            or not isinstance(resource_receipt, Mapping)
        ):
            _fail("pilot readiness requires sandbox and resource receipts")
        profile_ref = sandbox_receipt.get("profile_ref")
        if not isinstance(profile_ref, str):
            _fail("pilot readiness requires a sandbox profile")
        profile_id, separator, profile_digest = profile_ref.rpartition("@sha256:")
        if not separator or profile_id != "sandbox-l16-dev":
            _fail("pilot readiness requires the L16-DEV sandbox profile")
        if _sandbox_profile_sha256(sandbox_receipt) != profile_digest:
            _fail("sandbox profile digest does not match its declared controls")
        if resource_receipt.get("profile_sha256") != profile_digest:
            _fail("resource receipt does not match the sandbox profile")
        if resource_receipt.get("sut_boundary") != sandbox_receipt.get("sut_boundary"):
            _fail("resource receipt does not match the sandbox SUT boundary")
        egress = sandbox_receipt.get("egress")
        if (
            sandbox_receipt.get("syscall_policy") == "unavailable"
            or not isinstance(egress, Mapping)
            or egress.get("mode") != "deny"
            or egress.get("endpoints") != []
            or sandbox_receipt.get("secrets") != "none"
            or sandbox_receipt.get("model_proxy") != "disabled"
            or resource_receipt.get("network_bytes") != 0
        ):
            _fail("pilot readiness requires enforced offline L16 controls")
        if resource_receipt.get("abort_status") != "completed":
            _fail("readiness requires a completed resource receipt")
        result_contract = record["result_contract"]
        if (
            not isinstance(result_contract, Mapping)
            or result_contract.get("attempt_state") != "finalized"
        ):
            _fail("pilot readiness requires a finalized attempt")
    return deepcopy(record)


class ProtocolValidator:
    def __init__(self, *, now: Callable[[], datetime] | None = None) -> None:
        self._now = now or (lambda: datetime.now(UTC))
        self._request_ids: set[str] = set()
        self._replays: dict[str, tuple[bytes, object]] = {}
        self._responses: dict[str, tuple[int, bytes]] = {}
        self._scope: tuple[str, str, str] | None = None
        self._retained_bytes = 0
        self._pending_transition: str | None = None
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
        scope = tuple(
            str(context[key]) for key in ("tenant_id", "run_id", "attempt_id")
        )
        if self._scope is not None and scope != self._scope:
            _fail("request scope changed", code="CONFLICT")
        request_bytes = canonical_json(validated)
        idempotency_key = str(context["idempotency_key"])
        replay = self._replays.get(idempotency_key)
        if replay is not None:
            if replay[0] != request_bytes:
                _fail(
                    "idempotency key was reused for different content", code="CONFLICT"
                )
            return deepcopy(replay[1])

        deadline = _parse_utc_timestamp(
            str(context["deadline_utc"]), "$.context.deadline_utc"
        )
        if deadline <= self._now():
            _fail("request deadline has elapsed", code="DEADLINE_EXCEEDED")

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
        if operation in {"negotiate", "create_run", "finalize"}:
            self._pending_transition = idempotency_key
        return deepcopy(validated)

    def validate_response(self, request: object, response: object) -> object:
        if not isinstance(request, dict):
            _fail("request must be an object")
        operation = request.get("operation")
        if operation not in _OPERATIONS:
            _fail("unsupported operation", code="UNSUPPORTED_OPERATION")
        _enforce_canonical_size(request, _MAX_REQUEST_BYTES)
        _enforce_canonical_size(response, _MAX_RESPONSE_BYTES, label="response")
        validated_request = validate_definition(f"{operation}_request", request)
        assert isinstance(validated_request, dict)
        context = validated_request["context"]
        assert isinstance(context, dict)
        replay = self._replays.get(str(context["idempotency_key"]))
        request_bytes = canonical_json(validated_request)
        if replay is None or replay[0] != request_bytes:
            _fail("response does not match an accepted request", code="CONFLICT")

        definition = (
            "error_response"
            if isinstance(response, dict) and "error" in response
            else f"{operation}_response"
        )
        validated_response = validate_definition(definition, response)
        assert isinstance(validated_response, dict)
        response_bytes = canonical_json(validated_response)
        response_fingerprint = (
            len(response_bytes),
            hashlib.sha256(response_bytes).digest(),
        )
        idempotency_key = str(context["idempotency_key"])
        prior_response = self._responses.get(idempotency_key)
        if prior_response is not None:
            if prior_response != response_fingerprint:
                _fail(
                    "accepted request produced a conflicting response",
                    code="CONFLICT",
                )
            return deepcopy(validated_response)

        if definition == "error_response":
            self._responses[idempotency_key] = response_fingerprint
            if self._pending_transition == idempotency_key:
                self._pending_transition = None
            return deepcopy(validated_response)

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
        elif operation == "retrieve":
            request_payload = validated_request["payload"]
            assert isinstance(request_payload, dict)
            if len(payload["hits"]) > request_payload["top_k"]:
                _fail("retrieve response exceeds the requested top_k")
        elif operation == "answer":
            request_payload = validated_request["payload"]
            assert isinstance(request_payload, dict)
            answer_text = payload.get("answer_text")
            if (payload["abstained"] and answer_text is not None) or (
                not payload["abstained"] and answer_text is None
            ):
                _fail("answer response contradicts its abstention status")
            if request_payload["response_mode"] == "forced" and payload["abstained"]:
                _fail("forced answer response must contain an answer")
        elif operation in {"create_run", "finalize"}:
            for key in ("run_id", "attempt_id"):
                if payload[key] != context[key]:
                    _fail(f"response {key} does not match request context")
        self._responses[idempotency_key] = response_fingerprint
        if self._pending_transition == idempotency_key:
            self._pending_transition = None
            if operation == "negotiate":
                self._phase = "negotiated"
            elif operation == "create_run" and payload["accepted"]:
                self._phase = "active"
            elif operation == "finalize" and payload["finalized"]:
                self._phase = "finalized"
        return deepcopy(validated_response)

    def _operation_allowed(self, operation: str) -> bool:
        if self._pending_transition is not None:
            return False
        if operation == "finalize" and any(
            key not in self._responses for key in self._replays
        ):
            return False
        if self._phase == "new":
            return operation == "negotiate"
        if self._phase == "negotiated":
            return operation == "create_run"
        if self._phase == "active":
            return operation in {"ingest", "retrieve", "answer", "finalize"}
        return False
