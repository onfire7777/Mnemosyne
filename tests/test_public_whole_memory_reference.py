from __future__ import annotations

import hashlib
import importlib
import json
import math
import re
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from jsonschema import Draft202012Validator

PROTOCOL_VERSION = "wmbs/0.1-draft"
REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "eval/public/schema/wmbs-0.1-draft.schema.json"
ADAPTER_PATH = REPO_ROOT / "eval/public/adapters/whole_memory_reference.py"
SCHEMA = (
    json.loads(SCHEMA_PATH.read_text(encoding="utf-8")) if SCHEMA_PATH.is_file() else {}
)
ERROR_CODES = (
    "INVALID_REQUEST",
    "UNSUPPORTED_OPERATION",
    "UNAUTHORIZED",
    "CONFLICT",
    "ORDER_VIOLATION",
    "DEADLINE_EXCEEDED",
    "RESOURCE_LIMIT",
    "DEPENDENCY_UNAVAILABLE",
    "INTERNAL_ERROR",
)
VOLATILE_FIELDS = {
    "wall_time_ms",
    "rss_samples_bytes",
    "signature",
    "path",
    "runtime_timestamp_utc",
}
_MISSING = [str(path) for path in (SCHEMA_PATH, ADAPTER_PATH) if not path.is_file()]
abi: Any = (
    importlib.import_module("eval.public.adapters.whole_memory_reference")
    if not _MISSING
    else None
)
requires_abi = pytest.mark.skipif(bool(_MISSING), reason="ABI artifacts are RED")

RUN_ID = "run-0001"
ATTEMPT_ID = "attempt-0001"
TENANT_ID = "tenant-0001"
DEADLINE = "2026-07-29T00:00:00Z"
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
L16_PROFILE_DIGEST = (
    "aef321c0ac53c043ddebfde8b3a8b27cafc145443700867cc0bbe9ef892cee40"
)


def _context(
    *,
    request_id: str,
    idempotency_key: str,
    sequence: int,
    deadline_utc: str = DEADLINE,
) -> dict[str, object]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "run_id": RUN_ID,
        "attempt_id": ATTEMPT_ID,
        "request_id": request_id,
        "idempotency_key": idempotency_key,
        "sequence": sequence,
        "deadline_utc": deadline_utc,
        "tenant_id": TENANT_ID,
        "principal_id": "principal-0001",
        "session_id": "session-0001",
    }


def _request(
    operation: str,
    payload: dict[str, object],
    *,
    sequence: int,
) -> dict[str, object]:
    return {
        "operation": operation,
        "context": _context(
            request_id=f"request-{sequence:04d}",
            idempotency_key=f"idempotency-{sequence:04d}",
            sequence=sequence,
        ),
        "payload": payload,
    }


GOLDEN_REQUESTS = {
    "negotiate": _request(
        "negotiate",
        {
            "client_name": "reference-client",
            "supported_protocol_versions": [PROTOCOL_VERSION],
        },
        sequence=1,
    ),
    "create_run": _request(
        "create_run",
        {
            "module_id": "M01",
            "module_version": "0.1.0",
            "division": "COMPONENT-CLOSED",
            "track": "DEVELOPMENT",
            "seed": 7,
        },
        sequence=2,
    ),
    "ingest": _request(
        "ingest",
        {
            "ordered_events": [
                {
                    "event_id": "event-0001",
                    "content": "Ada prefers tea.",
                    "actor_label": "user",
                    "event_time": "2026-07-28T12:00:00Z",
                    "ingestion_time": "2026-07-28T12:00:01Z",
                    "valid_from": "2026-07-28T12:00:00Z",
                    "valid_to": None,
                    "content_sha256": DIGEST_A,
                    "modality_handle": None,
                    "public_metadata": {"source": "golden"},
                }
            ]
        },
        sequence=3,
    ),
    "retrieve": _request(
        "retrieve",
        {
            "query": "What does Ada prefer?",
            "observation_time": "2026-07-28T12:05:00Z",
            "top_k": 5,
        },
        sequence=4,
    ),
    "answer": _request(
        "answer",
        {
            "question": "What does Ada prefer?",
            "observation_time": "2026-07-28T12:05:00Z",
            "response_mode": "normal",
        },
        sequence=5,
    ),
    "finalize": _request("finalize", {"reason": "completed"}, sequence=6),
}

GOLDEN_RESPONSES = {
    "negotiate": {
        "operation": "negotiate",
        "payload": {
            "protocol_version": PROTOCOL_VERSION,
            "server_name": "whole-memory-reference",
            "supported_operations": list(GOLDEN_REQUESTS),
        },
    },
    "create_run": {
        "operation": "create_run",
        "payload": {
            "run_id": RUN_ID,
            "attempt_id": ATTEMPT_ID,
            "accepted": True,
        },
    },
    "ingest": {
        "operation": "ingest",
        "payload": {
            "statuses": [
                {
                    "event_id": "event-0001",
                    "outcome": "accepted",
                    "durability": "acknowledged",
                    "evidence_handle": "evidence-0001",
                    "error": None,
                }
            ]
        },
    },
    "retrieve": {
        "operation": "retrieve",
        "payload": {
            "hits": [
                {
                    "rank": 1,
                    "stable_item_id": "item-0001",
                    "score": 1.0,
                    "content_or_handle": "Ada prefers tea.",
                    "evidence_handles": ["evidence-0001"],
                    "observed_at": "2026-07-28T12:05:00Z",
                    "provenance_status": "verified",
                }
            ]
        },
    },
    "answer": {
        "operation": "answer",
        "payload": {
            "answer_text": "Ada prefers tea.",
            "abstained": False,
            "confidence": 1.0,
            "evidence_handles": ["evidence-0001"],
            "action_handles": [],
            "adapter_metadata": {"mode": "deterministic"},
        },
    },
    "finalize": {
        "operation": "finalize",
        "payload": {
            "run_id": RUN_ID,
            "attempt_id": ATTEMPT_ID,
            "finalized": True,
            "output_sha256": DIGEST_B,
            "usage": {
                "model_calls": 0,
                "tokens": 0,
                "cpu_ms": 10,
                "peak_rss_bytes": 1024,
                "disk_bytes": 0,
                "network_bytes": 0,
                "storage_bytes": 0,
                "latency_ms": 10,
                "retries": 0,
                "errors": 0,
            },
        },
    },
}

REJECTED_INGEST_RESPONSE = {
    "operation": "ingest",
    "payload": {
        "statuses": [
            {
                "event_id": "event-0002",
                "outcome": "rejected",
                "durability": "not_acknowledged",
                "evidence_handle": None,
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "event was rejected",
                },
            }
        ]
    },
}

ERROR_ENVELOPES = {
    code: {
        "error": {
            "code": code,
            "retriable": code
            in {"RESOURCE_LIMIT", "DEPENDENCY_UNAVAILABLE", "INTERNAL_ERROR"},
            "message": f"closed error: {code.lower()}",
            "details_sha256": DIGEST_C,
        }
    }
    for code in ERROR_CODES
}


def _artifact(schema_id: str, **fields: object) -> dict[str, object]:
    artifact = {"schema_id": schema_id, "artifact_sha256": DIGEST_A, **fields}
    return _rebind_artifact(artifact)


def _rebind_artifact(artifact: dict[str, object]) -> dict[str, object]:
    artifact = deepcopy(artifact)
    payload = {key: value for key, value in artifact.items() if key != "artifact_sha256"}
    artifact["artifact_sha256"] = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            ensure_ascii=False,
        ).encode()
        + b"\n"
    ).hexdigest()
    return artifact


def _sandbox_profile_digest(receipt: dict[str, object]) -> str:
    return abi.canonical_sha256(
        {
            key: value
            for key, value in receipt.items()
            if key not in {"schema_id", "artifact_sha256", "profile_ref"}
        }
    )


