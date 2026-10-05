import json
import sys

import pytest

from eval.public import action_dependency_run
from eval.public.action_formation import CommandFormationProvider
from eval.public.action_dependency_plan import make_corpus


def single_case(monkeypatch):
    corpus = make_corpus()
    corpus['cases'] = [next(c for c in corpus['cases'] if c['gold']['scenario'] == 'satisfied')]
    monkeypatch.setattr(action_dependency_run, 'make_corpus', lambda: corpus)
    return corpus


def test_real_command_and_public_cli_retained_without_claiming_model_quality(tmp_path, monkeypatch):
    corpus = single_case(monkeypatch)
    command = (sys.executable, '-c',
               'import json,sys; r=json.load(sys.stdin); '
               'assert "gold" not in r; '
               'print(json.dumps({"operations":[],"clarification":"When should I remind you?"}))')
    provider = CommandFormationProvider(command, 'scripted-test-double; not-a-model')
    output = tmp_path / 'attempt'
    result = action_dependency_run.run_development(output, provider)
    assert result['scored'] is result['publishable'] is False
    assert result['model_quality'] == 'not-evaluated'
    assert result['firing_evaluation'] == 'development-timing-diagnostic'
    observed = json.loads((output / 'observations.json').read_text())
    assert len(observed['cases'][0]['ticks']) == 6
    assert all(not tick['firing_observations'] for tick in observed['cases'][0]['ticks'])
    assert (output / 'sink.sqlite3').exists()
    assert len(result['cases']) == 1
    assert result['cases'][0]['turns'] == 2
    diagnostic = json.loads((output / 'formation-state.json').read_text())
    assert diagnostic['ranking_eligible'] is False
    turns = diagnostic['cases'][0]['turns']
    # Always asking a question must not look like successful formation.
    assert turns[0]['false_negatives'] == 1
    assert turns[0]['state_exact_match'] is False
    assert turns[0]['clarification_expected'] is False
    assert turns[0]['clarification_present'] is True
    assert turns[1]['state_exact_match'] is False
    assert turns[1]['false_negatives'] == 2
    timing = json.loads((output / 'formation-timing.json').read_text())
    assert timing['cases'][0]['metrics']['false_negatives'] == 2
    status = json.loads((output / 'status.json').read_text())
    assert status['status'] == 'completed'
    records = [json.loads(row) for row in (output / 'operations.jsonl').read_text().splitlines()]
    assert status['retained_records'] == len(records)
    requests = [r for r in records if r['stage'] == 'formation_request']
    assert [len(r['request']['conversation']['turns']) for r in requests] == [1, 2]
    assert json.loads((output / 'inputs.json').read_text())['cases'][0] == corpus['cases'][0]['public']
    assert not (output / 'labels.json').exists()
    with pytest.raises(FileExistsError):
        action_dependency_run.run_development(output, provider)


def test_provider_failure_keeps_partial_log_and_no_success_artifact(tmp_path, monkeypatch):
    single_case(monkeypatch)
    provider = CommandFormationProvider((sys.executable, '-c', 'print("not-json")'), 'invalid-test-double')
    output = tmp_path / 'attempt'
    with pytest.raises(ValueError):
        action_dependency_run.run_development(output, provider)
    status = json.loads((output / 'status.json').read_text())
    assert status['status'] == 'failed'
    assert status['completed_cases'] == 0
    assert status['retained_records'] > 0
    records = [json.loads(row) for row in (output / 'operations.jsonl').read_text().splitlines()]
    assert any(r['stage'] == 'formation_response' for r in records)
    assert not (output / 'execution.json').exists()
    assert not (output / 'formation-state.json').exists()


def test_failed_observation_is_not_counted_as_completed_case(tmp_path, monkeypatch):
    single_case(monkeypatch)
    provider = CommandFormationProvider(
        (sys.executable, '-c', 'print(\'{"operations":[],"clarification":null}\')'), 'test-double')

    def fail(*args, **kwargs):
        raise RuntimeError('observation failed')

    monkeypatch.setattr(action_dependency_run, 'observe_case', fail)
    output = tmp_path / 'attempt'
    with pytest.raises(RuntimeError, match='observation failed'):
        action_dependency_run.run_development(output, provider)
    status = json.loads((output / 'status.json').read_text())
    assert status['status'] == 'failed'
    assert status['completed_cases'] == 0
    assert not (output / 'execution.json').exists()


def test_scripted_provider_forms_real_dependency_from_public_history(tmp_path, monkeypatch):
    single_case(monkeypatch)
    script = '''
import json,re,sys
r=json.load(sys.stdin)
assert set(r)=={'schema','conversation','current_tasks','prior_responses','response_contract'}
c=r['conversation']
assert 'gold' not in c and 'scenario' not in c
first=len(c['turns'])==1
name='approve the release packet' if first else 'publish the release packet'
action=next(a['action_id'] for a in c['actions'] if a['description']==name)
at=re.search(r'\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}Z',c['turns'][-1]['text']).group()
p={'task_id':'approval' if first else 'publication','action_id':action,
   'trigger':{'type':'exact_time' if first else 'dependency_completion',
              'payload':{'at':at} if first else {'due_at':at}}}
if not first:
    p['dependency_ids']=[r['current_tasks'][0]['task_id']]
print(json.dumps({'operations':[{'command':'task.create','payload':p}],'clarification':None}))
'''
    provider = CommandFormationProvider((sys.executable, '-c', script), 'scripted-public-contract-test; not-a-model')
    output = tmp_path / 'scripted'
    action_dependency_run.run_development(output, provider)
    state = json.loads((output / 'formation-state.json').read_text())
    assert all(row['state_exact_match'] for row in state['cases'][0]['turns'])
    timing = json.loads((output / 'formation-timing.json').read_text())['cases'][0]['metrics']
    assert timing['true_positives'] == 2
    assert timing['false_positives'] == timing['false_negatives'] == 0
    observations = json.loads((output / 'observations.json').read_text())
    assert len(observations['cases'][0]['sink']['receipts']) == 2
    assert len(observations['cases'][0]['sink']['attempts']) == 4
