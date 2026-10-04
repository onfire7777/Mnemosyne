"""Development natural-language formation corpus; never a candidate executor.

Public conversations and evaluator labels have separate projections. Structured
gold schedules must never be substituted for a system's formation response.
"""

import argparse
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import random


SEEDS = (7, 19, 41, 73, 101)
SCHEMA = 'm12-implicit-formation-corpus/v1'


def _encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def make_corpus():
    cases = []
    for seed in SEEDS:
        rng = random.Random(seed)
        origin = datetime(2030, 1, 1, tzinfo=UTC) + timedelta(days=rng.randrange(730))
        for week in range(4):
            start = origin + timedelta(weeks=week)

            def stamp(seconds):
                return (start + timedelta(seconds=seconds)).isoformat().replace('+00:00', 'Z')

            due, end, revised = stamp(3600), stamp(7200), stamp(10800)
            label = rng.choice(('review the release packet', 'check the archive report', 'inspect the delivery summary'))
            action = hashlib.sha256(f'{seed}:{week}:action'.encode()).hexdigest()[:16]
            distractor = hashlib.sha256(f'{seed}:{week}:other'.encode()).hexdigest()[:16]

            def schedule(kind='exact_time', payload=None, recurrence=None):
                return {'action_id': action, 'trigger': {'type': kind, 'payload': payload or {'at': due}},
                        'recurrence_policy': recurrence}

            exact = schedule()
            variants = [
                ('exact', [f'At {due}, remind me to {label}.'], ['form'], [exact]),
                ('commitment', [f'I will {label} at {due}.'], ['form'], [exact]),
                ('window', [f'Remind me to {label} once during the interval from {due} up to but not including {end}. '
                            'If that interval has passed, skip it.'], ['form'],
                 [schedule('time_window', {'start': due, 'end': end})]),
                ('event', [f'At or after {due}, when a delivery event has status ready, remind me to {label}. '
                           'Ignore other delivery statuses.'], ['form'],
                 [schedule('event', {'event_type': 'delivery', 'match': {'status': 'ready'}, 'due_at': due})]),
                ('condition', [f'From {due} onward, remind me to {label} when release_ready is true.'], ['form'],
                 [schedule('condition', {'condition_id': 'release_ready', 'operator': 'eq', 'value': True, 'due_at': due})]),
                ('recurrence', [f'Remind me to {label} at {due}, then at the same UTC time seven days later '
                                'and fourteen days later. Three reminders total.'], ['form'],
                 [schedule(recurrence={'type': 'interval', 'interval_seconds': 604800, 'max_occurrences': 3})]),
                ('ambiguous', [f'Remind me to {label} sometime. Ask me when before scheduling anything.'], ['clarify'], [None]),
                ('negative', [f'I already remembered to {label}. Do not create a reminder.'], ['no_action'], [None]),
                ('quotation', [f'The sample document says: "At {due}, remind me to {label}." '
                               'That is quoted example text, not a request from me.'], ['no_action'], [None]),
                ('cancellation', [f'At {due}, remind me to {label}.', 'Cancel that reminder.'],
                 ['form', 'cancel'], [exact, None]),
                ('reschedule', [f'At {due}, remind me to {label}.', f'Move that reminder to {revised} instead.'],
                 ['form', 'reschedule'], [exact, schedule(payload={'at': revised})]),
            ]
            rng.shuffle(variants)
            for scenario, texts, decisions, states in variants:
                case_id = hashlib.sha256(f'{seed}:{week}:{scenario}'.encode()).hexdigest()[:24]
                turns = [{'turn_id': str(i), 'now': stamp(i * 60), 'text': text}
                         for i, text in enumerate(texts)]
                public = {
                    'case_id': case_id, 'timezone': 'UTC',
                    'task': 'Track the user\'s prospective reminders and future commitments using the offered inert actions. '
                            'Ask about missing timing before scheduling. Do not turn quoted examples or completed tasks into reminders. '
                            'Process each user turn in order. Never execute an external action.',
                    'actions': [{'action_id': action, 'description': label},
                                {'action_id': distractor, 'description': 'review the unrelated budget'}],
                    'signals': {'events': [{'event_type': 'delivery', 'fields': {'status': 'string'}}],
                                'conditions': [{'condition_id': 'release_ready', 'value_type': 'boolean'}]},
                    'turns': turns,
                }
                # Vary action order so selecting the first offered action is not a shortcut.
                rng.shuffle(public['actions'])
                gold = {'case_id': case_id, 'seed': seed, 'week': week, 'scenario': scenario,
                        'turns': [{'turn_id': str(i), 'decision': decision,
                                   'active_schedules': [] if state is None else [deepcopy(state)]}
                                  for i, (decision, state) in enumerate(zip(decisions, states, strict=True))]}
                cases.append({'public': public, 'gold': gold})
    return {'schema': SCHEMA, 'track': 'DEVELOPMENT', 'publishable': False, 'cases': cases}


def public_case(case):
    """Detached, allowlisted payload; never traverse evaluator labels."""
    value = case['public']
    return deepcopy({key: value[key] for key in ('case_id', 'timezone', 'task', 'actions', 'signals', 'turns')})


def public_turn(case, index):
    """Return only the conversation prefix available at this turn."""
    result = public_case(case)
    if type(index) is not int or not 0 <= index < len(result['turns']):
        raise ValueError('turn index must identify an existing turn')
    result['turns'] = result['turns'][:index + 1]
    return result


def write_corpus(output):
    """Materialize separate inputs/labels with byte hashes, not result receipts."""
    corpus = make_corpus()
    public = b''.join(_encoded(public_case(case)) for case in corpus['cases'])
    labels = b''.join(_encoded(case['gold']) for case in corpus['cases'])
    manifest = {'schema': SCHEMA, 'track': 'DEVELOPMENT', 'publishable': False,
                'case_count': len(corpus['cases']), 'seeds': list(SEEDS), 'weeks_per_seed': 4,
                'generator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'files': {'public.jsonl': hashlib.sha256(public).hexdigest(),
                          'labels.jsonl': hashlib.sha256(labels).hexdigest()},
                'candidate_execution': 'not-run', 'formation_adapter': 'required',
                'official_variant': False}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in (('public.jsonl', public), ('labels.jsonl', labels), ('manifest.json', _encoded(manifest))):
        with (output / name).open('xb') as handle:
            handle.write(raw)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    print(json.dumps(write_corpus(parser.parse_args().output), sort_keys=True))