EVIDENCE_FIXTURES = {
    "BaselineManifest": _artifact(
        "urn:wmbs:0.1-draft#BaselineManifest",
        tokenizer="tokenizer@sha256:" + DIGEST_A,
        chunking={"size": 512, "overlap": 64},
        embedding_model="embedding@sha256:" + DIGEST_B,
        index_parameters={"metric": "cosine"},
        top_k=5,
        prompt_sha256=DIGEST_C,
        context_order="rank-ascending",
        truncation="tail",
        cache_state="cold",
        setup_cost_usd=0.0,
        indexing_cost_usd=0.0,
        budget={"wall_time_seconds": 60, "memory_bytes": 1_073_741_824},
    ),
    "PowerPlan": _artifact(
        "urn:wmbs:0.1-draft#PowerPlan",
        primary_endpoint="exact_match",
        denominator="admitted_examples",
        independence_unit="fixture",
        sample_size=100,
        power_rationale="Exact deterministic census.",
        seeds=[7, 11],
        reruns=5,
        interval="clopper-pearson-95",
        multiplicity="holm",
        tie_rule="declare-tie",
        missing_data_rule="fail-closed",
        abort_rule="any-safety-rail-failure",
        rerun_rule="preregistered-only",
    ),
    "SoftwareDataBOM": _artifact(
        "urn:wmbs:0.1-draft#SoftwareDataBOM",
        software=[{"name": "python", "version": "3.12", "license": "PSF-2.0"}],
        datasets=[
            {
                "name": "synthetic-golden",
                "declared_license": "CC0-1.0",
                "concluded_license": "CC0-1.0",
                "redistribution": "allowed",
                "lineage": "deterministic-generator",
                "modifications": "none",
                "attribution": "not-required",
                "pii": "none",
                "consent_basis": "not-applicable",
                "privacy_scan": "passed",
                "retention": "repository-lifetime",
                "takedown": "remove-and-version",
            }
        ],
        oci_digest=None,
        lockfile_sha256=DIGEST_B,
        sbom_sha256=DIGEST_C,
        build_provenance_sha256=DIGEST_A,
        external_services=[],
        secret_requirements=[],
    ),
    "SandboxReceipt": _artifact(
        "urn:wmbs:0.1-draft#SandboxReceipt",
        profile_ref="sandbox-l16-dev@sha256:" + L16_PROFILE_DIGEST,
        sut_boundary="adapter-process",
        root_filesystem="read-only",
        uid=65534,
        gid=65534,
        mounts=["inputs:ro", "outputs:rw"],
        environment_allowlist=["LANG", "PATH", "TZ"],
        syscall_policy="platform-sandbox",
        egress={
            "mode": "deny",
            "endpoints": [],
            "block_cloud_metadata": True,
            "block_private_ranges": True,
        },
        secrets="none",
        privilege="unprivileged",
        cpu_limit=1.0,
        memory_limit_bytes=1_073_741_824,
        process_limit=16,
        file_limit=128,
        output_limit_bytes=1_048_576,
        wall_deadline_seconds=60,
        locale="C",
        timezone="UTC",
        cleanup="ephemeral-destroyed",
        log_redaction="secrets-and-direct-personal-data",
        scorer_isolation="separate-process",
        model_proxy="disabled",
        usage_counters="harness-owned",
    ),
    "ResourceReceipt": _artifact(
        "urn:wmbs:0.1-draft#ResourceReceipt",
        profile_sha256=L16_PROFILE_DIGEST,
        sut_boundary="adapter-process",
        wall_time_ms=10,
        peak_rss_bytes=1024,
        host_free_memory_bytes=8_589_934_592,
        swap_bytes=0,
        disk_bytes=0,
        cpu="1 logical core",
        gpu="none",
        workers=1,
        network_bytes=0,
        model_calls=0,
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        cache_state="cold",
        abort_status="completed",
    ),
}
EVIDENCE_FIXTURES["FeasibilityRecord"] = _artifact(
    "urn:wmbs:0.1-draft#FeasibilityRecord",
    identity={
        "module_id": "M01",
        "module_version": "0.1.0",
        "source_commit": "1" * 40,
        "owner_ids": ["WMB-P1", "M15"],
    },
    adapter_contract_ref="wmbs/0.1-draft@sha256:" + DIGEST_A,
    data_source_ref="synthetic-golden@sha256:" + DIGEST_B,
    scorer_ref="exact-match@sha256:" + DIGEST_C,
    inherited_rails=["RAIL-001", "RAIL-002"],
    baseline_manifest_ref=(
        "urn:wmbs:0.1-draft#BaselineManifest@sha256:"
        + EVIDENCE_FIXTURES["BaselineManifest"]["artifact_sha256"]  # type: ignore[operator]
    ),
    power_plan_ref=(
        "urn:wmbs:0.1-draft#PowerPlan@sha256:"
        + EVIDENCE_FIXTURES["PowerPlan"]["artifact_sha256"]  # type: ignore[operator]
    ),
    replay_protocol={
        "canonical_payload": "m15-v1",
        "volatile_fields": sorted(VOLATILE_FIELDS),
        "run_count": 5,
        "seed_encoding": "decimal",
        "float_rule": "finite-json",
        "order_rule": "sorted-keys",
        "time_rule": "utc-z",
        "locale": "C",
        "clean_process_replay": True,
        "artifact_digest": "sha256",
    },
    sandbox_receipt_ref=(
        "urn:wmbs:0.1-draft#SandboxReceipt@sha256:"
        + EVIDENCE_FIXTURES["SandboxReceipt"]["artifact_sha256"]  # type: ignore[operator]
    ),
    resource_receipt_ref=None,
    software_data_bom_ref=(
        "urn:wmbs:0.1-draft#SoftwareDataBOM@sha256:"
        + EVIDENCE_FIXTURES["SoftwareDataBOM"]["artifact_sha256"]  # type: ignore[operator]
    ),
    result_contract={
        "schema_version": "result-v1",
        "metric_family": "development",
        "attempt_state": "finalized",
        "custody": "development-public",
        "compatibility": "no-v1-mutation",
    },
    deferral_condition="official and production variants lack measured receipts",
    feasibility_disposition={
        "development": "PROPOSED",
        "official_local": "DEFERRED",
        "hosted_service": "DEFERRED",
        "production_operations": "DEFERRED",
    },
)


def _resolved_feasibility_bundle() -> tuple[dict[str, object], dict[str, object]]:
    record = deepcopy(EVIDENCE_FIXTURES["FeasibilityRecord"])
    artifacts: dict[str, object] = {}
    for field, artifact in [
        ("adapter_contract_ref", {"protocol": "wmbs/0.1-draft"}),
        ("data_source_ref", {"fixture": "synthetic-golden"}),
        ("scorer_ref", {"command": "score-exact-match"}),
    ]:
        reference = (
            f"{field.removesuffix('_ref')}@sha256:{abi.canonical_sha256(artifact)}"
        )
        record[field] = reference
        artifacts[reference] = artifact
    for field, definition in [
        ("baseline_manifest_ref", "BaselineManifest"),
        ("power_plan_ref", "PowerPlan"),
        ("sandbox_receipt_ref", "SandboxReceipt"),
        ("resource_receipt_ref", "ResourceReceipt"),
        ("software_data_bom_ref", "SoftwareDataBOM"),
    ]:
        artifact = EVIDENCE_FIXTURES[definition]
        reference = (
            f"{artifact['schema_id']}@sha256:{artifact['artifact_sha256']}"
        )
        record[field] = reference
        artifacts[reference] = artifact
    return record, artifacts


def _drop_key(value: dict[str, object], dotted_key: str) -> dict[str, object]:
    mutated = deepcopy(value)
    target: Any = mutated
    parts = dotted_key.split(".")
    for part in parts[:-1]:
        target = target[int(part)] if isinstance(target, list) else target[part]
    target.pop(parts[-1])
    return mutated


def _set_key(
    value: dict[str, object], dotted_key: str, replacement: object
) -> dict[str, object]:
    mutated = deepcopy(value)
    target: Any = mutated
    parts = dotted_key.split(".")
    for part in parts[:-1]:
        target = target[int(part)] if isinstance(target, list) else target[part]
    if isinstance(target, list):
        target[int(parts[-1])] = replacement
    else:
        target[parts[-1]] = replacement
    return mutated


def _at_path(value: object, path: tuple[str | int, ...]) -> object:
    target = value
    for part in path:
        target = target[part]  # type: ignore[index]
    return target


def _resolved_schema(schema: dict[str, object]) -> dict[str, object]:
    reference = schema.get("$ref")
    if isinstance(reference, str):
        return SCHEMA["$defs"][reference.removeprefix("#/$defs/")]
    return schema


def _object_instances(
    schema: dict[str, object],
    value: object,
    path: tuple[str | int, ...] = (),
) -> list[tuple[tuple[str | int, ...], dict[str, object]]]:
    schema = _resolved_schema(schema)
    options = schema.get("anyOf")
    if isinstance(options, list):
        for option in options:
            resolved = _resolved_schema(option)
            expected = resolved.get("type")
            if (expected == "null" and value is None) or (
                expected != "null" and value is not None
            ):
                return _object_instances(resolved, value, path)
        return []
    if isinstance(value, dict):
        instances = [(path, schema)]
        properties = schema.get("properties", {})
        for key, nested in value.items():
            nested_schema = properties.get(key)
            if isinstance(nested_schema, dict):
                instances.extend(_object_instances(nested_schema, nested, (*path, key)))
        return instances
    if isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            return [
                instance
                for index, nested in enumerate(value)
                for instance in _object_instances(item_schema, nested, (*path, index))
            ]
    return []


def _error_code(exc: pytest.ExceptionInfo[Exception]) -> str:
    return exc.value.code  # type: ignore[attr-defined,no-any-return]


def test_red_dependency_is_only_the_missing_schema_and_adapter() -> None:
    assert not _MISSING, "missing RED contract artifacts: " + ", ".join(_MISSING)


@requires_abi
@pytest.mark.parametrize("definition,payload", GOLDEN_REQUESTS.items())
def test_golden_requests_are_closed_and_valid(
    definition: str, payload: dict[str, object]
) -> None:
    assert abi.validate_definition(f"{definition}_request", payload) == payload


@requires_abi
@pytest.mark.parametrize("definition,payload", GOLDEN_RESPONSES.items())
def test_golden_responses_are_closed_and_valid(
    definition: str, payload: dict[str, object]
) -> None:
    assert abi.validate_definition(f"{definition}_response", payload) == payload


@requires_abi
def test_reference_validator_accepts_integral_float_as_json_schema_integer() -> None:
    request = deepcopy(GOLDEN_REQUESTS["negotiate"])
    request["context"]["sequence"] = 1.0  # type: ignore[index]

    assert abi.validate_definition("negotiate_request", request) == request


@requires_abi
def test_reference_validator_uses_json_numeric_equality_for_unique_items() -> None:
    schema = {"type": "array", "items": {"type": "number"}, "uniqueItems": True}

    with pytest.raises(abi.WholeMemoryValidationError):
        abi._validate([1, 1.0], schema, "$")


@requires_abi
@pytest.mark.parametrize(
    ("definition", "payload"),
    [
        *[
            (f"{operation}_request", payload)
            for operation, payload in GOLDEN_REQUESTS.items()
        ],
        *[
            (f"{operation}_response", payload)
            for operation, payload in GOLDEN_RESPONSES.items()
        ],
        ("ingest_response", REJECTED_INGEST_RESPONSE),
        *EVIDENCE_FIXTURES.items(),
        *[("error_response", payload) for payload in ERROR_ENVELOPES.values()],
    ],
)
def test_every_reachable_object_rejects_missing_and_unknown_fields(
    definition: str, payload: dict[str, object]
) -> None:
    schema = SCHEMA["$defs"][definition]
    instances = _object_instances(schema, payload)
    assert instances

    for path, object_schema in instances:
        assert object_schema.get("additionalProperties") is False
        for field in object_schema.get("required", []):
            missing = deepcopy(payload)
            _at_path(missing, path).pop(field)  # type: ignore[union-attr]
            with pytest.raises(abi.WholeMemoryValidationError):
                abi.validate_definition(definition, missing)

        unknown = deepcopy(payload)
        _at_path(unknown, path)["__unknown__"] = True  # type: ignore[index]
        with pytest.raises(abi.WholeMemoryValidationError):
            abi.validate_definition(definition, unknown)


