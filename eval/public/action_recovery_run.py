"""Persist public operation response-loss recovery over four virtual weeks."""

import argparse
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import hashlib
from pathlib import Path
import random
import sys
import tempfile

from eval.harness.cli_driver import MnemoCLI
from eval.public.action_cli import ActionCLI
from eval.public.action_timing_run import SEEDS, _source_receipt, _write
from eval.public.action_trigger_timing import score_trigger_windows
from eval.public.bundle import _canonical, _parse_json


class InjectedResponseLoss(Exception):
    """The subprocess succeeded; the adapter did not receive its response."""


@dataclass(slots=True)
class ResponseLossCLI(MnemoCLI):
    fault: dict = field(default_factory=dict)

    def run(self, command, *args, **kwargs):
        result = super(ResponseLossCLI, self).run(command, *args, **kwargs)
        if command == self.fault.get('command'):
            if not result.ok:
                raise ValueError('cannot inject response loss after a failed command')
            self.fault.clear()
            raise InjectedResponseLoss()
        return result


def make_plan():
    cases = []
    for seed in SEEDS:
        start = datetime(2030, 1, 1, tzinfo=UTC) + timedelta(days=random.Random(seed).randrange(730))
        steps, expected = [], []

        def stamp(seconds):
            return (start + timedelta(seconds=seconds)).isoformat().replace('+00:00', 'Z')

        def add(command, payload=None, *, lose=False, check=None):
            steps.append({'command': command, 'payload': deepcopy(payload or {}),
                          'lose_response': lose, 'check': check})
            return len(steps) - 1

        for week in range(4):
            task = f'w{week}'
            due = week * 604800 + 60
            cancel = week % 2 == 1
            create = {'task_id': task, 'action_id': task + '-original', 'idempotency_key': task + '-create',
                      'trigger': {'type': 'exact_time', 'payload': {'at': stamp(due)}}}
            add('clock.inject', {'now': stamp(due - 60)})
            add('task.create', create, lose=True)
            add('adapter.reset')
            add('task.create', create)
            before = add('task.inspect', {'task_id': task}, check={
                'status': 'scheduled', 'action_id': task + '-original', 'same_identity_as': None,
                'different_revision_from': None})
            update = {'type': 'override', 'task_id': task, 'action_id': task + '-revised',
                      'idempotency_key': task + '-update', 'expected_revision_from': before}
            add('task.update', update, lose=True)
            add('adapter.reset')
            add('task.create', create)
            add('task.update', update)
            after = add('task.inspect', {'task_id': task}, check={
                'status': 'scheduled', 'action_id': task + '-revised', 'same_identity_as': before,
                'different_revision_from': before})
            if cancel:
                cancellation = {'type': 'cancel', 'task_id': task, 'idempotency_key': task + '-cancel',
                                'expected_revision_from': after}
                add('clock.inject', {'now': stamp(due - 1)})
                add('task.update', cancellation, lose=True)
                add('adapter.reset')
                add('task.create', create)
                add('task.update', update)
                add('task.update', cancellation)
            add('clock.inject', {'now': stamp(due)})
            add('intention.observe')
            add('intention.observe')
            add('task.update', update)
            add('task.inspect', {'task_id': task}, check={
                'status': 'cancelled' if cancel else 'fired', 'action_id': task + '-revised',
                'same_identity_as': before, 'different_revision_from': after})
            expected.append({'action_id': task + '-revised', 'occurrence': 0, 'trigger_type': 'exact_time',
                             'due_at': stamp(due), 'cancelled_at': stamp(due - 1) if cancel else None,
                             'windows': [{'start': stamp(due), 'end': None, 'end_inclusive': True}]})
        cases.append({'case_id': f'seed-{seed}', 'seed': seed, 'operations': steps, 'expected': expected})
    return {'schema': 'm12-operation-recovery-run/v1', 'publishable': False, 'track': 'DEVELOPMENT', 'cases': cases}


def resolve_payload(operation, past):
    payload = deepcopy(operation['payload'])
    if 'expected_revision_from' in payload:
        index = payload.pop('expected_revision_from')
        if type(index) is not int or not 0 <= index < len(past):
            raise ValueError('revision must refer to an earlier inspection')
        row = past[index]
        if row['command'] != 'task.inspect' or row['outcome'] != 'ok':
            raise ValueError('revision source must be a successful inspection')
        if row['payload']['task_id'] != payload['task_id']:
            raise ValueError('revision source belongs to another task')
        payload['expected_revision'] = row['response']['revision']
    return payload


def _check_inspection(response, operation, past):
    if not isinstance(response, dict) or set(response) != {'task_id', 'intention_id', 'revision', 'status', 'action_id'}:
        raise ValueError('invalid inspection response')
    check = operation['check']
    if (response['task_id'] != operation['payload']['task_id'] or response['status'] != check['status']
            or response['action_id'] != check['action_id']):
        raise ValueError('inspection differs from planned state')
    if not isinstance(response['intention_id'], str) or not response['intention_id']:
        raise ValueError('missing intention identity')
    revision = response['revision']
    if not isinstance(revision, str) or len(revision) != 64 or any(c not in '0123456789abcdef' for c in revision):
        raise ValueError('invalid content revision')
    index = check['same_identity_as']
    if index is not None and response['intention_id'] != past[index]['response']['intention_id']:
        raise ValueError('retry changed intention identity')
    index = check['different_revision_from']
    if index is not None and revision == past[index]['response']['revision']:
        raise ValueError('expected state transition did not change revision')


