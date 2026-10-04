from collections import Counter
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import random

import pytest

from eval.public.action_implicit_plan import SEEDS, make_corpus, public_case, public_turn, write_corpus


def test_corpus_has_five_seeds_four_weeks_and_all_declared_scenarios():
    random_state = random.getstate()
    corpus = make_corpus()
    assert corpus == make_corpus()
    assert random.getstate() == random_state
    assert corpus['publishable'] is False
    assert len(corpus['cases']) == 220
    assert len({c['public']['case_id'] for c in corpus['cases']}) == 220
    expected = {'exact', 'commitment', 'window', 'event', 'condition', 'recurrence', 'ambiguous',
                'negative', 'quotation', 'cancellation', 'reschedule'}
    for seed in SEEDS:
        for week in range(4):
            cases = [c for c in corpus['cases'] if c['gold']['seed'] == seed and c['gold']['week'] == week]
            assert {c['gold']['scenario'] for c in cases} == expected
            for case in cases:
                assert case['gold']['case_id'] == case['public']['case_id']
                assert len(case['gold']['turns']) == len(case['public']['turns'])
    positions = Counter(next(i for i, a in enumerate(c['public']['actions'])
                             if a['description'] != 'review the unrelated budget') for c in corpus['cases'])
    assert set(positions) == {0, 1}


def test_public_projection_is_detached_and_ignores_gold_and_extra_top_level_fields():
    case = make_corpus()['cases'][0]
    original = public_case(case)
    case['gold'] = {'expected': 'SECRET_EVALUATOR_LABEL'}
    case['public']['gold'] = 'SECRET_EVALUATOR_LABEL'
    assert public_case(case) == original
    projected = public_case(case)
    projected['turns'][0]['text'] = 'changed by consumer'
    assert public_case(case) == original
    assert 'SECRET_EVALUATOR_LABEL' not in json.dumps(public_case(case))


def test_hand_checked_mutation_negative_and_timing_labels():
    cases = {c['gold']['scenario']: deepcopy(c) for c in make_corpus()['cases']
             if c['gold']['seed'] == 7 and c['gold']['week'] == 0}
    for name in ('ambiguous', 'negative', 'quotation'):
        turn = cases[name]['gold']['turns'][0]
        assert turn['active_schedules'] == []
        assert turn['decision'] == ('clarify' if name == 'ambiguous' else 'no_action')
    cancelled = cases['cancellation']['gold']['turns']
    assert [t['decision'] for t in cancelled] == ['form', 'cancel']
    assert len(cancelled[0]['active_schedules']) == 1
    assert cancelled[1]['active_schedules'] == []
    moved = cases['reschedule']['gold']['turns']
    first, second = [t['active_schedules'][0] for t in moved]
    assert first['action_id'] == second['action_id']
    assert datetime.fromisoformat(second['trigger']['payload']['at']) > datetime.fromisoformat(first['trigger']['payload']['at'])
    window = cases['window']['gold']['turns'][0]['active_schedules'][0]['trigger']['payload']
    assert (datetime.fromisoformat(window['end']) - datetime.fromisoformat(window['start'])).total_seconds() == 3600
    recurrence = cases['recurrence']['gold']['turns'][0]['active_schedules'][0]['recurrence_policy']
    assert recurrence == {'type': 'interval', 'interval_seconds': 604800, 'max_occurrences': 3}
    assert cases['commitment']['gold']['turns'][0]['active_schedules'] == cases['exact']['gold']['turns'][0]['active_schedules']


def test_turn_projection_cannot_reveal_future_cancellation_or_mutate_input():
    case = next(c for c in make_corpus()['cases'] if c['gold']['scenario'] == 'cancellation')
    first = public_turn(case, 0)
    assert len(first['turns']) == 1
    assert 'Cancel that reminder.' not in json.dumps(first)
    second = public_turn(case, 1)
    assert second['turns'][-1]['text'] == 'Cancel that reminder.'
    second['turns'][0]['text'] = 'changed'
    assert public_turn(case, 0) == first
    for index in (-1, 2, True, '0'):
        with pytest.raises(ValueError, match='turn index'):
            public_turn(case, index)


def test_materialized_inputs_and_labels_are_separate_reproducible_and_not_results(tmp_path):
    first, second = tmp_path / 'one', tmp_path / 'two'
    manifest = write_corpus(first)
    assert write_corpus(second) == manifest
    assert manifest['candidate_execution'] == 'not-run'
    assert manifest['formation_adapter'] == 'required'
    assert manifest['official_variant'] is manifest['publishable'] is False
    for name, digest in manifest['files'].items():
        raw = (first / name).read_bytes()
        assert raw == (second / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == digest
    for line in (first / 'public.jsonl').read_text().splitlines():
        assert set(json.loads(line)) == {'case_id', 'timezone', 'task', 'actions', 'signals', 'turns'}
    before = (first / 'public.jsonl').read_bytes()
    with pytest.raises(FileExistsError):
        write_corpus(first)
    assert (first / 'public.jsonl').read_bytes() == before


def test_committed_fixture_bytes_match_the_versioned_generator(tmp_path):
    committed = Path(__file__).resolve().parents[1] / 'eval/public/fixtures/m12-implicit-formation-development-v1'
    output = tmp_path / 'regenerated'
    write_corpus(output)
    for name in ('public.jsonl', 'labels.jsonl', 'manifest.json'):
        assert (output / name).read_bytes() == (committed / name).read_bytes()
