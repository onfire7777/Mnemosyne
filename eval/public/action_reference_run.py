"""Retain draft reference runs without presenting them as candidate measurements."""

import argparse
import hashlib
from pathlib import Path
import sys
import time
import uuid

from eval.public.action_reference import ExplicitActionReference
from eval.public.action_trigger_run import make_plan, reports as validate_workload
from eval.public.action_fanout_plan import make_fanout_plan
from eval.public.action_timing_run import _deliver, _sink_for, _source_receipt, _validate_sink_annex, _write
from eval.public.bundle import _canonical, _parse_json

REFERENCE_ID = 'draft-explicit-action-reference/v1'
SESSION = 'draft-reference'


def _report(plan, records):
    workload = validate_workload(plan, records)
    cursor = 0
    for case in plan['cases']:
        reference = ExplicitActionReference()
        for operation in case['operations']:
            actual = records[cursor]['response']
            cursor += 1
            semantic = reference.run(operation['command'], operation['payload'])
            if operation['command'] == 'intention.observe':
                semantic.update(action_ids=sorted(row['action_id'] for row in semantic['firing_observations']),
                                queried_channels=[], evaluation_wall_ms=actual['evaluation_wall_ms'])
                # The outer protocol preserves the request's clock spelling.
                semantic['evaluated_at'] = actual['evaluated_at']
            if _canonical(semantic) != _canonical(actual):
                raise ValueError('reference semantics do not replay')
    return {'schema': 'm12-draft-reference-report/v1', 'reference_id': REFERENCE_ID,
            'track': 'DEVELOPMENT', 'publishable': False, 'baseline_admitted': False,
            'workload': workload}


def run_development(output, *, fanout=False):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    plan = make_fanout_plan() if fanout else make_plan()
    _write(output / 'plan.json', plan)
    source = _source_receipt(True)
    source['reference_id'] = REFERENCE_ID
    for name in ('action_reference.py', 'action_reference_run.py', 'action_trigger_run.py',
                 'action_trigger_timing.py', 'action_fanout_plan.py'):
        source['harness_files']['eval/public/' + name] = hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
    _write(output / 'source.json', source)
    records, sink_cases = [], []
    run_id = str(uuid.uuid4())
    try:
        with (output / 'operations.jsonl').open('xb') as log:
            for case in plan['cases']:
                reference = ExplicitActionReference()
                sink = _sink_for(output / 'sink.sqlite3', run_id, case['case_id'], SESSION)
                now = None
                for step, operation in enumerate(case['operations']):
                    started = time.perf_counter()
                    response = reference.run(operation['command'], operation['payload'])
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    if operation['command'] == 'clock.inject':
                        now = operation['payload']['now']
                    if operation['command'] == 'intention.observe':
                        response.update(evaluated_at=now, evaluation_wall_ms=elapsed_ms,
                                        queried_channels=[], action_ids=sorted(row['action_id'] for row in response['firing_observations']))
                    record = {'case_id': case['case_id'], 'step': step, **operation, 'response': response}
                    log.write(_canonical(record))
                    log.flush()
                    records.append(record)
                    if operation['command'] == 'intention.observe':
                        _deliver(sink, response)
                sink_cases.append({'case_id': case['case_id'], 'snapshot': sink.snapshot()})
        result = _report(plan, records)
        _write(output / 'reports.json', result)
        _write(output / 'sink.json', {'schema': 'm12-inert-sink-annex/v1', 'run_id': run_id, 'cases': sink_cases})
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
            raise ValueError('reference artifact exceeds 16 MiB')
        return raw.decode('utf-8')

    source = _parse_json(read('source.json'), 'source')
    if source.get('reference_id') != REFERENCE_ID or source.get('sink_enabled') is not True:
        raise ValueError('draft reference identity and sink are required')
    plan = _parse_json(read('plan.json'), 'plan')
    records = [_parse_json(row, 'operation') for row in read('operations.jsonl').splitlines()]
    result = _report(plan, records)
    if _parse_json(read('status.json'), 'status') != {
        'status': 'completed', 'completed_operations': len(records), 'publishable': False,
    }:
        raise ValueError('reference execution did not complete')
    if _canonical(_parse_json(read('reports.json'), 'report')) != _canonical(result):
        raise ValueError('reference report differs from replay')
    _validate_sink_annex(output, read, plan, records, SESSION)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--recompute', action='store_true')
    mode.add_argument('--fanout', action='store_true')
    args = parser.parse_args()
    try:
        result = recompute(args.output) if args.recompute else run_development(args.output, fanout=args.fanout)
    except Exception as error:
        print(f'Reference run failed: {type(error).__name__}', file=sys.stderr)
        raise SystemExit(1) from None
    print(_canonical(result).decode(), end='')
