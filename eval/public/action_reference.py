"""Draft explicit-action reference interpreter, independent of product and gold.

One instance is one isolated case. This is not an admitted M12 baseline. It
returns semantic firings, not fabricated timing measurements or sink receipts.
"""

from copy import deepcopy
from datetime import datetime, timedelta
import json


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


class ExplicitActionReference:
    """Bounded, in-memory draft semantics; no inference from expected outcomes."""

    def __init__(self):
        self.tasks = {}
        self.keys = {}
        self.now = None
        self.events = []
        self.conditions = {}

    def run(self, command, payload):
        payload = deepcopy(payload)
        if command == 'task.create':
            return self._create(payload)
        if command == 'task.update':
            _closed(payload, ('type', 'task_id'))
            if payload['type'] != 'cancel' or payload['task_id'] not in self.tasks:
                raise ValueError('only known-task cancellation is supported')
            self.tasks[payload['task_id']]['cancelled'] = True
            return {}
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

    def _create(self, task):
        _closed(task, ('task_id', 'action_id', 'trigger'), ('idempotency_key', 'dependency_ids', 'recurrence_policy'))
        task_id, action_id = _text(task['task_id']), _text(task['action_id'])
        encoded = _json(task)
        key = task.get('idempotency_key')
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
            if spec['operator'] != 'eq':
                raise ValueError('draft reference supports equality conditions only')
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
        firings = []
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
                eligible = signal is not None and task['due'] <= _time(signal['observed_at']) <= self.now and _json(signal['value']) == _json(spec['value'])
            elif kind == 'dependency_completion':
                eligible = set(task['dependencies']) <= completed
            if not eligible:
                continue
            firings.append({'action_id': task['action_id'], 'intention_id': 'reference:' + task_id,
                            'occurrence': task['occurrence'], 'trigger_type': kind,
                            'due_at': task['due'].isoformat(), 'evaluated_at': self.now.isoformat(),
                            'provider_evaluated_at': None})
            task['occurrence'] += 1
            if task['interval'] is not None:
                task['due'] += timedelta(seconds=task['interval'])
        self.events.clear()
        self.conditions.clear()
        return {'firing_observations': firings, 'evaluated_at': self.now.isoformat()}
