"""Retain formation execution and descriptive state checks, not benchmark ranks."""

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid

from eval.harness.cli_driver import MnemoCLI
from eval.public.action_cli import ActionCLI
from eval.public.action_formation import CommandFormationProvider, run_case
from eval.public.action_formation_scoring import score_case
from eval.public.action_formation_observe import observation_plan, observe_case
from eval.public.action_implicit_plan import make_corpus, public_case
from eval.public.action_timing_run import _source_receipt, _write, _sink_for
from eval.public.bundle import _canonical


def run_development(output, provider):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    corpus = make_corpus()
    public = [public_case(case) for case in corpus['cases']]
    _write(output / 'inputs.json', {'schema': corpus['schema'], 'cases': public})
    _write(output / 'provider.json', {
        'identity': provider.identity, 'identity_verified': False,
        'argv': list(provider.argv), 'timeout_seconds': provider.timeout_seconds,
        'filesystem_isolation_verified': False, 'publishable': False,
    })
    source = _source_receipt(True)
    for name in ('action_formation.py', 'action_formation_run.py', 'action_implicit_plan.py',
                 'action_formation_scoring.py', 'action_formation_observe.py'):
        source['harness_files']['eval/public/' + name] = hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
    _write(output / 'source.json', source)
    completed, diagnostics, snapshots, observations, records = [], [], [], [], 0
    run_id = str(uuid.uuid4())
    _write(output / 'observation-plan.json', {
        'schema': 'm12-formation-probes/v1', 'cases': [
            {'case_id': case['public']['case_id'], 'probes': observation_plan(case)}
            for case in corpus['cases']]})
    try:
        with (output / 'operations.jsonl').open('xb') as log, \
                tempfile.TemporaryDirectory(prefix='m12-formation-') as temp:
            def emit(record):
                nonlocal records
                log.write(_canonical(record))
                log.flush()
                os.fsync(log.fileno())
                records += 1
                if record['stage'] == 'turn_completed':
                    snapshots.append(deepcopy(record))

            for case in corpus['cases']:
                snapshots.clear()
                identity = case['public']['case_id']
                # Isolate harness task maps and stores per case. This does not
                # attest isolation inside the separately configured provider.
                actions = ActionCLI(MnemoCLI(store='unused', timeout_s=30))
                scope = {'store': str(Path(temp) / (identity + '.json')),
                         'tenant_id': identity, 'session_id': 'formation'}
                formation = run_case(
                    case, provider=provider, actions=actions,
                    scope=scope, emit=emit,
                )
                diagnostics.append(score_case(case, snapshots))
                observations.append(observe_case(
                    case, actions=actions, scope=scope,
                    sink=_sink_for(output / 'sink.sqlite3', run_id, identity, 'formation'), emit=emit))
                completed.append(formation)
    except BaseException as error:
        _write(output / 'status.json', {
            'status': 'failed', 'exception_type': type(error).__name__,
            'completed_cases': len(completed), 'retained_records': records,
            'publishable': False, 'scored': False,
        })
        raise
    _write(output / 'formation-state.json', {
        'schema': 'm12-formation-state-report/v1', 'publishable': False,
        'ranking_eligible': False, 'cases': diagnostics,
    })
    _write(output / 'observations.json', {
        'schema': 'm12-formation-observations/v1', 'run_id': run_id,
        'scored': False, 'publishable': False, 'cases': observations})
    result = {'schema': 'm12-formation-execution/v3', 'track': 'DEVELOPMENT',
              'publishable': False, 'scored': False, 'cases': completed,
              'firing_evaluation': 'observed-unscored', 'observations': 'observations.json', 'model_quality': 'not-evaluated',
              'formation_state_diagnostics': 'formation-state.json',
              'scoring_scope': 'descriptive-active-state-only; full benchmark unscored',
              'filesystem_isolation_verified': False}
    _write(output / 'execution.json', result)
    _write(output / 'status.json', {'status': 'completed', 'completed_cases': len(completed),
                                  'retained_records': records, 'publishable': False, 'scored': False})
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--provider-identity', required=True)
    parser.add_argument('--timeout-seconds', type=float, default=30)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    provider = CommandFormationProvider(tuple(command), args.provider_identity, args.timeout_seconds)
    result = run_development(args.output, provider)
    print(json.dumps({'status': 'completed', 'cases': len(result['cases']), 'scored': False}))
