"""Versioned four-week explicit-trigger DEVELOPMENT workload and trace replay."""

import argparse
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
import random
import sys
import tempfile

from eval.harness.cli_driver import MnemoCLI
from eval.public.action_cli import ActionCLI
from eval.public.action_timing_run import SEEDS, _source_receipt, _write
from eval.public.action_trigger_timing import score_trigger_windows
from eval.public.bundle import _canonical, _parse_json


def make_plan():
    cases = []
    for seed in SEEDS:
        rng = random.Random(seed)
        start = datetime(2030, 1, 1, tzinfo=UTC) + timedelta(days=rng.randrange(730))
        operations, expected = [], []

        def stamp(seconds):
            return (start + timedelta(seconds=seconds)).isoformat().replace('+00:00', 'Z')

        def op(command, **payload):
            operations.append({'command': command, 'payload': payload})

        def gold(action, kind, due, windows, occurrence=0, cancelled=None):
            expected.append({
                'action_id': action, 'occurrence': occurrence, 'trigger_type': kind,
                'due_at': stamp(due), 'cancelled_at': stamp(cancelled) if cancelled is not None else None,
                'windows': [{'start': stamp(a), 'end': stamp(b) if b is not None else None,
                             'end_inclusive': kind != 'time_window'} for a, b in windows],
            })

        for action in ('weekly-keep', 'weekly-cancel'):
            op('task.create', task_id=action, action_id=action, idempotency_key=action,
               trigger={'type': 'exact_time', 'payload': {'at': stamp(0)}},
               recurrence_policy={'type': 'interval', 'interval_seconds': 604800, 'max_occurrences': 4})
            # Identical creation replay must not create a second schedule.
            operations.append({'command': 'task.create', 'payload': dict(operations[-1]['payload'])})
            for week in range(4):
                gold(action, 'exact_time', week * 604800, [(week * 604800, None)], week,
                     604803 if action == 'weekly-cancel' else None)

        for week in range(4):
            base = week * 604800
            prefix = f'w{week}-'
            specs = [
                ('exact', 'exact_time', {'at': stamp(base)}, base, [(base, None)], []),
                ('window', 'time_window', {'start': stamp(base + 1), 'end': stamp(base + 3)}, base + 1, [(base + 1, base + 3)], []),
                ('event', 'event', {'event_type': prefix + 'arrived', 'match': {'code': 'yes'}, 'due_at': stamp(base)}, base, [(base + 1, base + 1)], []),
                ('condition', 'condition', {'condition_id': prefix + 'ready', 'operator': 'eq', 'value': True, 'due_at': stamp(base)}, base, [(base + 1, base + 1)], []),
                ('dependency', 'dependency_completion', {'due_at': stamp(base + 2)}, base + 2, [(base + 2, None)], [prefix + 'exact']),
                ('never-event', 'event', {'event_type': prefix + 'arrived', 'match': {'code': 'never'}, 'due_at': stamp(base)}, base, [], []),
                ('expired', 'time_window', {'start': stamp(base - 2), 'end': stamp(base - 1)}, base - 2, [(base - 2, base - 1)], []),
                ('cancelled', 'exact_time', {'at': stamp(base + 2)}, base + 2, [(base + 2, None)], []),
            ]
            for name, kind, payload, due, windows, dependencies in specs:
                action = prefix + name
                op('task.create', task_id=action, action_id=action, idempotency_key=action,
                   trigger={'type': kind, 'payload': payload}, dependency_ids=dependencies)
                gold(action, kind, due, windows, cancelled=base - 1 if name == 'cancelled' else None)
            op('clock.inject', now=stamp(base - 1))
            op('task.update', type='cancel', task_id=prefix + 'cancelled')
            op('intention.observe')
            for tick_index, second in enumerate((0, 1, 1, 2, 3)):
                op('clock.inject', now=stamp(base + second))
                # Signals are consumed by observe; the repeated tick has none.
                if tick_index < 2:
                    op('event.inject', kind='event', event_id=prefix + str(second),
                       event_type=prefix + 'arrived', occurred_at=stamp(base + second),
                       payload={'code': 'yes' if second == 1 else 'no'})
                    op('event.inject', kind='condition', condition_id=prefix + 'ready',
                       value=second == 1, observed_at=stamp(base + second))
                op('intention.observe')
            if week == 1:
                op('task.update', type='cancel', task_id='weekly-cancel')
        cases.append({'case_id': f'seed-{seed}', 'seed': seed, 'operations': operations, 'expected': expected})
    return {'schema': 'm12-explicit-trigger-run/v1', 'track': 'DEVELOPMENT', 'publishable': False, 'cases': cases}


