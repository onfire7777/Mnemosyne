import json
import shutil
import sqlite3
import sys

import pytest

from eval.public import action_dependency_replay as replay
from eval.public import action_dependency_run as runner
from eval.public.action_dependency_plan import make_corpus
from eval.public.action_formation import CommandFormationProvider


@pytest.fixture(scope='module')
def capture(tmp_path_factory):
    output = tmp_path_factory.mktemp('dependency') / 'run'
    corpus = make_corpus()
    corpus['cases'] = [corpus['cases'][0]]
    script = '''import json,re,sys
r=json.load(sys.stdin);c=r['conversation'];first=len(c['turns'])==1
name='approve the release packet' if first else 'publish the release packet'
a=next(a['action_id'] for a in c['actions'] if a['description']==name)
at=re.search(r'\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}Z',c['turns'][-1]['text']).group()
p={'task_id':'first' if first else 'second','action_id':a,
   'trigger':{'type':'exact_time' if first else 'dependency_completion',
   'payload':{'at':at} if first else {'due_at':at}}}
if not first:p['dependency_ids']=[r['current_tasks'][0]['task_id']]
print(json.dumps({'operations':[{'command':'task.create','payload':p}],'clarification':None}))
'''
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(runner, 'make_corpus', lambda: corpus)
        runner.run_development(output, CommandFormationProvider((sys.executable, '-c', script), 'scripted-not-model'))
    return output, corpus


@pytest.fixture
def artifact(capture, tmp_path, monkeypatch):
    original, corpus = capture
    root = tmp_path / 'copy'
    shutil.copytree(original, root)
    monkeypatch.setattr(replay, 'make_corpus', lambda: corpus)
    return root


def test_dependency_replay_reconstructs_reports_and_sink_without_execution(artifact, monkeypatch):
    from eval.harness.cli_driver import MnemoCLI
    def forbid(*args, **kwargs):
        pytest.fail('replay must not execute provider or CLI')
    monkeypatch.setattr(CommandFormationProvider, 'complete', forbid)
    monkeypatch.setattr(MnemoCLI, 'run', forbid)
    before = {p.name: p.read_bytes() for p in artifact.iterdir()}
    result = replay.recompute(artifact)
    assert result['trace_consistency_verified'] is True
    assert result['cases'] == 1
    assert result['schema'] == 'm12-dependency-formation-replay/v1'
    assert result['provider_execution_verified'] is result['engine_execution_verified'] is False
    assert result['publishable'] is result['ranking_eligible'] is False
    assert before == {p.name: p.read_bytes() for p in artifact.iterdir()}


@pytest.mark.parametrize('mutation', ['dependency', 'probe', 'timing', 'sink', 'source', 'truncated'])
def test_dependency_replay_rejects_changed_evidence(artifact, mutation):
    if mutation == 'sink':
        with sqlite3.connect(artifact / 'sink.sqlite3') as connection:
            connection.execute("UPDATE attempts SET outcome='conflict' WHERE sequence=1")
    elif mutation in ('dependency', 'probe', 'truncated'):
        path = artifact / 'operations.jsonl'
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        if mutation == 'truncated':
            rows.pop()
        elif mutation == 'probe':
            next(r for r in rows if r['stage'] == 'observation_request')['probe'] = 100
        else:
            row = next(r for r in rows if r['stage'] == 'turn_completed' and r['turn'] == 1)
            row['tasks'][1]['schedule']['dependencies'] = []
        path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    else:
        path = artifact / ('source.json' if mutation == 'source' else 'formation-timing.json')
        value = json.loads(path.read_text())
        if mutation == 'source':
            value['harness_files']['eval/public/action_dependency_observe.py'] = '0' * 64
        else:
            value['cases'][0]['metrics']['true_positives'] = 1000
        path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        replay.recompute(artifact)
