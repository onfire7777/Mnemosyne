import copy
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from leaderboard import validate
from leaderboard.validate import validate_record


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
