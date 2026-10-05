"""Characterize a baseline-freeze question through the real public action seam."""

from eval.harness.cli_driver import MnemoCLI
from eval.public.action_cli import ActionCLI
from eval.public.action_reference import ExplicitActionReference


def test_nested_json_type_boundary_is_explicit_before_reference_admission(tmp_path):
    candidate = ActionCLI(MnemoCLI(store=str(tmp_path / 'unused.json'), timeout_s=30))
    reference = ExplicitActionReference()
    scope = {'store': str(tmp_path / 'case.json'), 'tenant_id': 'condition-boundary', 'session_id': 'session'}
    now = '2030-01-01T00:00:00+00:00'
    cases = [
        ('scalar-control', 'eq', True, 1),
        ('nested-eq', 'eq', {'enabled': True}, {'enabled': 1}),
        ('nested-ne', 'ne', {'enabled': True}, {'enabled': 1}),
        ('nested-in', 'in', [{'enabled': True}], {'enabled': 1}),
        ('matching-control', 'eq', {'enabled': True}, {'enabled': True}),
    ]
    for name, operator, expected, observed in cases:
        payload = {'task_id': name, 'action_id': name,
                   'trigger': {'type': 'condition', 'payload': {
                       'condition_id': name, 'operator': operator, 'value': expected, 'due_at': now}}}
        candidate.run('task.create', scope, payload)
        reference.run('task.create', payload)
        signal = {'kind': 'condition', 'condition_id': name, 'value': observed, 'observed_at': now}
        candidate.run('event.inject', scope, signal)
        reference.run('event.inject', signal)
    candidate.run('clock.inject', scope, {'now': now})
    reference.run('clock.inject', {'now': now})
    observed = candidate.run('intention.observe', scope, {})
    baseline = reference.run('intention.observe', {})
    # Characterization, not endorsement: these exact outcomes differ and must
    # not be labelled semantically equivalent by a comparison/admission step.
    assert set(observed['action_ids']) == {'nested-eq', 'nested-in', 'matching-control'}
    assert {row['action_id'] for row in baseline['firing_observations']} == {'nested-ne', 'matching-control'}
