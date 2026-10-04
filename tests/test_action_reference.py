from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from eval.public.action_reference import ExplicitActionReference
from eval.public.action_trigger_run import make_plan
from eval.public.action_fanout_plan import make_fanout_plan


def stamp(second):
    return (datetime(2030, 1, 1, tzinfo=UTC) + timedelta(seconds=second)).isoformat()


def task(name='a', kind='exact_time', spec=None, **extra):
    return {'task_id': name, 'action_id': name, 'idempotency_key': name,
            'trigger': {'type': kind, 'payload': spec or {'at': stamp(10)}}, **extra}


def observe(reference, at):
    reference.run('clock.inject', {'now': stamp(at)})
    return reference.run('intention.observe', {})['firing_observations']


def test_late_poll_preserves_due_and_recurring_occurrences_without_repeated_fire():
    ref = ExplicitActionReference()
    value = task(recurrence_policy={'type': 'interval', 'interval_seconds': 10, 'max_occurrences': 2})
    ref.run('task.create', value)
    assert observe(ref, 9) == []
    fired = observe(ref, 12)
    assert fired[0]['due_at'] == stamp(10)
    assert fired[0]['occurrence'] == 0
    ref.run('task.create', value)
    assert observe(ref, 12) == []
    assert observe(ref, 20)[0]['occurrence'] == 1
    assert observe(ref, 30) == []


def test_cancel_is_not_undone_by_creation_retry():
    ref = ExplicitActionReference()
    value = task()
    ref.run('task.create', value)
    ref.run('task.update', {'type': 'cancel', 'task_id': 'a'})
    ref.run('task.create', value)
    assert observe(ref, 10) == []
    changed = deepcopy(value)
    changed['action_id'] = 'changed'
    with pytest.raises(ValueError, match='conflict'):
        ref.run('task.create', changed)


def test_window_end_is_exclusive_and_dependency_uses_previous_tick():
    ref = ExplicitActionReference()
    ref.run('task.create', task('window', 'time_window', {'start': stamp(5), 'end': stamp(10)}))
    ref.run('task.create', task('parent'))
    ref.run('task.create', task('child', 'dependency_completion', {'due_at': stamp(10)}, dependency_ids=['parent']))
    assert [x['action_id'] for x in observe(ref, 10)] == ['parent']
    assert [x['action_id'] for x in observe(ref, 10)] == ['child']


def test_signals_use_strict_json_values_and_are_consumed_per_tick():
    ref = ExplicitActionReference()
    ref.run('task.create', task('event', 'event', {'event_type': 'ready', 'match': {'ok': True}, 'due_at': stamp(10)}))
    def signal(value, at):
        ref.run('event.inject', {'kind': 'event', 'event_id': str(at), 'event_type': 'ready',
                                'payload': {'ok': value}, 'occurred_at': stamp(at)})
    signal(1, 10)
    assert observe(ref, 10) == []
    signal(True, 11)
    assert observe(ref, 10) == []
    assert observe(ref, 11) == []  # The future signal was consumed, not carried forward.
    signal(True, 11)
    assert [x['action_id'] for x in observe(ref, 11)] == ['event']
    assert observe(ref, 11) == []


@pytest.mark.parametrize('generator,total', [(make_plan, 130), (make_fanout_plan, 750)])
def test_reference_accepts_only_request_stream_not_gold(generator, total):
    plan = generator()
    firings = []
    for case in plan['cases']:
        ref = ExplicitActionReference()
        for op in case['operations']:
            reply = ref.run(op['command'], op['payload'])
            firings.extend(reply.get('firing_observations', []))
    assert len(firings) == total
    assert all('evaluation_wall_ms' not in row for row in firings)


def test_reference_rejects_gold_and_unknown_operation_without_changing_state():
    ref = ExplicitActionReference()
    with pytest.raises(ValueError):
        ref.run('task.create', {**task(), 'expected': True})
    assert ref.tasks == {}
    with pytest.raises(ValueError):
        ref.run('answer.from_gold', {})
    with pytest.raises(ValueError):
        observe(ref, 10)
        observe(ref, 9)


