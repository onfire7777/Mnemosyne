"""Bounded mixed-trigger fan-out development workload; not a capacity claim."""

from datetime import UTC, datetime, timedelta
import random

from eval.public.action_timing_run import SEEDS


def make_fanout_plan():
    cases = []
    for seed in SEEDS:
        start = datetime(2030, 1, 1, tzinfo=UTC) + timedelta(days=random.Random(seed).randrange(730))
        operations, expected, phases = [], [], []

        def stamp(offset):
            return (start + timedelta(seconds=offset)).isoformat().replace('+00:00', 'Z')

        def op(command, **payload):
            operations.append({'command': command, 'payload': payload})

        for week, fanout in enumerate((2, 4, 8, 16)):
            first_step, first_expected = len(operations), len(expected)
            base = week * 604800
            group = f'w{week}'
            for index in range(fanout):
                prefix = f'{group}-{index}-'
                specs = (
                    ('exact', 'exact_time', {'at': stamp(base)}, base, [(base, None)], []),
                    ('window', 'time_window', {'start': stamp(base + 1), 'end': stamp(base + 3)}, base + 1, [(base + 1, base + 3)], []),
                    ('event', 'event', {'event_type': group, 'match': {'code': 'yes'}, 'due_at': stamp(base)}, base, [(base + 1, base + 1)], []),
                    ('condition', 'condition', {'condition_id': group, 'operator': 'eq', 'value': True, 'due_at': stamp(base)}, base, [(base + 1, base + 1)], []),
                    ('dependency', 'dependency_completion', {'due_at': stamp(base + 2)}, base + 2, [(base + 2, None)], [prefix + 'exact']),
                    ('decoy', 'event', {'event_type': group, 'match': {'code': 'never'}, 'due_at': stamp(base)}, base, [], []),
                )
                for name, kind, payload, due, windows, dependencies in specs:
                    action = prefix + name
                    op('task.create', task_id=action, action_id=action, idempotency_key=action,
                       trigger={'type': kind, 'payload': payload}, dependency_ids=dependencies)
                    expected.append({
                        'action_id': action, 'occurrence': 0, 'trigger_type': kind, 'due_at': stamp(due),
                        'cancelled_at': None,
                        'windows': [{'start': stamp(a), 'end': stamp(b) if b is not None else None,
                                     'end_inclusive': kind != 'time_window'} for a, b in windows],
                    })
            for tick_index, second in enumerate((-1, 0, 1, 1, 2, 3)):
                op('clock.inject', now=stamp(base + second))
                if tick_index in (1, 2):
                    op('event.inject', kind='event', event_id=group + '-' + str(second),
                       event_type=group, occurred_at=stamp(base + second),
                       payload={'code': 'yes' if second == 1 else 'no'})
                    op('event.inject', kind='condition', condition_id=group,
                       value=second == 1, observed_at=stamp(base + second))
                op('intention.observe')
            phases.append({'week': week, 'fanout_per_trigger': fanout, 'operation_start': first_step,
                           'operation_end': len(operations), 'action_ids': [row['action_id'] for row in expected[first_expected:]]})
        cases.append({'case_id': f'seed-{seed}', 'seed': seed, 'operations': operations, 'expected': expected, 'phases': phases})
    return {'schema': 'm12-trigger-fanout-run/v1', 'track': 'DEVELOPMENT', 'publishable': False,
            'fanout_per_trigger_by_week': [2, 4, 8, 16], 'cases': cases}
