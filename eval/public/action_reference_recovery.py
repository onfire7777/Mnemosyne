"""Retained durable draft-reference execution of the public recovery workload."""

import argparse
import hashlib
from pathlib import Path
import sys
import tempfile
import time
import uuid

from eval.public.action_recovery_run import make_plan, resolve_payload, reports
from eval.public.action_reference_store import DurableActionReference
from eval.public.action_timing_run import _deliver, _sink_for, _source_receipt, _validate_sink_annex, _write
from eval.public.bundle import _canonical, _parse_json

IDENTITY = 'draft-durable-action-reference/v1'
SESSION = 'reference-recovery'


def _execute(plan, database, emit):
    for case in plan['cases']:
        def reopen():
            return DurableActionReference(database, run_id='reference-recovery', case_id=case['case_id'],
                                          tenant_id=case['case_id'], session_id=SESSION)
        reference, past, now = reopen(), [], None
        for step, operation in enumerate(case['operations']):
            command = operation['command']
            payload = resolve_payload(operation, past)
            if command == 'adapter.reset':
                reference, response, now = reopen(), {}, None
            else:
                started = time.perf_counter()
                response = reference.run(command, payload)
                duration = (time.perf_counter() - started) * 1000
                if command == 'clock.inject':
                    now = payload['now']
                if command == 'intention.observe':
                    if now is None:
                        raise ValueError('reference adapter requires reinjected clock')
                    response.update(evaluated_at=now, evaluation_wall_ms=duration,
                                    queried_channels=[], action_ids=sorted(x['action_id'] for x in response['firing_observations']))
            outcome = 'ok'
            if operation['lose_response']:
                # run() has returned only after its SQLite transaction committed.
                response, outcome = {}, 'lost_response_after_success'
            record = {'case_id': case['case_id'], 'step': step, 'command': command,
                      'payload': operation['payload'], 'resolved_payload': payload,
                      'outcome': outcome, 'response': response}
            emit(record)
            past.append(record)


def _report(plan, records):
    checked = reports(plan, records)
    regenerated = []
    with tempfile.TemporaryDirectory(prefix='m12-reference-replay-') as temp:
        _execute(plan, Path(temp) / 'reference.sqlite3', regenerated.append)
    for original, replay in zip(records, regenerated, strict=True):
        if original['command'] == 'intention.observe':
            replay['response']['evaluation_wall_ms'] = original['response']['evaluation_wall_ms']
        if _canonical(original) != _canonical(replay):
            raise ValueError('durable reference semantics differ from retained records')
    return {'schema': 'm12-reference-recovery-report/v1', 'reference_id': IDENTITY,
            'publishable': False, 'baseline_admitted': False, 'workload': checked}


def run_development(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    plan, records = make_plan(), []
    _write(output / 'plan.json', plan)
    source = _source_receipt(True)
    source['reference_id'] = IDENTITY
    for name in ('action_reference.py', 'action_reference_store.py', 'action_reference_recovery.py',
                 'action_recovery_run.py', 'action_trigger_timing.py'):
        source['harness_files']['eval/public/' + name] = hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
    _write(output / 'source.json', source)
    run_id = str(uuid.uuid4())
    sinks = {case['case_id']: _sink_for(output / 'sink.sqlite3', run_id, case['case_id'], SESSION)
             for case in plan['cases']}
    try:
        with (output / 'operations.jsonl').open('xb') as log:
            def retain(record):
                log.write(_canonical(record))
                log.flush()
                records.append(record)
                if record['command'] == 'intention.observe':
                    _deliver(sinks[record['case_id']], record['response'])
            _execute(plan, output / 'reference.sqlite3', retain)
        result = _report(plan, records)
        _write(output / 'reports.json', result)
        _write(output / 'sink.json', {'schema': 'm12-inert-sink-annex/v1', 'run_id': run_id,
                                    'cases': [{'case_id': case['case_id'], 'snapshot': sinks[case['case_id']].snapshot()}
                                              for case in plan['cases']]})
    except BaseException as error:
        _write(output / 'status.json', {'status': 'failed', 'exception_type': type(error).__name__,
                                       'completed_operations': len(records), 'publishable': False})
        raise
    _write(output / 'status.json', {'status': 'completed', 'completed_operations': len(records), 'publishable': False})
    return result


def recompute(output):
    output = Path(output)
    def read(name):
        with (output / name).open('rb') as handle:
            raw = handle.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError('reference artifact exceeds limit')
        return raw.decode()
    source = _parse_json(read('source.json'), 'source')
    if not isinstance(source, dict) or source.get('reference_id') != IDENTITY or source.get('sink_enabled') is not True:
        raise ValueError('durable reference identity and sink required')
    plan = _parse_json(read('plan.json'), 'plan')
    records = [_parse_json(line, 'operation') for line in read('operations.jsonl').splitlines()]
    result = _report(plan, records)
    if _parse_json(read('status.json'), 'status') != {
        'status': 'completed', 'completed_operations': len(records), 'publishable': False,
    }:
        raise ValueError('reference recovery did not complete')
    if _canonical(result) != _canonical(_parse_json(read('reports.json'), 'report')):
        raise ValueError('reference recovery report differs')
    _validate_sink_annex(output, read, plan, records, SESSION)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--recompute', action='store_true')
    args = parser.parse_args()
    try:
        result = recompute(args.output) if args.recompute else run_development(args.output)
    except Exception as error:
        print(f'Reference recovery failed: {type(error).__name__}', file=sys.stderr)
        raise SystemExit(1) from None
    print(_canonical(result).decode(), end='')
