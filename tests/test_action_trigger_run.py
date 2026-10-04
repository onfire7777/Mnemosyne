from copy import deepcopy

import pytest

from eval.public.action_trigger_run import make_plan, reports


def empty_trace():
    plan = make_plan()
    records = []
    for case in plan['cases']:
        now = None
        for step, operation in enumerate(case['operations']):
            response = {}
            if operation['command'] == 'clock.inject':
                now = operation['payload']['now']
            if operation['command'] == 'intention.observe':
                response = {'action_ids': [], 'queried_channels': [], 'evaluated_at': now,
                            'evaluation_wall_ms': 1, 'firing_observations': []}
            records.append({'case_id': case['case_id'], 'step': step, **deepcopy(operation), 'response': response})
    return plan, records


def test_complete_nonfiring_trace_cannot_pass_despite_complete_execution():
    plan, records = empty_trace()
    result = reports(plan, records)
    assert result['ordered_workload_verified'] is True
    assert result['publishable'] is False
    assert len(result['cases']) == 5
    for case in result['cases']:
        report = case['report']
        assert report['metrics']['true_positives'] == 0
        assert report['metrics']['false_negatives'] == 26
        assert report['metrics']['recall'] == 0
        assert report['no_observed_opportunity'] == 14
        assert len(report['by_trigger']) == 5


@pytest.mark.parametrize('mutation', ['drop', 'extra', 'reorder', 'payload', 'clock', 'step', 'response', 'gold'])
def test_trace_and_plan_tampering_fails_closed(mutation):
    plan, records = empty_trace()
    if mutation == 'drop':
        records.pop()
    elif mutation == 'extra':
        records.append(deepcopy(records[-1]))
    elif mutation == 'reorder':
        records[0], records[1] = records[1], records[0]
    elif mutation == 'payload':
        record = next(row for row in records if row['command'] == 'event.inject')
        record['payload']['event_type'] = 'different-event'
    elif mutation == 'clock':
        record = next(row for row in records if row['command'] == 'intention.observe')
        record['response']['evaluated_at'] = '2000-01-01T00:00:00Z'
    elif mutation == 'step':
        records[0]['step'] = False
    elif mutation == 'response':
        records[0]['response'] = {'unexpected': True}
    else:
        plan['cases'][0]['expected'][0]['windows'] = []
    with pytest.raises(ValueError):
        reports(plan, records)


def test_plan_is_deterministic_and_has_no_gold_in_candidate_payloads():
    assert make_plan() == make_plan()
    for case in make_plan()['cases']:
        assert len(case['expected']) == 40
        for operation in case['operations']:
            assert not {'expected', 'windows', 'cancelled_at'} & operation['payload'].keys()


@pytest.mark.parametrize('damage', [None, 'report', 'status', 'oversized'])
def test_saved_replay_checks_reports_completion_and_size(tmp_path, damage):
    from eval.public.action_trigger_run import recompute
    from eval.public.bundle import _canonical

    plan, records = empty_trace()
    result = reports(plan, records)
    (tmp_path / 'plan.json').write_bytes(_canonical(plan))
    (tmp_path / 'operations.jsonl').write_bytes(b''.join(_canonical(row) for row in records))
    (tmp_path / 'status.json').write_bytes(_canonical({
        'status': 'failed' if damage == 'status' else 'completed',
        'completed_operations': len(records), 'publishable': False,
    }))
    if damage == 'report':
        result['cases'][0]['report']['metrics']['recall'] = 1
    (tmp_path / 'reports.json').write_bytes(_canonical(result))
    if damage == 'oversized':
        (tmp_path / 'plan.json').write_bytes(b' ' * (16 * 1024 * 1024 + 1))
    if damage:
        with pytest.raises(ValueError):
            recompute(tmp_path)
    else:
        assert recompute(tmp_path) == result


def test_retained_real_public_cli_capture_replays():
    from pathlib import Path
    from eval.public.action_trigger_run import recompute

    root = Path(__file__).resolve().parents[1]
    result = recompute(root / 'eval/reports/m12-explicit-trigger-development-2026-10-04')
    assert sum(c['report']['metrics']['true_positives'] for c in result['cases']) == 130
    assert all(c['report']['metrics']['false_positives'] == 0 for c in result['cases'])
    assert all(c['report']['metrics']['false_negatives'] == 0 for c in result['cases'])


def test_replay_rejects_boolean_signal_rewritten_as_integer():
    plan, records = empty_trace()
    condition = next(r for r in records if r['command'] == 'event.inject' and r['payload'].get('value') is True)
    condition['payload']['value'] = 1
    with pytest.raises(ValueError):
        reports(plan, records)
