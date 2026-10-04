import base64
from copy import deepcopy
import json
import sys

import pytest

from eval.harness.cli_driver import MnemoCLI
from eval.public.action_cli import ActionCLI
from eval.public.action_formation import CommandFormationProvider, run_case, validate_response
from eval.public.action_implicit_plan import make_corpus, public_turn


def case():
    return next(c for c in make_corpus()['cases'] if c['gold']['scenario'] == 'cancellation')


def creation(public):
    # A scripted test response, never a claimed model or benchmark result.
    return {'command': 'task.create', 'payload': {
        'task_id': 'model-selected-task', 'action_id': public['actions'][0]['action_id'],
        'trigger': {'type': 'exact_time', 'payload': {'at': '2035-01-01T00:00:00Z'}},
        'idempotency_key': 'model-create'}}


class Provider:
    identity = 'scripted-test-double; not-a-model'

    def __init__(self, respond):
        self.respond = respond
        self.requests = []

    def complete(self, request):
        self.requests.append(deepcopy(request))
        return self.respond(request)


def encoded(operations, clarification=None):
    return json.dumps({'operations': operations, 'clarification': clarification}).encode()


def test_scripted_responses_drive_real_public_creation_and_revision_keyed_cancellation(tmp_path):
    fixture = case()
    fixture['gold'] = {'sentinel': 'MUST_NOT_REACH_PROVIDER'}

    def respond(request):
        if not request['current_tasks']:
            return 0, encoded([creation(request['conversation'])])
        current = request['current_tasks'][0]
        return 0, encoded([{'command': 'task.update', 'payload': {
            'type': 'cancel', 'task_id': current['task_id'],
            'expected_revision': current['revision'], 'idempotency_key': 'model-cancel'}}])

    provider = Provider(respond)
    records = []
    summary = run_case(fixture, provider=provider, actions=ActionCLI(MnemoCLI(store='unused', timeout_s=30)),
                       scope={'store': str(tmp_path / 'memory.json'), 'tenant_id': 'formation', 'session_id': 'one'},
                       emit=records.append)
    assert summary['status'] == 'completed'
    assert summary['scored'] is summary['publishable'] is False
    assert len(provider.requests) == 2
    assert provider.requests[0]['conversation'] == public_turn(fixture, 0)
    assert 'Cancel that reminder.' not in json.dumps(provider.requests[0])
    assert 'MUST_NOT_REACH_PROVIDER' not in json.dumps(provider.requests)
    assert str(tmp_path) not in json.dumps(provider.requests)
    ends = [r for r in records if r['stage'] == 'turn_completed']
    assert [r['tasks'][0]['status'] for r in ends] == ['scheduled', 'cancelled']
    assert len([r for r in records if r['stage'] == 'formation_response']) == 2
    assert provider.requests[1]['prior_responses'][0]['operations'][0]['command'] == 'task.create'


@pytest.mark.parametrize('alter', [
    lambda op: op.update(command='shell.execute'),
    lambda op: op.update(command='evidence.capture'),
    lambda op: op['payload'].update(store='/another/tenant.json'),
    lambda op: op['payload'].update(action_id='not-offered'),
])
def test_unsafe_batch_envelopes_are_rejected_before_any_creation(alter):
    public = case()['public']
    valid = creation(public)
    invalid = deepcopy(valid)
    alter(invalid)
    with pytest.raises(ValueError):
        validate_response(encoded([valid, invalid]), allowed_actions={a['action_id'] for a in public['actions']},
                          existing_tasks=set())


def test_duplicate_json_keys_and_clarification_with_writes_are_rejected():
    with pytest.raises(ValueError):
        validate_response(b'{"operations":[],"operations":[],"clarification":null}',
                          allowed_actions=set(), existing_tasks=set())
    public = case()['public']
    with pytest.raises(ValueError, match='clarification'):
        validate_response(encoded([creation(public)], 'When?'),
                          allowed_actions={a['action_id'] for a in public['actions']}, existing_tasks=set())


def test_failed_provider_output_is_retained_without_scheduling():
    class ClockOnly:
        def run(self, command, *_args):
            assert command in ('clock.inject', 'evidence.capture')
            return {}

    raw = b'provider returned an error, not a valid plan'
    records = []
    with pytest.raises(ValueError, match='unsuccessfully'):
        run_case(case(), provider=Provider(lambda _: (7, raw)), actions=ClockOnly(), scope={}, emit=records.append)
    saved = next(r for r in records if r['stage'] == 'formation_response')
    assert base64.b64decode(saved['stdout_base64']) == raw
    assert saved['returncode'] == 7
    assert records[-1]['stage'] == 'formation_error'
    assert not any(r['stage'] == 'turn_completed' for r in records)


def test_partial_public_failure_retains_prior_success_and_failed_attempt():
    class Partial:
        def __init__(self):
            self.count = 0

        def run(self, command, *_args):
            if command == 'task.create':
                self.count += 1
                if self.count == 2:
                    raise ValueError('public CLI rejected payload semantics')
            return {}

    fixture = case()
    one = creation(fixture['public'])
    two = deepcopy(one)
    two['payload']['task_id'] = 'another'
    two['payload']['trigger']['payload']['at'] = 'bad timestamp'
    records, actions = [], Partial()
    with pytest.raises(ValueError, match='payload semantics'):
        run_case(fixture, provider=Provider(lambda _: (0, encoded([one, two]))),
                 actions=actions, scope={}, emit=records.append)
    assert actions.count == 2
    assert len([r for r in records if r['stage'] == 'action_response' and r['command'] == 'task.create']) == 1
    assert records[-1]['stage'] == 'action_error'
    assert not any(r['stage'] == 'turn_completed' for r in records)


def test_failure_to_record_model_response_prevents_writes():
    class ClockOnly:
        def run(self, command, *_args):
            assert command in ('clock.inject', 'evidence.capture')
            return {}

    def emit(record):
        if record['stage'] == 'formation_response':
            raise OSError('disk full')

    fixture = case()
    with pytest.raises(OSError, match='disk full'):
        run_case(fixture, provider=Provider(lambda _: (0, encoded([creation(fixture['public'])]))),
                 actions=ClockOnly(), scope={}, emit=emit)


def test_command_transport_uses_actual_stdout_and_preserves_nonzero_status():
    provider = CommandFormationProvider((sys.executable, '-c',
        'import sys; data=sys.stdin.buffer.read(); sys.stdout.buffer.write(data); sys.exit(3)'), 'echo-test-command')
    code, raw = provider.complete({'input': 'literal ; not a shell command'})
    assert code == 3
    assert json.loads(raw) == {'input': 'literal ; not a shell command'}
    with pytest.raises(ValueError):
        CommandFormationProvider((), 'empty')
    with pytest.raises(ValueError):
        CommandFormationProvider((sys.executable,), 'invalid-timeout', timeout_seconds=True)
    with pytest.raises(ValueError):
        CommandFormationProvider(sys.executable, 'string-is-not-an-argv')
    with pytest.raises(ValueError):
        CommandFormationProvider((sys.executable,), 'invalid-timeout', timeout_seconds='30')
