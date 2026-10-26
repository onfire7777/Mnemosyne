"""Synthetic report/subprocess-contract tests; never run the quality harness."""

import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from eval import run_quality_gate as gate
from eval.tests import test_quality_gate as contract


@pytest.fixture(autouse=True)
def no_real_subprocess(monkeypatch):
    monkeypatch.setattr(contract.subprocess, "run", lambda *a, **kw: pytest.fail("unexpected real subprocess"))


def baseline():
    return json.loads(contract.BASELINE_PATH.read_text(encoding="utf-8"))


def candidate(split="all", *, composite=None):
    source = baseline()
    report = copy.deepcopy(source)
    target = source["summary"] if split == "all" else source["split_breakdown"][split.replace("-", "_")]
    report["meta"]["split"] = split
    report["summary"]["composite_score"] = target["composite_score"] if composite is None else composite
    report["query_details"] = [row for row in report["query_details"] if split == "all" or row["split"] == split]
    report["verdicts"] += [
        {"check": "pareto_no_quality_drop", "target": target["composite_score"], "passed": True},
        {"check": "pareto_no_safety_drop", "target": source["summary"]["poison_block_rate"], "passed": True},
    ]
    return report


def integration_module():
    path = Path(__file__).with_name("test_quality_gate_baseline_reproducible.py")
    spec = importlib.util.spec_from_file_location("quality_gate_integration_contract", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("split,expected", [("dev", .2), ("held-out", .9), ("all", .6)])
def test_baseline_targets_use_matching_partition(split, expected):
    synthetic = {"summary": {"composite_score": .6, "poison_block_rate": 1.0},
                 "split_breakdown": {"dev": {"composite_score": .2}, "held_out": {"composite_score": .9}}}
    assert gate._baseline_targets(synthetic, split) == (expected, 1.0)


def test_missing_baseline_split_fails_instead_of_using_all_aggregate():
    with pytest.raises(ValueError):
        gate._baseline_targets({"summary": {"composite_score": .6, "poison_block_rate": 1.0}}, "dev")
    with pytest.raises(ValueError):
        gate._baseline_targets({"summary": {}}, "other")


def test_saturation_is_diagnostic_and_cannot_reject_improved_candidate():
    verdicts = [{"check": "non_saturation", "passed": False, "value": 1.0, "target": 1.0, "operator": "<"},
                {"check": "pareto_no_quality_drop", "passed": True, "value": 1.0, "target": .6, "operator": ">="},
                {"check": "pareto_no_safety_drop", "passed": True, "value": 1.0, "target": 1.0, "operator": ">="}]
    assert gate._gate_passes(verdicts)
    assert not gate._gate_passes([])
    assert not gate._gate_passes(verdicts[:1])


@pytest.mark.parametrize("name", ["poison_block_rate", "benign_false_positive_rate", "cognitive_integrity",
                                 "pareto_no_quality_drop", "pareto_no_safety_drop"])
def test_quality_and_safety_failures_still_block_gate(name):
    assert not gate._gate_passes([{"check": name, "passed": False, "value": .5, "target": 1.0, "operator": ">="}])


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), True, "0.5", None, [], -1, 2])
@pytest.mark.parametrize("field", ["composite_score", "poison_block_rate"])
def test_nonfinite_or_malformed_baseline_thresholds_are_rejected(value, field):
    source = {"summary": {"composite_score": .5, "poison_block_rate": 1.0}}
    source["summary"][field] = value
    with pytest.raises(ValueError):
        gate._baseline_targets(source, "all")


@pytest.mark.parametrize("source", [None, [], {}, {"summary": []}, {"summary": {}}])
def test_malformed_baseline_objects_are_rejected(source):
    with pytest.raises(ValueError):
        gate._baseline_targets(source, "all")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), True, "0.5", None, [], -1, 2])
@pytest.mark.parametrize("field", ["value", "target"])
def test_nonfinite_or_malformed_verdict_scores_fail_closed(value, field):
    verdict = {"check": "pareto_no_quality_drop", "passed": True, "value": .8, "target": .5, "operator": ">="}
    verdict[field] = value
    assert not gate._gate_passes([verdict])


@pytest.mark.parametrize("malformed", [None, {}, [None], [{}], [{"check": "non_saturation"}]])
def test_malformed_verdict_records_fail_closed(malformed):
    assert not gate._gate_passes(malformed)


def test_verdict_pass_flag_cannot_override_failed_comparison_or_invalid_operator():
    verdict = {"check": "pareto_no_quality_drop", "passed": True, "value": .4, "target": .5, "operator": ">="}
    assert not gate._gate_passes([verdict])
    verdict.update(value=.8, operator="unsupported")
    assert not gate._gate_passes([verdict])
    verdict.update(operator=">=")
    assert not gate._gate_passes([verdict, verdict])