@requires_abi
@pytest.mark.parametrize(("code", "payload"), ERROR_ENVELOPES.items())
def test_error_envelope_accepts_exactly_the_nine_closed_codes(
    code: str, payload: dict[str, object]
) -> None:
    assert abi.validate_definition("error_response", payload) == payload
    assert payload["error"]["code"] == code  # type: ignore[index]


@requires_abi
def test_error_envelope_rejects_unknown_codes() -> None:
    payload = deepcopy(ERROR_ENVELOPES["INTERNAL_ERROR"])
    payload["error"]["code"] = "UNKNOWN"  # type: ignore[index]

    with pytest.raises(abi.WholeMemoryValidationError) as exc:
        abi.validate_definition("error_response", payload)

    assert _error_code(exc) == "INVALID_REQUEST"


@requires_abi
def test_event_error_rejects_codes_outside_closed_set() -> None:
    with pytest.raises(abi.WholeMemoryValidationError) as exc:
        abi.validate_definition("event_error", {"code": "UNKNOWN", "message": "closed"})

    assert _error_code(exc) == "INVALID_REQUEST"


@requires_abi
def test_usage_counters_reject_oversized_values() -> None:
    response = deepcopy(GOLDEN_RESPONSES["finalize"])
    response["payload"]["usage"]["tokens"] = 2**64  # type: ignore[index]

    with pytest.raises(abi.WholeMemoryValidationError) as exc:
        abi.validate_definition("finalize_response", response)

    assert _error_code(exc) == "INVALID_REQUEST"


@requires_abi
@pytest.mark.parametrize(
    ("abstained", "answer_text"),
    [(True, "contradiction"), (False, None)],
)
def test_definition_validator_rejects_contradictory_answers(
    abstained: bool, answer_text: str | None
) -> None:
    response = deepcopy(GOLDEN_RESPONSES["answer"])
    response["payload"]["abstained"] = abstained  # type: ignore[index]
    response["payload"]["answer_text"] = answer_text  # type: ignore[index]

    with pytest.raises(abi.WholeMemoryValidationError):
        abi.validate_definition("answer_response", response)


REQUEST_REJECTIONS: list[
    tuple[str, str, Callable[[dict[str, object]], dict[str, object]], str]
] = [
    (
        "missing field",
        "retrieve",
        lambda value: _drop_key(value, "payload.top_k"),
        "INVALID_REQUEST",
    ),
    (
        "unknown field",
        "retrieve",
        lambda value: {**value, "unknown": "field"},
        "INVALID_REQUEST",
    ),
    (
        "boolean as number",
        "retrieve",
        lambda value: _set_key(value, "payload.top_k", True),
        "INVALID_REQUEST",
    ),
    (
        "non-finite number",
        "retrieve",
        lambda value: _set_key(value, "payload.top_k", math.inf),
        "INVALID_REQUEST",
    ),
    (
        "whitespace-only string",
        "answer",
        lambda value: _set_key(value, "payload.question", "   "),
        "INVALID_REQUEST",
    ),
    (
        "oversized string",
        "answer",
        lambda value: _set_key(value, "payload.question", "x" * 65_537),
        "INVALID_REQUEST",
    ),
    (
        "oversized module version",
        "create_run",
        lambda value: _set_key(value, "payload.module_version", "1" * 65 + ".0.0"),
        "INVALID_REQUEST",
    ),
    (
        "oversized array",
        "ingest",
        lambda value: _set_key(
            value,
            "payload.ordered_events",
            [deepcopy(value["payload"]["ordered_events"][0])] * 1_001,  # type: ignore[index]
        ),
        "INVALID_REQUEST",
    ),
    (
        "malformed digest",
        "ingest",
        lambda value: _set_key(
            value,
            "payload.ordered_events",
            [{**value["payload"]["ordered_events"][0], "content_sha256": "bad"}],  # type: ignore[index]
        ),
        "INVALID_REQUEST",
    ),
    (
        "non-UTC deadline",
        "retrieve",
        lambda value: _set_key(
            value, "context.deadline_utc", "2026-07-29T00:00:00+01:00"
        ),
        "INVALID_REQUEST",
    ),
    (
        "invalid nullable shape",
        "ingest",
        lambda value: _set_key(value, "payload.ordered_events.0.valid_to", {}),
        "INVALID_REQUEST",
    ),
    (
        "constant mismatch",
        "retrieve",
        lambda value: _set_key(value, "operation", "answer"),
        "INVALID_REQUEST",
    ),
    (
        "empty required array",
        "negotiate",
        lambda value: _set_key(value, "payload.supported_protocol_versions", []),
        "INVALID_REQUEST",
    ),
    (
        "duplicate unique array value",
        "negotiate",
        lambda value: _set_key(
            value,
            "payload.supported_protocol_versions",
            [PROTOCOL_VERSION, PROTOCOL_VERSION],
        ),
        "INVALID_REQUEST",
    ),
]


@requires_abi
@pytest.mark.parametrize(
    ("case", "operation", "mutation", "expected_code"),
    REQUEST_REJECTIONS,
    ids=[case[0] for case in REQUEST_REJECTIONS],
)
def test_request_shape_rejections_fail_closed(
    case: str,
    operation: str,
    mutation: Callable[[dict[str, object]], dict[str, object]],
    expected_code: str,
) -> None:
    del case
    with pytest.raises(abi.WholeMemoryValidationError) as exc:
        abi.validate_definition(
            f"{operation}_request", mutation(deepcopy(GOLDEN_REQUESTS[operation]))
        )

    assert _error_code(exc) == expected_code


@requires_abi
@pytest.mark.parametrize(("definition", "payload"), EVIDENCE_FIXTURES.items())
def test_all_six_evidence_definitions_are_digest_bound_and_valid(
    definition: str, payload: dict[str, object]
) -> None:
    assert abi.validate_definition(definition, payload) == payload


@requires_abi
def test_evidence_artifact_digest_rejects_content_tampering() -> None:
    manifest = deepcopy(EVIDENCE_FIXTURES["BaselineManifest"])
    manifest["top_k"] = 6

    with pytest.raises(abi.WholeMemoryValidationError) as exc:
        abi.validate_definition("BaselineManifest", manifest)

    assert _error_code(exc) == "INVALID_REQUEST"


@requires_abi
def test_proposed_feasibility_record_allows_an_explicitly_missing_artifact() -> None:
    record = deepcopy(EVIDENCE_FIXTURES["FeasibilityRecord"])
    record["resource_receipt_ref"] = None
    record = _rebind_artifact(record)

    assert abi.validate_definition("FeasibilityRecord", record) == record


@requires_abi
def test_readiness_requires_resolved_digest_bound_artifacts() -> None:
    record = deepcopy(EVIDENCE_FIXTURES["FeasibilityRecord"])
    record["feasibility_disposition"] = {
        "development": "PILOT-READY-DEV",
        "official_local": "RUN-READY-OFFICIAL-LOCAL",
        "hosted_service": "RUN-READY-HOSTED-X",
        "production_operations": "RUN-READY-P32-OPS",
    }
    record = _rebind_artifact(record)

    with pytest.raises(abi.WholeMemoryValidationError) as exc:
        abi.validate_definition("FeasibilityRecord", record)

    assert _error_code(exc) == "INVALID_REQUEST"


@requires_abi
def test_evidence_bundle_resolves_every_feasibility_reference() -> None:
    record, artifacts = _resolved_feasibility_bundle()
    record["feasibility_disposition"] = {
        "development": "PILOT-READY-DEV",
        "official_local": "DEFERRED",
        "hosted_service": "DEFERRED",
        "production_operations": "DEFERRED",
    }
    record = _rebind_artifact(record)

    assert abi.validate_evidence_bundle(record, artifacts) == record

    changed = deepcopy(artifacts)
    baseline_ref = record["baseline_manifest_ref"]
    assert isinstance(baseline_ref, str)
    changed[baseline_ref] = {
        **EVIDENCE_FIXTURES["BaselineManifest"],
        "top_k": 6,
    }
    with pytest.raises(abi.WholeMemoryValidationError):
        abi.validate_evidence_bundle(record, changed)


@requires_abi
@pytest.mark.parametrize(
    "dispositions",
    [
        {
            "development": "PILOT-READY-DEV",
            "official_local": "RUN-READY-OFFICIAL-LOCAL",
            "hosted_service": "DEFERRED",
            "production_operations": "DEFERRED",
        },
        {
            "development": "DEFERRED",
            "official_local": "RUN-READY-OFFICIAL-LOCAL",
            "hosted_service": "DEFERRED",
            "production_operations": "DEFERRED",
        },
    ],
)
def test_evidence_bundle_rejects_unprovable_run_readiness(
    dispositions: dict[str, str],
) -> None:
    record, artifacts = _resolved_feasibility_bundle()
    record["feasibility_disposition"] = dispositions
    record = _rebind_artifact(record)

    with pytest.raises(
        abi.WholeMemoryValidationError,
        match="run readiness requires profile-specific signed evidence",
    ):
        abi.validate_evidence_bundle(record, artifacts)


