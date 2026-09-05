import copy
import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from leaderboard import validate
from leaderboard.validate import (
    DIGEST_PAYLOAD_NAMES,
    SCHEMA_VERSION,
    SCHEMA_VERSION_V2,
    validate_projection,
    validate_record,
    verify_result_digests,
)


def _retrieval_record() -> dict[str, object]:
    return {
        "schema_version": "mnemosyne.leaderboard.result/v1",
        "record_id": "synthetic-retrieval-001",
        "system": "mnemosyne",
        "track": "development",
        "benchmark": "synthetic-retrieval",
        "benchmark_version": "1",
        "run_commit": "0123456789abcdef0123456789abcdef01234567",
        "build_fingerprint": f"sha256:{'1' * 64}",
        "config_digest": f"sha256:{'2' * 64}",
        "bundle_digest": f"sha256:{'3' * 64}",
        "trace_index_digest": f"sha256:{'4' * 64}",
        "metrics": [
            {
                "name": "recall_at_10",
                "family": "retrieval",
                "value": 0.75,
                "unit": "ratio",
                "confidence_interval": {"low": 0.60, "high": 0.85},
            }
        ],
        "publication": {"publishable": False, "label": "operator-run"},
        "operator_entry": {"operator": "synthetic-test", "disclosed": True},
        "history": {"supersedes": None},
    }


def _judged_qa_record() -> dict[str, object]:
    record = _retrieval_record()
    record.update(
        {
            "record_id": "synthetic-judged-qa-001",
            "benchmark": "synthetic-judged-qa",
            "metrics": [
                {
                    "name": "answer_quality",
                    "family": "judged_qa",
                    "value": 0.80,
                    "unit": "ratio",
                    "confidence_interval": {"low": 0.70, "high": 0.90},
                    "judge": {
                        "model": "synthetic-judge-v1",
                        "prompt_digest": f"sha256:{'5' * 64}",
                        "config_digest": f"sha256:{'6' * 64}",
                    },
                }
            ],
        }
    )
    return record


def test_accepts_minimal_deterministic_retrieval_record() -> None:
    assert validate_record(_retrieval_record()) == []


def test_accepts_minimal_disclosed_judged_qa_record() -> None:
    assert validate_record(_judged_qa_record()) == []


@pytest.mark.parametrize(
    "family",
    ["security", "calibration", "performance", "reproducibility"],
)
def test_accepts_additional_metric_family(family: str) -> None:
    record = _retrieval_record()
    metrics = record["metrics"]
    assert isinstance(metrics, list)
    metrics[0]["family"] = family

    assert validate_record(record) == []


def test_rejects_unknown_metric_family() -> None:
    record = _retrieval_record()
    metrics = record["metrics"]
    assert isinstance(metrics, list)
    metrics[0]["family"] = "unknown"

    assert validate_record(record) == ["/metrics/0/family"]


def test_unknown_metric_family_does_not_add_mixed_family_error() -> None:
    record = _retrieval_record()
    metrics = record["metrics"]
    assert isinstance(metrics, list)
    unknown_metric = copy.deepcopy(metrics[0])
    unknown_metric["family"] = "unknown"
    metrics.append(unknown_metric)

    assert validate_record(record) == ["/metrics/1/family"]


def test_rejects_mixed_additional_metric_families() -> None:
    record = _retrieval_record()
    metrics = record["metrics"]
    assert isinstance(metrics, list)
    security_metric = copy.deepcopy(metrics[0])
    security_metric["family"] = "security"
    metrics.append(security_metric)

    assert validate_record(record) == ["/metrics"]


@pytest.mark.parametrize(
    "field",
    [
        "record_id",
        "system",
        "track",
        "benchmark",
        "benchmark_version",
        "run_commit",
        "build_fingerprint",
        "config_digest",
        "bundle_digest",
        "trace_index_digest",
    ],
)
def test_rejects_whitespace_only_top_level_strings(field: str) -> None:
    record = _retrieval_record()
    record[field] = "   "

    assert f"/{field}" in validate_record(record)


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("name", "/metrics/0/name"),
        ("family", "/metrics/0/family"),
        ("unit", "/metrics/0/unit"),
        ("judge.model", "/metrics/0/judge/model"),
        ("judge.prompt_digest", "/metrics/0/judge/prompt_digest"),
        ("judge.config_digest", "/metrics/0/judge/config_digest"),
    ],
)
def test_rejects_whitespace_only_metric_strings(field: str, expected: str) -> None:
    record = _judged_qa_record()
    metrics = record["metrics"]
    assert isinstance(metrics, list)
    metric = metrics[0]
    assert isinstance(metric, dict)
    if field.startswith("judge."):
        judge = metric["judge"]
        assert isinstance(judge, dict)
        judge[field.removeprefix("judge.")] = "   "
    else:
        metric[field] = "   "

    assert expected in validate_record(record)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_rejects_non_finite_metric_numbers(value: float) -> None:
    record = _retrieval_record()
    metrics = record["metrics"]
    assert isinstance(metrics, list)
    metrics[0]["value"] = value

    assert "/metrics/0/value" in validate_record(record)


