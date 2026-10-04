"""Versioned natural-language dependency extension; no candidate execution."""

import argparse
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
from pathlib import Path
import random

from eval.public.action_implicit_plan import public_case
from eval.public.action_timing_run import SEEDS
from eval.public.bundle import _canonical

SCHEMA = 'm12-dependency-formation-corpus/v1'
SCENARIOS = ('satisfied', 'unsatisfied', 'cancel_dependent', 'cancel_prerequisite', 'unrelated_completion')


def make_corpus():
    cases = []
    for seed in SEEDS:
        rng = random.Random(seed)
        base = datetime(2031, 1, 1, tzinfo=UTC) + timedelta(days=rng.randrange(365))
        for week in range(4):
            start = base + timedelta(weeks=week)
            def stamp(seconds):
                return (start + timedelta(seconds=seconds)).isoformat().replace('+00:00', 'Z')
            for scenario in SCENARIOS:
                identity = f'{seed}:{week}:{scenario}'
                ids = {name: hashlib.sha256(f'{identity}:{name}'.encode()).hexdigest()[:16]
                       for name in ('prerequisite', 'dependent', 'unrelated')}
                late = scenario in ('unsatisfied', 'unrelated_completion')
                due = 10800 if late else 3600
                def schedule(name, kind, payload, dependencies=()):
                    return {'action_id': ids[name], 'trigger': {'type': kind, 'payload': payload},
                            'recurrence_policy': None,
                            'dependency_action_ids': [ids[d] for d in dependencies]}
                prerequisite = schedule('prerequisite', 'exact_time', {'at': stamp(due)})
                dependent = schedule('dependent', 'dependency_completion', {'due_at': stamp(3601)}, ('prerequisite',))
                unrelated = schedule('unrelated', 'exact_time', {'at': stamp(3600)})
                states = [[prerequisite], [prerequisite, dependent]]
                texts = [f'At {stamp(due)}, remind me to approve the release packet.',
                         f'After the approve-the-release-packet reminder has fired, remind me to publish the release packet, '
                         f'but not before {stamp(3601)}. Keep this dependent on that reminder; a timer alone is not sufficient.']
                decisions = ['form', 'form']
                if scenario == 'cancel_dependent':
                    texts.append('Cancel the publish-the-release-packet reminder. Keep the approval reminder.')
                    states.append([prerequisite])
                    decisions.append('cancel')
                elif scenario == 'cancel_prerequisite':
                    texts.append('Cancel the approve-the-release-packet reminder. Leave the dependent publish reminder waiting; '
                                 'cancellation does not count as firing.')
                    states.append([dependent])
                    decisions.append('cancel')
                elif scenario == 'unrelated_completion':
                    texts.append(f'At {stamp(3600)}, also remind me to review the travel budget. '
                                 'That unrelated reminder must not unlock publishing the release packet.')
                    states.append([prerequisite, dependent, unrelated])
                    decisions.append('form')
                actions = [{'action_id': ids[n], 'description': description} for n, description in (
                    ('prerequisite', 'approve the release packet'), ('dependent', 'publish the release packet'),
                    ('unrelated', 'review the travel budget'))]
                rng.shuffle(actions)
                case_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
                public = {'case_id': case_id, 'timezone': 'UTC',
                          'task': 'Track prospective reminders through the offered inert actions. A dependency is satisfied only '
                                  'after its prerequisite reminder fires. Cancellation is not completion. Never execute an external action.',
                          'actions': actions, 'signals': {'events': [], 'conditions': []},
                          'turns': [{'turn_id': str(i), 'now': stamp(i * 60), 'text': text} for i, text in enumerate(texts)]}
                expected = []
                if scenario != 'cancel_prerequisite' and not late:
                    expected.append({'action_id': ids['prerequisite'], 'first_eligible_at': stamp(3600)})
                if scenario == 'satisfied':
                    expected.append({'action_id': ids['dependent'], 'first_eligible_at': stamp(3601)})
                if scenario == 'unrelated_completion':
                    expected.append({'action_id': ids['unrelated'], 'first_eligible_at': stamp(3600)})
                cases.append({'public': public, 'gold': {'case_id': case_id, 'seed': seed, 'week': week,
                              'scenario': scenario, 'turns': [{'turn_id': str(i), 'decision': decision,
                              'active_schedules': deepcopy(state)} for i, (decision, state) in enumerate(zip(decisions, states, strict=True))],
                              'expected_firings': expected}})
    return {'schema': SCHEMA, 'track': 'DEVELOPMENT', 'publishable': False,
            'cases': cases}


def observation_plan(case):
    start = datetime.fromisoformat(case['public']['turns'][0]['now'])
    # Repeated timestamps test duplicates; horizon stops before late prerequisites.
    return [(start + timedelta(seconds=offset)).isoformat().replace('+00:00', 'Z')
            for offset in (3599, 3600, 3600, 3601, 3601, 7200)]


def write_corpus(output):
    corpus = make_corpus()
    public = b''.join(_canonical(public_case(case)) for case in corpus['cases'])
    labels = b''.join(_canonical(case['gold']) for case in corpus['cases'])
    manifest = {'schema': SCHEMA, 'case_count': len(corpus['cases']), 'seeds': list(SEEDS),
                'weeks_per_seed': 4, 'scenarios': list(SCENARIOS), 'publishable': False,
                'candidate_execution': 'not-run', 'scoring_integration': 'required',
                'generator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'files': {name: hashlib.sha256(raw).hexdigest() for name, raw in
                          (('public.jsonl', public), ('labels.jsonl', labels))}}
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    for name, raw in (('public.jsonl', public), ('labels.jsonl', labels), ('manifest.json', _canonical(manifest))):
        (root / name).write_bytes(raw)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    print(_canonical(write_corpus(parser.parse_args().output)).decode(), end='')
