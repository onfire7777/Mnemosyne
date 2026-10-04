from pathlib import Path
import shutil

import pytest

from eval.public import action_comparison

REPORTS = Path(__file__).resolve().parents[1] / 'eval/reports'


@pytest.mark.parametrize('candidate,reference,loads', [
    ('m12-trigger-sink-development-2026-10-04', 'm12-reference-explicit-development-2026-10-04', False),
    ('m12-fanout-sink-development-2026-10-04', 'm12-reference-fanout-development-2026-10-04', True),
])
def test_paired_capture_replay_preserves_cases_loads_and_no_ranking(candidate, reference, loads):
    result = action_comparison.compare(REPORTS / candidate, REPORTS / reference)
    assert len(result['cases']) == 5
    assert result['ranking_eligible'] is result['non_inferiority_evaluated'] is False
    assert result['publishable'] is result['baseline_admitted'] is False
    for case in result['cases']:
        assert all(row['difference'] == 0 for row in case['metrics'].values())
        assert ('by_load' in case) == loads
        if loads:
            assert [row['fanout_per_trigger'] for row in case['by_load']] == [2, 4, 8, 16]
    assert set(result['input_sha256']) == {'candidate', 'draft_reference'}
    assert 'latency' not in result


def test_different_valid_workloads_cannot_be_compared():
    with pytest.raises(ValueError, match='workloads differ'):
        action_comparison.compare(REPORTS / 'm12-trigger-sink-development-2026-10-04',
                                  REPORTS / 'm12-reference-fanout-development-2026-10-04')


def test_changes_during_replay_are_rejected(tmp_path, monkeypatch):
    candidate = tmp_path / 'candidate'
    shutil.copytree(REPORTS / 'm12-trigger-sink-development-2026-10-04', candidate)
    original = action_comparison.candidate_recompute
    def changed(root):
        result = original(root)
        with (root / 'source.json').open('a') as handle:
            handle.write('\n')
        return result
    monkeypatch.setattr(action_comparison, 'candidate_recompute', changed)
    with pytest.raises(ValueError, match='changed during replay'):
        action_comparison.compare(candidate, REPORTS / 'm12-reference-explicit-development-2026-10-04')


def test_undefined_rates_stay_undefined_and_difference_is_signed():
    candidate = {'metrics': dict(true_positives=1, false_positives=2, false_negatives=0,
                                precision=1 / 3, recall=None, f1=None),
                 'duplicate_observations': 2, 'no_observed_opportunity': 3}
    reference = {**candidate, 'metrics': {**candidate['metrics'], 'false_positives': 0, 'precision': 1}}
    result = action_comparison._pair(candidate, reference)
    assert result['metrics']['false_positives']['difference'] == 2
    assert result['metrics']['precision']['difference'] < 0
    assert result['metrics']['recall']['difference'] is None


@pytest.mark.parametrize('name,candidate', [
    ('explicit', 'm12-trigger-sink-development-2026-10-04'),
    ('fanout', 'm12-fanout-sink-development-2026-10-04'),
])
def test_retained_paired_reports_reproduce_exact_bytes(name, candidate):
    from eval.public.bundle import _canonical

    result = action_comparison.compare(REPORTS / candidate,
                                       REPORTS / f'm12-reference-{name}-development-2026-10-04')
    assert _canonical(result) == (REPORTS / 'm12-paired-development-2026-10-04' / f'{name}.json').read_bytes()
