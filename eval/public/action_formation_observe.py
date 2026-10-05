"""Fixed public-input probes for the version-one formation development corpus.

The probe plan never reads gold labels or candidate schedules. It is not a
scorer: receipts prove observed delivery, not correct formation or eligibility.
"""

from copy import deepcopy
from datetime import UTC, datetime, timedelta

from eval.public.action_implicit_plan import public_case
from eval.public.action_timing_run import _deliver


def observation_plan(case):
    public = public_case(case)
    start = datetime.fromisoformat(public['turns'][0]['now'].replace('Z', '+00:00'))
    if start.tzinfo is None:
        raise ValueError('observation origin must be timezone aware')
    last = datetime.fromisoformat(public['turns'][-1]['now'].replace('Z', '+00:00'))
    # Probe before due, at due with decoys, at a matching signal, after expiry,
    # at rescheduled due, and at all recurrence dates plus a fourth-date control.
    offsets = (120, 3599, 3600, 3601, 7200, 10800, 10801,
               608400, 608401, 1213200, 1213201, 1818000)
    rows = []
    for index, offset in enumerate(offsets):
        at = start + timedelta(seconds=offset)
        if at <= last:
            raise ValueError('formation turns overlap fixed observation horizon')
        stamp = at.astimezone(UTC).isoformat().replace('+00:00', 'Z')
        signals = []
        if offset in (3600, 3601):
            signals = [
                {'kind': 'event', 'event_id': f'formation-probe-{index}',
                 'event_type': 'delivery', 'occurred_at': stamp,
                 'payload': {'status': 'ready' if offset == 3601 else 'pending'}},
                {'kind': 'condition', 'condition_id': 'release_ready',
                 'observed_at': stamp, 'value': offset == 3601},
            ]
        rows.append({'now': stamp, 'signals': signals})
    return rows


def observe_case(case, *, actions, scope, sink, emit):
    """Retain each attempted call before execution and every firing in the sink."""
    case_id = public_case(case)['case_id']
    ticks = []
    for index, probe in enumerate(observation_plan(case)):
        operations = [('clock.inject', {'now': probe['now']})]
        operations.extend(('event.inject', signal) for signal in probe['signals'])
        operations.append(('intention.observe', {}))
        for command, payload in operations:
            context = {'case_id': case_id, 'probe': index, 'command': command}
            emit({'stage': 'observation_request', **context, 'payload': deepcopy(payload)})
            try:
                response = actions.run(command, scope, deepcopy(payload))
            except Exception as error:
                emit({'stage': 'observation_error', **context, 'error_type': type(error).__name__})
                raise
            emit({'stage': 'observation_response', **context, 'response': deepcopy(response)})
            if command == 'intention.observe':
                if response.get('evaluated_at') != probe['now']:
                    raise ValueError('observation clock differs from fixed probe')
                ticks.append(deepcopy(response))
                _deliver(sink, response)
    return {'case_id': case_id, 'ticks': ticks, 'sink': sink.snapshot(),
            'scored': False, 'publishable': False}
