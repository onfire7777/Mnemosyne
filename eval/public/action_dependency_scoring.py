"""Dependency-aware state diagnostics using public inspection, never proposals."""

from collections import Counter
from copy import deepcopy
import json

from eval.public.action_formation_scoring import _expected, _json, _observed, _signature
from eval.public.action_formation_scoring import score_case as validate_snapshots


def score_case(case, snapshots):
    # Reuse structural and state validation without changing the frozen v1
    # scorer or pretending it supports dependency labels.
    structural = deepcopy(case)
    for turn in structural['gold']['turns']:
        turn['active_schedules'] = []
    report = validate_snapshots(structural, snapshots)
    for expected, snapshot, result in zip(case['gold']['turns'], snapshots, report['turns'], strict=True):
        tasks = snapshot['tasks']
        by_intention = {task['intention_id']: task for task in tasks}
        action_counts = Counter(task['action_id'] for task in tasks)
        actual = Counter()
        for task in tasks:
            signature = json.loads(_observed(task)[0])
            dependencies = []
            for identifier in signature['dependencies']:
                if identifier not in by_intention:
                    raise ValueError('dependency absent from complete public snapshot')
                action = by_intention[identifier]['action_id']
                # Two instances of the same action cannot establish which one
                # was intended as prerequisite from action-level labels alone.
                dependencies.append(action if action_counts[action] == 1 else {'ambiguous_action': action})
            signature['dependencies'] = sorted(dependencies, key=_json)
            if task['status'] == 'scheduled':
                actual[_json(signature)] += 1
        desired = Counter()
        for schedule in expected['active_schedules']:
            if set(schedule) != {'action_id', 'trigger', 'recurrence_policy', 'dependency_action_ids'}:
                raise ValueError('invalid dependency extension label')
            dependencies = schedule['dependency_action_ids']
            if not isinstance(dependencies, list) or any(not isinstance(d, str) or not d for d in dependencies):
                raise ValueError('invalid expected dependency identities')
            if schedule['trigger']['type'] == 'dependency_completion':
                payload = schedule['trigger']['payload']
                if set(payload) != {'due_at'} or not dependencies:
                    raise ValueError('dependency label requires due time and prerequisite')
                signature = _signature(schedule['action_id'], 'dependency_completion', {'require': 'all'},
                                       payload['due_at'], schedule['recurrence_policy'] or {'type': 'none'}, dependencies)
            else:
                plain = {k: v for k, v in schedule.items() if k != 'dependency_action_ids'}
                value = json.loads(_expected(plain))
                value['dependencies'] = sorted(dependencies)
                signature = _json(value)
            desired[signature] += 1
        result.update(true_positives=sum((desired & actual).values()),
                      false_positives=sum((actual - desired).values()),
                      false_negatives=sum((desired - actual).values()),
                      state_exact_match=actual == desired and not result['premature_fired_tasks']
                      and not result['observed_occurrence_advances'])
    report['schema'] = 'm12-dependency-formation-state-diagnostic/v1'
    report['dependency_identity'] = 'public intention identifiers resolved to unambiguous action identities'
    return report