def test_rejects_inverted_confidence_interval() -> None:
    record = _retrieval_record()
    metrics = record["metrics"]
    assert isinstance(metrics, list)
    metrics[0]["confidence_interval"] = {"low": 0.9, "high": 0.1}

    assert "/metrics/0/confidence_interval" in validate_record(record)


@pytest.mark.parametrize("family", [[], {}])
def test_rejects_unhashable_metric_family(family: object) -> None:
    record = _retrieval_record()
    metrics = record["metrics"]
    assert isinstance(metrics, list)
    metrics[0]["family"] = family

    assert validate_record(record) == ["/metrics/0/family"]


def _delete(record: dict[str, object], field: str) -> None:
    del record[field]


def _mix_metric_families(record: dict[str, object]) -> None:
    judged_metric = _judged_qa_record()["metrics"]
    assert isinstance(judged_metric, list)
    metrics = record["metrics"]
    assert isinstance(metrics, list)
    metrics.extend(judged_metric)


def _remove_judge_disclosure(record: dict[str, object]) -> None:
    metrics = record["metrics"]
    assert isinstance(metrics, list)
    metrics[0]["family"] = "judged_qa"
    metrics[0]["judge"] = {"model": "synthetic-judge-v1"}


def _set_nested(
    record: dict[str, object], section: str, field: str, value: object
) -> None:
    nested = record[section]
    assert isinstance(nested, dict)
    nested[field] = value


def _delete_nested(record: dict[str, object], section: str, field: str) -> None:
    nested = record[section]
    assert isinstance(nested, dict)
    del nested[field]


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda record: _delete(record, "bundle_digest"), "/bundle_digest"),
        (
            lambda record: _delete(record, "trace_index_digest"),
            "/trace_index_digest",
        ),
        (_mix_metric_families, "/metrics"),
        (_remove_judge_disclosure, "/metrics/0/judge/config_digest"),
        (
            lambda record: record.update(run_commit="main"),
            "/run_commit",
        ),
        (
            lambda record: record.update(build_fingerprint="mutable-build"),
            "/build_fingerprint",
        ),
        (
            lambda record: record.update(config_digest="mutable-config"),
            "/config_digest",
        ),
        (
            lambda record: _set_nested(record, "publication", "publishable", True),
            "/publication/publishable",
        ),
        (
            lambda record: _delete_nested(record, "publication", "label"),
            "/publication/label",
        ),
        (
            lambda record: _set_nested(record, "publication", "label", ""),
            "/publication/label",
        ),
        (
            lambda record: _set_nested(record, "publication", "label", "independent"),
            "/publication/label",
        ),
        (
            lambda record: record.update(record_id="   "),
            "/record_id",
        ),
        (
            lambda record: record.update(history={}),
            "/history/supersedes",
        ),
        (
            lambda record: record.update(history={"supersedes": record["record_id"]}),
            "/record_id",
        ),
        (
            lambda record: record.update(operator_entry={"operator": "synthetic-test"}),
            "/operator_entry/disclosed",
        ),
        (
            lambda record: _delete_nested(record, "operator_entry", "operator"),
            "/operator_entry/operator",
        ),
        (
            lambda record: _set_nested(record, "operator_entry", "operator", ""),
            "/operator_entry/operator",
        ),
        (
            lambda record: _set_nested(record, "operator_entry", "operator", "   "),
            "/operator_entry/operator",
        ),
        (
            lambda record: record.update(
                publication={"publishable": False, "label": "neutral"}
            ),
            "/publication/register_b_satisfied",
        ),
        (
            lambda record: _set_nested(
                record, "publication", "register_b_satisfied", "yes"
            ),
            "/publication/register_b_satisfied",
        ),
    ],
    ids=[
        "missing-bundle-provenance",
        "missing-trace-provenance",
        "mixed-retrieval-and-judged-qa",
        "incomplete-judge-disclosure",
        "unpinned-run-commit",
        "non-sha256-build-fingerprint",
        "non-sha256-config-digest",
        "development-result-marked-publishable",
        "publication-label-missing",
        "publication-label-empty",
        "publication-label-not-allowed",
        "record-id-whitespace-only",
        "replacement-omits-supersedes",
        "superseded-record-reuses-record-id",
        "operator-entry-disclosure-missing",
        "operator-name-missing",
        "operator-name-empty",
        "operator-name-whitespace-only",
        "neutral-label-without-register-b",
        "non-boolean-register-b",
    ],
)
def test_rejects_prohibited_result_mutations(
    mutate: Callable[[dict[str, object]], None], expected: str
) -> None:
    record = copy.deepcopy(_retrieval_record())
    mutate(record)
    assert expected in validate_record(record)


def test_schema_rejects_mixed_metric_families() -> None:
    schema = json.loads(
        Path("leaderboard/schema/result-v1.schema.json").read_text(encoding="utf-8")
    )
    families = {
        "retrieval",
        "judged_qa",
        "security",
        "calibration",
        "performance",
        "reproducibility",
    }

    assert set(schema["$defs"]["metric"]["properties"]["family"]["enum"]) == families
    family_rules = next(
        rule["properties"]["metrics"]["anyOf"]
        for rule in schema["allOf"]
        if "properties" in rule and "metrics" in rule["properties"]
    )
    assert {
        rule["items"]["properties"]["family"]["const"] for rule in family_rules
    } == families