@requires_abi
def test_pilot_readiness_requires_finalized_l16_profile_receipt() -> None:
    record, artifacts = _resolved_feasibility_bundle()
    record["feasibility_disposition"] = {
        "development": "PILOT-READY-DEV",
        "official_local": "DEFERRED",
        "hosted_service": "DEFERRED",
        "production_operations": "DEFERRED",
    }

    record["result_contract"]["attempt_state"] = "created"  # type: ignore[index]
    created = _rebind_artifact(record)
    with pytest.raises(
        abi.WholeMemoryValidationError,
        match="pilot readiness requires a finalized attempt",
    ):
        abi.validate_evidence_bundle(created, artifacts)

    record["result_contract"]["attempt_state"] = "finalized"  # type: ignore[index]
    sandbox = _rebind_artifact(
        {
            **EVIDENCE_FIXTURES["SandboxReceipt"],
            "profile_ref": "sandbox-official-local@sha256:" + DIGEST_B,
        }
    )
    old_ref = record["sandbox_receipt_ref"]
    assert isinstance(old_ref, str)
    artifacts.pop(old_ref)
    new_ref = f"{sandbox['schema_id']}@sha256:{sandbox['artifact_sha256']}"
    record["sandbox_receipt_ref"] = new_ref
    artifacts[new_ref] = sandbox
    wrong_profile = _rebind_artifact(record)

    with pytest.raises(
        abi.WholeMemoryValidationError,
        match="pilot readiness requires the L16-DEV sandbox profile",
    ):
        abi.validate_evidence_bundle(wrong_profile, artifacts)


@requires_abi
def test_pilot_readiness_binds_resource_receipt_to_sandbox_profile() -> None:
    record, artifacts = _resolved_feasibility_bundle()
    record["feasibility_disposition"] = {
        "development": "PILOT-READY-DEV",
        "official_local": "DEFERRED",
        "hosted_service": "DEFERRED",
        "production_operations": "DEFERRED",
    }
    resource = _rebind_artifact(
        {
            **EVIDENCE_FIXTURES["ResourceReceipt"],
            "profile_sha256": DIGEST_C,
        }
    )
    old_ref = record["resource_receipt_ref"]
    assert isinstance(old_ref, str)
    artifacts.pop(old_ref)
    new_ref = f"{resource['schema_id']}@sha256:{resource['artifact_sha256']}"
    record["resource_receipt_ref"] = new_ref
    artifacts[new_ref] = resource
    record = _rebind_artifact(record)

    with pytest.raises(
        abi.WholeMemoryValidationError,
        match="resource receipt does not match the sandbox profile",
    ):
        abi.validate_evidence_bundle(record, artifacts)


@requires_abi
def test_pilot_readiness_rejects_unbound_sandbox_profile_digest() -> None:
    record, artifacts = _resolved_feasibility_bundle()
    record["feasibility_disposition"] = {
        "development": "PILOT-READY-DEV",
        "official_local": "DEFERRED",
        "hosted_service": "DEFERRED",
        "production_operations": "DEFERRED",
    }
    sandbox = _rebind_artifact(
        {
            **EVIDENCE_FIXTURES["SandboxReceipt"],
            "profile_ref": "sandbox-l16-dev@sha256:" + DIGEST_C,
        }
    )
    resource = _rebind_artifact(
        {
            **EVIDENCE_FIXTURES["ResourceReceipt"],
            "profile_sha256": DIGEST_C,
        }
    )
    for field, artifact in (
        ("sandbox_receipt_ref", sandbox),
        ("resource_receipt_ref", resource),
    ):
        old_ref = record[field]
        assert isinstance(old_ref, str)
        artifacts.pop(old_ref)
        new_ref = f"{artifact['schema_id']}@sha256:{artifact['artifact_sha256']}"
        record[field] = new_ref
        artifacts[new_ref] = artifact
    record = _rebind_artifact(record)

    with pytest.raises(
        abi.WholeMemoryValidationError,
        match="sandbox profile digest does not match its declared controls",
    ):
        abi.validate_evidence_bundle(record, artifacts)


@requires_abi
@pytest.mark.parametrize("abort_status", ["aborted", "failed"])
def test_pilot_readiness_requires_completed_resource_receipt(
    abort_status: str,
) -> None:
    record, artifacts = _resolved_feasibility_bundle()
    record["feasibility_disposition"] = {
        "development": "PILOT-READY-DEV",
        "official_local": "DEFERRED",
        "hosted_service": "DEFERRED",
        "production_operations": "DEFERRED",
    }
    resource = _rebind_artifact(
        {
            **EVIDENCE_FIXTURES["ResourceReceipt"],
            "abort_status": abort_status,
        }
    )
    old_ref = record["resource_receipt_ref"]
    assert isinstance(old_ref, str)
    artifacts.pop(old_ref)
    new_ref = f"{resource['schema_id']}@sha256:{resource['artifact_sha256']}"
    record["resource_receipt_ref"] = new_ref
    artifacts[new_ref] = resource
    record = _rebind_artifact(record)

    with pytest.raises(
        abi.WholeMemoryValidationError,
        match="readiness requires a completed resource receipt",
    ):
        abi.validate_evidence_bundle(record, artifacts)


@requires_abi
def test_pilot_readiness_requires_the_same_sut_boundary_for_metering() -> None:
    record, artifacts = _resolved_feasibility_bundle()
    record["feasibility_disposition"] = {
        "development": "PILOT-READY-DEV",
        "official_local": "DEFERRED",
        "hosted_service": "DEFERRED",
        "production_operations": "DEFERRED",
    }
    resource = _rebind_artifact(
        {
            **EVIDENCE_FIXTURES["ResourceReceipt"],
            "sut_boundary": "different-process",
        }
    )
    old_ref = record["resource_receipt_ref"]
    assert isinstance(old_ref, str)
    artifacts.pop(old_ref)
    new_ref = f"{resource['schema_id']}@sha256:{resource['artifact_sha256']}"
    record["resource_receipt_ref"] = new_ref
    artifacts[new_ref] = resource
    record = _rebind_artifact(record)

    with pytest.raises(
        abi.WholeMemoryValidationError,
        match="resource receipt does not match the sandbox SUT boundary",
    ):
        abi.validate_evidence_bundle(record, artifacts)


@requires_abi
@pytest.mark.parametrize(
    ("sandbox_changes", "resource_changes"),
    [
        ({"syscall_policy": "unavailable"}, {}),
        (
            {
                "egress": {
                    "mode": "metered-allowlist",
                    "endpoints": [
                        {
                            "endpoint": "external",
                            "dns_names": ["example.com"],
                            "ip_ranges": ["93.184.216.34/32"],
                            "protocols": ["https"],
                        }
                    ],
                    "block_cloud_metadata": True,
                    "block_private_ranges": True,
                }
            },
            {},
        ),
        ({}, {"network_bytes": 1}),
    ],
)
def test_pilot_readiness_requires_enforced_offline_l16_controls(
    sandbox_changes: dict[str, object],
    resource_changes: dict[str, object],
) -> None:
    record, artifacts = _resolved_feasibility_bundle()
    record["feasibility_disposition"] = {
        "development": "PILOT-READY-DEV",
        "official_local": "DEFERRED",
        "hosted_service": "DEFERRED",
        "production_operations": "DEFERRED",
    }
    sandbox = _rebind_artifact(
        {**EVIDENCE_FIXTURES["SandboxReceipt"], **sandbox_changes}
    )
    profile_digest = _sandbox_profile_digest(sandbox)
    sandbox["profile_ref"] = "sandbox-l16-dev@sha256:" + profile_digest
    sandbox = _rebind_artifact(sandbox)
    resource = _rebind_artifact(
        {
            **EVIDENCE_FIXTURES["ResourceReceipt"],
            "profile_sha256": profile_digest,
            **resource_changes,
        }
    )
    for field, artifact in (
        ("sandbox_receipt_ref", sandbox),
        ("resource_receipt_ref", resource),
    ):
        old_ref = record[field]
        assert isinstance(old_ref, str)
        artifacts.pop(old_ref)
        new_ref = f"{artifact['schema_id']}@sha256:{artifact['artifact_sha256']}"
        record[field] = new_ref
        artifacts[new_ref] = artifact
    record = _rebind_artifact(record)

    with pytest.raises(
        abi.WholeMemoryValidationError,
        match="pilot readiness requires enforced offline L16 controls",
    ):
        abi.validate_evidence_bundle(record, artifacts)


@requires_abi
def test_evidence_bundle_rejects_typed_reference_schema_mismatch() -> None:
    record, artifacts = _resolved_feasibility_bundle()
    power_ref = record["power_plan_ref"]
    assert isinstance(power_ref, str)
    record["baseline_manifest_ref"] = power_ref
    record["feasibility_disposition"] = {
        "development": "PILOT-READY-DEV",
        "official_local": "DEFERRED",
        "hosted_service": "DEFERRED",
        "production_operations": "DEFERRED",
    }
    record = _rebind_artifact(record)

    with pytest.raises(abi.WholeMemoryValidationError):
        abi.validate_evidence_bundle(record, artifacts)


@requires_abi
def test_contract_ready_requires_resolved_contract_artifacts() -> None:
    record, artifacts = _resolved_feasibility_bundle()
    record["resource_receipt_ref"] = None
    record["feasibility_disposition"] = {
        "development": "CONTRACT-READY",
        "official_local": "DEFERRED",
        "hosted_service": "DEFERRED",
        "production_operations": "DEFERRED",
    }
    record = _rebind_artifact(record)

    with pytest.raises(abi.WholeMemoryValidationError):
        abi.validate_definition("FeasibilityRecord", record)

    assert abi.validate_evidence_bundle(record, artifacts) == record

    adapter_ref = record["adapter_contract_ref"]
    assert isinstance(adapter_ref, str)
    missing = dict(artifacts)
    missing.pop(adapter_ref)
    with pytest.raises(abi.WholeMemoryValidationError):
        abi.validate_evidence_bundle(record, missing)


@requires_abi
def test_mixed_feasibility_dispositions_are_independent() -> None:
    record, artifacts = _resolved_feasibility_bundle()
    record["feasibility_disposition"] = {
        "development": "PILOT-READY-DEV",
        "official_local": "PROPOSED",
        "hosted_service": "DEFERRED",
        "production_operations": "DEFERRED",
    }
    record = _rebind_artifact(record)

    assert abi.validate_evidence_bundle(record, artifacts) == record


@requires_abi
def test_sandbox_receipt_records_the_complete_isolation_policy() -> None:
    receipt = deepcopy(EVIDENCE_FIXTURES["SandboxReceipt"])

    assert abi.validate_definition("SandboxReceipt", receipt) == receipt