def test_markdown_reports_observed_calibration_without_obsolete_floor_claims():
    report = baseline()
    markdown = gate._build_markdown_summary(report, report["meta"]["dataset_manifest"])
    assert "Observed calibration error for the selected partition" in markdown
    assert "support_floor" not in markdown and "clamping artifact" not in markdown


def test_dev_contract_uses_dev_floor_not_higher_all_floor():
    report = candidate("dev")
    assert report["summary"]["composite_score"] < baseline()["summary"]["composite_score"]
    contract._assert_nonregression(report, baseline(), "dev")


def test_report_contract_accepts_safe_improvement_above_difficulty_ceiling():
    report = candidate("dev", composite=.99)
    report["verdicts"][0]["passed"] = False
    assert report["verdicts"][0]["check"] == "non_saturation"
    contract._assert_nonregression(report, baseline(), "dev")


def test_report_contract_rejects_wrong_split_target_and_missing_safety_verdict():
    report = candidate("dev")
    report["verdicts"][-2]["target"] = baseline()["summary"]["composite_score"]
    with pytest.raises(AssertionError):
        contract._assert_nonregression(report, baseline(), "dev")
    report = candidate("dev")
    report["verdicts"].pop()
    with pytest.raises(AssertionError, match="Missing required"):
        contract._assert_nonregression(report, baseline(), "dev")


@pytest.mark.parametrize("split", ["dev", "held-out", "all"])
def test_each_partition_rejects_its_own_quality_drop(split):
    report = candidate(split)
    report["summary"]["composite_score"] -= .001
    with pytest.raises(AssertionError, match="matching split"):
        contract._assert_nonregression(report, baseline(), split)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "wrong_split", "substituted_id", "manifest"])
def test_fresh_coverage_rejects_incomplete_or_replaced_query_set(mutation):
    report = candidate("dev")
    if mutation == "missing":
        report["query_details"].pop()
    elif mutation == "duplicate":
        report["query_details"][-1] = copy.deepcopy(report["query_details"][0])
    elif mutation == "wrong_split":
        report["query_details"][0]["split"] = "held-out"
    elif mutation == "substituted_id":
        report["query_details"][0]["qid"] = "substitute"
    else:
        report["meta"]["dataset_manifest"] = {}
    with pytest.raises(AssertionError):
        contract._assert_fresh_coverage(report, "dev")


@pytest.mark.parametrize("split", ["dev", "held-out", "all"])
def test_release_partition_orchestration_uses_fresh_matching_report(monkeypatch, tmp_path, split):
    calls = []

    def stub(command, **kwargs):
        calls.append(command)
        assert command[command.index("--split") + 1] == split
        Path(command[command.index("--report") + 1]).write_text(json.dumps(candidate(split)), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(contract.subprocess, "run", stub)
    contract.test_quality_gate_release_partition_nonregression(tmp_path, split)
    assert len(calls) == 1 and "--assert-gate" in calls[0]


@pytest.mark.parametrize("changed", [None, "confidence", "retrieved_ids", "ece"])
def test_current_run_determinism_keeps_stable_detail_and_preserves_all_split_coverage(monkeypatch, tmp_path, changed):
    calls = []

    def stub(command, **kwargs):
        calls.append(command)
        assert command[command.index("--split") + 1] == "all"
        assert command[command.index("--seed") + 1] == "42"
        report = candidate("all", composite=.8)  # Improvement must not need a rewritten baseline.
        report["meta"]["generated_at"] = f"run-{len(calls)}"
        report["meta"]["runtime_seconds"] = len(calls)
        report["query_details"][0]["latency_ms"] = len(calls)
        if changed and len(calls) == 2:
            if changed == "ece":
                report["summary"]["ece"] += .01
            elif changed == "confidence":
                report["query_details"][0]["confidence"] = .123456
            else:
                report["query_details"][0]["retrieved_ids"] = ["different-rank"]
        Path(command[command.index("--report") + 1]).write_text(json.dumps(report), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(contract.subprocess, "run", stub)
    test = integration_module().test_quality_gate_current_run_reproduces_bit_for_bit
    if changed:
        with pytest.raises(AssertionError, match="stable output"):
            test(tmp_path)
    else:
        test(tmp_path)
    assert len(calls) == 2
    assert calls[0][calls[0].index("--report") + 1] != calls[1][calls[1].index("--report") + 1]


@pytest.mark.parametrize("failure", ["nonzero", "missing_report"])
def test_runner_contract_rejects_failed_or_missing_result(monkeypatch, tmp_path, failure):
    monkeypatch.setattr(contract.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=1 if failure == "nonzero" else 0, stdout="", stderr="fixture failure"))
    with pytest.raises(AssertionError):
        contract._run_report(tmp_path, "dev")
