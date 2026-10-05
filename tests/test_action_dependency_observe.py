from copy import deepcopy

import pytest

from eval.harness.cli_driver import MnemoCLI
from eval.public.action_cli import ActionCLI
from eval.public.action_dependency_plan import make_corpus, observation_plan, SCENARIOS
from eval.public.action_dependency_observe import observe_case, score_observations
from eval.public.action_timing_run import _sink_for


@pytest.mark.parametrize('scenario', SCENARIOS)
def test_public_dependency_execution_cancellation_and_duplicate_probes(tmp_path, scenario):
    case = next(c for c in make_corpus()['cases'] if c['gold']['scenario'] == scenario)
    identity = case['public']['case_id']
    scope = {'store': str(tmp_path / 'store.json'), 'tenant_id': identity, 'session_id': 'dependency'}
    actions = ActionCLI(MnemoCLI(store='unused', timeout_s=30))
    known = {}
    # Explicit golden setup is a storage/observation integration test, never a model run.
    for turn in case['gold']['turns']:
        current = {s['action_id']: s for s in turn['active_schedules']}
        for action, schedule in current.items():
            if action not in known:
                actions.run('task.create', scope, {'task_id': action, 'action_id': action,
                    'trigger': schedule['trigger'], 'dependency_ids': schedule['dependency_action_ids']})
        for action in known.keys() - current.keys():
            actions.run('task.update', scope, {'task_id': action, 'type': 'cancel'})
        known = current
    sink = _sink_for(tmp_path / 'sink.sqlite3', 'test-run', identity, 'dependency')
    records = []
    public_only = deepcopy(case)
    del public_only['gold']
    observation = observe_case(public_only, actions=actions, scope=scope, sink=sink, emit=records.append)
    report = score_observations(case, observation)
    count = len(case['gold']['expected_firings'])
    assert report['metrics']['true_positives'] == count
    assert report['metrics']['false_positives'] == report['metrics']['false_negatives'] == 0
    assert len(observation['sink']['receipts']) == count
    assert len(observation['sink']['attempts']) == 2 * count
    assert len(records) == 24
    assert [t['evaluated_at'] for t in observation['ticks']] == observation_plan(case)
    assert observation['ticks'][2]['firing_observations'] == []
    assert observation['ticks'][4]['firing_observations'] == []
    assert report['ranking_eligible'] is report['trace_replay_verified'] is False
    altered = deepcopy(observation)
    altered['ticks'].pop()
    with pytest.raises(ValueError, match='probe sequence'):
        score_observations(case, altered)


def test_request_retention_failure_stops_before_public_execution():
    class Actions:
        def run(self, *args):
            pytest.fail('no operation before retained request')
    def fail(record):
        raise OSError('disk full')
    with pytest.raises(OSError):
        observe_case(make_corpus()['cases'][0], actions=Actions(), scope={}, sink=None, emit=fail)


@pytest.mark.parametrize('scenario', ['unsatisfied', 'cancel_dependent', 'cancel_prerequisite', 'unrelated_completion'])
def test_blocked_or_cancelled_dependency_firing_is_false_positive(scenario):
    case = next(c for c in make_corpus()['cases'] if c['gold']['scenario'] == scenario)
    dependent = case['gold']['turns'][1]['active_schedules'][1]
    ticks = [{'action_ids': [], 'queried_channels': [], 'evaluated_at': now,
              'evaluation_wall_ms': 0, 'firing_observations': []} for now in observation_plan(case)]
    target = ticks[3]
    target['action_ids'] = [dependent['action_id']]
    target['firing_observations'] = [{'action_id': dependent['action_id'], 'intention_id': 'test-only',
        'occurrence': 0, 'trigger_type': 'dependency_completion',
        'due_at': dependent['trigger']['payload']['due_at'], 'evaluated_at': target['evaluated_at'],
        'provider_evaluated_at': target['evaluated_at']}]
    report = score_observations(case, {'case_id': case['public']['case_id'], 'ticks': ticks})
    assert report['metrics']['false_positives'] == 1
    assert report['metrics']['true_positives'] == 0


def test_overlapping_formation_turns_cannot_move_observation_clock_backwards():
    case = make_corpus()['cases'][0]
    case['public']['turns'][-1]['now'] = observation_plan(case)[-1]
    with pytest.raises(ValueError, match='overlap'):
        observe_case(case, actions=None, scope={}, sink=None, emit=lambda record: None)