@requires_abi
@pytest.mark.parametrize(
    "egress",
    [
        {
            "mode": "metered-allowlist",
            "endpoints": [],
            "block_cloud_metadata": True,
            "block_private_ranges": True,
        },
        {
            "mode": "deny",
            "endpoints": [
                {
                    "endpoint": "model-proxy",
                    "dns_names": ["proxy.example"],
                    "ip_ranges": ["192.0.2.10/32"],
                    "protocols": ["https"],
                }
            ],
            "block_cloud_metadata": True,
            "block_private_ranges": True,
        },
    ],
)
def test_sandbox_receipt_rejects_egress_mode_allowlist_mismatch(
    egress: dict[str, object],
) -> None:
    receipt = deepcopy(EVIDENCE_FIXTURES["SandboxReceipt"])
    receipt["egress"] = egress
    receipt = _rebind_artifact(receipt)

    with pytest.raises(abi.WholeMemoryValidationError):
        abi.validate_definition("SandboxReceipt", receipt)


@requires_abi
@pytest.mark.parametrize(
    "ip_range",
    ["10.0.0.0/8", "127.0.0.1/32", "169.254.169.254/32", "::1/128"],
)
def test_sandbox_receipt_rejects_non_public_egress_ranges(
    ip_range: str,
) -> None:
    receipt = deepcopy(EVIDENCE_FIXTURES["SandboxReceipt"])
    receipt["egress"] = {
        "mode": "metered-allowlist",
        "endpoints": [
            {
                "endpoint": "forbidden",
                "dns_names": ["example.invalid"],
                "ip_ranges": [ip_range],
                "protocols": ["https"],
            }
        ],
        "block_cloud_metadata": True,
        "block_private_ranges": True,
    }
    receipt = _rebind_artifact(receipt)

    with pytest.raises(
        abi.WholeMemoryValidationError,
        match="egress IP ranges must be globally routable",
    ):
        abi.validate_definition("SandboxReceipt", receipt)


@requires_abi
@pytest.mark.parametrize("module_id", ["M00", "M21", "M99"])
def test_module_ids_are_closed_to_the_twenty_defined_modules(
    module_id: str,
) -> None:
    request = deepcopy(GOLDEN_REQUESTS["create_run"])
    request["payload"]["module_id"] = module_id  # type: ignore[index]
    with pytest.raises(abi.WholeMemoryValidationError):
        abi.validate_definition("create_run_request", request)

    record = deepcopy(EVIDENCE_FIXTURES["FeasibilityRecord"])
    record["identity"]["module_id"] = module_id  # type: ignore[index]
    record = _rebind_artifact(record)
    with pytest.raises(abi.WholeMemoryValidationError):
        abi.validate_definition("FeasibilityRecord", record)


@requires_abi
def test_result_custody_is_closed_to_the_three_disclosure_labels() -> None:
    record = deepcopy(EVIDENCE_FIXTURES["FeasibilityRecord"])
    record["result_contract"]["custody"] = "certified"  # type: ignore[index]
    record = _rebind_artifact(record)

    with pytest.raises(abi.WholeMemoryValidationError):
        abi.validate_definition("FeasibilityRecord", record)


@requires_abi
def test_feasibility_record_covers_all_fourteen_categories() -> None:
    record = EVIDENCE_FIXTURES["FeasibilityRecord"]
    categories = {
        "identity",
        "adapter_contract_ref",
        "data_source_ref",
        "scorer_ref",
        "inherited_rails",
        "baseline_manifest_ref",
        "power_plan_ref",
        "replay_protocol",
        "sandbox_receipt_ref",
        "resource_receipt_ref",
        "software_data_bom_ref",
        "result_contract",
        "deferral_condition",
        "feasibility_disposition",
    }

    assert categories <= record.keys()

    for category in sorted(categories):
        with pytest.raises(abi.WholeMemoryValidationError) as exc:
            abi.validate_definition("FeasibilityRecord", _drop_key(record, category))
        assert _error_code(exc) == "INVALID_REQUEST"


@requires_abi
@pytest.mark.parametrize(
    ("definition", "mutation"),
    [
        (
            "FeasibilityRecord",
            lambda value: _set_key(value, "baseline_manifest_ref", "undigested"),
        ),
        (
            "BaselineManifest",
            lambda value: _set_key(value, "top_k", True),
        ),
        (
            "PowerPlan",
            lambda value: _set_key(value, "sample_size", 0),
        ),
        (
            "SoftwareDataBOM",
            lambda value: _set_key(value, "datasets.0.declared_license", "not-spdx"),
        ),
        (
            "SandboxReceipt",
            lambda value: _set_key(value, "egress", "allow-all"),
        ),
        (
            "ResourceReceipt",
            lambda value: _set_key(value, "cost_usd", math.nan),
        ),
    ],
)
def test_evidence_definitions_reject_invalid_or_unbound_values(
    definition: str,
    mutation: Callable[[dict[str, object]], dict[str, object]],
) -> None:
    mutated = mutation(EVIDENCE_FIXTURES[definition])
    if isinstance(mutated, dict):
        try:
            mutated = _rebind_artifact(mutated)
        except ValueError:
            pass  # Non-finite JSON must fail before artifact digest validation.
    with pytest.raises(abi.WholeMemoryValidationError) as exc:
        abi.validate_definition(definition, mutated)

    assert _error_code(exc) == "INVALID_REQUEST"


@requires_abi
@pytest.mark.parametrize(
    ("field", "license_expression"),
    [
        ("software.0.license", "0BSD"),
        ("datasets.0.declared_license", "MIT OR Apache-2.0"),
        (
            "datasets.0.concluded_license",
            "GPL-2.0-only WITH Classpath-exception-2.0",
        ),
    ],
)
def test_software_data_bom_accepts_approved_spdx_expressions(
    field: str, license_expression: str
) -> None:
    abi.validate_definition(
        "SoftwareDataBOM",
        _rebind_artifact(
            _set_key(EVIDENCE_FIXTURES["SoftwareDataBOM"], field, license_expression)
        ),
    )


@requires_abi
def test_software_data_bom_rejects_unknown_spdx_identifier() -> None:
    with pytest.raises(abi.WholeMemoryValidationError) as exc:
        abi.validate_definition(
            "SoftwareDataBOM",
            _rebind_artifact(
                _set_key(
                    EVIDENCE_FIXTURES["SoftwareDataBOM"],
                    "software.0.license",
                    "FOO",
                )
            ),
        )

    assert _error_code(exc) == "INVALID_REQUEST"


@requires_abi
def test_canonical_json_is_mapping_order_independent_with_stable_sha256() -> None:
    left = {"b": [2, 3], "a": 1}
    right = {"a": 1, "b": [2, 3]}
    expected = b'{"a":1,"b":[2,3]}\n'

    assert abi.canonical_json(left) == expected
    assert abi.canonical_json(right) == expected
    assert (
        abi.canonical_sha256(left)
        == "06d1ac940bec12987f319657ce46130daa57ab2d831421ddb892eba6a4509692"
    )


@requires_abi
@pytest.mark.parametrize("function_name", ["canonical_json", "canonical_projection"])
def test_canonical_helpers_reject_cycles_without_recursion_errors(
    function_name: str,
) -> None:
    value: dict[str, object] = {}
    value["self"] = value

    with pytest.raises(abi.WholeMemoryValidationError):
        getattr(abi, function_name)(value)


@requires_abi
@pytest.mark.parametrize("function_name", ["canonical_json", "canonical_projection"])
def test_canonical_helpers_reject_excessive_depth_without_recursion_errors(
    function_name: str,
) -> None:
    value: dict[str, object] = {}
    for _ in range(1_200):
        value = {"nested": value}

    with pytest.raises(abi.WholeMemoryValidationError) as exc:
        getattr(abi, function_name)(value)

    assert _error_code(exc) == "RESOURCE_LIMIT"


@requires_abi
def test_schema_sha256_is_frozen() -> None:
    assert (
        hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest()
        == "c628b7a1c0f40117ea54f9d759b5308f46debaec988f515d1fec2609f1d7312e"
    )


@requires_abi
def test_schema_patterns_are_portable_and_closed() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    patterns: list[str] = []
    objects: list[dict[str, object]] = []

    def collect(value: object) -> None:
        if isinstance(value, dict):
            if value.get("type") == "object":
                objects.append(value)
            pattern = value.get("pattern")
            if isinstance(pattern, str):
                patterns.append(pattern)
            for nested in value.values():
                collect(nested)
        elif isinstance(value, list):
            for nested in value:
                collect(nested)

    collect(schema)

    assert patterns
    assert objects
    assert all(item.get("additionalProperties") is False for item in objects)
    assert all(
        pattern.startswith("^") and pattern.endswith("$") for pattern in patterns
    )
    assert all(not pattern.startswith("(?") for pattern in patterns)
    assert re.search(schema["$defs"]["sha256"]["pattern"], "x" + DIGEST_A) is None


@requires_abi
def test_evidence_schema_ids_resolve_to_public_anchors() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert urlsplit(schema["$id"]).scheme

    for definition in EVIDENCE_FIXTURES:
        subschema = schema["$defs"][definition]
        assert subschema["$anchor"] == definition
        assert (
            subschema["properties"]["schema_id"]["const"]
            == f"{schema['$id']}#{definition}"
        )


@requires_abi
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("volatile_fields", []),
        ("run_count", 2),
        ("clean_process_replay", False),
    ],
)
def test_m15_replay_protocol_is_frozen(field: str, value: object) -> None:
    record = deepcopy(EVIDENCE_FIXTURES["FeasibilityRecord"])
    record["replay_protocol"][field] = value  # type: ignore[index]
    record = _rebind_artifact(record)

    with pytest.raises(abi.WholeMemoryValidationError):
        abi.validate_definition("FeasibilityRecord", record)


