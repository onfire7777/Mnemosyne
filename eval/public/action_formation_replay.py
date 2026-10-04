"""Verify completed formation evidence without executing its recorded command.

This recomputes trace consistency, not model or engine execution. It shares the
versioned protocol driver and scorers; it is not an independent implementation
or attestation of provider identity, provenance, isolation or benchmark rank.
"""

import argparse
import base64
from copy import deepcopy
import hashlib
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile

from eval.public.action_formation import CommandFormationProvider, run_case
from eval.public.action_formation_observe import observation_plan, observe_case
from eval.public.action_formation_scoring import score_case
from eval.public.action_formation_timing import score_observations
from eval.public.action_implicit_plan import make_corpus, public_case
from eval.public.action_timing_run import _sink_for
from eval.public.bundle import _canonical, _json_depth, _parse_json

FILES = ('inputs.json', 'provider.json', 'source.json', 'observation-plan.json',
         'operations.jsonl', 'formation-state.json', 'observations.json',
         'formation-timing.json', 'execution.json', 'status.json', 'sink.sqlite3')
HARNESS_FILES = ('action_timing_run.py', 'action_cli.py', 'action_timing.py', 'action_sink.py',
                 'action_formation.py', 'action_formation_run.py', 'action_implicit_plan.py',
                 'action_formation_scoring.py', 'action_formation_observe.py',
                 'action_formation_timing.py', 'action_trigger_timing.py', 'action_formation_replay.py',
                 'action_formation_ollama.py')


def _read(path):
    # Refuse FIFOs/devices and final-component symlinks before reading. A read
    # budget also bounds a file that grows after fstat. The parent is caller-owned.
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError('formation artifact must be a regular file')
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as handle:
        opened = os.fstat(handle.fileno())
        if (not stat.S_ISREG(opened.st_mode)
                or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)):
            raise ValueError('formation artifact must be a regular file')
        raw = handle.read(64 * 1024 * 1024 + 1)
    if len(raw) > 64 * 1024 * 1024:
        raise ValueError('formation artifact exceeds 64 MiB')
    return raw


def _snapshot(root):
    result, size = {}, 0
    for name in FILES:
        result[name] = _read(root / name)
        size += len(result[name])
        if size > 128 * 1024 * 1024:
            raise ValueError('formation evidence exceeds 128 MiB')
    return result


def _json(raw, label):
    result = _parse_json(raw.decode('utf-8'), label)
    _json_depth(result)
    return result


def _same(actual, expected, label):
    if _canonical(actual) != _canonical(expected):
        raise ValueError(f'{label} differs from formation replay')


class _Trace:
    def __init__(self, records):
        self.records, self.position, self.snapshots = records, 0, []

    def peek(self, stages):
        if self.position >= len(self.records):
            raise ValueError('formation trace ended prematurely')
        row = self.records[self.position]
        if not isinstance(row, dict) or row.get('stage') not in stages:
            raise ValueError('formation trace has an unexpected stage')
        return row

    def emit(self, expected):
        actual = self.peek((expected['stage'],))
        expected = deepcopy(expected)
        if expected['stage'] in ('action_response', 'formation_response'):
            duration = actual.get('wall_ms')
            if type(duration) not in (int, float) or not math.isfinite(duration) or not 0 <= duration <= 86400000:
                raise ValueError('invalid recorded formation duration')
            # Wall time is measured data, not reproducible by replaying a log.
            expected['wall_ms'] = duration
        _same(actual, expected, 'trace record')
        self.position += 1
        if expected['stage'] == 'turn_completed':
            self.snapshots.append(deepcopy(expected))

    def run(self, command, scope, payload):
        del scope
        row = self.peek(('action_response', 'observation_response'))
        if row.get('command') != command:
            raise ValueError('formation response command mismatch')
        result = row.get('response')
        if command in ('clock.inject', 'event.inject', 'task.create', 'task.update'):
            _same(result, {}, 'public operation acknowledgement')
        elif command == 'task.inspect':
            if not isinstance(result, dict) or result.get('task_id') != payload['task_id']:
                raise ValueError('inspection response identifies another task')
        elif command == 'evidence.capture':
            if (not isinstance(result, dict) or set(result) != {'evidence_cid', 'content_sha256'}
                    or not isinstance(result['evidence_cid'], str) or not result['evidence_cid']):
                raise ValueError('invalid recorded evidence capture')
            if result['content_sha256'] != hashlib.sha256(payload['content'].encode()).hexdigest():
                raise ValueError('captured evidence content hash differs')
        return deepcopy(result)


class _RecordedProvider:
    def __init__(self, trace, identity):
        self.trace, self.identity = trace, identity

    def complete(self, request):
        del request  # The preceding formation_request was compared exactly.
        row = self.trace.peek(('formation_response',))
        if type(row.get('returncode')) is not int or row['returncode'] != 0:
            raise ValueError('formation trace contains unsuccessful provider output')
        try:
            raw = base64.b64decode(row['stdout_base64'], validate=True)
        except (KeyError, ValueError, TypeError) as error:
            raise ValueError('invalid retained formation output') from error
        return row['returncode'], raw


def _verify_source(source):
    paths = {'eval/public/' + name for name in HARNESS_FILES} | {'eval/harness/cli_driver.py'}
    if (not isinstance(source, dict)
            or set(source) != {'source_commit', 'source_dirty', 'python_version', 'harness_files',
                               'production_runtime_match_verified', 'sink_enabled'}
            or source['sink_enabled'] is not True or source['production_runtime_match_verified'] is not False
            or type(source['source_dirty']) is not bool
            or not isinstance(source['python_version'], str)
            or not isinstance(source['source_commit'], str)
            or re.fullmatch('[0-9a-f]{40}', source['source_commit']) is None
            or not isinstance(source['harness_files'], dict) or set(source['harness_files']) != paths):
        raise ValueError('unsupported formation source receipt')
    root = Path(__file__).resolve().parents[2]
    for name in paths:
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != source['harness_files'][name]:
            raise ValueError('recorded formation source differs from replay checkout')


