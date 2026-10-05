"""Clock-driven public-CLI trigger pressure; development evidence, not capacity certification."""

import argparse
from datetime import UTC, datetime, timedelta
import hashlib
from pathlib import Path
import random
import re
import sqlite3
import sys
import tempfile
import time
import uuid

from eval.harness.cli_driver import MnemoCLI
from eval.public.action_cli import ActionCLI
from eval.public.action_formation_replay import _database_rows
from eval.public.action_timing import _closed, _time
from eval.public.action_timing_run import (
    SEEDS, _deliver, _sink_for, _source_receipt, _validate_sink_annex, _write,
)
from eval.public.action_trigger_timing import _metrics, score_trigger_windows
from eval.public.bundle import _canonical, _parse_json

DRAIN_NS = 1_640_000_000
MAX_NS = 10_000_000_000
MAX_TICKS = 64
SESSION = 'clocked-pressure'


def stamp(case, elapsed_ns):
    return (_time(case['start']) + timedelta(microseconds=elapsed_ns // 1000)).isoformat()


def make_plan():
    cases = []
    for seed in SEEDS:
        start = datetime(2030, 1, 1, tzinfo=UTC) + timedelta(weeks=random.Random(seed).randrange(104))
        case = {'case_id': f'seed-{seed}', 'seed': seed, 'start': start.isoformat(), 'setup': [], 'expected': []}
        case['setup'].append({'command':'clock.inject', 'payload':{'now':stamp(case, -1_000_000_000)}})
        for index in range(72):
            cancelled = index >= 64
            window = index % 2 == 1 and not cancelled
            offset = (index % 64) * 10_000_000
            at, end = stamp(case, offset), stamp(case, offset + 50_000_000)
            action = f'action-{index:03}'
            kind = 'time_window' if window else 'exact_time'
            case['setup'].append({'command':'task.create', 'payload':{
                'task_id':action, 'action_id':action, 'idempotency_key':action,
                'trigger':{'type':kind, 'payload':{'start':at, 'end':end} if window else {'at':at}}}})
            if cancelled:
                case['setup'].append({'command':'task.update', 'payload':{'type':'cancel', 'task_id':action}})
            case['expected'].append({'action_id':action, 'occurrence':0, 'trigger_type':kind, 'due_at':at,
                'cancelled_at':stamp(case, -1_000_000_000) if cancelled else None,
                'windows':[{'start':at, 'end':end if window else None, 'end_inclusive':False}]})
        cases.append(case)
    return {'schema':'m12-clocked-pressure/v1', 'track':'DEVELOPMENT', 'publishable':False,
            'release_interval_ns':10_000_000, 'release_period_ns':640_000_000,
            'drain_horizon_ns':DRAIN_NS, 'max_dispatch_ns':MAX_NS, 'max_ticks':MAX_TICKS, 'cases':cases}


def score_case(case, records):
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_TICKS:
        raise ValueError('missing or excessive pressure ticks')
    previous = 0
    for row in records:
        _closed(row, 'dispatch_ns response_ns delivered_ns response')
        values = [row[k] for k in ('dispatch_ns','response_ns','delivered_ns')]
        if any(type(n) is not int or n < 0 for n in values):
            raise ValueError('elapsed times must be nonnegative integer nanoseconds')
        dispatch, response, delivered = values
        if not previous <= dispatch <= response <= delivered or dispatch > MAX_NS:
            raise ValueError('nonmonotonic or over-budget pressure timeline')
        if row['response'].get('evaluated_at') != stamp(case, dispatch):
            raise ValueError('virtual clock differs from elapsed dispatch time')
        previous = delivered
    if records[-1]['dispatch_ns'] < DRAIN_NS:
        raise ValueError('missing final drain evaluation')
    conditional = score_trigger_windows(case['expected'], [r['response'] for r in records])
    live = {r['action_id']:r for r in case['expected'] if r['cancelled_at'] is None}
    valid = {r['action_id'] for r in conditional['rows'] if r['true_positives']}
    # Never reward missing a whole window because no poll visited it.
    full = _metrics(len(valid), conditional['metrics']['false_positives'], len(live)-len(valid))
    seen, samples, latencies = set(), [], []
    for record in records:
        complete = _time(stamp(case, record['response_ns']))
        now = _time(record['response']['evaluated_at'])
        for firing in record['response']['firing_observations']:
            key = firing['action_id']
            target = live.get(key)
            if target is None or key in seen or firing['occurrence'] != 0 or firing['trigger_type'] != target['trigger_type']:
                continue
            start = _time(target['due_at'])
            end = target['windows'][0]['end']
            if now < start or (end is not None and now >= _time(end)):
                continue
            seen.add(key)
            latencies.append({'action_id':key, 'seconds':(complete-start).total_seconds()})
        remaining = [r for k,r in live.items() if k not in seen and _time(r['due_at']) <= complete]
        samples.append({'response_ns':record['response_ns'],
                        'service_ns':record['response_ns']-record['dispatch_ns'],
                        'sink_ns':record['delivered_ns']-record['response_ns'],
                        'released_live':sum(_time(r['due_at']) <= complete for r in live.values()),
                        'valid_observed':len(seen),
                        'pending_exact':sum(r['trigger_type']=='exact_time' for r in remaining),
                        'open_unobserved_windows':sum(r['trigger_type']=='time_window' and complete < _time(r['windows'][0]['end']) for r in remaining),
                        'expired_unobserved_windows':sum(r['trigger_type']=='time_window' and complete >= _time(r['windows'][0]['end']) for r in remaining)})
    return {'case_id':case['case_id'], 'offered_live':len(live),
            'pre_cancelled':len(case['expected'])-len(live),
            'acknowledged_setup_schedules':len(case['expected']), 'setup_rejections':0,
            'native_admission_limit':None,
            'full_workload_metrics':full, 'tick_conditional':conditional, 'samples':samples,
            'response_lateness_seconds':latencies,
            'exact_drain_recovered':samples[-1]['pending_exact']==0,
            'native_capacity_verified':False, 'ranking_eligible':False}


def run_development(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    plan, results, sink_cases, completed = make_plan(), [], [], 0
    run_id = str(uuid.uuid4())
    _write(output/'plan.json', plan)
    source = _source_receipt(True)
    for path in (Path(__file__), Path(__file__).with_name('action_trigger_timing.py'),
                 Path(__file__).with_name('action_formation_replay.py')):
        source['harness_files']['eval/public/'+path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    _write(output/'source.json', source)
    try:
        with (output/'operations.jsonl').open('xb') as log, (output/'timings.jsonl').open('xb') as timing_log, tempfile.TemporaryDirectory(prefix='m12-pressure-', dir=output) as temp:
            adapter = ActionCLI(MnemoCLI(store=str(Path(temp)/'unused.json'), timeout_s=10))
            for case in plan['cases']:
                scope = {'store':str(Path(temp)/(case['case_id']+'.json')), 'tenant_id':case['case_id'], 'session_id':SESSION}
                sink = _sink_for(output/'sink.sqlite3', run_id, case['case_id'], SESSION)
                step = 0
                def invoke(command, payload):
                    nonlocal completed, step
                    request = {'case_id':case['case_id'], 'step':step, 'command':command, 'payload':payload}
                    log.write(_canonical({'kind':'request', **request}))
                    log.flush()
                    response = adapter.run(command, scope, payload)
                    log.write(_canonical({'kind':'response', 'case_id':case['case_id'], 'step':step, 'response':response}))
                    log.flush()
                    completed += 1
                    step += 1
                    return response
                for operation in case['setup']:
                    if invoke(operation['command'], operation['payload']) != {}:
                        raise ValueError('unexpected setup acknowledgement')
                records = []
                origin = time.perf_counter_ns()
                for _ in range(MAX_TICKS):
                    dispatch = time.perf_counter_ns()-origin
                    if dispatch > MAX_NS:
                        raise TimeoutError('pressure dispatch budget exceeded')
                    invoke('clock.inject', {'now':stamp(case, dispatch)})
                    response = invoke('intention.observe', {})
                    responded = time.perf_counter_ns()-origin
                    _deliver(sink, response)
                    record = {'dispatch_ns':dispatch, 'response_ns':responded,
                              'delivered_ns':time.perf_counter_ns()-origin, 'response':response}
                    timing_log.write(_canonical({'case_id':case['case_id'], 'index':len(records), **record}))
                    timing_log.flush()
                    records.append(record)
                    if dispatch >= DRAIN_NS:
                        break
                else:
                    raise TimeoutError('pressure tick budget exceeded')
                results.append(score_case(case, records))
                sink_cases.append({'case_id':case['case_id'], 'snapshot':sink.snapshot()})
        report = {'schema':'m12-clocked-pressure-report/v1', 'publishable':False, 'cases':results}
        _write(output/'reports.json', report)
        _write(output/'sink.json', {'schema':'m12-inert-sink-annex/v1', 'run_id':run_id, 'cases':sink_cases})
    except BaseException as error:
        _write(output/'status.json', {'status':'failed', 'exception_type':type(error).__name__, 'completed_operations':completed, 'completed_cases':len(results), 'publishable':False})
        raise
    _write(output/'status.json', {'status':'completed', 'completed_operations':completed, 'completed_cases':len(results), 'publishable':False})
    return report


def recompute(output):
    """Check ordered saved inputs and derived metrics; this does not attest the clock."""
    output = Path(output)
    def read_bytes(name):
        with (output/name).open('rb') as stream:
            raw = stream.read(16*1024*1024+1)
        if len(raw)>16*1024*1024:
            raise ValueError('pressure artifact exceeds limit')
        return raw
    def read(name):
        return read_bytes(name).decode('utf-8')
    source = _parse_json(read('source.json'), 'source')
    _closed(source, 'source_commit source_dirty python_version harness_files production_runtime_match_verified sink_enabled')
    paths = {'eval/public/'+name for name in ('action_timing_run.py','action_timing.py','action_cli.py','action_sink.py',
             'action_pressure.py','action_trigger_timing.py','action_formation_replay.py')} | {'eval/harness/cli_driver.py'}
    if (source['sink_enabled'] is not True or source['production_runtime_match_verified'] is not False
            or type(source['source_dirty']) is not bool or not isinstance(source['python_version'],str)
            or not isinstance(source['source_commit'],str) or re.fullmatch('[0-9a-f]{40}', source['source_commit']) is None
            or not isinstance(source['harness_files'],dict) or set(source['harness_files'])!=paths):
        raise ValueError('invalid pressure source receipt')
    root = Path(__file__).resolve().parents[2]
    if any(hashlib.sha256((root/name).read_bytes()).hexdigest()!=source['harness_files'][name] for name in paths):
        raise ValueError('pressure replay source differs from recorded source')
    plan = _parse_json(read('plan.json'), 'plan')
    if _canonical(plan) != _canonical(make_plan()):
        raise ValueError('pressure plan differs from the versioned workload')
    events = [_parse_json(line,'operation') for line in read('operations.jsonl').splitlines()]
    timings = [_parse_json(line,'timing') for line in read('timings.jsonl').splitlines()]
    if len(events)%2:
        raise ValueError('incomplete public operation')
    operations = []
    for request, response in zip(events[::2],events[1::2]):
        _closed(request, 'kind case_id step command payload')
        _closed(response, 'kind case_id step response')
        if request['kind']!='request' or response['kind']!='response' or any(request[k]!=response[k] for k in ('case_id','step')):
            raise ValueError('unpaired public operation')
        operations.append({k:v for k,v in request.items() if k!='kind'} | {'response':response['response']})
    cursor, time_cursor, results = 0, 0, []
    for case in plan['cases']:
        records = []
        while time_cursor < len(timings) and timings[time_cursor].get('case_id')==case['case_id']:
            timing = timings[time_cursor]
            _closed(timing, 'case_id index dispatch_ns response_ns delivered_ns response')
            if type(timing['index']) is not int or timing['index']!=len(records):
                raise ValueError('unordered pressure timing')
            records.append({k:v for k,v in timing.items() if k not in ('case_id','index')})
            time_cursor += 1
        expected = [{**op, 'response':{}} for op in case['setup']]
        for row in records:
            expected.extend([{'command':'clock.inject','payload':{'now':stamp(case,row['dispatch_ns'])},'response':{}},
                             {'command':'intention.observe','payload':{},'response':row['response']}])
        for step, operation in enumerate(expected):
            actual = operations[cursor] if cursor < len(operations) else None
            if actual is None or type(actual['step']) is not int or _canonical(actual)!=_canonical({'case_id':case['case_id'],'step':step,**operation}):
                raise ValueError('public operations differ from pressure inputs')
            cursor += 1
        results.append(score_case(case,records))
    if cursor!=len(operations) or time_cursor!=len(timings):
        raise ValueError('extra pressure records')
    status = {'status':'completed','completed_operations':len(operations),'completed_cases':len(results),'publishable':False}
    if _canonical(_parse_json(read('status.json'),'status'))!=_canonical(status):
        raise ValueError('pressure run did not complete')
    report = {'schema':'m12-clocked-pressure-report/v1','publishable':False,'cases':results}
    if _canonical(_parse_json(read('reports.json'),'reports'))!=_canonical(report):
        raise ValueError('pressure report does not recompute')
    _validate_sink_annex(output,read,plan,operations,SESSION)
    annex = _parse_json(read('sink.json'),'sink')
    # Compare the durable database too, using private copies for read-only inspection.
    with tempfile.TemporaryDirectory(prefix='pressure-replay-') as directory:
        original, replay = Path(directory)/'original.sqlite3', Path(directory)/'replay.sqlite3'
        original.write_bytes(read_bytes('sink.sqlite3'))
        for case in plan['cases']:
            sink = _sink_for(replay, annex['run_id'], case['case_id'], SESSION)
            for operation in operations:
                if operation['case_id']==case['case_id'] and operation['command']=='intention.observe':
                    _deliver(sink,operation['response'])
        try:
            if _database_rows(original)!=_database_rows(replay):
                raise ValueError('pressure sink database differs from delivery replay')
        except sqlite3.DatabaseError as error:
            raise ValueError('invalid pressure sink database') from error
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    parser.add_argument('--recompute',action='store_true')
    args = parser.parse_args()
    try:
        result = recompute(args.output) if args.recompute else run_development(args.output)
    except Exception as error:
        print(f'Pressure diagnostic failed: {type(error).__name__}', file=sys.stderr)
        raise SystemExit(1) from None
    print(_canonical(result).decode(),end='')
