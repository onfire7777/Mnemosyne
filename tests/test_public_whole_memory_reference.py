from __future__ import annotations

import hashlib
import importlib
import math
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

PROTOCOL_VERSION = "wmbs/0.1-draft"
SCHEMA_PATH = Path("eval/public/schema/wmbs-0.1-draft.schema.json")
ADAPTER_PATH = Path("eval/public/adapters/whole_memory_reference.py")
ERROR_CODES = {
    "INVALID_REQUEST",
    "UNSUPPORTED_OPERATION",
    "UNAUTHORIZED",
    "CONFLICT",
    "ORDER_VIOLATION",
    "DEADLINE_EXCEEDED",
    "RESOURCE_LIMIT",
    "DEPENDENCY_UNAVAILABLE",
    "INTERNAL_ERROR",
}
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
    return {"schema_id": schema_id, "artifact_sha256": DIGEST_A, **fields}


EVIDENCE_FIXTURES = {
    "BaselineManifest": _artifact(
        "wmbs/0.1-draft#BaselineManifest",
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
        "wmbs/0.1-draft#PowerPlan",
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
        "wmbs/0.1-draft#SoftwareDataBOM",
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
        "wmbs/0.1-draft#SandboxReceipt",
        profile_sha256=DIGEST_B,
        sut_boundary="adapter-process",
        uid=65534,
        gid=65534,
        mounts=["inputs:ro", "outputs:rw"],
        egress="deny",
        secrets="none",
        privilege="unprivileged",
        cpu_limit=1.0,
        memory_limit_bytes=1_073_741_824,
        process_limit=16,
        file_limit=128,
        output_limit_bytes=1_048_576,
        wall_deadline_seconds=60,
        scorer_isolation="separate-process",
        model_proxy="disabled",
        usage_counters="harness-owned",
    ),
    "ResourceReceipt": _artifact(
        "wmbs/0.1-draft#ResourceReceipt",
        profile_sha256=DIGEST_B,
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
    "wmbs/0.1-draft#FeasibilityRecord",
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
        "wmbs/0.1-draft#BaselineManifest@sha256:"
        + EVIDENCE_FIXTURES["BaselineManifest"]["artifact_sha256"]  # type: ignore[operator]
    ),
    power_plan_ref=(
        "wmbs/0.1-draft#PowerPlan@sha256:"
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
        "wmbs/0.1-draft#SandboxReceipt@sha256:"
        + EVIDENCE_FIXTURES["SandboxReceipt"]["artifact_sha256"]  # type: ignore[operator]
    ),
    resource_receipt_ref=(
        "wmbs/0.1-draft#ResourceReceipt@sha256:"
        + EVIDENCE_FIXTURES["ResourceReceipt"]["artifact_sha256"]  # type: ignore[operator]
    ),
    software_data_bom_ref=(
        "wmbs/0.1-draft#SoftwareDataBOM@sha256:"
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


def _drop_key(value: dict[str, object], dotted_key: str) -> dict[str, object]:
    mutated = deepcopy(value)
    target: dict[str, object] = mutated
    parts = dotted_key.split(".")
    for part in parts[:-1]:
        target = target[part]  # type: ignore[assignment]
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
            value, "payload.ordered_events", [{**value["payload"]["ordered_events"][0], "content_sha256": "bad"}]  # type: ignore[index]
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
            abi.validate_definition(
                "FeasibilityRecord", _drop_key(record, category)
            )
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
            lambda value: _set_key(
                value, "datasets.0.declared_license", "not-spdx"
            ),
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
    with pytest.raises(abi.WholeMemoryValidationError) as exc:
        abi.validate_definition(definition, mutation(EVIDENCE_FIXTURES[definition]))

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
def test_schema_sha256_is_frozen() -> None:
    assert (
        hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest()
        == "e5239b2cdc9694a15b87c02d7afbe89628245f8cbd6268dc7aceec1afff23155"
    )


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


@requires_abi
def test_identical_idempotent_replay_does_not_advance_state() -> None:
    validator = _validator()
    validator.validate_request(GOLDEN_REQUESTS["negotiate"])
    request = GOLDEN_REQUESTS["create_run"]

    first = validator.validate_request(request)
    replay = validator.validate_request(deepcopy(request))

    assert replay == first
    assert validator.last_sequence == 2


STATE_REJECTIONS = [
    ("stale deadline", "DEADLINE_EXCEEDED"),
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
    validator.validate_request(GOLDEN_REQUESTS["negotiate"])

    if case == "stale deadline":
        request = deepcopy(GOLDEN_REQUESTS["create_run"])
        request["context"]["deadline_utc"] = "2026-07-28T11:59:59Z"  # type: ignore[index]
    elif case == "duplicate request id":
        validator.validate_request(GOLDEN_REQUESTS["create_run"])
        request = deepcopy(GOLDEN_REQUESTS["ingest"])
        request["context"]["request_id"] = "request-0002"  # type: ignore[index]
    elif case == "conflicting idempotency reuse":
        validator.validate_request(GOLDEN_REQUESTS["create_run"])
        request = deepcopy(GOLDEN_REQUESTS["ingest"])
        request["context"]["idempotency_key"] = "idempotency-0002"  # type: ignore[index]
    elif case == "sequence regression":
        validator.validate_request(GOLDEN_REQUESTS["create_run"])
        request = deepcopy(GOLDEN_REQUESTS["ingest"])
        request["context"]["sequence"] = 1  # type: ignore[index]
    elif case == "invalid operation order":
        request = GOLDEN_REQUESTS["retrieve"]
    else:
        for operation in ("create_run", "finalize"):
            validator.validate_request(GOLDEN_REQUESTS[operation])
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
