"""Coverage and partial diagnostics for failed formation attempts, never ranks.

This validates frozen inputs and recomputes completed-prefix diagnostics. It
is not complete protocol replay or authentication of provider/engine execution.
"""

import argparse
import hashlib
from pathlib import Path

from eval.public.action_formation_observe import observation_plan
from eval.public.action_formation_scoring import score_case
from eval.public.action_formation_timing import score_observations
from eval.public.action_implicit_plan import make_corpus, public_case
from eval.public.action_formation_replay import _json, _read, _same
from eval.public.bundle import _canonical


def summarize(output):
    output = Path(output)
    names = ('inputs.json', 'source.json', 'status.json', 'operations.jsonl')
    saved = {name: _read(output / name) for name in names}
    if sum(map(len, saved.values())) > 128 * 1024 * 1024:
        raise ValueError('failed formation artifacts exceed aggregate size bound')
    status = _json(saved['status.json'], 'failed status')
    if (not isinstance(status, dict) or set(status) != {
            'status', 'exception_type', 'completed_cases', 'retained_records', 'publishable', 'scored'}
            or status['status'] != 'failed' or status['publishable'] is not False or status['scored'] is not False
            or not isinstance(status['exception_type'], str) or not status['exception_type']
            or type(status['completed_cases']) is not int or type(status['retained_records']) is not int):
        raise ValueError('expected a failed formation completion record')
    corpus = make_corpus()
    cases = corpus['cases']
    count = status['completed_cases']
    if not 0 <= count <= len(cases):
        raise ValueError('invalid completed case count')
    _same(_json(saved['inputs.json'], 'inputs'), {'schema': corpus['schema'],
          'cases': [public_case(case) for case in cases]}, 'frozen public inputs')
    source = _json(saved['source.json'], 'source')
    # Later transport fixes do not invalidate interpretation of archived public
    # inputs/ticks. Require the actual corpus and diagnostic dependencies to match.
    dependencies = ('action_implicit_plan.py', 'action_formation_scoring.py', 'action_formation_timing.py',
                    'action_formation_observe.py', 'action_trigger_timing.py', 'action_timing.py')
    for name in dependencies:
        digest = hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        if source.get('harness_files', {}).get('eval/public/' + name) != digest:
            raise ValueError('archived diagnostic source differs from this analyzer')
    lines = saved['operations.jsonl'].splitlines()
    if len(lines) > 250000 or any(len(line) > 1024 * 1024 for line in lines):
        raise ValueError('failed formation trace exceeds bounds')
    records = [_json(line, 'trace record') for line in lines]
    if len(records) != status['retained_records']:
        raise ValueError('retained record count differs')
    by_id = {case['public']['case_id']: index for index, case in enumerate(cases)}
    grouped = [[] for _ in cases]
    previous = 0
    for record in records:
        if not isinstance(record, dict) or record.get('case_id') not in by_id:
            raise ValueError('unknown case in failed trace')
        index = by_id[record['case_id']]
        if index < previous or index > previous + 1 or index > count:
            raise ValueError('failed trace is not an ordered attempted prefix')
        if not grouped[0] and index != 0:
            raise ValueError('failed trace omitted its first case')
        previous = index
        grouped[index].append(record)
    results = []
    for index, case in enumerate(cases):
        rows = grouped[index]
        result = {'case_id': case['public']['case_id'], 'retained_records': len(rows)}
        if index < count:
            if any(str(row.get('stage', '')).endswith('_error') for row in rows):
                raise ValueError('completed case contains an error')
            snapshots = [row for row in rows if row.get('stage') == 'turn_completed']
            ticks = [row['response'] for row in rows if row.get('stage') == 'observation_response'
                     and row.get('command') == 'intention.observe']
            probes = [row.get('probe') for row in rows if row.get('stage') == 'observation_response'
                      and row.get('command') == 'intention.observe']
            if (any(type(probe) is not int for probe in probes)
                    or probes != list(range(len(observation_plan(case))))):
                raise ValueError('completed case has incomplete observation probes')
            result.update(status='completed', state=score_case(case, snapshots),
                          timing=score_observations(case, {'case_id': result['case_id'], 'ticks': ticks}))
        elif rows:
            result.update(status='incomplete', last_recorded_stage=rows[-1].get('stage'),
                          diagnostics=None)
        else:
            result.update(status='not_attempted', diagnostics=None)
        results.append(result)
    if saved != {name: _read(output / name) for name in names}:
        raise ValueError('failed formation artifacts changed during analysis')
    return {'schema': 'm12-failed-formation-coverage/v1', 'status': 'failed',
            'exception_type': status['exception_type'], 'planned_cases': len(cases),
            'completed_cases': count, 'incomplete_cases': sum(r['status'] == 'incomplete' for r in results),
            'not_attempted_cases': sum(r['status'] == 'not_attempted' for r in results),
            'cases': results, 'full_corpus_score': None, 'publishable': False, 'ranking_eligible': False,
            'trace_consistency_verified': False, 'provider_execution_verified': False,
            'selection': 'all planned cases; diagnostics only for completed prefix',
            'files': {name: hashlib.sha256(raw).hexdigest() for name, raw in saved.items()}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    print(_canonical(summarize(parser.parse_args().output)).decode(), end='')