def _database_rows(path):
    # Always read a private byte snapshot, never initialize/mutate the input DB.
    connection = sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)
    try:
        if (connection.execute('PRAGMA application_id').fetchone()[0] != 0x4D313253
                or connection.execute('PRAGMA user_version').fetchone()[0] != 1
                or connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]):
            raise ValueError('invalid formation sink database')
        return {table: connection.execute(f'SELECT * FROM {table} ORDER BY {order}').fetchall()
                for table, order in (('receipts', 'receipt_id'), ('attempts', 'sequence'))}
    finally:
        connection.close()


def recompute(output):
    """Require the full frozen corpus; return only verified consistency claims."""
    output = Path(output)
    saved = _snapshot(output)
    parsed = {name: _json(raw, name) for name, raw in saved.items() if name.endswith('.json')}
    _verify_source(parsed['source.json'])
    corpus = make_corpus()
    _same(parsed['inputs.json'], {'schema': corpus['schema'],
          'cases': [public_case(case) for case in corpus['cases']]}, 'frozen public inputs')
    _same(parsed['observation-plan.json'], {'schema': 'm12-formation-probes/v1', 'cases': [
        {'case_id': case['public']['case_id'], 'probes': observation_plan(case)}
        for case in corpus['cases']]}, 'fixed observation plan')
    provider = parsed['provider.json']
    if not isinstance(provider, dict) or set(provider) != {
            'identity', 'identity_verified', 'argv', 'timeout_seconds', 'filesystem_isolation_verified', 'publishable'}:
        raise ValueError('invalid formation provider receipt')
    if any(provider[field] is not False for field in ('identity_verified', 'filesystem_isolation_verified', 'publishable')):
        raise ValueError('unsupported formation provider claims')
    if not isinstance(provider['argv'], list):
        raise ValueError('invalid recorded provider command')
    # Validate configuration only. Never invoke the recorded executable.
    CommandFormationProvider(tuple(provider['argv']), provider['identity'], provider['timeout_seconds'])
    lines = saved['operations.jsonl'].splitlines()
    if not lines or len(lines) > 250000 or any(len(line) > 1024 * 1024 for line in lines):
        raise ValueError('formation trace exceeds record bounds or is empty')
    trace = _Trace([_json(line, 'trace record') for line in lines])
    run_id = parsed['observations.json'].get('run_id')
    completed, states, observations, timings = [], [], [], []
    with tempfile.TemporaryDirectory(prefix='m12-formation-replay-') as temp:
        root = Path(temp)
        replay_db = root / 'replay.sqlite3'
        for case in corpus['cases']:
            trace.snapshots.clear()
            completed.append(run_case(case, provider=_RecordedProvider(trace, provider['identity']),
                                      actions=trace, scope={}, emit=trace.emit))
            states.append(score_case(case, trace.snapshots))
            observed = observe_case(case, actions=trace, scope={}, emit=trace.emit,
                                    sink=_sink_for(replay_db, run_id, case['public']['case_id'], 'formation'))
            observations.append(observed)
            timings.append(score_observations(case, observed))
        if trace.position != len(trace.records):
            raise ValueError('unexpected trailing formation trace records')
        original_db = root / 'original.sqlite3'
        original_db.write_bytes(saved['sink.sqlite3'])
        _same(_database_rows(original_db), _database_rows(replay_db), 'durable sink rows')
    _same(parsed['formation-state.json'], {'schema': 'm12-formation-state-report/v1',
          'publishable': False, 'ranking_eligible': False, 'cases': states}, 'stored-state report')
    _same(parsed['formation-timing.json'], {'schema': 'm12-formation-timing-report/v1',
          'publishable': False, 'ranking_eligible': False, 'cases': timings}, 'timing report')
    _same(parsed['observations.json'], {'schema': 'm12-formation-observations/v1', 'run_id': run_id,
          'scored': False, 'publishable': False, 'cases': observations}, 'observations and receipts')
    _same(parsed['execution.json'], {'schema': 'm12-formation-execution/v4', 'track': 'DEVELOPMENT',
          'publishable': False, 'scored': False, 'cases': completed,
          'firing_evaluation': 'development-timing-diagnostic', 'firing_diagnostics': 'formation-timing.json',
          'observations': 'observations.json', 'model_quality': 'not-evaluated',
          'formation_state_diagnostics': 'formation-state.json',
          'scoring_scope': 'descriptive-state-and-timing; full benchmark unscored',
          'filesystem_isolation_verified': False}, 'execution summary')
    _same(parsed['status.json'], {'status': 'completed', 'completed_cases': len(completed),
          'retained_records': len(lines), 'publishable': False, 'scored': False}, 'completion status')
    _verify_source(parsed['source.json'])
    if saved != _snapshot(output):
        raise ValueError('formation artifacts changed during replay')
    return {'schema': 'm12-formation-replay/v1', 'trace_consistency_verified': True,
            'source_files_match_checkout': True, 'cases': len(completed), 'records': len(lines),
            'files': {name: hashlib.sha256(raw).hexdigest() for name, raw in saved.items()},
            'provider_execution_verified': False, 'engine_execution_verified': False,
            'independent_implementation': False, 'publishable': False, 'ranking_eligible': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    print(_canonical(recompute(parser.parse_args().output)).decode(), end='')
