"""Focused host checks: real observations, current code, and no invented credit."""
import importlib.util
import json
from pathlib import Path
import subprocess
import zipfile
from types import SimpleNamespace

import pytest

from mnemosyne.hosts.codex import _tool_event
from mnemosyne.hosts.memory_checks import observed_memory_checks
from mnemosyne.models import Assertion, Evidence
from tests.test_codex_lifecycle import LocalHost


def test_hypothesis_contract_survives_typed_verifier_but_not_printed_json():
    payload = {'hypothesis_id': 'h', 'contract_hash': 'hash', 'tested_steps': ['inspect'],
               'source_versions': {'cid': 1}, 'hypothesis_review': {'status': 'tested'},
               'experiment_environment': {'version': 1, 'kind': 'sqlite'}, 'verdict': True}
    result = _tool_event('external_checker', {'structuredContent': payload}, tool_id='actual')
    for key, value in payload.items():
        assert result[key] == value
    for name, response in [('shell', payload), ('external_checker', json.dumps(payload))]:
        result = _tool_event(name, response, command='echo check' if name == 'shell' else None)
        assert not {'contract_hash', 'hypothesis_review', 'experiment_environment'} & result.keys()


def _host_with_command_memory(tmp_path):
    host = LocalHost(tmp_path)
    host.engine.policy.learning_exploration_rate = 0
    host.engine.policy.learning_exploration_floor = 0
    cid = host.engine.append_evidence(Evidence(tenant_id='t', user_id='u', actor='tool',
        source_type='test_observation', content='python -m compileall src completed with exit 0',
        access_policy={'tenant': 't', 'allow_principals': ['u']}))
    contract = {'kind': 'command_observation', 'argv': ['python', '-m', 'compileall', 'src'],
                'cwd': str(tmp_path), 'expected_exit_code': 0, 'source_cid': cid}
    identifier = host.engine.upsert_assertion(Assertion(tenant_id='t', user_id='u',
        subject='Atlas', predicate='build_command', object='python -m compileall src',
        status='active', source_evidence_cids=[cid], calibration={'verification_contract': contract},
        access_policy={'tenant': 't', 'allow_principals': ['u']}))
    response = host.event('UserPromptSubmit', turn_id='turn', prompt='Atlas build command', cwd=str(tmp_path))
    context = json.loads(response['hookSpecificOutput']['additionalContext'].split('\n', 1)[1])
    assert identifier in {hit['id'] for hit in context['hits']}
    receipt = host.runtime.writer.read('t')['receipts'][context['receipt_id']]
    frozen = receipt['item_verification_contracts'][identifier][0]
    assert {key: value for key, value in frozen.items() if key != '_projection'} == contract
    assert frozen['_projection']['id'] == identifier
    return host, context, identifier, cid


@pytest.mark.parametrize('code', [0, 1])
def test_observed_command_verifies_applied_memory_without_grading_task(tmp_path, code):
    host, context, identifier, _ = _host_with_command_memory(tmp_path)
    host.event('MemoryUse', receipt_id=context['receipt_id'], used_items=[identifier])
    host.event('PostToolUse', tool_name='shell', tool_use_id='compile',
        tool_input={'command': 'python -m compileall src', 'cwd': str(tmp_path)},
        tool_response={'exit_code': code, 'output': 'compiler output'})
    host.event('Stop', last_assistant_message='The command was checked.')
    episode = host.episodes()[-1]
    assert episode['target_outcomes'][identifier]['value'] == (1 if code == 0 else -1)
    assert episode['reward'] is None and episode['status'] == 'open'
    assert not host.runtime.writer.read('t')['credit']


def test_superseded_memory_cannot_receive_new_feedback(tmp_path):
    host, context, identifier, _ = _host_with_command_memory(tmp_path)
    host.event('MemoryUse', receipt_id=context['receipt_id'], used_items=[identifier])
    assertion = host.engine._get_projection_for_adapter('t', 'main', 'assertion', identifier)
    assertion.status = 'retracted'
    host.engine.upsert_assertion(assertion)
    host.event('PostToolUse', tool_name='shell', tool_use_id='compile',
        tool_input={'command': 'python -m compileall src', 'cwd': str(tmp_path)},
        tool_response={'exit_code': 0, 'output': 'compiler output'})
    host.event('Stop', last_assistant_message='The command was checked.')
    assert identifier not in host.episodes()[-1].get('target_outcomes', {})