def test_condition_false_and_future_inputs_do_not_trigger_until_valid_current_signal():
    ref = ExplicitActionReference()
    ref.run('task.create', task('condition', 'condition', {
        'condition_id': 'ready', 'operator': 'eq', 'value': True, 'due_at': stamp(10)}))
    for value, observed, tick in ((False, 10, 10), (True, 12, 11), (True, 12, 12)):
        ref.run('event.inject', {'kind': 'condition', 'condition_id': 'ready',
                                'value': value, 'observed_at': stamp(observed)})
        fired = observe(ref, tick)
        assert bool(fired) == (value is True and observed == tick)
    assert observe(ref, 13) == []


def test_final_recurrence_does_not_advance_beyond_representable_time():
    ref = ExplicitActionReference()
    last = '9999-12-31T23:59:59+00:00'
    ref.run('task.create', task(spec={'at': last}, recurrence_policy={
        'type': 'interval', 'interval_seconds': 1, 'max_occurrences': 1}))
    ref.run('clock.inject', {'now': last})
    assert len(ref.run('intention.observe', {})['firing_observations']) == 1
    assert ref.run('intention.observe', {})['firing_observations'] == []


@pytest.mark.parametrize('generator', [make_plan, make_fanout_plan])
def test_every_reference_occurrence_matches_independently_declared_eligibility(generator):
    def parse(value):
        return datetime.fromisoformat(value.replace('Z', '+00:00'))

    for case in generator()['cases']:
        ref = ExplicitActionReference()
        observations, ticks = [], []
        for operation in case['operations']:
            response = ref.run(operation['command'], operation['payload'])
            if operation['command'] == 'intention.observe':
                ticks.append(parse(response['evaluated_at']))
                observations.extend(response['firing_observations'])
        actual = {(row['action_id'], row['occurrence']): row for row in observations}
        assert len(actual) == len(observations), 'duplicate occurrence'
        expected_keys = set()
        for expected in case['expected']:
            cancelled = parse(expected['cancelled_at']) if expected['cancelled_at'] else None
            eligible = [now for now in ticks if (cancelled is None or now < cancelled)
                        and any(now >= parse(window['start']) and
                                (window['end'] is None or now < parse(window['end']) or
                                 (window['end_inclusive'] and now == parse(window['end'])))
                                for window in expected['windows'])]
            key = (expected['action_id'], expected['occurrence'])
            if not eligible:
                assert key not in actual
                continue
            expected_keys.add(key)
            assert key in actual
            assert parse(actual[key]['evaluated_at']) == min(eligible)
            assert parse(actual[key]['due_at']) == parse(expected['due_at'])
            assert actual[key]['trigger_type'] == expected['trigger_type']
        assert set(actual) == expected_keys


def test_revision_guarded_update_retry_preserves_terminal_state():
    ref = ExplicitActionReference()
    ref.run('task.create', task())
    before = ref.run('task.inspect', {'task_id': 'a'})
    update = {'type': 'override', 'task_id': 'a', 'action_id': 'revised',
              'idempotency_key': 'update', 'expected_revision': before['revision']}
    ref.run('task.update', update)
    after = ref.run('task.inspect', {'task_id': 'a'})
    assert after['revision'] != before['revision']
    with pytest.raises(ValueError, match='stale'):
        ref.run('task.update', {**update, 'idempotency_key': 'stale'})
    with pytest.raises(ValueError, match='conflict'):
        ref.run('task.update', {**update, 'action_id': 'conflicting'})
    assert observe(ref, 10)[0]['action_id'] == 'revised'
    final = ref.run('task.inspect', {'task_id': 'a'})
    assert final['status'] == 'fired' and final['revision'] != after['revision']
    ref.run('task.update', update)
    assert ref.run('task.inspect', {'task_id': 'a'}) == final


