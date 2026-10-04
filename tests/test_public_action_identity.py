from copy import deepcopy

import pytest

from eval.harness.cli_driver import MnemoCLI
from eval.public.action_cli import ActionCLI, ActionCLIError


@pytest.mark.parametrize('replacement', ['same', 'changed', 'add_key'])
def test_unkeyed_task_identity_cannot_be_rebound(tmp_path, replacement):
    adapter = ActionCLI(MnemoCLI(store='unused', timeout_s=30))
    scope = {'store': str(tmp_path / 'store.json'), 'tenant_id': 'tenant', 'session_id': 'session'}
    task = {'task_id': 'stable-name', 'action_id': 'original',
            'trigger': {'type': 'exact_time', 'payload': {'at': '2030-01-01T00:00:00Z'}}}
    adapter.run('task.create', scope, task)
    before = adapter.run('task.inspect', scope, {'task_id': 'stable-name', 'include_schedule': True})
    raw_before = (tmp_path / 'store.json').read_bytes()
    proposed = deepcopy(task)
    if replacement == 'changed':
        proposed['action_id'] = 'replacement'
    if replacement == 'add_key':
        proposed['idempotency_key'] = 'new-key'
    with pytest.raises(ActionCLIError, match='unkeyed task'):
        adapter.run('task.create', scope, proposed)
    assert (tmp_path / 'store.json').read_bytes() == raw_before
    assert adapter.run('task.inspect', scope, {'task_id': 'stable-name', 'include_schedule': True}) == before
    adapter.run('clock.inject', scope, {'now': '2030-01-01T00:00:00Z'})
    assert adapter.run('intention.observe', scope, {})['action_ids'] == ['original']


def test_keyed_creation_retry_preserves_identity(tmp_path):
    adapter = ActionCLI(MnemoCLI(store='unused', timeout_s=30))
    scope = {'store': str(tmp_path / 'store.json'), 'tenant_id': 'tenant', 'session_id': 'session'}
    task = {'task_id': 'stable-name', 'action_id': 'original', 'idempotency_key': 'retry-key',
            'trigger': {'type': 'exact_time', 'payload': {'at': '2030-01-01T00:00:00Z'}}}
    adapter.run('task.create', scope, task)
    before = adapter.run('task.inspect', scope, {'task_id': 'stable-name'})
    adapter.run('task.create', scope, task)
    assert adapter.run('task.inspect', scope, {'task_id': 'stable-name'}) == before
