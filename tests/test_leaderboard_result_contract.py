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
    forbidden_family_sets = [
        {
            item["contains"]["properties"]["family"]["const"]
            for item in rule["not"]["properties"]["metrics"]["allOf"]
        }
        for rule in schema["allOf"]
        if "not" in rule
    ]

    assert {"retrieval", "judged_qa"} in forbidden_family_sets
    assert {"retrieval"} not in forbidden_family_sets
    assert {"judged_qa"} not in forbidden_family_sets


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


def test_cli_validates_one_record_and_arrays(tmp_path: Path) -> None:
    path = tmp_path / "records.json"
    path.write_text(
        json.dumps([_retrieval_record(), _judged_qa_record()]),
        encoding="utf-8",
    )

    assert validate.main([str(path)]) == 0


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
