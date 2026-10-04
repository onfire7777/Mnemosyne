from copy import deepcopy

import pytest

from eval.public import action_pressure as pressure


def tick(case, start, end, firings=()):
    now = pressure.stamp(case, start)
    rows = [dict(row, evaluated_at=now, provider_evaluated_at=now) for row in firings]
    return {'dispatch_ns': start, 'response_ns': end, 'delivered_ns': end + 1000,
            'response': {'evaluated_at': now, 'action_ids': [row['action_id'] for row in rows],
                         'queried_channels': [], 'evaluation_wall_ms': (end-start)/1e6,
                         'firing_observations': rows}}


def test_plan_is_deterministic_and_never_sends_gold():
    plan = pressure.make_plan()
    assert plan == pressure.make_plan()
    assert [case['seed'] for case in plan['cases']] == [7, 19, 41, 73, 101]
    for case in plan['cases']:
        assert len(case['expected']) == 72
        assert sum(row['cancelled_at'] is None for row in case['expected']) == 64
        assert sum(row['trigger_type'] == 'time_window' for row in case['expected']) == 32
        for op in case['setup']:
            assert not {'expected', 'windows', 'cancelled_at'} & op['payload'].keys()


def test_missed_windows_count_even_without_a_polling_opportunity():
    case = pressure.make_plan()['cases'][0]
    result = pressure.score_case(case, [tick(case, 700_000_000, 900_000_000),
                                      tick(case, 1_640_000_000, 1_700_000_000)])
    assert result['full_workload_metrics']['false_negatives'] == 64
    assert result['tick_conditional']['metrics']['false_negatives'] == 32
    assert result['samples'][0]['expired_unobserved_windows'] == 32
    assert result['samples'][-1]['pending_exact'] == 32
    assert result['exact_drain_recovered'] is False
    assert result['ranking_eligible'] is False


def test_duplicate_and_cancelled_outputs_are_not_lost_in_backlog_metrics():
    case = pressure.make_plan()['cases'][0]
    live, cancelled = case['expected'][0], case['expected'][-1]
    def firing(row):
        return {name:row[name] for name in ('action_id','occurrence','trigger_type','due_at')} | {'intention_id':row['action_id']}
    records = [tick(case, 700_000_000, 900_000_000, [firing(live), firing(live), firing(cancelled)]),
               tick(case, 1_640_000_000, 1_700_000_000)]
    result = pressure.score_case(case, records)
    assert result['full_workload_metrics'] == {'true_positives':1,'false_positives':2,'false_negatives':63,
        'precision':1/3,'recall':1/64,'f1':2/67}
    assert result['tick_conditional']['duplicate_observations'] == 1
    assert result['response_lateness_seconds'][0]['seconds'] == .9
    assert result['samples'][0]['pending_exact'] == 31


@pytest.mark.parametrize('mutation', ['bool','backwards','clock','missing-drain'])
def test_corrupt_or_incomplete_timelines_are_rejected(mutation):
    case = pressure.make_plan()['cases'][0]
    records = [tick(case, 700_000_000, 900_000_000), tick(case, 1_640_000_000, 1_700_000_000)]
    if mutation == 'bool':
        records[0]['dispatch_ns'] = True
    if mutation == 'backwards':
        records[1]['dispatch_ns'] = 800_000_000
    if mutation == 'clock':
        records[0]['response']['evaluated_at'] = pressure.stamp(case, 0)
    if mutation == 'missing-drain':
        records.pop()
    with pytest.raises(ValueError):
        pressure.score_case(case, records)


def test_public_runner_replays_and_retains_every_delivery(tmp_path, monkeypatch):
    plan = deepcopy(pressure.make_plan())
    plan['cases'] = plan['cases'][:1]
    case = plan['cases'][0]
    keep = {row['action_id'] for row in case['expected'][:4] + case['expected'][-1:]}
    case['expected'] = [row for row in case['expected'] if row['action_id'] in keep]
    case['setup'] = [op for op in case['setup'] if op['payload'].get('task_id') in keep or op['command']=='clock.inject']
    monkeypatch.setattr(pressure, 'make_plan', lambda:deepcopy(plan))
    output = tmp_path/'run'
    result = pressure.run_development(output)
    assert pressure.recompute(output) == result
    assert result['cases'][0]['offered_live'] == 4
    assert result['cases'][0]['exact_drain_recovered'] is True
    assert (output/'sink.sqlite3').is_file()
    source = (output/'source.json').read_bytes()
    (output/'source.json').write_text('{}')
    with pytest.raises(ValueError):
        pressure.recompute(output)
    (output/'source.json').write_bytes(source)
    sink = (output/'sink.sqlite3').read_bytes()
    (output/'sink.sqlite3').write_bytes(b'bad database')
    with pytest.raises(ValueError):
        pressure.recompute(output)
    (output/'sink.sqlite3').write_bytes(sink)
    lines = (output/'operations.jsonl').read_text().splitlines()
    (output/'operations.jsonl').write_text('\n'.join(lines[:-1])+'\n')
    with pytest.raises(ValueError):
        pressure.recompute(output)


def test_failed_setup_retains_request_and_no_completed_report(tmp_path, monkeypatch):
    import json
    class Broken:
        def __init__(self, cli):
            pass
        def run(self, command, *args):
            if command == 'task.create':
                raise RuntimeError('private provider detail')
            return {}
    monkeypatch.setattr(pressure, 'ActionCLI', Broken)
    output = tmp_path/'failed'
    with pytest.raises(RuntimeError):
        pressure.run_development(output)
    status = json.loads((output/'status.json').read_text())
    assert status['status'] == 'failed' and status['completed_cases'] == 0
    assert not (output/'reports.json').exists()
    records = [json.loads(line) for line in (output/'operations.jsonl').read_text().splitlines()]
    assert records[-1]['kind'] == 'request' and records[-1]['command'] == 'task.create'
    assert 'private provider detail' not in (output/'status.json').read_text()
