from copy import deepcopy
import json

import pytest

from eval.public import action_recovery_run, action_trigger_run


@pytest.mark.parametrize('module', [action_trigger_run, action_recovery_run])
@pytest.mark.parametrize('fail_delivery', [False, True])
def test_public_workloads_deliver_to_sink_and_keep_failures_incomplete(tmp_path, monkeypatch, module, fail_delivery):
    plan = module.make_plan()
    plan['cases'] = plan['cases'][:1]
    case = plan['cases'][0]
    if module is action_recovery_run:
        # First complete week includes two actual response losses and resets.
        case['operations'] = case['operations'][:15]
        case['expected'] = case['expected'][:1]
    else:
        creation = next(row for row in case['operations'] if row['payload'].get('task_id') == 'w0-exact')
        due = creation['payload']['trigger']['payload']['at']
        case['operations'] = [creation, {'command': 'clock.inject', 'payload': {'now': due}},
                              {'command': 'intention.observe', 'payload': {}},
                              {'command': 'intention.observe', 'payload': {}}]
        case['expected'] = [row for row in case['expected'] if row['action_id'] == 'w0-exact']
    monkeypatch.setattr(module, 'make_plan', lambda: deepcopy(plan))
    output = tmp_path / 'run'
    if fail_delivery:
        def fail(*args):
            raise OSError('sink unavailable')
        monkeypatch.setattr(module, '_deliver', fail)
        with pytest.raises(OSError):
            module.run_development(output, with_sink=True)
        assert json.loads((output / 'status.json').read_text())['status'] == 'failed'
        assert not (output / 'reports.json').exists()
        assert 'intention.observe' in (output / 'operations.jsonl').read_text()
        return
    result = module.run_development(output, with_sink=True)
    assert module.recompute(output) == result
    annex = json.loads((output / 'sink.json').read_text())
    snapshot = annex['cases'][0]['snapshot']
    assert len(snapshot['receipts']) == 1
    assert [row['outcome'] for row in snapshot['attempts']] == ['accepted', 'duplicate']
    assert [row['origin'] for row in snapshot['attempts']] == ['candidate-observation', 'harness-retry']
    assert snapshot['external_actions_executed'] is False
    for mutation in ('missing', 'scope', 'duplicate', 'unadvertised'):
        changed = deepcopy(annex)
        if mutation == 'missing':
            changed['cases'][0]['snapshot']['receipts'] = []
        elif mutation == 'scope':
            changed['cases'][0]['snapshot']['receipts'][0]['session_id'] = 'another-session'
        elif mutation == 'duplicate':
            changed['cases'][0]['snapshot']['attempts'][1]['outcome'] = 'accepted'
        else:
            source = json.loads((output / 'source.json').read_text())
            source['sink_enabled'] = False
            (output / 'source.json').write_text(json.dumps(source))
        (output / 'sink.json').write_text(json.dumps(changed))
        with pytest.raises(ValueError):
            module.recompute(output)
