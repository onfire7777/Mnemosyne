"""Draft explicit-action reference interpreter, independent of product and gold.

One instance is one isolated case. This is not an admitted M12 baseline. It
returns semantic firings, not fabricated timing measurements or sink receipts.
"""

from copy import deepcopy
from datetime import datetime, timedelta
import json
import hashlib


def _time(value):
    if not isinstance(value, str):
        raise ValueError('timestamp must be text')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timestamp must have an offset')
    return result


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('nonempty identifier required')
    return value


def _closed(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise ValueError('unsupported request fields')


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _condition_matches(observed, operator, expected):
    if operator == 'eq':
        return _json(observed) == _json(expected)
    if operator == 'ne':
        return _json(observed) != _json(expected)
    if operator == 'in':
        if not isinstance(expected, list):
            raise ValueError('membership requires a list')
        return any(_json(observed) == _json(item) for item in expected)
    if operator not in ('lt', 'lte', 'gt', 'gte'):
        raise ValueError('unsupported condition operator')
    if type(observed) is not type(expected) or type(observed) not in (int, float, str):
        raise ValueError('ordering requires same-type numbers or strings')
    _json(observed)
    _json(expected)
    return {'lt': observed < expected, 'lte': observed <= expected,
            'gt': observed > expected, 'gte': observed >= expected}[operator]


class ExplicitActionReference:
    """Bounded, in-memory draft semantics; no inference from expected outcomes."""

    def __init__(self):
        self.tasks = {}
        self.keys = {}
        self.mutations = {}
        self.now = None
        self.events = []
        self.conditions = {}

    def run(self, command, payload):
        payload = deepcopy(payload)
        if command == 'task.create':
            return self._create(payload)
        if command == 'task.update':
            return self._update(payload)
        if command == 'task.inspect':
            _closed(payload, ('task_id',))
            task_id = _text(payload['task_id'])
            if task_id not in self.tasks:
                raise ValueError('unknown task')
            task = self.tasks[task_id]
            return {'task_id': task_id, 'intention_id': 'reference:' + task_id,
                    'revision': self._revision(task), 'action_id': task['action_id'],
                    'status': 'cancelled' if task['cancelled'] else
                    'fired' if task['occurrence'] >= task['maximum'] else 'scheduled'}
        if command == 'clock.inject':
            _closed(payload, ('now',))
            now = _time(payload['now'])
            if self.now is not None and now < self.now:
                raise ValueError('clock cannot move backward')
            self.now = now
            return {}
        if command == 'event.inject':
            return self._inject(payload)
        if command == 'intention.observe':
            _closed(payload, ())
            return self._observe()
        raise ValueError('unsupported reference command')

    @staticmethod
    def _revision(task):
        return hashlib.sha256(_json({**task, 'due': task['due'].isoformat()}).encode()).hexdigest()

    def _update(self, payload):
        _closed(payload, ('type', 'task_id'), ('action_id', 'due_at', 'expected_revision', 'idempotency_key'))
        task_id = _text(payload['task_id'])
        if task_id not in self.tasks:
            raise ValueError('unknown task')
        kind = payload['type']
        if kind not in ('cancel', 'override', 'reschedule'):
            raise ValueError('unsupported mutation')
        if (kind == 'cancel' and ('action_id' in payload or 'due_at' in payload)
                or kind == 'override' and 'due_at' in payload):
            raise ValueError('fields do not match mutation')
        encoded = _json(payload)
        key = payload.get('idempotency_key')
        if 'idempotency_key' in payload:
            _text(key)
        if ('expected_revision' in payload) != ('idempotency_key' in payload):
            raise ValueError('revision and idempotency key must be supplied together')
        if key is not None:
            _text(key)
            revision = _text(payload['expected_revision'])
            if len(revision) != 64 or any(c not in '0123456789abcdef' for c in revision):
                raise ValueError('invalid revision')
            if key in self.mutations:
                if self.mutations[key] != encoded:
                    raise ValueError('mutation key conflict')
                return {}
        task = self.tasks[task_id]
        if key is not None and payload['expected_revision'] != self._revision(task):
            raise ValueError('stale revision')
        changed = deepcopy(task)
        if kind == 'cancel':
            if task['occurrence'] >= task['maximum']:
                raise ValueError('fired task cannot be cancelled')
            changed['cancelled'] = True
        else:
            if task['cancelled'] or task['occurrence'] >= task['maximum']:
                raise ValueError('terminal task cannot be updated')
            changed['action_id'] = _text(payload.get('action_id'))
            if kind == 'reschedule':
                if task['trigger']['type'] != 'exact_time':
                    raise ValueError('draft rescheduling supports exact-time only')
                changed['due'] = _time(payload.get('due_at'))
                if changed['interval'] is not None:
                    changed['due'] + timedelta(seconds=changed['interval'] * (changed['maximum'] - changed['occurrence'] - 1))
        self.tasks[task_id] = changed
        if key is not None:
            self.mutations[key] = encoded
        return {}

    def _create(self, task):
        _closed(task, ('task_id', 'action_id', 'trigger'), ('idempotency_key', 'dependency_ids', 'recurrence_policy'))
        task_id, action_id = _text(task['task_id']), _text(task['action_id'])
        encoded = _json(task)
        key = task.get('idempotency_key')
        if 'idempotency_key' in task:
            _text(key)
        if key is not None:
            _text(key)
            if key in self.keys:
                if self.keys[key] != encoded:
                    raise ValueError('idempotency key conflict')
                return {}
        if task_id in self.tasks or len(self.tasks) >= 10000:
            raise ValueError('duplicate task or capacity exceeded')
        trigger = task['trigger']
        _closed(trigger, ('type', 'payload'))
        kind, spec = trigger['type'], trigger['payload']
        fields = {'exact_time': ('at',), 'time_window': ('start', 'end'),
                  'event': ('event_type', 'match', 'due_at'),
                  'condition': ('condition_id', 'operator', 'value', 'due_at'),
                  'dependency_completion': ('due_at',)}
        if kind not in fields:
            raise ValueError('unsupported trigger')
        _closed(spec, fields[kind])
        due = _time(spec['at'] if kind == 'exact_time' else spec['start'] if kind == 'time_window' else spec['due_at'])
        if kind == 'time_window' and _time(spec['end']) <= due:
            raise ValueError('empty window')
        if kind == 'event':
            _text(spec['event_type'])
            if not isinstance(spec['match'], dict):
                raise ValueError('event match must be an object')
        if kind == 'condition':
            _text(spec['condition_id'])
            if spec['operator'] not in ('eq', 'ne', 'in', 'lt', 'lte', 'gt', 'gte'):
                raise ValueError('unsupported condition operator')
            if spec['operator'] == 'in' and not isinstance(spec['value'], list):
                raise ValueError('membership requires a list')
            if spec['operator'] in ('lt', 'lte', 'gt', 'gte') and type(spec['value']) not in (int, float, str):
                raise ValueError('ordering requires numbers or strings')
        deps = task.get('dependency_ids', [])
        if not isinstance(deps, list) or any(not isinstance(dep, str) or dep not in self.tasks for dep in deps):
            raise ValueError('dependencies must already exist')
        if len(set(deps)) != len(deps) or (kind == 'dependency_completion' and not deps) or (deps and kind != 'dependency_completion'):
            raise ValueError('invalid dependency list')
        interval, maximum = None, 1
        if 'recurrence_policy' in task:
            recurrence = task['recurrence_policy']
            _closed(recurrence, ('type', 'interval_seconds', 'max_occurrences'))
            interval, maximum = recurrence['interval_seconds'], recurrence['max_occurrences']
            if kind != 'exact_time' or recurrence['type'] != 'interval' or type(interval) is not int or not 0 < interval <= 31536000 or type(maximum) is not int or not 0 < maximum <= 10000:
                raise ValueError('unsupported recurrence')
        if interval is not None:
            due + timedelta(seconds=interval * (maximum - 1))
        self.tasks[task_id] = {'action_id': action_id, 'trigger': trigger, 'due': due,
                               'dependencies': deps, 'interval': interval, 'maximum': maximum,
                               'occurrence': 0, 'cancelled': False}
        if key is not None:
            self.keys[key] = encoded
        return {}

    def _inject(self, signal):
        if not isinstance(signal, dict):
            raise ValueError('signal must be an object')
        _json(signal)
        kind = signal.get('kind')
        if kind == 'event':
            _closed(signal, ('kind', 'event_id', 'event_type', 'occurred_at', 'payload'))
            _text(signal['event_id'])
            _text(signal['event_type'])
            _time(signal['occurred_at'])
            if not isinstance(signal['payload'], dict) or len(self.events) >= 10000:
                raise ValueError('invalid event payload or too many events')
            self.events.append(signal)
        elif kind == 'condition':
            _closed(signal, ('kind', 'condition_id', 'value', 'observed_at'))
            _text(signal['condition_id'])
            _time(signal['observed_at'])
            if signal['condition_id'] not in self.conditions and len(self.conditions) >= 10000:
                raise ValueError('too many conditions')
            self.conditions[signal['condition_id']] = signal
        else:
            raise ValueError('unsupported signal')
        return {}

    def _observe(self):
        if self.now is None:
            raise ValueError('clock required')
        # Dependencies see completion before this tick, independent of task order.
        completed = {key for key, task in self.tasks.items() if task['occurrence'] >= task['maximum']}
        firings, transitions = [], []
        for task_id, task in self.tasks.items():
            if task['cancelled'] or task['occurrence'] >= task['maximum'] or self.now < task['due']:
                continue
            kind, spec = task['trigger']['type'], task['trigger']['payload']
            eligible = kind == 'exact_time'
            if kind == 'time_window':
                eligible = self.now < _time(spec['end'])
            elif kind == 'event':
                eligible = any(event['event_type'] == spec['event_type']
                    and task['due'] <= _time(event['occurred_at']) <= self.now
                    and all(k in event['payload'] and _json(event['payload'][k]) == _json(v) for k, v in spec['match'].items())
                    for event in self.events)
            elif kind == 'condition':
                signal = self.conditions.get(spec['condition_id'])
                eligible = signal is not None and task['due'] <= _time(signal['observed_at']) <= self.now and _condition_matches(signal['value'], spec['operator'], spec['value'])
            elif kind == 'dependency_completion':
                eligible = set(task['dependencies']) <= completed
            if not eligible:
                continue
            firings.append({'action_id': task['action_id'], 'intention_id': 'reference:' + task_id,
                            'occurrence': task['occurrence'], 'trigger_type': kind,
                            'due_at': task['due'].isoformat(), 'evaluated_at': self.now.isoformat(),
                            'provider_evaluated_at': None})
            transitions.append(task)
        for task in transitions:
            task['occurrence'] += 1
            if task['interval'] is not None and task['occurrence'] < task['maximum']:
                task['due'] += timedelta(seconds=task['interval'])
        self.events.clear()
        self.conditions.clear()
        return {'firing_observations': firings, 'evaluated_at': self.now.isoformat()}
