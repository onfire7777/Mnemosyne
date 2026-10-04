"""Descriptive formation-state comparison from public inspection snapshots.

Independent of the product engine, provider proposal and action translator.
This is not firing evaluation, a calibrated quality score or input attestation.
"""

from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime
import json


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _time(value):
    if not isinstance(value, str):
        raise ValueError('timestamp must be text')
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError('timestamp must have a timezone')
    return result.astimezone(UTC).isoformat()


def _signature(action, kind, expression, due, recurrence, dependencies):
    if not isinstance(action, str) or not action or not isinstance(kind, str):
        raise ValueError('invalid schedule identity')
    if not isinstance(expression, dict) or not isinstance(recurrence, dict) or not isinstance(dependencies, list):
        raise ValueError('invalid schedule fields')
    expression = deepcopy(expression)
    if kind == 'exact_time':
        expression['at'] = _time(expression['at'])
    elif kind == 'time_window':
        expression['start'] = _time(expression['start'])
        expression['end'] = _time(expression['end'])
    # Remaining JSON values retain their exact types, including nested bools.
    return _json({'action_id': action, 'type': kind, 'expression': expression,
                  'due_at': _time(due), 'recurrence': recurrence,
                  'dependencies': sorted(dependencies)})


def _expected(schedule):
    if set(schedule) != {'action_id', 'trigger', 'recurrence_policy'}:
        raise ValueError('unsupported expected schedule fields')
    trigger = schedule['trigger']
    if not isinstance(trigger, dict) or set(trigger) != {'type', 'payload'}:
        raise ValueError('invalid expected trigger')
    kind, expression = trigger['type'], deepcopy(trigger['payload'])
    if kind == 'exact_time':
        due = expression['at']
    elif kind == 'time_window':
        due = expression['start']
    elif kind in ('event', 'condition'):
        due = expression.pop('due_at')
    else:
        raise ValueError('expected trigger is not defined by this corpus version')
    recurrence = schedule['recurrence_policy']
    if recurrence is None:
        recurrence = {'type': 'none'}
    return _signature(schedule['action_id'], kind, expression, due, recurrence, [])


def _observed(task):
    if not isinstance(task, dict) or set(task) != {'task_id', 'intention_id', 'revision', 'status', 'action_id', 'schedule'}:
        raise ValueError('full public schedule inspection is required')
    if task['status'] not in ('scheduled', 'cancelled', 'fired'):
        raise ValueError('invalid task status')
    for field in ('task_id', 'intention_id', 'revision'):
        if not isinstance(task[field], str) or not task[field]:
            raise ValueError('invalid task identity')
    schedule = task['schedule']
    if not isinstance(schedule, dict) or set(schedule) != {
        'trigger_type', 'trigger_expression', 'due_at', 'dependencies',
        'recurrence_policy', 'recurrence_state', 'evidence_ids',
    }:
        raise ValueError('invalid inspected schedule fields')
    state = schedule['recurrence_state']
    if not isinstance(state, dict) or type(state.get('occurrence')) is not int or state['occurrence'] < 0:
        raise ValueError('invalid inspected recurrence state')
    signature = _signature(task['action_id'], schedule['trigger_type'], schedule['trigger_expression'],
                           schedule['due_at'], schedule['recurrence_policy'], schedule['dependencies'])
    return signature, state['occurrence']


def score_case(case, snapshots):
    """Compare every turn, without using provider-proposed operation content."""
    expected_turns = case['gold']['turns']
    if case['gold']['case_id'] != case['public']['case_id'] or len(expected_turns) != len(snapshots):
        raise ValueError('case identity or turn count differs')
    rows = []
    for index, (expected, observed) in enumerate(zip(expected_turns, snapshots, strict=True)):
        if (not isinstance(observed, dict)
                or set(observed) != {'stage', 'case_id', 'turn', 'tasks', 'clarification'}
                or observed['stage'] != 'turn_completed'
                or observed['case_id'] != case['public']['case_id']
                or type(observed['turn']) is not int or observed['turn'] != index
                or expected['turn_id'] != str(index)):
            raise ValueError('snapshot differs from ordered case turns')
        if not isinstance(observed['tasks'], list):
            raise ValueError('invalid task snapshots')
        question = observed['clarification']
        if question is not None and (not isinstance(question, str) or not question.strip()):
            raise ValueError('invalid clarification observation')
        desired = Counter(_expected(schedule) for schedule in expected['active_schedules'])
        actual, task_ids, intention_ids = Counter(), set(), set()
        fired, advanced = 0, 0
        for task in observed['tasks']:
            signature, occurrence = _observed(task)
            if task['task_id'] in task_ids or task['intention_id'] in intention_ids:
                raise ValueError('duplicate identity in public task snapshot')
            task_ids.add(task['task_id'])
            intention_ids.add(task['intention_id'])
            if task['status'] == 'scheduled':
                actual[signature] += 1
            fired += task['status'] == 'fired'
            advanced += occurrence
        tp = sum((desired & actual).values())
        fp, fn = sum((actual - desired).values()), sum((desired - actual).values())
        rows.append({'turn': index, 'true_positives': tp, 'false_positives': fp, 'false_negatives': fn,
                     'state_exact_match': actual == desired and not fired and not advanced,
                     'premature_fired_tasks': fired, 'observed_occurrence_advances': advanced,
                     'clarification_expected': expected['decision'] == 'clarify',
                     'clarification_present': question is not None,
                     'clarification_semantics': 'not-evaluated'})
    return {'schema': 'm12-formation-state-diagnostic/v1', 'case_id': case['public']['case_id'],
            'track': 'DEVELOPMENT', 'publishable': False, 'ranking_eligible': False,
            'firing_evaluated': False, 'provenance_verified': False, 'turns': rows}
