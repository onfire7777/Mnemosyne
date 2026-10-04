"""Paired development diagnostics; never a calibrated non-inferiority verdict."""

import argparse
import hashlib
from pathlib import Path
import sys

from eval.public.action_trigger_run import recompute as candidate_recompute
from eval.public.action_reference_run import recompute as reference_recompute
from eval.public.action_recovery_run import recompute as candidate_recovery_recompute
from eval.public.action_reference_recovery import recompute as reference_recovery_recompute
from eval.public.bundle import _canonical, _parse_json

COUNTS = ('true_positives', 'false_positives', 'false_negatives')
RATES = ('precision', 'recall', 'f1')


def _read(path):
    with path.open('rb') as handle:
        value = handle.read(16 * 1024 * 1024 + 1)
    if len(value) > 16 * 1024 * 1024:
        raise ValueError('comparison input exceeds 16 MiB')
    return value


def _snapshot(root):
    return {name: _read(root / name) for name in
            ('plan.json', 'operations.jsonl', 'reports.json', 'sink.json', 'source.json', 'status.json')}


def _pair(candidate, reference):
    metrics = {}
    for field in (*COUNTS, *RATES):
        left, right = candidate['metrics'][field], reference['metrics'][field]
        metrics[field] = {'candidate': left, 'draft_reference': right,
                          'difference': left - right if left is not None and right is not None else None}
    return {'metrics': metrics,
            'candidate_duplicate_observations': candidate['duplicate_observations'],
            'reference_duplicate_observations': reference['duplicate_observations'],
            'candidate_no_observed_opportunity': candidate['no_observed_opportunity'],
            'reference_no_observed_opportunity': reference['no_observed_opportunity']}


def compare(candidate_dir, reference_dir):
    candidate_dir, reference_dir = Path(candidate_dir), Path(reference_dir)
    before = (_snapshot(candidate_dir), _snapshot(reference_dir))
    candidate_plan = _parse_json(before[0]['plan.json'].decode(), 'candidate plan')
    if not isinstance(candidate_plan, dict):
        raise ValueError('candidate plan must be an object')
    recovery = candidate_plan.get('schema') == 'm12-operation-recovery-run/v1'
    candidate = (candidate_recovery_recompute if recovery else candidate_recompute)(candidate_dir)
    reference = (reference_recovery_recompute if recovery else reference_recompute)(reference_dir)
    if before != (_snapshot(candidate_dir), _snapshot(reference_dir)):
        raise ValueError('comparison artifacts changed during replay')
    plans = [_parse_json(snapshot['plan.json'].decode(), 'plan') for snapshot in before]
    if _canonical(plans[0]) != _canonical(plans[1]):
        raise ValueError('candidate and reference workloads differ')
    source = _parse_json(before[0]['source.json'].decode(), 'source')
    if 'reference_id' in source or source.get('sink_enabled') is not True:
        raise ValueError('candidate requires its own sink-enabled execution')
    cases = []
    reference_cases = reference['workload']['cases']
    if [row['case_id'] for row in candidate['cases']] != [row['case_id'] for row in reference_cases]:
        raise ValueError('candidate and reference cases differ')
    for left, right in zip(candidate['cases'], reference_cases, strict=True):
        paired = {'case_id': left['case_id'], **_pair(left['report'], right['report'])}
        if recovery:
            paired['recovery_operations'] = {
                field: {'candidate': left[field], 'draft_reference': right[field]}
                for field in ('injected_response_losses', 'adapter_resets')
            }
        if 'by_load' in left:
            paired['by_load'] = []
            for a, b in zip(left['by_load'], right['by_load'], strict=True):
                if (a['week'], a['fanout_per_trigger']) != (b['week'], b['fanout_per_trigger']):
                    raise ValueError('load phases differ')
                paired['by_load'].append({'week': a['week'], 'fanout_per_trigger': a['fanout_per_trigger'],
                                           **_pair(a['report'], b['report'])})
        cases.append(paired)
    return {'schema': 'm12-paired-development-diagnostic/v1', 'track': 'DEVELOPMENT',
            'publishable': False, 'baseline_admitted': False, 'ranking_eligible': False,
            'non_inferiority_evaluated': False, 'reference_id': reference['reference_id'],
            'workload_sha256': hashlib.sha256(_canonical(plans[0])).hexdigest(),
            'input_sha256': {role: {name: hashlib.sha256(data).hexdigest() for name, data in snapshot.items()}
                             for role, snapshot in zip(('candidate', 'draft_reference'), before, strict=True)},
            'limitations': [
                'Same deterministic requests; not matched runtime, deployment or resource boundaries.',
                'Differences are descriptive; no confidence interval, calibrated floor or non-inferiority margin.',
                'Candidate subprocess and reference in-process timing are excluded from comparison.',
                'Replay validates consistency, not independent authentication or reproduction.',
            ], 'cases': cases}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('reference', type=Path)
    args = parser.parse_args()
    try:
        result = compare(args.candidate, args.reference)
    except Exception as error:
        print(f'Comparison failed: {type(error).__name__}', file=sys.stderr)
        raise SystemExit(1) from None
    print(_canonical(result).decode(), end='')
