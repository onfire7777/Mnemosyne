from copy import deepcopy
import json

from jsonschema import Draft202012Validator
import pytest

from eval.public.action_formation import validate_response
from eval.public.action_formation_schema import response_schema


@pytest.fixture
def validator():
    schema = response_schema([{'action_id': 'allowed', 'description': 'public action'}])
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def envelope(payload, command='task.create'):
    return {'operations': [{'command': command, 'payload': payload}], 'clarification': None}


def creation():
    return {'task_id': 'one', 'action_id': 'allowed',
            'trigger': {'type': 'exact_time', 'payload': {'at': '2030-01-01T00:00:00Z'}}}


@pytest.mark.parametrize('kind,payload', [
    ('exact_time', {'at': '2030-01-01T00:00:00Z'}),
    ('time_window', {'start': '2030-01-01T00:00:00Z', 'end': '2030-01-01T01:00:00Z'}),
    ('event', {'event_type': 'delivery', 'match': {'status': 'ready'}, 'due_at': '2030-01-01T00:00:00Z'}),
    ('condition', {'condition_id': 'ready', 'operator': 'eq', 'value': True, 'due_at': '2030-01-01T00:00:00Z'}),
    ('dependency_completion', {'due_at': '2030-01-01T00:00:00Z'}),
])
def test_valid_public_trigger_shapes_remain_available(validator, kind, payload):
    task = creation()
    task['trigger'] = {'type': kind, 'payload': payload}
    value = envelope(task)
    validator.validate(value)
    validate_response(json.dumps(value).encode(), allowed_actions={'allowed'}, existing_tasks=set())


def test_grammar_blocks_initial_real_failure_and_unoffered_action(validator):
    mixed = envelope(creation())
    mixed['clarification'] = 'When should I remind you?'
    assert not validator.is_valid(mixed)
    malformed = envelope({'action_id': 'allowed', 'trigger': 'exact_time', 'due_at': '2030-01-01'})
    assert not validator.is_valid(malformed)
    wrong = creation()
    wrong['action_id'] = 'unoffered'
    assert not validator.is_valid(envelope(wrong))


def test_question_noop_recurrence_and_update_pairs(validator):
    validator.validate({'operations': [], 'clarification': 'When?'})
    validator.validate({'operations': [], 'clarification': None})
    recurring = creation()
    recurring['recurrence_policy'] = {'type': 'interval', 'interval_seconds': 604800, 'max_occurrences': 3}
    validator.validate(envelope(recurring))
    for kind in ('cancel', 'override', 'reschedule'):
        task = {'task_id': 'one', 'type': kind}
        if kind != 'cancel':
            task['action_id'] = 'allowed'
        if kind == 'reschedule':
            task['due_at'] = '2031-01-01T00:00:00Z'
        validator.validate(envelope(task, 'task.update'))
        task['idempotency_key'] = 'original-key'
        assert not validator.is_valid(envelope(task, 'task.update'))
        task['expected_revision'] = 'observed-revision'
        validator.validate(envelope(task, 'task.update'))


def test_schema_has_no_preferred_time_or_gold_and_is_detached(validator):
    value = envelope(creation())
    # A wrong timestamp is still grammar-valid; the evaluator must score it.
    value['operations'][0]['payload']['trigger']['payload']['at'] = '2099-01-01T00:00:00Z'
    validator.validate(value)
    actions = [{'action_id': 'allowed', 'description': 'description is not a label'}]
    before = deepcopy(actions)
    schema = response_schema(actions)
    assert actions == before
    assert 'description is not a label' not in json.dumps(schema)
    assert '2099' not in json.dumps(schema)
    schema.clear()
    assert response_schema(actions)