def test_cancel_retry_and_original_update_do_not_resurrect_cancelled_task():
    ref = ExplicitActionReference()
    ref.run('task.create', task())
    revision = ref.run('task.inspect', {'task_id': 'a'})['revision']
    cancel = {'type': 'cancel', 'task_id': 'a', 'idempotency_key': 'cancel', 'expected_revision': revision}
    ref.run('task.update', cancel)
    ref.run('task.update', cancel)
    assert ref.run('task.inspect', {'task_id': 'a'})['status'] == 'cancelled'
    assert observe(ref, 10) == []


def test_reschedule_and_invalid_update_are_atomic():
    ref = ExplicitActionReference()
    ref.run('task.create', task())
    before = ref.run('task.inspect', {'task_id': 'a'})
    invalid = {'type': 'reschedule', 'task_id': 'a', 'action_id': 'changed', 'due_at': 'invalid'}
    with pytest.raises(ValueError):
        ref.run('task.update', invalid)
    assert ref.run('task.inspect', {'task_id': 'a'}) == before
    ref.run('task.update', {**invalid, 'due_at': stamp(20), 'idempotency_key': 'reschedule',
                            'expected_revision': before['revision']})
    assert observe(ref, 10) == []
    row = observe(ref, 20)[0]
    assert row['action_id'] == 'changed' and row['due_at'] == stamp(20)


def test_cancellation_cannot_relabel_a_fired_task():
    ref = ExplicitActionReference()
    ref.run('task.create', task())
    observe(ref, 10)
    before = ref.run('task.inspect', {'task_id': 'a'})
    with pytest.raises(ValueError, match='fired'):
        ref.run('task.update', {'type': 'cancel', 'task_id': 'a'})
    assert ref.run('task.inspect', {'task_id': 'a'}) == before


def test_explicit_null_keys_cannot_bypass_revision_or_creation_validation():
    ref = ExplicitActionReference()
    with pytest.raises(ValueError):
        ref.run('task.create', {**task(), 'idempotency_key': None})
    assert not ref.tasks
    ref.run('task.create', task())
    before = ref.run('task.inspect', {'task_id': 'a'})
    with pytest.raises(ValueError):
        ref.run('task.update', {'type': 'cancel', 'task_id': 'a',
                                'idempotency_key': None, 'expected_revision': None})
    assert ref.run('task.inspect', {'task_id': 'a'}) == before


@pytest.mark.parametrize('operator,observed,expected,match', [
    ('eq', True, 1, False), ('ne', True, 1, True),
    ('lt', 2, 3, True), ('lte', 3, 3, True), ('gt', 3, 2, True),
    ('gte', 'b', 'a', True), ('lt', 3, 2, False),
    ('in', True, [1, False], False), ('in', 3, [2, 3], True),
])
def test_condition_operator_golden_vectors(operator, observed, expected, match):
    from eval.public.action_reference import _condition_matches
    assert _condition_matches(observed, operator, expected) is match


def test_invalid_condition_evaluation_does_not_partially_consume_earlier_action():
    ref = ExplicitActionReference()
    ref.run('task.create', task())
    ref.run('task.create', task('condition', 'condition', {
        'condition_id': 'value', 'operator': 'gt', 'value': 2, 'due_at': stamp(10)}))
    ref.run('event.inject', {'kind': 'condition', 'condition_id': 'value',
                             'value': True, 'observed_at': stamp(10)})
    with pytest.raises(ValueError, match='same-type'):
        observe(ref, 10)
    assert ref.run('task.inspect', {'task_id': 'a'})['status'] == 'scheduled'
    ref.run('event.inject', {'kind': 'condition', 'condition_id': 'value',
                             'value': 3, 'observed_at': stamp(10)})
    assert {row['action_id'] for row in observe(ref, 10)} == {'a', 'condition'}
