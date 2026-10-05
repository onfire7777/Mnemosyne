import hashlib
import json

import pytest

from eval.harness.cli_driver import MnemoCLI
from eval.public.action_cli import ActionCLI, ActionCLIError
from eval.public.action_formation import run_case
from eval.public.action_implicit_plan import make_corpus, public_turn
from eval.public.bundle import _canonical


def test_public_capture_binds_creation_and_preserves_original_evidence_on_keyed_retry(tmp_path, monkeypatch):
    original = MnemoCLI.run
    scheduled = []

    def observe(self, command, *args, **kwargs):
        result = original(self, command, *args, **kwargs)
        if command == 'intention-schedule':
            scheduled.append(result.json)
        return result

    monkeypatch.setattr(MnemoCLI, 'run', observe)
    adapter = ActionCLI(MnemoCLI(store='unused', timeout_s=30))
    scope = {'store': str(tmp_path / 'memory.json'), 'tenant_id': 'tenant', 'session_id': 'session'}
    first = adapter.run('evidence.capture', scope, {'content': 'Original user instruction.'})
    assert first['content_sha256'] == hashlib.sha256(b'Original user instruction.').hexdigest()
    task = {'task_id': 'one', 'action_id': 'a', 'idempotency_key': 'create-one',
            'trigger': {'type': 'exact_time', 'payload': {'at': '2035-01-01T00:00:00Z'}}}
    adapter.run('task.create', scope, task)
    second = adapter.run('evidence.capture', scope, {'content': 'A later, distinct user instruction.'})
    assert first['evidence_cid'] != second['evidence_cid']
    adapter.run('task.create', scope, task)
    adapter.run('task.create', scope, {**task, 'task_id': 'two', 'idempotency_key': 'create-two'})
    assert [row['evidence_ids'] for row in scheduled] == [
        [first['evidence_cid']], [first['evidence_cid']], [second['evidence_cid']],
    ]
    assert scheduled[0]['intention_id'] == scheduled[1]['intention_id']
    with pytest.raises(ActionCLIError, match='reused across tenants'):
        adapter.run('evidence.capture', {**scope, 'tenant_id': 'other'}, {'content': 'wrong scope'})


def test_formation_captures_only_available_conversation_and_uses_its_cid(tmp_path, monkeypatch):
    fixture = next(c for c in make_corpus()['cases'] if c['gold']['scenario'] == 'cancellation')
    original = MnemoCLI.run
    captured, scheduled = {}, []

    def observe(self, command, *args, **kwargs):
        result = original(self, command, *args, **kwargs)
        if command == 'capture':
            captured[result.json['cid']] = args[args.index('--content') + 1]
        if command == 'intention-schedule':
            scheduled.append(result.json)
        return result

    class ScriptedProvider:
        identity = 'test-double-not-a-model'

        def complete(self, request):
            operations = []
            if not request['prior_responses']:
                operations = [{'command': 'task.create', 'payload': {
                    'task_id': 'one', 'action_id': request['conversation']['actions'][0]['action_id'],
                    'trigger': {'type': 'exact_time', 'payload': {'at': '2035-01-01T00:00:00Z'}}}}]
            return 0, json.dumps({'operations': operations, 'clarification': None}).encode()

    monkeypatch.setattr(MnemoCLI, 'run', observe)
    records = []
    run_case(fixture, provider=ScriptedProvider(), actions=ActionCLI(MnemoCLI(store='unused', timeout_s=30)),
             scope={'store': str(tmp_path / 'memory.json'), 'tenant_id': 'tenant', 'session_id': 'session'},
             emit=records.append)
    evidence = [r['response'] for r in records if r['stage'] == 'action_response' and r['command'] == 'evidence.capture']
    assert len(evidence) == 2
    for index, response in enumerate(evidence):
        assert captured[response['evidence_cid']] == _canonical(public_turn(fixture, index)).decode()
    assert scheduled[0]['evidence_ids'] == [evidence[0]['evidence_cid']]
    assert 'Cancel that reminder.' not in captured[evidence[0]['evidence_cid']]
    assert not any('gold' in json.loads(content) for content in captured.values() if content.startswith('{'))


def test_invalid_evidence_cannot_replace_current_binding(tmp_path, monkeypatch):
    adapter = ActionCLI(MnemoCLI(store='unused', timeout_s=30))
    scope = {'store': str(tmp_path / 'memory.json'), 'tenant_id': 'tenant', 'session_id': 'session'}
    initial = adapter.run('evidence.capture', scope, {'content': 'Keep this evidence.'})
    original = MnemoCLI.run
    rows = []

    def fail_capture(self, command, *args, **kwargs):
        if command == 'capture':
            raise RuntimeError('capture unavailable')
        result = original(self, command, *args, **kwargs)
        if command == 'intention-schedule':
            rows.append(result.json)
        return result

    monkeypatch.setattr(MnemoCLI, 'run', fail_capture)
    for payload in ({'content': ''}, {'content': 'x', 'tenant_id': 'other'}, {'content': 'x' * (256 * 1024 + 1)}):
        with pytest.raises(ActionCLIError):
            adapter.run('evidence.capture', scope, payload)
    with pytest.raises(RuntimeError, match='unavailable'):
        adapter.run('evidence.capture', scope, {'content': 'Replacement failed.'})
    adapter.run('task.create', scope, {'task_id': 'one', 'action_id': 'a',
                'trigger': {'type': 'exact_time', 'payload': {'at': '2035-01-01T00:00:00Z'}}})
    assert rows[0]['evidence_ids'] == [initial['evidence_cid']]