@requires_abi
def test_schema_constants_keep_booleans_distinct_from_numbers() -> None:
    record = deepcopy(EVIDENCE_FIXTURES["FeasibilityRecord"])
    record["replay_protocol"]["clean_process_replay"] = 1  # type: ignore[index]
    record = _rebind_artifact(record)

    with pytest.raises(abi.WholeMemoryValidationError):
        abi.validate_definition("FeasibilityRecord", record)


@requires_abi
def test_m15_projection_excludes_only_frozen_volatile_fields_at_any_depth() -> None:
    value = {
        "run_id": RUN_ID,
        "wall_time_ms": 99,
        "nested": {
            "rss_samples_bytes": [1, 2],
            "signature": "volatile",
            "path": "/volatile/path",
            "runtime_timestamp_utc": "2026-07-28T12:00:00Z",
            "stable": {"score": 1.0},
        },
    }
    expected = b'{"nested":{"stable":{"score":1.0}},"run_id":"run-0001"}\n'

    assert abi.VOLATILE_FIELDS == VOLATILE_FIELDS
    assert abi.canonical_projection(value) == {
        "run_id": RUN_ID,
        "nested": {"stable": {"score": 1.0}},
    }
    assert abi.canonical_json(abi.canonical_projection(value)) == expected
    assert (
        abi.canonical_sha256(abi.canonical_projection(value))
        == "8e0dbcde4c5abee662aa6c1fae210a50556906fc6799bf0ee4fe61c4f7ee10d8"
    )


def _validator() -> Any:
    return abi.ProtocolValidator(now=lambda: datetime(2026, 7, 28, 12, tzinfo=UTC))


def _complete_exchange(validator: Any, operation: str) -> None:
    request = GOLDEN_REQUESTS[operation]
    validator.validate_request(request)
    validator.validate_response(request, GOLDEN_RESPONSES[operation])


@requires_abi
def test_lifecycle_transitions_commit_only_after_successful_responses() -> None:
    validator = _validator()
    negotiate = GOLDEN_REQUESTS["negotiate"]
    validator.validate_request(negotiate)

    with pytest.raises(abi.WholeMemoryValidationError) as pending:
        validator.validate_request(GOLDEN_REQUESTS["create_run"])
    assert _error_code(pending) == "ORDER_VIOLATION"

    validator.validate_response(negotiate, GOLDEN_RESPONSES["negotiate"])
    create = GOLDEN_REQUESTS["create_run"]
    validator.validate_request(create)
    rejected = deepcopy(GOLDEN_RESPONSES["create_run"])
    rejected["payload"]["accepted"] = False  # type: ignore[index]
    validator.validate_response(create, rejected)

    with pytest.raises(abi.WholeMemoryValidationError) as inactive:
        validator.validate_request(GOLDEN_REQUESTS["ingest"])
    assert _error_code(inactive) == "ORDER_VIOLATION"

    retry = _request("create_run", deepcopy(create["payload"]), sequence=3)  # type: ignore[arg-type]
    validator.validate_request(retry)
    validator.validate_response(retry, GOLDEN_RESPONSES["create_run"])
    ingest = _request(
        "ingest",
        deepcopy(GOLDEN_REQUESTS["ingest"]["payload"]),  # type: ignore[arg-type]
        sequence=4,
    )
    assert validator.validate_request(ingest) == ingest


@requires_abi
def test_failed_finalize_response_preserves_active_phase() -> None:
    validator = _validator()
    for operation in ("negotiate", "create_run"):
        _complete_exchange(validator, operation)
    finalize = GOLDEN_REQUESTS["finalize"]
    validator.validate_request(finalize)
    failed = deepcopy(GOLDEN_RESPONSES["finalize"])
    failed["payload"]["finalized"] = False  # type: ignore[index]
    validator.validate_response(finalize, failed)
    retrieve = _request(
        "retrieve",
        deepcopy(GOLDEN_REQUESTS["retrieve"]["payload"]),  # type: ignore[arg-type]
        sequence=7,
    )

    assert validator.validate_request(retrieve) == retrieve


@requires_abi
@pytest.mark.parametrize("operation", ["ingest", "retrieve", "answer"])
def test_finalize_waits_for_every_accepted_active_response(operation: str) -> None:
    validator = _validator()
    for setup_operation in ("negotiate", "create_run"):
        _complete_exchange(validator, setup_operation)
    validator.validate_request(GOLDEN_REQUESTS[operation])

    with pytest.raises(abi.WholeMemoryValidationError) as exc:
        validator.validate_request(GOLDEN_REQUESTS["finalize"])

    assert _error_code(exc) == "ORDER_VIOLATION"
    validator.validate_response(
        GOLDEN_REQUESTS[operation], GOLDEN_RESPONSES[operation]
    )
    assert validator.validate_request(GOLDEN_REQUESTS["finalize"])[
        "operation"
    ] == "finalize"


@requires_abi
def test_cancellation_is_closed_terminal_and_idempotent() -> None:
    invalid = deepcopy(GOLDEN_REQUESTS["finalize"])
    invalid["payload"]["reason"] = "arbitrary"  # type: ignore[index]
    with pytest.raises(abi.WholeMemoryValidationError):
        abi.validate_definition("finalize_request", invalid)

    validator = _validator()
    for operation in ("negotiate", "create_run"):
        _complete_exchange(validator, operation)
    cancellation = deepcopy(GOLDEN_REQUESTS["finalize"])
    cancellation["payload"]["reason"] = "cancelled"  # type: ignore[index]
    validator.validate_request(cancellation)
    validator.validate_response(cancellation, GOLDEN_RESPONSES["finalize"])

    assert validator.validate_request(deepcopy(cancellation)) == cancellation
    assert (
        validator.validate_response(
            deepcopy(cancellation), deepcopy(GOLDEN_RESPONSES["finalize"])
        )
        == GOLDEN_RESPONSES["finalize"]
    )
    with pytest.raises(abi.WholeMemoryValidationError) as terminal:
        validator.validate_request(
            _request(
                "retrieve",
                deepcopy(GOLDEN_REQUESTS["retrieve"]["payload"]),  # type: ignore[arg-type]
                sequence=7,
            )
        )
    assert _error_code(terminal) == "ORDER_VIOLATION"


@requires_abi
def test_response_replay_is_frozen_and_closed_errors_do_not_advance_state() -> None:
    validator = _validator()
    request = GOLDEN_REQUESTS["negotiate"]
    validator.validate_request(request)
    response = ERROR_ENVELOPES["INTERNAL_ERROR"]

    assert validator.validate_response(request, response) == response
    assert validator.validate_response(request, deepcopy(response)) == response
    conflicting = deepcopy(ERROR_ENVELOPES["DEPENDENCY_UNAVAILABLE"])
    with pytest.raises(abi.WholeMemoryValidationError) as conflict:
        validator.validate_response(request, conflicting)
    assert _error_code(conflict) == "CONFLICT"
    with pytest.raises(abi.WholeMemoryValidationError) as inactive:
        validator.validate_request(GOLDEN_REQUESTS["create_run"])
    assert _error_code(inactive) == "ORDER_VIOLATION"


@requires_abi
def test_response_replay_rejects_contradictory_success_receipts() -> None:
    validator = _validator()
    _complete_exchange(validator, "negotiate")
    request = GOLDEN_REQUESTS["create_run"]
    validator.validate_request(request)
    validator.validate_response(request, GOLDEN_RESPONSES["create_run"])
    conflicting = deepcopy(GOLDEN_RESPONSES["create_run"])
    conflicting["payload"]["accepted"] = False  # type: ignore[index]

    with pytest.raises(abi.WholeMemoryValidationError) as conflict:
        validator.validate_response(request, conflicting)

    assert _error_code(conflict) == "CONFLICT"


@requires_abi
def test_response_binding_enforces_retrieval_budget_and_forced_answer() -> None:
    validator = _validator()
    for operation in ("negotiate", "create_run"):
        _complete_exchange(validator, operation)

    retrieve = deepcopy(GOLDEN_REQUESTS["retrieve"])
    retrieve["payload"]["top_k"] = 1  # type: ignore[index]
    validator.validate_request(retrieve)
    oversized = deepcopy(GOLDEN_RESPONSES["retrieve"])
    second = deepcopy(oversized["payload"]["hits"][0])  # type: ignore[index]
    second.update({"rank": 2, "stable_item_id": "item-0002"})
    oversized["payload"]["hits"].append(second)  # type: ignore[index]
    with pytest.raises(abi.WholeMemoryValidationError):
        validator.validate_response(retrieve, oversized)

    answer = GOLDEN_REQUESTS["answer"]
    forced = deepcopy(answer)
    forced["payload"]["response_mode"] = "forced"  # type: ignore[index]
    validator.validate_request(forced)
    abstained = deepcopy(GOLDEN_RESPONSES["answer"])
    abstained["payload"].update(  # type: ignore[union-attr]
        {"abstained": True, "answer_text": None}
    )
    with pytest.raises(abi.WholeMemoryValidationError):
        validator.validate_response(forced, abstained)


@requires_abi
@pytest.mark.parametrize(
    ("abstained", "answer_text"),
    [(False, None), (True, "contradictory answer")],
)
def test_normal_answer_response_enforces_answer_abstention_consistency(
    abstained: bool,
    answer_text: str | None,
) -> None:
    response = deepcopy(GOLDEN_RESPONSES["answer"])
    response["payload"].update(  # type: ignore[union-attr]
        {"abstained": abstained, "answer_text": answer_text}
    )
    validator = Draft202012Validator(SCHEMA).evolve(
        schema=SCHEMA["$defs"]["answer_response"]
    )
    assert list(validator.iter_errors(response))

    protocol_validator = _validator()
    for operation in ("negotiate", "create_run"):
        _complete_exchange(protocol_validator, operation)
    request = GOLDEN_REQUESTS["answer"]
    protocol_validator.validate_request(request)
    with pytest.raises(abi.WholeMemoryValidationError):
        protocol_validator.validate_response(request, response)


