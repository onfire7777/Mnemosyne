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
