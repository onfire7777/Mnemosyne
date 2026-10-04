import json

import pytest

from eval.public import action_reference_run


@pytest.mark.parametrize('fanout,count', [(False, 130), (True, 750)])
def test_reference_full_workload_replays_with_sink(tmp_path, fanout, count):
    output = tmp_path / 'reference'
    result = action_reference_run.run_development(output, fanout=fanout)
    assert action_reference_run.recompute(output) == result
    assert result['baseline_admitted'] is False and result['publishable'] is False
    assert sum(c['report']['metrics']['true_positives'] for c in result['workload']['cases']) == count
    annex = json.loads((output / 'sink.json').read_text())
    assert sum(len(c['snapshot']['receipts']) for c in annex['cases']) == count
    assert sum(len(c['snapshot']['attempts']) for c in annex['cases']) == count * 2
    with pytest.raises(FileExistsError):
        action_reference_run.run_development(output, fanout=fanout)


@pytest.mark.parametrize('damage', ['identity', 'sink', 'semantic', 'duration', 'status'])
def test_reference_tampering_is_rejected(tmp_path, damage):
    output = tmp_path / 'reference'
    action_reference_run.run_development(output)
    if damage in ('semantic', 'duration'):
        path = output / 'operations.jsonl'
        records = [json.loads(line) for line in path.read_text().splitlines()]
        record = next(r for r in records if r['response'].get('firing_observations'))
        if damage == 'semantic':
            record['response']['firing_observations'][0]['intention_id'] = 'forged'
        else:
            record['response']['evaluation_wall_ms'] = -1
        path.write_text(''.join(json.dumps(r) + '\n' for r in records))
    else:
        name = {'identity': 'source.json', 'sink': 'sink.json', 'status': 'status.json'}[damage]
        path = output / name
        value = json.loads(path.read_text())
        if damage == 'identity':
            value['reference_id'] = 'candidate'
        elif damage == 'sink':
            value['cases'][0]['snapshot']['receipts'].pop()
        else:
            value['completed_operations'] -= 1
        path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        action_reference_run.recompute(output)


def test_reference_failure_retains_completed_operations_without_exception_text(tmp_path, monkeypatch):
    original = action_reference_run.ExplicitActionReference.run
    calls = 0

    def fail(self, command, payload):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError('sensitive-content-must-not-be-written')
        return original(self, command, payload)

    monkeypatch.setattr(action_reference_run.ExplicitActionReference, 'run', fail)
    output = tmp_path / 'failed'
    with pytest.raises(RuntimeError):
        action_reference_run.run_development(output)
    status = json.loads((output / 'status.json').read_text())
    assert status == {'status': 'failed', 'exception_type': 'RuntimeError',
                      'completed_operations': 2, 'publishable': False}
    assert len((output / 'operations.jsonl').read_text().splitlines()) == 2
    assert 'sensitive-content' not in (output / 'status.json').read_text()
    assert not (output / 'reports.json').exists()
