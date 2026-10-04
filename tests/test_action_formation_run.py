import json
import sys

import pytest

from eval.public import action_formation_run
from eval.public.action_formation import CommandFormationProvider
from eval.public.action_implicit_plan import make_corpus


def single_case(monkeypatch):
    corpus = make_corpus()
    corpus['cases'] = [next(c for c in corpus['cases'] if c['gold']['scenario'] == 'cancellation')]
    monkeypatch.setattr(action_formation_run, 'make_corpus', lambda: corpus)
    return corpus


def test_real_command_and_public_cli_retained_without_claiming_model_quality(tmp_path, monkeypatch):
    corpus = single_case(monkeypatch)
    command = (sys.executable, '-c',
               'import json,sys; r=json.load(sys.stdin); '
               'assert "gold" not in r; '
               'print(json.dumps({"operations":[],"clarification":"When should I remind you?"}))')
    provider = CommandFormationProvider(command, 'scripted-test-double; not-a-model')
    output = tmp_path / 'attempt'
    result = action_formation_run.run_development(output, provider)
    assert result['scored'] is result['publishable'] is False
    assert result['model_quality'] == 'not-evaluated'
    assert result['firing_evaluation'] == 'not-run'
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
    assert turns[1]['state_exact_match'] is True
    status = json.loads((output / 'status.json').read_text())
    assert status['status'] == 'completed'
    records = [json.loads(row) for row in (output / 'operations.jsonl').read_text().splitlines()]
    assert status['retained_records'] == len(records)
    requests = [r for r in records if r['stage'] == 'formation_request']
    assert [len(r['request']['conversation']['turns']) for r in requests] == [1, 2]
    assert json.loads((output / 'inputs.json').read_text())['cases'][0] == corpus['cases'][0]['public']
    assert not (output / 'labels.json').exists()
    with pytest.raises(FileExistsError):
        action_formation_run.run_development(output, provider)


def test_provider_failure_keeps_partial_log_and_no_success_artifact(tmp_path, monkeypatch):
    single_case(monkeypatch)
    provider = CommandFormationProvider((sys.executable, '-c', 'print("not-json")'), 'invalid-test-double')
    output = tmp_path / 'attempt'
    with pytest.raises(ValueError):
        action_formation_run.run_development(output, provider)
    status = json.loads((output / 'status.json').read_text())
    assert status['status'] == 'failed'
    assert status['completed_cases'] == 0
    assert status['retained_records'] > 0
    records = [json.loads(row) for row in (output / 'operations.jsonl').read_text().splitlines()]
    assert any(r['stage'] == 'formation_response' for r in records)
    assert not (output / 'execution.json').exists()
    assert not (output / 'formation-state.json').exists()
