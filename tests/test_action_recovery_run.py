from copy import deepcopy
from types import SimpleNamespace

import pytest

from eval.harness.cli_driver import MnemoCLI
from eval.public.action_recovery_run import (
    InjectedResponseLoss, ResponseLossCLI, make_plan, reports, resolve_payload,
)


def synthetic_trace():
    """Deliberately no firings: completeness must still produce missed actions."""
    plan, records = make_plan(), []
    for case in plan['cases']:
        past, now = [], None
        for step, operation in enumerate(case['operations']):
            command, response = operation['command'], {}
            if command == 'clock.inject':
                now = operation['payload']['now']
            elif command == 'task.inspect':
                response = {
                    'task_id': operation['payload']['task_id'],
                    'intention_id': operation['payload']['task_id'] + '-identity',
                    'revision': f'{step:064x}',
                    'status': operation['check']['status'],
                    'action_id': operation['check']['action_id'],
                }
            elif command == 'intention.observe':
                response = {'action_ids': [], 'queried_channels': [], 'evaluated_at': now,
                            'evaluation_wall_ms': 1, 'firing_observations': []}
            row = {'case_id': case['case_id'], 'step': step, 'command': command,
                   'payload': deepcopy(operation['payload']), 'resolved_payload': resolve_payload(operation, past),
                   'outcome': 'lost_response_after_success' if operation['lose_response'] else 'ok',
                   'response': response}
            past.append(row)
            records.append(row)
    return plan, records


def test_complete_recovery_trace_without_actions_still_fails_recall():
    plan, records = synthetic_trace()
    result = reports(plan, records)
    assert result['publishable'] is False
    assert result['ordered_workload_verified'] is True
    assert len(result['cases']) == 5
    for case in result['cases']:
        assert case['injected_response_losses'] == case['adapter_resets'] == 10
        assert case['report']['metrics']['false_negatives'] == 2
        assert case['report']['metrics']['recall'] == 0


@pytest.mark.parametrize('damage', [
    'missing', 'order', 'fresh-revision', 'wrong-identity', 'wrong-state', 'unchanged-revision',
    'fault-not-injected', 'unexpected-response', 'clock', 'gold', 'firing-identity',
])
def test_recovery_replay_rejects_tampering(damage):
    plan, records = synthetic_trace()
    inspections = [r for r in records if r['command'] == 'task.inspect']
    if damage == 'missing':
        records.pop()
    elif damage == 'order':
        records[0], records[1] = records[1], records[0]
    elif damage == 'fresh-revision':
        retry = next(r for r in records if r['command'] == 'task.update' and r['outcome'] == 'ok')
        retry['resolved_payload']['expected_revision'] = 'f' * 64
    elif damage == 'wrong-identity':
        inspections[1]['response']['intention_id'] = 'another-intention'
    elif damage == 'wrong-state':
        inspections[2]['response']['status'] = 'scheduled'
    elif damage == 'unchanged-revision':
        inspections[1]['response']['revision'] = inspections[0]['response']['revision']
    elif damage == 'fault-not-injected':
        next(r for r in records if r['outcome'] != 'ok')['outcome'] = 'ok'
    elif damage == 'unexpected-response':
        records[1]['response'] = {'intention_id': 'leaked-response'}
    elif damage == 'gold':
        plan['cases'][0]['expected'][0]['windows'] = []
    elif damage == 'clock':
        next(r for r in records if r['command'] == 'intention.observe')['response']['evaluated_at'] = '2000-01-01T00:00:00Z'
    else:
        tick = next(r for r in records if r['command'] == 'intention.observe')['response']
        tick['action_ids'] = ['w0-revised']
        tick['firing_observations'] = [{
            'action_id': 'w0-revised', 'intention_id': 'unrelated', 'occurrence': 0,
            'trigger_type': 'exact_time', 'evaluated_at': tick['evaluated_at'],
            'provider_evaluated_at': None, 'due_at': tick['evaluated_at'],
        }]
    with pytest.raises(ValueError):
        reports(plan, records)


def test_revision_reference_cannot_be_forward_or_cross_task():
    _, records = synthetic_trace()
    operation = {'payload': {'task_id': 'other', 'expected_revision_from': 4}}
    with pytest.raises(ValueError, match='another task'):
        resolve_payload(operation, records[:5])
    operation['payload']['expected_revision_from'] = 5
    with pytest.raises(ValueError, match='earlier inspection'):
        resolve_payload(operation, records[:5])


def test_fault_injector_runs_underlying_command_before_dropping_response(monkeypatch):
    calls = []
    def run(self, command, *args, **kwargs):
        calls.append(command)
        return SimpleNamespace(ok=True)
    monkeypatch.setattr(MnemoCLI, 'run', run)
    driver = ResponseLossCLI(store='unused', fault={'command': 'intention-update'})
    assert driver.run('capture').ok
    with pytest.raises(InjectedResponseLoss):
        driver.run('intention-update')
    assert calls == ['capture', 'intention-update']
    assert driver.fault == {}
    assert driver.run('intention-update').ok


def test_failed_execution_retains_partial_log_without_error_secrets(tmp_path, monkeypatch):
    import json
    from eval.public.action_recovery_run import run_development

    def fail_after_capture(self, command, *args, **kwargs):
        if command == 'capture':
            return SimpleNamespace(json={'cid': 'origin'})
        raise RuntimeError('sensitive-test-error-must-not-be-retained')
    monkeypatch.setattr(ResponseLossCLI, 'run', fail_after_capture)
    output = tmp_path / 'failed'
    with pytest.raises(RuntimeError):
        run_development(output)
    assert json.loads((output / 'status.json').read_text()) == {
        'status': 'failed', 'exception_type': 'RuntimeError', 'completed_operations': 1, 'publishable': False,
    }
    assert len((output / 'operations.jsonl').read_text().splitlines()) == 1
    assert not (output / 'reports.json').exists()
    assert all('sensitive-test-error' not in p.read_text() for p in output.iterdir())
    with pytest.raises(FileExistsError):
        run_development(output)


def test_replay_requires_original_revision_reference_json_type():
    plan, records = synthetic_trace()
    update = next(r for r in records if 'expected_revision_from' in r['payload'])
    update['payload']['expected_revision_from'] = float(update['payload']['expected_revision_from'])
    with pytest.raises(ValueError):
        reports(plan, records)


def test_retained_clean_source_recovery_capture_replays():
    from pathlib import Path
    from eval.public.action_recovery_run import recompute

    root = Path(__file__).resolve().parents[1]
    result = recompute(root / 'eval/reports/m12-operation-recovery-development-2026-10-04')
    assert sum(c['injected_response_losses'] for c in result['cases']) == 50
    assert sum(c['adapter_resets'] for c in result['cases']) == 50
    assert sum(c['report']['metrics']['true_positives'] for c in result['cases']) == 10
    assert all(c['report']['metrics']['false_positives'] == 0 for c in result['cases'])
    assert all(c['report']['metrics']['false_negatives'] == 0 for c in result['cases'])
