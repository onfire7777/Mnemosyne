from copy import deepcopy

import pytest

from eval.public.action_formation_observe import observation_plan
from eval.public.action_formation_timing import expected_occurrences, score_observations
from eval.public.action_implicit_plan import make_corpus


def fixture(scenario):
    case = next(c for c in make_corpus()['cases'] if c['gold']['scenario'] == scenario)
    observation = {'case_id': case['public']['case_id'], 'ticks': [
        {'evaluated_at': p['now'], 'evaluation_wall_ms': 1, 'queried_channels': [],
         'action_ids': [], 'firing_observations': []} for p in observation_plan(case)]}
    return case, observation


def fire(observation, row, index):
    tick = observation['ticks'][index]
    tick['action_ids'].append(row['action_id'])
    tick['firing_observations'].append({
        'action_id': row['action_id'], 'intention_id': 'test-only', 'occurrence': row['occurrence'],
        'trigger_type': row['trigger_type'], 'due_at': row['due_at'],
        'evaluated_at': tick['evaluated_at'], 'provider_evaluated_at': tick['evaluated_at']})


@pytest.mark.parametrize('scenario,count', [('exact', 1), ('commitment', 1), ('window', 1),
    ('event', 1), ('condition', 1), ('recurrence', 3), ('reschedule', 1),
    ('cancellation', 0), ('ambiguous', 0), ('negative', 0), ('quotation', 0)])
def test_silence_has_expected_misses(scenario, count):
    case, observed = fixture(scenario)
    report = score_observations(case, observed)
    assert report['metrics']['false_negatives'] == count
    assert report['metrics']['true_positives'] == 0
    assert report['publishable'] is report['ranking_eligible'] is False


@pytest.mark.parametrize('scenario', ['event', 'condition'])
def test_only_matching_signal_tick_is_eligible(scenario):
    case, observed = fixture(scenario)
    row = expected_occurrences(case)[0]
    fire(observed, row, 2)  # decoy signal
    report = score_observations(case, observed)
    assert report['metrics']['false_positives'] == 1
    assert report['metrics']['false_negatives'] == 1
    fire(observed, row, 3)
    report = score_observations(case, observed)
    assert report['metrics']['true_positives'] == 1
    assert report['metrics']['false_positives'] == 1
    assert report['duplicate_observations'] == 1


def test_cancelled_and_expired_outputs_are_failures():
    for scenario, index, reason in [('cancellation', 2, 'cancelled'), ('window', 4, 'expired')]:
        case, observed = fixture(scenario)
        fire(observed, expected_occurrences(case)[0], index)
        report = score_observations(case, observed)
        assert report['invalid_observations'][0]['reason'] == reason
        assert report['metrics']['false_positives'] == 1


def test_recurrence_and_extra_occurrence():
    case, observed = fixture('recurrence')
    rows = expected_occurrences(case)
    for row, index in zip(rows, (2, 7, 9), strict=True):
        fire(observed, row, index)
    report = score_observations(case, observed)
    assert report['metrics']['true_positives'] == 3
    assert report['metrics']['false_negatives'] == 0
    extra = {**rows[-1], 'occurrence': 3}
    fire(observed, extra, 11)
    assert score_observations(case, observed)['metrics']['false_positives'] == 1


def test_missing_probe_and_wrong_case_cannot_hide_failures():
    case, observed = fixture('exact')
    incomplete = deepcopy(observed)
    incomplete['ticks'].pop(2)
    with pytest.raises(ValueError, match='probe sequence'):
        score_observations(case, incomplete)
    observed['case_id'] = 'other'
    with pytest.raises(ValueError, match='case mismatch'):
        score_observations(case, observed)


def test_reschedule_uses_final_label_not_original_due():
    case, observed = fixture('reschedule')
    row = expected_occurrences(case)[0]
    assert row['due_at'] == observed['ticks'][5]['evaluated_at']
    fire(observed, row, 2)
    report = score_observations(case, observed)
    assert report['invalid_observations'][0]['reason'] == 'early'
    assert report['metrics']['false_negatives'] == 1
    fire(observed, row, 5)
    assert score_observations(case, observed)['metrics']['true_positives'] == 1


def test_negative_case_cannot_receive_credit_for_unrequested_action():
    case, observed = fixture('negative')
    other, _ = fixture('exact')
    fire(observed, expected_occurrences(other)[0], 2)
    report = score_observations(case, observed)
    assert report['metrics']['false_positives'] == 1
    assert report['metrics']['true_positives'] == 0
    assert len(report['unexpected_observations']) == 1
