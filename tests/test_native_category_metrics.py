"""Native summaries preserve denominators and missingness without invented CIs."""
from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from leaderboard.native_metrics import category_metric, validate_category_metric
from leaderboard.validate import validate_record
from leaderboard.render import _record_details
from leaderboard.grouping import build_comparison_index
from leaderboard.workspace import comparison_body
from tests.test_leaderboard_result_contract import _retrieval_record, _v2_development_record, _v2_official_record
from tests.test_leaderboard_grouping import _input


def metric(*, family="reference_qa", source=3, observed=2, applicable=1):
    return category_metric({"source_count": source, "scored_count": observed,
        "missing_count": source - observed, "native_recall_count": applicable,
        "rounded_qa_sum": observed * .5, "native_recall_sum": applicable * .5},
        4, family=family, scorer_digest="sha256:" + "c" * 64)


@pytest.mark.parametrize("item,expected", [
    (metric(), (1 / 3, "incomplete", 3)),
    (metric(family="retrieval"), (.5, "incomplete", 1)),
    (metric(source=0, observed=0, applicable=0), (None, "absent-category", 0)),
    (metric(source=2, observed=0, applicable=0), (0, "incomplete", 2)),
    (metric(family="retrieval", source=2, observed=0, applicable=0), (None, "incomplete", 0)),
    (metric(family="retrieval", source=2, observed=2, applicable=0), (None, "not-applicable", 0)),
    (metric(source=2, observed=2, applicable=1), (.5, "measured", 2)),
])
def test_native_descriptive_metrics_validate_and_render(item, expected):
    assert (item["value"], item["status"], item["denominator"]) == expected
    assert validate_category_metric(item, "/metric") == []
    record = _v2_development_record()
    record["metrics"] = [item]
    schema = json.loads(Path("leaderboard/schema/result-v2.schema.json").read_text())
    assert list(Draft202012Validator(schema).iter_errors(record)) == []
    assert validate_record(record) == []
    html = _record_details(record)
    assert "uncertainty not estimated" in html
    assert f"missing {item['missing_count']}" in html
    assert f"Score denominator: {expected[2]}" in html
    assert "None" not in html
    if item["family"] == "reference_qa" and item["missing_count"]:
        assert "Missing answers contribute zero" in html
    legacy = _retrieval_record()
    legacy["metrics"] = [item]
    assert validate_record(legacy)


@pytest.mark.parametrize("field,value", [
    ("value", .9), ("denominator", 2), ("missing_count", 0), ("observed_count", True),
    ("name", "qa_category_3"), ("category", 8), ("numerator", 3),
    ("confidence_interval", {"low": 0, "high": 1}), ("uncertainty_method", "bootstrap"),
    ("status", "measured"), ("scorer_digest", "floating"), ("extra", True),
])
def test_native_descriptive_metrics_reject_changed_meaning(field, value):
    item = metric()
    item[field] = value
    record = _v2_development_record()
    record["metrics"] = [item]
    assert validate_record(record)


def test_native_summary_does_not_open_official_or_publication_path():
    record = _v2_official_record()
    record["metrics"] = [metric(source=2, observed=2)]
    schema = json.loads(Path("leaderboard/schema/result-v2.schema.json").read_text())
    assert list(Draft202012Validator(schema).iter_errors(record))
    assert "/track_kind" in validate_record(record)
    record = _v2_development_record()
    record["metrics"] = [metric()]
    record["publication"]["publishable"] = True
    assert list(Draft202012Validator(schema).iter_errors(record))
    assert "/publication/publishable" in validate_record(record)


def test_native_comparisons_keep_unavailable_categories_visible_and_methods_separate():
    record, payloads = _input()
    good = metric(source=2, observed=2)
    absent = metric(source=0, observed=0, applicable=0)
    absent.update(name="qa_category_5", category=5)
    record["metrics"] = [good, absent]
    index = build_comparison_index([record], {"one": payloads})
    assert len(index["groups"]) == 1
    assert index["exclusions"] == [{"record_id": "one", "metric": "qa_category_5", "reason": "metric-absent-category"}]
    assert index["groups"][0]["compatibility"]["summary"]["uncertainty_method"] == "not-estimated"
    body = comparison_body(index)
    assert "qa_category_5" in body and "metric absent category" in body
    assert "Not estimated (descriptive)" in body
    changed = deepcopy(record)
    changed["metrics"] = [{**good, "scorer_digest": "sha256:" + "d" * 64}]
    rejected = build_comparison_index([changed], {"one": payloads})
    assert rejected["groups"] == []
    assert rejected["exclusions"][0]["reason"] == "metric-scorer-mismatch"
