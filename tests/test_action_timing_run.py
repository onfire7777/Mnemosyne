import json
import random
import shutil
from pathlib import Path

import pytest

from eval.public.action_cli import ActionCLI
from eval.public.action_timing_run import make_plan, recompute, run_development


def test_plan_is_stable_and_does_not_consume_ambient_randomness():
    before = random.getstate()
    assert make_plan() == make_plan()
    assert random.getstate() == before
    plan = make_plan()
    assert [case["seed"] for case in plan["cases"]] == [7, 19, 41, 73, 101]
    assert all(len(case["operations"]) == 29 for case in plan["cases"])
    assert all(len(case["expected"]) == 8 for case in plan["cases"])
    assert all("expected" not in json.dumps(op) for case in plan["cases"] for op in case["operations"])


@pytest.fixture(scope="module")
def completed(tmp_path_factory):
    output = tmp_path_factory.mktemp("timing") / "run"
    result = run_development(output, with_sink=True)
    return output, result


def test_real_public_run_recomputes_all_five_cases(completed):
    output, result = completed
    assert recompute(output) == result
    assert len(result["cases"]) == 5
    for case in result["cases"]:
        report = case["report"]
        assert report["expected_occurrences"] == 8
        assert report["lateness_observed_denominator"] == 6
        assert report["status_counts"]["cancelled-unfired"] == 2
        assert report["status_counts"]["early"] == report["status_counts"]["missed"] == 0
        assert report["status_counts"]["pending"] == report["status_counts"]["cancelled-fired"] == 0
        assert report["duplicate_observations"] == report["reported_due_drift_observations"] == 0
        assert report["unexpected_observations"] == []
        assert report["evaluation_command_wall_ms"] > 0
    status = json.loads((output / "status.json").read_text())
    assert status == {"status": "completed", "completed_operations": 145, "publishable": False}
    annex = json.loads((output / "sink.json").read_text())
    for case in annex["cases"]:
        assert len(case["snapshot"]["receipts"]) == 6
        attempts = case["snapshot"]["attempts"]
        assert len(attempts) == 12
        assert sum(row["outcome"] == "accepted" for row in attempts) == 6
        assert sum(row["origin"] == "harness-retry" and row["outcome"] == "duplicate" for row in attempts) == 6
    with pytest.raises(FileExistsError):
        run_development(output)


@pytest.mark.parametrize("change", ["omit", "clock", "report", "plan", "sink"])
def test_recompute_rejects_missing_or_inconsistent_evidence(completed, tmp_path, change):
    original, _ = completed
    output = tmp_path / "run"
    shutil.copytree(original, output)
    operations = output / "operations.jsonl"
    if change in {"omit", "clock"}:
        rows = [json.loads(line) for line in operations.read_text().splitlines()]
        if change == "omit":
            rows.pop()
        else:
            row = next(r for r in rows if r["command"] == "intention.observe")
            row["response"]["evaluated_at"] = "2040-01-01T00:00:00Z"
        operations.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    elif change == "report":
        path = output / "reports.json"
        value = json.loads(path.read_text())
        value["cases"][0]["report"]["duplicate_observations"] = False
        path.write_text(json.dumps(value), encoding="utf-8")
    elif change == "plan":
        path = output / "plan.json"
        value = json.loads(path.read_text())
        value["cases"][0]["expected"].pop()
        path.write_text(json.dumps(value), encoding="utf-8")
    else:
        path = output / "sink.json"
        value = json.loads(path.read_text())
        value["cases"][0]["snapshot"]["attempts"].pop()
        path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError):
        recompute(output)


def test_failed_run_retains_partial_operations_without_exception_secrets(tmp_path, monkeypatch):
    calls = 0

    def fail(self, *args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("sensitive exception text")
        return {}

    monkeypatch.setattr(ActionCLI, "run", fail)
    output = tmp_path / "failed"
    with pytest.raises(RuntimeError):
        run_development(output)
    status = json.loads((output / "status.json").read_text())
    assert status == {"status": "failed", "exception_type": "RuntimeError",
                      "completed_operations": 1, "publishable": False}
    assert len((output / "operations.jsonl").read_text().splitlines()) == 1
    assert not (output / "reports.json").exists()
    assert all("sensitive exception text" not in path.read_text() for path in output.iterdir())
    with pytest.raises(ValueError, match="did not complete"):
        recompute(output)


def test_pre_sink_saved_capture_still_recomputes():
    root = Path(__file__).resolve().parents[1]
    result = recompute(root / "eval/reports/m12-exact-time-development-2026-10-04")
    assert len(result["cases"]) == 5


def test_replay_rejects_integer_recurrence_rewritten_as_float():
    from eval.public.action_timing_run import _reports

    root = Path(__file__).resolve().parents[1] / 'eval/reports/m12-exact-time-development-2026-10-04'
    plan = json.loads((root / 'plan.json').read_text())
    records = [json.loads(row) for row in (root / 'operations.jsonl').read_text().splitlines()]
    records[0]['payload']['recurrence_policy']['max_occurrences'] = 4.0
    with pytest.raises(ValueError):
        _reports(plan, records)
