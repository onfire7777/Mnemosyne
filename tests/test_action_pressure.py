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


def test_command_duration_cannot_exceed_observed_response_interval():
    case = pressure.make_plan()['cases'][0]
    records = [tick(case, 700_000_000, 900_000_000), tick(case, 1_640_000_000, 1_700_000_000)]
    records[0]['response']['evaluation_wall_ms'] = 250
    with pytest.raises(ValueError):
        pressure.score_case(case, records)


def test_retained_full_capture_hashes_and_stricter_timing_validation():
    import hashlib
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]/'eval/reports/m12-clocked-pressure-2026-10-04'
    manifest = json.loads((root/'manifest.json').read_text())
    for relative, digest in manifest['files'].items():
        assert hashlib.sha256((root/relative).read_bytes()).hexdigest() == digest
    source = json.loads((root/'workload/source.json').read_text())
    assert source['source_dirty'] is False
    assert hashlib.sha256((root/'source/action_pressure.py.txt').read_bytes()).hexdigest() == source['harness_files']['eval/public/action_pressure.py']
    plan = json.loads((root/'workload/plan.json').read_text())
    assert plan == pressure.make_plan()
    timings = [json.loads(line) for line in (root/'workload/timings.jsonl').read_text().splitlines()]
    expected = json.loads((root/'workload/reports.json').read_text())
    for case, saved in zip(plan['cases'], expected['cases'], strict=True):
        rows = [{k:v for k,v in row.items() if k not in ('case_id','index')}
                for row in timings if row['case_id']==case['case_id']]
        assert pressure.score_case(case, rows) == saved
    assert sum(row['full_workload_metrics']['false_negatives'] for row in expected['cases']) == 113
    assert all(row['exact_drain_recovered'] for row in expected['cases'])


@pytest.mark.parametrize('transport', ['cli','mcp-stdio'])
def test_service_profile_preserves_workload_and_replays(tmp_path,monkeypatch,transport):
    plan = pressure.make_service_plan()
    original = pressure.make_plan()
    assert plan['cases']==original['cases']
    assert plan['max_ticks']==4096 and plan['schema']!='m12-clocked-pressure/v1'
    plan['cases']=plan['cases'][:1]
    case=plan['cases'][0]
    keep={row['action_id'] for row in case['expected'][:2]}
    case['expected']=[r for r in case['expected'] if r['action_id'] in keep]
    case['setup']=[op for op in case['setup'] if op['payload'].get('task_id') in keep or op['command']=='clock.inject']
    monkeypatch.setattr(pressure,'make_service_plan',lambda:deepcopy(plan))
    output=tmp_path/transport
    result=pressure.run_development(output,transport=transport)
    assert pressure.recompute(output)==result
    assert result['cases'][0]['exact_drain_recovered'] is True


def test_retained_paired_transport_evidence_replays_and_preserves_failures():
    import hashlib
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]/'eval/reports/m12-transport-pressure-2026-10-04'
    manifest = json.loads((root/'manifest.json').read_text())
    for relative, digest in manifest['files'].items():
        assert hashlib.sha256((root/relative).read_bytes()).hexdigest() == digest
    summary = json.loads((root/'comparison.json').read_text())
    assert summary['ranking_eligible'] is False
    plans = []
    for transport, expected_missed in [('cli', 120), ('mcp-stdio', 0)]:
        output = root/transport/'workload'
        plans.append(json.loads((output/'plan.json').read_text()))
        report = pressure.recompute(output)
        assert report == json.loads((output/'reports.json').read_text())
        missed = sum(c['full_workload_metrics']['false_negatives'] for c in report['cases'])
        assert missed == expected_missed == summary['transports'][transport]['missed_triggers']
        assert all(c['exact_drain_recovered'] for c in report['cases'])
        assert all(c['full_workload_metrics']['false_positives'] == 0 for c in report['cases'])
    assert plans[0] == plans[1] == pressure.make_service_plan()