def test_schema_closes_object_boundaries_and_publication_labels() -> None:
    schema = json.loads(
        Path("leaderboard/schema/result-v1.schema.json").read_text(encoding="utf-8")
    )

    assert schema["additionalProperties"] is False
    for name in ("publication", "operator_entry", "history"):
        assert schema["properties"][name]["additionalProperties"] is False
    for name in ("metric", "judge", "confidenceInterval"):
        assert schema["$defs"][name]["additionalProperties"] is False
    assert schema["properties"]["publication"]["properties"]["label"]["enum"] == [
        "operator-run",
        "neutral",
    ]
    assert schema["$defs"]["nonEmptyString"]["pattern"] == r".*\S.*"


@pytest.mark.parametrize(
    "payload",
    [_retrieval_record(), [_retrieval_record(), _judged_qa_record()]],
    ids=["record", "array"],
)
def test_cli_validates_one_record_and_arrays(
    payload: object, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "records.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert validate.main([str(path)]) == 0
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize(("depth", "expected"), [(1_000, 1), (1_001, 2)])
def test_cli_enforces_json_nesting_boundary(
    depth: int,
    expected: int,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "records.json"
    path.write_text("[" * (depth - 1) + "{}" + "]" * (depth - 1), encoding="utf-8")

    assert validate.main([str(path)]) == expected
    capsys.readouterr()


def test_json_nesting_ignores_delimiters_inside_escaped_strings() -> None:
    raw = json.dumps({"operator": r'escaped \"[{]}\" delimiters'})

    assert validate._json_nesting_too_deep(raw) is False


def test_rejects_unknown_fields_at_each_object_boundary() -> None:
    record = _judged_qa_record()
    metrics = record["metrics"]
    assert isinstance(metrics, list)
    metric = metrics[0]
    assert isinstance(metric, dict)
    judge = metric["judge"]
    interval = metric["confidence_interval"]
    assert isinstance(judge, dict)
    assert isinstance(interval, dict)

    mutations = [
        (record, "unexpected", "/unexpected"),
        (record["publication"], "unexpected", "/publication/unexpected"),
        (record["operator_entry"], "unexpected", "/operator_entry/unexpected"),
        (record["history"], "unexpected", "/history/unexpected"),
        (metric, "unexpected", "/metrics/0/unexpected"),
        (judge, "unexpected", "/metrics/0/judge/unexpected"),
        (
            interval,
            "unexpected",
            "/metrics/0/confidence_interval/unexpected",
        ),
    ]
    for target, field, expected in mutations:
        assert isinstance(target, dict)
        target[field] = True
        assert expected in validate_record(record)
        del target[field]


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("a/b", "/a~1b"),
        ("a~b", "/a~0b"),
        ("line\nbreak", r"/line\nbreak"),
    ],
)
def test_unknown_field_errors_escape_pointer_tokens(field: str, expected: str) -> None:
    record = _retrieval_record()
    record[field] = True

    assert expected in validate_record(record)


def test_rejects_non_object_records() -> None:
    assert validate_record(None) == ["/"]