def reports(plan, records):
    if _canonical(plan) != _canonical(make_plan()):
        raise ValueError('saved plan differs from the versioned workload')
    if len(records) != sum(len(case['operations']) for case in plan['cases']):
        raise ValueError('missing or extra operation records')
    cursor, results = 0, []
    for case in plan['cases']:
        ticks, now = [], None
        for step, operation in enumerate(case['operations']):
            record = records[cursor]
            cursor += 1
            if not isinstance(record, dict) or set(record) != {'case_id', 'step', 'command', 'payload', 'response'}:
                raise ValueError('invalid operation record')
            if (record['case_id'] != case['case_id'] or type(record['step']) is not int or record['step'] != step
                    or record['command'] != operation['command'] or _canonical(record['payload']) != _canonical(operation['payload'])):
                raise ValueError('operation record does not match the plan')
            if operation['command'] == 'clock.inject':
                now = operation['payload']['now']
            if operation['command'] == 'intention.observe':
                if not isinstance(record['response'], dict) or record['response'].get('evaluated_at') != now:
                    raise ValueError('observation clock differs from planned clock')
                ticks.append(record['response'])
            elif record['response'] != {}:
                raise ValueError('unexpected non-observation response')
        results.append({'case_id': case['case_id'], 'report': score_trigger_windows(case['expected'], ticks)})
    return {'schema': 'm12-explicit-trigger-reports/v1', 'publishable': False,
            'ordered_workload_verified': True, 'cases': results}


def run_development(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    plan, records = make_plan(), []
    _write(output / 'plan.json', plan)
    source = _source_receipt()
    for name in ('action_trigger_run.py', 'action_trigger_timing.py'):
        path = Path(__file__).with_name(name)
        source['harness_files']['eval/public/' + name] = hashlib.sha256(path.read_bytes()).hexdigest()
    _write(output / 'source.json', source)
    try:
        with (output / 'operations.jsonl').open('xb') as log, tempfile.TemporaryDirectory(prefix='m12-triggers-') as temp:
            adapter = ActionCLI(MnemoCLI(store=str(Path(temp) / 'unused.json'), timeout_s=30))
            for case in plan['cases']:
                scope = {'store': str(Path(temp) / (case['case_id'] + '.json')),
                         'tenant_id': case['case_id'], 'session_id': 'explicit-triggers'}
                for step, operation in enumerate(case['operations']):
                    response = adapter.run(operation['command'], scope, operation['payload'])
                    record = {'case_id': case['case_id'], 'step': step, **operation, 'response': response}
                    log.write(_canonical(record))
                    log.flush()
                    records.append(record)
        result = reports(plan, records)
        _write(output / 'reports.json', result)
    except BaseException as error:
        _write(output / 'status.json', {'status': 'failed', 'exception_type': type(error).__name__,
                                       'completed_operations': len(records), 'publishable': False})
        raise
    _write(output / 'status.json', {'status': 'completed', 'completed_operations': len(records), 'publishable': False})
    return result


def recompute(output):
    output = Path(output)

    def read(name):
        with (output / name).open('rb') as source:
            raw = source.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError('diagnostic artifact exceeds 16 MiB')
        return raw.decode('utf-8')

    status = _parse_json(read('status.json'), 'status')
    plan = _parse_json(read('plan.json'), 'plan')
    records = [_parse_json(line, 'operation') for line in read('operations.jsonl').splitlines()]
    result = reports(plan, records)
    if status != {'status': 'completed', 'completed_operations': len(records), 'publishable': False}:
        raise ValueError('execution did not complete')
    if _canonical(_parse_json(read('reports.json'), 'reports')) != _canonical(result):
        raise ValueError('saved reports do not recompute')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--recompute', action='store_true')
    args = parser.parse_args()
    try:
        result = recompute(args.output) if args.recompute else run_development(args.output)
    except Exception as error:
        print(f'Development diagnostic failed: {type(error).__name__}', file=sys.stderr)
        raise SystemExit(1) from None
    print(_canonical(result).decode('utf-8'), end='')