@pytest.mark.parametrize('mismatch', ['workspace', 'command', 'self_grade', 'not_used', 'source_erased'])
def test_command_feedback_rejects_unrelated_or_unapplied_observations(tmp_path, mismatch):
    host, context, identifier, _ = _host_with_command_memory(tmp_path)
    receipt = host.runtime.writer.read('t')['receipts'][context['receipt_id']]
    event = _tool_event('shell', {'exit_code': 0, 'output': 'ok'}, command='python -m compileall src',
                        cwd=str(tmp_path), tool_id='actual')
    if mismatch == 'workspace':
        event['cwd'] += '/other'
    elif mismatch == 'command':
        event['command'] = 'python -m compileall other'
    elif mismatch == 'self_grade':
        event['source'] = 'assistant'
    assert observed_memory_checks(receipt, [] if mismatch == 'not_used' else [identifier], [event],
                                  lambda cids: mismatch != 'source_erased') == []


def _runtime():
    path = Path(__file__).parents[1] / 'integrations/codex/runtime_template.py'
    spec = importlib.util.spec_from_file_location('fresh_runtime_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fresh_dispatch_reads_updated_child_and_preserves_bound_session(tmp_path, monkeypatch):
    runtime = _runtime()
    child = tmp_path / 'runtime.py'
    monkeypatch.setattr(runtime, '__file__', str(child))
    for revision in (1, 2):
        child.write_text('import json,sys\np=json.load(sys.stdin)\n'
                         f'print(json.dumps({{"revision":{revision},"payload":p}}))\n')
        response = runtime.fresh_call('learning_status', {'tenant_id': 't',
            'session_identity': SimpleNamespace(session_id='bound'), 'session_token': 'secret'})
        assert response['revision'] == revision
        assert response['payload'] == {'arguments': {'tenant_id': 't'}, 'session_id': 'bound'}


def test_mutation_timeout_is_never_retried_or_reported_as_success(monkeypatch):
    runtime = _runtime()
    calls = []
    def timeout(*args, **kwargs):
        calls.append(args)
        raise subprocess.TimeoutExpired(args[0], kwargs['timeout'])
    monkeypatch.setattr(runtime.subprocess, 'run', timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        runtime.fresh_call('capture', {'content': 'private'})
    assert len(calls) == 1


def test_installed_release_is_a_separate_snapshot_and_bad_wheel_cannot_replace_it(tmp_path):
    path = Path(__file__).parents[1] / 'integrations/codex/install.py'
    spec = importlib.util.spec_from_file_location('release_installer_test', path)
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    destination = tmp_path / 'codex'
    destination.mkdir()
    wheel = tmp_path / 'package.whl'
    with zipfile.ZipFile(wheel, 'w') as archive:
        archive.writestr('mnemosyne/__init__.py', 'VERSION = 1\n')
    release = installer.install_release(destination, wheel)
    assert (Path(release['path']) / 'mnemosyne/__init__.py').read_text() == 'VERSION = 1\n'
    manifest = (destination / 'active-release.json').read_bytes()
    with zipfile.ZipFile(wheel, 'w') as archive:
        archive.writestr('../escape.py', 'bad')
    with pytest.raises(ValueError, match='invalid member'):
        installer.install_release(destination, wheel)
    assert (destination / 'active-release.json').read_bytes() == manifest
    assert not (tmp_path / 'escape.py').exists()


def test_projection_recovery_retries_failure_and_is_idempotent(tmp_path, monkeypatch):
    from mnemosyne.hosts.project_memory import advance_project_memory
    from mnemosyne.hosts import project_memory
    monkeypatch.setattr(project_memory.time, 'time', lambda: 100)
    rows = {'one': {'id': 'one', 'user_id': 'u', 'status': 'resolved', 'source_cids': ['cid']}}
    calls = []
    def project(tenant, row, **kwargs):
        calls.append(row['id'])
        if len(calls) == 1:
            raise OSError('temporarily unavailable')
        return [{'created_count': 2}]
    runtime = SimpleNamespace(writer=SimpleNamespace(read=lambda _: {'episodes': rows}),
                              _project_episode_memory=project)
    path = tmp_path / 'checkpoint.json'
    first = advance_project_memory(runtime, 't', 'u', path)
    assert first['pending'] == 1 and first['errors'][0]['type'] == 'OSError'
    assert advance_project_memory(runtime, 't', 'u', path)['deferred'] == 1
    monkeypatch.setattr(project_memory.time, 'time', lambda: 140)
    second = advance_project_memory(runtime, 't', 'u', path)
    assert second['pending'] == 0 and second['created'] == 2
    assert advance_project_memory(runtime, 't', 'u', path)['processed'] == 0
    assert calls == ['one', 'one']


def test_failed_old_projection_does_not_starve_newer_sources(tmp_path, monkeypatch):
    from mnemosyne.hosts import project_memory
    monkeypatch.setattr(project_memory.time, 'time', lambda: 100)
    rows = {key: {'id': key, 'user_id': 'u', 'status': 'resolved', 'source_cids': [key]}
            for key in ('a', 'b')}
    def project(tenant, row, **kwargs):
        return [{'rejected': [{'reason': 'provider_unavailable'}]}] if row['id'] == 'a' else []
    runtime = SimpleNamespace(writer=SimpleNamespace(read=lambda _: {'episodes': rows}),
                              _project_episode_memory=project)
    path = tmp_path / 'checkpoint.json'
    project_memory.advance_project_memory(runtime, 't', 'u', path, limit=1)
    result = project_memory.advance_project_memory(runtime, 't', 'u', path, limit=1)
    assert result['processed'] == 1 and result['deferred'] == 1
    assert list(json.loads(path.read_text())['completed']) == ['b']


def test_live_snapshot_survives_matching_transcript_but_not_changed_execution():
    from mnemosyne.hosts.codex import _merge_events
    live = {'tool_use_id': 'call', 'command': 'pytest test_x.py', 'exit_code': 1,
            'cwd': '/workspace', 'experiment_environment': {'source_call_id': 'call'}}
    transcript = {'tool_use_id': 'call', 'command': 'pytest test_x.py', 'exit_code': 1}
    assert _merge_events([live], [transcript])[0] == live
    changed = _merge_events([live], [{**transcript, 'exit_code': 0}])[0]
    assert 'experiment_environment' not in changed


def test_nested_provider_failure_remains_retryable():
    from mnemosyne.hosts.project_memory import _retryable
    assert _retryable([{'rejected_proposals': [{'reason': 'provider_failed'}]}])
    assert _retryable([{'rejected': [{'reason': 'reviewer_unavailable'}]}])
    assert not _retryable([{'rejected': [{'reason': 'unsupported_claim'}]}])


def test_partial_page_never_gets_whole_page_verification_contract():
    from mnemosyne.hosts.memory_checks import freeze_contracts
    page = {'page_id': 'page', 'claims': [
        {'text': 'first fact', 'verification_contract': {'source_cid': 'a'}},
        {'text': 'second fact', 'verification_contract': {'source_cid': 'b'}},
    ]}
    assert freeze_contracts(None, 't', [], [page],
        {'page': {'text': 'first fact', 'omitted_claims': 1}}, {'page': ['a']}) == {}


def test_maintenance_reads_normal_captured_sources_under_unchanged_policy(tmp_path):
    from mnemosyne.hosts.project_memory import maintenance_context
    from mnemosyne.knowledge_maintenance import KnowledgeMaintenanceWorker
    host = LocalHost(tmp_path)
    host.runtime.observe_turn('t', 'u', 'earlier', 'Inspect configuration.', '', tool_events=[{
        'name': 'shell', 'source': 'tool', 'command': 'cat service.json', 'cwd': '/work/Atlas',
        'exit_code': 0, 'output': '{"language":"python","database":"sqlite"}', 'call_id': 'read'}])
    context = maintenance_context(host.engine, 't', 'u')
    assert context.to_filter()['max_trust_tier'] == host.engine.policy.max_trust_tier
    assert KnowledgeMaintenanceWorker(host.engine, context).run_once()['created'] == 1


@pytest.mark.parametrize('value,expected', [
    ('file:/work/My%20Project', '/work/My Project'),
    ('file:///work/Atlas', '/work/Atlas'),
    ('file://localhost/work/Atlas', '/work/Atlas'),
    ('file://remote/work/Atlas', None),
    ('file:/work/a%00b', None),
    ('file:/work/Atlas?token=private', None),
])
def test_local_workspace_uri_is_normalized_without_accepting_remote_paths(value, expected):
    from mnemosyne.local_paths import normalize_workspace
    assert normalize_workspace(value) == expected
