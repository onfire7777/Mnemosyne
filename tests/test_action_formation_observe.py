from copy import deepcopy
from datetime import datetime

import pytest

from eval.public.action_formation_observe import observation_plan, observe_case
from eval.public.action_implicit_plan import make_corpus


def test_probes_do_not_depend_on_labels_or_candidate_schedule():
    case = make_corpus()['cases'][0]
    expected = observation_plan(case)
    del case['gold']
    assert observation_plan(case) == expected
    start = datetime.fromisoformat(case['public']['turns'][0]['now'])
    assert [(datetime.fromisoformat(p['now']) - start).total_seconds() for p in expected] == [
        120, 3599, 3600, 3601, 7200, 10800, 10801,
        608400, 608401, 1213200, 1213201, 1818000]
    assert expected[2]['signals'][0]['payload'] == {'status': 'pending'}
    assert expected[2]['signals'][1]['value'] is False
    assert expected[3]['signals'][0]['payload'] == {'status': 'ready'}
    assert expected[3]['signals'][1]['value'] is True
    assert sum(bool(p['signals']) for p in expected) == 2


def test_overlapping_turns_fail_instead_of_moving_clock_backwards():
    case = deepcopy(make_corpus()['cases'][0])
    case['public']['turns'][-1]['now'] = '2099-01-01T00:00:00Z'
    # Keep the first turn separate when this fixture has only one turn.
    case['public']['turns'].insert(0, {'now': '2030-01-01T00:00:00Z'})
    with pytest.raises(ValueError, match='overlap'):
        observation_plan(case)


def test_failed_evidence_write_prevents_observation_calls():
    class Actions:
        def run(self, *args):
            pytest.fail('must retain request before any public operation')

    def fail(record):
        raise OSError('disk full')

    with pytest.raises(OSError, match='disk full'):
        observe_case(make_corpus()['cases'][0], actions=Actions(), scope={}, sink=None, emit=fail)


def test_real_public_firing_reaches_durable_inert_sink(tmp_path):
    from eval.harness.cli_driver import MnemoCLI
    from eval.public.action_cli import ActionCLI
    from eval.public.action_timing_run import _sink_for

    case = make_corpus()['cases'][0]
    identity = case['public']['case_id']
    scope = {'store': str(tmp_path / 'store.json'), 'tenant_id': identity, 'session_id': 'formation'}
    actions = ActionCLI(MnemoCLI(store='unused', timeout_s=30))
    due = observation_plan(case)[2]['now']
    # Explicit setup tests execution plumbing only, never model formation.
    actions.run('task.create', scope, {
        'task_id': 'plumbing-only', 'action_id': case['public']['actions'][0]['action_id'],
        'trigger': {'type': 'exact_time', 'payload': {'at': due}}})
    sink = _sink_for(tmp_path / 'sink.sqlite3', 'test-run', identity, 'formation')
    records = []
    result = observe_case(case, actions=actions, scope=scope, sink=sink, emit=records.append)
    firings = [f for tick in result['ticks'] for f in tick['firing_observations']]
    assert len(firings) == 1
    assert result['ticks'][2]['firing_observations'] == firings
    assert result['scored'] is False
    assert result['sink'] == sink.snapshot()
    assert len(result['sink']['receipts']) == 1
    assert len(result['sink']['attempts']) == 2
