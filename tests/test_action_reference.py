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