@requires_abi
def test_validator_rejects_oversized_response_before_schema_walk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator = _validator()
    for operation in ("negotiate", "create_run"):
        _complete_exchange(validator, operation)
    request = GOLDEN_REQUESTS["retrieve"]
    validator.validate_request(request)
    response = deepcopy(GOLDEN_RESPONSES["retrieve"])
    response["payload"]["hits"][0]["content_or_handle"] = "x" * 1_024  # type: ignore[index]
    response["unexpected"] = True
    monkeypatch.setattr(abi, "_MAX_RESPONSE_BYTES", 512, raising=False)

    with pytest.raises(abi.WholeMemoryValidationError) as exc:
        validator.validate_response(request, response)

    assert _error_code(exc) == "RESOURCE_LIMIT"


@requires_abi
def test_validator_accepts_response_at_exact_byte_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator = _validator()
    for operation in ("negotiate", "create_run"):
        _complete_exchange(validator, operation)
    request = GOLDEN_REQUESTS["retrieve"]
    response = GOLDEN_RESPONSES["retrieve"]
    validator.validate_request(request)
    response_size = len(abi.canonical_json(response))
    monkeypatch.setattr(abi, "_MAX_RESPONSE_BYTES", response_size, raising=False)

    assert validator.validate_response(request, response) == response


@requires_abi
@pytest.mark.parametrize(
    ("definition", "source", "paths"),
    [
        (
            "ingest_request",
            GOLDEN_REQUESTS["ingest"],
            (
                "payload.ordered_events.0.valid_from",
                "payload.ordered_events.0.valid_to",
                "payload.ordered_events.0.modality_handle",
            ),
        ),
        (
            "ingest_response",
            GOLDEN_RESPONSES["ingest"],
            ("payload.statuses.0.evidence_handle", "payload.statuses.0.error"),
        ),
        ("retrieve_response", GOLDEN_RESPONSES["retrieve"], ("payload.hits.0.score",)),
        (
            "answer_response",
            GOLDEN_RESPONSES["answer"],
            ("payload.answer_text", "payload.confidence"),
        ),
        (
            "error_response",
            ERROR_ENVELOPES["INTERNAL_ERROR"],
            ("error.details_sha256",),
        ),
    ],
)
def test_spec_optional_fields_may_be_omitted(
    definition: str,
    source: dict[str, object],
    paths: tuple[str, ...],
) -> None:
    value = deepcopy(source)
    if definition == "answer_response":
        value["payload"]["abstained"] = True  # type: ignore[index]
        value["payload"]["answer_text"] = None  # type: ignore[index]
    for path in paths:
        value = _drop_key(value, path)

    assert abi.validate_definition(definition, value) == value


@requires_abi
def test_state_machine_accepts_frozen_operation_order() -> None:
    validator = _validator()
    for operation in (
        "negotiate",
        "create_run",
        "ingest",
        "retrieve",
        "answer",
        "finalize",
    ):
        assert validator.validate_request(GOLDEN_REQUESTS[operation])["operation"] == (
            operation
        )
        validator.validate_response(
            GOLDEN_REQUESTS[operation], GOLDEN_RESPONSES[operation]
        )


@requires_abi
def test_identical_idempotent_replay_does_not_advance_state() -> None:
    validator = _validator()
    _complete_exchange(validator, "negotiate")
    request = GOLDEN_REQUESTS["create_run"]

    first = validator.validate_request(request)
    replay = validator.validate_request(deepcopy(request))

    assert replay == first
    assert validator.last_sequence == 2


@requires_abi
def test_identical_idempotent_replay_survives_original_deadline() -> None:
    current_time = [datetime(2026, 7, 28, 12, tzinfo=UTC)]
    validator = abi.ProtocolValidator(now=lambda: current_time[0])
    request = GOLDEN_REQUESTS["negotiate"]

    first = validator.validate_request(request)
    validator.validate_response(request, GOLDEN_RESPONSES["negotiate"])
    current_time[0] = datetime(2026, 7, 30, 12, tzinfo=UTC)

    assert validator.validate_request(deepcopy(request)) == first


@requires_abi
def test_idempotent_replay_is_isolated_from_caller_mutation() -> None:
    validator = _validator()
    _complete_exchange(validator, "negotiate")
    request = GOLDEN_REQUESTS["create_run"]
    expected = deepcopy(request)

    first = validator.validate_request(request)
    first["payload"]["module_id"] = "M99"  # type: ignore[index]
    replay = validator.validate_request(deepcopy(request))
    replay["payload"]["module_id"] = "M98"  # type: ignore[index]

    assert validator.validate_request(deepcopy(request)) == expected


@requires_abi
def test_validator_rejects_cross_scope_requests() -> None:
    validator = _validator()
    _complete_exchange(validator, "negotiate")
    request = deepcopy(GOLDEN_REQUESTS["create_run"])
    request["context"]["tenant_id"] = "tenant-0002"  # type: ignore[index]

    with pytest.raises(abi.WholeMemoryValidationError) as exc:
        validator.validate_request(request)

    assert _error_code(exc) == "CONFLICT"


@requires_abi
def test_validator_bounds_retained_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(abi, "_MAX_REQUESTS", 1)
    validator = _validator()
    _complete_exchange(validator, "negotiate")

    with pytest.raises(abi.WholeMemoryValidationError) as exc:
        validator.validate_request(GOLDEN_REQUESTS["create_run"])

    assert _error_code(exc) == "RESOURCE_LIMIT"


@requires_abi
def test_validator_rejects_oversized_request_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator = _validator()
    _complete_exchange(validator, "negotiate")
    _complete_exchange(validator, "create_run")
    monkeypatch.setattr(abi, "_MAX_REQUEST_BYTES", 512)
    request = deepcopy(GOLDEN_REQUESTS["ingest"])
    request["payload"]["ordered_events"][0]["content"] = "x" * 1_024  # type: ignore[index]

    with pytest.raises(abi.WholeMemoryValidationError) as exc:
        validator.validate_request(request)

    assert _error_code(exc) == "RESOURCE_LIMIT"


@requires_abi
def test_validator_rejects_oversized_malformed_request_before_schema_walk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = deepcopy(GOLDEN_REQUESTS["negotiate"])
    request["unexpected"] = "x" * 1_024
    monkeypatch.setattr(abi, "_MAX_REQUEST_BYTES", 512)

    with pytest.raises(abi.WholeMemoryValidationError) as exc:
        _validator().validate_request(request)

    assert _error_code(exc) == "RESOURCE_LIMIT"


@requires_abi
def test_canonical_size_guard_stops_before_traversing_oversized_primitive_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CountingList(list[object]):
        visited = 0

        def __iter__(self):  # type: ignore[no-untyped-def]
            for item in super().__iter__():
                self.visited += 1
                yield item

    value = CountingList([0] * 100)
    monkeypatch.setattr(abi, "_MAX_RETAINED_BYTES", 16)

    with pytest.raises(abi.WholeMemoryValidationError) as exc:
        abi.canonical_json(value)

    assert _error_code(exc) == "RESOURCE_LIMIT"
    assert value.visited < len(value)


@requires_abi
def test_validator_rejects_deeply_nested_malformed_request_without_crashing() -> None:
    nested: dict[str, object] = {}
    for _ in range(1_200):
        nested = {"nested": nested}

    with pytest.raises(abi.WholeMemoryValidationError) as exc:
        _validator().validate_request({"operation": "negotiate", "unexpected": nested})

    assert _error_code(exc) == "RESOURCE_LIMIT"


@requires_abi
def test_validator_rejects_cyclic_malformed_request_without_hanging() -> None:
    request: dict[str, object] = {"operation": "negotiate"}
    request["unexpected"] = request

    with pytest.raises(abi.WholeMemoryValidationError) as exc:
        _validator().validate_request(request)

    assert _error_code(exc) == "INVALID_REQUEST"


@requires_abi
def test_validator_accepts_request_at_exact_byte_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = GOLDEN_REQUESTS["negotiate"]
    size = len(abi.canonical_json(request))
    monkeypatch.setattr(abi, "_MAX_REQUEST_BYTES", size)

    assert _validator().validate_request(request) == request
    monkeypatch.setattr(abi, "_MAX_REQUEST_BYTES", size - 1)
    with pytest.raises(abi.WholeMemoryValidationError) as exc:
        _validator().validate_request(request)
    assert _error_code(exc) == "RESOURCE_LIMIT"


@requires_abi
def test_validator_rejects_cumulative_retained_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator = _validator()
    _complete_exchange(validator, "negotiate")
    _complete_exchange(validator, "create_run")
    retained = validator._retained_bytes
    monkeypatch.setattr(abi, "_MAX_RETAINED_BYTES", retained + 1)

    with pytest.raises(abi.WholeMemoryValidationError) as exc:
        validator.validate_request(GOLDEN_REQUESTS["ingest"])

    assert _error_code(exc) == "RESOURCE_LIMIT"
    assert validator.last_sequence == 2
    assert validator._retained_bytes == retained


@requires_abi
def test_validator_accepts_request_at_exact_retained_byte_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = GOLDEN_REQUESTS["negotiate"]
    size = len(abi.canonical_json(request))
    monkeypatch.setattr(abi, "_MAX_RETAINED_BYTES", size)

    assert _validator().validate_request(request) == request
    monkeypatch.setattr(abi, "_MAX_RETAINED_BYTES", size - 1)
    with pytest.raises(abi.WholeMemoryValidationError) as exc:
        _validator().validate_request(request)
    assert _error_code(exc) == "RESOURCE_LIMIT"