def reports(plan, records):
    if _canonical(plan) != _canonical(make_plan()):
        raise ValueError('saved plan differs from versioned recovery workload')
    if len(records) != sum(len(c['operations']) for c in plan['cases']):
        raise ValueError('missing or extra recovery operation records')
    cursor, results = 0, []
    for case in plan['cases']:
        past, ticks, now, losses, resets = [], [], None, 0, 0
        identities = {}
        for step, operation in enumerate(case['operations']):
            record = records[cursor]
            cursor += 1
            if not isinstance(record, dict) or set(record) != {
                'case_id', 'step', 'command', 'payload', 'resolved_payload', 'outcome', 'response',
            }:
                raise ValueError('invalid recovery record')
            if (record['case_id'] != case['case_id'] or type(record['step']) is not int or record['step'] != step
                    or record['command'] != operation['command'] or record['payload'] != operation['payload']
                    or record['resolved_payload'] != resolve_payload(operation, past)):
                raise ValueError('recovery record differs from plan or original revision')
            wanted = 'lost_response_after_success' if operation['lose_response'] else 'ok'
            if record['outcome'] != wanted:
                raise ValueError('recovery fault outcome differs from plan')
            command = operation['command']
            response = record['response']
            if command == 'clock.inject':
                now = operation['payload']['now']
            elif command == 'adapter.reset':
                resets += 1
                now = None
            if operation['lose_response']:
                losses += 1
                if response != {}:
                    raise ValueError('lost response must not be exposed to adapter log')
            elif command == 'task.inspect':
                _check_inspection(response, operation, past)
                previous = identities.setdefault(response['action_id'], response['intention_id'])
                if previous != response['intention_id']:
                    raise ValueError('action identity changed across recovery')
            elif command == 'intention.observe':
                if now is None or not isinstance(response, dict) or response.get('evaluated_at') != now:
                    raise ValueError('observation clock differs from plan')
                ticks.append(response)
            elif response != {}:
                raise ValueError('unexpected recovery acknowledgement')
            past.append(record)
        timing = score_trigger_windows(case['expected'], ticks)
        for tick in ticks:
            for firing in tick.get('firing_observations', []):
                if (firing.get('action_id') in identities
                        and firing.get('intention_id') != identities[firing['action_id']]):
                    raise ValueError('firing identity differs from recovered intention')
        results.append({'case_id': case['case_id'], 'injected_response_losses': losses, 'adapter_resets': resets,
                        'report': timing})
    return {'schema': 'm12-operation-recovery-reports/v1', 'publishable': False,
            'ordered_workload_verified': True, 'cases': results}


def run_development(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    plan, records = make_plan(), []
    _write(output / 'plan.json', plan)
    source = _source_receipt()
    for name in ('action_recovery_run.py', 'action_trigger_timing.py'):
        path = Path(__file__).with_name(name)
        source['harness_files']['eval/public/' + name] = hashlib.sha256(path.read_bytes()).hexdigest()
    _write(output / 'source.json', source)
    try:
        with (output / 'operations.jsonl').open('xb') as log, tempfile.TemporaryDirectory(prefix='m12-recovery-') as temp:
            for case in plan['cases']:
                driver = ResponseLossCLI(store=str(Path(temp) / 'unused.json'), timeout_s=30)
                adapter, past = ActionCLI(driver), []
                scope = {'store': str(Path(temp) / (case['case_id'] + '.json')),
                         'tenant_id': case['case_id'], 'session_id': 'operation-recovery'}
                for step, operation in enumerate(case['operations']):
                    payload = resolve_payload(operation, past)
                    command = operation['command']
                    outcome = 'ok'
                    if operation['lose_response']:
                        driver.fault['command'] = ('intention-schedule' if command == 'task.create'
                                                   else 'intention-cancel' if payload.get('type') == 'cancel'
                                                   else 'intention-update')
                    try:
                        if command == 'adapter.reset':
                            adapter, response = ActionCLI(driver), {}
                        else:
                            response = adapter.run(command, scope, payload)
                    except InjectedResponseLoss:
                        if not operation['lose_response']:
                            raise
                        outcome, response = 'lost_response_after_success', {}
                    if driver.fault or (outcome == 'ok' and operation['lose_response']):
                        raise ValueError('planned response loss was not injected')
                    record = {'case_id': case['case_id'], 'step': step, 'command': command,
                              'payload': operation['payload'], 'resolved_payload': payload,
                              'outcome': outcome, 'response': response}
                    log.write(_canonical(record))
                    log.flush()
                    records.append(record)
                    past.append(record)
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
            raise ValueError('recovery artifact exceeds 16 MiB')
        return raw.decode('utf-8')

    plan = _parse_json(read('plan.json'), 'plan')
    records = [_parse_json(row, 'operation') for row in read('operations.jsonl').splitlines()]
    result = reports(plan, records)
    if _parse_json(read('status.json'), 'status') != {
        'status': 'completed', 'completed_operations': len(records), 'publishable': False,
    }:
        raise ValueError('recovery execution did not complete')
    if _canonical(_parse_json(read('reports.json'), 'reports')) != _canonical(result):
        raise ValueError('saved recovery report does not recompute')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--recompute', action='store_true')
    args = parser.parse_args()
    try:
        result = recompute(args.output) if args.recompute else run_development(args.output)
    except Exception as error:
        print(f'Recovery diagnostic failed: {type(error).__name__}', file=sys.stderr)
        raise SystemExit(1) from None
    print(_canonical(result).decode('utf-8'), end='')
