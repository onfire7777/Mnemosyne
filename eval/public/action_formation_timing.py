"""Evaluator-only timing expectations for the v1 formation development corpus."""

from datetime import timedelta

from eval.public.action_formation_observe import observation_plan
from eval.public.action_timing import _time
from eval.public.action_trigger_timing import score_trigger_windows


def expected_occurrences(case):
    """Use evaluator labels and fixed stimuli, never the candidate's schedules."""
    gold = case['gold']
    public = case['public']
    if gold['case_id'] != public['case_id'] or len(gold['turns']) != len(public['turns']):
        raise ValueError('misaligned formation labels')
    final = gold['turns'][-1]
    cancelled = final['decision'] == 'cancel'
    schedules = gold['turns'][0]['active_schedules'] if cancelled else final['active_schedules']
    cancelled_at = public['turns'][-1]['now'] if cancelled else None
    probes = observation_plan(case)
    rows = []
    for schedule in schedules:
        trigger = schedule['trigger']
        kind, payload = trigger['type'], trigger['payload']
        due = payload['at'] if kind == 'exact_time' else payload['start'] if kind == 'time_window' else payload['due_at']
        recurrence = schedule['recurrence_policy']
        if recurrence is not None and (kind != 'exact_time' or recurrence['type'] != 'interval'):
            raise ValueError('unsupported formation recurrence')
        count = 1 if recurrence is None else recurrence['max_occurrences']
        if type(count) is not int or not 1 <= count <= 100:
            raise ValueError('invalid formation occurrence count')
        for occurrence in range(count):
            at = _time(due) + timedelta(seconds=0 if recurrence is None else occurrence * recurrence['interval_seconds'])
            stamp = at.isoformat().replace('+00:00', 'Z')
            if kind in ('exact_time', 'time_window'):
                windows = [{'start': stamp, 'end': payload['end'] if kind == 'time_window' else None,
                            'end_inclusive': False}]
            elif kind in ('event', 'condition'):
                windows = []
                for probe in probes:
                    if _time(probe['now']) < at:
                        continue
                    for signal in probe['signals']:
                        if kind == 'event':
                            match = signal['kind'] == 'event' and signal['event_type'] == payload['event_type'] and all(
                                type(signal['payload'].get(key)) is type(value) and signal['payload'].get(key) == value
                                for key, value in payload['match'].items())
                        else:
                            if payload['operator'] != 'eq':
                                raise ValueError('unsupported formation condition operator')
                            match = signal['kind'] == 'condition' and signal['condition_id'] == payload['condition_id'] and (
                                type(signal['value']) is type(payload['value']) and signal['value'] == payload['value'])
                        if match:
                            windows.append({'start': probe['now'], 'end': probe['now'], 'end_inclusive': True})
                            break
            else:
                raise ValueError('unsupported formation trigger')
            rows.append({'action_id': schedule['action_id'], 'occurrence': occurrence,
                         'trigger_type': kind, 'due_at': stamp, 'windows': windows,
                         'cancelled_at': cancelled_at})
    return rows


def score_observations(case, observation):
    if observation['case_id'] != case['public']['case_id']:
        raise ValueError('observation case mismatch')
    ticks = observation['ticks']
    if [tick['evaluated_at'] for tick in ticks] != [probe['now'] for probe in observation_plan(case)]:
        raise ValueError('incomplete or altered formation probe sequence')
    report = score_trigger_windows(expected_occurrences(case), ticks)
    report.update({'case_id': observation['case_id'], 'ranking_eligible': False,
                   'clarification_quality_evaluated': False,
                   'trace_replay_verified': False})
    return report
