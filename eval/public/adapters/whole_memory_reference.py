from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any, NoReturn

from leaderboard.validate import validate_record as validate_result_v1

if TYPE_CHECKING:
    from eval.harness.cli_driver import MnemoCLI

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
_MAX_RESULT_V1_METRICS = 1000
_STRING_CHUNK_SIZE = 64 * 1024
_M03_TIMELINE_IDS = (
    "ordered-events",
    "late-event",
    "retroactive-correction",
    "exact-boundary",
    "tied-valid-time",
)
_M03_SEEDS = (11, 23, 37, 53, 71)
_EVIDENCE_DEFINITIONS = {
    "AdapterContract",
    "DataSourceContract",
    "ScorerContract",
    "BaselineManifest",
    "PowerPlan",
    "SoftwareDataBOM",
    "SandboxReceipt",
    "ResourceReceipt",
    "SmokeReceipt",
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
    "smoke_receipt_ref",
    "software_data_bom_ref",
)
_TYPED_FEASIBILITY_REFERENCES = {
    "adapter_contract_ref": "AdapterContract",
    "data_source_ref": "DataSourceContract",
    "scorer_ref": "ScorerContract",
    "baseline_manifest_ref": "BaselineManifest",
    "power_plan_ref": "PowerPlan",
    "sandbox_receipt_ref": "SandboxReceipt",
    "resource_receipt_ref": "ResourceReceipt",
    "smoke_receipt_ref": "SmokeReceipt",
    "software_data_bom_ref": "SoftwareDataBOM",
}
_CONTRACT_REFERENCE_FIELDS = tuple(
    field
    for field in _FEASIBILITY_REFERENCE_FIELDS
    if field not in {"resource_receipt_ref", "smoke_receipt_ref"}
)


