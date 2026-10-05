"""Public operation grammar for optional constrained formation decoding.

No corpus labels or preferred decisions enter this schema. Runtime and semantic
validation remain authoritative; grammar validity is not benchmark correctness.
"""

from copy import deepcopy


def _object(properties, required=None):
    return {'type': 'object', 'properties': properties, 'additionalProperties': False,
            'required': list(properties) if required is None else required}


def response_schema(actions):
    if (not isinstance(actions, list) or not actions or len(actions) > 128
            or any(not isinstance(a, dict) or not isinstance(a.get('action_id'), str)
                   or not a['action_id'].strip() or len(a['action_id']) > 256 for a in actions)):
        raise ValueError('schema requires bounded offered action identifiers')
    identifiers = [a['action_id'] for a in actions]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError('duplicate offered action identifier')
    name = {'type': 'string', 'minLength': 1, 'maxLength': 256}
    timestamp = {'type': 'string', 'minLength': 1}
    action = {'type': 'string', 'enum': identifiers}
    variants = []
    for kind, fields in (
        ('exact_time', {'at': timestamp}),
        ('time_window', {'start': timestamp, 'end': timestamp}),
        ('event', {'event_type': name, 'match': {'type': 'object'}, 'due_at': timestamp}),
        ('condition', {'condition_id': name, 'operator': {'enum': ['eq', 'ne', 'in', 'lt', 'lte', 'gt', 'gte']},
                       'value': {}, 'due_at': timestamp}),
        ('dependency_completion', {'due_at': timestamp}),
    ):
        variants.append(_object({'type': {'const': kind}, 'payload': _object(fields)}))
    recurrence = {'oneOf': [
        _object({'type': {'const': 'none'}}),
        _object({'type': {'const': 'interval'}, 'interval_seconds': {'type': 'integer', 'minimum': 1},
                 'max_occurrences': {'type': 'integer', 'minimum': 1}}, ['type', 'interval_seconds']),
    ]}
    create = _object({'task_id': name, 'action_id': action, 'trigger': {'oneOf': variants},
                      'dependency_ids': {'type': 'array', 'items': name, 'maxItems': 128},
                      'recurrence_policy': recurrence, 'idempotency_key': name},
                     ['task_id', 'action_id', 'trigger'])
    operations = [_object({'command': {'const': 'task.create'}, 'payload': create})]
    for kind in ('cancel', 'override', 'reschedule'):
        fields = {'task_id': name, 'type': {'const': kind}}
        if kind != 'cancel':
            fields['action_id'] = action
        if kind == 'reschedule':
            fields['due_at'] = timestamp
        required = list(fields)
        if kind != 'cancel':
            fields['recurrence_policy'] = recurrence
        # Distinct branches enforce paired revision/key fields without relying
        # on vendor support for dependentRequired or if/then JSON Schema rules.
        plain = _object(fields, required)
        keyed = _object({**fields, 'idempotency_key': name, 'expected_revision': name},
                        [*required, 'idempotency_key', 'expected_revision'])
        operations.append(_object({'command': {'const': 'task.update'},
                                   'payload': {'oneOf': [plain, keyed]}}))
    schema = {'oneOf': [
        _object({'operations': {'type': 'array', 'items': {'oneOf': operations}, 'maxItems': 16},
                 'clarification': {'type': 'null'}}),
        _object({'operations': {'type': 'array', 'items': {}, 'maxItems': 0},
                 'clarification': {'type': 'string', 'minLength': 1, 'maxLength': 4096}}),
    ]}
    return deepcopy(schema)