def test_cli_rejects_scalar_array_members(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "records.json"
    path.write_text(json.dumps([_retrieval_record(), 1]), encoding="utf-8")

    assert validate.main([str(path)]) == 1
    assert capsys.readouterr().err == "/1\n"


def test_cli_accepts_supersession_outside_input_array(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "records.json"
    record = _retrieval_record()
    record["history"] = {"supersedes": "external-record"}
    path.write_text(json.dumps([record]), encoding="utf-8")

    assert validate.main([str(path)]) == 0
    assert capsys.readouterr().err == ""


def test_cli_rejects_duplicate_record_ids(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "records.json"
    record = _retrieval_record()
    path.write_text(json.dumps([record, record]), encoding="utf-8")

    assert validate.main([str(path)]) == 1
    assert capsys.readouterr().err == "/1/record_id\n"


def test_cli_rejects_internal_supersession_cycles(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "records.json"
    first = _retrieval_record()
    second = _judged_qa_record()
    first["history"] = {"supersedes": second["record_id"]}
    second["history"] = {"supersedes": first["record_id"]}
    path.write_text(json.dumps([first, second]), encoding="utf-8")

    assert validate.main([str(path)]) == 1
    assert capsys.readouterr().err == "/0/history/supersedes\n/1/history/supersedes\n"


def test_cycle_detection_visits_each_link_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = []
    for index in range(50):
        record = _retrieval_record()
        record["record_id"] = f"record-{index}"
        record["history"] = {
            "supersedes": f"record-{index + 1}" if index < 49 else None
        }
        records.append(record)

    calls = 0

    def counted_len(value: object) -> int:
        nonlocal calls
        calls += 1
        return len(value)  # type: ignore[arg-type]

    monkeypatch.setattr(validate, "len", counted_len, raising=False)

    assert validate._validate_records(records) == []
    assert calls <= len(records)


def test_cli_reports_contract_violations(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "record.json"
    record = _retrieval_record()
    del record["bundle_digest"]
    path.write_text(json.dumps(record), encoding="utf-8")

    assert validate.main([str(path)]) == 1
    assert capsys.readouterr().err == "/bundle_digest\n"


def test_cli_indexes_contract_violations_in_arrays(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "records.json"
    first = _retrieval_record()
    del first["bundle_digest"]
    second = _judged_qa_record()
    del second["trace_index_digest"]
    path.write_text(json.dumps([first, second]), encoding="utf-8")

    assert validate.main([str(path)]) == 1
    assert capsys.readouterr().err == "/0/bundle_digest\n/1/trace_index_digest\n"


def test_cli_reports_unreadable_or_invalid_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.json"

    assert validate.main([str(missing)]) == 2
    assert capsys.readouterr().err == f"error: cannot read JSON: {missing}\n"

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    assert validate.main([str(invalid)]) == 2
    assert capsys.readouterr().err == f"error: invalid JSON: {invalid}\n"

    invalid.write_bytes(b"\xff")
    assert validate.main([str(invalid)]) == 2
    assert capsys.readouterr().err == f"error: invalid JSON: {invalid}\n"


def test_cli_rejects_excessively_nested_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "nested.json"
    path.write_text("[" * 10_000 + "]" * 10_000, encoding="utf-8")

    assert validate.main([str(path)]) == 2
    assert capsys.readouterr().err == f"error: invalid JSON: {path}\n"


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity", "1e400"])
def test_cli_rejects_non_finite_json_numbers(
    constant: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "non-finite.json"
    path.write_text(
        json.dumps(_retrieval_record()).replace("0.75", constant, 1),
        encoding="utf-8",
    )

    assert validate.main([str(path)]) == 2
    assert capsys.readouterr().err == f"error: invalid JSON: {path}\n"


_V1_SCHEMA_SHA256 = (
    "22544dbcfbad5f09cc4bccbbfd6b79f4bda1b70d2a903f6908cd89cfd3e51817"
)


def _v2_identity(**overrides: object) -> dict[str, object]:
    identity: dict[str, object] = {
        "system_id": "mnemosyne",
        "system_version": "0.1.0",
        "adapter_id": "whole-memory-reference",
        "adapter_version": "0.1.0",
        "track_kind": "DEVELOPMENT",
        "benchmark_id": "synthetic-retrieval",
        "benchmark_version": "1",
        "module_id": "M01",
        "division": "COMPONENT-CLOSED",
        "resource_profile": "L16-DEV",
        "backend_id": "sqlite",
        "hardware_fingerprint": f"sha256:{'a' * 64}",
        "model_policy_id": "none",
        "dataset_split_digest": f"sha256:{'b' * 64}",
        "run_id": "run-001",
        "attempt_id": "attempt-001",
        "seed": 1,
    }
    identity.update(overrides)
    return identity


def _v2_development_record() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION_V2,
        "record_id": "synthetic-v2-dev-001",
        "system": "mnemosyne",
        "track": "development",
        "benchmark": "synthetic-retrieval",
        "benchmark_version": "1",
        "run_commit": "0123456789abcdef0123456789abcdef01234567",
        "build_fingerprint": f"sha256:{'1' * 64}",
        "config_digest": f"sha256:{'2' * 64}",
        "bundle_digest": f"sha256:{'3' * 64}",
        "trace_index_digest": f"sha256:{'4' * 64}",
        "metrics": [
            {
                "name": "recall_at_10",
                "family": "retrieval",
                "value": 0.75,
                "unit": "ratio",
                "confidence_interval": {"low": 0.60, "high": 0.85},
            }
        ],
        "publication": {
            "publishable": False,
            "label": "operator-run",
            "pbpp_headline_eligible": False,
        },
        "operator_entry": {"operator": "synthetic-test", "disclosed": True},
        "history": {"supersedes": None},
        "module_id": "M01",
        "admission_state": "PROPOSED",
        "evidence_level": "IMPLEMENTED",
        "track_kind": "DEVELOPMENT",
        "lineage": {},
        "identity": _v2_identity(),
        "division": "COMPONENT-CLOSED",
        "capability": "native",
        "safety_gates": [{"name": "no-leakage", "status": "passed"}],
        "resources": {
            "treatment": "verified",
            "wall_time_ms": 10,
            "peak_rss_bytes": 1024,
            "cost": 0,
            "latency_ms": 5,
        },
        "run_profile": {
            "profile_id": "L16-DEV",
            "seeds": [1],
            "retries": 0,
            "aborts": 0,
        },
        "custody": "development-public",
        "signer_role": "operator",
        "trace_id": "trace-001",
        "attempt_outcome": "measured",
    }


def _v2_official_record() -> dict[str, object]:
    record = _v2_development_record()
    record.update(
        {
            "record_id": "synthetic-v2-official-001",
            "track": "official-upstream",
            "track_kind": "OFFICIAL-UPSTREAM",
            "admission_state": "PROPOSED",
            "evidence_level": "PUBLICLY_MEASURED",
            "identity": _v2_identity(
                track_kind="OFFICIAL-UPSTREAM",
                attempt_id="attempt-official",
            ),
            "lineage": {
                "fidelity": {
                    "upstream_protocol_digest": f"sha256:{'c' * 64}",
                    "dataset_digest": f"sha256:{'d' * 64}",
                    "split_digest": f"sha256:{'e' * 64}",
                    "preprocessing_digest": f"sha256:{'f' * 64}",
                    "scorer_digest": f"sha256:{'11' * 32}",
                    "environment_digest": f"sha256:{'12' * 32}",
                    "revision_digest": f"sha256:{'13' * 32}",
                }
            },
            "publication": {
                "publishable": True,
                "label": "operator-run",
                "pbpp_headline_eligible": False,
            },
            "custody": "operator-held-out",
        }
    )
    return record


def _v2_successor_record() -> dict[str, object]:
    record = _v2_official_record()
    record.update(
        {
            "record_id": "synthetic-v2-successor-001",
            "track": "enhanced-successor",
            "track_kind": "ENHANCED-SUCCESSOR",
            "identity": _v2_identity(
                track_kind="ENHANCED-SUCCESSOR",
                attempt_id="attempt-successor",
            ),
            "lineage": {
                "parent_official_record_id": "synthetic-v2-official-001",
                "parent_construct_digest": f"sha256:{'14' * 32}",
                "difference_manifest_digest": f"sha256:{'15' * 32}",
            },
        }
    )
    return record


def _projection(source_ids: list[str], **overrides: object) -> dict[str, object]:
    projection: dict[str, object] = {
        "schema_version": "mnemosyne.leaderboard.projection/v1",
        "projection_id": "proj-001",
        "kind": "exploratory",
        "source_record_ids": source_ids,
        "filters": {"backend_id": "sqlite"},
        "compatibility_key": {
            "track_kind": "DEVELOPMENT",
            "benchmark_id": "synthetic-retrieval",
            "benchmark_version": "1",
            "scorer_digest": f"sha256:{'11' * 32}",
            "division": "COMPONENT-CLOSED",
            "metric": {
                "name": "recall_at_10",
                "family": "retrieval",
                "unit": "ratio",
            },
            "resource_treatment": "verified",
        },
        "exclusions": [],
        "weighting": {"formula": "unweighted-mean", "disclosed": True},
        "numerator": 3,
        "denominator": 4,
        "uncertainty_method": "bootstrap-percentile",
        "missing_count": 0,
        "unsupported_count": 0,
        "failed_count": 0,
        "aborted_count": 0,
        "not_measured_count": 0,
        "certified": False,
        "official": False,
        "headline": False,
        "safety_failures_visible": False,
    }
    projection.update(overrides)
    return projection


def test_v1_schema_bytes_remain_immutable() -> None:
    digest = hashlib.sha256(
        Path("leaderboard/schema/result-v1.schema.json").read_bytes()
    ).hexdigest()
    assert digest == _V1_SCHEMA_SHA256
    assert SCHEMA_VERSION == "mnemosyne.leaderboard.result/v1"


def test_v2_schema_is_additive_closed_contract() -> None:
    schema = json.loads(
        Path("leaderboard/schema/result-v2.schema.json").read_text(encoding="utf-8")
    )

    assert schema["$id"] == SCHEMA_VERSION_V2
    assert schema["additionalProperties"] is False
    assert "atomic_identity" in schema["$defs"]
    assert schema["$defs"]["atomic_identity"]["additionalProperties"] is False
    assert set(schema["$defs"]["track_kind"]["enum"]) == {
        "OFFICIAL-UPSTREAM",
        "ENHANCED-SUCCESSOR",
        "DEVELOPMENT",
    }
    assert DIGEST_PAYLOAD_NAMES == {
        "build_fingerprint": "build.json",
        "config_digest": "config.json",
        "bundle_digest": "bundle-manifest.json",
        "trace_index_digest": "traces.jsonl",
    }


def _confidence_interval_covers(splits: list[object], low: float, high: float) -> bool:
    return any(
        isinstance(branch, dict)
        and low <= branch["properties"]["low"]["maximum"]
        and high >= branch["properties"]["high"]["minimum"]
        for branch in splits
    )


def test_v2_schema_aligns_metric_contract_with_runtime() -> None:
    schema = json.loads(
        Path("leaderboard/schema/result-v2.schema.json").read_text(encoding="utf-8")
    )
    families = {
        "retrieval",
        "judged_qa",
        "security",
        "calibration",
        "performance",
        "reproducibility",
    }

    assert set(schema["$defs"]["metric"]["properties"]["family"]["enum"]) == families
    family_rules = next(
        rule["properties"]["metrics"]["anyOf"]
        for rule in schema["allOf"]
        if "properties" in rule and "metrics" in rule["properties"]
    )
    assert {
        rule["items"]["properties"]["family"]["const"] for rule in family_rules
    } == families
    judge_rule = schema["$defs"]["metric"]["allOf"][0]
    assert judge_rule["if"]["properties"]["family"]["const"] == "judged_qa"
    assert judge_rule["then"]["required"] == ["judge"]
    assert judge_rule["else"]["not"]["required"] == ["judge"]
    items = schema["properties"]["metrics"]["items"]
    assert items["allOf"][0] == {"$ref": "#/$defs/metric"}
    published_judge = items["allOf"][1]
    assert published_judge["if"]["properties"]["family"]["const"] == "judged_qa"
    assert published_judge["then"]["required"] == ["judge"]
    assert published_judge["else"]["not"]["required"] == ["judge"]
    interval = schema["$defs"]["confidenceInterval"]
    assert "low <= high" in interval["$comment"]
    splits = interval["anyOf"]
    assert splits

    unit_maxima = [
        branch["properties"]["low"]["maximum"]
        for branch in splits
        if 0.0 <= branch["properties"]["low"]["maximum"] <= 1.0
    ]
    assert 0.995 in unit_maxima
    assert len(unit_maxima) >= 1001

    assert _confidence_interval_covers(splits, 0.60, 0.85)
    assert _confidence_interval_covers(splits, 0.70, 0.90)
    assert _confidence_interval_covers(splits, 0.995, 0.995)
    assert not _confidence_interval_covers(splits, 0.9, 0.1)


def test_v2_runtime_rejects_metric_contract_violations() -> None:
    missing_judge = _v2_development_record()
    missing_judge["metrics"] = [
        {
            "name": "answer_quality",
            "family": "judged_qa",
            "value": 0.80,
            "unit": "ratio",
            "confidence_interval": {"low": 0.70, "high": 0.90},
        }
    ]
    assert "/metrics/0/judge" in validate_record(missing_judge)

    mixed = _v2_development_record()
    metrics = mixed["metrics"]
    assert isinstance(metrics, list)
    metrics.append(
        {
            "name": "answer_quality",
            "family": "judged_qa",
            "value": 0.80,
            "unit": "ratio",
            "confidence_interval": {"low": 0.70, "high": 0.90},
            "judge": {
                "model": "synthetic-judge-v1",
                "prompt_digest": f"sha256:{'5' * 64}",
                "config_digest": f"sha256:{'6' * 64}",
            },
        }
    )
    assert "/metrics" in validate_record(mixed)

    inverted = _v2_development_record()
    inverted_metrics = inverted["metrics"]
    assert isinstance(inverted_metrics, list)
    inverted_metrics[0]["confidence_interval"] = {"low": 0.9, "high": 0.1}
    assert "/metrics/0/confidence_interval" in validate_record(inverted)

    equal_milli = _v2_development_record()
    equal_metrics = equal_milli["metrics"]
    assert isinstance(equal_metrics, list)
    equal_metrics[0]["confidence_interval"] = {"low": 0.995, "high": 0.995}
    assert validate_record(equal_milli) == []


def test_v2_projection_schema_declares_closed_properties() -> None:
    schema = json.loads(
        Path("leaderboard/schema/result-v2.schema.json").read_text(encoding="utf-8")
    )
    projection = schema["$defs"]["projection"]

    assert projection["additionalProperties"] is False
    assert "properties" in projection
    assert set(projection["required"]) <= set(projection["properties"])
    assert "weighting" in projection["properties"]
    assert projection["properties"]["source_record_ids"]["minItems"] == 1


def test_accepts_minimal_v2_development_record() -> None:
    assert validate_record(_v2_development_record()) == []


def test_accepts_official_record_with_complete_fidelity_pins() -> None:
    assert validate_record(_v2_official_record()) == []


def test_accepts_successor_record_with_parent_and_difference() -> None:
    assert validate_record(_v2_successor_record()) == []


def test_v1_records_are_unchanged_by_v2_dispatch() -> None:
    assert validate_record(_retrieval_record()) == []
    v2_as_v1 = _v2_development_record()
    v2_as_v1["schema_version"] = SCHEMA_VERSION
    errors = validate_record(v2_as_v1)
    assert "/identity" in errors
    assert "/schema_version" not in errors


@pytest.mark.parametrize(
    "field",
    [
        "module_id",
        "admission_state",
        "evidence_level",
        "track_kind",
        "lineage",
        "identity",
        "division",
        "capability",
        "safety_gates",
        "resources",
        "run_profile",
        "custody",
        "signer_role",
        "trace_id",
        "attempt_outcome",
    ],
)
def test_rejects_missing_required_v2_fields(field: str) -> None:
    record = _v2_development_record()
    del record[field]

    assert f"/{field}" in validate_record(record)


@pytest.mark.parametrize(
    ("field", "value", "pointer"),
    [
        ("admission_state", "READY", "/admission_state"),
        ("evidence_level", "CERTIFIED", "/evidence_level"),
        ("track_kind", "official", "/track_kind"),
        ("division", "open", "/division"),
        ("capability", "partial", "/capability"),
        ("custody", "public", "/custody"),
        ("signer_role", "anonymous", "/signer_role"),
        ("attempt_outcome", "zeroed", "/attempt_outcome"),
    ],
)
def test_rejects_closed_v2_enum_violations(
    field: str, value: object, pointer: str
) -> None:
    record = _v2_development_record()
    record[field] = value

    assert pointer in validate_record(record)


def test_rejects_resource_unverified_as_verified_alias() -> None:
    record = _v2_development_record()
    resources = record["resources"]
    assert isinstance(resources, dict)
    resources["treatment"] = "unmetered"

    assert "/resources/treatment" in validate_record(record)


def test_accepts_resource_unverified_disclosure() -> None:
    record = _v2_development_record()
    resources = record["resources"]
    assert isinstance(resources, dict)
    resources["treatment"] = "resource-unverified"

    assert validate_record(record) == []


@pytest.mark.parametrize("role", ["operator", "independent", "custodian"])
def test_accepts_distinct_signer_roles(role: str) -> None:
    record = _v2_development_record()
    record["signer_role"] = role

    assert validate_record(record) == []


def test_rejects_development_result_marked_publishable_or_headline() -> None:
    record = _v2_development_record()
    publication = record["publication"]
    assert isinstance(publication, dict)
    publication["publishable"] = True

    assert "/publication/publishable" in validate_record(record)

    publication["publishable"] = False
    publication["pbpp_headline_eligible"] = True
    assert "/publication/pbpp_headline_eligible" in validate_record(record)


def test_rejects_official_record_missing_fidelity_pins() -> None:
    record = _v2_official_record()
    record["lineage"] = {}

    assert "/lineage/fidelity" in validate_record(record)


def test_rejects_successor_record_missing_parent_or_difference() -> None:
    record = _v2_successor_record()
    record["lineage"] = {"parent_official_record_id": "synthetic-v2-official-001"}

    assert "/lineage/difference_manifest_digest" in validate_record(record)


def test_rejects_track_kind_mismatch_with_identity() -> None:
    record = _v2_development_record()
    identity = record["identity"]
    assert isinstance(identity, dict)
    identity["track_kind"] = "OFFICIAL-UPSTREAM"

    assert "/identity/track_kind" in validate_record(record)


@pytest.mark.parametrize(
    "field",
    ["average", "mean", "rank", "composite", "members", "source_record_ids"],
)
def test_rejects_cross_attempt_aggregate_fields_on_atomic_rows(field: str) -> None:
    record = _v2_development_record()
    record[field] = True

    assert f"/{field}" in validate_record(record)


def test_cli_rejects_duplicate_atomic_identity_keys(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = _v2_development_record()
    second = _v2_development_record()
    second["record_id"] = "synthetic-v2-dev-002"
    path = tmp_path / "records.json"
    path.write_text(json.dumps([first, second]), encoding="utf-8")

    assert validate.main([str(path)]) == 1
    assert "/1/identity" in capsys.readouterr().err


@pytest.mark.parametrize(
    "field",
    ["build_fingerprint", "config_digest", "bundle_digest", "trace_index_digest"],
)
def test_rejects_v2_digest_format_mismatches(field: str) -> None:
    record = _v2_development_record()
    record[field] = "not-a-digest"

    assert f"/{field}" in validate_record(record)


def test_verify_result_digests_hashes_named_payload_bytes() -> None:
    record = _v2_development_record()
    artifacts = {
        "build.json": b'{"build":true}\n',
        "config.json": b'{"config":true}\n',
        "bundle-manifest.json": b'{"bundle":true}\n',
        "traces.jsonl": b'{"question_id":"q1"}\n',
    }
    for field, name in DIGEST_PAYLOAD_NAMES.items():
        digest = hashlib.sha256(artifacts[name]).hexdigest()
        record[field] = f"sha256:{digest}"

    assert verify_result_digests(record, artifacts) == []

    artifacts["build.json"] = b'{"build":false}\n'
    assert "/build_fingerprint" in verify_result_digests(record, artifacts)


def test_accepts_exploratory_projection_over_compatible_records() -> None:
    records = [_v2_development_record()]
    assert validate_projection(_projection(["synthetic-v2-dev-001"]), records) == []


@pytest.mark.parametrize(
    "field",
    [
        "projection_id",
        "filters",
        "compatibility_key",
        "exclusions",
        "numerator",
        "denominator",
        "uncertainty_method",
    ],
)
def test_rejects_incomplete_projection_contract(field: str) -> None:
    projection = _projection(["synthetic-v2-dev-001"])
    del projection[field]

    assert f"/{field}" in validate_projection(projection, [_v2_development_record()])


def test_rejects_empty_projection_sources() -> None:
    projection = _projection([])

    assert "/source_record_ids" in validate_projection(projection, [])


def test_rejects_certified_blend_of_official_and_enhanced_records() -> None:
    records = [_v2_official_record(), _v2_successor_record()]
    projection = _projection(
        ["synthetic-v2-official-001", "synthetic-v2-successor-001"],
        certified=True,
        kind="certified",
    )

    errors = validate_projection(projection, records)
    assert "/certified" in errors


def test_rejects_incompatible_track_scorer_division_metric_or_resource() -> None:
    official = _v2_official_record()
    successor = _v2_successor_record()
    projection = _projection(
        ["synthetic-v2-official-001", "synthetic-v2-successor-001"],
        compatibility_key={
            "track_kind": "OFFICIAL-UPSTREAM",
            "benchmark_id": "synthetic-retrieval",
            "benchmark_version": "1",
            "scorer_digest": f"sha256:{'11' * 32}",
            "division": "COMPONENT-CLOSED",
            "metric": {
                "name": "recall_at_10",
                "family": "retrieval",
                "unit": "ratio",
            },
            "resource_treatment": "verified",
        },
    )

    assert "/compatibility_key/track_kind" in validate_projection(
        projection, [official, successor]
    )


def test_rejects_projection_with_mismatched_benchmark_or_scorer() -> None:
    record = _v2_official_record()
    projection = _projection(
        ["synthetic-v2-official-001"],
        compatibility_key={
            "track_kind": "OFFICIAL-UPSTREAM",
            "benchmark_id": "synthetic-retrieval",
            "benchmark_version": "1",
            "scorer_digest": f"sha256:{'11' * 32}",
            "division": "COMPONENT-CLOSED",
            "metric": {
                "name": "recall_at_10",
                "family": "retrieval",
                "unit": "ratio",
            },
            "resource_treatment": "verified",
        },
    )
    assert validate_projection(projection, [record]) == []

    mismatched_benchmark = copy.deepcopy(record)
    mismatched_benchmark["benchmark"] = "other-suite"
    identity = mismatched_benchmark["identity"]
    assert isinstance(identity, dict)
    identity["benchmark_id"] = "other-suite"
    assert "/compatibility_key/benchmark_id" in validate_projection(
        projection, [mismatched_benchmark]
    )

    mismatched_version = copy.deepcopy(record)
    mismatched_version["benchmark_version"] = "2"
    version_identity = mismatched_version["identity"]
    assert isinstance(version_identity, dict)
    version_identity["benchmark_version"] = "2"
    assert "/compatibility_key/benchmark_version" in validate_projection(
        projection, [mismatched_version]
    )

    mismatched_scorer = copy.deepcopy(record)
    lineage = mismatched_scorer["lineage"]
    assert isinstance(lineage, dict)
    fidelity = lineage["fidelity"]
    assert isinstance(fidelity, dict)
    fidelity["scorer_digest"] = f"sha256:{'22' * 32}"
    assert "/compatibility_key/scorer_digest" in validate_projection(
        projection, [mismatched_scorer]
    )


def test_safety_gate_failure_is_visible_and_non_averageable() -> None:
    record = _v2_development_record()
    record["safety_gates"] = [{"name": "no-leakage", "status": "failed"}]
    projection = _projection(["synthetic-v2-dev-001"])

    errors = validate_projection(projection, [record])
    assert "/safety_failures_visible" in errors

    projection["safety_failures_visible"] = True
    projection["failed_count"] = 0
    assert "/failed_count" in validate_projection(projection, [record])

    projection["failed_count"] = 1
    projection["weighting"] = {"formula": "unweighted-mean", "disclosed": True}
    assert "/weighting" in validate_projection(projection, [record])


@pytest.mark.parametrize(
    ("outcome", "count_field"),
    [
        ("missing", "missing_count"),
        ("unsupported", "unsupported_count"),
        ("failed", "failed_count"),
        ("aborted", "aborted_count"),
        ("not-measured", "not_measured_count"),
    ],
)
def test_projection_keeps_distinct_non_measured_states(
    outcome: str, count_field: str
) -> None:
    record = _v2_development_record()
    record["attempt_outcome"] = outcome
    projection = _projection(["synthetic-v2-dev-001"])

    assert f"/{count_field}" in validate_projection(projection, [record])

    projection[count_field] = 1
    if outcome == "failed":
        projection["safety_failures_visible"] = True
        projection["weighting"] = None
    assert validate_projection(projection, [record]) == []


def test_cli_validates_v2_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "v2.json"
    path.write_text(json.dumps(_v2_development_record()), encoding="utf-8")

    assert validate.main([str(path)]) == 0
    assert capsys.readouterr().err == ""


def test_operator_run_cannot_claim_headline_eligibility() -> None:
    record = _v2_official_record()
    publication = record["publication"]
    assert isinstance(publication, dict)
    publication["pbpp_headline_eligible"] = True

    assert "/publication/pbpp_headline_eligible" in validate_record(record)
    assert publication["label"] == "operator-run"


def test_independent_signer_does_not_upgrade_headline() -> None:
    record = _v2_official_record()
    record["signer_role"] = "independent"
    publication = record["publication"]
    assert isinstance(publication, dict)

    assert validate_record(record) == []
    assert publication["pbpp_headline_eligible"] is False
    assert publication["label"] == "operator-run"

    publication["pbpp_headline_eligible"] = True
    assert "/publication/pbpp_headline_eligible" in validate_record(record)


def test_implemented_evidence_cannot_upgrade_admission_to_run_ready() -> None:
    record = _v2_official_record()
    record["evidence_level"] = "IMPLEMENTED"
    record["admission_state"] = "RUN-READY-OFFICIAL-LOCAL"

    assert "/admission_state" in validate_record(record)


def test_v1_schema_bytes_are_not_reinterpreted_as_v2() -> None:
    v1 = _retrieval_record()
    assert v1["schema_version"] == SCHEMA_VERSION
    assert validate_record(v1) == []
    assert Path("leaderboard/schema/result-v1.schema.json").read_bytes()
    v1["pbpp_headline_eligible"] = True
    assert "/pbpp_headline_eligible" in validate_record(v1)
