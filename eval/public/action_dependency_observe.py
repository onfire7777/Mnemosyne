"""Public observation and evaluator-only timing for dependency development cases."""

from copy import deepcopy

from eval.public.action_dependency_plan import observation_plan
from eval.public.action_timing_run import _deliver
from eval.public.action_timing import _time
from eval.public.action_trigger_timing import score_trigger_windows


def observe_case(case, *, actions, scope, sink, emit):
    case_id = case['public']['case_id']
    ticks = []
    probes = observation_plan(case)
    if _time(probes[0]) <= _time(case['public']['turns'][-1]['now']):
        raise ValueError('formation turns overlap dependency observations')
    for index, now in enumerate(probes):
        for command, payload in (('clock.inject', {'now': now}), ('intention.observe', {})):
            context = {'case_id': case_id, 'probe': index, 'command': command}
            emit({'stage': 'observation_request', **context, 'payload': deepcopy(payload)})
            try:
                response = actions.run(command, scope, deepcopy(payload))
            except Exception as error:
                emit({'stage': 'observation_error', **context, 'error_type': type(error).__name__})
                raise
            emit({'stage': 'observation_response', **context, 'response': deepcopy(response)})
            if command == 'intention.observe':
                if response.get('evaluated_at') != now:
                    raise ValueError('dependency observation clock differs from fixed probe')
                ticks.append(deepcopy(response))
                _deliver(sink, response)
    return {'case_id': case_id, 'ticks': ticks, 'sink': sink.snapshot(),
            'scored': False, 'publishable': False}


def expected_occurrences(case):
    gold = case['gold']
    if gold['case_id'] != case['public']['case_id'] or len(gold['turns']) != len(case['public']['turns']):
        raise ValueError('misaligned dependency labels')
    schedules = {s['action_id']: s for turn in gold['turns'] for s in turn['active_schedules']}
    final = {s['action_id'] for s in gold['turns'][-1]['active_schedules']}
    eligible = {s['action_id']: s['first_eligible_at'] for s in gold['expected_firings']}
    if len(eligible) != len(gold['expected_firings']) or not eligible.keys() <= final:
        raise ValueError('invalid dependency firing labels')
    rows = []
    for action, schedule in schedules.items():
        kind = schedule['trigger']['type']
        if kind not in ('exact_time', 'dependency_completion') or schedule['recurrence_policy'] is not None:
            raise ValueError('unsupported dependency extension schedule')
        payload = schedule['trigger']['payload']
        due = payload['at'] if kind == 'exact_time' else payload['due_at']
        rows.append({'action_id': action, 'occurrence': 0, 'trigger_type': kind, 'due_at': due,
                     'windows': [] if action not in eligible else [
                         {'start': eligible[action], 'end': None, 'end_inclusive': False}],
                     'cancelled_at': None if action in final else case['public']['turns'][-1]['now']})
    return rows


def score_observations(case, observation):
    if observation['case_id'] != case['public']['case_id']:
        raise ValueError('dependency observation case mismatch')
    if [tick['evaluated_at'] for tick in observation['ticks']] != observation_plan(case):
        raise ValueError('incomplete or altered dependency probe sequence')
    result = score_trigger_windows(expected_occurrences(case), observation['ticks'])
    result.update(case_id=observation['case_id'], ranking_eligible=False,
                  clarification_quality_evaluated=False, trace_replay_verified=False)
    return result
