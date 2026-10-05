from copy import deepcopy

import pytest

from eval.harness.cli_driver import MnemoCLI
from eval.public.action_cli import ActionCLI, ActionCLIError
from eval.public.action_formation_scoring import score_case


DUE = '2030-01-01T00:00:00Z'


def fixture():
    return {'public': {'case_id': 'case'}, 'gold': {'case_id': 'case', 'turns': [
        {'turn_id': '0', 'decision': 'form', 'active_schedules': [
            {'action_id': 'action', 'trigger': {'type': 'exact_time', 'payload': {'at': DUE}},
             'recurrence_policy': None},
        ]},
    ]}}


def task():
    return {'task_id': 'task', 'intention_id': 'intention', 'revision': 'a' * 64,
            'status': 'scheduled', 'action_id': 'action', 'schedule': {
                'trigger_type': 'exact_time', 'trigger_expression': {'at': DUE}, 'due_at': DUE,
                'dependencies': [], 'recurrence_policy': {'type': 'none'},
                'recurrence_state': {'occurrence': 0}, 'evidence_ids': ['evidence'],
            }}


def snapshot(tasks, question=None):
    return {'stage': 'turn_completed', 'case_id': 'case', 'turn': 0, 'tasks': tasks, 'clarification': question}


def test_equivalent_timezone_spellings_match_but_different_stored_due_time_does_not():
    observed = task()
    observed['schedule']['due_at'] = '2029-12-31T19:00:00-05:00'
    observed['schedule']['trigger_expression']['at'] = '2029-12-31T19:00:00-05:00'
    report = score_case(fixture(), [snapshot([observed])])
    assert report['turns'][0]['state_exact_match'] is True
    assert report['publishable'] is report['ranking_eligible'] is False
    observed['schedule']['due_at'] = '2030-01-01T01:00:00Z'
    row = score_case(fixture(), [snapshot([observed])])['turns'][0]
    assert (row['true_positives'], row['false_positives'], row['false_negatives']) == (0, 1, 1)


def test_distinct_duplicate_intentions_are_extra_schedules_not_deduplicated():
    first, second = task(), task()
    second.update(task_id='second-task', intention_id='second-intention')
    row = score_case(fixture(), [snapshot([first, second])])['turns'][0]
    assert (row['true_positives'], row['false_positives'], row['false_negatives']) == (1, 1, 0)
    assert row['state_exact_match'] is False
    with pytest.raises(ValueError, match='duplicate identity'):
        score_case(fixture(), [snapshot([first, deepcopy(first)])])


def test_nested_boolean_number_matching_is_strict_and_not_inferred_from_product():
    case, observed = fixture(), task()
    case['gold']['turns'][0]['active_schedules'][0]['trigger'] = {
        'type': 'event', 'payload': {'event_type': 'ready', 'match': {'nested': {'on': True}}, 'due_at': DUE}}
    observed['schedule'].update(trigger_type='event', trigger_expression={'event_type': 'ready', 'match': {'nested': {'on': 1}}})
    row = score_case(case, [snapshot([observed])])['turns'][0]
    assert (row['true_positives'], row['false_positives'], row['false_negatives']) == (0, 1, 1)


def test_cancelled_fired_and_advanced_recurrence_states_are_distinct():
    case, observed = fixture(), task()
    case['gold']['turns'][0].update(decision='cancel', active_schedules=[])
    observed['status'] = 'cancelled'
    assert score_case(case, [snapshot([observed])])['turns'][0]['state_exact_match'] is True
    observed['status'] = 'fired'
    row = score_case(case, [snapshot([observed])])['turns'][0]
    assert row['state_exact_match'] is False
    assert row['premature_fired_tasks'] == 1
    observed = task()
    observed['schedule']['recurrence_state']['occurrence'] = 1
    row = score_case(fixture(), [snapshot([observed])])['turns'][0]
    assert row['true_positives'] == 1
    assert row['state_exact_match'] is False
    assert row['observed_occurrence_advances'] == 1


def test_clarification_presence_does_not_claim_semantic_correctness():
    case = fixture()
    case['gold']['turns'][0].update(decision='clarify', active_schedules=[])
    row = score_case(case, [snapshot([], 'An irrelevant question?')])['turns'][0]
    assert row['clarification_expected'] is row['clarification_present'] is True
    assert row['clarification_semantics'] == 'not-evaluated'
    assert score_case(case, [snapshot([])])['turns'][0]['clarification_present'] is False


def test_incomplete_or_misaligned_snapshots_are_not_zero_scores():
    with pytest.raises(ValueError, match='turn count'):
        score_case(fixture(), [])
    wrong = snapshot([task()])
    wrong['turn'] = True
    with pytest.raises(ValueError, match='ordered'):
        score_case(fixture(), [wrong])
    missing = task()
    del missing['schedule']
    with pytest.raises(ValueError, match='full public schedule'):
        score_case(fixture(), [snapshot([missing])])


@pytest.mark.parametrize('kind,payload,policy', [
    ('exact_time', {'at': DUE}, None),
    ('time_window', {'start': DUE, 'end': '2030-01-01T01:00:00Z'}, None),
    ('event', {'event_type': 'ready', 'match': {'status': 'ok'}, 'due_at': DUE}, None),
    ('condition', {'condition_id': 'ready', 'operator': 'eq', 'value': True, 'due_at': DUE}, None),
    ('exact_time', {'at': DUE}, {'type': 'interval', 'interval_seconds': 604800, 'max_occurrences': 3}),
])
def test_actual_public_inspection_preserves_legacy_shape_and_supplies_stored_schedule(tmp_path, kind, payload, policy):
    actions = ActionCLI(MnemoCLI(store='unused', timeout_s=30))
    scope = {'store': str(tmp_path / 'memory.json'), 'tenant_id': 'tenant', 'session_id': 'session'}
    trigger = {'type': kind, 'payload': payload}
    request = {'task_id': 'task', 'action_id': 'action', 'trigger': trigger}
    if policy is not None:
        request['recurrence_policy'] = policy
    actions.run('task.create', scope, request)
    before = actions.run('task.inspect', scope, {'task_id': 'task'})
    full = actions.run('task.inspect', scope, {'task_id': 'task', 'include_schedule': True})
    assert set(before) == {'task_id', 'intention_id', 'revision', 'status', 'action_id'}
    assert {k: v for k, v in full.items() if k != 'schedule'} == before
    assert full['schedule']['evidence_ids']
    expected = fixture()
    expected['gold']['turns'][0]['active_schedules'][0].update(trigger=trigger, recurrence_policy=policy)
    assert score_case(expected, [snapshot([full])])['turns'][0]['state_exact_match'] is True
    with pytest.raises(ActionCLIError, match='boolean'):
        actions.run('task.inspect', scope, {'task_id': 'task', 'include_schedule': 1})
