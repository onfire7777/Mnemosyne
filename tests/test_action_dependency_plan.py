from copy import deepcopy
from datetime import datetime
import hashlib
import json

from eval.public.action_dependency_plan import SCENARIOS, make_corpus, observation_plan, write_corpus
from eval.public.action_implicit_plan import public_case, public_turn
from eval.public.action_timing_run import SEEDS


def test_extension_preserves_each_seed_week_control_and_no_future_turn_leak():
    corpus = make_corpus()
    assert corpus == make_corpus()
    assert len(corpus['cases']) == 100
    assert len({c['public']['case_id'] for c in corpus['cases']}) == 100
    for seed in SEEDS:
        for week in range(4):
            rows = [c for c in corpus['cases'] if c['gold']['seed'] == seed and c['gold']['week'] == week]
            assert {c['gold']['scenario'] for c in rows} == set(SCENARIOS)
    for case in corpus['cases']:
        assert len(public_turn(case, 0)['turns']) == 1
        before = public_case(case)
        mutated = deepcopy(case)
        mutated['gold'] = {'secret': 'HIDDEN_EXPECTATION'}
        assert public_case(mutated) == before
        assert 'HIDDEN_EXPECTATION' not in json.dumps(before)
        ticks = observation_plan(case)
        assert ticks[1] == ticks[2] and ticks[3] == ticks[4]
        assert datetime.fromisoformat(ticks[0]) > datetime.fromisoformat(case['public']['turns'][-1]['now'])


def test_hand_checked_dependencies_cancellation_and_unrelated_completion():
    cases = {c['gold']['scenario']: c for c in make_corpus()['cases'] if c['gold']['seed'] == 7 and c['gold']['week'] == 0}
    assert {k: len(c['gold']['expected_firings']) for k,c in cases.items()} == {
        'satisfied': 2, 'unsatisfied': 0, 'cancel_dependent': 1, 'cancel_prerequisite': 0, 'unrelated_completion': 1}
    for case in cases.values():
        first, dependent = case['gold']['turns'][1]['active_schedules']
        assert dependent['dependency_action_ids'] == [first['action_id']]
        assert dependent['trigger']['type'] == 'dependency_completion'
    cancelled = cases['cancel_prerequisite']['gold']['turns']
    assert cancelled[-1]['active_schedules'] == [cancelled[1]['active_schedules'][1]]
    unrelated = cases['unrelated_completion']['gold']
    assert unrelated['expected_firings'][0]['action_id'] == unrelated['turns'][-1]['active_schedules'][2]['action_id']


def test_extension_materializes_separate_inputs_labels_and_hashes(tmp_path):
    manifest = write_corpus(tmp_path / 'fixture')
    assert manifest['candidate_execution'] == 'not-run'
    assert manifest['scoring_integration'] == 'required'
    for name,digest in manifest['files'].items():
        assert hashlib.sha256((tmp_path / 'fixture' / name).read_bytes()).hexdigest() == digest


def test_committed_dependency_fixture_is_reproducible(tmp_path):
    from pathlib import Path
    committed = Path(__file__).resolve().parents[1] / 'eval/public/fixtures/m12-dependency-formation-development-v1'
    output = tmp_path / 'regenerated'
    write_corpus(output)
    for name in ('public.jsonl', 'labels.jsonl', 'manifest.json'):
        assert (output / name).read_bytes() == (committed / name).read_bytes()
