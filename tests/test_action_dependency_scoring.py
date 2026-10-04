from copy import deepcopy

import pytest

from eval.public.action_dependency_plan import make_corpus
from eval.public.action_dependency_scoring import score_case
from tests.test_action_formation_scoring import task


def fixture():
    case = next(c for c in make_corpus()['cases'] if c['gold']['scenario'] == 'satisfied')
    first, dependent = case['gold']['turns'][1]['active_schedules']
    prerequisite = task()
    prerequisite.update(task_id='prerequisite', intention_id='opaque-A', action_id=first['action_id'])
    prerequisite['schedule'].update(trigger_expression=first['trigger']['payload'], due_at=first['trigger']['payload']['at'])
    follow = task()
    follow.update(task_id='follow', intention_id='opaque-B', action_id=dependent['action_id'])
    follow['schedule'].update(trigger_type='dependency_completion', trigger_expression={'require': 'all'},
                              due_at=dependent['trigger']['payload']['due_at'], dependencies=['opaque-A'])
    snapshots = [{'stage': 'turn_completed', 'case_id': case['public']['case_id'], 'turn': i,
                  'tasks': deepcopy(tasks), 'clarification': None}
                 for i,tasks in enumerate(([prerequisite], [prerequisite, follow]))]
    return case, snapshots


def test_dependency_matches_through_opaque_public_identity_not_task_name():
    case, snapshots = fixture()
    result = score_case(case, snapshots)
    assert all(row['state_exact_match'] for row in result['turns'])
    assert result['turns'][1]['true_positives'] == 2
    assert result['publishable'] is result['ranking_eligible'] is False
    snapshots[1]['tasks'][0]['intention_id'] = 'different-opaque'
    snapshots[1]['tasks'][1]['schedule']['dependencies'] = ['different-opaque']
    assert score_case(case, snapshots)['turns'][1]['state_exact_match']


@pytest.mark.parametrize('damage', ['timer', 'missing', 'self', 'duplicate'])
def test_wrong_or_ambiguous_prerequisite_is_not_credit(damage):
    case, snapshots = fixture()
    tasks = snapshots[1]['tasks']
    if damage == 'timer':
        schedule = tasks[1]['schedule']
        schedule.update(trigger_type='exact_time', trigger_expression={'at': schedule['due_at']}, dependencies=[])
    elif damage == 'missing':
        tasks[1]['schedule']['dependencies'] = []
    elif damage == 'self':
        tasks[1]['schedule']['dependencies'] = ['opaque-B']
    else:
        duplicate = deepcopy(tasks[0])
        duplicate.update(task_id='duplicate', intention_id='opaque-C')
        tasks.append(duplicate)
    row = score_case(case, snapshots)['turns'][1]
    assert not row['state_exact_match']
    assert row['false_negatives'] >= 1 and row['false_positives'] >= 1


def test_unknown_dependency_is_incomplete_evidence():
    case, snapshots = fixture()
    snapshots[1]['tasks'][1]['schedule']['dependencies'] = ['unseen']
    with pytest.raises(ValueError, match='absent'):
        score_case(case, snapshots)


def test_cancelled_prerequisite_still_resolves_without_being_active():
    case, snapshots = fixture()
    case['gold']['turns'][1]['active_schedules'].pop(0)
    snapshots[1]['tasks'][0]['status'] = 'cancelled'
    assert score_case(case, snapshots)['turns'][1]['state_exact_match']


def test_real_public_dependency_inspection_matches_extension_labels(tmp_path):
    from eval.harness.cli_driver import MnemoCLI
    from eval.public.action_cli import ActionCLI

    case, _ = fixture()
    actions = ActionCLI(MnemoCLI(store='unused', timeout_s=30))
    scope = {'store': str(tmp_path / 'memory.json'), 'tenant_id': 'tenant', 'session_id': 'session'}
    expected = case['gold']['turns'][1]['active_schedules']
    snapshots = []
    for index, (name, schedule) in enumerate(zip(('first', 'second'), expected, strict=True)):
        # This is a public storage conformance fixture, not a model provider.
        payload = {'task_id': name, 'action_id': schedule['action_id'], 'trigger': schedule['trigger']}
        if index:
            payload['dependency_ids'] = ['first']
        actions.run('task.create', scope, payload)
        stored = [actions.run('task.inspect', scope, {'task_id': task_id, 'include_schedule': True})
                  for task_id in ('first', 'second')[:index + 1]]
        snapshots.append({'stage': 'turn_completed', 'case_id': case['public']['case_id'],
                          'turn': index, 'tasks': stored, 'clarification': None})
    assert snapshots[1]['tasks'][1]['schedule']['dependencies'] == [snapshots[1]['tasks'][0]['intention_id']]
    assert all(row['state_exact_match'] for row in score_case(case, snapshots)['turns'])