@requires_abi
@pytest.mark.parametrize(
    ("definition", "mutation"),
    [
        (
            "ingest_request",
            lambda value: _set_key(
                value, "payload.ordered_events.0.valid_to", "2026-07-27T12:00:00Z"
            ),
        ),
        (
            "retrieve_response",
            lambda value: _set_key(
                value,
                "payload.hits",
                [
                    value["payload"]["hits"][0],  # type: ignore[index]
                    {
                        **value["payload"]["hits"][0],  # type: ignore[index]
                        "rank": 2,
                    },
                ],
            ),
        ),
        (
            "retrieve_response",
            lambda value: _set_key(
                value,
                "payload.hits",
                [
                    {
                        **value["payload"]["hits"][0],  # type: ignore[index]
                        "rank": 2,
                        "stable_item_id": "item-0002",
                    }
                ],
            ),
        ),
    ],
)
def test_cross_field_semantics_fail_closed(
    definition: str,
    mutation: Callable[[dict[str, object]], dict[str, object]],
) -> None:
    source = (
        GOLDEN_REQUESTS["ingest"]
        if definition == "ingest_request"
        else GOLDEN_RESPONSES["retrieve"]
    )

    with pytest.raises(abi.WholeMemoryValidationError):
        abi.validate_definition(definition, mutation(deepcopy(source)))


@requires_abi
def test_cross_field_semantics_accept_valid_boundaries() -> None:
    ingest = deepcopy(GOLDEN_REQUESTS["ingest"])
    event = ingest["payload"]["ordered_events"][0]  # type: ignore[index]
    event["valid_to"] = event["valid_from"]
    assert abi.validate_definition("ingest_request", ingest) == ingest

    retrieve = deepcopy(GOLDEN_RESPONSES["retrieve"])
    second = deepcopy(retrieve["payload"]["hits"][0])  # type: ignore[index]
    second.update({"rank": 2, "stable_item_id": "item-0002"})
    retrieve["payload"]["hits"].append(second)  # type: ignore[index]
    assert abi.validate_definition("retrieve_response", retrieve) == retrieve


@requires_abi
@pytest.mark.parametrize(
    ("outcome", "durability", "evidence_handle", "error"),
    [
        ("accepted", "not_acknowledged", "evidence-0001", None),
        (
            "accepted",
            "acknowledged",
            "evidence-0001",
            {"code": "INVALID_REQUEST", "message": "contradiction"},
        ),
        (
            "rejected",
            "acknowledged",
            None,
            {"code": "INVALID_REQUEST", "message": "rejected"},
        ),
        (
            "rejected",
            "not_acknowledged",
            "evidence-0001",
            {"code": "INVALID_REQUEST", "message": "rejected"},
        ),
        ("rejected", "not_acknowledged", None, None),
    ],
)
def test_ingest_status_outcome_matrix_fails_closed(
    outcome: str,
    durability: str,
    evidence_handle: str | None,
    error: dict[str, str] | None,
) -> None:
    response = deepcopy(GOLDEN_RESPONSES["ingest"])
    response["payload"]["statuses"][0].update(  # type: ignore[index]
        {
            "outcome": outcome,
            "durability": durability,
            "evidence_handle": evidence_handle,
            "error": error,
        }
    )

    with pytest.raises(abi.WholeMemoryValidationError):
        abi.validate_definition("ingest_response", response)


@requires_abi
def test_draft_2020_12_schema_requires_rejected_ingest_error() -> None:
    response = deepcopy(GOLDEN_RESPONSES["ingest"])
    status = response["payload"]["statuses"][0]  # type: ignore[index]
    status.update(  # type: ignore[union-attr]
        {
            "outcome": "rejected",
            "durability": "not_acknowledged",
            "evidence_handle": None,
        }
    )
    status.pop("error")  # type: ignore[union-attr]

    validator = Draft202012Validator(SCHEMA).evolve(
        schema=SCHEMA["$defs"]["ingest_response"]
    )
    assert list(validator.iter_errors(response))


@requires_abi
def test_protocol_validator_binds_ingest_receipt_to_request_event_order() -> None:
    validator = _validator()
    _complete_exchange(validator, "negotiate")
    _complete_exchange(validator, "create_run")
    request = deepcopy(GOLDEN_REQUESTS["ingest"])
    second_event = deepcopy(request["payload"]["ordered_events"][0])  # type: ignore[index]
    second_event["event_id"] = "event-0002"
    request["payload"]["ordered_events"].append(second_event)  # type: ignore[index]
    validator.validate_request(request)

    response = deepcopy(GOLDEN_RESPONSES["ingest"])
    second_status = deepcopy(response["payload"]["statuses"][0])  # type: ignore[index]
    second_status.update({"event_id": "event-0002", "outcome": "deduplicated"})
    response["payload"]["statuses"].append(second_status)  # type: ignore[index]

    for event_ids in (
        ["event-0001"],
        ["event-0002", "event-0001"],
        ["event-0001", "unrelated-event"],
    ):
        malformed = deepcopy(response)
        malformed["payload"]["statuses"] = [  # type: ignore[index]
            {
                **response["payload"]["statuses"][index],  # type: ignore[index]
                "event_id": event_id,
            }
            for index, event_id in enumerate(event_ids)
        ]
        with pytest.raises(
            abi.WholeMemoryValidationError,
            match="ingest statuses do not match request event order",
        ):
            validator.validate_response(request, malformed)
    assert validator.validate_response(request, response) == response


@requires_abi
@pytest.mark.parametrize("field", ["run_id", "attempt_id"])
def test_protocol_validator_binds_receipt_scope_to_request_context(field: str) -> None:
    validator = _validator()
    _complete_exchange(validator, "negotiate")
    request = GOLDEN_REQUESTS["create_run"]
    validator.validate_request(request)
    response = deepcopy(GOLDEN_RESPONSES["create_run"])

    malformed = deepcopy(response)
    malformed["payload"][field] = f"other-{field}"  # type: ignore[index]
    with pytest.raises(
        abi.WholeMemoryValidationError,
        match=rf"response {field} does not match request context",
    ):
        validator.validate_response(request, malformed)
    assert validator.validate_response(request, response) == response


@requires_abi
def test_canonical_inputs_reject_non_string_object_keys() -> None:
    with pytest.raises(abi.WholeMemoryValidationError):
        abi.canonical_json({1: "value"})
    with pytest.raises(abi.WholeMemoryValidationError):
        abi.validate_definition("public_metadata", {1: "value"})


@requires_abi
@pytest.mark.parametrize(
    ("value", "expected_code"),
    [
        (None, "INVALID_REQUEST"),
        ({"operation": "purge"}, "UNSUPPORTED_OPERATION"),
    ],
)
def test_validator_entry_guards_fail_closed(value: object, expected_code: str) -> None:
    with pytest.raises(abi.WholeMemoryValidationError) as exc:
        _validator().validate_request(value)

    assert _error_code(exc) == expected_code


@requires_abi
@pytest.mark.parametrize(
    ("request_value", "expected_code"),
    [
        (None, "INVALID_REQUEST"),
        ({"operation": "purge"}, "UNSUPPORTED_OPERATION"),
        (GOLDEN_REQUESTS["negotiate"], "CONFLICT"),
    ],
)
def test_response_entry_guards_fail_closed_without_mutating_state(
    request_value: object,
    expected_code: str,
) -> None:
    validator = _validator()

    with pytest.raises(abi.WholeMemoryValidationError) as exc:
        validator.validate_response(request_value, GOLDEN_RESPONSES["negotiate"])

    assert _error_code(exc) == expected_code
    assert validator.last_sequence == 0
    assert validator._replays == {}
    assert validator._responses == {}


@requires_abi
def test_unknown_definition_and_reference_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(abi.WholeMemoryValidationError) as unknown:
        abi.validate_definition("missing", {})
    assert _error_code(unknown) == "INVALID_REQUEST"

    monkeypatch.setitem(abi._DEFINITIONS, "broken", {"$ref": "#/$defs/missing"})
    with pytest.raises(abi.WholeMemoryValidationError) as reference:
        abi.validate_definition("broken", {})
    assert _error_code(reference) == "INVALID_REQUEST"


STATE_REJECTIONS = [
    ("stale deadline", "DEADLINE_EXCEEDED"),
    ("deadline equal to now", "DEADLINE_EXCEEDED"),
    ("duplicate request id", "CONFLICT"),
    ("conflicting idempotency reuse", "CONFLICT"),
    ("sequence regression", "ORDER_VIOLATION"),
    ("invalid operation order", "ORDER_VIOLATION"),
    ("post-finalize request", "ORDER_VIOLATION"),
]


@requires_abi
@pytest.mark.parametrize(
    ("case", "expected_code"),
    STATE_REJECTIONS,
    ids=[case[0] for case in STATE_REJECTIONS],
)
def test_stateful_rejections_are_closed(case: str, expected_code: str) -> None:
    validator = _validator()
    _complete_exchange(validator, "negotiate")

    if case in {"stale deadline", "deadline equal to now"}:
        request = deepcopy(GOLDEN_REQUESTS["create_run"])
        request["context"]["deadline_utc"] = (  # type: ignore[index]
            "2026-07-28T11:59:59Z"
            if case == "stale deadline"
            else "2026-07-28T12:00:00Z"
        )
    elif case == "duplicate request id":
        _complete_exchange(validator, "create_run")
        request = deepcopy(GOLDEN_REQUESTS["ingest"])
        request["context"]["request_id"] = "request-0002"  # type: ignore[index]
    elif case == "conflicting idempotency reuse":
        _complete_exchange(validator, "create_run")
        request = deepcopy(GOLDEN_REQUESTS["ingest"])
        request["context"]["idempotency_key"] = "idempotency-0002"  # type: ignore[index]
    elif case == "sequence regression":
        _complete_exchange(validator, "create_run")
        request = deepcopy(GOLDEN_REQUESTS["ingest"])
        request["context"]["sequence"] = 1  # type: ignore[index]
    elif case == "invalid operation order":
        request = GOLDEN_REQUESTS["retrieve"]
    else:
        for operation in ("create_run", "finalize"):
            _complete_exchange(validator, operation)
        request = deepcopy(GOLDEN_REQUESTS["retrieve"])
        request["context"].update(  # type: ignore[union-attr]
            {
                "request_id": "request-0007",
                "idempotency_key": "idempotency-0007",
                "sequence": 7,
            }
        )

    with pytest.raises(abi.WholeMemoryValidationError) as exc:
        validator.validate_request(request)

    assert _error_code(exc) == expected_code
