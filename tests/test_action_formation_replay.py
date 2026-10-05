import json
from pathlib import Path
import shutil
import sqlite3
import sys

import pytest

from eval.public import action_formation_replay as replay
from eval.public import action_formation_run as runner
from eval.public.action_formation import CommandFormationProvider
from eval.public.action_implicit_plan import make_corpus


@pytest.fixture(scope='module')
def capture(tmp_path_factory):
    output = tmp_path_factory.mktemp('formation-capture') / 'run'
    corpus = make_corpus()
    corpus['cases'] = [next(c for c in corpus['cases'] if c['gold']['scenario'] == scenario)
                       for scenario in ('exact', 'cancellation')]
    # This is a transparent scripted test double, not a model result. It reads
    # the actual public request and never receives fixture labels.
    script = '''import json,re,sys
r=json.load(sys.stdin)
c=r['conversation']
if len(c['turns']) == 1:
    text=c['turns'][0]['text']
    action=next(a['action_id'] for a in c['actions'] if a['description'] in text)
    due=re.search(r'At (\\S+),', text).group(1)
    ops=[{'command':'task.create','payload':{'task_id':'one','action_id':action,
         'trigger':{'type':'exact_time','payload':{'at':due}}}}]
else:
    ops=[{'command':'task.update','payload':{'task_id':'one','type':'cancel'}}]
print(json.dumps({'operations':ops,'clarification':None}))
'''
    provider = CommandFormationProvider((sys.executable, '-c', script), 'scripted-test-double-not-model')
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(runner, 'make_corpus', lambda: corpus)
        runner.run_development(output, provider)
    return output, corpus


@pytest.fixture
def artifact(capture, tmp_path, monkeypatch):
    output, corpus = capture
    root = tmp_path / 'copy'
    shutil.copytree(output, root)
    monkeypatch.setattr(replay, 'make_corpus', lambda: corpus)
    return root


def edit_json(root, name, update):
    path = root / name
    value = json.loads(path.read_text())
    update(value)
    path.write_text(json.dumps(value))


def edit_trace(root, update):
    path = root / 'operations.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    update(rows)
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))


def test_replay_reconstructs_both_reports_and_database_without_executing_provider(artifact, monkeypatch):
    from eval.harness.cli_driver import MnemoCLI

    def forbid(*args, **kwargs):
        pytest.fail('replay must never run model or public CLI')

    monkeypatch.setattr(CommandFormationProvider, 'complete', forbid)
    monkeypatch.setattr(MnemoCLI, 'run', forbid)
    before = {path.name: path.read_bytes() for path in artifact.iterdir()}
    result = replay.recompute(artifact)
    assert result['trace_consistency_verified'] is True
    assert result['cases'] == 2
    assert result['publishable'] is result['provider_execution_verified'] is False
    assert result['engine_execution_verified'] is result['independent_implementation'] is False
    assert set(result['files']) == set(replay.FILES)
    assert before == {path.name: path.read_bytes() for path in artifact.iterdir()}
    reports = json.loads((artifact / 'formation-timing.json').read_text())['cases']
    assert reports[0]['metrics']['true_positives'] == 1
    assert reports[1]['metrics']['false_positives'] == 0


@pytest.mark.parametrize('name', ['formation-state.json', 'formation-timing.json', 'observations.json',
                                  'execution.json', 'status.json', 'inputs.json', 'observation-plan.json'])
def test_altered_artifact_is_rejected(artifact, name):
    edit_json(artifact, name, lambda value: value.update(invented=True))
    with pytest.raises(ValueError, match='differs'):
        replay.recompute(artifact)


@pytest.mark.parametrize('mutation', ['request', 'output', 'snapshot', 'ack', 'capture-hash',
                                     'duration', 'truncated', 'trailing', 'probe'])
def test_altered_trace_is_rejected(artifact, mutation):
    def update(rows):
        def first(stage):
            return next(r for r in rows if r['stage'] == stage)
        if mutation == 'request':
            first('formation_request')['request']['gold'] = 'leaked'
        elif mutation == 'output':
            first('formation_response')['stdout_base64'] = 'e30='
        elif mutation == 'snapshot':
            first('turn_completed')['tasks'] = []
        elif mutation == 'ack':
            first('action_response')['response'] = {'extra': True}
        elif mutation == 'capture-hash':
            next(r for r in rows if r['stage'] == 'action_response' and
                 r['command'] == 'evidence.capture')['response']['content_sha256'] = '0' * 64
        elif mutation == 'duration':
            first('formation_response')['wall_ms'] = True
        elif mutation == 'truncated':
            rows.pop()
        elif mutation == 'trailing':
            rows.append(rows[-1])
        elif mutation == 'probe':
            first('observation_request')['payload']['now'] = '2099-01-01T00:00:00Z'
    edit_trace(artifact, update)
    with pytest.raises(ValueError):
        replay.recompute(artifact)


def test_database_edit_is_rejected_even_when_json_is_unchanged(artifact):
    with sqlite3.connect(artifact / 'sink.sqlite3') as connection:
        connection.execute("UPDATE attempts SET outcome='conflict' WHERE sequence=1")
    with pytest.raises(ValueError, match='durable sink rows'):
        replay.recompute(artifact)


def test_wrong_source_and_upgraded_claims_are_rejected(artifact):
    edit_json(artifact, 'source.json', lambda value: value['harness_files'].update(
        {'eval/public/action_formation.py': '0' * 64}))
    with pytest.raises(ValueError, match='source differs'):
        replay.recompute(artifact)


def test_provider_identity_is_not_attested_by_trace(artifact):
    edit_json(artifact, 'provider.json', lambda value: value.update(identity_verified=True))
    with pytest.raises(ValueError, match='provider claims'):
        replay.recompute(artifact)


def test_symlink_artifact_is_rejected(artifact, tmp_path):
    original = artifact / 'status.json'
    outside = tmp_path / 'outside.json'
    original.rename(outside)
    try:
        original.symlink_to(outside)
    except OSError:
        pytest.skip('symlink creation is unavailable on this host')
    with pytest.raises((OSError, ValueError)):
        replay.recompute(artifact)


def test_duplicate_json_keys_are_rejected(artifact):
    (artifact / 'status.json').write_text('{"status":"failed","status":"completed"}')
    with pytest.raises(ValueError):
        replay.recompute(artifact)


def test_files_changed_during_replay_are_rejected(artifact, monkeypatch):
    original = replay._snapshot
    calls = 0

    def snapshot(root):
        nonlocal calls
        calls += 1
        if calls == 2:
            with (Path(root) / 'provider.json').open('a') as handle:
                handle.write('\n')
        return original(root)

    monkeypatch.setattr(replay, '_snapshot', snapshot)
    with pytest.raises(ValueError, match='changed during replay'):
        replay.recompute(artifact)