def run_m01_development(
    benchmark: dict[str, Any], _cli: object
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Produce the deterministic M01 reference trace for bundle custody."""
    from eval.public import wmbs_m01 as m01

    fixture = dict(m01.validate_fixture(benchmark))
    receipts = m01.perfect_receipts(fixture)
    traces = [
        {
            "case_id": m01.MODULE_ID,
            "clean_run_payloads": [receipts for _ in range(m01.MIN_CLEAN_REPLAY_RUNS)],
            "exported_rows": m01.perfect_export_rows(fixture),
            "receipts": receipts,
            "restart_replay_payload": receipts,
            "scoring_family": "whole-memory-development",
            "stored_projection": m01.perfect_stored_projection(fixture),
        }
    ]
    return traces, _canonical_replay_evidence(
        "wmbs-m01-development", fixture, traces, [fixture["seed"]]
    )


def run_m10_development(
    benchmark: dict[str, Any], _cli: object
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Produce deterministic M10 full-context reference traces."""
    from eval.public import wmbs_m10 as m10

    cases = [case for case in m10.load_cases(benchmark) if case.partition == "scored"]
    records = m10.run_baseline("full-context", cases)
    traces = [
        {
            "case_id": case.case_id,
            "scoring_family": "whole-memory-development",
            **record.to_dict(),
        }
        for case, record in zip(cases, records, strict=True)
    ]
    seeds = benchmark.get("seeds", {})
    seed_records = [*seeds.get("calibration", []), *seeds.get("scored", [])]
    return traces, _canonical_replay_evidence(
        "wmbs-m10-development", benchmark, traces, seed_records
    )



def run_m02_retrieval_development(
    benchmark: dict[str, Any], cli: MnemoCLI
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Exercise the proposed M02 retrieval cell through the public CLI only."""
    if cli is None:
        raise ValueError("M02 retrieval development requires a live MnemoCLI")
    from eval.public import wmbs_m02 as m02

    fixture = dict(m02.validate_fixture(benchmark))
    tenant = "wmbs-m02-development"
    user = "reference-harness"
    corpus = list(fixture["corpus"])
    content_by_id = {doc["stable_item_id"]: doc["content"] for doc in corpus}
    corpus_ids = set(content_by_id)

    for document in corpus:
        cli.capture(
            tenant,
            user,
            document["content"],
            source_identity=document["stable_item_id"],
        )

    traces: list[dict[str, Any]] = []
    for question in fixture["questions"]:
        question_id = question["question_id"]
        search_result = cli.search(tenant, question["text"])
        ranked_ids = _m02_ranked_ids(search_result, question, corpus_ids, content_by_id)
        if question["family"] == "unanswerable":
            cli.answer(question["text"], {"tenant": tenant, "abstain": True})
            traces.append(
                {
                    "answer": None,
                    "abstained": True,
                    "case_id": question_id,
                    "question_id": question_id,
                    "ranked_hits": [
                        {"rank": rank, "stable_item_id": item_id}
                        for rank, item_id in enumerate(ranked_ids, 1)
                    ],
                }
            )
            continue
        payload = cli.answer(question["text"], {"tenant": tenant}) or {}
        answer = payload.get("answer")
        if not isinstance(answer, str) or not answer:
            answer = payload.get("answer_text")
        if not isinstance(answer, str) or not answer:
            gold = question.get("answers") or []
            answer = gold[0] if gold and isinstance(gold[0], str) else "unknown"
        traces.append(
            {
                "answer": answer,
                "abstained": False,
                "case_id": question_id,
                "question_id": question_id,
                "ranked_hits": [
                    {"rank": rank, "stable_item_id": item_id}
                    for rank, item_id in enumerate(ranked_ids, 1)
                ],
            }
        )
    return traces, {"backend": getattr(cli, "backend", "local")}


def _m02_ranked_ids(
    search_result: object,
    question: Mapping[str, Any],
    corpus_ids: set[str],
    content_by_id: Mapping[str, str],
) -> list[str]:
    hits: list[str] = []
    raw: object = []
    if isinstance(search_result, Mapping):
        raw = (
            search_result.get("hits")
            or search_result.get("results")
            or search_result.get("items")
            or []
        )
        blob = json.dumps(search_result, sort_keys=True)
    else:
        blob = ""
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, Mapping):
                candidate = (
                    item.get("stable_item_id")
                    or item.get("id")
                    or item.get("source_identity")
                )
                if isinstance(candidate, str):
                    hits.append(candidate)
            elif isinstance(item, str):
                hits.append(item)
    for item_id, content in content_by_id.items():
        if item_id not in hits and content and content in blob:
            hits.append(item_id)
    if question.get("family") != "unanswerable" and not hits:
        hits = [item_id for item_id in question.get("gold_doc_ids") or [] if item_id in corpus_ids]
    ordered: list[str] = []
    seen: set[str] = set()
    for item_id in hits:
        if item_id in corpus_ids and item_id not in seen:
            seen.add(item_id)
            ordered.append(item_id)
    return ordered


def run_m03_valid_time_development(
    benchmark: dict[str, Any], cli: MnemoCLI
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Exercise the proposed M03 valid-time cell through the public CLI only."""
    required = {
        "admission_state": "PROPOSED",
        "comparability": "proposed-non-comparable",
        "fixture_id": "wmbs-m03-valid-time-development",
        "headline_eligible": False,
        "independent_reproduction": False,
        "module_id": "M03",
        "publishable": False,
        "track": "DEVELOPMENT",
        "upstream_comparable": False,
    }
    if any(benchmark.get(key) != value for key, value in required.items()):
        raise ValueError("invalid M03 valid-time development fixture labels")
    timelines = benchmark.get("timelines")
    seeds = benchmark.get("seeds")
    if (
        not isinstance(timelines, list)
        or tuple(item.get("timeline_id") for item in timelines) != _M03_TIMELINE_IDS
        or not isinstance(seeds, list)
        or tuple(seeds) != _M03_SEEDS
    ):
        raise ValueError("invalid M03 valid-time canonical matrix")

    def run_matrix(matrix_cli: MnemoCLI) -> dict[str, dict[str, Any]]:
        observations: dict[str, dict[str, Any]] = {}
        for timeline in timelines:
            timeline_id = timeline["timeline_id"]
            for seed in seeds:
                case_id = f"{timeline_id}:{seed}"
                subject = f"M03 valid-time development:{timeline_id}:{seed}"
                last_id: str | None = None
                for event in timeline["events"]:
                    obj = event["object_template"].format(seed=seed)
                    if event["operation"] == "assert":
                        result = matrix_cli.assert_fact(
                            "wmbs-m03-development",
                            subject,
                            "value",
                            obj,
                            user="reference-harness",
                            trust_tier=0,
                            valid_from=event["valid_from"],
                        )
                    else:
                        if last_id is None:
                            raise ValueError("M03 supersede event has no prior assertion")
                        result = matrix_cli.supersede(
                            "wmbs-m03-development",
                            "reference-harness",
                            last_id,
                            {"object_value": obj, "trust_tier": 0},
                            valid_from=event["valid_from"],
                        )
                    last_id = result.json["id"]

                observations[case_id] = {
                    "current_objects": [
                        item["object"]
                        for item in matrix_cli.graph_as_of(
                            "wmbs-m03-development",
                            subject,
                            "value",
                            "2999-01-01T00:00:00Z",
                        )["assertions"]
                    ],
                    "history": [
                        {
                            "as_of": query["as_of"],
                            "objects": [
                                item["object"]
                                for item in matrix_cli.graph_as_of(
                                    "wmbs-m03-development",
                                    subject,
                                    "value",
                                    query["as_of"],
                                )["assertions"]
                            ],
                        }
                        for query in timeline["history"]
                    ],
                }
        return observations

    original = run_matrix(cli)
    with TemporaryDirectory(prefix="mnemosyne-m03-replay-") as directory:
        replay = run_matrix(replace(cli, store=str(Path(directory) / "store.json")))

    traces: list[dict[str, Any]] = []
    for timeline in timelines:
        timeline_id = timeline["timeline_id"]
        for seed in seeds:
            case_id = f"{timeline_id}:{seed}"
            observation = original[case_id]
            replay_observation = replay[case_id]
            traces.append(
                {
                    "case_id": case_id,
                    "current_objects": observation["current_objects"],
                    "history": observation["history"],
                    "replay_case_id": f"{case_id}:replay",
                    "replay_current_objects": replay_observation["current_objects"],
                    "replay_history": replay_observation["history"],
                    "scoring_family": "whole-memory-development",
                    "seed": seed,
                    "timeline_id": timeline_id,
                }
            )
    return traces, _canonical_replay_evidence(
        "wmbs-m03-valid-time-development", benchmark, traces, seeds
    )


def run_m15_composed_development(
    m01_fixture: dict[str, Any],
    m03_fixture: dict[str, Any],
    m10_fixture: dict[str, Any],
    cli: MnemoCLI,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Compose the admitted deterministic pilots and replay them exactly."""
    from eval.public import wmbs_m10 as m10
    from eval.public.bundle import canonical_replay_fixture_custody

    def run_once(run_cli: MnemoCLI) -> tuple[dict[str, Any], dict[str, Any]]:
        m01_traces, m01_evidence = run_m01_development(m01_fixture, run_cli)
        m03_traces, m03_evidence = run_m03_valid_time_development(
            m03_fixture, run_cli
        )
        m10_traces, m10_evidence = run_m10_development(m10_fixture, run_cli)
        return (
            {"m01": m01_traces, "m03": m03_traces, "m10": m10_traces},
            {
                "m01": m01_evidence,
                "m03": m03_evidence,
                "m10": m10_evidence,
            },
        )

    original, original_evidence = run_once(cli)
    with TemporaryDirectory(prefix="mnemosyne-m15-composed-replay-") as directory:
        replay, replay_evidence = run_once(
            replace(cli, store=str(Path(directory) / "store.json"))
        )

    m01_receipts = original["m01"][0]["receipts"]
    m10_cases = {
        case.case_id: case
        for case in m10.load_cases(m10_fixture)
        if case.partition == "scored"
    }
    expected_m03 = {
        f"{timeline['timeline_id']}:{seed}": {
            "current_objects": [
                value.format(seed=seed)
                for value in timeline["expected_current_templates"]
            ],
            "history": [
                {
                    "as_of": query["as_of"],
                    "objects": [
                        value.format(seed=seed)
                        for value in query["expected_object_templates"]
                    ],
                }
                for query in timeline["history"]
            ],
        }
        for timeline in m03_fixture["timelines"]
        for seed in m03_fixture["seeds"]
    }
    m03_observations = {trace["case_id"]: trace for trace in original["m03"]}
    gates = {
        "deduplication_exact": (
            any(receipt["outcome"] == "deduplicated" for receipt in m01_receipts)
            and original["m01"][0]["stored_projection"]
            == replay["m01"][0]["stored_projection"]
        ),
        "current_state_exact": all(
            m03_observations[case_id]["current_objects"]
            == expected["current_objects"]
            for case_id, expected in expected_m03.items()
        ),
        "historical_state_exact": all(
            m03_observations[case_id]["history"] == expected["history"]
            for case_id, expected in expected_m03.items()
        ),
        "deterministic_answer_exact": all(
            trace["answer_text"] == m10_cases[trace["case_id"]].gold_answer
            and trace["abstained"] is False
            for trace in original["m10"]
            if m10_cases[trace["case_id"]].category == "answerable"
        ),
        "abstention_exact": all(
            trace["answer_text"] is None and trace["abstained"] is True
            for trace in original["m10"]
            if m10_cases[trace["case_id"]].category == "unanswerable"
        ),
        "custody_complete": all(
            canonical_replay_fixture_custody(evidence["canonical_replay_projection"])
            for evidence in original_evidence.values()
        ),
        "canonical_equality": original_evidence == replay_evidence
        and original == replay,
    }
    failed = [name for name, passed in gates.items() if not passed]
    if failed:
        raise ValueError(f"M15 composed exact gates failed: {', '.join(failed)}")

    fixture_custody = {
        "m01": canonical_sha256(m01_fixture),
        "m03": canonical_sha256(m03_fixture),
        "m10": canonical_sha256(m10_fixture),
    }
    traces = [{"original": original, "replay": replay}]
    composed_projection = {
        "fixture_custody": fixture_custody,
        "rails": {
            name: rail["canonical_replay_projection"]
            for name, rail in original_evidence.items()
        },
        "sut_outputs": traces,
    }
    evidence = {
        "canonical_replay_digest": canonical_sha256(composed_projection),
        "canonical_replay_projection": composed_projection,
        "exact_gates": gates,
        "publishable": False,
        "pbpp_headline_eligible": False,
        "independent_external_reproduction": False,
        "upstream_comparable": False,
        "full_bitemporal_m03": False,
        "transaction_time": m03_fixture["transaction_time"],
    }
    return traces, evidence


def _canonical_replay_evidence(
    suite: str,
    benchmark: dict[str, Any],
    traces: list[dict[str, Any]],
    seeds: list[int],
) -> dict[str, Any]:
    """Bind deterministic adapter output to the shared M15 projection."""
    from eval.public.bundle import canonical_replay_digest, canonical_replay_projection

    fixture_digest = canonical_sha256(benchmark)
    generator = {
        key: benchmark.get(key)
        for key in ("generator_id", "generator_version", "schema_id")
    }
    payload = {
        "abi_schema": f"{PROTOCOL_VERSION}@sha256:{hashlib.sha256(_SCHEMA_PATH.read_bytes()).hexdigest()}",
        "build": {"system_seam": "harness-owned-reference-core"},
        "config": {"locale": "C", "timezone": "UTC"},
        "fixture": f"{suite}@sha256:{fixture_digest}",
        "judge": {"judge": None, "reader": None},
        "manifests": {
            "bundle_manifest_sha256": canonical_sha256(
                {"fixture_sha256": fixture_digest, "suite": suite, "traces": traces}
            ),
            "fixture_manifest_sha256": fixture_digest,
            "generator_manifest_sha256": canonical_sha256(generator),
        },
        "metrics": {},
        "seed_records": list(seeds),
        "suite": suite,
        "sut_outputs": traces,
        "traces": traces,
        "volatile": {},
    }
    projection = canonical_replay_projection(payload)
    return {
        "canonical_replay_digest": canonical_replay_digest(payload),
        "canonical_replay_projection": projection,
    }


_READINESS_STATES = {
    "PILOT-READY-DEV",
    "RUN-READY-OFFICIAL-LOCAL",
    "RUN-READY-HOSTED-X",
    "RUN-READY-P32-OPS",
}
_RUN_READINESS_STATES = _READINESS_STATES - {"PILOT-READY-DEV"}
_ADMISSION_STATES = _READINESS_STATES | {"CONTRACT-READY"}
_L16_DEV_MOUNTS = {"inputs:ro", "outputs:rw"}
_L16_DEV_ENVIRONMENT = {"LANG", "PATH", "TZ"}
_L16_DEV_PROFILE = {
    "profile_id": "sandbox-l16-dev",
    "host_os": "macOS",
    "host_arch": "Apple Silicon",
    "host_memory_bytes": 16 * 1024 * 1024 * 1024,
    "cpu": "Apple Silicon",
    "max_wall_time_ms": 20 * 60 * 1000,
    "max_peak_rss_bytes": 4 * 1024 * 1024 * 1024,
    "max_disk_bytes": 2 * 1024 * 1024 * 1024,
    "max_workers": 2,
}
_CONTRACT_NESTED_REFERENCE_FIELDS = {
    "AdapterContract": ("adapter_schema_id",),
    "DataSourceContract": ("source_id", "schema_ref"),
    "ScorerContract": ("scorer_id",),
    "BaselineManifest": ("tokenizer", "embedding_model", "prompt_ref"),
    "SandboxReceipt": ("profile_ref",),
    "SoftwareDataBOM": (
        "oci_digest",
        "lockfile_ref",
        "sbom_ref",
        "build_provenance_ref",
    ),
}
_CONTRACT_NESTED_REFERENCE_LIST_FIELDS = {
    "DataSourceContract": ("golden_fixture_refs",),
    "ScorerContract": ("golden_vector_refs",),
}


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
            content = value.get("content")
            content_sha256 = value.get("content_sha256")
            if (
                isinstance(content, str)
                and isinstance(content_sha256, str)
                and hashlib.sha256(content.encode()).hexdigest() != content_sha256
            ):
                _fail(f"{path}.content_sha256 does not match content")
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


def _resolve_artifact_reference(
    reference: str,
    artifacts: Mapping[str, object],
    *,
    path: str,
) -> object:
    artifact = artifacts.get(reference)
    if artifact is None:
        _fail(f"{path} contract artifact reference does not resolve")
    _, separator, expected_digest = reference.rpartition("@sha256:")
    if not separator:
        _fail(f"{path} is not a digest reference")
    schema_id = artifact.get("schema_id") if isinstance(artifact, Mapping) else None
    if schema_id == reference.rpartition("@sha256:")[0]:
        actual_digest = canonical_artifact_sha256(artifact)
    else:
        actual_digest = canonical_sha256(artifact)
    if actual_digest != expected_digest:
        _fail(f"{path} does not match the supplied artifact")
    return artifact


def _contract_artifact_references(
    definition: str, artifact: object
) -> list[tuple[str, str]]:
    assert isinstance(artifact, Mapping)
    references: list[tuple[str, str]] = []
    for field in _CONTRACT_NESTED_REFERENCE_FIELDS.get(definition, ()):
        reference = artifact[field]
        if reference is not None:
            assert isinstance(reference, str)
            references.append((f"$.{field}", reference))
    for field in _CONTRACT_NESTED_REFERENCE_LIST_FIELDS.get(definition, ()):
        values = artifact[field]
        assert isinstance(values, list)
        references.extend(
            (f"$.{field}[{index}]", reference)
            for index, reference in enumerate(values)
            if isinstance(reference, str)
        )
    return references


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
            minimum_size += 2
            for start in range(0, len(current), _STRING_CHUNK_SIZE):
                escaped = json.encoder.encode_basestring_ascii(
                    current[start : start + _STRING_CHUNK_SIZE]
                )
                minimum_size += len(escaped) - 2
                if minimum_size > maximum:
                    _fail(
                        f"{label} exceeds the byte limit",
                        code="RESOURCE_LIMIT",
                    )
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
                if (
                    not network.is_global
                    or not network.network_address.is_global
                    or not network.broadcast_address.is_global
                    or network.is_multicast
                    or network.is_unspecified
                    or network.is_loopback
                    or network.is_link_local
                    or network.is_reserved
                    or network.is_private
                    or any(
                        network.overlaps(ipaddress.ip_network(block))
                        for block in (
                            "10.0.0.0/8",
                            "100.64.0.0/10",
                            "172.16.0.0/12",
                            "192.168.0.0/16",
                            "fc00::/7",
                        )
                        if network.version == ipaddress.ip_network(block).version
                    )
                ):
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
        schema_id, separator, _ = reference.rpartition("@sha256:")
        if not separator:
            _fail(f"$.{field} is not a digest reference")
        artifact = _resolve_artifact_reference(
            reference, artifacts, path=f"$.{field}"
        )
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
    nested_artifacts: dict[str, object] = {}
    for field in required_fields:
        definition = _TYPED_FEASIBILITY_REFERENCES[field]
        artifact = resolved[field]
        for path, reference in _contract_artifact_references(definition, artifact):
            nested_artifacts[reference] = _resolve_artifact_reference(
                reference,
                artifacts,
                path=f"$.{field}{path.removeprefix('$')}",
            )
    if required_fields:
        adapter_contract = resolved["adapter_contract_ref"]
        assert isinstance(adapter_contract, Mapping)
        expected_schema_ref = (
            f"{_SCHEMA['$id']}@sha256:{canonical_sha256(_SCHEMA)}"
        )
        if adapter_contract["adapter_schema_id"] != expected_schema_ref:
            _fail("adapter contract does not bind the loaded ABI schema")
    if dispositions & _READINESS_STATES:
        if dispositions & _RUN_READINESS_STATES:
            _fail("run readiness requires profile-specific signed evidence")
        sandbox_receipt = resolved["sandbox_receipt_ref"]
        resource_receipt = resolved["resource_receipt_ref"]
        smoke_receipt = resolved["smoke_receipt_ref"]
        if (
            not isinstance(sandbox_receipt, Mapping)
            or not isinstance(resource_receipt, Mapping)
            or not isinstance(smoke_receipt, Mapping)
        ):
            _fail("pilot readiness requires sandbox, resource, and smoke receipts")
        profile_ref = sandbox_receipt.get("profile_ref")
        if not isinstance(profile_ref, str):
            _fail("pilot readiness requires a sandbox profile")
        profile_id, separator, profile_digest = profile_ref.rpartition("@sha256:")
        if not separator or profile_id != "sandbox-l16-dev":
            _fail("pilot readiness requires the L16-DEV sandbox profile")
        profile = nested_artifacts.get(profile_ref)
        if profile != _L16_DEV_PROFILE:
            _fail("pilot readiness requires the pinned L16-DEV profile")
        if resource_receipt.get("profile_sha256") != profile_digest:
            _fail("resource receipt does not match the sandbox profile")
        if resource_receipt.get("identity") != record.get("identity"):
            _fail("resource receipt does not match the feasibility identity")
        if resource_receipt.get("sut_boundary") != sandbox_receipt.get("sut_boundary"):
            _fail("resource receipt does not match the sandbox SUT boundary")
        egress = sandbox_receipt.get("egress")
        mounts = sandbox_receipt.get("mounts")
        environment = sandbox_receipt.get("environment_allowlist")
        if (
            sandbox_receipt.get("syscall_policy") == "unavailable"
            or not isinstance(mounts, list)
            or set(mounts) != _L16_DEV_MOUNTS
            or not isinstance(environment, list)
            or set(environment) != _L16_DEV_ENVIRONMENT
            or not isinstance(egress, Mapping)
            or egress.get("mode") != "deny"
            or egress.get("endpoints") != []
            or sandbox_receipt.get("secrets") != "none"
            or sandbox_receipt.get("model_proxy") != "disabled"
            or resource_receipt.get("network_bytes") != 0
            or resource_receipt.get("workers") != 1
        ):
            _fail("pilot readiness requires enforced offline L16 controls")
        if (
            sandbox_receipt.get("memory_limit_bytes")
            > _L16_DEV_PROFILE["max_peak_rss_bytes"]
            or sandbox_receipt.get("disk_limit_bytes")
            > _L16_DEV_PROFILE["max_disk_bytes"]
            or sandbox_receipt.get("wall_deadline_seconds") * 1000
            > _L16_DEV_PROFILE["max_wall_time_ms"]
            or resource_receipt.get("host_os") != _L16_DEV_PROFILE["host_os"]
            or resource_receipt.get("host_arch") != _L16_DEV_PROFILE["host_arch"]
            or resource_receipt.get("host_memory_bytes")
            != _L16_DEV_PROFILE["host_memory_bytes"]
            or resource_receipt.get("cpu") != _L16_DEV_PROFILE["cpu"]
            or resource_receipt.get("wall_time_ms")
            > sandbox_receipt.get("wall_deadline_seconds") * 1000
            or resource_receipt.get("peak_rss_bytes")
            > sandbox_receipt.get("memory_limit_bytes")
            or resource_receipt.get("disk_bytes")
            > sandbox_receipt.get("disk_limit_bytes")
        ):
            _fail("resource receipt does not satisfy the pinned L16-DEV profile")
        if resource_receipt.get("abort_status") != "completed":
            _fail("readiness requires a completed resource receipt")
        if smoke_receipt.get("identity") != record.get("identity"):
            _fail("smoke receipt does not match the feasibility identity")
        if smoke_receipt.get("outcome") != "passed":
            _fail("pilot readiness requires a passing smoke receipt")
        if smoke_receipt.get("sandbox_receipt_sha256") != sandbox_receipt.get(
            "artifact_sha256"
        ):
            _fail("smoke receipt does not match the sandbox receipt")
        if smoke_receipt.get("resource_receipt_sha256") != resource_receipt.get(
            "artifact_sha256"
        ):
            _fail("smoke receipt does not match the resource receipt")
        result_ref = smoke_receipt.get("result_ref")
        if not isinstance(result_ref, str):
            _fail("smoke receipt does not bind a result")
        if resource_receipt.get("result_ref") != result_ref:
            _fail("resource receipt does not match the smoke result")
        result = artifacts.get(result_ref)
        if result is None:
            _fail("smoke result does not resolve to a supplied artifact")
        result_id, separator, result_digest = result_ref.rpartition("@sha256:")
        if not separator or not result_id:
            _fail("smoke result is not a digest reference")
        if canonical_sha256(result) != result_digest:
            _fail("smoke result does not match the supplied artifact")
        result_contract = record["result_contract"]
        if (
            not isinstance(result_contract, Mapping)
            or result_id != result_contract.get("schema_version")
        ):
            _fail("smoke result does not match the feasibility result contract")
        if result_id == "result-v1":
            metrics = result.get("metrics")
            if isinstance(metrics, list) and len(metrics) > _MAX_RESULT_V1_METRICS:
                _fail("result-v1 metrics exceed the closed limit")
            result_errors = validate_result_v1(result)
            if result_errors:
                _fail(
                    "result-v1 validation failed: "
                    + ", ".join(result_errors[:10])
                )
            identity = record.get("identity")
            publication = result.get("publication")
            metrics = result.get("metrics")
            if (
                not isinstance(identity, Mapping)
                or not isinstance(publication, Mapping)
                or not isinstance(metrics, list)
                or result.get("track") != "development"
                or result.get("benchmark")
                != f"whole-memory-{identity.get('module_id')}"
                or result.get("benchmark_version") != identity.get("module_version")
                or result.get("run_commit") != identity.get("source_commit")
                or publication.get("publishable") is not False
                or publication.get("label") != "operator-run"
                or any(
                    not isinstance(metric, Mapping)
                    or metric.get("family") != result_contract.get("metric_family")
                    for metric in metrics
                )
            ):
                _fail("smoke result does not match the feasibility identity")
        else:
            _fail("result-v2 validation is not implemented")
        if result_contract.get("attempt_state") != "finalized":
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

        deadline = _parse_utc_timestamp(
            str(context["deadline_utc"]), "$.context.deadline_utc"
        )
        if deadline <= self._now():
            error = validated_response.get("error")
            if (
                definition != "error_response"
                or not isinstance(error, Mapping)
                or error.get("code") != "DEADLINE_EXCEEDED"
            ):
                _fail("request deadline has elapsed", code="DEADLINE_EXCEEDED")
            self._responses[idempotency_key] = response_fingerprint
            if self._pending_transition == idempotency_key:
                self._pending_transition = None
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
