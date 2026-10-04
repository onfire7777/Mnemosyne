from copy import deepcopy
import json
import random

import pytest

from eval.public import action_trigger_run
from eval.public.action_fanout_plan import make_fanout_plan


def test_fanout_plan_is_deterministic_and_includes_decoys():
    state = random.getstate()
    plan = make_fanout_plan()
    assert make_fanout_plan() == plan
    assert random.getstate() == state
    assert plan['fanout_per_trigger_by_week'] == [2, 4, 8, 16]
    assert len(plan['cases']) == 5
    for case in plan['cases']:
        assert len(case['expected']) == 180
        assert sum(bool(row['windows']) for row in case['expected']) == 150
        assert len(case['operations']) == 244
        for operation in case['operations']:
            assert not {'expected', 'windows', 'cancelled_at'} & operation['payload'].keys()


def test_real_first_week_fanout_delivers_all_types_once(tmp_path, monkeypatch):
    plan = make_fanout_plan()
    plan['cases'] = plan['cases'][:1]
    case = plan['cases'][0]
    cut = next(i for i, op in enumerate(case['operations']) if op['payload'].get('task_id', '').startswith('w1-'))
    case['operations'] = case['operations'][:cut]
    case['expected'] = case['expected'][:12]
    case['phases'] = case['phases'][:1]
    monkeypatch.setattr(action_trigger_run, 'make_fanout_plan', lambda: deepcopy(plan))
    output = tmp_path / 'fanout'
    result = action_trigger_run.run_development(output, with_sink=True, fanout=True)
    assert action_trigger_run.recompute(output) == result
    assert result['cases'][0]['by_load'][0]['fanout_per_trigger'] == 2
    assert result['cases'][0]['by_load'][0]['report']['metrics']['true_positives'] == 10
    report = result['cases'][0]['report']
    assert report['metrics']['true_positives'] == 10
    assert report['metrics']['false_positives'] == report['metrics']['false_negatives'] == 0
    assert report['no_observed_opportunity'] == 2
    assert len(report['by_trigger']) == 5
    assert report['duplicate_observations'] == report['reported_due_drift_observations'] == 0
    snapshot = json.loads((output / 'sink.json').read_text())['cases'][0]['snapshot']
    assert len(snapshot['receipts']) == 10
    assert len(snapshot['attempts']) == 20
    assert sum(row['outcome'] == 'duplicate' for row in snapshot['attempts']) == 10
    changed = deepcopy(plan)
    changed['fanout_per_trigger_by_week'][0] = 1
    records = [json.loads(line) for line in (output / 'operations.jsonl').read_text().splitlines()]
    with pytest.raises(ValueError):
        action_trigger_run.reports(changed, records)


@pytest.mark.parametrize('capture', [
    'm12-fanout-sink-development-2026-10-04',
    'm12-fanout-resource-development-2026-10-04',
])
def test_retained_full_fanout_capture_replays_with_per_load_evidence(capture):
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / 'eval/reports' / capture
    result = action_trigger_run.recompute(root)
    for load, count in ((2, 50), (4, 100), (8, 200), (16, 400)):
        reports = [p['report'] for c in result['cases'] for p in c['by_load']
                   if p['fanout_per_trigger'] == load]
        assert len(reports) == 5
        assert sum(r['metrics']['true_positives'] for r in reports) == count
        assert all(r['metrics']['false_positives'] == r['metrics']['false_negatives'] == 0 for r in reports)
        assert all(r['duplicate_observations'] == r['reported_due_drift_observations'] == 0 for r in reports)
    annex = json.loads((root / 'sink.json').read_text())
    assert sum(len(c['snapshot']['receipts']) for c in annex['cases']) == 750
    attempts = [row for c in annex['cases'] for row in c['snapshot']['attempts']]
    assert len(attempts) == 1500
    assert sum(row['outcome'] == 'accepted' for row in attempts) == 750
    assert sum(row['outcome'] == 'duplicate' for row in attempts) == 750
